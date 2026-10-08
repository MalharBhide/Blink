"""Normalized entities; applicant content is encrypted, only IDs/state/index hashes are plaintext."""

import json
from datetime import datetime, timezone
from sqlalchemy import Text, String, ForeignKey, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from backend.app.config import cipher


def now():
    return datetime.now(timezone.utc)


class EncryptedJSON(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return (
            cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()
            if value is not None
            else None
        )

    def process_result_value(self, value, dialect):
        return json.loads(cipher().decrypt(value.encode())) if value is not None else None


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON, default=dict)


class Education(Base):
    __tablename__ = "education"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON)


class Employment(Base):
    __tablename__ = "employment"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON)


class Preference(Base):
    __tablename__ = "preferences"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON, default=dict)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), default=1)
    data: Mapped[dict] = mapped_column(EncryptedJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SavedAnswer(Base):
    __tablename__ = "saved_answers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), default=1)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    data: Mapped[dict] = mapped_column(EncryptedJSON)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(EncryptedJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    data: Mapped[dict] = mapped_column(EncryptedJSON)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    data: Mapped[dict] = mapped_column(EncryptedJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
