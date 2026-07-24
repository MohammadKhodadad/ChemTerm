"""Contracts for linking concepts to external terminology authorities."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from chemterm.resolution.contracts import ConceptProposal


class ExternalMappingType(StrEnum):
    """How strongly an external record identifies the proposed concept."""

    EXACT = "exact"
    CLOSE = "close"
    BROAD = "broad"
    NARROW = "narrow"
    RELATED = "related"


class ExternalConceptReference(BaseModel):
    """One auditable external authority candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str = Field(min_length=1, max_length=60)
    external_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=2_000)
    canonical_url: str = Field(min_length=1, max_length=2_000)
    description: str | None = Field(default=None, max_length=5_000)
    mapping_type: ExternalMappingType
    confidence: float = Field(ge=0, le=1)
    needs_review: bool
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ExternalReferenceIssue(BaseModel):
    """Non-fatal authority lookup failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    code: str
    message: str


class ConceptEnrichmentResult(BaseModel):
    """External references proposed for one internal concept proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    term: str
    references: tuple[ExternalConceptReference, ...]
    issues: tuple[ExternalReferenceIssue, ...] = ()


class ExternalReferenceProvider(Protocol):
    """Read-only external concept authority."""

    name: str

    def lookup(self, proposal: ConceptProposal) -> tuple[ExternalConceptReference, ...]:
        """Return bounded, auditable candidates without persisting them."""

        ...
