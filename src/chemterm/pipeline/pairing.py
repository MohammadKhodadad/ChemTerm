"""Pair known English candidates with exact parallel target-language spans."""

from __future__ import annotations

from collections.abc import Iterable

from chemterm.config import get_settings
from chemterm.contracts.extraction import EnglishExtractionResult, TermCandidate
from chemterm.contracts.input import (
    PatentInput,
    TextUnitType,
    canonicalize_language_tag,
)
from chemterm.contracts.mapping import (
    MappingIssue,
    MultilingualMappingResult,
    TargetTermMapping,
)
from chemterm.llm import OpenAICompatibleJsonClient
from chemterm.mapping import LlmParallelTextMapper, ParallelTextMapper
from chemterm.normalization import normalize_source_text
from chemterm.pipeline.grouped_text import GroupedText


class MultilingualPairingPipeline:
    """Apply one mapper to corresponding target-language text units."""

    def __init__(self, mapper: ParallelTextMapper) -> None:
        self.mapper = mapper

    def pair(
        self,
        record: PatentInput,
        english_result: EnglishExtractionResult,
        *,
        target_languages: Iterable[str] | None = None,
    ) -> MultilingualMappingResult:
        """Map selected English candidates to each corresponding target text."""

        if record.source_record_id != english_result.source_record_id:
            raise ValueError("record and English extraction result IDs do not match")
        allowed_languages = (
            {canonicalize_language_tag(item) for item in target_languages}
            if target_languages is not None
            else None
        )

        mappings: list[TargetTermMapping] = []
        issues: list[MappingIssue] = []
        english_group_indices = tuple(
            index
            for index, unit in enumerate(record.text_units)
            if unit.language.split("-", maxsplit=1)[0] == "en"
            and unit.unit_type in {TextUnitType.TITLE, TextUnitType.ABSTRACT}
        )
        english_group_types = {
            record.text_units[index].unit_type for index in english_group_indices
        }
        grouped_indices = (
            english_group_indices
            if {TextUnitType.TITLE, TextUnitType.ABSTRACT}.issubset(english_group_types)
            else ()
        )
        if grouped_indices:
            grouped_mappings, grouped_issues = self._pair_grouped_units(
                record,
                english_result,
                grouped_indices,
                allowed_languages,
            )
            mappings.extend(grouped_mappings)
            issues.extend(grouped_issues)

        for english_unit_index, english_unit in enumerate(record.text_units):
            if english_unit.language.split("-", maxsplit=1)[0] != "en":
                continue
            if english_unit_index in grouped_indices:
                continue

            english_candidates = self._select_candidates(english_result, english_unit_index)
            if not english_candidates:
                continue
            english_text = normalize_source_text(english_unit.text).normalized_text

            for target_index, target_unit in enumerate(record.text_units):
                if target_unit.language.split("-", maxsplit=1)[0] == "en":
                    continue
                if allowed_languages is not None and target_unit.language not in allowed_languages:
                    continue
                if (
                    target_unit.unit_type != english_unit.unit_type
                    or target_unit.locator != english_unit.locator
                ):
                    continue

                normalized_target = normalize_source_text(target_unit.text)
                try:
                    raw_mappings = self.mapper.map_terms(
                        english_text=english_text,
                        english_candidates=english_candidates,
                        target_language=target_unit.language,
                        target_text=normalized_target.normalized_text,
                    )
                    self._validate_coverage(raw_mappings, len(english_candidates))
                    mappings.extend(
                        self._ground_mappings(
                            record,
                            english_candidates,
                            english_unit_index,
                            target_index,
                            target_unit.language,
                            normalized_target,
                            raw_mappings,
                        )
                    )
                except Exception as error:
                    issues.append(
                        MappingIssue(
                            source_record_id=record.source_record_id,
                            target_text_unit_index=target_index,
                            target_language=target_unit.language,
                            mapper=self.mapper.name,
                            code="TARGET_MAPPING_FAILED",
                            message=str(error),
                        )
                    )

        return MultilingualMappingResult(
            source_record_id=record.source_record_id,
            mappings=tuple(mappings),
            issues=tuple(issues),
        )

    def _pair_grouped_units(
        self,
        record: PatentInput,
        english_result: EnglishExtractionResult,
        english_unit_indices: tuple[int, ...],
        allowed_languages: set[str] | None,
    ) -> tuple[list[TargetTermMapping], list[MappingIssue]]:
        english_candidates = tuple(
            candidate
            for unit_index in english_unit_indices
            for candidate in self._select_candidates(english_result, unit_index)
        )
        if not english_candidates:
            return [], []

        english_group = GroupedText.from_record(record, english_unit_indices)
        shifted_candidates = tuple(
            english_group.shift_term(candidate) for candidate in english_candidates
        )
        source_shapes = {
            (
                record.text_units[index].unit_type,
                record.text_units[index].locator,
            )
            for index in english_unit_indices
        }
        target_languages = {
            unit.language
            for unit in record.text_units
            if unit.language.split("-", maxsplit=1)[0] != "en"
            and (allowed_languages is None or unit.language in allowed_languages)
        }

        mappings: list[TargetTermMapping] = []
        issues: list[MappingIssue] = []
        for target_language in sorted(target_languages):
            target_indices = tuple(
                index
                for index, unit in enumerate(record.text_units)
                if unit.language == target_language
                and (unit.unit_type, unit.locator) in source_shapes
            )
            if not target_indices:
                continue
            target_group = GroupedText.from_record(record, target_indices)
            try:
                raw_mappings = self.mapper.map_terms(
                    english_text=english_group.text,
                    english_candidates=shifted_candidates,
                    target_language=target_language,
                    target_text=target_group.text,
                )
                self._validate_coverage(raw_mappings, len(shifted_candidates))
                mappings.extend(
                    self._ground_grouped_mappings(
                        record,
                        shifted_candidates,
                        target_group,
                        target_language,
                        raw_mappings,
                    )
                )
            except Exception as error:
                issues.append(
                    MappingIssue(
                        source_record_id=record.source_record_id,
                        target_text_unit_index=target_indices[0],
                        target_language=target_language,
                        mapper=self.mapper.name,
                        code="GROUPED_TARGET_MAPPING_FAILED",
                        message=str(error),
                    )
                )
        return mappings, issues

    @staticmethod
    def _select_candidates(
        result: EnglishExtractionResult,
        text_unit_index: int,
    ) -> tuple[TermCandidate, ...]:
        refined = tuple(
            item for item in result.refined_candidates if item.text_unit_index == text_unit_index
        )
        available = (
            refined
            if text_unit_index in result.refined_text_unit_indices
            else tuple(
                item
                for item in result.baseline_candidates
                if item.text_unit_index == text_unit_index
            )
        )

        best_by_span: dict[tuple[int, int, tuple], TermCandidate] = {}
        for candidate in available:
            key = (
                candidate.normalized_start,
                candidate.normalized_end,
                candidate.types,
            )
            current = best_by_span.get(key)
            if current is None or candidate.confidence > current.confidence:
                best_by_span[key] = candidate
        return tuple(
            sorted(
                best_by_span.values(),
                key=lambda item: (
                    item.normalized_start,
                    item.normalized_end,
                    item.text,
                ),
            )
        )

    @staticmethod
    def _validate_coverage(raw_mappings: tuple, candidate_count: int) -> None:
        indices = [item.source_candidate_index for item in raw_mappings]
        if len(indices) != len(set(indices)):
            raise ValueError("mapper returned duplicate source candidate decisions")
        if set(indices) != set(range(candidate_count)):
            raise ValueError("mapper must return one decision per source candidate")

    def _ground_grouped_mappings(
        self,
        record: PatentInput,
        english_candidates: tuple[TermCandidate, ...],
        target_group: GroupedText,
        target_language: str,
        raw_mappings: tuple,
    ) -> list[TargetTermMapping]:
        results: list[TargetTermMapping] = []
        for raw_mapping in raw_mappings:
            source = english_candidates[raw_mapping.source_candidate_index]
            target_index = target_group.segments[0].unit_index
            target_start: int | None = None
            target_end: int | None = None
            original_start: int | None = None
            original_end: int | None = None
            if raw_mapping.target_text is not None:
                assert raw_mapping.target_start is not None
                assert raw_mapping.target_end is not None
                segment, target_start, target_end = target_group.local_span(
                    raw_mapping.target_start,
                    raw_mapping.target_end,
                )
                exact = segment.normalized.normalized_text[target_start:target_end]
                if exact != raw_mapping.target_text:
                    raise ValueError(
                        f"mapper target {raw_mapping.target_text!r} "
                        f"does not match target source span {exact!r}"
                    )
                target_index = segment.unit_index
                original_start, original_end = segment.normalized.original_span(
                    target_start,
                    target_end,
                )

            results.append(
                TargetTermMapping(
                    source_record_id=record.source_record_id,
                    source_text_unit_index=source.text_unit_index,
                    source_candidate_index=raw_mapping.source_candidate_index,
                    source_text=source.text,
                    source_types=source.types,
                    target_language=target_language,
                    target_text_unit_index=target_index,
                    target_text=raw_mapping.target_text,
                    target_normalized_start=target_start,
                    target_normalized_end=target_end,
                    target_original_start=original_start,
                    target_original_end=original_end,
                    relation=raw_mapping.relation,
                    target_form_status=raw_mapping.target_form_status,
                    confidence=raw_mapping.confidence,
                    needs_review=raw_mapping.needs_review,
                    mapper=self.mapper.name,
                    mapper_version=self.mapper.version,
                    reason_code=raw_mapping.reason_code,
                )
            )
        return results

    def _ground_mappings(
        self,
        record: PatentInput,
        english_candidates: tuple[TermCandidate, ...],
        english_unit_index: int,
        target_index: int,
        target_language: str,
        normalized_target,
        raw_mappings: tuple,
    ) -> list[TargetTermMapping]:
        results: list[TargetTermMapping] = []
        for raw_mapping in raw_mappings:
            source = english_candidates[raw_mapping.source_candidate_index]
            original_start: int | None = None
            original_end: int | None = None
            if raw_mapping.target_text is not None:
                assert raw_mapping.target_start is not None
                assert raw_mapping.target_end is not None
                exact = normalized_target.normalized_text[
                    raw_mapping.target_start : raw_mapping.target_end
                ]
                if exact != raw_mapping.target_text:
                    raise ValueError(
                        f"mapper target {raw_mapping.target_text!r} "
                        f"does not match target source span {exact!r}"
                    )
                original_start, original_end = normalized_target.original_span(
                    raw_mapping.target_start,
                    raw_mapping.target_end,
                )

            results.append(
                TargetTermMapping(
                    source_record_id=record.source_record_id,
                    source_text_unit_index=english_unit_index,
                    source_candidate_index=raw_mapping.source_candidate_index,
                    source_text=source.text,
                    source_types=source.types,
                    target_language=target_language,
                    target_text_unit_index=target_index,
                    target_text=raw_mapping.target_text,
                    target_normalized_start=raw_mapping.target_start,
                    target_normalized_end=raw_mapping.target_end,
                    target_original_start=original_start,
                    target_original_end=original_end,
                    relation=raw_mapping.relation,
                    target_form_status=raw_mapping.target_form_status,
                    confidence=raw_mapping.confidence,
                    needs_review=raw_mapping.needs_review,
                    mapper=self.mapper.name,
                    mapper_version=self.mapper.version,
                    reason_code=raw_mapping.reason_code,
                )
            )
        return results


def build_llm_pairing_pipeline() -> MultilingualPairingPipeline:
    """Build pairing from configured OpenAI-compatible LLM settings."""

    settings = get_settings()
    if settings.llm_api_key is None or settings.llm_model is None:
        raise ValueError("LLM pairing requires CHEMTERM_LLM_API_KEY and CHEMTERM_LLM_MODEL")
    client = OpenAICompatibleJsonClient(
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return MultilingualPairingPipeline(LlmParallelTextMapper(client))
