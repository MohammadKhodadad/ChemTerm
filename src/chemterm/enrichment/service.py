"""Orchestration for bounded external concept-reference discovery."""

from __future__ import annotations

from collections.abc import Iterable

from chemterm.enrichment.contracts import (
    ConceptEnrichmentResult,
    ExternalConceptReference,
    ExternalReferenceIssue,
    ExternalReferenceProvider,
)
from chemterm.resolution.contracts import ConceptProposal


class ConceptEnrichmentService:
    """Query independent authorities without letting one failure discard others."""

    def __init__(self, providers: Iterable[ExternalReferenceProvider]) -> None:
        self.providers = tuple(providers)
        if not self.providers:
            raise ValueError("at least one external reference provider is required")

    def enrich(self, proposal: ConceptProposal) -> ConceptEnrichmentResult:
        references: dict[tuple[str, str], ExternalConceptReference] = {}
        issues: list[ExternalReferenceIssue] = []
        for provider in self.providers:
            try:
                matches = provider.lookup(proposal)
            except Exception as error:
                issues.append(
                    ExternalReferenceIssue(
                        provider=provider.name,
                        code="LOOKUP_FAILED",
                        message=str(error),
                    )
                )
                continue
            for match in matches:
                key = (match.namespace, match.external_id)
                current = references.get(key)
                if current is None or match.confidence > current.confidence:
                    references[key] = match

        return ConceptEnrichmentResult(
            proposal_id=proposal.proposal_id,
            term=proposal.term,
            references=tuple(
                sorted(
                    references.values(),
                    key=lambda item: (
                        item.needs_review,
                        -item.confidence,
                        item.namespace,
                        item.external_id,
                    ),
                )
            ),
            issues=tuple(issues),
        )
