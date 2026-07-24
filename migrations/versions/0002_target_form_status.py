"""Record translated, unchanged, and language-neutral target forms.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an evidence-level target-form classification."""

    op.add_column(
        "term_evidence",
        sa.Column(
            "target_form_status",
            sa.String(20),
            server_default="UNKNOWN",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_term_evidence_target_form_status",
        "term_evidence",
        "target_form_status IN ('TRANSLATED', 'UNCHANGED', 'LANGUAGE_NEUTRAL', 'UNKNOWN')",
    )


def downgrade() -> None:
    """Remove target-form classification."""

    op.drop_constraint(
        "ck_term_evidence_target_form_status",
        "term_evidence",
        type_="check",
    )
    op.drop_column("term_evidence", "target_form_status")
