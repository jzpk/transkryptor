"""Standardowe przyciski Qt mówią tym samym językiem co reszta interfejsu."""

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QMessageBox

from transkryptor.__main__ import configure_language, install_qt_translations
from transkryptor.i18n import ENGLISH, POLISH, current_language
from transkryptor.settings import AppearanceSettings, Settings
from transkryptor.ui.settings_store import SettingsStore


def test_standard_dialog_buttons_are_polish(qapp) -> None:
    assert install_qt_translations(qapp, POLISH)
    try:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            "Pytanie",
            "Treść",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        texts = {
            button: box.button(button).text().replace("&", "")
            for button in (
                QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Cancel,
            )
        }
    finally:
        for translator in qapp.findChildren(QTranslator):
            qapp.removeTranslator(translator)
            translator.deleteLater()

    assert texts[QMessageBox.StandardButton.Yes] == "Tak"
    assert texts[QMessageBox.StandardButton.No] == "Nie"
    assert texts[QMessageBox.StandardButton.Cancel] == "Anuluj"
    assert texts[QMessageBox.StandardButton.Discard] != "Discard"


def test_english_needs_no_qt_translation(qapp) -> None:
    """Angielski to język źródłowy Qt — przyciski są angielskie bez pliku."""
    before = len(qapp.findChildren(QTranslator))
    assert install_qt_translations(qapp, ENGLISH)
    assert len(qapp.findChildren(QTranslator)) == before


def test_language_comes_from_settings(isolated_settings) -> None:
    raw = isolated_settings()
    SettingsStore(raw).save(Settings(appearance=AppearanceSettings(language="en")))
    assert configure_language(isolated_settings()) == ENGLISH
    assert current_language() == ENGLISH
