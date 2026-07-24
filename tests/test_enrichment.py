"""Tests for external concept authority enrichment."""

from __future__ import annotations

import json

import httpx

from chemterm.enrichment import (
    ConceptEnrichmentService,
    IateReferenceProvider,
    PubChemReferenceProvider,
    WikidataReferenceProvider,
)
from chemterm.resolution import ConceptProposal


def _proposal(term: str, *type_codes: str) -> ConceptProposal:
    return ConceptProposal(
        proposal_id=f"test:{term}",
        term=term,
        normalized_term=term.casefold(),
        type_codes=type_codes,
    )


def test_pubchem_provider_returns_canonical_compound_reference() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/compound/name/water/property/" in str(request.url)
        return httpx.Response(
            200,
            json={
                "PropertyTable": {
                    "Properties": [
                        {
                            "CID": 962,
                            "Title": "Water",
                            "IUPACName": "oxidane",
                            "InChIKey": "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
                        }
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        references = PubChemReferenceProvider(client).lookup(_proposal("water", "COMPOUND"))

    assert references[0].namespace == "PUBCHEM_CID"
    assert references[0].external_id == "962"
    assert not references[0].needs_review


def test_wikidata_provider_rejects_homonyms_and_adds_wikipedia() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params["action"]
        if action == "wbsearchentities":
            return httpx.Response(
                200,
                json={
                    "search": [
                        {
                            "id": "Q1",
                            "label": "Starch",
                            "description": "family name",
                            "match": {"type": "label", "text": "Starch"},
                        },
                        {
                            "id": "Q41534",
                            "label": "starch",
                            "description": "carbohydrate consisting of glucose units",
                            "match": {"type": "label", "text": "starch"},
                        },
                    ]
                },
            )
        assert action == "wbgetentities"
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q41534": {
                        "descriptions": {
                            "en": {"value": "carbohydrate consisting of glucose units"}
                        },
                        "sitelinks": {
                            "enwiki": {
                                "title": "Starch",
                                "url": "https://en.wikipedia.org/wiki/Starch",
                            }
                        },
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        references = WikidataReferenceProvider(client).lookup(_proposal("starch", "CHEMICAL_CLASS"))

    assert {(item.namespace, item.external_id) for item in references} == {
        ("WIKIDATA", "Q41534"),
        ("WIKIPEDIA_EN", "Starch"),
    }
    assert all(not item.needs_review for item in references)


def test_wikidata_provider_singularizes_plural_when_exact_results_are_not_domain_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params["action"]
        if action == "wbsearchentities":
            if request.url.params["search"] == "fuel cells":
                return httpx.Response(
                    200,
                    json={
                        "search": [
                            {
                                "id": "Q-JOURNAL",
                                "label": "Fuel Cells",
                                "description": "journal",
                                "match": {"type": "label", "text": "Fuel Cells"},
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "search": [
                        {
                            "id": "Q180253",
                            "label": "fuel cell",
                            "description": "electrochemical cell that converts chemical energy",
                            "match": {"type": "label", "text": "fuel cell"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q180253": {
                        "descriptions": {
                            "en": {"value": "electrochemical cell that converts chemical energy"}
                        },
                        "sitelinks": {},
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        references = WikidataReferenceProvider(client).lookup(_proposal("fuel cells", "EQUIPMENT"))

    assert references[0].external_id == "Q180253"
    assert not references[0].needs_review


def test_iate_provider_returns_exact_entry_and_definition() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert json.loads(request.content)["query"] == "polymer"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 3535130,
                        "code": "IATE-CODE",
                        "domains": [{"name": "chemistry"}],
                        "language": {
                            "en": {
                                "term_entries": [{"term_value": "polymer"}],
                                "definition": {"value": "A chemical polymer definition."},
                            }
                        },
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        references = IateReferenceProvider(client).lookup(_proposal("polymer", "POLYMER"))

    assert references[0].namespace == "IATE"
    assert references[0].external_id == "3535130"
    assert references[0].description == "A chemical polymer definition."
    assert not references[0].needs_review


def test_enrichment_service_isolates_provider_failures() -> None:
    class BrokenProvider:
        name = "broken"

        def lookup(self, proposal: ConceptProposal):
            raise RuntimeError("temporary failure")

    class EmptyProvider:
        name = "empty"

        def lookup(self, proposal: ConceptProposal):
            return ()

    result = ConceptEnrichmentService((BrokenProvider(), EmptyProvider())).enrich(
        _proposal("water", "COMPOUND")
    )

    assert result.references == ()
    assert result.issues[0].provider == "broken"
    assert result.issues[0].code == "LOOKUP_FAILED"
