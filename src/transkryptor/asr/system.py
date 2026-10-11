"""Zasoby komputera istotne dla ASR: pamięć RAM i karty graficzne CUDA.

Moduł nie zależy od elementów GUI. Obie funkcje są „najlepszego wysiłku”:
brak informacji nie może zablokować transkrypcji.
"""

from __future__ import annotations

import ctypes
import os
import sys


def total_memory_bytes() -> int | None:
    """Całkowita pamięć RAM komputera albo ``None``, gdy nie da się jej odczytać."""
    try:
        if sys.platform == "win32":
            return _windows_total_memory()
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return int(pages * page_size)


def _windows_total_memory() -> int | None:
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
        ctypes.byref(status)
    ):
        return None
    return int(status.ullTotalPhys)


def cuda_device_count() -> int:
    """Liczba kart CUDA widocznych dla CTranslate2 (0 przy braku lub błędzie).

    Biblioteki CUDA nie są dołączane do aplikacji — GPU działa tylko, gdy
    użytkownik zainstalował je sam (``docs/installation.md``).
    """
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:  # noqa: BLE001 — brak GPU to normalny stan
        return 0
