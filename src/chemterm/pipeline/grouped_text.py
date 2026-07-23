"""Offset-safe grouping of source text units for one model request."""

from __future__ import annotations

from dataclasses import dataclass

from chemterm.contracts.extraction import RawCandidate, TermCandidate
from chemterm.contracts.input import PatentInput, TextUnitType
from chemterm.normalization import NormalizedText, normalize_source_text


@dataclass(frozen=True)
class GroupedTextSegment:
    """One source unit's position inside grouped normalized text."""

    unit_index: int
    language: str
    unit_type: TextUnitType
    locator: str
    normalized: NormalizedText
    start: int
    end: int


@dataclass(frozen=True)
class GroupedText:
    """Several source units presented together without losing local offsets."""

    text: str
    segments: tuple[GroupedTextSegment, ...]

    @classmethod
    def from_record(cls, record: PatentInput, unit_indices: tuple[int, ...]) -> GroupedText:
        parts: list[str] = []
        segments: list[GroupedTextSegment] = []
        for unit_index in unit_indices:
            unit = record.text_units[unit_index]
            normalized = normalize_source_text(unit.text)
            header = (
                f'[[SECTION id="U{unit_index}" type="{unit.unit_type.value}" '
                f'locator="{unit.locator}"]]\n'
            )
            if parts:
                parts.append("\n")
            parts.append(header)
            start = sum(len(part) for part in parts)
            parts.append(normalized.normalized_text)
            end = start + len(normalized.normalized_text)
            parts.append("\n[[END SECTION]]\n")
            segments.append(
                GroupedTextSegment(
                    unit_index=unit_index,
                    language=unit.language,
                    unit_type=unit.unit_type,
                    locator=unit.locator,
                    normalized=normalized,
                    start=start,
                    end=end,
                )
            )
        return cls(text="".join(parts), segments=tuple(segments))

    def segment_for_unit(self, unit_index: int) -> GroupedTextSegment:
        for segment in self.segments:
            if segment.unit_index == unit_index:
                return segment
        raise ValueError(f"text unit {unit_index} is not present in grouped text")

    def local_span(self, start: int, end: int) -> tuple[GroupedTextSegment, int, int]:
        """Map a grouped span to exactly one source unit."""

        for segment in self.segments:
            if segment.start <= start < end <= segment.end:
                return segment, start - segment.start, end - segment.start
        raise ValueError(f"grouped span [{start}, {end}) crosses or targets section metadata")

    def shift_raw(self, candidate: RawCandidate, unit_index: int) -> RawCandidate:
        segment = self.segment_for_unit(unit_index)
        return candidate.model_copy(
            update={
                "start": candidate.start + segment.start,
                "end": candidate.end + segment.start,
            }
        )

    def shift_term(self, candidate: TermCandidate) -> TermCandidate:
        segment = self.segment_for_unit(candidate.text_unit_index)
        return candidate.model_copy(
            update={
                "normalized_start": candidate.normalized_start + segment.start,
                "normalized_end": candidate.normalized_end + segment.start,
            }
        )
