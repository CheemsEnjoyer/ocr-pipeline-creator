from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from ..access import COOKIE, public

router = APIRouter(tags=["Авторизация"])
STATE_COOKIE = "ocr_oidc_state"


def provider(request):
    if request.app.state.auth_provider != "keycloak":
        raise HTTPException(404, "Keycloak не включён")
    return request.app.state.keycloak


@router.get("/api/auth/config", dependencies=[Depends(public)])
def configuration(request: Request):
    return {"provider": request.app.state.auth_provider, "loginUrl": "/api/auth/keycloak/login"}


@router.get("/api/auth/keycloak/login", dependencies=[Depends(public)])
def begin_session(request: Request):
    kc = provider(request)
    url, state = kc.start()
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(STATE_COOKIE, state, max_age=300, httponly=True, samesite="lax", secure=kc.settings.app_url.startswith("https://"), path="/api/auth/keycloak")
    return response


@router.get("/api/auth/keycloak/callback", dependencies=[Depends(public)])
def callback(request: Request, code: str = Query(min_length=1, max_length=4096), state: str = Query(min_length=1, max_length=512)):
    kc = provider(request)
    token = kc.callback(code, state, request.cookies.get(STATE_COOKIE))
    previous = request.cookies.get(COOKIE)
    if previous:
        kc.revoke(previous)
    response = RedirectResponse(kc.settings.app_url + "/", status_code=302)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/keycloak", httponly=True, samesite="lax", secure=kc.settings.app_url.startswith("https://"))
    response.set_cookie(COOKIE, token, max_age=43200, httponly=True, samesite="lax", secure=kc.settings.app_url.startswith("https://"), path="/")
    return response


def end_session(request, response):
    kc = provider(request)
    origin = request.headers.get("origin")
    public_url = urlsplit(kc.settings.app_url)
    if origin and origin != f"{public_url.scheme}://{public_url.netloc}":
        raise HTTPException(403, "Недопустимый источник запроса")
    url = kc.logout(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=kc.settings.app_url.startswith("https://"))
    return {"status": "ok", "logoutUrl": url}


@router.post("/api/auth/keycloak/logout", dependencies=[Depends(public)])
def logout(request: Request, response: Response):
    return end_session(request, response)
