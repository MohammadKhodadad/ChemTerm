"""CLI for external concept-reference coverage and audit reports."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from chemterm.enrichment import (
    ConceptEnrichmentService,
    IateReferenceProvider,
    PubChemReferenceProvider,
    WikidataReferenceProvider,
)
from chemterm.normalization import TermNormalizationProfile, normalize_term
from chemterm.resolution import ConceptProposal


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find PubChem, Wikidata/Wikipedia, and IATE concept references"
    )
    parser.add_argument("report", type=Path, help="ChemTerm extraction JSONL report")
    parser.add_argument("--output", type=Path, required=True, help="Enrichment JSONL output")
    parser.add_argument(
        "--source-csv",
        type=Path,
        help="Optional source CSV used to attach publication and family identifiers",
    )
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    return parser


def _documents(path: Path | None) -> dict[str, dict[str, str | None]]:
    if path is None:
        return {}
    result = {}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row_number, row in enumerate(csv.DictReader(source), start=2):
            result[f"{path.name}:{row_number}"] = {
                "source_record_id": f"{path.name}:{row_number}",
                "publication_number": row.get("publication_number"),
                "family_id": row.get("family_id"),
            }
    return result


def _terms(path: Path) -> dict[tuple[str, tuple[str, ...]], set[str]]:
    terms: dict[tuple[str, tuple[str, ...]], set[str]] = defaultdict(set)
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            payload = json.loads(line)
            extraction = payload.get("extraction", payload)
            candidates = extraction.get("refined_candidates", [])
            for candidate in candidates:
                key = (candidate["text"], tuple(candidate.get("types", [])))
                terms[key].add(extraction["source_record_id"])
    return terms


def main() -> int:
    """Enrich unique refined terms and write auditable authority matches."""

    args = _parser().parse_args()
    terms = _terms(args.report)
    documents = _documents(args.source_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    namespace_terms: dict[str, set[str]] = defaultdict(set)
    matched_terms: set[str] = set()
    with (
        httpx.Client(
            timeout=30,
            headers={"User-Agent": "ChemTerm/0.1 research concept enrichment"},
            transport=httpx.HTTPTransport(retries=2),
        ) as client,
        args.output.open("w", encoding="utf-8", newline="\n") as output,
    ):
        service = ConceptEnrichmentService(
            (
                PubChemReferenceProvider(client),
                WikidataReferenceProvider(client),
                IateReferenceProvider(client),
            )
        )
        for index, ((term, type_codes), source_ids) in enumerate(sorted(terms.items())):
            proposal = ConceptProposal(
                proposal_id=f"external:{index}",
                term=term,
                normalized_term=normalize_term(term, TermNormalizationProfile.GENERAL),
                type_codes=type_codes,
            )
            result = service.enrich(proposal)
            if result.references:
                matched_terms.add(term)
            for reference in result.references:
                namespace_terms[reference.namespace].add(term)
            row: dict[str, Any] = {
                **result.model_dump(mode="json"),
                "type_codes": type_codes,
                "source_documents": [
                    documents.get(source_id, {"source_record_id": source_id})
                    for source_id in sorted(source_ids)
                ],
            }
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            if args.delay_seconds > 0:
                time.sleep(args.delay_seconds)

    print(
        json.dumps(
            {
                "unique_terms": len(terms),
                "terms_with_external_references": len(matched_terms),
                "coverage": len(matched_terms) / len(terms) if terms else 0,
                "terms_by_namespace": {
                    namespace: len(values) for namespace, values in sorted(namespace_terms.items())
                },
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
