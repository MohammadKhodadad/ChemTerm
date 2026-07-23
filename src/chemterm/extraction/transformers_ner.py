"""Optional Hugging Face token-classification NER adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from chemterm.contracts.extraction import (
    CandidateType,
    ContextRole,
    RawCandidate,
)

_CHEMU_TYPE_MAP: dict[str, CandidateType] = {
    "STARTING_MATERIAL": CandidateType.CHEMICAL_ENTITY,
    "REAGENT_CATALYST": CandidateType.CHEMICAL_ENTITY,
    "REACTION_PRODUCT": CandidateType.CHEMICAL_ENTITY,
    "SOLVENT": CandidateType.CHEMICAL_ENTITY,
    "OTHER_COMPOUND": CandidateType.CHEMICAL_ENTITY,
    "TEMPERATURE": CandidateType.MEASUREMENT,
    "TIME": CandidateType.MEASUREMENT,
    "YIELD_PERCENT": CandidateType.MEASUREMENT,
    "YIELD_OTHER": CandidateType.MEASUREMENT,
    "EXAMPLE_LABEL": CandidateType.OTHER_TECHNICAL_CONCEPT,
}
_CHEMU_ROLE_MAP: dict[str, ContextRole] = {
    "STARTING_MATERIAL": ContextRole.STARTING_MATERIAL,
    "REAGENT_CATALYST": ContextRole.REAGENT,
    "REACTION_PRODUCT": ContextRole.REACTION_PRODUCT,
    "SOLVENT": ContextRole.SOLVENT,
}


class TransformersNerExtractor:
    """Adapt any character-offset Hugging Face NER model to ChemTerm."""

    name = "transformers_ner"

    def __init__(
        self,
        model_name: str,
        *,
        pipeline_factory: Callable[..., Any] | None = None,
        label_types: dict[str, CandidateType] | None = None,
        label_roles: dict[str, ContextRole] | None = None,
    ) -> None:
        self.model_name = model_name
        self.version = model_name
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any | None = None
        self._label_types = label_types or _CHEMU_TYPE_MAP
        self._label_roles = label_roles or _CHEMU_ROLE_MAP

    def extract(self, text: str) -> tuple[RawCandidate, ...]:
        """Run token classification and preserve exact source spans."""

        model = self._get_pipeline()
        predictions = model(text)
        candidates: list[RawCandidate] = []

        for prediction in predictions:
            start = int(prediction["start"])
            end = int(prediction["end"])
            if start < 0 or end <= start or end > len(text):
                raise ValueError(f"NER returned invalid span [{start}, {end})")

            raw_label = (
                str(prediction.get("entity_group") or prediction.get("entity") or "UNKNOWN")
                .removeprefix("B-")
                .removeprefix("I-")
            )
            candidate_type = self._label_types.get(raw_label, self._fallback_type(raw_label))
            role = self._label_roles.get(raw_label)
            candidates.append(
                RawCandidate(
                    text=text[start:end],
                    start=start,
                    end=end,
                    types=(candidate_type,),
                    roles=(role,) if role else (),
                    confidence=float(prediction.get("score", 0)),
                    extractor=self.name,
                    extractor_version=self.version,
                    raw_label=raw_label,
                    needs_review=raw_label == "REAGENT_CATALYST",
                    metadata={"model_name": self.model_name},
                )
            )
        return tuple(candidates)

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        factory = self._pipeline_factory
        if factory is None:
            try:
                from transformers import pipeline
            except ImportError as error:
                raise RuntimeError(
                    "Transformers NER is optional; install the 'ner' project extra"
                ) from error
            factory = pipeline

        self._pipeline = factory(
            "token-classification",
            model=self.model_name,
            tokenizer=self.model_name,
            aggregation_strategy="simple",
        )
        return self._pipeline

    @staticmethod
    def _fallback_type(label: str) -> CandidateType:
        normalized = label.upper()
        if any(token in normalized for token in ("CHEM", "COMPOUND", "SUBSTANCE")):
            return CandidateType.CHEMICAL_ENTITY
        if "MATERIAL" in normalized:
            return CandidateType.MATERIAL
        return CandidateType.OTHER_TECHNICAL_CONCEPT
