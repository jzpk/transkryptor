"""Standardowe przyciski Qt są po polsku, zgodnie z resztą interfejsu."""

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QMessageBox

from transkryptor.__main__ import install_qt_translations


def test_standard_dialog_buttons_are_polish(qapp) -> None:
    assert install_qt_translations(qapp)
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
