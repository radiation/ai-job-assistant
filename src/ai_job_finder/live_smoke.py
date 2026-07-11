from __future__ import annotations

import os

from ai_job_finder.application.extraction import ExtractedDocument
from ai_job_finder.domain.enums import SourceDocumentType
from ai_job_finder.infrastructure.llm.vertex import VertexGeminiCareerFactExtractor
from ai_job_finder.settings import get_settings


def main() -> int:
    if os.environ.get("AI_JOB_FINDER_RUN_VERTEX_SMOKE") != "true":
        print("Skipped. Set AI_JOB_FINDER_RUN_VERTEX_SMOKE=true to run a live Vertex call.")
        return 0
    settings = get_settings()
    if not settings.vertex_project or not settings.vertex_region:
        print("Vertex smoke test requires VERTEX_PROJECT and VERTEX_REGION.")
        return 1
    extractor = VertexGeminiCareerFactExtractor(
        project=settings.vertex_project,
        region=settings.vertex_region,
        model_id=settings.vertex_gemini_model_id,
        prompt_version=settings.extraction_prompt_version,
        schema_version=settings.extraction_schema_version,
        temperature=settings.extraction_temperature,
        timeout_seconds=settings.extraction_timeout_seconds,
    )
    result = extractor.extract(
        ExtractedDocument(
            text=(
                "Led a platform engineering program that standardized Kubernetes, CI/CD, "
                "and observability across product teams, reducing release coordination toil by 27%."
            ),
            source_type=SourceDocumentType.CAREER_NOTES,
            source_location="live smoke fixture",
        )
    )
    print(f"model={result.model_id}")
    print(f"prompt_version={result.prompt_version}")
    print(f"input_tokens={result.input_token_count}")
    print(f"output_tokens={result.output_token_count}")
    print(f"proposal_count={len(result.proposals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
