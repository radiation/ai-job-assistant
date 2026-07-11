# ruff: noqa: E501
from __future__ import annotations

from io import BytesIO

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter

from ai_job_finder.application.extraction import (
    ExtractedCareerFactProposal,
    ExtractedDocument,
    chunk_extracted_document,
    excerpt_is_grounded,
)
from ai_job_finder.domain.document_ingestion import ensure_valid_proposal_transition
from ai_job_finder.domain.enums import (
    CareerFactProposalReviewStatus,
    SourceDocumentType,
)
from ai_job_finder.domain.errors import DocumentExtractionError, InvalidProposalTransitionError
from ai_job_finder.infrastructure.llm.fake import FakeCareerFactExtractor
from ai_job_finder.infrastructure.storage import LocalDocumentStorage, sanitize_filename
from ai_job_finder.infrastructure.text_extraction import extract_text_from_document


def _text_pdf_bytes() -> bytes:
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length 69 >>
stream
BT /F1 12 Tf 72 720 Td (Led platform work with Kubernetes.) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000241 00000 n
0000000311 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
430
%%EOF
"""


def test_sanitize_filename_removes_path_segments() -> None:
    assert sanitize_filename("../../resume final.txt") == "resume-final.txt"


def test_local_storage_rejects_unsafe_read_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = LocalDocumentStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.read("../outside.txt")


def test_plain_text_extraction_requires_utf8() -> None:
    extracted = extract_text_from_document(
        filename="notes.txt",
        content_type="text/plain",
        content=b"Led platform work.\r\n\r\nUsed Kubernetes.",
    )
    assert "Led platform work." in extracted.text

    with pytest.raises(DocumentExtractionError):
        extract_text_from_document(filename="bad.txt", content_type="text/plain", content=b"\xff")


def test_pdf_text_extraction_and_blank_pdf_failure() -> None:
    extracted = extract_text_from_document(
        filename="resume.pdf",
        content_type="application/pdf",
        content=_text_pdf_bytes(),
    )
    assert "Page 1" in extracted.text
    assert "Kubernetes" in extracted.text

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(DocumentExtractionError):
        extract_text_from_document(
            filename="scan.pdf",
            content_type="application/pdf",
            content=buffer.getvalue(),
        )


def test_chunking_preserves_page_locations() -> None:
    chunks = chunk_extracted_document(
        "--- Page 1 ---\nA" * 200 + "\n--- Page 2 ---\nB" * 200,
        max_characters=500,
    )
    assert chunks
    assert any("page" in chunk.source_location for chunk in chunks)


def test_chunking_returns_full_chunk_list() -> None:
    chunks = chunk_extracted_document(
        "One paragraph.\n\nTwo paragraph.\n\nThree paragraph.\n\nFour paragraph.",
        max_characters=20,
    )

    assert len(chunks) == 4


def test_structured_output_rejects_bad_tags_and_null_lists() -> None:
    with pytest.raises(ValidationError):
        ExtractedCareerFactProposal.model_validate(
            {
                "statement": "Led platform work",
                "category": "platform",
                "technologies": None,
                "evidence_tags": ["not_a_tag"],
                "supporting_excerpt": "Led platform work",
                "confidence": 0.8,
            }
        )


def test_excerpt_grounding_exact_match() -> None:
    text = "Led platform work with Kubernetes."
    assert excerpt_is_grounded(text, "platform work with Kubernetes")


def test_excerpt_grounding_normalizes_whitespace_and_line_wraps() -> None:
    text = "Led platform work\nwith Kubernetes and developer productivity improvements."
    assert excerpt_is_grounded(
        text,
        "platform work with Kubernetes and developer productivity improvements",
    )


def test_excerpt_grounding_normalizes_pdf_hyphenation() -> None:
    text = "Delivered plat-\nform migrations across teams."
    assert excerpt_is_grounded(text, "Delivered platform migrations across teams")


def test_excerpt_grounding_normalizes_conservative_punctuation() -> None:
    text = "Led “platform enablement,” improving developer productivity."
    assert excerpt_is_grounded(text, 'Led "platform enablement" improving developer productivity')


def test_excerpt_grounding_rejects_paraphrases_and_token_overlap_only() -> None:
    text = "Built platform workflows. Improved reliability with Kubernetes automation."
    assert not excerpt_is_grounded(text, "managed a sales team")
    assert not excerpt_is_grounded(text, "Improved platform automation workflows reliability")


def test_fake_extractor_returns_grounded_excerpt() -> None:
    text = "Led platform work with Kubernetes."

    result = FakeCareerFactExtractor().extract(
        ExtractedDocument(
            text=text,
            source_type=SourceDocumentType.RESUME,
            source_location="document",
        )
    )
    assert result.provider == "fake"
    assert result.proposals[0].supporting_excerpt in text


def test_proposal_lifecycle_rejects_terminal_transition() -> None:
    ensure_valid_proposal_transition(
        CareerFactProposalReviewStatus.PENDING,
        CareerFactProposalReviewStatus.ACCEPTED,
    )
    with pytest.raises(InvalidProposalTransitionError):
        ensure_valid_proposal_transition(
            CareerFactProposalReviewStatus.ACCEPTED,
            CareerFactProposalReviewStatus.REJECTED,
        )
