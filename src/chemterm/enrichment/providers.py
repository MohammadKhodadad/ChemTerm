"""Read-only clients for PubChem, Wikidata/Wikipedia, and IATE."""

from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

import httpx

from chemterm.enrichment.contracts import (
    ExternalConceptReference,
    ExternalMappingType,
)
from chemterm.resolution.contracts import ConceptProposal

_CHEMISTRY_WORDS = {
    "alloy",
    "carbohydrate",
    "chemical",
    "chemistry",
    "coating",
    "compound",
    "electrochemical",
    "element",
    "material",
    "metal",
    "molecule",
    "polymer",
    "polysaccharide",
    "protein",
    "reaction",
    "substance",
}
_NON_DOMAIN_WORDS = {
    "album",
    "article",
    "family name",
    "film",
    "given name",
    "journal",
    "music",
    "surname",
    "video game",
}
_PUBCHEM_TYPES = {
    "CHEMICAL_ENTITY",
    "ELEMENT",
    "COMPOUND",
    "SALT",
    "SOLVATE",
    "HYDRATE",
}


def _key(value: str) -> str:
    return " ".join(value.casefold().split())


def _domain_score(description: str | None) -> int:
    text = (description or "").casefold()
    if any(word in text for word in _NON_DOMAIN_WORDS):
        return -1
    return sum(word in text for word in _CHEMISTRY_WORDS)


class PubChemReferenceProvider:
    """Resolve exact compound-name matches through PubChem PUG REST."""

    name = "pubchem"

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def lookup(self, proposal: ConceptProposal) -> tuple[ExternalConceptReference, ...]:
        if proposal.type_codes and not set(proposal.type_codes).intersection(_PUBCHEM_TYPES):
            return ()
        url = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            f"{quote(proposal.term, safe='')}/property/Title,IUPACName,InChIKey/JSON"
        )
        response = self.client.get(url)
        if response.status_code == 404:
            return ()
        response.raise_for_status()
        properties = response.json().get("PropertyTable", {}).get("Properties", [])
        ambiguous = len(properties) > 1
        references: list[ExternalConceptReference] = []
        for item in properties[:3]:
            cid = str(item["CID"])
            label = item.get("Title") or item.get("IUPACName") or proposal.term
            exact_label = _key(label) == _key(proposal.term)
            references.append(
                ExternalConceptReference(
                    namespace="PUBCHEM_CID",
                    external_id=cid,
                    label=label,
                    canonical_url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                    description=(
                        f"IUPAC name: {item['IUPACName']}" if item.get("IUPACName") else None
                    ),
                    mapping_type=(
                        ExternalMappingType.EXACT if exact_label else ExternalMappingType.CLOSE
                    ),
                    confidence=0.96 if exact_label and not ambiguous else 0.72,
                    needs_review=ambiguous or not exact_label,
                    metadata={
                        "inchikey": item.get("InChIKey"),
                        "provider": "PubChem PUG REST",
                    },
                )
            )
        return tuple(references)


class WikidataReferenceProvider:
    """Find a chemistry-aware Wikidata candidate and its English Wikipedia page."""

    name = "wikidata"

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def lookup(self, proposal: ConceptProposal) -> tuple[ExternalConceptReference, ...]:
        candidates = self._search(proposal.term)
        if proposal.term.casefold().endswith("s") and (
            not candidates or max(item[0] for item in candidates) == 0
        ):
            candidates.extend(self._search(proposal.term[:-1]))
        if not candidates:
            return ()

        domain_score, _, selected = max(candidates, key=lambda value: (value[0], value[1]))
        qid = selected["id"]
        entity_response = self._get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "labels|descriptions|sitelinks/urls",
                "languages": "en",
                "sitefilter": "enwiki",
                "format": "json",
                "formatversion": 2,
            },
        )
        entity_response.raise_for_status()
        entity = entity_response.json().get("entities", {}).get(qid, {})
        description = entity.get("descriptions", {}).get("en", {}).get("value") or selected.get(
            "description"
        )
        confident = domain_score > 0
        references = [
            ExternalConceptReference(
                namespace="WIKIDATA",
                external_id=qid,
                label=selected.get("label") or proposal.term,
                canonical_url=f"https://www.wikidata.org/wiki/{qid}",
                description=description,
                mapping_type=(
                    ExternalMappingType.EXACT if confident else ExternalMappingType.CLOSE
                ),
                confidence=0.92 if confident else 0.65,
                needs_review=not confident,
                metadata={"search_match_type": selected.get("match", {}).get("type", "unknown")},
            )
        ]
        sitelink = entity.get("sitelinks", {}).get("enwiki")
        if sitelink and sitelink.get("url"):
            references.append(
                ExternalConceptReference(
                    namespace="WIKIPEDIA_EN",
                    external_id=sitelink["title"],
                    label=sitelink["title"],
                    canonical_url=sitelink["url"],
                    description=description,
                    mapping_type=(
                        ExternalMappingType.EXACT if confident else ExternalMappingType.CLOSE
                    ),
                    confidence=0.9 if confident else 0.62,
                    needs_review=not confident,
                    metadata={"wikidata_id": qid},
                )
            )
        return tuple(references)

    def _search(self, term: str) -> list[tuple[int, int, dict]]:
        response = self._get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": term,
                "language": "en",
                "uselang": "en",
                "type": "item",
                "limit": 10,
                "format": "json",
            },
        )
        response.raise_for_status()
        candidates = []
        for order, item in enumerate(response.json().get("search", [])):
            label = item.get("label") or ""
            match_text = item.get("match", {}).get("text") or label
            if _key(label) != _key(term) and _key(match_text) != _key(term):
                continue
            description = item.get("description")
            domain_score = _domain_score(description)
            if domain_score < 0:
                continue
            candidates.append((domain_score, -order, item))
        return candidates

    def _get(self, url: str, *, params: dict) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(4):
            response = self.client.get(url, params=params)
            if response.status_code != 429:
                return response
            retry_after = float(response.headers.get("Retry-After", 1))
            time.sleep(max(retry_after, 1.5 * (2**attempt)))
        assert response is not None
        return response


class IateReferenceProvider:
    """Find exact English terms through IATE's public search API."""

    name = "iate"

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def lookup(self, proposal: ConceptProposal) -> tuple[ExternalConceptReference, ...]:
        response = self.client.post(
            "https://iate.europa.eu/em-api/ws/entries/_search",
            params={"expand": "true", "offset": 0, "limit": 5, "trans_lang": "en"},
            json={
                "query": proposal.term,
                "source": "en",
                "targets": [],
                "search_in_fields": [0],
                "search_in_term_types": [0, 1, 2, 3, 4],
                "query_operator": "3",
            },
        )
        response.raise_for_status()
        matches: list[tuple[dict, str]] = []
        for item in response.json().get("items", []):
            term_entries = item.get("language", {}).get("en", {}).get("term_entries", [])
            exact = next(
                (
                    entry.get("term_value")
                    for entry in term_entries
                    if _key(entry.get("term_value", "")) == _key(proposal.term)
                ),
                None,
            )
            if exact:
                matches.append((item, exact))

        ambiguous = len(matches) > 1
        references = []
        for item, label in matches[:3]:
            entry_id = str(item["id"])
            serialized = json.dumps(item, ensure_ascii=False).casefold()
            chemistry_context = any(word in serialized for word in _CHEMISTRY_WORDS)
            confidence = 0.9 if chemistry_context and not ambiguous else 0.68
            references.append(
                ExternalConceptReference(
                    namespace="IATE",
                    external_id=entry_id,
                    label=label,
                    canonical_url=f"https://iate.europa.eu/entry/result/{entry_id}/en",
                    description=self._definition(item),
                    mapping_type=(
                        ExternalMappingType.EXACT
                        if chemistry_context
                        else ExternalMappingType.CLOSE
                    ),
                    confidence=confidence,
                    needs_review=ambiguous or not chemistry_context,
                    metadata={
                        "iate_code": item.get("code"),
                        "result_score": item.get("score"),
                    },
                )
            )
        return tuple(references)

    @staticmethod
    def _definition(item: dict) -> str | None:
        definition = item.get("language", {}).get("en", {}).get("definition")
        if not definition:
            return None
        value = definition.get("value") if isinstance(definition, dict) else str(definition)
        return re.sub(r"<[^>]+>", " ", value).strip()[:5_000] if value else None
