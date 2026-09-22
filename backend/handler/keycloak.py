import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import delete, select

from ..db.domain.models import OIDCFlow, OIDCSession


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class KeycloakSettings:
    url: str
    realm: str
    client_id: str
    client_secret: str
    app_url: str
    session_key: str
    role_scope: str = "client"
    admin_role: str = "admin"
    user_role: str = "user"
    admin_client_id: str = ""
    admin_client_secret: str = ""

    @classmethod
    def from_env(cls):
        required = ["KEYCLOAK_URL", "KEYCLOAK_REALM", "KEYCLOAK_CLIENT_ID", "KEYCLOAK_CLIENT_SECRET", "APP_PUBLIC_URL", "KEYCLOAK_SESSION_KEY"]
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            raise RuntimeError("Для Keycloak задайте: " + ", ".join(missing))
        for name in ("KEYCLOAK_URL", "APP_PUBLIC_URL"):
            parts = urlsplit(os.environ[name])
            if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or (parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"})):
                raise RuntimeError(f"{name}: нужен HTTPS URL (HTTP допустим только на localhost)")
            if name == "APP_PUBLIC_URL" and parts.path not in {"", "/"}:
                raise RuntimeError("APP_PUBLIC_URL: укажите адрес интерфейса без пути")
        scope = os.getenv("KEYCLOAK_ROLE_SCOPE") or "client"
        if scope not in {"client", "realm"}:
            raise RuntimeError("KEYCLOAK_ROLE_SCOPE: client или realm")
        settings = cls(*(os.environ[name].strip().rstrip("/") if name in {"KEYCLOAK_URL", "APP_PUBLIC_URL"} else os.environ[name].strip() for name in required), role_scope=scope, admin_role=os.getenv("KEYCLOAK_ADMIN_ROLE") or "admin", user_role=os.getenv("KEYCLOAK_USER_ROLE") or "user", admin_client_id=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", ""), admin_client_secret=os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", ""))
        if settings.admin_role == settings.user_role:
            raise RuntimeError("Роли admin и user должны различаться")
        Fernet(settings.session_key.encode())
        return settings

    @property
    def issuer(self):
        return f"{self.url}/realms/{quote(self.realm, safe='')}"

    @property
    def callback(self):
        return self.app_url + "/api/auth/keycloak/callback"


class Keycloak:
    def __init__(self, settings, sessions, transport=None):
        self.settings, self.sessions = settings, sessions
        self.http = httpx.Client(timeout=httpx.Timeout(15, connect=5), transport=transport, follow_redirects=False)
        self.cipher = Fernet(settings.session_key.encode())
        self.keys, self.keys_until = [], 0

    def close(self):
        self.http.close()

    def encode(self, data):
        return self.cipher.encrypt(json.dumps(data).encode()).decode()

    def decode(self, value):
        try:
            return json.loads(self.cipher.decrypt(value.encode()))
        except (InvalidToken, ValueError) as error:
            raise HTTPException(401, "Сессия недействительна. Войдите снова") from error

    def endpoint(self, path):
        return self.settings.issuer + "/protocol/openid-connect/" + path

    def request(self, method, url, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise HTTPException(503, "Keycloak недоступен") from error
        if not response.is_success:
            status = response.status_code
            raise HTTPException(401 if status == 401 else 409 if status == 409 else 403 if status == 403 else 400 if status == 400 else 503, f"Keycloak отклонил запрос (HTTP {status})")
        return response

    def credentials(self):
        return {"client_id": self.settings.client_id, "client_secret": self.settings.client_secret}

    def validate(self, token, identity=False):
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise ValueError("Unexpected algorithm")
            kid = header.get("kid")
            if time.time() >= self.keys_until or not any(key.get("kid") == kid for key in self.keys):
                self.keys = self.request("GET", self.endpoint("certs")).json()["keys"]
                self.keys_until = time.time() + 300
            key = next(key for key in self.keys if key.get("kid") == kid)
            claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"], issuer=self.settings.issuer, audience=self.settings.client_id if identity else None, options={"require":["exp", "iat", "sub", "iss"], "verify_aud": identity}, leeway=5)
            if (not identity or "azp" in claims) and claims.get("azp") != self.settings.client_id:
                raise ValueError("Unexpected client")
            if identity and isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1 and "azp" not in claims:
                raise ValueError("Missing authorized party")
            if not isinstance(claims.get("sub"), str) or not claims["sub"]:
                raise ValueError("Missing subject")
            return claims
        except (jwt.PyJWTError, ValueError, KeyError, StopIteration, TypeError) as error:
            raise HTTPException(401, "Некорректный токен Keycloak") from error

    def role(self, claims):
        try:
            roles = claims.get("realm_access", {}).get("roles", []) if self.settings.role_scope == "realm" else claims.get("resource_access", {}).get(self.settings.client_id, {}).get("roles", [])
        except (AttributeError, TypeError):
            raise HTTPException(403, "Некорректный набор ролей Keycloak")
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise HTTPException(403, "Некорректный набор ролей Keycloak")
        if self.settings.admin_role in roles:
            return "admin"
        if self.settings.user_role in roles:
            return "user"
        raise HTTPException(403, "В Keycloak не назначена роль приложения")

    def start(self):
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with self.sessions.begin() as session:
            session.execute(delete(OIDCFlow).where(OIDCFlow.expires_at <= time.time()))
            session.execute(delete(OIDCSession).where(OIDCSession.expires_at <= time.time()))
            session.add(OIDCFlow(id=digest(state), payload=self.encode({"nonce":nonce, "verifier":verifier}), expires_at=time.time()+300))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        query = urlencode({"client_id":self.settings.client_id, "redirect_uri":self.settings.callback, "response_type":"code", "scope":"openid profile email", "state":state, "nonce":nonce, "code_challenge":challenge, "code_challenge_method":"S256"})
        return self.endpoint("auth") + "?" + query, state

    def callback(self, code, state, cookie):
        if not state or not cookie or not secrets.compare_digest(state, cookie):
            raise HTTPException(400, "Проверка состояния входа не пройдена")
        with self.sessions.begin() as session:
            flow = session.scalar(select(OIDCFlow).where(OIDCFlow.id == digest(state)).with_for_update())
            if flow is None or flow.expires_at <= time.time():
                raise HTTPException(400, "Запрос входа истёк или уже использован")
            data = self.decode(flow.payload)
            session.delete(flow)
        tokens = self.request("POST", self.endpoint("token"), data={**self.credentials(), "grant_type":"authorization_code", "code":code, "redirect_uri":self.settings.callback, "code_verifier":data["verifier"]}).json()
        identity = self.validate(tokens.get("id_token"), identity=True)
        if not secrets.compare_digest(str(identity.get("nonce", "")), data["nonce"]):
            raise HTTPException(401, "Некорректный nonce Keycloak")
        claims = self.validate(tokens.get("access_token"))
        if claims["sub"] != identity["sub"]:
            raise HTTPException(401, "Токены относятся к разным пользователям")
        self.role(claims)
        if not tokens.get("refresh_token"):
            raise HTTPException(401, "Keycloak не вернул refresh token")
        cookie = secrets.token_urlsafe(32)
        tokens.update(checked_at=time.time(), access_expires_at=claims["exp"], identity=identity)
        with self.sessions.begin() as session:
            session.add(OIDCSession(id=digest(cookie), subject=claims["sub"], payload=self.encode(tokens), expires_at=time.time()+43200))
        return cookie

    def authenticate(self, cookie):
        with self.sessions() as session:
            row = session.get(OIDCSession, digest(cookie))
            if row is None or row.expires_at <= time.time():
                raise HTTPException(401, "Требуется вход через Keycloak")
            payload, subject = row.payload, row.subject
        tokens = self.decode(payload)
        if time.time() - tokens["checked_at"] >= 60 or tokens.get("access_expires_at", 0) <= time.time() + 10:
            try:
                # A row lock serializes refresh-token rotation across backend replicas.
                # Only this short, bounded authentication request holds the lock.
                with self.sessions.begin() as session:
                    row = session.scalar(select(OIDCSession).where(OIDCSession.id == digest(cookie)).with_for_update())
                    if row is None or row.expires_at <= time.time():
                        raise HTTPException(401, "Сессия завершена")
                    tokens = self.decode(row.payload)
                    if time.time() - tokens["checked_at"] >= 60 or tokens.get("access_expires_at", 0) <= time.time() + 10:
                        refreshed = self.request("POST", self.endpoint("token"), data={**self.credentials(), "grant_type":"refresh_token", "refresh_token":tokens["refresh_token"]}).json()
                        claims = self.validate(refreshed.get("access_token"))
                        if claims["sub"] != subject:
                            raise HTTPException(401, "Пользователь сессии изменился")
                        tokens.update(refreshed, checked_at=time.time(), access_expires_at=claims["exp"])
                        row.payload = self.encode(tokens)
            except HTTPException as error:
                if error.status_code in {400, 401}:
                    raise HTTPException(401, "Войдите через Keycloak снова") from error
                raise
        claims = self.validate(tokens.get("access_token"))
        active = self.request("POST", self.endpoint("token/introspect"), data={**self.credentials(), "token":tokens["access_token"]}).json()
        if active.get("active") is not True:
            self.revoke(cookie)
            raise HTTPException(401, "Сессия Keycloak завершена")
        info = tokens["identity"]
        return {"id":subject, "login":info.get("preferred_username", subject), "name":info.get("name") or info.get("preferred_username", subject), "role":self.role(claims), "status":"active", "is_bootstrap":False, "provider":"keycloak", "users_management":bool(self.settings.admin_client_id and self.settings.admin_client_secret)}

    def revoke(self, cookie):
        with self.sessions.begin() as session:
            row = session.get(OIDCSession, digest(cookie))
            payload = row.payload if row else None
            if row:
                session.delete(row)
        try:
            return self.decode(payload) if payload else {}
        except HTTPException:
            return {}

    def logout(self, cookie):
        tokens = self.revoke(cookie)
        query = {"client_id":self.settings.client_id, "post_logout_redirect_uri":self.settings.app_url + "/login"}
        if tokens.get("id_token"):
            query["id_token_hint"] = tokens["id_token"]
        return self.endpoint("logout") + "?" + urlencode(query)
