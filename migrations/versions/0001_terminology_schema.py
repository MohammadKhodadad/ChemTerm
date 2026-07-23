"""Create terminology-only schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    """Create the initial terminology tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "concept_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["parent_id"], ["concept_type.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "term_form",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "relation_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("symmetric", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "identifier_namespace",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(60), nullable=False, unique=True),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("value_pattern", sa.Text),
        sa.Column("identity_strength", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "identity_strength IN ('authoritative', 'strong', 'supporting')",
            name="ck_identifier_namespace_strength",
        ),
    )
    op.create_table(
        "pipeline_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_version", sa.String(120), nullable=False),
        sa.Column("code_revision", sa.String(160)),
        sa.Column(
            "model_versions",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "configuration",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_pipeline_run_status",
        ),
    )
    op.create_table(
        "concept",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("english_definition", sa.Text),
        sa.Column("status", sa.String(20), server_default="proposed", nullable=False),
        sa.Column("created_by_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'deprecated', 'merged')",
            name="ck_concept_status",
        ),
        sa.ForeignKeyConstraint(["created_by_run_id"], ["pipeline_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["concept.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "concept_type_assignment",
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("concept_type_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_concept_type_assignment_confidence",
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concept.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_type_id"], ["concept_type.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "term",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("normalized_text", sa.Text, nullable=False),
        sa.Column("language", sa.String(35), nullable=False),
        sa.Column("script", sa.String(4)),
        sa.Column("term_form_id", postgresql.UUID(as_uuid=True)),
        sa.Column("is_preferred", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("status", sa.String(20), server_default="proposed", nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("created_by_run_id", postgresql.UUID(as_uuid=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'deprecated')",
            name="ck_term_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_term_confidence",
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concept.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["term_form_id"], ["term_form.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_run_id"], ["pipeline_run.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "concept_id",
            "language",
            "normalized_text",
            name="uq_term_concept_language_normalized",
        ),
    )
    op.create_index("ix_term_language_normalized", "term", ["language", "normalized_text"])
    op.create_index(
        "ix_term_normalized_trgm",
        "term",
        ["normalized_text"],
        postgresql_using="gin",
        postgresql_ops={"normalized_text": "gin_trgm_ops"},
    )
    op.create_index(
        "uq_term_preferred_per_concept_language",
        "term",
        ["concept_id", "language"],
        unique=True,
        postgresql_where=sa.text("is_preferred"),
    )
    op.create_table(
        "concept_identifier",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("mapping_type", sa.String(20), server_default="exact", nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("source_uri", sa.Text),
        *_timestamps(),
        sa.CheckConstraint(
            "mapping_type IN ('exact', 'close', 'broad', 'narrow', 'related')",
            name="ck_concept_identifier_mapping_type",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_concept_identifier_confidence",
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concept.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["namespace_id"], ["identifier_namespace.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "concept_id",
            "namespace_id",
            "external_id",
            name="uq_concept_identifier_mapping",
        ),
    )
    op.create_index(
        "ix_concept_identifier_lookup",
        "concept_identifier",
        ["namespace_id", "external_id"],
    )
    op.create_table(
        "concept_embedding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("embedded_text", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["concept_id"], ["concept.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "concept_id",
            "model_name",
            "model_version",
            name="uq_concept_embedding_model",
        ),
    )
    op.create_index(
        "ix_concept_embedding_hnsw",
        "concept_embedding",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "evidence_set",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", sa.String(120), nullable=False),
        sa.Column("extraction_method", sa.String(80), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("status", sa.String(20), server_default="proposed", nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "score_components",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'needs_expert')",
            name="ck_evidence_set_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_evidence_set_confidence"
        ),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_run.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "term_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evidence_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", sa.String(120), nullable=False),
        sa.Column("publication_number", sa.String(120), nullable=False),
        sa.Column("source_language", sa.String(35), nullable=False),
        sa.Column("source_locator", sa.String(255), nullable=False),
        sa.Column("source_uri", sa.Text),
        sa.Column("evidence_excerpt", sa.Text),
        sa.Column("text_origin", sa.String(30), server_default="unknown", nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_term_evidence_confidence"
        ),
        sa.CheckConstraint(
            "text_origin IN ('original', 'official_translation', 'machine_translation', 'unknown')",
            name="ck_term_evidence_text_origin",
        ),
        sa.ForeignKeyConstraint(["evidence_set_id"], ["evidence_set.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["term_id"], ["term.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "evidence_set_id",
            "term_id",
            "publication_number",
            "source_locator",
            name="uq_term_evidence_reference",
        ),
    )
    op.create_index(
        "ix_term_evidence_family_publication",
        "term_evidence",
        ["family_id", "publication_number"],
    )
    op.create_table(
        "concept_relation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("status", sa.String(20), server_default="proposed", nullable=False),
        sa.Column("evidence_set_id", postgresql.UUID(as_uuid=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "source_concept_id <> target_concept_id",
            name="ck_concept_relation_not_self",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_concept_relation_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'deprecated')",
            name="ck_concept_relation_status",
        ),
        sa.ForeignKeyConstraint(["source_concept_id"], ["concept.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_concept_id"], ["concept.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["relation_type_id"], ["relation_type.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_set_id"], ["evidence_set.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "source_concept_id",
            "target_concept_id",
            "relation_type_id",
            name="uq_concept_relation",
        ),
    )
    op.create_table(
        "review_decision",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evidence_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reviewer", sa.String(160), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected', 'needs_expert')",
            name="ck_review_decision",
        ),
        sa.ForeignKeyConstraint(["evidence_set_id"], ["evidence_set.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    """Drop the terminology tables."""

    op.drop_table("review_decision")
    op.drop_table("concept_relation")
    op.drop_index("ix_term_evidence_family_publication", table_name="term_evidence")
    op.drop_table("term_evidence")
    op.drop_table("evidence_set")
    op.drop_index("ix_concept_embedding_hnsw", table_name="concept_embedding")
    op.drop_table("concept_embedding")
    op.drop_index("ix_concept_identifier_lookup", table_name="concept_identifier")
    op.drop_table("concept_identifier")
    op.drop_index("uq_term_preferred_per_concept_language", table_name="term")
    op.drop_index("ix_term_normalized_trgm", table_name="term")
    op.drop_index("ix_term_language_normalized", table_name="term")
    op.drop_table("term")
    op.drop_table("concept_type_assignment")
    op.drop_table("concept")
    op.drop_table("pipeline_run")
    op.drop_table("identifier_namespace")
    op.drop_table("relation_type")
    op.drop_table("term_form")
    op.drop_table("concept_type")
