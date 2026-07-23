"""Versioned contracts shared across pipeline boundaries."""

from chemterm.contracts.extraction import (
    CandidateType,
    ContextRole,
    EnglishExtractionResult,
    ExtractionIssue,
    RawCandidate,
    TermCandidate,
)
from chemterm.contracts.input import (
    INPUT_CONTRACT_VERSION,
    PatentInput,
    TextOrigin,
    TextUnit,
    TextUnitType,
)
from chemterm.contracts.mapping import (
    MappingIssue,
    MappingRelation,
    MultilingualMappingResult,
    RawTargetMapping,
    TargetTermMapping,
)

__all__ = [
    "CandidateType",
    "ContextRole",
    "EnglishExtractionResult",
    "ExtractionIssue",
    "INPUT_CONTRACT_VERSION",
    "MappingIssue",
    "MappingRelation",
    "MultilingualMappingResult",
    "PatentInput",
    "RawCandidate",
    "RawTargetMapping",
    "TermCandidate",
    "TargetTermMapping",
    "TextOrigin",
    "TextUnit",
    "TextUnitType",
]
