from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse

from ai_job_finder.api.dependencies import (
    job_source_connector_dependency,
    settings_dependency,
)
from ai_job_finder.application.job_imports import (
    get_job_import_run,
    get_job_source_configuration,
    run_job_source_import,
)
from ai_job_finder.domain.job_sources import JobSourceConnector
from ai_job_finder.settings import Settings
from ai_job_finder.web.dependencies import DbSession, render_template

router = APIRouter(tags=["web"])
SettingsDependency = Annotated[Settings, Depends(settings_dependency)]
JobSourceConnectorDependency = Annotated[
    JobSourceConnector, Depends(job_source_connector_dependency)
]


@router.post("/job-sources/{source_id}/sync")
def job_sources_sync(
    source_id: UUID,
    session: DbSession,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> Response:
    run = run_job_source_import(
        session,
        source_id=source_id,
        connector=connector,
        retain_raw_payload=settings.greenhouse_retain_raw_payload,
        close_on_empty=settings.greenhouse_close_on_empty_result,
        stale_after_seconds=settings.job_source_stale_after_seconds,
    )
    return RedirectResponse(
        url=f"/job-import-runs/{run.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/job-import-runs/{run_id}")
def job_import_run_detail(request: Request, run_id: UUID, session: DbSession) -> Response:
    run = get_job_import_run(session, run_id)
    source = get_job_source_configuration(session, run.source_configuration_id)
    return render_template(
        request,
        "job_sources/import_run.html",
        {"page_title": "Import Run", "run": run, "source": source},
    )
