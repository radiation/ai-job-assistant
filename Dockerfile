FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "uvicorn", "ai_job_finder.main:app", "--host", "0.0.0.0", "--port", "8000"]
