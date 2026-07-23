"""Streaming adapter for multilingual patent title and abstract CSV files."""

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
    """Map a wide multilingual patent-text CSV into canonical patent inputs.

    Language columns are discovered dynamically from ``title_<language>`` and
    ``abstract_<language>`` prefixes.
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
            text_columns = self._discover_text_columns(reader.fieldnames)

            for row_number, row in enumerate(reader, start=2):
                self.report.rows_seen += 1
                record = self._map_row(row, row_number, text_columns)
                if record is None:
                    continue
                self.report.records_emitted += 1
                yield record

    def _discover_text_columns(
        self,
        fieldnames: list[str] | None,
    ) -> tuple[tuple[str, str, TextUnitType], ...]:
        if not fieldnames:
            raise AdapterConfigurationError("CSV has no header")
        if "publication_number" not in fieldnames:
            raise AdapterConfigurationError("CSV requires a publication_number column")

        discovered: list[tuple[str, str, TextUnitType]] = []
        for column in fieldnames:
            prefix_and_type = next(
                (
                    (prefix, unit_type)
                    for prefix, unit_type in (
                        ("title_", TextUnitType.TITLE),
                        ("abstract_", TextUnitType.ABSTRACT),
                    )
                    if column.startswith(prefix)
                ),
                None,
            )
            if prefix_and_type is None:
                continue
            prefix, unit_type = prefix_and_type
            raw_language = column.removeprefix(prefix).replace("_", "-")
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
            discovered.append((column, language, unit_type))

        if not discovered:
            raise AdapterConfigurationError(
                "CSV requires at least one title_<language> or abstract_<language> column"
            )
        return tuple(discovered)

    def _map_row(
        self,
        row: dict[str, str | None],
        row_number: int,
        text_columns: tuple[tuple[str, str, TextUnitType], ...],
    ) -> PatentInput | None:
        publication_number = (row.get("publication_number") or "").strip()
        source_record_id = f"{self.source_name}:{row_number}"

        text_units = tuple(
            TextUnit(
                language=language,
                text=value,
                unit_type=unit_type,
                locator=unit_type.value,
                text_origin=TextOrigin.UNKNOWN,
                metadata={"source_column": column},
            )
            for column, language, unit_type in text_columns
            if (value := row.get(column)) is not None and value.strip()
        )

        if not text_units:
            self.report.reject(
                AdapterIssue(
                    row_number=row_number,
                    code="NO_TEXT",
                    message="row has no non-empty multilingual title or abstract",
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
                    message=f"declared language {language!r} has no title or abstract text",
                    source_record_id=source_record_id,
                )
            )
        for language in available_languages - declared_languages:
            self.report.warn(
                AdapterIssue(
                    row_number=row_number,
                    code="UNDECLARED_AVAILABLE_LANGUAGE",
                    message=f"text language {language!r} was not declared",
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
