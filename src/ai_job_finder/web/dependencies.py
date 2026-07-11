from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ai_job_finder.api.dependencies import db_session_dependency
from ai_job_finder.infrastructure.database.models import JobEvaluationModel

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.auto_reload = True


def _humanize(value: str) -> str:
    return value.replace("_", " ").title()


def _format_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M %Z")


templates.env.filters["humanize"] = _humanize
templates.env.filters["datetime"] = _format_datetime

DbSession = Annotated[Session, Depends(db_session_dependency)]


def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request", "false").lower() == "true"


def latest_evaluation(job_evaluations: list[JobEvaluationModel]) -> JobEvaluationModel | None:
    if not job_evaluations:
        return None
    return max(job_evaluations, key=lambda evaluation: evaluation.evaluated_at)


def render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> Response:
    merged_context = {"request": request, **context}
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=merged_context,
        status_code=status_code,
    )


def optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def split_multivalue(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,]", value) if item.strip()]
