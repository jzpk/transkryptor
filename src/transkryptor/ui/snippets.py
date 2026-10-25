"""Wstawki użytkownika i autouzupełnianie w edytorze (propozycja 21).

Wstawka to tekst w składni ``^x`` z fazy 07 (``be^ndzie`` → ``n`` w indeksie
górnym), wstawiany skrótem albo z menu „Wstawki” na pasku narzędzi jednym
krokiem cofania. Opcjonalne autouzupełnianie (domyślnie wyłączone)
podpowiada wstawki i słowa użyte już w dokumencie po wpisaniu kilku liter.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QStringListModel, Qt, QTimer
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QCompleter, QMenu, QWidget

from transkryptor.document.search import (
    ParsedReplacement,
    SearchError,
    parse_replacement,
)
from transkryptor.i18n import tr
from transkryptor.settings import Snippet
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.shortcuts import SNIPPET_PREFIX, tooltip_with_shortcut

# Podpowiadane skróty kolejnych wstawek (nowa wstawka dostaje pierwszy wolny).
SUGGESTED_SNIPPET_SHORTCUTS = tuple(f"Alt+{n}" for n in range(1, 10))
MIN_PREFIX = 2
MIN_WORD_LENGTH = 4
MAX_DOCUMENT_WORDS = 5000
WORDS_REFRESH_MS = 1000
_WORD_RE = re.compile(r"[^\W\d_]+")
_PREFIX_RE = re.compile(r"[^\W\d_]+$")
_MODIFIER_LETTERS = str.maketrans("mnu", "ᵐⁿᵘ")


def snippet_id(index: int) -> str:
    return f"{SNIPPET_PREFIX}{index + 1}"


def parse_snippet(text: str) -> ParsedReplacement | None:
    """Tekst wstawki i zakresy indeksu górnego; None przy błędnej składni."""
    try:
        return parse_replacement(text)
    except SearchError:
        return None


def snippet_label(parsed: ParsedReplacement) -> str:
    """Etykieta menu: indeks górny ``m``/``n``/``u`` jako znaki modyfikujące."""
    chars = list(parsed.text)
    for start, end in parsed.superscript_ranges:
        for i in range(start, end):
            chars[i] = chars[i].translate(_MODIFIER_LETTERS)
    return "".join(chars)


@dataclass(frozen=True)
class _Completion:
    text: str
    superscript_ranges: tuple[tuple[int, int], ...] = ()


class SnippetController(QObject):
    """Akcje wstawek (skróty, menu) i autouzupełnianie edytora."""

    def __init__(
        self,
        owner: QWidget,
        editor: TranscriptionEditor,
        menu: QMenu,
        open_settings: Callable[[], None],
    ) -> None:
        super().__init__(owner)
        self._owner = owner
        self.editor = editor
        self.menu = menu
        self._open_settings = open_settings
        self.actions: list[QAction] = []
        self._snippets: tuple[Snippet, ...] = ()
        self._locked = False

        self.autocomplete_enabled = False
        self._model = QStringListModel(self)
        self.completer = QCompleter(self._model, self)
        self.completer.setWidget(editor)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.activated.connect(self.insert_completion)
        self._completions: dict[str, _Completion] = {}
        self._words_timer = QTimer(self)
        self._words_timer.setSingleShot(True)
        self._words_timer.setInterval(WORDS_REFRESH_MS)
        self._words_timer.timeout.connect(self.refresh_completions)
        editor.document().contentsChanged.connect(self._on_text_changed)
        editor.key_filter = self._key_filter
        editor.after_key = self._after_key
        self.set_snippets(())

    # --- wstawki --------------------------------------------------------------

    @property
    def snippets(self) -> tuple[Snippet, ...]:
        return self._snippets

    def set_snippets(self, snippets: tuple[Snippet, ...]) -> None:
        """Odtwarza akcje i menu wstawek (po zmianie ustawień, bez restartu)."""
        for action in self.actions:
            self._owner.removeAction(action)
            action.deleteLater()
        self.actions = []
        self._snippets = tuple(snippets)
        self.menu.clear()
        for index, snippet in enumerate(self._snippets):
            parsed = parse_snippet(snippet.text)
            if parsed is None or not parsed.text:
                continue
            action = QAction(snippet_label(parsed), self._owner)
            action.setObjectName(snippet_id(index))
            if snippet.shortcut:
                action.setShortcut(QKeySequence(snippet.shortcut))
                action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.setToolTip(
                tooltip_with_shortcut(
                    tr("snippets.insert", text=snippet_label(parsed)),
                    *([snippet.shortcut] if snippet.shortcut else []),
                )
            )
            action.triggered.connect(
                lambda _checked=False, chosen=parsed: self.insert(chosen)
            )
            action.setEnabled(not self._locked)
            self._owner.addAction(action)
            self.menu.addAction(action)
            self.actions.append(action)
        if not self.actions:
            placeholder = self.menu.addAction(tr("snippets.empty"))
            placeholder.setEnabled(False)
        self.menu.addSeparator()
        manage = self.menu.addAction(tr("snippets.manage"))
        manage.triggered.connect(lambda _checked=False: self._open_settings())
        self.refresh_completions()

    def insert(self, parsed: ParsedReplacement) -> None:
        """ACC-44: wstawka w miejscu kursora - jeden krok cofania."""
        if self._locked:
            return
        self.editor.insert_formatted(parsed.text, parsed.superscript_ranges)
        self.editor.setFocus()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        for action in self.actions:
            action.setEnabled(not locked)
        if locked:
            self._popup().hide()

    # --- autouzupełnianie ------------------------------------------------------

    def set_autocomplete(self, enabled: bool) -> None:
        self.autocomplete_enabled = enabled
        if not enabled:
            self._popup().hide()
        self.refresh_completions()

    def refresh_completions(self) -> None:
        """Model podpowiedzi: wstawki, potem słowa dokumentu (bez powtórzeń)."""
        completions: dict[str, _Completion] = {}
        for snippet in self._snippets:
            parsed = parse_snippet(snippet.text)
            if parsed is not None and parsed.text:
                completions.setdefault(
                    parsed.text, _Completion(parsed.text, parsed.superscript_ranges)
                )
        if self.autocomplete_enabled:
            text = self.editor.plain_text()
            for match in _WORD_RE.finditer(text):
                word = match.group(0)
                if len(word) >= MIN_WORD_LENGTH and word not in completions:
                    completions[word] = _Completion(word)
                    if len(completions) >= MAX_DOCUMENT_WORDS:
                        break
        self._completions = completions
        self._model.setStringList(sorted(completions, key=str.lower))

    def current_prefix(self) -> str:
        """Litery słowa tuż przed kursorem."""
        cursor = self.editor.textCursor()
        block = cursor.block().text()[: cursor.positionInBlock()]
        match = _PREFIX_RE.search(block)
        return match.group(0) if match else ""

    def complete_now(self) -> bool:
        """Pokazuje podpowiedzi dla bieżącego prefiksu; True, gdy są."""
        prefix = self.current_prefix()
        popup = self._popup()
        if not self.autocomplete_enabled or self._locked or len(prefix) < MIN_PREFIX:
            popup.hide()
            return False
        self.completer.setCompletionPrefix(prefix)
        count = self.completer.completionCount()
        only = self.completer.currentCompletion()
        if count == 0 or (
            count == 1
            and only == prefix
            and not self._completions[only].superscript_ranges
        ):
            popup.hide()
            return False
        popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        rect = self.editor.cursorRect()
        rect.setWidth(
            popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width()
        )
        self.completer.complete(rect)
        return True

    def insert_completion(self, text: str) -> None:
        """Zastępuje wpisany prefiks wybraną podpowiedzią (jeden krok cofania)."""
        completion = self._completions.get(text)
        if completion is None:
            return
        prefix = self.current_prefix()
        self.editor.insert_formatted(
            completion.text, completion.superscript_ranges, replace_before=len(prefix)
        )
        self._popup().hide()

    def _popup(self) -> QAbstractItemView:
        popup = self.completer.popup()
        assert popup is not None  # QCompleter tworzy popup w konstruktorze
        return popup

    def _key_filter(self, event: QKeyEvent) -> bool:
        """Klawisze wyboru podpowiedzi obsługuje ``QCompleter``, nie edytor."""
        if not self._popup().isVisible():
            return False
        if event.key() in (
            Qt.Key.Key_Enter,
            Qt.Key.Key_Return,
            Qt.Key.Key_Escape,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
        ):
            event.ignore()
            return True
        return False

    def _after_key(self, event: QKeyEvent) -> None:
        if not self.autocomplete_enabled:
            return
        if event.key() == Qt.Key.Key_Backspace or event.text().isalpha():
            self.complete_now()
        else:
            self._popup().hide()

    def _on_text_changed(self) -> None:
        if self.autocomplete_enabled:
            self._words_timer.start()
