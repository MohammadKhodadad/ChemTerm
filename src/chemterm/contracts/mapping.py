"""Contracts for mapping known English terms into parallel target text."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chemterm.contracts.extraction import CandidateType


class MappingRelation(StrEnum):
    """Relationship between an English concept and target-language span."""

    EXACT_EQUIVALENT = "EXACT_EQUIVALENT"
    CONTEXTUAL_EQUIVALENT = "CONTEXTUAL_EQUIVALENT"
    BROADER = "BROADER"
    NARROWER = "NARROWER"
    RELATED = "RELATED"
    NO_MATCH = "NO_MATCH"
    AMBIGUOUS = "AMBIGUOUS"


class RawTargetMapping(BaseModel):
    """Mapper output using offsets in normalized target text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_candidate_index: int = Field(ge=0)
    target_text: str | None = None
    target_start: int | None = Field(default=None, ge=0)
    target_end: int | None = Field(default=None, gt=0)
    relation: MappingRelation
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    reason_code: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_optional_target_span(self) -> RawTargetMapping:
        """Require all target fields together for matched relations."""

        target_values = (self.target_text, self.target_start, self.target_end)
        has_all_target = all(item is not None for item in target_values)
        has_any_target = any(item is not None for item in target_values)
        if has_any_target and not has_all_target:
            raise ValueError("target text and offsets must be provided together")
        if (
            self.relation
            not in {
                MappingRelation.NO_MATCH,
                MappingRelation.AMBIGUOUS,
            }
            and not has_all_target
        ):
            raise ValueError(f"{self.relation.value} requires an exact target span")
        if self.relation == MappingRelation.NO_MATCH and has_any_target:
            raise ValueError("NO_MATCH cannot include a target span")
        if (
            self.target_start is not None
            and self.target_end is not None
            and self.target_end <= self.target_start
        ):
            raise ValueError("target_end must be greater than target_start")
        return self


class TargetTermMapping(BaseModel):
    """Validated multilingual mapping grounded in both source texts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str
    source_text_unit_index: int = Field(ge=0)
    source_candidate_index: int = Field(ge=0)
    source_text: str
    source_types: tuple[CandidateType, ...]
    target_language: str
    target_text_unit_index: int = Field(ge=0)
    target_text: str | None = None
    target_normalized_start: int | None = Field(default=None, ge=0)
    target_normalized_end: int | None = Field(default=None, gt=0)
    target_original_start: int | None = Field(default=None, ge=0)
    target_original_end: int | None = Field(default=None, gt=0)
    relation: MappingRelation
    confidence: float = Field(ge=0, le=1)
    needs_review: bool
    mapper: str
    mapper_version: str
    reason_code: str


class MappingIssue(BaseModel):
    """Non-fatal target mapper or grounding failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str
    target_text_unit_index: int = Field(ge=0)
    target_language: str
    mapper: str
    code: str
    message: str


class MultilingualMappingResult(BaseModel):
    """All target-language decisions for one patent input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str
    mappings: tuple[TargetTermMapping, ...]
    issues: tuple[MappingIssue, ...] = ()
