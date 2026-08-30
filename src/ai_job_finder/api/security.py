from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ai_job_finder.domain.errors import CsrfValidationError
from ai_job_finder.settings import get_settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CsrfCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        settings = get_settings()
        if request.cookies.get(settings.csrf_cookie_name) is None:
            response.set_cookie(
                key=settings.csrf_cookie_name,
                value=secrets.token_urlsafe(32),
                secure=settings.csrf_cookie_secure,
                httponly=False,
                samesite="lax",
                path="/",
            )
        return response


async def csrf_protection_dependency(request: Request) -> None:
    if request.method not in UNSAFE_METHODS:
        return

    settings = get_settings()
    expected_token = request.cookies.get(settings.csrf_cookie_name)
    supplied_token = request.headers.get("X-CSRF-Token")
    if supplied_token is None:
        form = await request.form()
        form_token = form.get("csrf_token")
        supplied_token = form_token if isinstance(form_token, str) else None

    if (
        expected_token is None
        or supplied_token is None
        or not hmac.compare_digest(expected_token, supplied_token)
    ):
        raise CsrfValidationError("CSRF validation failed.")
