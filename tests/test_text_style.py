"""Styl tekstu z CLAUDE.md: łącznik zamiast pauzy i półpauzy.

Kod, który musi rozpoznawać te znaki w danych wejściowych, zapisuje je
kodami ``\\u2013`` / ``\\u2014`` - dosłowny znak nie pojawia się wtedy
w pliku i test go nie zgłasza.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {chr(0x2013): "półpauza (U+2013)", chr(0x2014): "pauza (U+2014)"}
# Plik generowany przez uv; teksty z zależności nie podlegają regule.
SKIPPED = {"uv.lock"}


def tracked_text_files() -> list[Path]:
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("brak repozytorium git")
    files = []
    for name in listing.decode("utf-8").split("\0"):
        path = REPO_ROOT / name
        if not name or name in SKIPPED or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8000]:
            continue  # plik binarny (PDF, obrazy, fonty)
        files.append(path)
    return files


def test_no_em_or_en_dashes_in_tracked_text_files() -> None:
    problems = []
    for path in tracked_text_files():
        text = path.read_bytes().decode("utf-8", "replace")
        for number, line in enumerate(text.splitlines(), 1):
            for char, name in FORBIDDEN.items():
                if char in line:
                    relative = path.relative_to(REPO_ROOT).as_posix()
                    problems.append(f"{relative}:{number}: {name}")
    assert not problems, "użyj „-” zamiast:\n" + "\n".join(problems)
