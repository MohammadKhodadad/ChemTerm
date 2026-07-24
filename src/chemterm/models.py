"""SQLAlchemy models for the terminology-only database."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIMENSIONS = 1024


class Base(DeclarativeBase):
    """Base class for all database models."""


class TimestampMixin:
    """Created/updated timestamps shared by mutable records."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ConceptType(Base, TimestampMixin):
    """Hierarchical semantic type such as compound, process, or property."""

    __tablename__ = "concept_type"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept_type.id", ondelete="RESTRICT")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class TermForm(Base, TimestampMixin):
    """Linguistic form such as systematic name, abbreviation, or trade name."""

    __tablename__ = "term_form"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class RelationType(Base, TimestampMixin):
    """Typed relation between concepts."""

    __tablename__ = "relation_type"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    symmetric: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class IdentifierNamespace(Base, TimestampMixin):
    """Controlled external identifier scheme exposed to resolvers."""

    __tablename__ = "identifier_namespace"
    __table_args__ = (
        CheckConstraint(
            "identity_strength IN ('authoritative', 'strong', 'supporting')",
            name="ck_identifier_namespace_strength",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value_pattern: Mapped[str | None] = mapped_column(Text)
    identity_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class PipelineRun(Base):
    """Reproducible extraction/import run metadata."""

    __tablename__ = "pipeline_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_pipeline_run_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(120), nullable=False)
    code_revision: Mapped[str | None] = mapped_column(String(160))
    model_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", server_default="running"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Concept(Base, TimestampMixin):
    """Language-neutral meaning shared by multilingual terms."""

    __tablename__ = "concept"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'deprecated', 'merged')",
            name="ck_concept_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    english_definition: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed", server_default="proposed"
    )
    created_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL")
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="RESTRICT")
    )


class ConceptTypeAssignment(Base):
    """Many-to-many concept classification with confidence."""

    __tablename__ = "concept_type_assignment"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_concept_type_assignment_confidence"
        ),
    )

    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), primary_key=True
    )
    concept_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept_type.id", ondelete="RESTRICT"), primary_key=True
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("1"))
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="model")


class Term(Base, TimestampMixin):
    """Language-specific label attached to one concept."""

    __tablename__ = "term"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'deprecated')",
            name="ck_term_status",
        ),
        UniqueConstraint(
            "concept_id",
            "language",
            "normalized_text",
            name="uq_term_concept_language_normalized",
        ),
        Index("ix_term_language_normalized", "language", "normalized_text"),
        Index(
            "ix_term_normalized_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
        Index(
            "uq_term_preferred_per_concept_language",
            "concept_id",
            "language",
            unique=True,
            postgresql_where=text("is_preferred"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    script: Mapped[str | None] = mapped_column(String(4))
    term_form_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("term_form.id", ondelete="RESTRICT")
    )
    is_preferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed", server_default="proposed"
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    created_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL")
    )

    __table_args__ += (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_term_confidence",
        ),
    )


class ConceptIdentifier(Base, TimestampMixin):
    """Mapping from an internal concept to an external authority."""

    __tablename__ = "concept_identifier"
    __table_args__ = (
        CheckConstraint(
            "mapping_type IN ('exact', 'close', 'broad', 'narrow', 'related')",
            name="ck_concept_identifier_mapping_type",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_concept_identifier_confidence"
        ),
        UniqueConstraint(
            "concept_id",
            "namespace_id",
            "external_id",
            name="uq_concept_identifier_mapping",
        ),
        Index("ix_concept_identifier_lookup", "namespace_id", "external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), nullable=False
    )
    namespace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identifier_namespace.id", ondelete="RESTRICT"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    mapping_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="exact", server_default="exact"
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("1"))
    source_uri: Mapped[str | None] = mapped_column(Text)


class ConceptEmbedding(Base, TimestampMixin):
    """Search representation for one concept and embedding model."""

    __tablename__ = "concept_embedding"
    __table_args__ = (
        UniqueConstraint(
            "concept_id",
            "model_name",
            "model_version",
            name="uq_concept_embedding_model",
        ),
        Index(
            "ix_concept_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    embedded_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)


class EvidenceSet(Base, TimestampMixin):
    """A lightweight patent-family observation supporting several terms."""

    __tablename__ = "evidence_set"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'needs_expert')",
            name="ck_evidence_set_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_evidence_set_confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[str] = mapped_column(String(120), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed", server_default="proposed"
    )
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL")
    )
    score_components: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class TermEvidence(Base, TimestampMixin):
    """Minimal patent reference showing a term in an evidence set."""

    __tablename__ = "term_evidence"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_term_evidence_confidence"),
        CheckConstraint(
            "text_origin IN ('original', 'official_translation', 'machine_translation', 'unknown')",
            name="ck_term_evidence_text_origin",
        ),
        CheckConstraint(
            "target_form_status IN ('TRANSLATED', 'UNCHANGED', 'LANGUAGE_NEUTRAL', 'UNKNOWN')",
            name="ck_term_evidence_target_form_status",
        ),
        UniqueConstraint(
            "evidence_set_id",
            "term_id",
            "publication_number",
            "source_locator",
            name="uq_term_evidence_reference",
        ),
        Index("ix_term_evidence_family_publication", "family_id", "publication_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_set.id", ondelete="CASCADE"), nullable=False
    )
    term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("term.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[str] = mapped_column(String(120), nullable=False)
    publication_number: Mapped[str] = mapped_column(String(120), nullable=False)
    source_language: Mapped[str] = mapped_column(String(35), nullable=False)
    source_locator: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_uri: Mapped[str | None] = mapped_column(Text)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    text_origin: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unknown", server_default="unknown"
    )
    target_form_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)


class ConceptRelation(Base, TimestampMixin):
    """Typed semantic or chemical relationship between concepts."""

    __tablename__ = "concept_relation"
    __table_args__ = (
        CheckConstraint(
            "source_concept_id <> target_concept_id", name="ck_concept_relation_not_self"
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_concept_relation_confidence"
        ),
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'deprecated')",
            name="ck_concept_relation_status",
        ),
        UniqueConstraint(
            "source_concept_id",
            "target_concept_id",
            "relation_type_id",
            name="uq_concept_relation",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), nullable=False
    )
    target_concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), nullable=False
    )
    relation_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("relation_type.id", ondelete="RESTRICT"), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed", server_default="proposed"
    )
    evidence_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_set.id", ondelete="SET NULL")
    )


class ReviewDecision(Base):
    """Append-only human decision on an evidence set."""

    __tablename__ = "review_decision"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accepted', 'rejected', 'needs_expert')",
            name="ck_review_decision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_set.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(160), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
