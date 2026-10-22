"""Lokalny dziennik błędów: maskowanie danych, wyjątki, awarie natywne."""

import logging
import os
import platform
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from transkryptor import diagnostics
from transkryptor.errors import ExportError

HOME = "/home/badacz"


@pytest.fixture
def fake_home(monkeypatch):
    """Katalog domowy i instalacja niezależne od maszyny z testami."""
    install = f"{HOME}/apps/transkryptor"
    monkeypatch.setattr(diagnostics, "_home", lambda: HOME)
    monkeypatch.setattr(diagnostics, "_safe_roots", lambda: (install, "/usr/lib"))
    return install


@pytest.fixture
def log_dir(tmp_path):
    """Dziennik włączony w katalogu tymczasowym; po teście — wyłączony."""
    directory = tmp_path / "logs"
    path = diagnostics.configure_logging(directory)
    assert path == directory / diagnostics.LOG_FILE_NAME
    yield directory
    diagnostics.shutdown_logging()


def log_text(directory: Path) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (directory / diagnostics.LOG_FILE_NAME).read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="ścieżki POSIX")
class TestRedact:
    def test_user_paths_keep_only_the_extension(self, fake_home) -> None:
        text = "No such file: '/home/badacz/Wywiady/Jan Kowalski.wav'"
        assert diagnostics.redact(text) == "No such file: '<path>.wav'"

    def test_unquoted_and_file_url_paths(self, fake_home) -> None:
        text = "open /media/pendrive/wywiad.transkr via file:///home/badacz/a.mp3"
        assert diagnostics.redact(text) == "open <path>.transkr via file:<path>.mp3"

    def test_installation_paths_stay_with_home_shortened(self, fake_home) -> None:
        text = f'File "{fake_home}/transkryptor/ui/editor.py", line 12'
        assert diagnostics.redact(text) == (
            'File "~/apps/transkryptor/transkryptor/ui/editor.py", line 12'
        )
        assert diagnostics.redact('File "/usr/lib/python3.12/json/x.py"') == (
            'File "/usr/lib/python3.12/json/x.py"'
        )

    def test_directory_without_extension(self, fake_home) -> None:
        assert diagnostics.redact("in /home/badacz/Dokumenty") == "in <path>"

    def test_urls_fractions_and_plain_words_are_untouched(self, fake_home) -> None:
        text = "GET https://github.com/jzpk/transkryptor 3/4 and/or 50%"
        assert diagnostics.redact(text) == text

    def test_email_addresses(self, fake_home) -> None:
        assert diagnostics.redact("from jan.kowalski@uni.example.pl") == (
            "from <email>"
        )


def test_windows_paths_are_masked() -> None:
    text = r"cannot open 'C:\Users\Jan\Desktop\wywiad.docx' or D:\nagrania\a.flac"
    assert diagnostics.redact(text) == "cannot open '<path>.docx' or <path>.flac"


def _raise_chain() -> ExportError:
    try:
        try:
            raise OSError(28, "No space left on device")
        except OSError as error:
            # Treść spoza kodu: w śladzie stosu widać tylko wiersz źródła.
            name = "Jan " + "Kowalski"
            raise ExportError(f"Nie zapisano pliku „{name}.docx”") from error
    except ExportError as error:
        return error


def test_format_exception_omits_user_message_but_keeps_cause() -> None:
    text = diagnostics.format_exception(_raise_chain())
    assert "Jan Kowalski" not in text
    assert "transkryptor.errors.ExportError: <user-facing message omitted>" in text
    assert "OSError: [Errno 28] No space left on device" in text
    assert "direct cause" in text
    assert text.index("OSError") < text.index("ExportError")
    assert "_raise_chain" in text


def test_long_exception_messages_are_shortened() -> None:
    text = diagnostics.describe_exception(ValueError("x" * 5000))
    assert len(text) < diagnostics.MAX_MESSAGE_CHARS + 50


def test_log_file_is_written_redacted(log_dir) -> None:
    logger = logging.getLogger("transkryptor.test")
    logger.info("Opened %s", "/home/someone/private/wywiad.wav")
    try:
        raise _raise_chain()
    except ExportError:
        logger.warning("Export failed", exc_info=True)
    text = log_text(log_dir)
    assert "Opened <path>.wav" in text
    assert "private" not in text
    assert "Jan Kowalski" not in text
    assert "ExportError: <user-facing message omitted>" in text
    assert "test_diagnostics.test_log_file_is_written_redacted" in text


def test_library_info_messages_are_skipped(log_dir) -> None:
    logging.getLogger("httpx").info("HTTP Request: GET https://example.org")
    logging.getLogger("httpx").warning("retrying")
    text = log_text(log_dir)
    assert "HTTP Request" not in text
    assert "retrying" in text


def test_unhandled_exceptions_are_logged(log_dir) -> None:
    # Poprzednie hooki (pytest-qt, wydruk na stderr) nie mogą dostać tych
    # wyjątków. Bez monkeypatch: jego cofnięcie nastąpiłoby po wyłączeniu
    # dziennika i zostawiło hooki w module.
    saved = dict(diagnostics._previous_hooks)
    diagnostics._previous_hooks.update(
        excepthook=lambda *args: None, threading=lambda args: None
    )
    try:
        try:
            raise RuntimeError("boom in slot")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        thread = threading.Thread(target=lambda: 1 / 0, name="worker-thread")
        thread.start()
        thread.join()
    finally:
        diagnostics._previous_hooks.update(saved)

    text = log_text(log_dir)
    assert "Unhandled exception\n" in text
    assert "RuntimeError: boom in slot" in text
    assert "Unhandled exception in thread worker-thread" in text
    assert "ZeroDivisionError" in text


def test_shutdown_restores_previous_hooks(tmp_path) -> None:
    before = sys.excepthook, threading.excepthook, sys.unraisablehook
    diagnostics.configure_logging(tmp_path)
    assert sys.excepthook is not before[0]
    diagnostics.shutdown_logging()
    assert (sys.excepthook, threading.excepthook, sys.unraisablehook) == before
    assert diagnostics.active_log_dir() is None


def test_configure_is_idempotent(log_dir, tmp_path) -> None:
    again = diagnostics.configure_logging(tmp_path / "other")
    assert again == log_dir / diagnostics.LOG_FILE_NAME
    assert diagnostics.active_log_dir() == log_dir


def test_unwritable_directory_does_not_block_start(tmp_path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    assert diagnostics.configure_logging(blocker / "logs") is None
    assert diagnostics.active_log_dir() is None


def test_crash_report_moves_to_the_log(log_dir) -> None:
    crash = log_dir / diagnostics.CRASH_FILE_NAME
    crash.write_text(
        'Fatal Python error: Segmentation fault\n  File "/home/x/a.py"\n',
        encoding="utf-8",
    )
    assert diagnostics.collect_crash_report() is True
    assert crash.read_text(encoding="utf-8") == ""
    assert diagnostics.collect_crash_report() is False
    text = log_text(log_dir)
    assert "Fatal Python error: Segmentation fault" in text
    assert "/home/x" not in text


def test_native_crash_is_written_to_crash_log(tmp_path) -> None:
    script = textwrap.dedent(f"""
        import faulthandler
        from pathlib import Path
        from transkryptor import diagnostics
        assert diagnostics.enable_crash_log(Path({str(tmp_path)!r}))
        faulthandler._sigsegv()
        """)
    env = {**os.environ, "PYTHONPATH": str(Path(diagnostics.__file__).parents[1])}
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, timeout=60
    )
    assert result.returncode != 0
    report = (tmp_path / diagnostics.CRASH_FILE_NAME).read_text(encoding="utf-8")
    assert "Fatal Python error" in report


def test_session_header_has_versions_but_no_identity(log_dir) -> None:
    diagnostics.log_session_start([("ui_language", "pl")])
    text = log_text(log_dir)
    assert "Transkryptor session started" in text
    assert "PySide6" in text
    assert "ui_language" in text
    node = platform.node()
    if len(node) > 3:
        assert node not in text


def test_file_summary_has_no_name(tmp_path) -> None:
    path = tmp_path / "Wywiad z Janem.WAV"
    path.write_bytes(b"x" * 2048)
    assert diagnostics.file_summary(path) == ".wav, 0.0 MiB"
    assert diagnostics.file_summary(tmp_path / "brak.mp3") == ".mp3, size unknown"
