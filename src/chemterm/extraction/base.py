"""Extractor and refiner extension points."""

from __future__ import annotations

from typing import Protocol

from chemterm.contracts.extraction import RawCandidate


class CandidateExtractor(Protocol):
    """Independent source-grounded candidate generator."""

    name: str
    version: str

    def extract(self, text: str) -> tuple[RawCandidate, ...]:
        """Extract candidates using normalized-text offsets."""

        ...


class CandidateRefiner(Protocol):
    """Candidate reviewer that may confirm, modify, or add exact spans."""

    name: str
    version: str

    def refine(
        self,
        text: str,
        candidates: tuple[RawCandidate, ...],
    ) -> tuple[RawCandidate, ...]:
        """Return refined candidates grounded in the same text."""

        ...
