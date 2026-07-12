from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError

from ai_job_finder.domain.errors import DomainError
from ai_job_finder.web.dependencies import render_template


def _is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> Response:
        status_code_by_code = {
            "not_found": 404,
            "unsupported_document_type": 415,
            "document_too_large": 413,
            "duplicate_source_document": 409,
            "document_extraction_failed": 422,
            "document_extraction_limit_exceeded": 422,
            "extraction_provider_unavailable": 503,
            "malformed_extraction_output": 502,
            "invalid_proposal_edit": 422,
            "invalid_proposal_transition": 409,
            "merge_target_mismatch": 409,
            "duplicate_job_source": 409,
            "invalid_job_source": 422,
            "job_source_disabled": 409,
            "job_source_provider_failure": 502,
            "job_source_timeout": 504,
            "malformed_job_source_payload": 502,
            "suspicious_empty_job_source_result": 409,
            "overlapping_job_import": 409,
            "missing_candidate": 409,
        }
        status_code = status_code_by_code.get(exc.code, 409)
        if not _is_api_request(request):
            return render_template(
                request,
                "errors/error.html",
                {
                    "page_title": "Request Error",
                    "title": "Request error",
                    "message": str(exc),
                },
                status_code=status_code,
            )
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": exc.code, "message": str(exc), "details": None}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        if not _is_api_request(request):
            return render_template(
                request,
                "errors/error.html",
                {
                    "page_title": "Validation Error",
                    "title": "Validation error",
                    "message": "The submitted request was invalid.",
                },
                status_code=422,
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> Response:
        if not _is_api_request(request):
            return render_template(
                request,
                "errors/error.html",
                {
                    "page_title": "Conflict",
                    "title": "Conflict",
                    "message": "A database constraint was violated.",
                },
                status_code=409,
            )
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "integrity_error",
                    "message": "A database constraint was violated.",
                    "details": str(exc.orig),
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _: Exception) -> Response:
        if _is_api_request(request):
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "internal_server_error",
                        "message": "An unexpected server error occurred.",
                        "details": None,
                    }
                },
            )
        return render_template(
            request,
            "errors/error.html",
            {
                "page_title": "Server Error",
                "title": "Server error",
                "message": "An unexpected server error occurred.",
            },
            status_code=500,
        )
