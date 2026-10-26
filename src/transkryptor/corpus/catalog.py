"""Katalog nagrań: zbiorcza tabela metryczek projektów korpusu (bez Qt).

Wiersz katalogu to jeden projekt: plik projektu (ścieżka względem folderu
korpusu), pola metryczki w kolejności konfiguracji zespołu (z polami spoza
konfiguracji na końcu, jak w eksporcie DOCX), autor i data transkrypcji,
legenda mówców, nagranie (nazwa i suma SHA-256) oraz liczby słów
i komentarzy. ``anonymize`` pomija pola osobowe i etykiety informatorów.

Tabela trafia do CSV (UTF-8 z BOM, czytelny w Excelu) albo XLSX
(``corpus/xlsx.py``). Ten sam moduł buduje tabelę słownika form.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from transkryptor.corpus.forms import FormEntry
from transkryptor.corpus.projects import CorpusProject
from transkryptor.corpus.xlsx import Cell, xlsx_bytes
from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    MetadataField,
    export_items,
)
from transkryptor.document.speakers import informant_spans, legend
from transkryptor.errors import ExportError
from transkryptor.i18n import tr

CSV_SUFFIX = ".csv"
XLSX_SUFFIX = ".xlsx"


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]


def catalog_columns(
    projects: Iterable[CorpusProject],
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
) -> list[MetadataField]:
    """Pola metryczki obecne w katalogu, w kolejności konfiguracji.

    Pola włączone w konfiguracji są zawsze (także puste), a pola spoza niej
    - gdy któryś projekt ma w nich wartość.
    """
    configured = tuple(fields)
    columns: dict[str, MetadataField] = {
        field.key: field
        for field in configured
        if field.enabled and not (anonymize and field.personal)
    }
    for project in projects:
        for field, _value in export_items(
            project.state.metadata, configured, anonymize
        ):
            columns.setdefault(field.key, field)
    return list(columns.values())


def catalog_table(
    projects: Sequence[CorpusProject],
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
    folder: Path | None = None,
) -> Table:
    """Katalog nagrań jako tabela (nagłówek i wiersze)."""
    configured = tuple(fields)
    columns = catalog_columns(projects, configured, anonymize)
    header = (
        tr("corpus.catalog.project"),
        *(field.display_label for field in columns),
        tr("corpus.catalog.author"),
        tr("corpus.catalog.date"),
        tr("corpus.catalog.speakers"),
        tr("corpus.catalog.audio"),
        tr("corpus.catalog.sha256"),
        tr("corpus.catalog.words"),
        tr("corpus.catalog.informant_words"),
        tr("corpus.catalog.comments"),
    )
    rows: list[tuple[Cell, ...]] = []
    for project in projects:
        state = project.state
        values = {
            field.key: value
            for field, value in export_items(state.metadata, configured, anonymize)
        }
        uses_speakers = bool(state.paragraph_speakers)
        informant_words = sum(
            len(state.text[start:end].split())
            for start, end in informant_spans(
                state.text, state.paragraph_speakers, state.speakers
            )
        )
        rows.append(
            (
                project.relative_name(folder),
                *(values.get(field.key, "") for field in columns),
                state.author,
                state.date,
                legend(state.speakers, anonymize) if uses_speakers else "",
                state.audio.name if state.audio is not None else "",
                state.audio.sha256 if state.audio is not None else "",
                state.word_count,
                informant_words if uses_speakers else "",
                0 if anonymize else len(state.comments),
            )
        )
    return Table(header, tuple(rows))


def forms_table(
    entries: Iterable[FormEntry], similar: dict[str, tuple[str, ...]]
) -> Table:
    """Słownik form: forma, liczba wystąpień i projektów, formy podobne."""
    return Table(
        (
            tr("corpus.forms.form"),
            tr("corpus.forms.count"),
            tr("corpus.forms.projects"),
            tr("corpus.forms.similar"),
        ),
        tuple(
            (
                entry.form,
                entry.count,
                entry.project_count,
                ", ".join(similar.get(entry.form, ())),
            )
            for entry in entries
        ),
    )


def csv_bytes(table: Table) -> bytes:
    """CSV (przecinek, cudzysłowy wg RFC 4180) w UTF-8 z BOM dla Excela."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(table.header)
    writer.writerows(table.rows)
    return buffer.getvalue().encode("utf-8-sig")


def save_table(table: Table, path: str | Path, sheet_name: str = "") -> None:
    """Zapisuje tabelę jako XLSX (rozszerzenie ``.xlsx``) albo CSV."""
    target = Path(path)
    if target.suffix.lower() == XLSX_SUFFIX:
        payload = xlsx_bytes(table.header, table.rows, sheet_name or target.stem)
    else:
        payload = csv_bytes(table)
    write_file(target, payload)


def write_file(target: Path, payload: bytes) -> None:
    """Zapis pliku eksportu; błąd systemu plików → ``ExportError``."""
    try:
        target.write_bytes(payload)
    except OSError as exc:
        raise ExportError(
            user_message=tr(
                "corpus.error.save", name=target.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("corpus.error.save.hint"),
        ) from exc
