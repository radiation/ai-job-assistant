from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_job_finder.domain.enums import CareerFactCategory, EvidenceTag, SourceDocumentType

PUNCTUATION_TRANSLATION_TABLE = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    source_type: SourceDocumentType
    source_location: str


class ExtractedCareerFactProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    category: CareerFactCategory
    source_organization: str | None = None
    metric: str | None = None
    technologies: list[str] = Field(default_factory=list)
    leadership_scope: str | None = None
    business_outcome: str | None = None
    approved_wording: str | None = None
    evidence_tags: list[EvidenceTag] = Field(default_factory=list)
    supporting_excerpt: str = Field(min_length=1)
    source_location: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("technologies", mode="before")
    @classmethod
    def reject_null_technologies(cls, value: object) -> object:
        if value is None:
            msg = "technologies must be an empty list, not null"
            raise ValueError(msg)
        return value

    @field_validator("evidence_tags", mode="before")
    @classmethod
    def reject_null_evidence_tags(cls, value: object) -> object:
        if value is None:
            msg = "evidence_tags must be an empty list, not null"
            raise ValueError(msg)
        return value


class CareerFactExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str
    prompt_version: str
    schema_version: str
    temperature: float
    proposals: list[ExtractedCareerFactProposal] = Field(default_factory=list)
    raw_response: str | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None


class CareerFactExtractor(Protocol):
    provider: str
    model_id: str
    prompt_version: str
    schema_version: str
    temperature: float

    def extract(self, document: ExtractedDocument) -> CareerFactExtractionResult: ...


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    text: str
    source_location: str


def normalize_text_for_matching(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(PUNCTUATION_TRANSLATION_TABLE)
    normalized = re.sub(r"\r\n?", "\n", normalized)
    normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", normalized)
    normalized = re.sub(r"[\t\n\r]+", " ", normalized)
    normalized = re.sub(r"[^\w\s.%+#/&-]+", " ", normalized.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def excerpt_is_grounded(source_text: str, excerpt: str) -> bool:
    normalized_source = normalize_text_for_matching(source_text)
    normalized_excerpt = normalize_text_for_matching(excerpt)
    if not normalized_excerpt:
        return False
    return normalized_excerpt in normalized_source


def proposal_fingerprint(proposal: ExtractedCareerFactProposal) -> str:
    organization = normalize_text_for_matching(proposal.source_organization or "")
    statement = normalize_text_for_matching(proposal.statement)
    metric = normalize_text_for_matching(proposal.metric or "")
    technologies = ",".join(
        sorted(normalize_text_for_matching(item) for item in proposal.technologies)
    )
    tags = ",".join(sorted(tag.value for tag in proposal.evidence_tags))
    return "|".join([proposal.category.value, organization, statement, metric, technologies, tags])


def chunk_extracted_document(
    text: str,
    *,
    max_characters: int,
) -> list[DocumentChunk]:
    normalized_text = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized_text:
        return []
    if len(normalized_text) <= max_characters:
        return [DocumentChunk(text=normalized_text, source_location="document")]

    page_parts = re.split(r"(?m)^--- Page (\d+) ---$", normalized_text)
    sections: list[DocumentChunk] = []
    if len(page_parts) > 1:
        preamble = page_parts[0].strip()
        if preamble:
            sections.append(DocumentChunk(text=preamble, source_location="document preamble"))
        for index in range(1, len(page_parts), 2):
            page_number = page_parts[index]
            page_text = page_parts[index + 1].strip()
            if page_text:
                sections.append(
                    DocumentChunk(text=page_text, source_location=f"page {page_number}")
                )
    else:
        sections = [
            DocumentChunk(text=part.strip(), source_location="document")
            for part in re.split(r"\n{2,}", normalized_text)
            if part.strip()
        ]

    chunks: list[DocumentChunk] = []
    current_parts: list[str] = []
    current_locations: list[str] = []
    current_length = 0
    for section in sections:
        if current_parts and current_length + len(section.text) + 2 > max_characters:
            chunks.append(
                DocumentChunk(
                    text="\n\n".join(current_parts),
                    source_location=", ".join(current_locations),
                )
            )
            current_parts = []
            current_locations = []
            current_length = 0
        if len(section.text) > max_characters:
            for start in range(0, len(section.text), max_characters):
                chunks.append(
                    DocumentChunk(
                        text=section.text[start : start + max_characters],
                        source_location=section.source_location,
                    )
                )
        else:
            current_parts.append(section.text)
            current_locations.append(section.source_location)
            current_length += len(section.text) + 2
    if current_parts:
        chunks.append(
            DocumentChunk(
                text="\n\n".join(current_parts),
                source_location=", ".join(current_locations),
            )
        )
    return chunks
