"""Schema-constrained LLM terminology refinement."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chemterm.contracts.extraction import (
    CandidateType,
    ContextRole,
    RawCandidate,
)
from chemterm.llm.client import StructuredLlmClient
from chemterm.llm.grounding import ExactSpanError, ground_exact_span
from chemterm.taxonomy import (
    SCOPE_POLICY_VERSION,
    render_scope_policy,
    render_type_definitions,
)

_SYSTEM_PROMPT = f"""\
You extract English scientific and patent terminology for a multilingual chemical glossary.

Apply terminology scope policy {SCOPE_POLICY_VERSION} exactly:
{render_scope_policy()}

Use only exact, contiguous substrings from the provided text and the allowed type/role enums.
The text may contain title and abstract section markers. Use both sections as context, but
never return marker text or create a term spanning two sections. Offsets refer to the complete
grouped text.
NER and rule candidates are incomplete hints: confirm useful candidates and add missed exact spans.
Prefer meaningful multi-word terms. Keep nested terms only when each is independently useful.
Choose the most specific supported type; use a parent type only when evidence is insufficient.
Never combine a parent type with its child. Do not use CHEMICAL_ENTITY, PROCESS, or PROPERTY
when a more specific child is supported. Broad substance families such as protein or starch
are CHEMICAL_CLASS; use POLYMER as an additional type only when polymer identity is explicit.
For every baseline candidate, return IN_SCOPE, OUT_OF_SCOPE, or REVIEW. OUT_OF_SCOPE decisions
are audited but mechanically removed. Add missed spans only when they are IN_SCOPE.
When the title supplies no chemical or material modifier, generic power plants, light-emitting
diodes, conversion circuits, donor organs, dental restorations, and analogous concepts are
OUT_OF_SCOPE. Fuel cells remain IN_SCOPE because their identity is intrinsically electrochemical.
For every returned term, provide a concise contextual definition using only facts explicit in
the source text. If the text merely names the concept, return null. Do not add textbook facts,
unstated structures, compositions, mechanisms, or applications.
Do not translate, rewrite, invent identifiers, or silently merge salts, hydrates,
stereoisomers, polymers, mixtures, classes, or related concepts.
Use needs_review=true for ambiguity. Offsets are zero-based and end-exclusive.

Type meanings:
{render_type_definitions()}
"""


class LlmOutputError(ValueError):
    """Raised when structured output is schema-valid but not source-grounded."""


class LlmTermDecision(BaseModel):
    """One exact-span LLM terminology decision."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    types: tuple[CandidateType, ...] = Field(min_length=1)
    roles: tuple[ContextRole, ...] = ()
    proposed_definition: str | None = Field(default=None, max_length=1_000)
    scope_decision: Literal["IN_SCOPE", "OUT_OF_SCOPE", "REVIEW"] = "IN_SCOPE"
    confidence: float = Field(ge=0, le=1)
    source: Literal["candidate_confirmed", "candidate_corrected", "llm_added"]
    needs_review: bool = False
    reason_code: str = Field(min_length=1, max_length=120)

    @field_validator("proposed_definition", mode="before")
    @classmethod
    def normalize_null_definition(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in {"null", "none", "n/a"}:
            return None
        return value


class LlmExtractionResponse(BaseModel):
    """Strict top-level response returned by the LLM."""

    model_config = ConfigDict(extra="forbid")

    terms: tuple[LlmTermDecision, ...]


class LlmTermRefiner:
    """Use an LLM to review candidates and add missed exact spans."""

    name = "schema_constrained_llm"

    def __init__(self, client: StructuredLlmClient) -> None:
        self.client = client
        self.version = client.model

    def refine(
        self,
        text: str,
        candidates: tuple[RawCandidate, ...],
    ) -> tuple[RawCandidate, ...]:
        """Return a strictly validated final candidate proposal."""

        payload = {
            "text": text,
            "allowed_types": [item.value for item in CandidateType],
            "allowed_roles": [item.value for item in ContextRole],
            "candidates": [
                {
                    "text": candidate.text,
                    "start": candidate.start,
                    "end": candidate.end,
                    "types": [item.value for item in candidate.types],
                    "roles": [item.value for item in candidate.roles],
                    "extractor": candidate.extractor,
                    "raw_label": candidate.raw_label,
                    "confidence": candidate.confidence,
                }
                for candidate in candidates
            ],
        }
        raw_response = self.client.complete_json(
            system_prompt=_SYSTEM_PROMPT,
            payload=payload,
            response_model=LlmExtractionResponse,
        )
        response = LlmExtractionResponse.model_validate(raw_response)

        seen: set[tuple[int, int, tuple[CandidateType, ...]]] = set()
        refined: list[RawCandidate] = []
        for term in response.terms:
            if term.scope_decision == "OUT_OF_SCOPE":
                continue
            try:
                start, end = ground_exact_span(
                    text,
                    term.text,
                    hinted_start=term.start,
                    hinted_end=term.end,
                )
            except ExactSpanError as error:
                raise LlmOutputError(
                    f"LLM term {term.text!r} does not match source span [{term.start}, {term.end})"
                ) from error
            key = (start, end, term.types)
            if key in seen:
                raise LlmOutputError(f"LLM returned duplicate term {term.text!r}")
            seen.add(key)
            refined.append(
                RawCandidate(
                    text=term.text,
                    start=start,
                    end=end,
                    types=term.types,
                    roles=term.roles,
                    proposed_definition=term.proposed_definition,
                    confidence=term.confidence,
                    extractor=self.name,
                    extractor_version=self.version,
                    raw_label="LLM_REFINED",
                    needs_review=term.needs_review or term.scope_decision == "REVIEW",
                    metadata={
                        "decision_source": term.source,
                        "reason_code": term.reason_code,
                        "scope_decision": term.scope_decision,
                    },
                )
            )
        return tuple(refined)
