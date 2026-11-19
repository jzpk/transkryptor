"""Wspólne elementy okien wniosków z poprawek (projekt i korpus, zgłoszenie #74).

Zapis zmiany reguły (``^n`` - indeks górny) pokazywany znakami indeksu
górnego, nazwy miejsc w słowie, kontekst miejsca w tekście i wypełnianie
prostych tabel.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from transkryptor.export.superscript import UNICODE_SUPERSCRIPT
from transkryptor.i18n import tr
from transkryptor.notation.learning import Change
from transkryptor.ui.corpus_table import count_item

CONTEXT_CHARS = 32


def shown(template: str) -> str:
    """Zamiennik reguły (``e^n``, ``\\^``) do pokazania: ``eⁿ``."""
    result: list[str] = []
    index = 0
    while index < len(template):
        char = template[index]
        if char == "\\" and index + 1 < len(template):
            result.append(template[index + 1])
            index += 2
            continue
        if char == "^" and index + 1 < len(template):
            following = template[index + 1]
            result.append(UNICODE_SUPERSCRIPT.get(following, f"^{following}"))
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def change_text(change: Change) -> str:
    """Zmiana do pokazania: ``ę → eⁿ``."""
    return f"{change.before} → {shown(change.after)}"


def place_name(place: str) -> str:
    """Miejsce zmiany w słowie: początek, koniec, środek."""
    return tr(f"insights.place.{place}")


def context(text: str, position: int, radius: int = CONTEXT_CHARS) -> str:
    """Fragment tekstu wokół ``position`` (w jednym wierszu, z wielokropkami)."""
    start, end = max(0, position - radius), min(len(text), position + radius)
    piece = " ".join(text[start:end].split())
    return f"{'…' if start else ''}{piece}{'…' if end < len(text) else ''}"


def fill_table(table: QTableWidget, rows: Sequence[Sequence[object]]) -> None:
    """Wiersze tabeli; liczby jako liczby (sortowanie po wartości)."""
    table.setSortingEnabled(False)
    table.clearContents()
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = (
                count_item(value)
                if isinstance(value, int) and not isinstance(value, bool)
                else QTableWidgetItem(str(value))
            )
            table.setItem(row, column, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)


__all__ = ["change_text", "context", "fill_table", "place_name", "shown"]
