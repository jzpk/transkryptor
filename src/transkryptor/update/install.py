"""Zastosowanie pobranej aktualizacji.

- Windows: instalator Inno Setup w trybie cichym. Ten sam ``AppId`` sprawia,
  że instaluje się w miejsce bieżącej wersji, a ``/CLOSEAPPLICATIONS``
  domyka proces, jeśli jeszcze trwa. Po cichej instalacji instalator sam
  uruchamia program (wpis ``WizardSilent`` w ``packaging/windows.py``).
- Linux (AppImage): nowy obraz zastępuje plik ``$APPIMAGE`` w miejscu, więc
  skróty i wpisy menu nadal działają. Działający proces korzysta z obrazu
  już zamontowanego, a podmiana pliku go nie przerywa.

Samoaktualizacja działa tylko w artefakcie wydania. W środowisku
deweloperskim (``uv run``) aplikacja tylko informuje o nowej wersji.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from transkryptor.errors import UpdateError
from transkryptor.i18n import tr

# /SILENT pokazuje tylko pasek postępu (użytkownik widzi, że coś się dzieje);
# /SUPPRESSMSGBOXES przyjmuje domyślne odpowiedzi na pytania instalatora.
SILENT_INSTALL_ARGS = (
    "/SILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/CLOSEAPPLICATIONS",
)

Launcher = Callable[[Sequence[str]], object]


def appimage_path(environ: Mapping[str, str] | None = None) -> Path | None:
    """Ścieżka uruchomionego pliku AppImage (zmienna ustawiana przez runtime)."""
    value = (os.environ if environ is None else environ).get("APPIMAGE")
    return Path(value) if value else None


def can_self_update(
    *,
    platform: str = sys.platform,
    frozen: bool | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Czy bieżąca instalacja potrafi sama się zaktualizować."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return False
    if platform.startswith("win"):
        return True
    if platform.startswith("linux"):
        current = appimage_path(environ)
        return (
            current is not None
            and current.is_file()
            and os.access(current.parent, os.W_OK)
        )
    return False


def replace_appimage(new: Path, current: Path) -> None:
    """Atomowo podmienia plik AppImage (kopia obok celu, potem ``os.replace``)."""
    staged = current.with_name(f".{current.name}.new")
    try:
        shutil.copyfile(new, staged)
        staged.chmod(0o755)
        os.replace(staged, current)
    except OSError as error:
        staged.unlink(missing_ok=True)
        raise UpdateError(
            user_message=tr("update.error.replace", name=current.name, reason=error),
            retry_hint=tr("update.error.replace.hint"),
        ) from error


def apply_update(
    artifact: Path,
    *,
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
    launcher: Launcher | None = None,
) -> None:
    """Uruchamia instalację pobranej wersji; aplikacja powinna się potem zamknąć."""
    if platform.startswith("win"):
        _run_windows_installer(artifact)
        return
    current = appimage_path(environ)
    if current is None:
        raise UpdateError(user_message=tr("update.error.unsupported"))
    replace_appimage(artifact, current)
    artifact.unlink(missing_ok=True)
    start = launcher or _start_detached
    start([str(current)])


def _start_detached(command: Sequence[str]) -> object:
    return subprocess.Popen(
        list(command),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _run_windows_installer(installer: Path) -> None:
    """``ShellExecuteW`` zamiast ``Popen``: obsługuje monit UAC, gdy program
    zainstalowano dla wszystkich użytkowników."""
    if sys.platform != "win32":
        raise UpdateError(user_message=tr("update.error.windows_only"))
    import ctypes

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "open", str(installer), " ".join(SILENT_INSTALL_ARGS), None, 1
    )
    # Wartość ≤ 32 oznacza błąd (także odmowę w monicie UAC).
    if int(result) <= 32:
        raise UpdateError(
            user_message=tr("update.error.installer"),
            retry_hint=tr("update.error.installer.hint", path=installer),
        )
