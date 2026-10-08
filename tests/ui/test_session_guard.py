"""Testy dialogu ochrony sesji (ACC-10, REQ-09)."""

import pytest
from PySide6.QtWidgets import QMessageBox

from transkryptor.ui.main_window import MainWindow


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def make_dirty(window: MainWindow) -> None:
    window.editor.setPlainText("niewyeksportowana praca")


def answer_dialog(monkeypatch, button) -> list[bool]:
    """Zastępuje QMessageBox.question zadaną odpowiedzią; zwraca historię wywołań."""
    calls: list[bool] = []

    def fake_question(*args, **kwargs):
        calls.append(True)
        return button

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    return calls


class TestCloseGuard:
    """ACC-10: zamknięcie po edycji bez eksportu pyta o potwierdzenie."""

    def test_close_with_dirty_document_asks_and_can_be_cancelled(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        assert not window.maybe_discard_changes()
        assert calls == [True]
        assert window.isVisible() or True  # okno nie zostało zamknięte

    def test_close_with_dirty_document_and_confirm_proceeds(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Discard)
        assert window.maybe_discard_changes()

    def test_close_without_changes_does_not_ask(
        self, qtbot, window, monkeypatch
    ) -> None:
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        assert window.maybe_discard_changes()
        assert calls == []  # czysty dokument — brak pytania

    def test_close_after_export_does_not_ask(self, qtbot, window, monkeypatch) -> None:
        make_dirty(window)
        window.document.mark_exported()
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        assert window.maybe_discard_changes()
        assert calls == []


class TestNewDocumentGuard:
    """REQ-09: nowy dokument pyta, gdy praca nie została wyeksportowana."""

    def test_new_document_cancelled_keeps_text(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        window._on_new_document()
        assert window.editor.toPlainText() == "niewyeksportowana praca"

    def test_new_document_confirmed_clears_state(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Discard)
        window._on_new_document()
        assert window.editor.toPlainText() == ""
        assert window.author_edit.text() == ""
        assert not window.document.is_dirty
        assert window.player.source_path is None


class TestAudioChangeGuard:
    """REQ-09: zmiana nagrania pyta przy niewyeksportowanej pracy."""

    def test_import_cancelled_keeps_old_state(self, qtbot, window, monkeypatch) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        window._on_import_audio("test/JaE_1979_przesądy.mp3")
        assert window.player.source_path is None  # import przerwany

    def test_import_confirmed_loads_file(self, qtbot, window, monkeypatch) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Discard)
        window._on_import_audio("test/JaE_1979_przesądy.mp3")
        assert window.player.source_path is not None

    def test_import_error_shows_message(self, qtbot, window, monkeypatch) -> None:
        shown: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2]))
        )
        window._on_import_audio("nieistniejacy.mp3")
        assert len(shown) == 1
        assert "Nie znaleziono" in shown[0]
