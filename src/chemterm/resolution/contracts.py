"""Concept retrieval and resolution contracts."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProposalIdentifier(BaseModel):
    """Identifier supplied with a new concept proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=500)


class ConceptProposal(BaseModel):
    """Incoming English concept candidate enriched with source context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(min_length=1, max_length=200)
    term: str = Field(min_length=1, max_length=2_000)
    normalized_term: str = Field(min_length=1, max_length=2_000)
    language: str = "en"
    context: str = Field(default="", max_length=10_000)
    type_codes: tuple[str, ...] = ()
    identifiers: tuple[ProposalIdentifier, ...] = ()


class ConceptIdentifierView(BaseModel):
    """Identifier shown on a candidate concept card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str
    value: str
    identity_strength: str


class RetrievalScores(BaseModel):
    """Independent retrieval signals; none is an identity decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exact_normalized: bool = False
    identifier_strength: str | None = None
    trigram: float | None = Field(default=None, ge=0, le=1)
    semantic: float | None = Field(default=None, ge=-1, le=1)
    ranking_score: float = 0


class ConceptCard(BaseModel):
    """Bounded existing-concept context presented to a resolver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: uuid.UUID
    preferred_english_term: str | None
    aliases: tuple[str, ...]
    type_codes: tuple[str, ...]
    identifiers: tuple[ConceptIdentifierView, ...]
    english_definition: str | None
    scores: RetrievalScores


class TypeDefinition(BaseModel):
    """Active concept type definition sent to the LLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    label: str
    description: str | None
    parent_code: str | None


class IdentifierDefinition(BaseModel):
    """Active identifier semantics sent to the LLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    label: str
    description: str
    identity_strength: str


class ResolutionVocabulary(BaseModel):
    """Explicit type, identifier, and safety vocabulary for each LLM call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    types: tuple[TypeDefinition, ...]
    identifier_namespaces: tuple[IdentifierDefinition, ...]
    non_merge_rules: tuple[str, ...]


class ResolutionOutcome(StrEnum):
    """Permitted bounded outcomes for a concept proposal."""

    SAME_CONCEPT = "SAME_CONCEPT"
    NEW_CONCEPT = "NEW_CONCEPT"
    RELATED_NOT_SAME = "RELATED_NOT_SAME"
    AMBIGUOUS = "AMBIGUOUS"


class ResolutionReason(StrEnum):
    """Auditable reason codes available to deterministic and LLM resolvers."""

    IDENTIFIER_EXACT = "IDENTIFIER_EXACT"
    EXACT_LABEL_MATCH = "EXACT_LABEL_MATCH"
    ALIAS_MATCH = "ALIAS_MATCH"
    CONTEXT_EQUIVALENT = "CONTEXT_EQUIVALENT"
    TYPE_COMPATIBLE = "TYPE_COMPATIBLE"
    TYPE_CONFLICT = "TYPE_CONFLICT"
    STRUCTURE_CONFLICT = "STRUCTURE_CONFLICT"
    SALT_SOLVATE_DIFFERENCE = "SALT_SOLVATE_DIFFERENCE"
    STEREO_DIFFERENCE = "STEREO_DIFFERENCE"
    CLASS_INSTANCE_DIFFERENCE = "CLASS_INSTANCE_DIFFERENCE"
    FORMULATION_DIFFERENCE = "FORMULATION_DIFFERENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_CANDIDATE = "NO_CANDIDATE"


class ConceptResolutionDecision(BaseModel):
    """Validated decision for one incoming proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    outcome: ResolutionOutcome
    concept_id: uuid.UUID | None = None
    related_concept_id: uuid.UUID | None = None
    confidence: float = Field(ge=0, le=1)
    reason_codes: tuple[ResolutionReason, ...] = Field(min_length=1)
    needs_review: bool

    @model_validator(mode="after")
    def validate_outcome_references(self) -> ConceptResolutionDecision:
        if self.outcome is ResolutionOutcome.SAME_CONCEPT and self.concept_id is None:
            raise ValueError("SAME_CONCEPT requires concept_id")
        if self.outcome is ResolutionOutcome.RELATED_NOT_SAME and self.related_concept_id is None:
            raise ValueError("RELATED_NOT_SAME requires related_concept_id")
        if self.outcome is ResolutionOutcome.NEW_CONCEPT and (
            self.concept_id is not None or self.related_concept_id is not None
        ):
            raise ValueError("NEW_CONCEPT cannot reference an existing concept")
        return self
