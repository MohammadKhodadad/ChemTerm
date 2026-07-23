"""Contracts for source-grounded terminology extraction."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class CandidateType(StrEnum):
    """Controlled concept types presented to extractors and LLMs."""

    CHEMICAL_ENTITY = "CHEMICAL_ENTITY"
    ELEMENT = "ELEMENT"
    COMPOUND = "COMPOUND"
    SALT = "SALT"
    SOLVATE = "SOLVATE"
    HYDRATE = "HYDRATE"
    POLYMER = "POLYMER"
    CHEMICAL_CLASS = "CHEMICAL_CLASS"
    FUNCTIONAL_GROUP = "FUNCTIONAL_GROUP"
    MARKUSH_CLASS = "MARKUSH_CLASS"
    MATERIAL = "MATERIAL"
    MIXTURE_OR_COMPOSITION = "MIXTURE_OR_COMPOSITION"
    PROCESS = "PROCESS"
    CHEMICAL_REACTION = "CHEMICAL_REACTION"
    SYNTHESIS_PROCESS = "SYNTHESIS_PROCESS"
    SEPARATION_PROCESS = "SEPARATION_PROCESS"
    MANUFACTURING_PROCESS = "MANUFACTURING_PROCESS"
    PROPERTY = "PROPERTY"
    CHEMICAL_PROPERTY = "CHEMICAL_PROPERTY"
    PHYSICAL_PROPERTY = "PHYSICAL_PROPERTY"
    PERFORMANCE_PROPERTY = "PERFORMANCE_PROPERTY"
    MEASUREMENT = "MEASUREMENT"
    EQUIPMENT = "EQUIPMENT"
    APPLICATION = "APPLICATION"
    OTHER_TECHNICAL_CONCEPT = "OTHER_TECHNICAL_CONCEPT"


class ContextRole(StrEnum):
    """Context-specific roles that do not define concept identity."""

    STARTING_MATERIAL = "STARTING_MATERIAL"
    REACTANT = "REACTANT"
    REAGENT = "REAGENT"
    CATALYST = "CATALYST"
    SOLVENT = "SOLVENT"
    INTERMEDIATE = "INTERMEDIATE"
    REACTION_PRODUCT = "REACTION_PRODUCT"
    ADDITIVE = "ADDITIVE"
    BINDER = "BINDER"
    MATRIX = "MATRIX"
    COATING = "COATING"
    SUBSTRATE = "SUBSTRATE"


class RawCandidate(BaseModel):
    """Extractor output using offsets in normalized source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    types: tuple[CandidateType, ...] = Field(min_length=1)
    roles: tuple[ContextRole, ...] = ()
    proposed_definition: str | None = Field(default=None, max_length=1_000)
    confidence: float = Field(ge=0, le=1)
    extractor: str = Field(min_length=1, max_length=120)
    extractor_version: str = Field(min_length=1, max_length=120)
    raw_label: str | None = Field(default=None, max_length=160)
    needs_review: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> RawCandidate:
        """Require a non-empty half-open span."""

        if self.end <= self.start:
            raise ValueError("candidate end must be greater than start")
        return self


class TermCandidate(BaseModel):
    """Validated candidate mapped to original and normalized source offsets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str
    text_unit_index: int = Field(ge=0)
    language: str
    text: str
    normalized_start: int = Field(ge=0)
    normalized_end: int = Field(gt=0)
    original_start: int = Field(ge=0)
    original_end: int = Field(gt=0)
    types: tuple[CandidateType, ...]
    roles: tuple[ContextRole, ...] = ()
    proposed_definition: str | None = Field(default=None, max_length=1_000)
    confidence: float = Field(ge=0, le=1)
    extractor: str
    extractor_version: str
    raw_label: str | None = None
    needs_review: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ExtractionIssue(BaseModel):
    """Non-fatal extractor or validation failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str
    text_unit_index: int = Field(ge=0)
    extractor: str
    code: str
    message: str


class EnglishExtractionResult(BaseModel):
    """Candidates and diagnostics for one patent input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str
    baseline_candidates: tuple[TermCandidate, ...]
    refined_candidates: tuple[TermCandidate, ...] = ()
    refined_text_unit_indices: tuple[int, ...] = ()
    issues: tuple[ExtractionIssue, ...] = ()
