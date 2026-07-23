"""ChemDataExtractor NER adapter over an isolated Python 3.11 worker."""

from __future__ import annotations

import atexit
import json
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from chemterm.contracts.extraction import CandidateType, RawCandidate


class _PersistentJsonWorker:
    def __init__(self, command: Sequence[str]) -> None:
        if not command:
            raise ValueError("ChemDataExtractor worker command cannot be empty")
        self.command = tuple(command)
        self.process: subprocess.Popen[str] | None = None
        atexit.register(self.close)

    def request(self, text: str) -> list[dict[str, Any]]:
        process = self._start()
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        process.stdin.flush()
        response: dict[str, Any] | None = None
        while response is None:
            response_line = process.stdout.readline()
            if not response_line:
                raise RuntimeError(
                    "ChemDataExtractor worker stopped unexpectedly; see worker stderr"
                )
            try:
                decoded = json.loads(response_line)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict) and ("entities" in decoded or "error" in decoded):
                response = decoded
        if "error" in response:
            raise RuntimeError(f"ChemDataExtractor worker failed: {response['error']}")
        return list(response["entities"])

    def _start(self) -> subprocess.Popen[str]:
        if self.process is None or self.process.poll() is not None:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        return self.process

    def close(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        finally:
            self.process = None


class ChemDataExtractorNerExtractor:
    """Adapt ChemDataExtractor chemical mentions to exact ChemTerm spans."""

    name = "chemdataextractor_ner"
    version = "chemdataextractor2"

    def __init__(
        self,
        command: Sequence[str] | None = None,
        *,
        request: Callable[[str], list[dict[str, Any]]] | None = None,
    ) -> None:
        if request is None and not command:
            raise ValueError("command is required when no request function is supplied")
        self._worker = _PersistentJsonWorker(command or ()) if request is None else None
        self._request = request or self._worker.request  # type: ignore[union-attr]

    def extract(self, text: str) -> tuple[RawCandidate, ...]:
        """Return CEM spans supplied by the isolated worker."""

        candidates: list[RawCandidate] = []
        for entity in self._request(text):
            start = int(entity["start"])
            end = int(entity["end"])
            if start < 0 or end <= start or end > len(text):
                raise ValueError(f"ChemDataExtractor returned invalid span [{start}, {end})")
            if text[start:end] != entity["text"]:
                raise ValueError("ChemDataExtractor text does not match its source span")
            candidates.append(
                RawCandidate(
                    text=entity["text"],
                    start=start,
                    end=end,
                    types=(CandidateType.CHEMICAL_ENTITY,),
                    confidence=float(entity.get("confidence", 0.9)),
                    extractor=self.name,
                    extractor_version=self.version,
                    raw_label="CEM",
                    metadata={"model_name": "chemdataextractor2"},
                )
            )
        return tuple(sorted(candidates, key=lambda item: (item.start, item.end)))

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()
