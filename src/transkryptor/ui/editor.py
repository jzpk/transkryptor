"""Edytor rich text ręcznej transkrypcji.

Edytor jest źródłem prawdy dla tekstu i formatowania w fazie 02: natywny
stos undo/redo QTextDocument obsługuje cofanie (NFR-04), a model ``Document``
jest synchronizowaną projekcją używaną przez walidator i metadane.

Publiczne API edytora przyjmuje i zwraca pozycje Pythona (punkty kodowe);
przeliczenie na pozycje Qt (UTF-16) odbywa się tutaj (``ui/positions.py``).

UI nie zawiera reguł lingwistycznych — jedynie wstawia markery i formatowanie
zdefiniowane w ``ui/markers.py`` oraz prezentuje wyniki ``notation``.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

from transkryptor.document.model import Document
from transkryptor.i18n import tr
from transkryptor.settings import EditorSettings
from transkryptor.ui.markers import ASIDE_TEXT
from transkryptor.ui.positions import PositionMap, utf16_len

# Półprzezroczyste tło czytelne w jasnym i ciemnym motywie.
REVIEW_HIGHLIGHT = QColor(255, 200, 0, 90)

# Warstwy ``ExtraSelections``: przegląd ASR pod spodem, wyszukiwanie na wierzchu.
REVIEW_LAYER = "review"
SEARCH_LAYER = "search"
_LAYER_ORDER = (REVIEW_LAYER, SEARCH_LAYER)

# Tekst transkrypcji czyta się godzinami — większy niż reszta interfejsu.
EDITOR_FONT_SCALE = 1.25

# ``toRawText`` zachowuje znaki specjalne Qt; separatory akapitów, wierszy
# i ramek zamieniamy 1:1 na ``\n`` (jak ``toPlainText``), ale NBSP zostaje.
_RAW_SEPARATORS = str.maketrans(
    {"\u2029": "\n", "\u2028": "\n", "\ufdd0": "\n", "\ufdd1": "\n"}
)


class TranscriptionEditor(QTextEdit):
    """QTextEdit z akcjami notacji transkrypcji."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(True)
        # Brak autokorekty/automatycznego formatowania: tekst transkrybenta
        # nie może być normalizowany (ACC-01).
        self.setAutoFormatting(QTextEdit.AutoFormattingFlag.AutoNone)
        self.setObjectName("editor")
        self.setPlaceholderText(tr("editor.placeholder"))
        self._base_font = QFont(self.font())
        self._layers: dict[str, list[QTextEdit.ExtraSelection]] = {}
        self.apply_settings(EditorSettings())
        self.document().setDocumentMargin(16)

    def apply_settings(self, settings: EditorSettings) -> None:
        """Ustawia czcionkę tekstu; puste pola oznaczają czcionkę domyślną.

        Czcionka należy do widoku, nie do dokumentu: nie zmienia tekstu,
        historii cofania ani eksportu DOCX.
        """
        font = QFont(self._base_font)
        if settings.font_family:
            font.setFamily(settings.font_family)
        if settings.font_size_pt:
            font.setPointSizeF(settings.font_size_pt)
        else:
            font.setPointSizeF(self._base_font.pointSizeF() * EDITOR_FONT_SCALE)
        self.setFont(font)

    def plain_text(self) -> str:
        """Tekst edytora bez normalizacji (NBSP zostaje, ACC-01).

        ``toPlainText()`` zamienia niełamliwą spację na zwykłą, dlatego tekst
        dla modelu, walidacji i wyszukiwania pochodzi stąd.
        """
        return self.document().toRawText().translate(_RAW_SEPARATORS)

    def position_map(self) -> PositionMap:
        """Przeliczenie pozycji dla bieżącego tekstu edytora."""
        return PositionMap(self.plain_text())

    def toggle_superscript(self) -> None:
        """Przełącza indeks górny na zaznaczeniu (lub w punkcie kursora)."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        is_superscript = (
            cursor.charFormat().verticalAlignment()
            == QTextCharFormat.VerticalAlignment.AlignSuperScript
        )
        new_format = QTextCharFormat()
        new_format.setVerticalAlignment(
            QTextCharFormat.VerticalAlignment.AlignNormal
            if is_superscript
            else QTextCharFormat.VerticalAlignment.AlignSuperScript
        )
        cursor.mergeCharFormat(new_format)

    def insert_marker(self, text: str) -> None:
        """Wstawia marker notacji w miejscu kursora.

        Dla dopisku ``[...]`` kursor ląduje między nawiasami, aby można było
        od razu wpisać treść dopisku.
        """
        cursor = self.textCursor()
        cursor.insertText(text)
        if text == ASIDE_TEXT:
            cursor.setPosition(cursor.position() - 2)
            self.setTextCursor(cursor)

    def insert_draft(self, text: str, append: bool) -> int:
        """Wstawia szkic ASR jako jeden krok cofania (REQ-14).

        ``append=False`` zastępuje całą treść, ``append=True`` dopisuje szkic
        w nowym akapicie na końcu. Szkic dostaje zwykły format znaków, nawet
        gdy tekst kończy się indeksem górnym. Zwraca pozycję początku szkicu
        (w punktach kodowych).
        """
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        if append:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if not self.document().isEmpty():
                cursor.insertBlock()
        else:
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.removeSelectedText()
        start = cursor.position()
        cursor.insertText(text, QTextCharFormat())
        cursor.endEditBlock()
        cursor.setPosition(start)
        self.setTextCursor(cursor)
        return self.position_map().to_py(start)

    def load_content(
        self, text: str, superscript_ranges: Iterable[tuple[int, int]]
    ) -> None:
        """Wczytuje tekst z zakresami indeksu górnego (projekt, import DOCX).

        Wczytanie zaczyna nową historię cofania — stan sprzed otwarcia
        należy do innego dokumentu.
        """
        self.setPlainText(text)
        superscript_format = QTextCharFormat()
        superscript_format.setVerticalAlignment(
            QTextCharFormat.VerticalAlignment.AlignSuperScript
        )
        positions = PositionMap(text)
        for start, end in superscript_ranges:
            self.track_range(start, end, positions).mergeCharFormat(superscript_format)
        self.document().clearUndoRedoStacks()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)

    def track_range(
        self, start: int, end: int, positions: PositionMap | None = None
    ) -> QTextCursor:
        """Zwraca kursor obejmujący zakres i przesuwający się razem z edycją.

        ``start`` i ``end`` to pozycje Pythona w tekście edytora. Przy wielu
        wywołaniach na niezmienionym tekście warto przekazać jedną mapę
        ``positions`` (:meth:`position_map`).
        """
        if positions is None:
            positions = self.position_map()
        return self._qt_cursor(positions.to_qt(start), positions.to_qt(end))

    def selection_range(
        self, cursor: QTextCursor, positions: PositionMap | None = None
    ) -> tuple[int, int]:
        """Zaznaczenie kursora jako zakres pozycji Pythona."""
        if positions is None:
            positions = self.position_map()
        return (
            positions.to_py(cursor.selectionStart()),
            positions.to_py(cursor.selectionEnd()),
        )

    def _qt_cursor(self, start: int, end: int) -> QTextCursor:
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def apply_tracked_replacements(
        self,
        replacements: list[tuple[QTextCursor, str, tuple[tuple[int, int], ...]]],
    ) -> None:
        """Stosuje zamiany na śledzonych zakresach jednym krokiem cofania.

        Zakresy ``superscript_ranges`` (względem początku zamiany) otrzymują
        format indeksu górnego, a standardowe cofanie (NFR-04) przywraca stan
        sprzed zastosowania (ACC-12, ACC-15). Po zamianie każdy kursor obejmuje wstawiony tekst, więc nadaje się
        do podświetlenia i nawigacji podczas przeglądu (REQ-16).
        """
        if not replacements:
            return
        block_cursor = QTextCursor(self.document())
        block_cursor.beginEditBlock()
        for cursor, replacement, superscript_ranges in replacements:
            self._replace_tracked(cursor, replacement, superscript_ranges)
        block_cursor.endEditBlock()

    def _replace_tracked(
        self,
        cursor: QTextCursor,
        replacement: str,
        superscript_ranges: tuple[tuple[int, int], ...],
    ) -> None:
        """Zastępuje zaznaczenie kursora i zaznacza nim wstawiony tekst."""
        start = cursor.selectionStart()
        # Zamiennik nie dziedziczy indeksu górnego po sąsiednim znaku — format
        # nadają wyłącznie ``superscript_ranges``.
        plain_format = cursor.charFormat()
        plain_format.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        cursor.insertText(replacement, plain_format)
        # Zakresy są względne w punktach kodowych zamiennika.
        positions = PositionMap(replacement)
        for rel_start, rel_end in superscript_ranges:
            format_cursor = self._qt_cursor(
                start + positions.to_qt(rel_start), start + positions.to_qt(rel_end)
            )
            superscript_format = QTextCharFormat()
            superscript_format.setVerticalAlignment(
                QTextCharFormat.VerticalAlignment.AlignSuperScript
            )
            format_cursor.mergeCharFormat(superscript_format)
        cursor.setPosition(start)
        cursor.setPosition(
            start + utf16_len(replacement), QTextCursor.MoveMode.KeepAnchor
        )

    def set_review_highlights(self, cursors: list[QTextCursor]) -> None:
        """Podświetla zakresy do przeglądu (REQ-16).

        ``ExtraSelections`` należą do widoku, nie do dokumentu: nie są
        formatem znaków, nie trafiają do ``Document`` ani do eksportu DOCX.
        """
        self.set_highlight_layer(
            REVIEW_LAYER, [highlight(cursor, REVIEW_HIGHLIGHT) for cursor in cursors]
        )

    def clear_review_highlights(self) -> None:
        self.set_highlight_layer(REVIEW_LAYER, [])

    def set_highlight_layer(
        self, name: str, selections: list[QTextEdit.ExtraSelection]
    ) -> None:
        """Zastępuje podświetlenia jednej warstwy, zachowując pozostałe."""
        self._layers[name] = list(selections)
        self.setExtraSelections(
            [
                selection
                for layer in _LAYER_ORDER
                for selection in self._layers.get(layer, [])
            ]
        )

    def sync_to_document(self, doc: Document) -> bool:
        """Przepisuje tekst i zakresy indeksu górnego z edytora do dokumentu.

        Zwraca True, gdy dokument się zmienił (rewizja rośnie tylko wtedy).
        """
        text = self.plain_text()
        ranges = _collect_superscript_ranges(self, PositionMap(text))
        return doc.replace_all(text, ranges)


def highlight(cursor: QTextCursor, color: QColor) -> QTextEdit.ExtraSelection:
    """Podświetlenie zakresu kursora tłem (tylko widok, nie format znaków)."""
    selection = QTextEdit.ExtraSelection()
    selection.cursor = cursor
    selection.format.setBackground(color)
    return selection


def _collect_superscript_ranges(
    editor: QTextEdit, positions: PositionMap
) -> list[tuple[int, int]]:
    """Skanuje dokument edytora i zbiera półotwarte zakresy indeksu górnego.

    Zwraca pozycje Pythona; sąsiednie fragmenty scala ``Document``.
    """
    ranges: list[tuple[int, int]] = []
    document = editor.document()
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and (
                fragment.charFormat().verticalAlignment()
                == QTextCharFormat.VerticalAlignment.AlignSuperScript
            ):
                start = fragment.position()
                ranges.append(
                    (
                        positions.to_py(start),
                        positions.to_py(start + fragment.length()),
                    )
                )
            iterator += 1
        block = block.next()
    ranges.sort()
    return ranges
