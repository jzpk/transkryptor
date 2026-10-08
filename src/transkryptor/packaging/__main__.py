"""Uruchomienie narzędzia wydania: ``python -m transkryptor.packaging``."""

from __future__ import annotations

import sys

from transkryptor.packaging.build import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
