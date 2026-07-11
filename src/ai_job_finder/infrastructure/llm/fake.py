from __future__ import annotations

from ai_job_finder.application.extraction import (
    CareerFactExtractionResult,
    ExtractedCareerFactProposal,
    ExtractedDocument,
)
from ai_job_finder.domain.enums import CareerFactCategory, EvidenceTag


class FakeCareerFactExtractor:
    provider = "fake"
    model_id = "fake-career-fact-extractor"

    def __init__(
        self,
        *,
        prompt_version: str = "career_fact_extraction_v1",
        schema_version: str = "career_fact_extraction_schema_v1",
        temperature: float = 0.0,
    ) -> None:
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.temperature = temperature

    def extract(self, document: ExtractedDocument) -> CareerFactExtractionResult:
        text = document.text.strip()
        proposals: list[ExtractedCareerFactProposal] = []
        if text:
            excerpt = text[: min(len(text), 300)]
            proposals.append(
                ExtractedCareerFactProposal(
                    statement="Built or led work explicitly described in the uploaded document.",
                    category=CareerFactCategory.PLATFORM,
                    source_organization=None,
                    metric=None,
                    technologies=[],
                    leadership_scope=None,
                    business_outcome=None,
                    approved_wording="Built or led documented platform work.",
                    evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING],
                    supporting_excerpt=excerpt,
                    source_location=document.source_location,
                    confidence=0.5,
                )
            )
        return CareerFactExtractionResult(
            provider=self.provider,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            temperature=self.temperature,
            proposals=proposals,
            raw_response=None,
            input_token_count=None,
            output_token_count=None,
        )
