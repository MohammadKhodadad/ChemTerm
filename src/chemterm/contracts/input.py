"""Source-independent patent input contracts."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue, field_validator

INPUT_CONTRACT_VERSION = "1.0"
_BCP47_PATTERN = re.compile(
    r"^[A-Za-z]{2,8}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-[A-Za-z0-9]{4,8})*$"
)


def canonicalize_language_tag(value: str) -> str:
    """Validate and canonicalize the common BCP 47 language-tag forms."""

    tag = value.strip().replace("_", "-")
    if not _BCP47_PATTERN.fullmatch(tag):
        raise ValueError(f"invalid BCP 47 language tag: {value!r}")

    parts = tag.split("-")
    canonical = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            canonical.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            canonical.append(part.upper())
        else:
            canonical.append(part.lower())
    return "-".join(canonical)


class TextUnitType(StrEnum):
    """Structural role of a transient input text unit."""

    TITLE = "title"
    ABSTRACT = "abstract"
    CLAIM = "claim"
    PARAGRAPH = "paragraph"
    DESCRIPTION = "description"
    OTHER = "other"


class TextOrigin(StrEnum):
    """Origin of a source-language text."""

    ORIGINAL = "original"
    OFFICIAL_TRANSLATION = "official_translation"
    MACHINE_TRANSLATION = "machine_translation"
    UNKNOWN = "unknown"


class TextUnit(BaseModel):
    """A language-tagged source text passed to extraction stages."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    language: str
    text: str = Field(min_length=1)
    unit_type: TextUnitType
    locator: str = Field(default="", max_length=500)
    text_origin: TextOrigin = TextOrigin.UNKNOWN
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        """Accept any valid common BCP 47 tag, not a fixed language list."""

        return canonicalize_language_tag(value)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject whitespace-only units while preserving source text."""

        if not value.strip():
            raise ValueError("text must contain non-whitespace characters")
        return value


class PatentInput(BaseModel):
    """Versioned transient record independent of provider and file format."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1.0"] = INPUT_CONTRACT_VERSION
    source_record_id: str = Field(min_length=1, max_length=500)
    family_id: str | None = Field(default=None, max_length=200)
    publication_number: str = Field(min_length=1, max_length=200)
    source_uri: HttpUrl | None = None
    text_units: tuple[TextUnit, ...] = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("source_record_id", "publication_number", mode="before")
    @classmethod
    def strip_identifiers(cls, value: object) -> object:
        """Canonicalize outer whitespace on required identifiers."""

        return value.strip() if isinstance(value, str) else value

    @field_validator("family_id", mode="before")
    @classmethod
    def strip_optional_identifier(cls, value: object) -> object:
        """Treat blank optional family IDs as missing."""

        if isinstance(value, str):
            return value.strip() or None
        return value

    def text_for_language(self, language: str) -> tuple[TextUnit, ...]:
        """Return text units matching a canonical language tag."""

        wanted = canonicalize_language_tag(language)
        return tuple(unit for unit in self.text_units if unit.language == wanted)
