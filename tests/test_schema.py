"""Tests for terminology schema invariants."""

import uuid

import pytest
from pydantic import ValidationError

from chemterm.contracts.extraction import CandidateType
from chemterm.models import Base
from chemterm.schemas import EvidenceSetCreate, TermCreate
from chemterm.seed import CONCEPT_TYPES
from chemterm.taxonomy import CONCEPT_TYPE_DEFINITIONS


def test_authoritative_schema_contains_only_terminology_tables() -> None:
    expected = {
        "concept",
        "concept_embedding",
        "concept_identifier",
        "concept_relation",
        "concept_type",
        "concept_type_assignment",
        "evidence_set",
        "identifier_namespace",
        "pipeline_run",
        "relation_type",
        "review_decision",
        "term",
        "term_evidence",
        "term_form",
    }

    assert set(Base.metadata.tables) == expected
    assert "document" not in Base.metadata.tables
    assert "passage" not in Base.metadata.tables
    assert "term_pair" not in Base.metadata.tables


def test_resolution_schema_has_controlled_identifiers_and_search_indexes() -> None:
    identifier = Base.metadata.tables["concept_identifier"]
    term = Base.metadata.tables["term"]
    embedding = Base.metadata.tables["concept_embedding"]

    assert identifier.c.namespace_id.foreign_keys
    assert "namespace" not in identifier.c
    assert any(index.name == "ix_term_normalized_trgm" for index in term.indexes)
    vector_index = next(
        index for index in embedding.indexes if index.name == "ix_concept_embedding_hnsw"
    )
    assert vector_index.dialect_options["postgresql"]["using"] == "hnsw"


def test_term_has_one_concept_and_language() -> None:
    table = Base.metadata.tables["term"]

    assert not table.c.concept_id.nullable
    assert not table.c.language.nullable
    assert table.c.concept_id.foreign_keys


def test_preferred_term_index_is_unique() -> None:
    table = Base.metadata.tables["term"]
    index = next(
        item for item in table.indexes if item.name == "uq_term_preferred_per_concept_language"
    )

    assert index.unique
    assert [column.name for column in index.columns] == ["concept_id", "language"]
    assert index.dialect_options["postgresql"]["where"] is not None


def test_term_contract_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        TermCreate(
            concept_id=uuid.uuid4(),
            text="aspirin",
            normalized_text="aspirin",
            language="en",
            confidence=1.1,
        )


def test_evidence_set_requires_one_family() -> None:
    with pytest.raises(ValidationError, match="evidence set family_id"):
        EvidenceSetCreate.model_validate(
            {
                "family_id": "family-1",
                "extraction_method": "ner_llm",
                "confidence": 0.9,
                "terms": [
                    {
                        "term_id": str(uuid.uuid4()),
                        "family_id": "family-2",
                        "publication_number": "EP-123-A1",
                        "source_language": "en",
                        "confidence": 0.9,
                    }
                ],
            }
        )


def test_seeded_concept_type_parents_precede_children() -> None:
    seen: set[str] = set()

    for code, _, parent_code in CONCEPT_TYPES:
        assert parent_code is None or parent_code in seen
        seen.add(code)


def test_extraction_and_database_use_same_defined_types() -> None:
    extraction_codes = {item.value for item in CandidateType}
    definitions = {item.code: item.description for item in CONCEPT_TYPE_DEFINITIONS}

    assert extraction_codes == set(definitions)
    assert all(definition.strip() for definition in definitions.values())
