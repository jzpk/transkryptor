"""Konfiguracja testów UI: Qt działa w trybie offscreen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402 — import po ustawieniu platformy Qt
from PySide6.QtWidgets import QMessageBox  # noqa: E402


@pytest.fixture
def add_window(qtbot):
    """Rejestruje główne okno w qtbot tak, aby teardown nigdy się nie blokował.

    ``pytest-qt`` zamyka widżety w hooku ``pytest_runtest_teardown``, który
    wykonuje się przed finalizatorami fikstur. Gdy dokument ma wtedy
    niewyeksportowane zmiany, ``MainWindow.closeEvent`` otwiera modalny dialog
    ochrony sesji (ACC-10), a w trybie offscreen nie ma kto na niego
    odpowiedzieć — test wisi w nieskończoność. ``before_close_func`` oznacza
    rewizję jako wyeksportowaną i zapisaną bezpośrednio przed zamknięciem, więc dialog nie
    jest potrzebny; samo ostrzeżenie jest testowane jawnie w
    ``test_session_guard.py``.
    """

    def register(window):
        def before_close(win) -> None:
            win.document.mark_exported()
            win.document.mark_saved()

        qtbot.addWidget(window, before_close_func=before_close)
        return window

    return register


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """Żaden modalny dialog nie może zatrzymać testu w trybie offscreen.

    Qt offscreen nie ma kto obsłużyć ``QMessageBox`` — niezaplanowany dialog
    zawiesiłby przebieg testów na zawsze. Domyślne odpowiedzi są zachowawcze
    (pytanie: „nie”), a testy sprawdzające konkretny dialog nadpisują te
    atrapy własnym ``monkeypatch`` i zachowują pełną kontrolę.

    Zwraca listę wywołań ``(rodzaj, tytuł, treść)`` do inspekcji w teście.
    """
    calls: list[tuple[str, str, str]] = []

    def record(kind, default):
        def fake(_parent=None, title="", text="", *args, **kwargs):
            calls.append((kind, title, text))
            return default

        return staticmethod(fake)

    monkeypatch.setattr(
        QMessageBox, "question", record("question", QMessageBox.StandardButton.No)
    )
    monkeypatch.setattr(
        QMessageBox, "warning", record("warning", QMessageBox.StandardButton.Ok)
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        record("information", QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox, "critical", record("critical", QMessageBox.StandardButton.Ok)
    )

    def fake_exec(box):
        # Dialog z własnymi przyciskami: bez kliknięcia ``clickedButton()``
        # zwraca None, czyli zachowawcze „anuluj”.
        calls.append(("exec", box.windowTitle(), box.text()))
        return int(QMessageBox.StandardButton.Cancel)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return calls


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Ustawienia z pliku INI w katalogu tymczasowym, nie z konta dewelopera.

    ``MainWindow()`` bez jawnego magazynu czyta ``default_qsettings()``; tu
    każdy test dostaje własny, pusty plik. Zwraca fabrykę ``QSettings`` tego
    pliku do zapisu wartości przed utworzeniem okna.
    """
    from PySide6.QtCore import QSettings

    from transkryptor.ui import settings_store

    path = str(tmp_path / "settings.ini")

    def factory() -> QSettings:
        return QSettings(path, QSettings.Format.IniFormat)

    monkeypatch.setattr(settings_store, "default_qsettings", factory)
    return factory


@pytest.fixture(autouse=True)
def isolated_autosave(monkeypatch, tmp_path):
    """Autozapis w katalogu tymczasowym, nie w danych użytkownika."""
    from transkryptor import paths

    directory = tmp_path / "autosave"
    monkeypatch.setattr(paths, "autosave_dir", lambda: directory)
    return directory
