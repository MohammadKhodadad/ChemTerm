"""Multilingual, chemistry-aware normalization."""

from chemterm.normalization.text import (
    NORMALIZATION_VERSION,
    NormalizedText,
    OffsetSpan,
    TermNormalizationProfile,
    normalize_source_text,
    normalize_term,
)

__all__ = [
    "NORMALIZATION_VERSION",
    "NormalizedText",
    "OffsetSpan",
    "TermNormalizationProfile",
    "normalize_source_text",
    "normalize_term",
]
