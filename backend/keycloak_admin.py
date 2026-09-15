import re
import time
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import delete

from .models import OIDCSession


class KeycloakAdmin:
    """Manage application membership without deleting shared Keycloak accounts."""

    def __init__(self, provider):
        self.kc = provider
        settings = provider.settings
        if not settings.admin_client_id or not settings.admin_client_secret:
            raise HTTPException(503, "Настройте сервисный клиент Keycloak для управления пользователями")
        self.base = f"{settings.url}/admin/realms/{quote(settings.realm, safe='')}"
        token = provider.request("POST", provider.endpoint("token"), data={"grant_type": "client_credentials", "client_id": settings.admin_client_id, "client_secret": settings.admin_client_secret}).json()["access_token"]
        self.headers = {"Authorization": "Bearer " + token}
        if settings.role_scope == "client":
            clients = self.call("GET", "/clients", params={"clientId": settings.client_id}).json()
            clients = [client for client in clients if client["clientId"] == settings.client_id]
            if len(clients) != 1:
                raise HTTPException(503, "Клиент приложения не найден в Keycloak")
            self.scope = "/clients/" + quote(clients[0]["id"], safe="")
            self.mapping = "clients/" + quote(clients[0]["id"], safe="")
        else:
            self.scope, self.mapping = "", "realm"
        self.roles = {role: self.call("GET", self.scope + "/roles/" + quote(name, safe="")).json() for role, name in {"admin": settings.admin_role, "user": settings.user_role}.items()}
        if any(role.get("composite") for role in self.roles.values()):
            raise HTTPException(503, "Для управления доступом нужны отдельные, несоставные роли приложения")

    def call(self, method, path, **kwargs):
        return self.kc.request(method, self.base + path, headers=self.headers, **kwargs)

    def path(self, user_id):
        return "/users/" + quote(user_id, safe="") + "/role-mappings/" + self.mapping

    def membership(self, user_id):
        direct = self.call("GET", self.path(user_id)).json()
        effective = self.call("GET", self.path(user_id) + "/composite").json()
        role_ids = {role["id"] for role in self.roles.values()}
        assigned = [role for role in direct if role["id"] in role_ids]
        effective_ids = {role["id"] for role in effective} & role_ids
        role = "admin" if self.roles["admin"]["id"] in effective_ids else "user" if effective_ids else None
        # Inherited roles are administered in Keycloak, where their groups/composites are visible.
        inherited = effective_ids - {role["id"] for role in assigned}
        return role, assigned, bool(inherited)

    def metadata(self, user, role, protected=False):
        return {"id": user["id"], "login": user.get("username", user["id"]), "name": " ".join(filter(None, [user.get("firstName"), user.get("lastName")])) or user.get("username", user["id"]), "role": role, "status": "active" if user.get("enabled") and not user.get("requiredActions") else "invited", "is_bootstrap": protected, "email": user.get("email", ""), "provider": "keycloak"}

    def users(self):
        result = []
        # Include group-derived memberships, but never expose unrelated realm users.
        for first in range(0, 10000, 100):
            page = self.call("GET", "/users", params={"first": first, "max": 100, "briefRepresentation": "false"}).json()
            for user in page:
                role, _, inherited = self.membership(user["id"])
                if role:
                    result.append(self.metadata(user, role, inherited))
            if len(page) < 100:
                return sorted(result, key=lambda user: user["login"].casefold())
        raise HTTPException(503, "В realm слишком много пользователей; используйте управление доступом в Keycloak")

    def invite(self, login, name, email, role):
        login, name, email = login.strip(), name.strip(), email.strip()
        if not login or not name or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise HTTPException(422, "Укажите имя, логин и корректный email")
        found = self.call("GET", "/users", params={"username": login, "exact": "true"}).json()
        if found:
            user = found[0]
            if user.get("email", "").casefold() != email.casefold():
                raise HTTPException(409, "Логин уже занят другой учётной записью")
            current, _, _ = self.membership(user["id"])
            if current:
                raise HTTPException(409, "У пользователя уже есть доступ к приложению")
            actions = ["VERIFY_EMAIL"]
        else:
            response = self.call("POST", "/users", json={"username": login, "firstName": name, "email": email, "enabled": True, "emailVerified": False, "requiredActions": ["UPDATE_PASSWORD", "VERIFY_EMAIL"]})
            user_id = response.headers.get("Location", "").rstrip("/").rsplit("/", 1)[-1]
            if not user_id:
                raise HTTPException(503, "Keycloak не вернул идентификатор пользователя")
            user = self.call("GET", "/users/" + quote(user_id, safe="")).json()
            actions = ["UPDATE_PASSWORD", "VERIFY_EMAIL"]
        assignment = [self.roles[role]]
        self.call("POST", self.path(user["id"]), json=assignment)
        try:
            self.call("PUT", "/users/" + quote(user["id"], safe="") + "/execute-actions-email", params={"client_id": self.kc.settings.client_id, "redirect_uri": self.kc.settings.app_url + "/login", "lifespan": 259200}, json=actions)
        except HTTPException:
            self.call("DELETE", self.path(user["id"]), json=assignment)
            raise
        return {"user": self.metadata(user, role), "emailSent": True}

    def change(self, user_id, actor, role=None):
        if actor == user_id:
            raise HTTPException(409, "Нельзя изменять свою роль или удалять себя")
        current, assigned, inherited = self.membership(user_id)
        if not current:
            raise HTTPException(404, "Пользователь приложения не найден")
        if inherited:
            raise HTTPException(409, "Доступ наследуется от группы или составной роли. Измените его в Keycloak")
        if current == "admin" and role != "admin" and len([user for user in self.users() if user["role"] == "admin"]) < 2:
            raise HTTPException(409, "Нельзя убрать последнего администратора")
        if role == current:
            user = self.call("GET", "/users/" + quote(user_id, safe="")).json()
            return {"user": self.metadata(user, role)}
        # Remove the old role first: failures cannot accidentally retain elevated access.
        if assigned:
            self.call("DELETE", self.path(user_id), json=assigned)
        with self.kc.sessions.begin() as session:
            session.execute(delete(OIDCSession).where(OIDCSession.subject == user_id))
        if role:
            self.call("POST", self.path(user_id), json=[self.roles[role]])
            user = self.call("GET", "/users/" + quote(user_id, safe="")).json()
            return {"user": self.metadata(user, role)}
        return {"status": "ok"}
