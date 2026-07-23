"""Target-language mapper extension point."""

from __future__ import annotations

from typing import Protocol

from chemterm.contracts.extraction import TermCandidate
from chemterm.contracts.mapping import RawTargetMapping


class ParallelTextMapper(Protocol):
    """Map known English candidates to exact target-text spans."""

    name: str
    version: str

    def map_terms(
        self,
        *,
        english_text: str,
        english_candidates: tuple[TermCandidate, ...],
        target_language: str,
        target_text: str,
    ) -> tuple[RawTargetMapping, ...]:
        """Return one decision for every English candidate."""

        ...
