"""Command-line entry point for English terminology extraction."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import TextIO

from chemterm.ingestion import CsvTitleAdapter
from chemterm.pipeline import build_english_pipeline, build_llm_pairing_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Multilingual patent-title CSV")
    parser.add_argument("--output", type=Path, help="Output JSONL; defaults to stdout")
    parser.add_argument("--ner-model", help="Optional Hugging Face token-classification model")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable configured schema-constrained LLM refinement",
    )
    parser.add_argument(
        "--pair-languages",
        nargs="+",
        metavar="LANGUAGE",
        help="Map English candidates to exact spans in these parallel languages",
    )
    return parser


def main() -> int:
    """Extract records and emit one structured JSON result per input row."""

    args = build_parser().parse_args()
    adapter = CsvTitleAdapter(args.input)
    pipeline = build_english_pipeline(ner_model=args.ner_model, use_llm=args.llm)
    pairing_pipeline = build_llm_pairing_pipeline() if args.pair_languages else None

    output_context = (
        args.output.open("w", encoding="utf-8") if args.output else nullcontext(sys.stdout)
    )
    result_count = 0
    with output_context as output:
        stream: TextIO = output
        for record in adapter.records():
            result = pipeline.extract(record)
            if pairing_pipeline is None:
                serialized = result.model_dump(mode="json")
            else:
                mapping = pairing_pipeline.pair(
                    record,
                    result,
                    target_languages=args.pair_languages,
                )
                serialized = {
                    "extraction": result.model_dump(mode="json"),
                    "mapping": mapping.model_dump(mode="json"),
                }
            stream.write(json.dumps(serialized, ensure_ascii=False) + "\n")
            result_count += 1

    print(
        f"processed={result_count} rejected={adapter.report.records_rejected} "
        f"adapter_issues={len(adapter.report.issues)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
