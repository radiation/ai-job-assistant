from __future__ import annotations

import pytest

from ai_job_finder.application.extraction import ExtractedCareerFactProposal
from ai_job_finder.domain.enums import EVIDENCE_TAG_DISPLAY_NAMES, EvidenceTag


@pytest.mark.parametrize(
    ("legacy_label", "canonical_tag", "display_name"),
    [
        ("Manager Of Managers", EvidenceTag.MANAGER_OF_MANAGERS, "Manager of Managers"),
        ("Ml Platform", EvidenceTag.ML_PLATFORM, "ML Platform"),
        ("P And L", EvidenceTag.P_AND_L, "P&L"),
        ("P&L", EvidenceTag.P_AND_L, "P&L"),
        ("Ci Cd", EvidenceTag.CI_CD, "CI/CD"),
        ("CI/CD", EvidenceTag.CI_CD, "CI/CD"),
    ],
)
def test_evidence_tag_normalizes_legacy_labels(
    legacy_label: str,
    canonical_tag: EvidenceTag,
    display_name: str,
) -> None:
    assert EvidenceTag(legacy_label) is canonical_tag
    assert canonical_tag.display_name == display_name


def test_evidence_tag_display_name_falls_back_when_mapping_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(EVIDENCE_TAG_DISPLAY_NAMES, EvidenceTag.AI_PLATFORM)

    assert EvidenceTag.AI_PLATFORM.display_name == "Ai Platform"


def test_extraction_accepts_multiple_specific_ai_capabilities() -> None:
    proposal = ExtractedCareerFactProposal.model_validate(
        {
            "statement": "Built governed AI platform capabilities for developers.",
            "category": "platform",
            "technologies": ["Vertex AI", "MCP"],
            "evidence_tags": [
                "ai_platform",
                "agentic_workflows",
                "ai_developer_experience",
                "llm_platform",
                "ai_governance",
            ],
            "supporting_excerpt": "Built governed AI platform capabilities for developers.",
            "confidence": 0.9,
        }
    )

    assert proposal.evidence_tags == [
        EvidenceTag.AI_PLATFORM,
        EvidenceTag.AGENTIC_WORKFLOWS,
        EvidenceTag.AI_DEVELOPER_EXPERIENCE,
        EvidenceTag.LLM_PLATFORM,
        EvidenceTag.AI_GOVERNANCE,
    ]


def test_generic_ai_mention_does_not_add_unspecified_ai_categories() -> None:
    proposal = ExtractedCareerFactProposal.model_validate(
        {
            "statement": "Supported an AI initiative.",
            "category": "transformation",
            "technologies": [],
            "evidence_tags": ["ai_enablement"],
            "supporting_excerpt": "Supported an AI initiative.",
            "confidence": 0.8,
        }
    )

    assert proposal.evidence_tags == [EvidenceTag.AI_ENABLEMENT]
