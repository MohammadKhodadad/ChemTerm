"""Persistence of accepted external references on internal concepts."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from chemterm.enrichment.contracts import ExternalConceptReference
from chemterm.models import ConceptIdentifier, IdentifierNamespace


class ExternalReferenceRepository:
    """Upsert authority references through controlled identifier namespaces."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        concept_id: uuid.UUID,
        references: Iterable[ExternalConceptReference],
        *,
        include_review: bool = False,
    ) -> int:
        """Persist accepted matches and optionally review candidates."""

        selected = tuple(item for item in references if include_review or not item.needs_review)
        if not selected:
            return 0
        namespace_by_code = {
            item.code: item.id
            for item in self.session.scalars(
                select(IdentifierNamespace).where(
                    IdentifierNamespace.code.in_({item.namespace for item in selected}),
                    IdentifierNamespace.active.is_(True),
                )
            )
        }
        missing = sorted({item.namespace for item in selected} - namespace_by_code.keys())
        if missing:
            raise ValueError(f"unseeded identifier namespaces: {missing}")

        changed = 0
        for reference in selected:
            statement = (
                pg_insert(ConceptIdentifier)
                .values(
                    concept_id=concept_id,
                    namespace_id=namespace_by_code[reference.namespace],
                    external_id=reference.external_id,
                    mapping_type=reference.mapping_type.value,
                    confidence=reference.confidence,
                    source_uri=reference.canonical_url,
                )
                .on_conflict_do_update(
                    constraint="uq_concept_identifier_mapping",
                    set_={
                        "mapping_type": reference.mapping_type.value,
                        "confidence": reference.confidence,
                        "source_uri": reference.canonical_url,
                        "updated_at": func.now(),
                    },
                )
                .returning(ConceptIdentifier.id)
            )
            if self.session.scalar(statement) is not None:
                changed += 1
        return changed
