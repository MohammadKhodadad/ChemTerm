"""Exact-span LLM mapping over existing parallel-language text."""

from __future__ import annotations

import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from chemterm.contracts.extraction import TermCandidate
from chemterm.contracts.mapping import (
    MappingRelation,
    RawTargetMapping,
    TargetFormStatus,
)
from chemterm.llm.client import StructuredLlmClient
from chemterm.llm.grounding import ExactSpanError, ground_exact_span

_SYSTEM_PROMPT = """\
You align known English scientific terminology to terminology that is explicitly present
in a corresponding target-language patent text.

You are not translating or rewriting either document. For every source_id, locate the exact,
contiguous target substring expressing the same concept in this context. Copy target_text
exactly, including its source spelling and script, and return zero-based end-exclusive offsets.
Never generate a corrected spelling, transliteration, or phrase absent from target_text.
Texts may contain title and abstract section markers. Use both sections as context, but never
return marker text or create a mapping span crossing section boundaries.

Return exactly one decision per source_id:
- EXACT_EQUIVALENT: the target span denotes the same concept.
- CONTEXTUAL_EQUIVALENT: equivalent in this patent context but not a universal synonym.
- BROADER: the target concept is broader than the English concept.
- NARROWER: the target concept is narrower than the English concept.
- RELATED: related but not equivalent.
- NO_MATCH: no defensible target span exists.
- AMBIGUOUS: multiple or uncertain interpretations; needs_review must be true.

Also classify the target form:
- TRANSLATED: the target uses a different language-specific surface form.
- UNCHANGED: the source wording appears unchanged as a target-language label.
- LANGUAGE_NEUTRAL: an inherently language-neutral formula, identifier, or notation is reused.
- NOT_PRESENT: use only when no target span exists.
- UNKNOWN: evidence is insufficient.

Use NO_MATCH instead of inventing text. Use BROADER, NARROWER, or RELATED instead of attaching
non-equivalent terminology to the same concept. Preserve Chinese, Japanese, Cyrillic, and all
other native scripts. Source candidates and target text are provided directly; machine
translation is neither requested nor permitted.
"""


class ParallelMappingError(ValueError):
    """Raised when LLM mappings do not cover or match the parallel text."""


class LlmPairDecision(BaseModel):
    """One source-to-target LLM decision."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^E[0-9]+$")
    target_text: str | None = None
    target_start: int | None = Field(default=None, ge=0)
    target_end: int | None = Field(default=None, gt=0)
    relation: MappingRelation
    target_form_status: TargetFormStatus = TargetFormStatus.UNKNOWN
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    reason_code: str = Field(min_length=1, max_length=120)


class LlmParallelMappingResponse(BaseModel):
    """Strict response for one English/target text pair."""

    model_config = ConfigDict(extra="forbid")

    mappings: tuple[LlmPairDecision, ...]


class LlmParallelTextMapper:
    """Align English candidates to exact target spans with an LLM."""

    name = "schema_constrained_parallel_llm"

    def __init__(self, client: StructuredLlmClient) -> None:
        self.client = client
        self.version = client.model

    def map_terms(
        self,
        *,
        english_text: str,
        english_candidates: tuple[TermCandidate, ...],
        target_language: str,
        target_text: str,
    ) -> tuple[RawTargetMapping, ...]:
        """Return complete, validated decisions without translating text."""

        if not english_candidates:
            return ()

        source_ids = {f"E{index}" for index in range(len(english_candidates))}
        payload = {
            "english_text": english_text,
            "english_terms": [
                {
                    "source_id": f"E{index}",
                    "text": candidate.text,
                    "start": candidate.normalized_start,
                    "end": candidate.normalized_end,
                    "types": [item.value for item in candidate.types],
                }
                for index, candidate in enumerate(english_candidates)
            ],
            "target_language": target_language,
            "target_text": target_text,
            "allowed_relations": [item.value for item in MappingRelation],
        }
        raw_response = self.client.complete_json(
            system_prompt=_SYSTEM_PROMPT,
            payload=payload,
            response_model=LlmParallelMappingResponse,
        )
        response = LlmParallelMappingResponse.model_validate(raw_response)

        returned_ids = [item.source_id for item in response.mappings]
        if len(returned_ids) != len(set(returned_ids)):
            raise ParallelMappingError("LLM returned duplicate source_id decisions")
        if set(returned_ids) != source_ids:
            missing = sorted(source_ids - set(returned_ids))
            extra = sorted(set(returned_ids) - source_ids)
            raise ParallelMappingError(
                f"LLM decision coverage mismatch; missing={missing}, extra={extra}"
            )

        results: list[RawTargetMapping] = []
        for decision in response.mappings:
            source_index = int(decision.source_id[1:])
            grounded_start = decision.target_start
            grounded_end = decision.target_end
            if decision.target_text is not None:
                try:
                    grounded_start, grounded_end = ground_exact_span(
                        target_text,
                        decision.target_text,
                        hinted_start=decision.target_start,
                        hinted_end=decision.target_end,
                    )
                except ExactSpanError:
                    results.append(
                        RawTargetMapping(
                            source_candidate_index=source_index,
                            relation=MappingRelation.NO_MATCH,
                            target_form_status=TargetFormStatus.NOT_PRESENT,
                            confidence=0,
                            needs_review=True,
                            reason_code="UNGROUNDED_LLM_TARGET_REJECTED",
                        )
                    )
                    continue
            raw_mapping = RawTargetMapping(
                source_candidate_index=source_index,
                target_text=decision.target_text,
                target_start=grounded_start,
                target_end=grounded_end,
                relation=decision.relation,
                target_form_status=self._target_form_status(
                    english_candidates[source_index].text,
                    decision.target_text,
                    decision.target_form_status,
                ),
                confidence=decision.confidence,
                needs_review=decision.needs_review
                or decision.relation
                in {
                    MappingRelation.AMBIGUOUS,
                    MappingRelation.BROADER,
                    MappingRelation.NARROWER,
                    MappingRelation.RELATED,
                },
                reason_code=decision.reason_code,
            )
            results.append(raw_mapping)

        return tuple(sorted(results, key=lambda item: item.source_candidate_index))

    @staticmethod
    def _target_form_status(
        source_text: str,
        target_text: str | None,
        proposed: TargetFormStatus,
    ) -> TargetFormStatus:
        if target_text is None:
            return TargetFormStatus.NOT_PRESENT
        source_key = " ".join(unicodedata.normalize("NFKC", source_text).casefold().split())
        target_key = " ".join(unicodedata.normalize("NFKC", target_text).casefold().split())
        if source_key == target_key:
            if proposed == TargetFormStatus.LANGUAGE_NEUTRAL:
                return proposed
            return TargetFormStatus.UNCHANGED
        return TargetFormStatus.TRANSLATED
