"""Deterministic reconciliation of overlapping extractor evidence."""

from __future__ import annotations

from collections import defaultdict

from chemterm.contracts.extraction import CandidateType, RawCandidate
from chemterm.taxonomy import CONCEPT_TYPE_BY_CODE


def _without_parent_types(types: set[CandidateType]) -> tuple[CandidateType, ...]:
    ancestor_codes: set[str] = set()
    for item in types:
        definition = CONCEPT_TYPE_BY_CODE[item.value]
        while definition.parent_code is not None:
            ancestor_codes.add(definition.parent_code)
            definition = CONCEPT_TYPE_BY_CODE[definition.parent_code]
    return tuple(sorted((item for item in types if item.value not in ancestor_codes), key=str))


class ExactSpanCandidateReconciler:
    """Merge exact spans while retaining every extractor's evidence."""

    name = "exact_span_reconciler"
    version = "1.0"

    def reconcile(
        self,
        text: str,
        candidates: tuple[RawCandidate, ...],
    ) -> tuple[RawCandidate, ...]:
        """Merge exact duplicates and mark incompatible type evidence for review."""

        groups: dict[tuple[int, int, str], list[RawCandidate]] = defaultdict(list)
        for candidate in candidates:
            if text[candidate.start : candidate.end] != candidate.text:
                raise ValueError("reconciler received an ungrounded candidate")
            groups[(candidate.start, candidate.end, candidate.text)].append(candidate)

        reconciled: list[RawCandidate] = []
        for (_, _, _), group in groups.items():
            if len(group) == 1:
                reconciled.append(group[0])
                continue

            types = _without_parent_types({item for candidate in group for item in candidate.types})
            roles = tuple(
                sorted(
                    {item for candidate in group for item in candidate.roles},
                    key=lambda item: item.value,
                )
            )
            top_level_types = {
                self._top_level_type(item)
                for item in types
                if item not in {CandidateType.MEASUREMENT, CandidateType.OTHER_TECHNICAL_CONCEPT}
            }
            confidence = min(
                0.99,
                max(candidate.confidence for candidate in group) + 0.03 * (len(group) - 1),
            )
            first = group[0]
            reconciled.append(
                RawCandidate(
                    text=first.text,
                    start=first.start,
                    end=first.end,
                    types=types,
                    roles=roles,
                    proposed_definition=next(
                        (
                            candidate.proposed_definition
                            for candidate in group
                            if candidate.proposed_definition
                        ),
                        None,
                    ),
                    confidence=confidence,
                    extractor=self.name,
                    extractor_version=self.version,
                    raw_label="RECONCILED",
                    needs_review=any(candidate.needs_review for candidate in group)
                    or len(top_level_types) > 1,
                    metadata={
                        "extractors": sorted({candidate.extractor for candidate in group}),
                        "raw_labels": sorted(
                            {
                                candidate.raw_label
                                for candidate in group
                                if candidate.raw_label is not None
                            }
                        ),
                        "component_confidences": [
                            candidate.confidence
                            for candidate in sorted(group, key=lambda item: item.extractor)
                        ],
                    },
                )
            )
        return tuple(
            sorted(
                reconciled,
                key=lambda item: (item.start, item.end, item.text, item.extractor),
            )
        )

    @staticmethod
    def _top_level_type(candidate_type: CandidateType) -> str:
        definition = CONCEPT_TYPE_BY_CODE[candidate_type.value]
        while definition.parent_code is not None:
            definition = CONCEPT_TYPE_BY_CODE[definition.parent_code]
        return definition.code
