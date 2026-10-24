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

from collections.abc import Callable, Iterable, Sequence

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QHelpEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPolygonF,
    QResizeEvent,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QMenu, QTextEdit, QToolTip

from transkryptor.document.model import Document
from transkryptor.i18n import tr
from transkryptor.settings import EditorSettings
from transkryptor.ui.fonts import text_font_family
from transkryptor.ui.highlights import (
    REVIEW_LAYER,
    SEARCH_LAYER,
    HighlightLayers,
)
from transkryptor.ui.highlights import background as highlight
from transkryptor.ui.markers import ASIDE_TEXT
from transkryptor.ui.positions import PositionMap, utf16_len
from transkryptor.ui.speaker_gutter import (
    SPEAKER_PROPERTY,
    SpeakerGutter,
    block_speaker,
)

# Półprzezroczyste tło czytelne w jasnym i ciemnym motywie.
REVIEW_HIGHLIGHT = QColor(255, 200, 0, 90)

# Warstwy podświetleń i ``highlight`` są w ``ui/highlights.py``; nazwy
# re-eksportowane dla zgodności importów.
__all__ = ["REVIEW_LAYER", "SEARCH_LAYER", "TranscriptionEditor", "highlight"]

# Tekst transkrypcji czyta się godzinami — większy niż reszta interfejsu.
EDITOR_FONT_SCALE = 1.25

# ``toRawText`` zachowuje znaki specjalne Qt; separatory akapitów, wierszy
# i ramek zamieniamy 1:1 na ``\n`` (jak ``toPlainText``), ale NBSP zostaje.
_RAW_SEPARATORS = str.maketrans(
    {"\u2029": "\n", "\u2028": "\n", "\ufdd0": "\n", "\ufdd1": "\n"}
)


class TranscriptionEditor(QTextEdit):
    """QTextEdit z akcjami notacji transkrypcji."""

    # Ctrl+klik lewym przyciskiem: pozycja tekstu (punkty kodowe) — odtworzenie
    # nagrania od kotwicy czasowej (faza 11).
    ctrl_clicked = Signal(int)
    # Klik w etykietę mówcy: pozycja początku akapitu (punkty kodowe) i punkt
    # ekranu dla menu wyboru mówcy (faza 12).
    speaker_label_clicked = Signal(int, QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(True)
        # Brak autokorekty/automatycznego formatowania: tekst transkrybenta
        # nie może być normalizowany (ACC-01).
        self.setAutoFormatting(QTextEdit.AutoFormattingFlag.AutoNone)
        self.setObjectName("editor")
        self.setPlaceholderText(tr("editor.placeholder"))
        self._base_font = QFont(self.font())
        self._layers = HighlightLayers()
        # Podpowiedzi i menu kontekstowe dla pozycji tekstu (punkty kodowe) —
        # dopisują kontrolery (opis ostrzeżenia, „Ignoruj tutaj”, znaczniki
        # czasu). Podpowiedzi pierwszego dostawcy, który coś zwrócił.
        self.tooltip_providers: list[Callable[[int], str | None]] = []
        self.context_menu_extenders: list[Callable[[QMenu, int], None]] = []
        # Punktowe znaczniki rysowane nad tekstem (ręczne znaczniki czasu).
        self._point_markers: list[QTextCursor] = []
        self._point_marker_color = QColor("#888888")
        # Autouzupełnianie: obsługa klawisza przed edytorem (True = obsłużony)
        # i powiadomienie po wpisaniu znaku.
        self.key_filter: Callable[[QKeyEvent], bool] | None = None
        self.after_key: Callable[[QKeyEvent], None] | None = None
        self._speaker_gutter = SpeakerGutter(self, self._on_speaker_label_clicked)
        self.verticalScrollBar().valueChanged.connect(self._speaker_gutter.update)
        self.document().documentLayout().documentSizeChanged.connect(
            self._speaker_gutter.update
        )
        self.apply_settings(EditorSettings())
        self.document().setDocumentMargin(16)

    def apply_settings(self, settings: EditorSettings) -> None:
        """Ustawia czcionkę tekstu; puste pole = dołączona Charis SIL.

        Czcionka należy do widoku, nie do dokumentu: nie zmienia tekstu ani
        historii cofania (eksport używa tego samego ustawienia).
        """
        font = QFont(self._base_font)
        family = text_font_family(settings.font_family)
        if family:
            font.setFamily(family)
        if settings.font_size_pt:
            font.setPointSizeF(settings.font_size_pt)
        else:
            font.setPointSizeF(self._base_font.pointSizeF() * EDITOR_FONT_SCALE)
        self.setFont(font)
        self.refresh_speakers()

    def text_position_at(self, viewport_point: QPoint) -> int:
        """Pozycja tekstu (punkty kodowe) pod punktem widoku."""
        cursor = self.cursorForPosition(viewport_point)
        return self.position_map().to_py(cursor.position())

    def viewportEvent(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.ToolTip
            and isinstance(event, QHelpEvent)
            and self.tooltip_providers
        ):
            position = self.text_position_at(event.pos())
            text = next(
                (
                    tip
                    for provider in self.tooltip_providers
                    if (tip := provider(position))
                ),
                None,
            )
            if text:
                QToolTip.showText(event.globalPos(), text, self.viewport())
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().viewportEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.key_filter is not None and self.key_filter(event):
            return
        super().keyPressEvent(event)
        if self.after_key is not None:
            self.after_key(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = self.createStandardContextMenu(event.pos())
        position = self.text_position_at(event.pos())
        for extend in self.context_menu_extenders:
            extend(menu, position)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.ctrl_clicked.emit(self.text_position_at(event.position().toPoint()))

    def set_point_markers(self, cursors: list[QTextCursor], color: QColor) -> None:
        """Znaczniki punktowe (kursory bez zaznaczenia) rysowane w tekście.

        Jak podświetlenia należą do widoku: nie są tekstem ani formatem.
        """
        self._point_markers = list(cursors)
        self._point_marker_color = QColor(color)
        self.viewport().update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._speaker_gutter.update_geometry()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        self._speaker_gutter.update()
        if not self._point_markers:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._point_marker_color)
        area = event.rect()
        for cursor in self._point_markers:
            rect = self.cursorRect(cursor)
            if not rect.intersects(area):
                continue
            x, top = float(rect.x()), float(rect.top())
            size = max(4.0, rect.height() / 4)
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(x - size / 2, top),
                        QPointF(x + size / 2, top),
                        QPointF(x, top + size),
                    ]
                )
            )
            painter.drawRect(int(x), int(top), 1, rect.height())
        painter.end()

    def visible_range(self, positions: PositionMap | None = None) -> tuple[int, int]:
        """Zakres tekstu (pozycje Pythona) widoczny w oknie edytora."""
        if positions is None:
            positions = self.position_map()
        # Punkty w marginesie dokumentu dają przypadkowe pozycje — próbkujemy
        # wewnątrz obszaru tekstu.
        inset = int(self.document().documentMargin()) + 1
        area = self.viewport().rect().adjusted(inset, inset, -inset, -inset)
        top = self.cursorForPosition(area.topLeft())
        top.movePosition(QTextCursor.MoveOperation.StartOfLine)
        bottom = self.cursorForPosition(area.bottomRight() + QPoint(1, 1))
        # Koniec ostatniego widocznego wiersza (kursor trafia w jego środek).
        bottom.movePosition(QTextCursor.MoveOperation.EndOfLine)
        first, last = sorted((top.position(), bottom.position()))
        return positions.to_py(first), positions.to_py(last) + 1

    def scroll_to_cursor(self, cursor: QTextCursor) -> None:
        """Przewija widok do początku zakresu bez przesuwania kursora tekstu."""
        start = QTextCursor(cursor)
        start.setPosition(cursor.selectionStart())
        rect = self.cursorRect(start)
        viewport = self.viewport().rect()
        if viewport.top() <= rect.top() and rect.bottom() <= viewport.bottom():
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + rect.top() - viewport.height() // 3)

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

    def insert_formatted(
        self,
        text: str,
        superscript_ranges: tuple[tuple[int, int], ...] = (),
        replace_before: int = 0,
    ) -> None:
        """Wstawia tekst z indeksem górnym jednym krokiem cofania (wstawki).

        Zastępuje zaznaczenie albo — gdy ``replace_before`` > 0 — tyle
        punktów kodowych przed kursorem (dopełnienie autouzupełniania).
        """
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if replace_before and not cursor.hasSelection():
            positions = self.position_map()
            end = positions.to_py(cursor.position())
            start = max(end - replace_before, 0)
            cursor.setPosition(positions.to_qt(start))
            cursor.setPosition(positions.to_qt(end), QTextCursor.MoveMode.KeepAnchor)
        self._replace_tracked(cursor, text, superscript_ranges)
        cursor.endEditBlock()
        cursor.clearSelection()
        self.setTextCursor(cursor)

    def insert_draft(
        self,
        text: str,
        append: bool,
        line_speakers: Sequence[str | None] = (),
    ) -> int:
        """Wstawia szkic ASR jako jeden krok cofania (REQ-14).

        ``append=False`` zastępuje całą treść, ``append=True`` dopisuje szkic
        w nowym akapicie na końcu. Szkic dostaje zwykły format znaków, nawet
        gdy tekst kończy się indeksem górnym. ``line_speakers`` to mówcy
        kolejnych wersów szkicu (podział na mówców). Zwraca pozycję początku
        szkicu (w punktach kodowych).
        """
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        if append:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if not self.document().isEmpty():
                # Nowy akapit bez mówcy poprzedniego.
                cursor.insertBlock(QTextBlockFormat())
        else:
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.removeSelectedText()
            cursor.setBlockFormat(QTextBlockFormat())
        start = cursor.position()
        cursor.insertText(text, QTextCharFormat())
        block = self.document().findBlock(start)
        for key in line_speakers:
            if not block.isValid():
                break
            if key is not None:
                _set_block_speaker(block, key)
            block = block.next()
        cursor.endEditBlock()
        cursor.setPosition(start)
        self.setTextCursor(cursor)
        if line_speakers:
            self.refresh_speakers()
        return self.position_map().to_py(start)

    def load_content(
        self,
        text: str,
        superscript_ranges: Iterable[tuple[int, int]],
        paragraph_speakers: dict[int, str] | None = None,
    ) -> None:
        """Wczytuje tekst z indeksem górnym i mówcami (projekt, import DOCX).

        Wczytanie zaczyna nową historię cofania — stan sprzed otwarcia
        należy do innego dokumentu.
        """
        self.setPlainText(text)
        # ``setPlainText`` tworzy blok z każdej linii: indeks bloku = akapit.
        for index, key in (paragraph_speakers or {}).items():
            block = self.document().findBlockByNumber(index)
            if block.isValid():
                _set_block_speaker(block, key)
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
        self.refresh_speakers()

    # --- mówcy akapitów (faza 12) -----------------------------------------

    def selected_blocks(self, cursor: QTextCursor | None = None) -> list[QTextBlock]:
        """Akapity objęte zaznaczeniem (albo akapit kursora)."""
        if cursor is None:
            cursor = self.textCursor()
        document = self.document()
        block = document.findBlock(cursor.selectionStart())
        last = document.findBlock(cursor.selectionEnd())
        blocks = [block]
        while block != last and block.isValid():
            block = block.next()
            blocks.append(block)
        return [b for b in blocks if b.isValid()]

    def set_paragraph_speaker(
        self, key: str | None, blocks: list[QTextBlock] | None = None
    ) -> None:
        """Przypisuje mówcę akapitom zaznaczenia jednym krokiem cofania.

        Gdy wszystkie akapity mają już tego mówcę, przypisanie jest zdejmowane
        (przełącznik). ``key=None`` usuwa mówcę.
        """
        if blocks is None:
            blocks = self.selected_blocks()
        if not blocks:
            return
        if key is not None and all(block_speaker(b) == key for b in blocks):
            key = None
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        for block in blocks:
            _set_block_speaker(block, key)
        edit.endEditBlock()
        self.refresh_speakers()

    def assign_paragraph_speakers(
        self, start: int, keys: Sequence[str | None], text: str | None = None
    ) -> None:
        """Ustawia mówców kolejnych akapitów od akapitu zawierającego ``start``.

        Bez przełączania (jak w :meth:`set_paragraph_speaker`): ``keys[i]`` to
        mówca i-tego akapitu, None usuwa przypisanie. Wołane wewnątrz bloku
        edycji, więc nie tworzy osobnego kroku cofania.
        """
        if text is None:
            text = self.plain_text()
        positions = PositionMap(text)
        paragraph_start = text.rfind("\n", 0, start) + 1
        for key in keys:
            block = self.document().findBlock(positions.to_qt(paragraph_start))
            if block.isValid() and block_speaker(block) != key:
                _set_block_speaker(block, key)
            next_start = text.find("\n", paragraph_start)
            if next_start < 0:
                break
            paragraph_start = next_start + 1
        self.refresh_speakers()

    def remap_speakers(self, mapping: dict[str, str | None]) -> None:
        """Zmienia klucze mówców w akapitach (None usuwa przypisanie)."""
        blocks = [
            block
            for block in self._blocks()
            if (key := block_speaker(block)) is not None and key in mapping
        ]
        if not blocks:
            return
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        for block in blocks:
            _set_block_speaker(block, mapping[block_speaker(block) or ""])
        edit.endEditBlock()
        self.refresh_speakers()

    def paragraph_speakers(self, text: str | None = None) -> dict[int, str]:
        """Indeks akapitu (w ``plain_text``) → klucz mówcy.

        Akapity tekstu rozdziela ``\n``; blok Qt może zawierać łamanie wiersza
        (``Shift+Enter``), więc indeks liczy się po znakach nowej linii.
        """
        assigned = [
            (block.position(), key)
            for block in self._blocks()
            if (key := block_speaker(block)) is not None
        ]
        if not assigned:
            return {}
        if text is None:
            text = self.plain_text()
        positions = PositionMap(text)
        return {
            text.count("\n", 0, positions.to_py(position)): key
            for position, key in assigned
        }

    def speaker_at(self, position: int) -> str | None:
        """Mówca akapitu zawierającego pozycję (punkty kodowe)."""
        qt_position = self.position_map().to_qt(position)
        return block_speaker(self.document().findBlock(qt_position))

    def refresh_speakers(self) -> None:
        """Dopasowuje kolumnę etykiet do mówców obecnych w tekście."""
        keys = sorted(
            {key for block in self._blocks() if (key := block_speaker(block))}
        )
        self._speaker_gutter.set_keys(keys)
        self._speaker_gutter.update()

    @property
    def speaker_gutter(self) -> SpeakerGutter:
        return self._speaker_gutter

    def _blocks(self) -> list[QTextBlock]:
        blocks: list[QTextBlock] = []
        block = self.document().begin()
        while block.isValid():
            blocks.append(block)
            block = block.next()
        return blocks

    def _on_speaker_label_clicked(self, block: QTextBlock, global_pos: QPoint) -> None:
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.speaker_label_clicked.emit(
            self.position_map().to_py(block.position()), global_pos
        )

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
        self._layers.set(name, selections)
        self.setExtraSelections(self._layers.ordered())

    def highlight_layer(self, name: str) -> list[QTextEdit.ExtraSelection]:
        """Bieżące podświetlenia jednej warstwy."""
        return self._layers.get(name)

    def sync_to_document(self, doc: Document) -> bool:
        """Przepisuje tekst, indeks górny i mówców akapitów z edytora do dokumentu.

        Zwraca True, gdy dokument się zmienił (rewizja rośnie tylko wtedy).
        """
        text = self.plain_text()
        ranges = _collect_superscript_ranges(self, PositionMap(text))
        return doc.replace_all(text, ranges, self.paragraph_speakers(text))


def _set_block_speaker(block: QTextBlock, key: str | None) -> None:
    """Ustawia albo usuwa mówcę bloku (edycja dokumentu, z historią cofania)."""
    block_format = block.blockFormat()
    if key is None:
        block_format.clearProperty(SPEAKER_PROPERTY)
    else:
        block_format.setProperty(SPEAKER_PROPERTY, key)
    QTextCursor(block).setBlockFormat(block_format)


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
