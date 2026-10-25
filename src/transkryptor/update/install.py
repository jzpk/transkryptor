"""Zastosowanie pobranej aktualizacji.

- Windows: instalator Inno Setup w trybie cichym. Ten sam ``AppId`` sprawia,
  że instaluje się w miejsce bieżącej wersji, a ``/CLOSEAPPLICATIONS``
  domyka proces, jeśli jeszcze trwa. Po cichej instalacji instalator sam
  uruchamia program (wpis ``WizardSilent`` w ``packaging/windows.py``).
- Linux (AppImage): nowy obraz zastępuje plik ``$APPIMAGE`` w miejscu, więc
  skróty i wpisy menu nadal działają. Działający proces korzysta z obrazu
  już zamontowanego, a podmiana pliku go nie przerywa.

Przed instalacją pobrany plik jest sprawdzany ponownie (podpis sum i suma
pliku), bo od pobrania mogły minąć godziny. AppImage jest dodatkowo
sprawdzany już jako kopia obok celu, tuż przed podmianą. Instalator Windows
jest przed sprawdzeniem otwierany z blokadą zapisu i usuwania
(``_lock_for_launch``): między weryfikacją a uruchomieniem (być może
z monitem UAC) nikt nie podmieni sprawdzonego pliku. Blokada trwa do
zamknięcia aplikacji, bo instalator czyta swój plik także po starcie.

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
from transkryptor.update.download import sha256_of, verify_downloaded

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


def replace_appimage(new: Path, current: Path, expected_sha256: str) -> None:
    """Atomowo podmienia plik AppImage (kopia obok celu, potem ``os.replace``).

    Suma jest sprawdzana na kopii, która faktycznie zastąpi bieżący plik.
    """
    staged = current.with_name(f".{current.name}.new")
    try:
        shutil.copyfile(new, staged)
        if sha256_of(staged) != expected_sha256:
            staged.unlink(missing_ok=True)
            raise UpdateError(
                user_message=tr("update.error.verify_failed", version=new.parent.name),
                retry_hint=tr("update.error.verify_failed.hint"),
            )
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
    trusted_keys: Sequence[str] | None = None,
) -> None:
    """Uruchamia instalację pobranej wersji; aplikacja powinna się potem zamknąć.

    Plik niezgodny z podpisanymi sumami → ``UpdateError`` (nic nie jest
    uruchamiane ani podmieniane).
    """
    windows = platform.startswith("win")
    current = None if windows else appimage_path(environ)
    if not windows and current is None:
        raise UpdateError(user_message=tr("update.error.unsupported"))
    if current is None:
        lock = _lock_for_launch(artifact)
        try:
            verify_downloaded(artifact, trusted_keys)
            _run_windows_installer(artifact)
        except BaseException:
            _release(lock)
            raise
        if lock is not None:
            _LAUNCH_LOCKS.append(lock)
        return
    expected = verify_downloaded(artifact, trusted_keys)
    replace_appimage(artifact, current, expected)
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


# Uchwyty blokujące uruchomione instalatory; system zwalnia je przy wyjściu.
_LAUNCH_LOCKS: list[int] = []

_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80


def _lock_for_launch(path: Path) -> int | None:
    """Uchwyt pliku tylko do odczytu, który zabrania innym zapisu i usuwania.

    Odczyt (weryfikacja, uruchomienie instalatora) nadal działa, ale zapis,
    podmiana (``os.replace``) i usunięcie kończą się błędem współdzielenia.
    Poza Windows → None (podmiany AppImage pilnuje ``replace_appimage``).
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.restype = wintypes.HANDLE
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    handle = create_file(
        str(path),
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle is None or handle == wintypes.HANDLE(-1).value:
        raise UpdateError(
            user_message=tr("update.error.verify_failed", version=path.parent.name),
            retry_hint=tr("update.error.verify_failed.hint"),
        )
    return int(handle)


def _release(lock: int | None) -> None:
    if lock is None or sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.kernel32.CloseHandle(lock)


def release_launch_locks() -> None:
    """Zwalnia blokady uruchomionych instalatorów (testy; wyjście robi to samo)."""
    while _LAUNCH_LOCKS:
        _release(_LAUNCH_LOCKS.pop())


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
