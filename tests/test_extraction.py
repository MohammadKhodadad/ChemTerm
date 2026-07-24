"""Tests for hybrid English terminology extraction."""

from typing import Any

from chemterm.contracts.extraction import CandidateType, ContextRole, RawCandidate
from chemterm.contracts.input import PatentInput, TextUnit, TextUnitType
from chemterm.contracts.mapping import TargetFormStatus
from chemterm.extraction import (
    ChemDataExtractorNerExtractor,
    ChemUNerExtractor,
    DeterministicRuleExtractor,
    ExactSpanCandidateReconciler,
    TechnicalPhraseExtractor,
    TransformersNerExtractor,
)
from chemterm.llm import LlmTermRefiner
from chemterm.llm.client import _strict_json_schema
from chemterm.llm.refinement import LlmExtractionResponse
from chemterm.mapping import LlmParallelTextMapper
from chemterm.pipeline import EnglishExtractionPipeline, MultilingualPairingPipeline


class FakeLlmClient:
    """Deterministic structured client used without an external API."""

    model = "fake-model"

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.payload: dict[str, Any] | None = None

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type,
    ) -> dict[str, Any]:
        assert "exact" in system_prompt.lower()
        self.payload = payload
        return self.response


class RoutingFakeLlmClient:
    """Return target-language-specific parallel mapping responses."""

    model = "fake-multilingual-model"

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.payloads: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type,
    ) -> dict[str, Any]:
        assert "not translating" in system_prompt
        assert response_model.__name__ == "LlmParallelMappingResponse"
        self.payloads.append(payload)
        return self.responses[payload["target_language"]]


class EchoRefinementClient:
    """Confirm every grouped baseline candidate and count requests."""

    model = "fake-grouped-model"

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type,
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        return {
            "terms": [
                {
                    "text": candidate["text"],
                    "start": candidate["start"],
                    "end": candidate["end"],
                    "types": candidate["types"],
                    "roles": candidate["roles"],
                    "proposed_definition": None,
                    "scope_decision": "IN_SCOPE",
                    "confidence": 0.95,
                    "source": "candidate_confirmed",
                    "needs_review": False,
                    "reason_code": "GROUPED_TEST_CONFIRMATION",
                }
                for candidate in payload["candidates"]
            ]
        }


class GroupedMappingClient:
    """Map title and abstract candidates in one target-language request."""

    model = "fake-grouped-mapping-model"

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type,
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        target_by_source = {
            "Gold alloy": "Goldlegierung",
            "copper coating": "Kupferbeschichtung",
        }
        return {
            "mappings": [
                {
                    "source_id": term["source_id"],
                    "target_text": (target := target_by_source[term["text"]]),
                    "target_start": (start := payload["target_text"].index(target)),
                    "target_end": start + len(target),
                    "relation": "EXACT_EQUIVALENT",
                    "confidence": 0.98,
                    "needs_review": False,
                    "reason_code": "GROUPED_PARALLEL_TERM",
                }
                for term in payload["english_terms"]
            ]
        }


def _record(text: str) -> PatentInput:
    return PatentInput(
        source_record_id="sample:1",
        family_id="33448527",
        publication_number="EP-1627088-A1",
        text_units=(TextUnit(language="en", text=text, unit_type=TextUnitType.TITLE),),
    )


def test_deterministic_rules_find_formula_quantity_and_label() -> None:
    text = "Compound 17 contains NaCl at 25 °C."

    candidates = DeterministicRuleExtractor().extract(text)

    assert {(item.text, item.raw_label) for item in candidates} == {
        ("Compound 17", "PATENT_LABEL"),
        ("NaCl", "MOLECULAR_FORMULA"),
        ("25 °C", "QUANTITY"),
    }


def test_deterministic_rules_cover_identifiers_conditions_and_ranges() -> None:
    text = "CAS 64-17-5; SMILES: CCO; pH 7.4; heated at 20-25 °C and 5 wt.% solids."

    candidates = DeterministicRuleExtractor().extract(text)
    extracted = {(item.text, item.raw_label) for item in candidates}

    assert ("64-17-5", "CAS_RN") in extracted
    assert ("CCO", "SMILES") in extracted
    assert ("pH 7.4", "PH") in extracted
    assert ("20-25 °C", "QUANTITY") in extracted
    assert ("5 wt.%", "QUANTITY") in extracted


def test_phrase_extractor_finds_nested_patent_terminology() -> None:
    text = "Low solvent coating process for a gold alloy"

    candidates = TechnicalPhraseExtractor().extract(text)
    extracted = {(item.text, item.types[0]) for item in candidates}

    assert ("Low solvent coating process", CandidateType.PROCESS) in extracted
    assert ("Low solvent coating", CandidateType.MATERIAL) in extracted
    assert ("gold alloy", CandidateType.MATERIAL) in extracted


def test_transformers_adapter_is_lazy_and_uses_exact_model_offsets() -> None:
    def factory(*args: Any, **kwargs: Any) -> Any:
        assert args == ("token-classification",)
        assert kwargs["aggregation_strategy"] == "simple"

        def model(text: str) -> list[dict[str, Any]]:
            assert text == "Gold alloy"
            return [
                {
                    "start": 0,
                    "end": 4,
                    "entity_group": "CHEMICAL",
                    "score": 0.97,
                }
            ]

        return model

    extractor = TransformersNerExtractor("fake/chemical-ner", pipeline_factory=factory)

    candidates = extractor.extract("Gold alloy")

    assert candidates[0].text == "Gold"
    assert candidates[0].types == (CandidateType.CHEMICAL_ENTITY,)


def test_chemu_adapter_maps_reaction_labels_and_roles() -> None:
    def factory(*args: Any, **kwargs: Any) -> Any:
        def model(text: str) -> list[dict[str, Any]]:
            return [
                {
                    "start": 0,
                    "end": 7,
                    "entity_group": "SOLVENT",
                    "score": 0.96,
                }
            ]

        return model

    candidate = ChemUNerExtractor(pipeline_factory=factory).extract("ethanol was added")[0]

    assert candidate.types == (CandidateType.CHEMICAL_ENTITY,)
    assert candidate.roles == (ContextRole.SOLVENT,)
    assert candidate.extractor == "chemu_ner"


def test_chemdataextractor_adapter_preserves_worker_spans() -> None:
    extractor = ChemDataExtractorNerExtractor(
        request=lambda text: [{"text": "NaCl", "start": 0, "end": 4, "confidence": 0.91}]
    )

    candidate = extractor.extract("NaCl solution")[0]

    assert candidate.text == "NaCl"
    assert candidate.extractor == "chemdataextractor_ner"
    assert candidate.types == (CandidateType.CHEMICAL_ENTITY,)


def test_reconciler_merges_exact_evidence_and_prefers_child_type() -> None:
    candidates = (
        RawCandidate(
            text="ethanol",
            start=0,
            end=7,
            types=(CandidateType.CHEMICAL_ENTITY,),
            confidence=0.9,
            extractor="cde",
            extractor_version="1",
        ),
        RawCandidate(
            text="ethanol",
            start=0,
            end=7,
            types=(CandidateType.COMPOUND,),
            roles=(ContextRole.SOLVENT,),
            confidence=0.95,
            extractor="chemu",
            extractor_version="1",
        ),
    )

    result = ExactSpanCandidateReconciler().reconcile("ethanol", candidates)

    assert len(result) == 1
    assert result[0].types == (CandidateType.COMPOUND,)
    assert result[0].roles == (ContextRole.SOLVENT,)
    assert result[0].metadata["extractors"] == ["cde", "chemu"]


def test_pipeline_runs_baseline_and_llm_refinement() -> None:
    text = "Gold alloy and method for manufacturing a dental restoration"
    client = FakeLlmClient(
        {
            "terms": [
                {
                    "text": "Gold alloy",
                    "start": 1,
                    "end": 9,
                    "types": ["MATERIAL"],
                    "roles": [],
                    "proposed_definition": "An alloy whose principal material is gold.",
                    "confidence": 0.96,
                    "source": "candidate_confirmed",
                    "needs_review": False,
                    "reason_code": "DOMAIN_MATERIAL",
                },
                {
                    "text": "dental restoration",
                    "start": 42,
                    "end": 60,
                    "types": ["APPLICATION"],
                    "roles": [],
                    "proposed_definition": "A restoration used in dental treatment.",
                    "confidence": 0.91,
                    "source": "candidate_confirmed",
                    "needs_review": False,
                    "reason_code": "SPECIALIZED_APPLICATION",
                },
            ]
        }
    )
    pipeline = EnglishExtractionPipeline(
        extractors=(DeterministicRuleExtractor(), TechnicalPhraseExtractor()),
        refiners=(LlmTermRefiner(client),),
    )

    result = pipeline.extract(_record(text))

    assert {item.text for item in result.refined_candidates} == {
        "Gold alloy",
        "dental restoration",
    }
    assert not result.issues
    gold = next(item for item in result.refined_candidates if item.text == "Gold alloy")
    assert (gold.normalized_start, gold.normalized_end) == (0, 10)
    assert gold.proposed_definition == "An alloy whose principal material is gold."
    assert client.payload is not None
    assert any(item["text"] == "Gold alloy" for item in client.payload["candidates"])


def test_pipeline_fails_closed_on_ungrounded_llm_output() -> None:
    client = FakeLlmClient(
        {
            "terms": [
                {
                    "text": "invented chemical",
                    "start": 0,
                    "end": 8,
                    "types": ["CHEMICAL_ENTITY"],
                    "roles": [],
                    "confidence": 0.99,
                    "source": "llm_added",
                    "needs_review": False,
                    "reason_code": "INVALID_TEST_OUTPUT",
                }
            ]
        }
    )
    pipeline = EnglishExtractionPipeline(
        extractors=(TechnicalPhraseExtractor(),),
        refiners=(LlmTermRefiner(client),),
    )

    result = pipeline.extract(_record("Gold alloy"))

    assert result.refined_candidates == ()
    assert result.issues[0].code == "REFINER_FAILED"


def test_llm_refiner_mechanically_removes_out_of_scope_decisions() -> None:
    client = FakeLlmClient(
        {
            "terms": [
                {
                    "text": "Light emitting diode",
                    "start": 0,
                    "end": 20,
                    "types": ["EQUIPMENT"],
                    "roles": [],
                    "proposed_definition": None,
                    "scope_decision": "OUT_OF_SCOPE",
                    "confidence": 0.99,
                    "source": "candidate_confirmed",
                    "needs_review": False,
                    "reason_code": "generic_electrical_equipment",
                }
            ]
        }
    )
    pipeline = EnglishExtractionPipeline(
        extractors=(TechnicalPhraseExtractor(),),
        refiners=(LlmTermRefiner(client),),
    )

    result = pipeline.extract(_record("Light emitting diode"))

    assert result.baseline_candidates
    assert result.refined_candidates == ()
    assert result.refined_text_unit_indices == (0,)
    assert result.issues == ()

    multilingual_record = PatentInput(
        source_record_id="sample:scope",
        publication_number="EP-2-A1",
        text_units=(
            TextUnit(language="en", text="Light emitting diode", unit_type=TextUnitType.TITLE),
            TextUnit(language="de", text="Leuchtdiode", unit_type=TextUnitType.TITLE),
        ),
    )
    multilingual_result = pipeline.extract(multilingual_record)
    pairing = MultilingualPairingPipeline(LlmParallelTextMapper(RoutingFakeLlmClient({}))).pair(
        multilingual_record, multilingual_result
    )
    assert pairing.mappings == ()
    assert pairing.issues == ()


def test_title_and_abstract_share_one_refinement_request_with_local_offsets() -> None:
    record = PatentInput(
        source_record_id="sample:grouped-refinement",
        publication_number="EP-3-A1",
        text_units=(
            TextUnit(language="en", text="Gold alloy", unit_type=TextUnitType.TITLE),
            TextUnit(
                language="en",
                text="A copper coating protects the surface.",
                unit_type=TextUnitType.ABSTRACT,
            ),
        ),
    )
    client = EchoRefinementClient()
    pipeline = EnglishExtractionPipeline(
        extractors=(TechnicalPhraseExtractor(),),
        refiners=(LlmTermRefiner(client),),
    )

    result = pipeline.extract(record)

    assert len(client.payloads) == 1
    assert "[[SECTION" in client.payloads[0]["text"]
    assert result.refined_text_unit_indices == (0, 1)
    assert {(item.text, item.text_unit_index) for item in result.refined_candidates} == {
        ("Gold alloy", 0),
        ("copper coating", 1),
    }
    for candidate in result.refined_candidates:
        source = record.text_units[candidate.text_unit_index].text
        assert source[candidate.original_start : candidate.original_end] == candidate.text


def test_title_and_abstract_share_one_mapping_request_per_language() -> None:
    record = PatentInput(
        source_record_id="sample:grouped-mapping",
        publication_number="EP-4-A1",
        text_units=(
            TextUnit(language="en", text="Gold alloy", unit_type=TextUnitType.TITLE),
            TextUnit(
                language="en",
                text="A copper coating protects the surface.",
                unit_type=TextUnitType.ABSTRACT,
            ),
            TextUnit(language="de", text="Goldlegierung", unit_type=TextUnitType.TITLE),
            TextUnit(
                language="de",
                text="Eine Kupferbeschichtung schützt die Oberfläche.",
                unit_type=TextUnitType.ABSTRACT,
            ),
        ),
    )
    extraction = EnglishExtractionPipeline(extractors=(TechnicalPhraseExtractor(),)).extract(record)
    client = GroupedMappingClient()

    result = MultilingualPairingPipeline(LlmParallelTextMapper(client)).pair(record, extraction)

    assert len(client.payloads) == 1
    assert {(item.target_text, item.target_text_unit_index) for item in result.mappings} == {
        ("Goldlegierung", 2),
        ("Kupferbeschichtung", 3),
    }
    assert {(item.target_text, item.target_normalized_start) for item in result.mappings} == {
        ("Goldlegierung", 0),
        ("Kupferbeschichtung", 5),
    }
    assert result.issues == ()


def test_parallel_pairing_maps_exact_native_language_spans() -> None:
    record = PatentInput(
        source_record_id="sample:parallel",
        family_id="33448527",
        publication_number="EP-1627088-A1",
        text_units=(
            TextUnit(language="en", text="Gold alloy", unit_type=TextUnitType.TITLE),
            TextUnit(
                language="de",
                text="Goldlegierung",
                unit_type=TextUnitType.TITLE,
            ),
            TextUnit(
                language="fr",
                text="Alliage d&#39;or",
                unit_type=TextUnitType.TITLE,
            ),
            TextUnit(language="zh-Hans", text="金合金", unit_type=TextUnitType.TITLE),
        ),
    )
    extraction = EnglishExtractionPipeline(extractors=(TechnicalPhraseExtractor(),)).extract(record)
    client = RoutingFakeLlmClient(
        {
            "de": {
                "mappings": [
                    {
                        "source_id": "E0",
                        "target_text": "Goldlegierung",
                        "target_start": 1,
                        "target_end": 12,
                        "relation": "EXACT_EQUIVALENT",
                        "confidence": 0.98,
                        "needs_review": False,
                        "reason_code": "DIRECT_PARALLEL_TERM",
                    }
                ]
            },
            "fr": {
                "mappings": [
                    {
                        "source_id": "E0",
                        "target_text": "Alliage d'or",
                        "target_start": 1,
                        "target_end": 11,
                        "relation": "EXACT_EQUIVALENT",
                        "confidence": 0.97,
                        "needs_review": False,
                        "reason_code": "DIRECT_PARALLEL_TERM",
                    }
                ]
            },
            "zh-Hans": {
                "mappings": [
                    {
                        "source_id": "E0",
                        "target_text": "金合金",
                        "target_start": 0,
                        "target_end": 3,
                        "relation": "EXACT_EQUIVALENT",
                        "confidence": 0.96,
                        "needs_review": False,
                        "reason_code": "DIRECT_PARALLEL_TERM",
                    }
                ]
            },
        }
    )
    pipeline = MultilingualPairingPipeline(LlmParallelTextMapper(client))

    result = pipeline.pair(
        record,
        extraction,
        target_languages=("de", "fr", "zh-Hans"),
    )

    assert {(item.target_language, item.target_text) for item in result.mappings} == {
        ("de", "Goldlegierung"),
        ("fr", "Alliage d'or"),
        ("zh-Hans", "金合金"),
    }
    french = next(item for item in result.mappings if item.target_language == "fr")
    assert (
        record.text_units[2].text[french.target_original_start : french.target_original_end]
        == "Alliage d&#39;or"
    )
    assert not result.issues


def test_parallel_pairing_labels_unchanged_target_language_form() -> None:
    record = PatentInput(
        source_record_id="sample:unchanged-parallel",
        publication_number="EP-5-A1",
        text_units=(
            TextUnit(language="en", text="Polymer matrix", unit_type=TextUnitType.TITLE),
            TextUnit(language="de", text="Polymer matrix", unit_type=TextUnitType.TITLE),
        ),
    )
    extraction = EnglishExtractionPipeline(extractors=(TechnicalPhraseExtractor(),)).extract(record)
    client = RoutingFakeLlmClient(
        {
            "de": {
                "mappings": [
                    {
                        "source_id": "E0",
                        "target_text": "Polymer matrix",
                        "target_start": 0,
                        "target_end": 14,
                        "relation": "EXACT_EQUIVALENT",
                        "target_form_status": "UNCHANGED",
                        "confidence": 0.98,
                        "needs_review": False,
                        "reason_code": "SOURCE_FORM_REUSED",
                    }
                ]
            }
        }
    )

    result = MultilingualPairingPipeline(LlmParallelTextMapper(client)).pair(record, extraction)

    assert result.mappings[0].target_language == "de"
    assert result.mappings[0].target_text == "Polymer matrix"
    assert result.mappings[0].target_form_status == TargetFormStatus.UNCHANGED


def test_parallel_pairing_fails_closed_on_invented_target_text() -> None:
    record = PatentInput(
        source_record_id="sample:invalid-parallel",
        publication_number="EP-1-A1",
        text_units=(
            TextUnit(language="en", text="Gold alloy", unit_type=TextUnitType.TITLE),
            TextUnit(language="de", text="Goldlegierung", unit_type=TextUnitType.TITLE),
        ),
    )
    extraction = EnglishExtractionPipeline(extractors=(TechnicalPhraseExtractor(),)).extract(record)
    client = RoutingFakeLlmClient(
        {
            "de": {
                "mappings": [
                    {
                        "source_id": "E0",
                        "target_text": "erfundener Begriff",
                        "target_start": 0,
                        "target_end": 13,
                        "relation": "EXACT_EQUIVALENT",
                        "confidence": 0.99,
                        "needs_review": False,
                        "reason_code": "INVALID_TEST_OUTPUT",
                    }
                ]
            }
        }
    )
    pipeline = MultilingualPairingPipeline(LlmParallelTextMapper(client))

    result = pipeline.pair(record, extraction)

    assert len(result.mappings) == 1
    assert result.mappings[0].relation.value == "NO_MATCH"
    assert result.mappings[0].target_text is None
    assert result.mappings[0].target_form_status == TargetFormStatus.NOT_PRESENT
    assert result.mappings[0].needs_review
    assert result.issues == ()


def test_openai_strict_schema_requires_defaulted_fields() -> None:
    schema = _strict_json_schema(LlmExtractionResponse)
    decision = schema["$defs"]["LlmTermDecision"]

    assert set(decision["required"]) == set(decision["properties"])
    assert decision["additionalProperties"] is False
    assert "default" not in decision["properties"]["roles"]
    assert "default" not in decision["properties"]["needs_review"]
