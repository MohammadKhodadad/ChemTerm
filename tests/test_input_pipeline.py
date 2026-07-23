"""Tests for canonical multilingual input and normalization."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from chemterm.contracts.input import PatentInput, TextUnit, TextUnitType
from chemterm.ingestion.csv_titles import CsvTitleAdapter
from chemterm.normalization.text import (
    TermNormalizationProfile,
    normalize_source_text,
    normalize_term,
)


def test_input_contract_accepts_global_language_tags() -> None:
    record = PatentInput(
        source_record_id="test:1",
        family_id="family-1",
        publication_number="EP-1-A1",
        text_units=(
            TextUnit(language="EN", text="polymer", unit_type=TextUnitType.TITLE),
            TextUnit(
                language="zh_hans",
                text="聚合物",
                unit_type=TextUnitType.TITLE,
            ),
            TextUnit(language="ja", text="ポリマー", unit_type=TextUnitType.TITLE),
            TextUnit(language="ru", text="полимер", unit_type=TextUnitType.TITLE),
        ),
    )

    assert [unit.language for unit in record.text_units] == [
        "en",
        "zh-Hans",
        "ja",
        "ru",
    ]
    assert record.text_for_language("ZH-hans")[0].text == "聚合物"


def test_input_contract_rejects_invalid_language_tag() -> None:
    with pytest.raises(ValidationError, match="BCP 47"):
        TextUnit(
            language="not_a_language_tag",
            text="polymer",
            unit_type=TextUnitType.TITLE,
        )


def test_input_contract_rejects_whitespace_only_identity() -> None:
    with pytest.raises(ValidationError):
        PatentInput(
            source_record_id=" ",
            publication_number=" ",
            text_units=(TextUnit(language="en", text="polymer", unit_type=TextUnitType.TITLE),),
        )


def test_csv_adapter_discovers_languages_and_handles_quoted_commas(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "patents.csv"
    csv_path.write_text(
        "publication_number,family_id,languages,title_en,title_nl,"
        "title_zh_hans,title_ja,title_ru\n"
        'EP-1-A1,F1,en|nl|zh-Hans|ja|ru,"Polymer, coating",,'
        "聚合物涂层,ポリマーコーティング,полимерное покрытие\n",
        encoding="utf-8",
    )
    adapter = CsvTitleAdapter(csv_path)

    records = list(adapter.records())

    assert len(records) == 1
    assert records[0].text_for_language("en")[0].text == "Polymer, coating"
    assert {unit.language for unit in records[0].text_units} == {
        "en",
        "zh-Hans",
        "ja",
        "ru",
    }
    assert adapter.report.rows_seen == 1
    assert adapter.report.records_emitted == 1
    assert adapter.report.records_rejected == 0
    assert [issue.code for issue in adapter.report.issues] == ["MISSING_DECLARED_LANGUAGE"]


def test_csv_adapter_rejects_rows_without_identity_or_text(tmp_path: Path) -> None:
    csv_path = tmp_path / "invalid.csv"
    csv_path.write_text(
        "publication_number,family_id,languages,title_en,title_de\n"
        ",F1,en|de,polymer,Polymer\n"
        "EP-2-A1,F2,en|de,,\n",
        encoding="utf-8",
    )
    adapter = CsvTitleAdapter(csv_path)

    assert list(adapter.records()) == []
    assert adapter.report.rows_seen == 2
    assert adapter.report.records_rejected == 2
    assert {issue.code for issue in adapter.report.issues} == {
        "CONTRACT_VALIDATION_FAILED",
        "NO_TEXT",
    }


def test_csv_adapter_emits_title_and_abstract_units_per_language(tmp_path: Path) -> None:
    csv_path = tmp_path / "patent-text.csv"
    csv_path.write_text(
        "publication_number,languages,title_en,abstract_en,title_de,abstract_de\n"
        "EP-3-A1,en|de,Gold alloy,A copper coating.,Goldlegierung,"
        "Eine Kupferbeschichtung.\n",
        encoding="utf-8",
    )

    record = next(CsvTitleAdapter(csv_path).records())

    assert [(unit.language, unit.unit_type, unit.locator) for unit in record.text_units] == [
        ("en", TextUnitType.TITLE, "title"),
        ("en", TextUnitType.ABSTRACT, "abstract"),
        ("de", TextUnitType.TITLE, "title"),
        ("de", TextUnitType.ABSTRACT, "abstract"),
    ]


def test_source_normalization_decodes_html_with_offset_mapping() -> None:
    result = normalize_source_text("d&#39;or")

    assert result.normalized_text == "d'or"
    apostrophe = result.normalized_text.index("'")
    start, end = result.original_span(apostrophe, apostrophe + 1)
    assert result.original_text[start:end] == "&#39;"


def test_source_normalization_is_unicode_safe_across_scripts() -> None:
    assert normalize_source_text("  聚合物　涂层  ").normalized_text == "聚合物 涂层"
    assert normalize_source_text("полимерное   покрытие").normalized_text == "полимерное покрытие"
    assert normalize_source_text("ポリマー").normalized_text == "ポリマー"


def test_term_normalization_handles_formatting_without_erasing_chemistry() -> None:
    profile = TermNormalizationProfile.CHEMICAL_NAME

    assert normalize_term("C0: 1", profile) == normalize_term("C0 :1", profile)
    assert normalize_term("Co", profile) != normalize_term("CO", profile)
    assert normalize_term("D-glucose", profile) != normalize_term("L-glucose", profile)


def test_general_term_normalization_supports_cyrillic_casefolding() -> None:
    profile = TermNormalizationProfile.GENERAL

    assert normalize_term("ПОЛИМЕР", profile) == normalize_term("полимер", profile)
