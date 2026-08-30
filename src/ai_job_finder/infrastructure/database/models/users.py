from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ai_job_finder.domain.common import utc_now
from ai_job_finder.infrastructure.database.base import Base


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("identity_provider <> ''", name="identity_provider_not_blank"),
        CheckConstraint("external_subject <> ''", name="external_subject_not_blank"),
        UniqueConstraint(
            "identity_provider",
            "external_subject",
            name="uq_users_identity_provider_external_subject",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    identity_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
