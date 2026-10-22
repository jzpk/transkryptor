"""Komunikaty błędów trafiają do dziennika bez zlokalizowanej treści."""

import logging

from PySide6.QtWidgets import QWidget

from transkryptor.errors import ImportAudioError
from transkryptor.ui.messages import show_error


def test_show_error_logs_class_and_cause_but_not_message(
    qtbot, caplog, no_blocking_dialogs
) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    try:
        try:
            raise OSError(5, "Input/output error")
        except OSError as cause:
            raise ImportAudioError("Nie można odczytać „wywiad.wav”") from cause
    except ImportAudioError as error:
        with caplog.at_level(logging.WARNING, logger="transkryptor.ui.messages"):
            show_error(parent, "Błąd", error)

    (record,) = caplog.records
    assert record.getMessage() == "Error shown to the user: ImportAudioError"
    # Miejsce wywołania wskazuje operację, a nie samą funkcję komunikatu.
    assert record.funcName == "test_show_error_logs_class_and_cause_but_not_message"
    assert record.exc_info is not None
    assert no_blocking_dialogs[-1][0] == "warning"
