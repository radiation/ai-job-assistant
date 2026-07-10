from __future__ import annotations

from fastapi import FastAPI

from ai_job_finder.api.errors import install_error_handlers
from ai_job_finder.api.v1.routes import router as v1_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Job Finder", version="0.1.0")
    install_error_handlers(app)
    app.include_router(v1_router)
    return app


app = create_app()
