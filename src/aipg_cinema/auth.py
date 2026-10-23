"""Hosted login API, deliberately separate from the single-user rendering app."""

import hmac
import json
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .core_accounts import CoreAccountError
from .resources import RequestLimitsMiddleware
from .sessions import (
    SESSION_SECONDS,
    AccountSessions,
    LoginCapacity,
    LoginFlow,
    SessionError,
    WorkspaceConflict,
)

LOGIN_COOKIE = "__Host-studio-login"
SESSION_COOKIE = "__Host-studio-session"
MAX_AUTH_BODY = 48 * 1024


def create_auth_app(
    accounts: AccountSessions, *, origin: str, google_client_id: str
) -> FastAPI:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.netloc != parsed.hostname
        or origin != f"https://{parsed.hostname}"
        or not origin.isascii()
        or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in origin)
    ):
        raise ValueError(
            "Configure one canonical HTTPS production origin without a port or path."
        )
    if (
        not google_client_id
        or len(google_client_id) > 255
        or not google_client_id.isascii()
        or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in google_client_id)
    ):
        raise ValueError("Configure a public Google OAuth client ID.")
    if accounts.origin != origin:
        raise ValueError("Wallet and HTTP sign-in origins must match.")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[parsed.hostname])

    @app.middleware("http")
    async def protect(request: Request, call_next):
        unsafe = request.method not in ("GET", "HEAD", "OPTIONS")
        if (
            request.headers.get("sec-fetch-site") == "cross-site"
            or (request.headers.get("origin") and request.headers["origin"] != origin)
            or (unsafe and request.headers.get("origin") != origin)
        ):
            response = JSONResponse(
                {"detail": "Use the Studio sign-in page."}, status_code=403
            )
        elif unsafe and request.url.path.startswith("/auth/"):
            if (
                request.headers.get("content-type", "")
                .partition(";")[0]
                .strip()
                .lower()
                != "application/json"
            ):
                response = JSONResponse(
                    {"detail": "Send a JSON sign-in request."}, status_code=415
                )
            else:
                payload = bytearray()
                too_large = False
                async for chunk in request.stream():
                    if len(payload) + len(chunk) > MAX_AUTH_BODY:
                        too_large = True
                        break
                    payload.extend(chunk)
                if too_large:
                    response = JSONResponse(
                        {"detail": "Sign-in request is too large."}, status_code=413
                    )
                else:
                    try:
                        body = json.loads(payload)
                        if not isinstance(body, dict):
                            raise TypeError
                    except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
                        response = JSONResponse(
                            {"detail": "Invalid sign-in request."}, status_code=400
                        )
                    else:
                        request.state.auth_body = body
                        response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        return response

    @app.exception_handler(SessionError)
    async def invalid_session(request, error):
        return JSONResponse({"detail": str(error)}, status_code=401)

    @app.exception_handler(CoreAccountError)
    async def core_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.exception_handler(WorkspaceConflict)
    async def workspace_conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(LoginCapacity)
    async def login_capacity(request, error):
        return JSONResponse(
            {"detail": str(error)},
            status_code=429,
            headers={"Retry-After": str(error.retry_after)},
        )

    def cookie(response, name, value, max_age):
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )

    def clear(response, name):
        response.delete_cookie(
            name, secure=True, httponly=True, samesite="lax", path="/"
        )

    def flow(request):
        pending = LoginFlow.from_cookie(request.cookies.get(LOGIN_COOKIE, ""))
        supplied = request.headers.get("x-studio-csrf", "")
        if (
            pending is None
            or not supplied.isascii()
            or not hmac.compare_digest(pending.csrf, supplied)
        ):
            raise SessionError()
        return pending

    def fields(request, names):
        body = request.state.auth_body
        if set(body) != set(names) or any(
            not isinstance(body[name], str) or not body[name] or len(body[name]) > 32768
            for name in names
        ):
            raise SessionError()
        return body

    def signed_in(session):
        response = JSONResponse(session.browser_state())
        cookie(response, SESSION_COOKIE, session.handle, SESSION_SECONDS)
        clear(response, LOGIN_COOKIE)
        return response

    @app.get("/auth/session")
    async def session(request: Request):
        handle = request.cookies.get(SESSION_COOKIE)
        if handle:
            try:
                current = await run_in_threadpool(accounts.resolve, handle)
            except SessionError:
                pass
            else:
                return JSONResponse(current.browser_state())
        pending = await run_in_threadpool(
            accounts.begin, LoginFlow.from_cookie(request.cookies.get(LOGIN_COOKIE, ""))
        )
        response = JSONResponse(
            {
                "authenticated": False,
                "csrf": pending.csrf,
                "google_client_id": google_client_id,
            }
        )
        cookie(response, LOGIN_COOKIE, pending.cookie(), pending.seconds)
        clear(response, SESSION_COOKIE)
        return response

    @app.post("/auth/google")
    async def google(request: Request):
        body = fields(request, ("id_token",))
        try:
            current = await run_in_threadpool(
                accounts.google, flow(request), body["id_token"]
            )
        except ValueError:
            raise SessionError() from None
        return signed_in(current)

    @app.post("/auth/wallet/challenge")
    async def wallet_challenge(request: Request):
        body = fields(request, ("address",))
        try:
            challenge = await run_in_threadpool(
                accounts.wallet_challenge, flow(request), body["address"]
            )
        except ValueError:
            raise SessionError() from None
        return JSONResponse(challenge)

    @app.post("/auth/wallet")
    async def wallet(request: Request):
        body = fields(request, ("signature",))
        try:
            current = await run_in_threadpool(
                accounts.wallet, flow(request), body["signature"]
            )
        except ValueError:
            raise SessionError() from None
        return signed_in(current)

    @app.post("/auth/logout")
    async def logout(request: Request):
        fields(request, ())
        await run_in_threadpool(
            accounts.logout,
            request.cookies.get(SESSION_COOKIE, ""),
            request.headers.get("x-studio-csrf", ""),
        )
        response = JSONResponse({"authenticated": False})
        clear(response, SESSION_COOKIE)
        clear(response, LOGIN_COOKIE)
        return response

    app.add_middleware(RequestLimitsMiddleware)
    return app
