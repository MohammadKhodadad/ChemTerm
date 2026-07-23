"""Streaming adapter for multilingual patent-title CSV files."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from chemterm.contracts.input import (
    PatentInput,
    TextOrigin,
    TextUnit,
    TextUnitType,
    canonicalize_language_tag,
)
from chemterm.ingestion.base import (
    AdapterConfigurationError,
    AdapterIssue,
    AdapterReport,
)


class CsvTitleAdapter:
    """Map a wide multilingual title CSV into canonical patent inputs.

    Language columns are discovered dynamically from the ``title_<language>``
    prefix, so the adapter is not limited to the current four test columns.
    Examples include ``title_zh``, ``title_zh_hans``, ``title_ja``, and
    ``title_ru``.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        encoding: str = "utf-8-sig",
        source_name: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.encoding = encoding
        self.source_name = source_name or self.path.name
        self.report = AdapterReport()

    def records(self) -> Iterator[PatentInput]:
        """Stream valid rows and collect typed diagnostics for invalid rows."""

        self.report = AdapterReport()
        with self.path.open("r", encoding=self.encoding, newline="") as source:
            reader = csv.DictReader(source)
            title_columns = self._discover_title_columns(reader.fieldnames)

            for row_number, row in enumerate(reader, start=2):
                self.report.rows_seen += 1
                record = self._map_row(row, row_number, title_columns)
                if record is None:
                    continue
                self.report.records_emitted += 1
                yield record

    def _discover_title_columns(self, fieldnames: list[str] | None) -> tuple[tuple[str, str], ...]:
        if not fieldnames:
            raise AdapterConfigurationError("CSV has no header")
        if "publication_number" not in fieldnames:
            raise AdapterConfigurationError("CSV requires a publication_number column")

        discovered: list[tuple[str, str]] = []
        for column in fieldnames:
            if not column.startswith("title_"):
                continue
            raw_language = column.removeprefix("title_").replace("_", "-")
            try:
                language = canonicalize_language_tag(raw_language)
            except ValueError as error:
                self.report.warn(
                    AdapterIssue(
                        row_number=None,
                        code="INVALID_LANGUAGE_COLUMN",
                        message=f"{column}: {error}",
                    )
                )
                continue
            discovered.append((column, language))

        if not discovered:
            raise AdapterConfigurationError("CSV requires at least one title_<language> column")
        return tuple(discovered)

    def _map_row(
        self,
        row: dict[str, str | None],
        row_number: int,
        title_columns: tuple[tuple[str, str], ...],
    ) -> PatentInput | None:
        publication_number = (row.get("publication_number") or "").strip()
        source_record_id = f"{self.source_name}:{row_number}"

        text_units = tuple(
            TextUnit(
                language=language,
                text=value,
                unit_type=TextUnitType.TITLE,
                locator="title",
                text_origin=TextOrigin.UNKNOWN,
                metadata={"source_column": column},
            )
            for column, language in title_columns
            if (value := row.get(column)) is not None and value.strip()
        )

        if not text_units:
            self.report.reject(
                AdapterIssue(
                    row_number=row_number,
                    code="NO_TEXT",
                    message="row has no non-empty multilingual title",
                    source_record_id=source_record_id,
                )
            )
            return None

        declared_languages = self._declared_languages(row.get("languages"))
        available_languages = {unit.language for unit in text_units}
        for language in declared_languages - available_languages:
            self.report.warn(
                AdapterIssue(
                    row_number=row_number,
                    code="MISSING_DECLARED_LANGUAGE",
                    message=f"declared language {language!r} has no title text",
                    source_record_id=source_record_id,
                )
            )
        for language in available_languages - declared_languages:
            self.report.warn(
                AdapterIssue(
                    row_number=row_number,
                    code="UNDECLARED_AVAILABLE_LANGUAGE",
                    message=f"title language {language!r} was not declared",
                    source_record_id=source_record_id,
                )
            )

        try:
            return PatentInput(
                source_record_id=source_record_id,
                family_id=row.get("family_id"),
                publication_number=publication_number,
                source_uri=(row.get("source_uri") or None),
                text_units=text_units,
                metadata={
                    "adapter": "csv_titles",
                    "source_name": self.source_name,
                    "row_number": row_number,
                    "declared_languages": sorted(declared_languages),
                },
            )
        except ValidationError as error:
            self.report.reject(
                AdapterIssue(
                    row_number=row_number,
                    code="CONTRACT_VALIDATION_FAILED",
                    message=str(error),
                    source_record_id=source_record_id,
                )
            )
            return None

    def _declared_languages(self, value: str | None) -> set[str]:
        languages: set[str] = set()
        for raw_language in (value or "").split("|"):
            if not raw_language.strip():
                continue
            try:
                languages.add(canonicalize_language_tag(raw_language))
            except ValueError as error:
                self.report.warn(
                    AdapterIssue(
                        row_number=None,
                        code="INVALID_DECLARED_LANGUAGE",
                        message=str(error),
                    )
                )
        return languages
