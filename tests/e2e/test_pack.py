"""Paczka do przekazania: zapis na jednym „komputerze”, otwarcie na drugim.

Transkrybent eksportuje paczkę z projektem, nagraniem, własnymi regułami,
wstawkami, ustawieniami notacji i szablonem DOCX. Weryfikator - z osobnymi
ustawieniami i regułami - otwiera ją w nowym oknie: projekt wczytuje się
z nagraniem, a ustawienia z paczki przyjmuje. Wariant bez nagrania wiąże
własną kopię nagrania weryfikatora po sumie SHA-256.
"""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from transkryptor.notation.rules import PhoneticRule
from transkryptor.settings import Snippet, encode_snippets
from transkryptor.ui import rules_store
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.pack_dialogs import PackExportDialog, PackImportDialog
from transkryptor.ui.settings_store import SettingsStore

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")
TEXT = "No to tak... uod tego czasu."
RULE = PhoneticRule("USR-UO", {"*": "uo"}, "o", "uo", 0.5)
Button = QMessageBox.StandardButton


def transcriber_window(qtbot, add_window, tmp_path) -> MainWindow:
    """Komputer transkrybenta: nagranie, tekst, reguła, wstawka, szablon."""
    if not SAMPLE_MP3.is_file():
        pytest.skip(f"brak nagrania testowego {SAMPLE_MP3}")
    audio = tmp_path / "transkrybent" / "WP-0042.mp3"
    audio.parent.mkdir()
    shutil.copy(SAMPLE_MP3, audio)
    template = tmp_path / "transkrybent" / "szablon-zespolu.docx"
    DocxDocument().save(str(template))

    window = add_window(MainWindow())
    window._on_import_audio(str(audio))
    qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)
    window.editor.setPlainText(TEXT)
    window.rules_store.save_user_rules([RULE])
    current = window.settings_store.current
    window.settings_store.save(
        replace(
            current,
            notation=replace(current.notation, ellipsis_style="ascii"),
            snippets=replace(
                current.snippets, spec=encode_snippets([Snippet("[śmiech]")])
            ),
            export=replace(current.export, template_path=str(template)),
        )
    )
    return window


def export_pack(window: MainWindow, monkeypatch, target: Path, audio: bool) -> None:
    def accept(dialog: PackExportDialog) -> int:
        dialog.audio_check.setChecked(audio)
        return int(PackExportDialog.DialogCode.Accepted)

    window.packs.run_export_dialog = accept
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    assert window.packs.export() == target


def verifier_window(add_window, tmp_path, monkeypatch) -> MainWindow:
    """Drugi komputer: własne (puste) ustawienia i reguły."""
    rules = tmp_path / "weryfikator" / "rules" / rules_store.USER_RULES_FILE
    monkeypatch.setattr(rules_store, "user_rules_path", lambda: rules)
    store = SettingsStore(
        QSettings(str(tmp_path / "weryfikator.ini"), QSettings.Format.IniFormat)
    )
    store.load()
    window = add_window(MainWindow(settings_store=store))
    window.packs.choose_directory = lambda _start: tmp_path / "od-transkrybenta"
    window.packs.run_import_dialog = lambda _dialog: int(
        PackImportDialog.DialogCode.Accepted
    )
    return window


def test_pack_opens_on_another_computer_with_audio_and_notation(
    qtbot, add_window, tmp_path, monkeypatch
) -> None:
    sender = transcriber_window(qtbot, add_window, tmp_path)
    pack = tmp_path / "wysylka" / "WP-0042.tkpack"
    pack.parent.mkdir()
    export_pack(sender, monkeypatch, pack, audio=True)
    sha256 = sender.session.audio_sha256
    # Plik nadawcy znika - odbiorca ma tylko paczkę.
    shutil.rmtree(tmp_path / "transkrybent")

    receiver = verifier_window(add_window, tmp_path, monkeypatch)
    assert receiver.settings_store.current.notation.ellipsis_style == "unicode"
    assert receiver.packs.open_pack(pack)
    qtbot.waitUntil(lambda: receiver.player_bar.has_media, timeout=10000)

    folder = tmp_path / "od-transkrybenta"
    assert receiver.session.project_path == folder / "WP-0042.transkr"
    assert receiver.player.source_path == folder / "WP-0042.mp3"
    assert receiver.session.audio_sha256 == sha256
    assert receiver.editor.toPlainText() == TEXT
    settings = receiver.settings_store.current
    assert settings.notation.ellipsis_style == "ascii"
    assert [s.text for s in settings.snippets.snippets] == ["[śmiech]"]
    assert settings.export.template_path == str(folder / "szablon-zespolu.docx")
    assert [rule.code for rule in receiver.rules_store.user_rules] == ["USR-UO"]


def test_pack_without_audio_binds_own_copy_by_checksum(
    qtbot, add_window, tmp_path, monkeypatch
) -> None:
    sender = transcriber_window(qtbot, add_window, tmp_path)
    pack = tmp_path / "WP-0042-bez-nagrania.tkpack"
    export_pack(sender, monkeypatch, pack, audio=False)
    own_copy = tmp_path / "weryfikator-nagrania" / "kopia.mp3"
    own_copy.parent.mkdir()
    shutil.copy(SAMPLE_MP3, own_copy)
    shutil.rmtree(tmp_path / "transkrybent")

    receiver = verifier_window(add_window, tmp_path, monkeypatch)
    # Nagrania nie ma obok projektu: program pyta i przyjmuje wskazaną kopię.
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: Button.Yes)
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(own_copy), "")),
    )
    assert receiver.packs.open_pack(pack)
    qtbot.waitUntil(lambda: receiver.player_bar.has_media, timeout=10000)
    assert receiver.player.source_path == own_copy
    assert receiver.session.audio_sha256 == sender.session.audio_sha256
    assert not (tmp_path / "od-transkrybenta" / "WP-0042.mp3").exists()


def test_pack_save_dialog_starts_next_to_project_or_audio(
    qtbot, add_window, tmp_path, monkeypatch
) -> None:
    window = transcriber_window(qtbot, add_window, tmp_path)
    window.packs.run_export_dialog = lambda _dialog: int(
        PackExportDialog.DialogCode.Accepted
    )
    defaults: list[str] = []

    def cancel(_parent, _title, default, _filter):
        defaults.append(default)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(cancel))
    window.packs.export()
    project = tmp_path / "projekty" / "AdK 1954.transkr"
    project.parent.mkdir()
    window.session.project_path = project
    window.packs.export()

    assert defaults == [
        str(tmp_path / "transkrybent" / "WP-0042.tkpack"),
        str(tmp_path / "projekty" / "AdK 1954.tkpack"),
    ]
