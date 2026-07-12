from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_job_finder.application.extraction import (
    CareerFactExtractionResult,
    ExtractedCareerFactProposal,
    ExtractedDocument,
)
from ai_job_finder.domain.enums import CareerFactCategory, EvidenceTag
from ai_job_finder.domain.errors import (
    ExtractionProviderUnavailableError,
    MalformedExtractionOutputError,
)

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


class _VertexExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[ExtractedCareerFactProposal] = Field(default_factory=list)


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": [item.value for item in CareerFactCategory],
                        },
                        "source_organization": {"type": "string", "nullable": True},
                        "metric": {"type": "string", "nullable": True},
                        "technologies": {"type": "array", "items": {"type": "string"}},
                        "leadership_scope": {"type": "string", "nullable": True},
                        "business_outcome": {"type": "string", "nullable": True},
                        "approved_wording": {"type": "string", "nullable": True},
                        "evidence_tags": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [item.value for item in EvidenceTag],
                            },
                        },
                        "supporting_excerpt": {"type": "string"},
                        "source_location": {"type": "string", "nullable": True},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "statement",
                        "category",
                        "technologies",
                        "evidence_tags",
                        "supporting_excerpt",
                        "confidence",
                    ],
                },
            }
        },
        "required": ["proposals"],
    }


class VertexGeminiCareerFactExtractor:
    provider = "vertex_gemini"

    def __init__(
        self,
        *,
        project: str,
        region: str,
        model_id: str,
        prompt_version: str,
        schema_version: str,
        temperature: float,
        timeout_seconds: float,
    ) -> None:
        self.project = project
        self.region = region
        self.model_id = model_id
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds

    def extract(self, document: ExtractedDocument) -> CareerFactExtractionResult:
        if not self.project or not self.region:
            msg = "Vertex project and region are required for extraction."
            raise ExtractionProviderUnavailableError(msg)
        try:
            import vertexai
            from vertexai.generative_models import GenerationConfig, GenerativeModel
        except ImportError as exc:
            msg = "google-cloud-aiplatform is not installed."
            raise ExtractionProviderUnavailableError(msg) from exc

        prompt = (PROMPT_DIR / f"{self.prompt_version}.md").read_text(encoding="utf-8")
        vertexai.init(project=self.project, location=self.region)
        model = GenerativeModel(self.model_id)
        generation_config = GenerationConfig(
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=_response_schema(),
        )
        request_text = (
            f"{prompt}\n\n"
            f"Source type: {document.source_type.value}\n"
            f"Source location: {document.source_location}\n\n"
            "Document text:\n"
            f"{document.text}"
        )
        try:
            response = cast(Any, model).generate_content(
                request_text,
                generation_config=generation_config,
            )
        except Exception as exc:
            msg = f"Vertex Gemini extraction failed: {exc}"
            raise ExtractionProviderUnavailableError(msg) from exc

        raw_text = getattr(response, "text", "") or ""
        usage_metadata = getattr(response, "usage_metadata", None)
        try:
            payload = _VertexExtractionPayload.model_validate_json(raw_text)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            msg = "Vertex Gemini returned malformed extraction output."
            raise MalformedExtractionOutputError(msg) from exc
        return CareerFactExtractionResult(
            provider=self.provider,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            temperature=self.temperature,
            proposals=payload.proposals,
            raw_response=raw_text[:20000],
            input_token_count=getattr(usage_metadata, "prompt_token_count", None),
            output_token_count=getattr(usage_metadata, "candidates_token_count", None),
        )
