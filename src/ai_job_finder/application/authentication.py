from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_job_finder.domain.common import new_uuid
from ai_job_finder.infrastructure.database.models.users import UserModel


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    provider: str
    subject: str


@dataclass(frozen=True, slots=True)
class EstablishedIdentitySession:
    identity: AuthenticatedIdentity
    session_cookie: str


class IdentitySessionError(Exception):
    pass


class IdentitySessionProvider(Protocol):
    def establish_session(
        self,
        id_token: str,
        *,
        max_age: timedelta,
    ) -> EstablishedIdentitySession: ...

    def verify_session(self, session_cookie: str) -> AuthenticatedIdentity: ...


def get_user_by_identity(
    session: Session,
    *,
    identity: AuthenticatedIdentity,
) -> UserModel | None:
    return session.scalar(
        select(UserModel).where(
            UserModel.identity_provider == identity.provider,
            UserModel.external_subject == identity.subject,
        )
    )


def resolve_or_create_user(
    session: Session,
    *,
    identity: AuthenticatedIdentity,
) -> UserModel:
    existing = get_user_by_identity(session, identity=identity)
    if existing is not None:
        return existing

    user = UserModel(
        id=new_uuid(),
        identity_provider=identity.provider,
        external_subject=identity.subject,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = get_user_by_identity(session, identity=identity)
        if existing is None:
            raise
        return existing
    session.refresh(user)
    return user
