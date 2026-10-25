"""Lokalny dziennik błędów do dołączenia do zgłoszenia na GitHubie.

Aplikacja niczego nie wysyła: dziennik leży w katalogu danych użytkownika
(``logs/``) i trafia do zgłoszenia tylko wtedy, gdy użytkownik sam go dołączy.
Dlatego wpisy mają być po angielsku i nie mogą zawierać danych osobowych ani
treści pracy:

- moduły aplikacji nie logują tekstu transkrypcji, metryczki, kontekstu ASR
  ani nazw plików - tylko rozszerzenia, rozmiary i czasy;
- formatter dodatkowo maskuje ścieżki spoza instalacji programu (``<path>.wav``),
  zastępuje katalog domowy znakiem ``~`` i usuwa adresy e-mail - także
  w komunikatach wyjątków z bibliotek;
- komunikat ``AppError`` (zlokalizowany, często z nazwą pliku) jest pomijany -
  zostaje klasa błędu i łańcuch przyczyn ze śladem stosu.

Poza wpisami modułów dziennik zbiera nieobsłużone wyjątki (wątek główny,
sloty Qt, wątki) i - przez ``faulthandler`` - awarie natywne (np. biblioteki
ASR), także procesu roboczego ASR; zapis awarii trafia do dziennika przy
następnym starcie.

Moduł nie zależy od Qt. Błąd zapisu dziennika nigdy nie blokuje programu.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import platform
import re
import sys
import sysconfig
import threading
import traceback
from collections.abc import Iterator
from functools import cache
from importlib import metadata
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from transkryptor import __version__, paths
from transkryptor.errors import AppError

LOG_FILE_NAME = "transkryptor.log"
CRASH_FILE_NAME = "crash.log"
# Dziennik z kopiami zajmuje najwyżej ~4 MB - wystarczy na wiele sesji,
# a plik da się jeszcze dołączyć do zgłoszenia na GitHubie.
MAX_LOG_BYTES = 1_000_000
BACKUP_COUNT = 3
# Komunikat wyjątku bywa długi (np. cały wynik biblioteki natywnej).
MAX_MESSAGE_CHARS = 500
# Dołączany do zgłoszenia zapis awarii natywnej nie powinien zalać dziennika.
MAX_CRASH_REPORT_CHARS = 20_000

LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s [%(processName)s/%(threadName)s] "
    "%(name)s %(module)s.%(funcName)s:%(lineno)d: %(message)s"
)

logger = logging.getLogger(__name__)

_handler: logging.Handler | None = None
_crash_file: IO[str] | None = None
_previous_hooks: dict[str, Any] = {}


def log_dir() -> Path:
    """Katalog dziennika: ``logs`` w trwałych danych aplikacji."""
    return paths.user_data_dir() / "logs"


def active_log_dir() -> Path | None:
    """Katalog działającego dziennika; None, gdy dziennik nie jest włączony."""
    if isinstance(_handler, logging.FileHandler):
        return Path(_handler.baseFilename).parent
    return None


# --- maskowanie danych -----------------------------------------------------------

_DRIVE = r"[A-Za-z]:[\\/]"
_QUOTED_PATH = re.compile(
    rf"""(?P<quote>['"])(?P<path>(?:{_DRIVE}|\\\\|/|~[\\/])[^'"\n]*)(?P=quote)"""
)
_FILE_URL = re.compile(r"file:/{1,3}[^\s'\"<>]*", re.IGNORECASE)
_BARE_PATH = re.compile(
    rf"""(?<![\w.:/\\~<])(?:{_DRIVE}|\\\\|/(?=[\w.~-])|~[\\/])[^\s'"<>|,;()\[\]]*"""
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,8}")


@cache
def _safe_roots() -> tuple[str, ...]:
    """Katalogi instalacji: ścieżki w nich (ślady stosu) nie są danymi osobowymi."""
    roots = {
        Path(__file__).resolve().parent.parent,  # src/ albo katalog wydania
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.exec_prefix),
        Path(sys.executable).resolve().parent,
    }
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.add(Path(bundle))
    for value in sysconfig.get_paths().values():
        roots.add(Path(value))
    normalized = {_normalize(str(root)) for root in roots}
    # Katalog główny systemu nie może „zabezpieczyć” każdej ścieżki.
    return tuple(sorted(root for root in normalized if len(Path(root).parts) > 1))


@cache
def _home() -> str:
    return _normalize(str(Path.home()))


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _is_safe(path: str) -> bool:
    expanded = _home() + path[1:] if path.startswith("~") else path
    normalized = _normalize(expanded)
    return any(
        normalized == root or normalized.startswith(root.rstrip(os.sep) + os.sep)
        for root in _safe_roots()
    )


def _mask_path(path: str) -> str:
    if _is_safe(path):
        return _shorten_home(path)
    suffix = Path(path.rstrip("\\/")).suffix
    return "<path>" + (suffix if _SUFFIX.fullmatch(suffix) else "")


def _shorten_home(path: str) -> str:
    home = _home()
    normalized = _normalize(path)
    if normalized.startswith(home.rstrip(os.sep) + os.sep):
        return "~" + normalized[len(home.rstrip(os.sep)) :]
    return path


def redact(text: str) -> str:
    """Tekst bez ścieżek użytkownika, katalogu domowego i adresów e-mail."""
    text = _QUOTED_PATH.sub(
        lambda match: match["quote"] + _mask_path(match["path"]) + match["quote"],
        text,
    )
    text = _FILE_URL.sub(lambda match: "file:" + _mask_path(_url_path(match[0])), text)
    text = _BARE_PATH.sub(lambda match: _mask_path(match[0]), text)
    return _EMAIL.sub("<email>", text)


def _url_path(url: str) -> str:
    path = re.sub(r"^file:/*", "/", url, flags=re.IGNORECASE)
    # file:///C:/… → C:/…
    return path[1:] if re.match(r"/[A-Za-z]:/", path) else path


# --- wyjątki ---------------------------------------------------------------------


def format_exception(error: BaseException) -> str:
    """Ślad stosu z łańcuchem przyczyn; bez zlokalizowanych komunikatów ``AppError``.

    Tekst nie jest jeszcze zamaskowany - robi to formatter dziennika (albo
    proces nadrzędny, gdy ślad przychodzi z procesu roboczego ASR).
    """
    chain = list(_exception_chain(error))
    parts: list[str] = []
    for index, exc in enumerate(reversed(chain)):
        if index:
            parts.append(
                "\nThe above exception was the direct cause of the following "
                "exception:\n\n"
                if exc.__cause__ is chain[len(chain) - index]
                else "\nDuring handling of the above exception, another exception "
                "occurred:\n\n"
            )
        if exc.__traceback__ is not None:
            parts.append("Traceback (most recent call last):\n")
            parts.extend(traceback.format_tb(exc.__traceback__))
        parts.append(describe_exception(exc) + "\n")
    return "".join(parts).rstrip("\n")


def describe_exception(error: BaseException) -> str:
    """Klasa i (dla błędów spoza ``AppError``) skrócony komunikat wyjątku."""
    kind = type(error)
    name = kind.__qualname__
    if kind.__module__ not in ("builtins", "__main__"):
        name = f"{kind.__module__}.{name}"
    if isinstance(error, AppError):
        return f"{name}: <user-facing message omitted>"
    try:
        message = str(error)
    except Exception:  # noqa: BLE001 - dziennik nie może zawieść przez __str__
        message = "<unprintable message>"
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[: MAX_MESSAGE_CHARS - 1] + "…"
    return f"{name}: {message}" if message else name


def _exception_chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:
            current = None
        else:
            current = current.__context__


class RedactingFormatter(logging.Formatter):
    """Format dziennika z maskowaniem danych w całym wpisie (także w śladzie)."""

    def formatException(self, ei: Any) -> str:  # noqa: N802 - API logging
        error = ei[1]
        if isinstance(error, BaseException):
            return format_exception(error)
        return super().formatException(ei)

    def format(self, record: logging.LogRecord) -> str:
        # Inny handler mógł już zapisać w rekordzie ślad w zwykłym formacie
        # (z komunikatem ``AppError``) - ten formatter składa własny.
        cached = record.exc_text
        record.exc_text = None
        try:
            return redact(super().format(record))
        finally:
            record.exc_text = cached


# --- konfiguracja ----------------------------------------------------------------


def configure_logging(directory: Path | None = None) -> Path | None:
    """Włącza dziennik w pliku z rotacją; zwraca ścieżkę pliku albo None.

    Wołane raz, przy starcie okna. Gdy katalogu nie da się utworzyć albo
    pliku otworzyć, program działa dalej bez dziennika.
    """
    global _handler
    if isinstance(_handler, logging.FileHandler):
        return Path(_handler.baseFilename)
    directory = directory or log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            directory / LOG_FILE_NAME,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    # Biblioteki tylko od ostrzeżeń (httpx loguje każde żądanie na INFO),
    # moduły aplikacji - także zdarzenia, które pomagają odtworzyć kroki.
    root.setLevel(logging.WARNING)
    logging.getLogger("transkryptor").setLevel(logging.INFO)
    logging.captureWarnings(True)
    _handler = handler
    _install_exception_hooks()
    return directory / LOG_FILE_NAME


def shutdown_logging() -> None:
    """Wyłącza dziennik i przywraca poprzednie hooki (koniec programu, testy)."""
    global _handler, _crash_file
    _restore_exception_hooks()
    logging.captureWarnings(False)
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler.close()
        _handler = None
    if _crash_file is not None:
        if faulthandler.is_enabled():
            faulthandler.disable()
        _crash_file.close()
        _crash_file = None


def crash_log_path(directory: Path | None = None) -> Path:
    return (directory or active_log_dir() or log_dir()) / CRASH_FILE_NAME


def enable_crash_log(directory: Path | None = None) -> bool:
    """Zapis awarii natywnych (``faulthandler``) do ``crash.log``.

    Plik jest dopisywany, więc dzieli go proces główny i proces roboczy ASR.
    Treść przenosi do dziennika :func:`collect_crash_report`.
    """
    global _crash_file
    if _crash_file is not None:
        return True
    path = crash_log_path(directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        crash_file = open(path, "a", encoding="utf-8")  # noqa: SIM115 - do końca
    except OSError:
        return False
    faulthandler.enable(file=crash_file, all_threads=True)
    _crash_file = crash_file
    return True


def collect_crash_report(directory: Path | None = None) -> bool:
    """Przenosi zapis awarii natywnej z ``crash.log`` do dziennika."""
    path = crash_log_path(directory)
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return False
        path.write_text("", encoding="utf-8")
    except OSError:
        return False
    if len(text) > MAX_CRASH_REPORT_CHARS:
        text = "…\n" + text[-MAX_CRASH_REPORT_CHARS:]
    logger.critical("Fatal error recorded by faulthandler:\n%s", text)
    return True


# --- nieobsłużone wyjątki ------------------------------------------------------


def _excepthook(
    kind: type[BaseException],
    value: BaseException,
    tb: TracebackType | None,
) -> None:
    if not issubclass(kind, KeyboardInterrupt):
        logger.critical("Unhandled exception", exc_info=(kind, value, tb))
    previous = _previous_hooks.get("excepthook") or sys.__excepthook__
    previous(kind, value, tb)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_value is not None and not issubclass(args.exc_type, SystemExit):
        thread = args.thread.name if args.thread is not None else "?"
        logger.critical(
            "Unhandled exception in thread %s",
            thread,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    previous = _previous_hooks.get("threading") or threading.__excepthook__
    previous(args)


def _unraisablehook(unraisable: Any) -> None:
    if unraisable.exc_value is not None:
        logger.error(
            "Unraisable exception (%s)",
            unraisable.err_msg or "exception ignored",
            exc_info=(
                unraisable.exc_type,
                unraisable.exc_value,
                unraisable.exc_traceback,
            ),
        )
    previous = _previous_hooks.get("unraisable") or sys.__unraisablehook__
    previous(unraisable)


def _install_exception_hooks() -> None:
    if _previous_hooks:
        return
    _previous_hooks["excepthook"] = sys.excepthook
    _previous_hooks["threading"] = threading.excepthook
    _previous_hooks["unraisable"] = sys.unraisablehook
    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook
    sys.unraisablehook = _unraisablehook


def _restore_exception_hooks() -> None:
    if not _previous_hooks:
        return
    sys.excepthook = _previous_hooks.pop("excepthook")
    threading.excepthook = _previous_hooks.pop("threading")
    sys.unraisablehook = _previous_hooks.pop("unraisable")


# --- opis środowiska -----------------------------------------------------------

# Pakiety, których wersje najczęściej tłumaczą błąd (Qt, ASR, DOCX, sieć).
REPORTED_PACKAGES = (
    "PySide6",
    "faster-whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "python-docx",
    "httpx",
    "huggingface-hub",
    "regex",
    "cryptography",
)


def environment_report() -> list[tuple[str, str]]:
    """Wersje i parametry środowiska bez danych identyfikujących komputer.

    Bez nazwy komputera i użytkownika - tylko system, architektura, Python,
    pakiety, liczba procesorów i ilość pamięci.
    """
    from transkryptor.asr.system import total_memory_bytes

    memory = total_memory_bytes()
    entries = [
        ("version", __version__),
        ("build", "frozen" if getattr(sys, "frozen", False) else "source"),
        (
            "python",
            f"{platform.python_version()} ({platform.python_implementation()}, "
            f"{platform.architecture()[0]})",
        ),
        ("os", platform.platform()),
        ("machine", platform.machine() or "?"),
        ("cpu_count", str(os.cpu_count() or "?")),
        ("memory", f"{memory / 2**30:.1f} GiB" if memory else "unknown"),
    ]
    for package in REPORTED_PACKAGES:
        try:
            entries.append((package, metadata.version(package)))
        except metadata.PackageNotFoundError:
            entries.append((package, "not installed"))
    return entries


def log_session_start(extra: list[tuple[str, str]] | None = None) -> None:
    """Nagłówek sesji: od niego zaczyna się czytanie dziennika ze zgłoszenia."""
    entries = environment_report() + list(extra or [])
    width = max(len(key) for key, _ in entries)
    lines = "\n".join(f"  {key.ljust(width)}  {value}" for key, value in entries)
    logger.info("===== Transkryptor session started =====\n%s", lines)


def file_summary(path: str | Path) -> str:
    """Opis pliku do dziennika bez jego nazwy: rozszerzenie i rozmiar."""
    target = Path(path)
    suffix = target.suffix.lower() or "<none>"
    try:
        size = target.stat().st_size
    except OSError:
        return f"{suffix}, size unknown"
    return f"{suffix}, {size / 2**20:.1f} MiB"


__all__ = [
    "LOG_FILE_NAME",
    "active_log_dir",
    "collect_crash_report",
    "configure_logging",
    "crash_log_path",
    "describe_exception",
    "enable_crash_log",
    "environment_report",
    "file_summary",
    "format_exception",
    "log_dir",
    "log_session_start",
    "redact",
    "shutdown_logging",
]
