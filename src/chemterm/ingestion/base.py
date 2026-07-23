"""Interfaces and diagnostics shared by input adapters."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from chemterm.contracts.input import PatentInput


class AdapterConfigurationError(ValueError):
    """Raised when a source cannot be interpreted by an adapter."""


@dataclass(frozen=True, slots=True)
class AdapterIssue:
    """Typed rejection or warning produced while reading source data."""

    row_number: int | None
    code: str
    message: str
    source_record_id: str | None = None


@dataclass(slots=True)
class AdapterReport:
    """Observable counters and issues for one adapter pass."""

    rows_seen: int = 0
    records_emitted: int = 0
    records_rejected: int = 0
    issues: list[AdapterIssue] = field(default_factory=list)

    def reject(self, issue: AdapterIssue) -> None:
        """Record a rejected source record."""

        self.records_rejected += 1
        self.issues.append(issue)

    def warn(self, issue: AdapterIssue) -> None:
        """Record a non-fatal source issue."""

        self.issues.append(issue)


class PatentInputAdapter(Protocol):
    """Port implemented by all patent input sources."""

    report: AdapterReport

    def records(self) -> Iterator[PatentInput]:
        """Stream validated, source-independent patent records."""

        ...
