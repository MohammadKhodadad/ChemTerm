"""Transparent patent-oriented multi-word terminology extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from chemterm.contracts.extraction import (
    CandidateType,
    ContextRole,
    RawCandidate,
)

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*")
_BOUNDARIES = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "comprising",
        "consisting",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "using",
        "with",
    }
)
_HEAD_TYPES: dict[str, CandidateType] = {
    "alloy": CandidateType.MATERIAL,
    "coating": CandidateType.MATERIAL,
    "composite": CandidateType.MATERIAL,
    "film": CandidateType.MATERIAL,
    "layer": CandidateType.MATERIAL,
    "material": CandidateType.MATERIAL,
    "matrix": CandidateType.MATERIAL,
    "polymer": CandidateType.MATERIAL,
    "composition": CandidateType.MIXTURE_OR_COMPOSITION,
    "dispersion": CandidateType.MIXTURE_OR_COMPOSITION,
    "emulsion": CandidateType.MIXTURE_OR_COMPOSITION,
    "formulation": CandidateType.MIXTURE_OR_COMPOSITION,
    "mixture": CandidateType.MIXTURE_OR_COMPOSITION,
    "solution": CandidateType.MIXTURE_OR_COMPOSITION,
    "suspension": CandidateType.MIXTURE_OR_COMPOSITION,
    "conversion": CandidateType.PROCESS,
    "manufacturing": CandidateType.PROCESS,
    "polymerization": CandidateType.PROCESS,
    "process": CandidateType.PROCESS,
    "purification": CandidateType.PROCESS,
    "reaction": CandidateType.PROCESS,
    "recovery": CandidateType.PROCESS,
    "separation": CandidateType.PROCESS,
    "synthesis": CandidateType.PROCESS,
    "treatment": CandidateType.PROCESS,
    "conductivity": CandidateType.PROPERTY,
    "life": CandidateType.PROPERTY,
    "resistance": CandidateType.PROPERTY,
    "stability": CandidateType.PROPERTY,
    "strength": CandidateType.PROPERTY,
    "viscosity": CandidateType.PROPERTY,
    "cell": CandidateType.EQUIPMENT,
    "cells": CandidateType.EQUIPMENT,
    "circuit": CandidateType.EQUIPMENT,
    "diode": CandidateType.EQUIPMENT,
    "plant": CandidateType.EQUIPMENT,
    "reactor": CandidateType.EQUIPMENT,
    "vessel": CandidateType.EQUIPMENT,
    "restoration": CandidateType.APPLICATION,
}
_HEAD_ROLES: dict[str, ContextRole] = {
    "coating": ContextRole.COATING,
    "matrix": ContextRole.MATRIX,
}


@dataclass(frozen=True, slots=True)
class _Token:
    text: str
    start: int
    end: int


class TechnicalPhraseExtractor:
    """Generate nested English technical phrases using auditable rules."""

    name = "technical_phrase_rules"
    version = "1.0"

    def __init__(self, *, max_tokens: int = 4) -> None:
        if max_tokens < 2:
            raise ValueError("max_tokens must be at least 2")
        self.max_tokens = max_tokens

    def extract(self, text: str) -> tuple[RawCandidate, ...]:
        """Extract nested phrases ending in domain-relevant head words."""

        tokens = tuple(
            _Token(match.group(0), match.start(), match.end()) for match in _TOKEN.finditer(text)
        )
        candidates: dict[tuple[int, int, CandidateType], RawCandidate] = {}

        for head_index, head in enumerate(tokens):
            head_key = head.text.casefold()
            candidate_type = _HEAD_TYPES.get(head_key)
            if candidate_type is None:
                continue

            phrase_tokens = self._backward_phrase(tokens, head_index, text)
            for length in range(2, len(phrase_tokens) + 1):
                selected = phrase_tokens[-length:]
                start, end = selected[0].start, selected[-1].end
                phrase = text[start:end]
                confidence = min(0.88, 0.64 + (0.05 * length))
                candidate = RawCandidate(
                    text=phrase,
                    start=start,
                    end=end,
                    types=(candidate_type,),
                    roles=(_HEAD_ROLES[head_key],) if head_key in _HEAD_ROLES else (),
                    confidence=confidence,
                    extractor=self.name,
                    extractor_version=self.version,
                    raw_label=f"{candidate_type.value}_PHRASE",
                    needs_review=True,
                    metadata={"head": head.text, "token_count": length},
                )
                candidates[(start, end, candidate_type)] = candidate

        return tuple(
            sorted(candidates.values(), key=lambda item: (item.start, item.end, item.text))
        )

    def _backward_phrase(
        self,
        tokens: tuple[_Token, ...],
        head_index: int,
        text: str,
    ) -> tuple[_Token, ...]:
        selected = [tokens[head_index]]
        current_index = head_index

        while current_index > 0 and len(selected) < self.max_tokens:
            previous = tokens[current_index - 1]
            current = tokens[current_index]
            separator = text[previous.end : current.start]
            if previous.text.casefold() in _BOUNDARIES or not separator.isspace():
                break
            selected.append(previous)
            current_index -= 1

        return tuple(reversed(selected))
