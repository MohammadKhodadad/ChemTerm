"""Seed controlled terminology types."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from chemterm.db import session_scope
from chemterm.models import ConceptType, IdentifierNamespace, RelationType, TermForm
from chemterm.taxonomy import CONCEPT_TYPE_BY_CODE, CONCEPT_TYPE_DEFINITIONS

CONCEPT_TYPES: tuple[tuple[str, str, str | None], ...] = tuple(
    (item.code, item.label, item.parent_code) for item in CONCEPT_TYPE_DEFINITIONS
)

TERM_FORMS: tuple[tuple[str, str], ...] = (
    ("SYSTEMATIC_NAME", "Systematic name"),
    ("COMMON_NAME", "Common name"),
    ("TRIVIAL_NAME", "Trivial name"),
    ("TRADE_NAME", "Trade name"),
    ("ABBREVIATION", "Abbreviation"),
    ("ACRONYM", "Acronym"),
    ("MOLECULAR_FORMULA", "Molecular formula"),
    ("LINE_NOTATION", "Line notation"),
    ("REGISTRY_IDENTIFIER", "Registry identifier"),
    ("MULTIWORD_TECHNICAL_TERM", "Multi-word technical term"),
    ("PATENT_DEFINED_LABEL", "Patent-defined label"),
    ("SPELLING_VARIANT", "Spelling variant"),
    ("OTHER_TERM_FORM", "Other term form"),
)

RELATION_TYPES: tuple[tuple[str, str, bool], ...] = (
    ("BROADER_THAN", "Broader than", False),
    ("NARROWER_THAN", "Narrower than", False),
    ("RELATED_TO", "Related to", True),
    ("PART_OF", "Part of", False),
    ("SALT_OF", "Salt of", False),
    ("SOLVATE_OF", "Solvate of", False),
    ("HYDRATE_OF", "Hydrate of", False),
    ("ISOMER_OF", "Isomer of", True),
    ("STEREOISOMER_OF", "Stereoisomer of", True),
    ("POLYMER_OF", "Polymer of", False),
    ("DERIVATIVE_OF", "Derivative of", False),
    ("HAS_FUNCTIONAL_GROUP", "Has functional group", False),
)

IDENTIFIER_NAMESPACES: tuple[tuple[str, str, str, str], ...] = (
    (
        "CHEBI",
        "ChEBI ID",
        "Curated Chemical Entities of Biological Interest concept identifier.",
        "authoritative",
    ),
    (
        "PUBCHEM_CID",
        "PubChem CID",
        "PubChem compound identifier; distinguish compound, substance, and assay IDs.",
        "strong",
    ),
    (
        "INCHI",
        "InChI",
        "IUPAC structure-derived identifier; layers encode chemical structure details.",
        "authoritative",
    ),
    (
        "INCHIKEY",
        "InChIKey",
        "Hashed InChI structure key; exact equality is a strong identity signal.",
        "authoritative",
    ),
    (
        "CANONICAL_SMILES",
        "Canonical SMILES",
        "Canonicalized structure notation; compare only when generated consistently.",
        "strong",
    ),
    (
        "ISOMERIC_SMILES",
        "Isomeric SMILES",
        "Structure notation retaining available stereochemical information.",
        "strong",
    ),
    (
        "MOLECULAR_FORMULA",
        "Molecular formula",
        "Composition formula; supporting only because isomers share formulas.",
        "supporting",
    ),
    (
        "WIKIDATA",
        "Wikidata item",
        "Cross-domain concept identifier with variable curation depth.",
        "supporting",
    ),
    (
        "WIKIPEDIA_EN",
        "English Wikipedia page",
        "Human-readable English encyclopedia page linked through a Wikidata item.",
        "supporting",
    ),
    (
        "IATE",
        "IATE entry",
        "Interactive Terminology for Europe multilingual terminology entry.",
        "supporting",
    ),
    (
        "CAS_RN",
        "CAS Registry Number",
        "Registry identifier subject to CAS licensing and redistribution constraints.",
        "strong",
    ),
)


def _existing_codes(
    session: Session,
    model: type[ConceptType | TermForm | RelationType | IdentifierNamespace],
) -> set[str]:
    return set(session.scalars(select(model.code)))


def seed_concept_types(session: Session) -> None:
    """Insert missing hierarchical concept types."""

    existing = _existing_codes(session, ConceptType)
    by_code = {item.code: item for item in session.scalars(select(ConceptType))}

    for code, label, parent_code in CONCEPT_TYPES:
        definition = CONCEPT_TYPE_BY_CODE[code]
        if code in existing:
            item = by_code[code]
            item.label = label
            item.description = definition.description
            continue
        parent = by_code.get(parent_code) if parent_code else None
        item = ConceptType(
            code=code,
            label=label,
            description=definition.description,
            parent_id=parent.id if parent else None,
        )
        session.add(item)
        session.flush()
        by_code[code] = item


def seed_term_forms(session: Session) -> None:
    """Insert missing term-form values."""

    existing = _existing_codes(session, TermForm)
    session.add_all(
        TermForm(code=code, label=label) for code, label in TERM_FORMS if code not in existing
    )


def seed_relation_types(session: Session) -> None:
    """Insert missing concept-relation values."""

    existing = _existing_codes(session, RelationType)
    session.add_all(
        RelationType(code=code, label=label, symmetric=symmetric)
        for code, label, symmetric in RELATION_TYPES
        if code not in existing
    )


def seed_identifier_namespaces(session: Session) -> None:
    """Insert identifier definitions used by deterministic and LLM resolution."""

    existing = _existing_codes(session, IdentifierNamespace)
    session.add_all(
        IdentifierNamespace(
            code=code,
            label=label,
            description=description,
            identity_strength=strength,
        )
        for code, label, description, strength in IDENTIFIER_NAMESPACES
        if code not in existing
    )


def seed_all(seed_functions: Iterable = ()) -> None:
    """Seed all controlled values in one transaction."""

    functions = tuple(seed_functions) or (
        seed_concept_types,
        seed_term_forms,
        seed_relation_types,
        seed_identifier_namespaces,
    )
    with session_scope() as session:
        for seed_function in functions:
            seed_function(session)


if __name__ == "__main__":
    seed_all()
