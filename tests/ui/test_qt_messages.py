"""Komunikaty Qt w dzienniku programu."""

import io
import logging

from PySide6.QtCore import QtMsgType, qWarning

from transkryptor.ui import qt_messages


def test_info_goes_only_to_log(caplog) -> None:
    console = io.StringIO()
    with caplog.at_level(logging.DEBUG, logger="transkryptor.qt"):
        qt_messages.handle_message(
            QtMsgType.QtInfoMsg,
            "qt.multimedia.ffmpeg",
            "Using Qt multimedia with FFmpeg",
            console,
        )
    assert console.getvalue() == ""
    assert caplog.records[-1].levelno == logging.INFO
    assert caplog.records[-1].getMessage() == (
        "qt.multimedia.ffmpeg: Using Qt multimedia with FFmpeg"
    )


def test_warning_is_logged_with_context_and_printed(caplog, add_window) -> None:
    from transkryptor.ui.main_window import MainWindow

    window = add_window(MainWindow())
    window.show()
    window.activateWindow()
    console = io.StringIO()
    with caplog.at_level(logging.WARNING, logger="transkryptor.qt"):
        qt_messages.handle_message(
            QtMsgType.QtWarningMsg,
            "qt.svg.draw",
            "The requested buffer size is too big, ignoring",
            console,
        )
    record = caplog.records[-1]
    assert record.levelno == logging.WARNING
    assert record.getMessage().startswith(
        "qt.svg.draw: The requested buffer size is too big, ignoring"
    )
    assert console.getvalue() == (
        "qt.svg.draw: The requested buffer size is too big, ignoring\n"
    )


def test_installed_handler_receives_qt_messages(caplog) -> None:
    console = io.StringIO()
    qt_messages.install(console)
    try:
        with caplog.at_level(logging.WARNING, logger="transkryptor.qt"):
            qWarning("ostrzeżenie z Qt")
    finally:
        qt_messages.uninstall()
    assert "ostrzeżenie z Qt" in caplog.records[-1].getMessage()
    assert console.getvalue() == "ostrzeżenie z Qt\n"
