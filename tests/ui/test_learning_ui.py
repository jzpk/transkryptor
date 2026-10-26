"""Propozycje reguł z powtarzalnych poprawek szkicu ASR w oknie."""

import pytest
from PySide6.QtGui import QTextCursor

from transkryptor.asr.engine import SegmentResult, TranscriptionResult, WordResult
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog

WORDS = ("mleko", "chleb", "ser", "dom")


def draft() -> TranscriptionResult:
    words = tuple(
        WordResult(i * 0.5, i * 0.5 + 0.5, f" {word}", 0.9)
        for i, word in enumerate(WORDS)
    )
    text = "".join(word.text for word in words)
    segment = SegmentResult(0.0, len(WORDS) * 0.5, text, 0.9, words)
    return TranscriptionResult(text=text.strip(), language="pl", segments=(segment,))


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    win = add_window(MainWindow())
    win.show()
    assert win.review.insert_draft(draft().text, draft().segments)
    return win


def correct(window: MainWindow, word: str, old: str, new: str) -> None:
    """Zamienia w słowie szkicu pierwsze ``old`` na ``new`` (jak transkrybent)."""
    text = window.editor.plain_text()
    position = text.index(word) + word.index(old)
    cursor = QTextCursor(window.editor.document())
    cursor.setPosition(position)
    cursor.setPosition(position + len(old), QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText(new)


def test_repeated_correction_suggests_a_rule(window, monkeypatch) -> None:
    correct(window, "mleko", "e", "y")
    correct(window, "chleb", "e", "y")
    window.learning.refresh()
    assert window.learning.button.isHidden()

    correct(window, "ser", "e", "y")
    window.learning.refresh()
    assert not window.learning.button.isHidden()
    assert window.learning.button.text() == "Propozycja reguły: e → y (3×)"
    candidate = window.learning.candidate
    assert candidate is not None
    assert candidate.rule.pattern == "(?<=[ls])e(?=[bkr])"

    opened: list[SettingsDialog] = []

    def accept(dialog: SettingsDialog) -> int:
        opened.append(dialog)
        return int(SettingsDialog.DialogCode.Accepted)

    monkeypatch.setattr(SettingsDialog, "exec", accept)
    window.learning.button.click()
    (dialog,) = opened
    assert dialog.tabs.currentWidget() is dialog.rules_editor
    (rule,) = window.rules_store.user_rules
    assert (rule.code, rule.replacement) == ("USR-1", "y")
    assert rule.example == "mleko"
    # Reguła już istnieje - propozycja znika.
    assert window.learning.button.isHidden()


def test_dismissed_change_is_not_suggested_again(window) -> None:
    for word in ("mleko", "chleb", "ser"):
        correct(window, word, "e", "y")
    window.learning.refresh()
    assert window.learning.candidate is not None
    window.learning.dismiss_action.trigger()
    assert window.learning.candidate is None
    assert window.learning.button.isHidden()


def test_superscript_in_correction_goes_to_replacement(window) -> None:
    for word in ("mleko", "chleb", "ser"):
        correct(window, word, "e", "en")
        text = window.editor.plain_text()
        position = text.index(word.replace("e", "en", 1)) + word.index("e") + 1
        cursor = QTextCursor(window.editor.document())
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        window.editor.setTextCursor(cursor)
        window.editor.toggle_superscript()
    window.learning.refresh()
    candidate = window.learning.candidate
    assert candidate is not None
    assert candidate.rule.replacement == "e^n"
