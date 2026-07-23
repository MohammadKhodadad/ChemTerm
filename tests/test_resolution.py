"""Tests for semantic concept retrieval and bounded LLM resolution."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from chemterm.resolution import (
    ConceptCard,
    ConceptProposal,
    ConceptResolutionService,
    IdentifierDefinition,
    LlmConceptResolver,
    ResolutionOutcome,
    ResolutionVocabulary,
    RetrievalScores,
    TypeDefinition,
    concept_representation,
)


def _vocabulary() -> ResolutionVocabulary:
    return ResolutionVocabulary(
        types=(
            TypeDefinition(
                code="SALT",
                label="Salt",
                description="Salt form of a compound.",
                parent_code="COMPOUND",
            ),
        ),
        identifier_namespaces=(
            IdentifierDefinition(
                code="INCHIKEY",
                label="InChIKey",
                description="Structure-derived key.",
                identity_strength="authoritative",
            ),
        ),
        non_merge_rules=("Do not merge a parent compound and its salt.",),
    )


def _card(concept_id: uuid.UUID | None = None) -> ConceptCard:
    return ConceptCard(
        concept_id=concept_id or uuid.uuid4(),
        preferred_english_term="aspirin",
        aliases=("acetylsalicylic acid", "aspirin"),
        type_codes=("COMPOUND",),
        identifiers=(),
        english_definition="An acetylated salicylate.",
        scores=RetrievalScores(
            exact_normalized=True,
            trigram=1,
            semantic=0.98,
            ranking_score=2.53,
        ),
    )


class FakeLlmClient:
    model = "fake"

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.payload: dict[str, Any] | None = None

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> dict[str, Any]:
        self.payload = payload
        assert "retrieval scores are clues, not proof" in system_prompt.lower()
        return self.response


def test_llm_resolver_receives_types_identifiers_and_non_merge_rules() -> None:
    card = _card()
    client = FakeLlmClient(
        {
            "proposal_id": "p1",
            "outcome": "SAME_CONCEPT",
            "concept_id": str(card.concept_id),
            "related_concept_id": None,
            "confidence": 0.98,
            "reason_codes": ["EXACT_LABEL_MATCH", "CONTEXT_EQUIVALENT"],
            "needs_review": False,
        }
    )
    resolver = LlmConceptResolver(client)
    proposal = ConceptProposal(
        proposal_id="p1",
        term="aspirin",
        normalized_term="aspirin",
        context="Aspirin was added.",
        type_codes=("COMPOUND",),
    )

    decision = resolver.resolve(proposal, (card,), _vocabulary())

    assert decision.concept_id == card.concept_id
    assert client.payload is not None
    controlled = client.payload["controlled_vocabulary"]
    assert controlled["types"][0]["code"] == "SALT"
    assert controlled["identifier_namespaces"][0]["code"] == "INCHIKEY"
    assert controlled["non_merge_rules"]


def test_llm_resolver_rejects_invented_concept_id() -> None:
    card = _card()
    client = FakeLlmClient(
        {
            "proposal_id": "p1",
            "outcome": "SAME_CONCEPT",
            "concept_id": str(uuid.uuid4()),
            "related_concept_id": None,
            "confidence": 0.8,
            "reason_codes": ["ALIAS_MATCH"],
            "needs_review": False,
        }
    )

    with pytest.raises(ValueError, match="outside the candidate set"):
        LlmConceptResolver(client).resolve(
            ConceptProposal(
                proposal_id="p1",
                term="aspirin",
                normalized_term="aspirin",
            ),
            (card,),
            _vocabulary(),
        )


def test_concept_representation_is_stable_and_excludes_retrieval_scores() -> None:
    card = _card()
    representation = concept_representation(card)

    assert "preferred term: aspirin" in representation
    assert "aliases: acetylsalicylic acid; aspirin" in representation
    assert "0.98" not in representation


class FakeProvider:
    model_name = "test-embedding"
    model_version = "v1"
    dimensions = 3

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        assert "term: aspirin" in texts[0]
        return [[0.1, 0.2, 0.3]]


class FakeRepository:
    def __init__(self, card: ConceptCard) -> None:
        self.card = card
        self.received: dict[str, Any] = {}

    def retrieve(self, proposal: ConceptProposal, **kwargs: Any) -> tuple[ConceptCard, ...]:
        self.received = kwargs
        return (self.card,)

    def vocabulary(self) -> ResolutionVocabulary:
        return _vocabulary()


def test_resolution_service_passes_query_vector_and_model_to_retrieval() -> None:
    card = _card()
    repository = FakeRepository(card)
    client = FakeLlmClient(
        {
            "proposal_id": "p1",
            "outcome": ResolutionOutcome.NEW_CONCEPT,
            "concept_id": None,
            "related_concept_id": None,
            "confidence": 0.7,
            "reason_codes": ["TYPE_CONFLICT"],
            "needs_review": False,
        }
    )
    service = ConceptResolutionService(
        repository,  # type: ignore[arg-type]
        LlmConceptResolver(client),
        embedding_provider=FakeProvider(),  # type: ignore[arg-type]
    )

    service.resolve(
        ConceptProposal(
            proposal_id="p1",
            term="aspirin",
            normalized_term="aspirin",
        )
    )

    assert repository.received["query_embedding"] == [0.1, 0.2, 0.3]
    assert repository.received["embedding_model"] == ("test-embedding", "v1")
