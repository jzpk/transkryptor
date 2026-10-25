"""Punkt wejścia aplikacji: uruchamia główne okno ręcznej transkrypcji.

Poza oknem punkt wejścia obsługuje dwa przełączniki potrzebne przy odbiorze
wydania (faza 05): ``--version`` oraz ``--self-test``, który sprawdza
kompletność artefaktu bez otwierania interfejsu - także na maszynie bez
serwera okien.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys
from pathlib import Path

from transkryptor import __version__, diagnostics
from transkryptor.i18n import (
    ENGLISH,
    current_language,
    resolve_language,
    set_language,
    tr,
)

logger = logging.getLogger(__name__)

# Moduły, bez których artefakt jest niekompletny. Pakiet ASR jest wymagany
# nawet bez pobranego modelu: bez niego panel „Szkic ASR” zgłosiłby błąd
# dopiero w trakcie pracy użytkownika.
REQUIRED_MODULES = (
    "PySide6.QtWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtSvg",
    "docx",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "sherpa_onnx",
    "av",
    "httpx",
    "huggingface_hub",
    "regex",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
)


def _vad_asset() -> Path:
    """Ścieżka modelu wykrywania mowy dołączanego do faster-whisper."""
    import faster_whisper

    return Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"


def self_test(stream=None) -> int:
    """Sprawdza, czy artefakt zawiera komplet środowiska uruchomieniowego.

    Zwraca 0, gdy wszystko jest na miejscu. Brak pobranego modelu ASR **nie**
    jest błędem: aplikacja ma się uruchamiać i pozwalać na pracę ręczną także
    bez niego (wymaganie wydania z specs/acceptance.md).
    """
    from importlib import import_module

    # Strumień rozstrzygany przy wywołaniu, a nie przy definicji: inaczej
    # funkcja pisałaby do wyjścia sprzed podmiany (także w testach).
    stream = stream if stream is not None else sys.stdout
    # Raport bywa po polsku, a wyjście - w kodowaniu bez polskich znaków
    # (Windows: przekierowanie do pliku lub potoku w cp1252). Znak spoza
    # kodowania nie może przerwać diagnostyki.
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    problems: list[str] = []
    print(f"Transkryptor {__version__}", file=stream)
    print(
        tr(
            "selftest.python",
            version=sys.version.split()[0],
            platform=sys.platform,
        ),
        file=stream,
    )
    print(
        (
            tr("selftest.mode.frozen")
            if getattr(sys, "frozen", False)
            else tr("selftest.mode.dev")
        ),
        file=stream,
    )

    for name in REQUIRED_MODULES:
        try:
            import_module(name)
        except Exception as error:  # noqa: BLE001 - raport, nie przerwanie
            problems.append(tr("selftest.missing_module", name=name, reason=error))
            print(f"  [{tr('selftest.error_tag')}] {name}", file=stream)
        else:
            print(f"  [ok]   {name}", file=stream)

    try:
        asset = _vad_asset()
    except Exception as error:  # noqa: BLE001
        problems.append(tr("selftest.asr_path", reason=error))
    else:
        if asset.is_file():
            print(f"  [ok]   {tr('selftest.vad')} ({asset.name})", file=stream)
        else:
            problems.append(tr("selftest.vad_missing", path=asset))
            print(f"  [{tr('selftest.error_tag')}] {tr('selftest.vad')}", file=stream)

    worker_problem = _check_asr_worker()
    if worker_problem is None:
        print(f"  [ok]   {tr('selftest.asr_worker')}", file=stream)
    else:
        problems.append(tr("selftest.asr_worker_failed", reason=worker_problem))
        print(
            f"  [{tr('selftest.error_tag')}] {tr('selftest.asr_worker')}", file=stream
        )

    from transkryptor.asr.manager import ModelManager

    manager = ModelManager()
    status = (
        tr("selftest.model.downloaded")
        if manager.is_downloaded()
        else tr("selftest.model.missing")
    )
    print(
        f"  [info] {tr('selftest.model', status=status, path=manager.model_dir)}",
        file=stream,
    )
    print(f"  [info] {tr('selftest.log', path=diagnostics.log_dir())}", file=stream)

    if problems:
        print("", file=stream)
        for problem in problems:
            print(f"{tr('selftest.error_tag')}: {problem}", file=stream)
        return 1
    print(f"\n{tr('selftest.complete')}", file=stream)
    return 0


def _check_asr_worker() -> str | None:
    """Start i odpowiedź procesu roboczego ASR; None = działa."""
    from transkryptor.asr.worker import AsrWorker

    worker = AsrWorker()
    try:
        if not worker.ping():
            return "timeout"
    except Exception as error:  # noqa: BLE001 - raport, nie przerwanie
        return str(error) or type(error).__name__
    finally:
        worker.shutdown()
    return None


def configure_language(qsettings=None) -> str:
    """Ustawia język tekstów z ustawień użytkownika (``system`` → język systemu).

    Wołane raz, przed zbudowaniem interfejsu: zmiana języka w ustawieniach
    działa od następnego uruchomienia.
    """
    from PySide6.QtCore import QLocale

    from transkryptor.ui.settings_store import SettingsStore

    setting = SettingsStore(qsettings).load().appearance.language
    return set_language(resolve_language(setting, QLocale.system().name()))


def install_qt_translations(app, language: str | None = None) -> bool:
    """Ładuje tłumaczenie Qt (przyciski Tak/Nie, Odrzuć/Anuluj…) dla języka UI.

    Język pochodzi z ustawień aplikacji (``configure_language``), a nie
    z systemu, żeby standardowe przyciski mówiły tym samym językiem co reszta
    interfejsu. Pliki ``qtbase_*.qm`` dostarcza PySide6 (także w artefakcie
    wydania). Angielski to język źródłowy Qt - nie wymaga pliku. Zwraca
    False, gdy tłumaczenia nie znaleziono - wtedy przyciski są angielskie.
    """
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    language = language or current_language()
    if language == ENGLISH:
        return True
    translator = QTranslator(app)
    loaded = translator.load(
        QLocale(language),
        "qtbase",
        "_",
        QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
    )
    if loaded:
        app.installTranslator(translator)
    return loaded


def main(argv: list[str] | None = None) -> int:
    # Proces roboczy ASR (``asr/worker.py``) w wydaniu PyInstaller startuje
    # z tego samego pliku wykonywalnego - freeze_support go obsługuje i kończy.
    multiprocessing.freeze_support()
    configure_language()
    parser = argparse.ArgumentParser(
        prog="transkryptor",
        description=tr("cli.description"),
    )
    parser.add_argument(
        "--version", action="version", version=f"Transkryptor {__version__}"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=tr("cli.self_test"),
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.self_test:
        return self_test()

    start_diagnostics()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from transkryptor.ui.theme import apply_theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName("transkryptor")
    app.setApplicationDisplayName("Transkryptor")
    app.setApplicationVersion(__version__)
    install_qt_translations(app)
    apply_theme(app)
    log_qt_environment(app)
    window = open_main_window(app)
    # ACC-30: propozycja odzyskania pracy po awarii - gdy okno już widać.
    QTimer.singleShot(0, window.session.offer_recovery)
    QTimer.singleShot(0, window.report_rule_errors)
    code = app.exec()
    logger.info("Session ended (exit code %d)", code)
    return code


def open_main_window(app):
    """Ekran startowy ze sprawdzaniem aktualizacji, potem okno główne.

    Okno powstaje, gdy ekran sprawdza aktualizacje (i ewentualnie pobiera
    nową wersję). Po zakończeniu albo „Pomiń” przebieg przejmuje kontroler
    aktualizacji okna - pominięte pobieranie kończy się w tle.
    """
    from transkryptor.ui.main_window import MainWindow
    from transkryptor.ui.startup_screen import StartupScreen
    from transkryptor.ui.update_controller import UpdateThread
    from transkryptor.update.service import UpdateService

    screen = StartupScreen()
    thread = UpdateThread(UpdateService())
    screen.attach(thread)
    screen.skipped.connect(lambda: logger.info("Startup update check skipped"))
    screen.show()
    app.processEvents()
    thread.start()
    window = MainWindow()
    screen.wait()
    window.updates.adopt(thread)
    window.show()
    screen.deleteLater()
    return window


def start_diagnostics() -> None:
    """Dziennik błędów okna: plik, zapis awarii i nagłówek sesji.

    Awaria natywna z poprzedniego uruchomienia (``crash.log``) trafia do
    dziennika zaraz za nagłówkiem nowej sesji.
    """
    if diagnostics.configure_logging() is None:
        return
    diagnostics.enable_crash_log()
    diagnostics.log_session_start([("ui_language", current_language())])
    diagnostics.collect_crash_report()


def log_qt_environment(app) -> None:
    """Qt, wtyczka platformy i ekrany - częste źródło błędów wyświetlania."""
    from PySide6.QtCore import QLocale, qVersion

    screens = ", ".join(
        f"{screen.size().width()}x{screen.size().height()}"
        f"@{screen.devicePixelRatio():g}"
        for screen in app.screens()
    )
    logger.info(
        "Qt %s, platform %s, locale %s, screens: %s",
        qVersion(),
        app.platformName(),
        QLocale.system().name(),
        screens or "none",
    )


if __name__ == "__main__":
    raise SystemExit(main())
