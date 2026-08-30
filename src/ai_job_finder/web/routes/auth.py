from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ai_job_finder.settings import get_settings
from ai_job_finder.web.dependencies import render_template

router = APIRouter(tags=["web"])


@router.get("/sign-in")
def sign_in(request: Request) -> Response:
    settings = get_settings()
    return render_template(
        request,
        "auth/sign_in.html",
        {
            "page_title": "Sign In",
            "firebase_web_api_key": settings.firebase_web_api_key,
            "firebase_web_auth_domain": settings.firebase_web_auth_domain,
            "firebase_web_app_id": settings.firebase_web_app_id,
            "firebase_project_id": settings.identity_platform_project_id,
            "firebase_tenant_id": settings.identity_platform_tenant_id,
        },
    )
