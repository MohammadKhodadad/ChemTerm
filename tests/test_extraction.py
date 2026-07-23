"""Tests for hybrid English terminology extraction."""

from typing import Any

from chemterm.contracts.extraction import CandidateType
from chemterm.contracts.input import PatentInput, TextUnit, TextUnitType
from chemterm.extraction import (
    DeterministicRuleExtractor,
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
    pairing = MultilingualPairingPipeline(
        LlmParallelTextMapper(RoutingFakeLlmClient({}))
    ).pair(multilingual_record, multilingual_result)
    assert pairing.mappings == ()
    assert pairing.issues == ()


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
    assert result.mappings[0].needs_review
    assert result.issues == ()


def test_openai_strict_schema_requires_defaulted_fields() -> None:
    schema = _strict_json_schema(LlmExtractionResponse)
    decision = schema["$defs"]["LlmTermDecision"]

    assert set(decision["required"]) == set(decision["properties"])
    assert decision["additionalProperties"] is False
    assert "default" not in decision["properties"]["roles"]
    assert "default" not in decision["properties"]["needs_review"]
