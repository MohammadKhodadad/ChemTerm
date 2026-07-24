"""Validated application contracts for terminology records."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from chemterm.contracts.input import TextOrigin
from chemterm.contracts.mapping import TargetFormStatus


class RecordStatus(StrEnum):
    """Lifecycle shared by concepts, terms, and relations."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class EvidenceStatus(StrEnum):
    """Review lifecycle for a multilingual evidence set."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_EXPERT = "needs_expert"


class ConceptCreate(BaseModel):
    """Input for a language-neutral concept."""

    english_definition: str | None = Field(default=None, max_length=10_000)
    type_codes: list[str] = Field(default_factory=list)
    status: RecordStatus = RecordStatus.PROPOSED


class TermCreate(BaseModel):
    """Input for a language-specific concept label."""

    concept_id: uuid.UUID
    text: str = Field(min_length=1, max_length=2_000)
    normalized_text: str = Field(min_length=1, max_length=2_000)
    language: str = Field(min_length=2, max_length=35)
    script: str | None = Field(default=None, min_length=4, max_length=4)
    term_form_code: str | None = Field(default=None, max_length=80)
    is_preferred: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: RecordStatus = RecordStatus.PROPOSED


class TermEvidenceCreate(BaseModel):
    """Minimal patent reference supporting one term."""

    term_id: uuid.UUID
    family_id: str = Field(min_length=1, max_length=120)
    publication_number: str = Field(min_length=1, max_length=120)
    source_language: str = Field(min_length=2, max_length=35)
    source_locator: str = Field(default="", max_length=255)
    source_uri: HttpUrl | None = None
    evidence_excerpt: str | None = Field(default=None, max_length=5_000)
    text_origin: TextOrigin = TextOrigin.UNKNOWN
    target_form_status: TargetFormStatus = TargetFormStatus.UNKNOWN
    confidence: float = Field(ge=0, le=1)

    @field_validator("target_form_status")
    @classmethod
    def reject_absent_target_evidence(cls, value: TargetFormStatus) -> TargetFormStatus:
        if value == TargetFormStatus.NOT_PRESENT:
            raise ValueError(
                "NOT_PRESENT cannot create term evidence because no target label exists"
            )
        return value


class EvidenceSetCreate(BaseModel):
    """A patent-family observation supporting multilingual terms."""

    model_config = ConfigDict(extra="forbid")

    family_id: str = Field(min_length=1, max_length=120)
    extraction_method: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    status: EvidenceStatus = EvidenceStatus.PROPOSED
    score_components: dict[str, float] = Field(default_factory=dict)
    terms: list[TermEvidenceCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_consistent_family(self) -> EvidenceSetCreate:
        """Require all references to belong to the evidence-set family."""

        inconsistent = [term.family_id for term in self.terms if term.family_id != self.family_id]
        if inconsistent:
            raise ValueError("all term evidence must use the evidence set family_id")
        return self


class ConceptIdentifierCreate(BaseModel):
    """Input for an external concept mapping."""

    concept_id: uuid.UUID
    namespace: str = Field(min_length=1, max_length=60)
    external_id: str = Field(min_length=1, max_length=255)
    mapping_type: str = Field(default="exact", pattern=r"^(exact|close|broad|narrow|related)$")
    confidence: float = Field(default=1, ge=0, le=1)
    source_uri: HttpUrl | None = None
