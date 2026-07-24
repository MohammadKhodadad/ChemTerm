"""PostgreSQL retrieval repository for concept resolution."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from chemterm.models import (
    Concept,
    ConceptEmbedding,
    ConceptIdentifier,
    ConceptType,
    ConceptTypeAssignment,
    IdentifierNamespace,
    Term,
)
from chemterm.resolution.contracts import (
    ConceptCard,
    ConceptIdentifierView,
    ConceptProposal,
    IdentifierDefinition,
    ResolutionVocabulary,
    RetrievalScores,
    TypeDefinition,
)
from chemterm.resolution.embedding import (
    EmbeddingProvider,
    concept_representation,
    representation_hash,
)

DEFAULT_NON_MERGE_RULES = (
    "Do not merge a parent compound with a salt, hydrate, solvate, or formulation.",
    "Do not merge stereoisomers, regioisomers, isotopologues, or distinct polymorphs.",
    "Do not merge a specific substance with a chemical class or Markush class.",
    "Do not merge a pure substance with a mixture, composition, material, or process.",
    "A shared molecular formula is supporting evidence only; isomers can share it.",
    "Lexical or embedding similarity retrieves candidates but never proves identity.",
    "If context cannot distinguish meanings, choose AMBIGUOUS and require review.",
)


@dataclass
class _MutableScores:
    exact_normalized: bool = False
    identifier_strength: str | None = None
    trigram: float | None = None
    semantic: float | None = None

    def ranking_score(self) -> float:
        identifier_weight = {
            "authoritative": 2.0,
            "strong": 1.5,
            "supporting": 0.35,
            None: 0.0,
        }[self.identifier_strength]
        return (
            identifier_weight
            + (1.25 if self.exact_normalized else 0.0)
            + 0.65 * (self.trigram or 0.0)
            + 0.65 * max(self.semantic or 0.0, 0.0)
        )


class ConceptSearchRepository:
    """Retrieve and hydrate bounded candidates from the terminology database."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def vocabulary(self) -> ResolutionVocabulary:
        """Load active controlled values; the database is the prompt source of truth."""

        type_rows = list(
            self.session.execute(
                select(
                    ConceptType.id,
                    ConceptType.code,
                    ConceptType.label,
                    ConceptType.description,
                    ConceptType.parent_id,
                )
                .where(ConceptType.active.is_(True))
                .order_by(ConceptType.code)
            )
        )
        type_code_by_id = {row.id: row.code for row in type_rows}
        identifier_rows = self.session.scalars(
            select(IdentifierNamespace)
            .where(IdentifierNamespace.active.is_(True))
            .order_by(IdentifierNamespace.code)
        )
        return ResolutionVocabulary(
            types=tuple(
                TypeDefinition(
                    code=row.code,
                    label=row.label,
                    description=row.description,
                    parent_code=type_code_by_id.get(row.parent_id),
                )
                for row in type_rows
            ),
            identifier_namespaces=tuple(
                IdentifierDefinition(
                    code=row.code,
                    label=row.label,
                    description=row.description,
                    identity_strength=row.identity_strength,
                )
                for row in identifier_rows
            ),
            non_merge_rules=DEFAULT_NON_MERGE_RULES,
        )

    def retrieve(
        self,
        proposal: ConceptProposal,
        *,
        query_embedding: list[float] | None = None,
        embedding_model: tuple[str, str] | None = None,
        top_k: int = 8,
        fuzzy_threshold: float = 0.25,
    ) -> tuple[ConceptCard, ...]:
        """Combine exact, identifier, trigram, and vector retrieval signals."""

        scores: dict[uuid.UUID, _MutableScores] = defaultdict(_MutableScores)
        active_terms = Term.status.in_(("proposed", "accepted"))

        exact_ids = self.session.scalars(
            select(Term.concept_id).where(
                Term.language == proposal.language,
                Term.normalized_text == proposal.normalized_term,
                active_terms,
            )
        )
        for concept_id in exact_ids:
            scores[concept_id].exact_normalized = True

        strength_rank = {"supporting": 1, "strong": 2, "authoritative": 3}
        for identifier in proposal.identifiers:
            rows = self.session.execute(
                select(ConceptIdentifier.concept_id, IdentifierNamespace.identity_strength)
                .join(
                    IdentifierNamespace,
                    IdentifierNamespace.id == ConceptIdentifier.namespace_id,
                )
                .where(
                    IdentifierNamespace.code == identifier.namespace,
                    ConceptIdentifier.external_id == identifier.value,
                )
            )
            for concept_id, strength in rows:
                current = scores[concept_id].identifier_strength
                if current is None or strength_rank[strength] > strength_rank[current]:
                    scores[concept_id].identifier_strength = strength

        similarity = func.similarity(Term.normalized_text, proposal.normalized_term)
        fuzzy_rows = self.session.execute(
            select(Term.concept_id, func.max(similarity).label("score"))
            .where(
                Term.language == proposal.language,
                active_terms,
                similarity >= fuzzy_threshold,
            )
            .group_by(Term.concept_id)
            .order_by(func.max(similarity).desc())
            .limit(top_k * 2)
        )
        for concept_id, score in fuzzy_rows:
            scores[concept_id].trigram = float(score)

        if query_embedding is not None and embedding_model is not None:
            model_name, model_version = embedding_model
            distance = ConceptEmbedding.embedding.cosine_distance(query_embedding)
            semantic_rows = self.session.execute(
                select(ConceptEmbedding.concept_id, (1 - distance).label("score"))
                .where(
                    ConceptEmbedding.model_name == model_name,
                    ConceptEmbedding.model_version == model_version,
                )
                .order_by(distance)
                .limit(top_k * 2)
            )
            for concept_id, score in semantic_rows:
                scores[concept_id].semantic = float(score)

        ranked_ids = sorted(
            scores,
            key=lambda concept_id: (-scores[concept_id].ranking_score(), str(concept_id)),
        )[:top_k]
        return self._hydrate_cards(ranked_ids, scores)

    def _hydrate_cards(
        self,
        concept_ids: list[uuid.UUID],
        scores: dict[uuid.UUID, _MutableScores],
    ) -> tuple[ConceptCard, ...]:
        if not concept_ids:
            return ()

        concepts = {
            item.id: item
            for item in self.session.scalars(select(Concept).where(Concept.id.in_(concept_ids)))
        }
        terms: dict[uuid.UUID, list[Term]] = defaultdict(list)
        for item in self.session.scalars(
            select(Term)
            .where(Term.concept_id.in_(concept_ids), Term.language == "en")
            .order_by(Term.normalized_text, Term.text)
        ):
            terms[item.concept_id].append(item)

        types: dict[uuid.UUID, list[str]] = defaultdict(list)
        for concept_id, code in self.session.execute(
            select(ConceptTypeAssignment.concept_id, ConceptType.code)
            .join(ConceptType, ConceptType.id == ConceptTypeAssignment.concept_type_id)
            .where(ConceptTypeAssignment.concept_id.in_(concept_ids))
        ):
            types[concept_id].append(code)

        identifiers: dict[uuid.UUID, list[ConceptIdentifierView]] = defaultdict(list)
        for concept_id, code, value, strength, source_uri in self.session.execute(
            select(
                ConceptIdentifier.concept_id,
                IdentifierNamespace.code,
                ConceptIdentifier.external_id,
                IdentifierNamespace.identity_strength,
                ConceptIdentifier.source_uri,
            )
            .join(
                IdentifierNamespace,
                IdentifierNamespace.id == ConceptIdentifier.namespace_id,
            )
            .where(ConceptIdentifier.concept_id.in_(concept_ids))
        ):
            identifiers[concept_id].append(
                ConceptIdentifierView(
                    namespace=code,
                    value=value,
                    identity_strength=strength,
                    source_uri=source_uri,
                )
            )

        cards = []
        for concept_id in concept_ids:
            concept = concepts.get(concept_id)
            if concept is None:
                continue
            concept_terms = terms[concept_id]
            preferred = next(
                (item.text for item in concept_terms if item.is_preferred),
                concept_terms[0].text if concept_terms else None,
            )
            raw_scores = scores[concept_id]
            cards.append(
                ConceptCard(
                    concept_id=concept_id,
                    preferred_english_term=preferred,
                    aliases=tuple(item.text for item in concept_terms),
                    type_codes=tuple(sorted(types[concept_id])),
                    identifiers=tuple(
                        sorted(
                            identifiers[concept_id],
                            key=lambda item: (item.namespace, item.value),
                        )
                    ),
                    english_definition=concept.english_definition,
                    scores=RetrievalScores(
                        exact_normalized=raw_scores.exact_normalized,
                        identifier_strength=raw_scores.identifier_strength,
                        trigram=raw_scores.trigram,
                        semantic=raw_scores.semantic,
                        ranking_score=raw_scores.ranking_score(),
                    ),
                )
            )
        return tuple(cards)

    def upsert_embedding(
        self,
        card: ConceptCard,
        provider: EmbeddingProvider,
    ) -> bool:
        """Refresh a concept embedding only when its canonical text changed."""

        text = concept_representation(card)
        content_hash = representation_hash(text)
        vector = provider.embed_documents([text])[0]
        if len(vector) != provider.dimensions:
            raise ValueError("embedding provider returned an unexpected dimension")

        statement = (
            pg_insert(ConceptEmbedding)
            .values(
                concept_id=card.concept_id,
                model_name=provider.model_name,
                model_version=provider.model_version,
                embedded_text=text,
                content_hash=content_hash,
                embedding=vector,
            )
            .on_conflict_do_update(
                constraint="uq_concept_embedding_model",
                set_={
                    "embedded_text": text,
                    "content_hash": content_hash,
                    "embedding": vector,
                    "updated_at": func.now(),
                },
                where=ConceptEmbedding.content_hash != content_hash,
            )
            .returning(ConceptEmbedding.id)
        )
        return self.session.scalar(statement) is not None
