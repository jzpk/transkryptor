"""Punkt wejścia aplikacji: uruchamia główne okno ręcznej transkrypcji.

Poza oknem punkt wejścia obsługuje dwa przełączniki potrzebne przy odbiorze
wydania (faza 05): ``--version`` oraz ``--self-test``, który sprawdza
kompletność artefaktu bez otwierania interfejsu — także na maszynie bez
serwera okien.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from transkryptor import __version__

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
    "av",
    "httpx",
    "huggingface_hub",
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
    # Raport jest po polsku, a wyjście bywa w kodowaniu bez polskich znaków
    # (Windows: przekierowanie do pliku lub potoku w cp1252). Znak spoza
    # kodowania nie może przerwać diagnostyki.
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    problems: list[str] = []
    print(f"Transkryptor {__version__}", file=stream)
    print(f"Python {sys.version.split()[0]}, platforma {sys.platform}", file=stream)
    print(
        (
            "Tryb: artefakt wydania"
            if getattr(sys, "frozen", False)
            else "Tryb: środowisko deweloperskie"
        ),
        file=stream,
    )

    for name in REQUIRED_MODULES:
        try:
            import_module(name)
        except Exception as error:  # noqa: BLE001 — raport, nie przerwanie
            problems.append(f"brak modułu {name}: {error}")
            print(f"  [BŁĄD] {name}", file=stream)
        else:
            print(f"  [ok]   {name}", file=stream)

    try:
        asset = _vad_asset()
    except Exception as error:  # noqa: BLE001
        problems.append(f"nie można ustalić ścieżki zasobów ASR: {error}")
    else:
        if asset.is_file():
            print(f"  [ok]   zasób VAD ({asset.name})", file=stream)
        else:
            problems.append(f"brak zasobu VAD: {asset}")
            print("  [BŁĄD] zasób VAD", file=stream)

    from transkryptor.asr.manager import ModelManager

    manager = ModelManager()
    status = "pobrany" if manager.is_downloaded() else "niepobrany (praca ręczna)"
    print(f"  [info] model ASR: {status} — {manager.model_dir}", file=stream)

    if problems:
        print("", file=stream)
        for problem in problems:
            print(f"BŁĄD: {problem}", file=stream)
        return 1
    print("\nArtefakt kompletny.", file=stream)
    return 0


UI_LOCALE = "pl_PL"


def install_qt_translations(app) -> bool:
    """Ładuje polskie tłumaczenie Qt (przyciski Tak/Nie, Odrzuć/Anuluj…).

    Interfejs aplikacji jest wyłącznie polski, więc język jest wymuszony,
    a nie brany z ustawień systemu. Pliki ``qtbase_*.qm`` dostarcza PySide6
    (także w artefakcie wydania). Zwraca False, gdy tłumaczenia nie
    znaleziono — wtedy standardowe przyciski pozostają angielskie.
    """
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    translator = QTranslator(app)
    loaded = translator.load(
        QLocale(UI_LOCALE),
        "qtbase",
        "_",
        QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
    )
    if loaded:
        app.installTranslator(translator)
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="transkryptor",
        description="Lokalna transkrypcja fonetyczna języka polskiego.",
    )
    parser.add_argument(
        "--version", action="version", version=f"Transkryptor {__version__}"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="sprawdź kompletność artefaktu i zakończ (bez interfejsu)",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.self_test:
        return self_test()

    from PySide6.QtWidgets import QApplication

    from transkryptor.ui.main_window import MainWindow
    from transkryptor.ui.theme import apply_theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName("transkryptor")
    app.setApplicationDisplayName("Transkryptor")
    app.setApplicationVersion(__version__)
    install_qt_translations(app)
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
