from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ai_job_finder.api.errors import install_error_handlers
from ai_job_finder.api.v1.routes import router as v1_router
from ai_job_finder.web.routes import router as web_router

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "web" / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="AI Job Finder", version="0.1.0")
    install_error_handlers(app)
    app.include_router(v1_router)
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
