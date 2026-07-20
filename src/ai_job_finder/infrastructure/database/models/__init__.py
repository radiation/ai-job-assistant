from __future__ import annotations

from typing import Any

from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.models.candidate import (
    CandidateProfileModel,
    CareerFactModel,
)
from ai_job_finder.infrastructure.database.models.documents import (
    CareerFactProposalModel,
    ExtractionRunModel,
    SourceDocumentModel,
)
from ai_job_finder.infrastructure.database.models.job_searches import (
    JobSearchDefinitionModel,
    JobSearchMatchModel,
    JobSearchRunModel,
)
from ai_job_finder.infrastructure.database.models.job_sources import (
    JobImportRunModel,
    JobSourceConfigurationModel,
    JobSourceObservationModel,
    SourceDetectionRunModel,
)
from ai_job_finder.infrastructure.database.models.jobs import (
    JobEvaluationModel,
    JobLeadModel,
)

__all__ = [
    "CandidateProfileModel",
    "CareerFactModel",
    "CareerFactProposalModel",
    "ExtractionRunModel",
    "JobEvaluationModel",
    "JobImportRunModel",
    "JobLeadModel",
    "JobSearchDefinitionModel",
    "JobSearchMatchModel",
    "JobSearchRunModel",
    "JobSourceConfigurationModel",
    "JobSourceObservationModel",
    "SourceDetectionRunModel",
    "SourceDocumentModel",
    "serialize_model",
]


def serialize_model(model: Base) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}
