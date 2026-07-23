"""Composable English candidate extraction pipeline."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from chemterm.config import get_settings
from chemterm.contracts.extraction import (
    EnglishExtractionResult,
    ExtractionIssue,
    RawCandidate,
    TermCandidate,
)
from chemterm.contracts.input import PatentInput
from chemterm.extraction import (
    CHEMU_MODEL,
    CandidateExtractor,
    CandidateReconciler,
    CandidateRefiner,
    ChemDataExtractorNerExtractor,
    ChemUNerExtractor,
    DeterministicRuleExtractor,
    ExactSpanCandidateReconciler,
    TechnicalPhraseExtractor,
    TransformersNerExtractor,
)
from chemterm.llm import LlmTermRefiner, OpenAICompatibleJsonClient
from chemterm.normalization import NormalizedText, normalize_source_text


class EnglishExtractionPipeline:
    """Run independent baseline extractors and optional bounded refiners."""

    def __init__(
        self,
        *,
        extractors: Iterable[CandidateExtractor],
        refiners: Iterable[CandidateRefiner] = (),
        reconciler: CandidateReconciler | None = None,
    ) -> None:
        self.extractors = tuple(extractors)
        self.refiners = tuple(refiners)
        self.reconciler = reconciler or ExactSpanCandidateReconciler()
        if not self.extractors:
            raise ValueError("at least one candidate extractor is required")

    def extract(self, record: PatentInput) -> EnglishExtractionResult:
        """Extract all English text units in one canonical input record."""

        baseline: list[TermCandidate] = []
        refined: list[TermCandidate] = []
        refined_units: set[int] = set()
        issues: list[ExtractionIssue] = []

        for unit_index, unit in enumerate(record.text_units):
            if unit.language.split("-", maxsplit=1)[0] != "en":
                continue

            normalized = normalize_source_text(unit.text)
            valid_raw: list[RawCandidate] = []
            for extractor in self.extractors:
                try:
                    predictions = extractor.extract(normalized.normalized_text)
                except Exception as error:
                    issues.append(
                        self._issue(
                            record,
                            unit_index,
                            extractor.name,
                            "EXTRACTOR_FAILED",
                            str(error),
                        )
                    )
                    continue

                for prediction in predictions:
                    try:
                        self._ground_candidate(
                            record,
                            unit_index,
                            unit.language,
                            normalized,
                            prediction,
                        )
                    except ValueError as error:
                        issues.append(
                            self._issue(
                                record,
                                unit_index,
                                extractor.name,
                                "INVALID_CANDIDATE_SPAN",
                                str(error),
                            )
                        )
                        continue
                    valid_raw.append(prediction)

            try:
                baseline_for_unit = self.reconciler.reconcile(
                    normalized.normalized_text,
                    tuple(valid_raw),
                )
            except Exception as error:
                issues.append(
                    self._issue(
                        record,
                        unit_index,
                        self.reconciler.name,
                        "RECONCILER_FAILED",
                        str(error),
                    )
                )
                baseline_for_unit = tuple(valid_raw)

            baseline.extend(
                self._ground_candidate(
                    record,
                    unit_index,
                    unit.language,
                    normalized,
                    prediction,
                )
                for prediction in baseline_for_unit
            )
            for refiner in self.refiners:
                try:
                    predictions = refiner.refine(
                        normalized.normalized_text,
                        baseline_for_unit,
                    )
                except Exception as error:
                    issues.append(
                        self._issue(
                            record,
                            unit_index,
                            refiner.name,
                            "REFINER_FAILED",
                            str(error),
                        )
                    )
                    continue

                refined_units.add(unit_index)
                for prediction in predictions:
                    try:
                        refined.append(
                            self._ground_candidate(
                                record,
                                unit_index,
                                unit.language,
                                normalized,
                                prediction,
                            )
                        )
                    except ValueError as error:
                        issues.append(
                            self._issue(
                                record,
                                unit_index,
                                refiner.name,
                                "INVALID_REFINED_SPAN",
                                str(error),
                            )
                        )

        def sort_key(item: TermCandidate) -> tuple[int, int, int, str]:
            return (
                item.text_unit_index,
                item.normalized_start,
                item.normalized_end,
                item.extractor,
            )

        return EnglishExtractionResult(
            source_record_id=record.source_record_id,
            baseline_candidates=tuple(sorted(baseline, key=sort_key)),
            refined_candidates=tuple(sorted(refined, key=sort_key)),
            refined_text_unit_indices=tuple(sorted(refined_units)),
            issues=tuple(issues),
        )

    @staticmethod
    def _ground_candidate(
        record: PatentInput,
        unit_index: int,
        language: str,
        normalized: NormalizedText,
        prediction: RawCandidate,
    ) -> TermCandidate:
        if prediction.end > len(normalized.normalized_text):
            raise ValueError(
                f"{prediction.extractor} span [{prediction.start}, {prediction.end}) "
                f"exceeds text length {len(normalized.normalized_text)}"
            )
        exact_text = normalized.normalized_text[prediction.start : prediction.end]
        if exact_text != prediction.text:
            raise ValueError(
                f"{prediction.extractor} text {prediction.text!r} does not equal "
                f"source span {exact_text!r}"
            )
        original_start, original_end = normalized.original_span(prediction.start, prediction.end)
        return TermCandidate(
            source_record_id=record.source_record_id,
            text_unit_index=unit_index,
            language=language,
            text=prediction.text,
            normalized_start=prediction.start,
            normalized_end=prediction.end,
            original_start=original_start,
            original_end=original_end,
            types=prediction.types,
            roles=prediction.roles,
            proposed_definition=prediction.proposed_definition,
            confidence=prediction.confidence,
            extractor=prediction.extractor,
            extractor_version=prediction.extractor_version,
            raw_label=prediction.raw_label,
            needs_review=prediction.needs_review,
            metadata=prediction.metadata,
        )

    @staticmethod
    def _issue(
        record: PatentInput,
        unit_index: int,
        extractor: str,
        code: str,
        message: str,
    ) -> ExtractionIssue:
        return ExtractionIssue(
            source_record_id=record.source_record_id,
            text_unit_index=unit_index,
            extractor=extractor,
            code=code,
            message=message,
        )


def build_english_pipeline(
    *,
    ner_model: str | None = None,
    ner_models: Iterable[str] = (),
    use_chemu: bool = False,
    cde_command: Sequence[str] | None = None,
    use_llm: bool = False,
) -> EnglishExtractionPipeline:
    """Build the default baseline with optional NER and LLM components."""

    extractors: list[CandidateExtractor] = [
        DeterministicRuleExtractor(),
        TechnicalPhraseExtractor(),
    ]
    configured_models = list(ner_models)
    if ner_model:
        configured_models.append(ner_model)
    for model_name in dict.fromkeys(configured_models):
        if use_chemu and model_name == CHEMU_MODEL:
            continue
        extractors.append(TransformersNerExtractor(model_name))
    if use_chemu:
        extractors.append(ChemUNerExtractor())
    if cde_command:
        extractors.append(ChemDataExtractorNerExtractor(cde_command))

    refiners: list[CandidateRefiner] = []
    if use_llm:
        settings = get_settings()
        if settings.llm_api_key is None or settings.llm_model is None:
            raise ValueError("LLM refinement requires CHEMTERM_LLM_API_KEY and CHEMTERM_LLM_MODEL")
        client = OpenAICompatibleJsonClient(
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        refiners.append(LlmTermRefiner(client))

    return EnglishExtractionPipeline(extractors=extractors, refiners=refiners)
