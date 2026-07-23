"""Unicode-safe source text and terminology normalization."""

from __future__ import annotations

import html
import re
import unicodedata
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

NORMALIZATION_VERSION = "1.0"
_HTML_ENTITY = re.compile(r"&(?:#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)
_APOSTROPHE_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u02bc": "'",
        "\uff07": "'",
    }
)


class OffsetSpan(BaseModel):
    """Half-open source range represented by one normalized character."""

    model_config = ConfigDict(frozen=True)

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> OffsetSpan:
        """Require a non-empty, ordered range."""

        if self.end <= self.start:
            raise ValueError("offset span end must be greater than start")
        return self


class NormalizedText(BaseModel):
    """Display-normalized text with a mapping back to source characters."""

    model_config = ConfigDict(frozen=True)

    normalization_version: str = NORMALIZATION_VERSION
    original_text: str
    normalized_text: str
    offset_map: tuple[OffsetSpan, ...]

    @model_validator(mode="after")
    def validate_offset_count(self) -> NormalizedText:
        """Keep exactly one source range per normalized character."""

        if len(self.normalized_text) != len(self.offset_map):
            raise ValueError("offset map length must equal normalized text length")
        return self

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a normalized half-open range back to the original text."""

        if start < 0 or end <= start or end > len(self.offset_map):
            raise ValueError("invalid normalized range")
        selected = self.offset_map[start:end]
        return min(item.start for item in selected), max(item.end for item in selected)


class TermNormalizationProfile(StrEnum):
    """Profiles that avoid applying unsafe generic rules to chemistry."""

    GENERAL = "general"
    CHEMICAL_NAME = "chemical_name"
    FORMULA = "formula"
    IDENTIFIER = "identifier"
    PATENT_LABEL = "patent_label"


def normalize_source_text(value: str) -> NormalizedText:
    """Normalize source text for extraction while retaining exact provenance."""

    decoded, spans = _decode_html_entities(value)
    unicode_text, unicode_spans = _normalize_unicode_clusters(decoded, spans)
    normalized, normalized_spans = _normalize_whitespace(unicode_text, unicode_spans)

    return NormalizedText(
        original_text=value,
        normalized_text=normalized,
        offset_map=tuple(OffsetSpan(start=start, end=end) for start, end in normalized_spans),
    )


def normalize_term(value: str, profile: TermNormalizationProfile) -> str:
    """Create a comparison key without losing chemistry-significant case."""

    normalized = normalize_source_text(value).normalized_text
    normalized = normalized.translate(_DASH_TRANSLATION).translate(_APOSTROPHE_TRANSLATION)

    if profile in {
        TermNormalizationProfile.GENERAL,
        TermNormalizationProfile.PATENT_LABEL,
    }:
        normalized = unicodedata.normalize("NFKC", normalized).casefold()
    else:
        normalized = unicodedata.normalize("NFC", normalized)

    normalized = re.sub(r"\s*([:/])\s*", r"\1", normalized)
    normalized = re.sub(r"\(\s+", "(", normalized)
    normalized = re.sub(r"\s+\)", ")", normalized)

    if profile in {
        TermNormalizationProfile.CHEMICAL_NAME,
        TermNormalizationProfile.FORMULA,
        TermNormalizationProfile.IDENTIFIER,
        TermNormalizationProfile.PATENT_LABEL,
    }:
        normalized = re.sub(r"\s*-\s*", "-", normalized)

    if profile in {
        TermNormalizationProfile.FORMULA,
        TermNormalizationProfile.IDENTIFIER,
    }:
        normalized = re.sub(r"\s+", "", normalized)

    return normalized.strip()


def _decode_html_entities(value: str) -> tuple[str, list[tuple[int, int]]]:
    output: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0

    for match in _HTML_ENTITY.finditer(value):
        for index in range(cursor, match.start()):
            output.append(value[index])
            spans.append((index, index + 1))

        decoded = html.unescape(match.group(0))
        for character in decoded:
            output.append(character)
            spans.append((match.start(), match.end()))
        cursor = match.end()

    for index in range(cursor, len(value)):
        output.append(value[index])
        spans.append((index, index + 1))

    return "".join(output), spans


def _normalize_unicode_clusters(
    value: str,
    spans: list[tuple[int, int]],
) -> tuple[str, list[tuple[int, int]]]:
    output: list[str] = []
    output_spans: list[tuple[int, int]] = []
    index = 0

    while index < len(value):
        cluster_end = index + 1
        while cluster_end < len(value) and unicodedata.combining(value[cluster_end]):
            cluster_end += 1

        cluster = unicodedata.normalize("NFC", value[index:cluster_end])
        source_start = min(span[0] for span in spans[index:cluster_end])
        source_end = max(span[1] for span in spans[index:cluster_end])
        for character in cluster:
            output.append(character)
            output_spans.append((source_start, source_end))
        index = cluster_end

    return "".join(output), output_spans


def _normalize_whitespace(
    value: str,
    spans: list[tuple[int, int]],
) -> tuple[str, list[tuple[int, int]]]:
    output: list[str] = []
    output_spans: list[tuple[int, int]] = []
    index = 0

    while index < len(value):
        if not value[index].isspace():
            output.append(value[index])
            output_spans.append(spans[index])
            index += 1
            continue

        whitespace_end = index + 1
        while whitespace_end < len(value) and value[whitespace_end].isspace():
            whitespace_end += 1

        if output and whitespace_end < len(value):
            output.append(" ")
            output_spans.append(
                (
                    min(span[0] for span in spans[index:whitespace_end]),
                    max(span[1] for span in spans[index:whitespace_end]),
                )
            )
        index = whitespace_end

    return "".join(output), output_spans
