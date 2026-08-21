from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    LargeBinary,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ModelProfile(Base):
    __tablename__ = "model_profiles"

    key: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
    model_id: Mapped[str | None] = mapped_column(nullable=True)
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TestSuite(Base):
    __tablename__ = "test_suites"

    key: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(index=True, nullable=False, unique=True)
    version: Mapped[str] = mapped_column(nullable=False)
    hash: Mapped[str] = mapped_column(nullable=False)
    source_path: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    suite_name: Mapped[str] = mapped_column(nullable=False)
    suite_version: Mapped[str] = mapped_column(nullable=False)
    suite_hash: Mapped[str] = mapped_column(nullable=False)
    profile_key: Mapped[str] = mapped_column(index=True, nullable=False)
    profile_label: Mapped[str] = mapped_column(nullable=False)
    model_id: Mapped[str | None] = mapped_column(nullable=True)
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    reasoning_effort: Mapped[str] = mapped_column(nullable=False, default="off")
    temperature: Mapped[float | None] = mapped_column(nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(nullable=True)
    modality: Mapped[str] = mapped_column(nullable=False, default="text")
    suite_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    results: Mapped[list["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EvaluationResult.index",
    )
    images: Mapped[list["EvaluationImage"]] = relationship(
        "EvaluationImage",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EvaluationImage.case_id",
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_runs.id"), index=True, nullable=False
    )
    case_id: Mapped[str] = mapped_column(nullable=False)
    index: Mapped[int] = mapped_column(nullable=False)
    category: Mapped[str | None] = mapped_column(nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(nullable=False, default="in_progress")
    request_started_at: Mapped[float | None] = mapped_column(nullable=True)
    ttft_seconds: Mapped[float | None] = mapped_column(nullable=True)
    completion_seconds: Mapped[float | None] = mapped_column(nullable=True)
    generation_tps: Mapped[float | None] = mapped_column(nullable=True)
    generation_tps_source: Mapped[str | None] = mapped_column(nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    token_source: Mapped[str | None] = mapped_column(nullable=True)
    input_type: Mapped[str | None] = mapped_column(nullable=True)
    case_type: Mapped[str | None] = mapped_column(nullable=True)
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    image_media_type: Mapped[str | None] = mapped_column(nullable=True)
    image_source: Mapped[str | None] = mapped_column(nullable=True)
    image_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    run: Mapped["EvaluationRun"] = relationship(back_populates="results")
    scores: Mapped["ManualScore"] = relationship(
        "ManualScore",
        back_populates="result",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ManualScore(Base):
    __tablename__ = "manual_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_results.id"),
        index=True,
        nullable=False,
        unique=True,
    )
    result: Mapped["EvaluationResult"] = relationship(back_populates="scores")
    accuracy: Mapped[int | None] = mapped_column(nullable=True)
    completeness: Mapped[int | None] = mapped_column(nullable=True)
    instruction_following: Mapped[int | None] = mapped_column(nullable=True)
    appropriate_judgment: Mapped[int | None] = mapped_column(nullable=True)
    refusal: Mapped[bool] = mapped_column(nullable=False, default=False)
    hallucination: Mapped[bool] = mapped_column(nullable=False, default=False)
    truncation: Mapped[bool] = mapped_column(nullable=False, default=False)
    unsafe_output: Mapped[bool] = mapped_column(nullable=False, default=False)
    format_failure: Mapped[bool] = mapped_column(nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvaluationImage(Base):
    __tablename__ = "evaluation_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_runs.id"), index=True, nullable=False
    )
    case_id: Mapped[str] = mapped_column(nullable=False)
    media_type: Mapped[str] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)
    data_url: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run: Mapped["EvaluationRun"] = relationship(back_populates="images")
