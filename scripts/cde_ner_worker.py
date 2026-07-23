"""JSON-lines worker for ChemDataExtractor 2 under Python 3.11."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout

with redirect_stdout(sys.stderr):
    from chemdataextractor.doc import Paragraph


def extract(text: str) -> list[dict[str, object]]:
    """Return exact chemical entity mention spans."""

    with redirect_stdout(sys.stderr):
        mentions = Paragraph(text).cems
    return [
        {"text": span.text, "start": span.start, "end": span.end, "confidence": 0.9}
        for span in mentions
    ]


def main() -> int:
    """Serve one JSON response for every input line."""

    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = {"entities": extract(str(request["text"]))}
        except Exception as error:
            response = {"error": f"{type(error).__name__}: {error}"}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
