"""Vocabulary-grounded, candidate-bounded LLM concept resolution."""

from __future__ import annotations

from chemterm.llm.client import StructuredLlmClient
from chemterm.resolution.contracts import (
    ConceptCard,
    ConceptProposal,
    ConceptResolutionDecision,
    ResolutionOutcome,
    ResolutionReason,
    ResolutionVocabulary,
)

_SYSTEM_PROMPT = """\
You resolve one proposed English chemical or technical concept against a small,
retrieved list of existing concepts.

Use only the supplied controlled type definitions, identifier definitions, reason
codes, and candidate concept IDs. Retrieval scores are clues, not proof. Never
invent a concept ID, identifier, type, synonym, structure, or unstated fact.

SAME_CONCEPT means the proposal and candidate denote the same meaning, not merely
related strings. NEW_CONCEPT means no candidate is the same. RELATED_NOT_SAME means
there is a useful existing relation but identity is false. AMBIGUOUS means the
evidence cannot safely distinguish these outcomes.

Apply every supplied non-merge rule. Prefer AMBIGUOUS with needs_review=true over a
risky merge. Confidence is confidence in the selected outcome, not retrieval
similarity. Give concise controlled reason codes only.
"""


class LlmConceptResolver:
    """Resolve proposals without allowing the LLM to search or invent records."""

    def __init__(self, client: StructuredLlmClient) -> None:
        self.client = client

    def resolve(
        self,
        proposal: ConceptProposal,
        candidates: tuple[ConceptCard, ...],
        vocabulary: ResolutionVocabulary,
    ) -> ConceptResolutionDecision:
        """Return a strict decision referencing only retrieved candidates."""

        if not candidates:
            return ConceptResolutionDecision(
                proposal_id=proposal.proposal_id,
                outcome=ResolutionOutcome.NEW_CONCEPT,
                confidence=1,
                reason_codes=(ResolutionReason.NO_CANDIDATE,),
                needs_review=False,
            )

        payload = {
            "proposal": proposal.model_dump(mode="json"),
            "candidate_concepts": [candidate.model_dump(mode="json") for candidate in candidates],
            "controlled_vocabulary": vocabulary.model_dump(mode="json"),
            "allowed_outcomes": [item.value for item in ResolutionOutcome],
            "allowed_reason_codes": [item.value for item in ResolutionReason],
        }
        raw = self.client.complete_json(
            system_prompt=_SYSTEM_PROMPT,
            payload=payload,
            response_model=ConceptResolutionDecision,
        )
        decision = ConceptResolutionDecision.model_validate(raw)
        if decision.proposal_id != proposal.proposal_id:
            raise ValueError("LLM returned a decision for a different proposal")

        allowed_ids = {candidate.concept_id for candidate in candidates}
        for concept_id in (decision.concept_id, decision.related_concept_id):
            if concept_id is not None and concept_id not in allowed_ids:
                raise ValueError("LLM referenced a concept outside the candidate set")
        if decision.outcome is ResolutionOutcome.AMBIGUOUS and not decision.needs_review:
            raise ValueError("AMBIGUOUS decisions must require review")
        return decision
