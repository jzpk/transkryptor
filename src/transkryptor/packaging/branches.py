"""Gałęzie wydań: skąd wolno wydać którą wersję.

``main`` to rozwój następnej wersji minor/major (np. 0.9.0), a gałąź
``release/X.Y`` - poprawki wydanej serii (0.8.2, 0.8.3, ...). Poprawki
scala się tylko w przód (``release/X.Y`` → ``main``), nigdy odwrotnie, więc
wydanie z ``release/X.Y`` nie zawiera zmian szykowanych na ``main``.

Workflow „Wydanie” sprawdza przed podbiciem wersji, że wybrana gałąź pasuje
do części wersji (``check``):

- ``release/X.Y`` - tylko ``patch``, a bieżąca wersja musi należeć do serii
  ``X.Y``;
- ``main`` - ``minor`` albo ``major`` (workflow zakłada wtedy gałąź
  ``release/X.Y`` nowej serii); ``patch`` tylko dopóki ``release/X.Y``
  bieżącej serii nie istnieje;
- inne gałęzie - nigdy.

``latest`` mówi, czy wydanie jest najnowszą wersją spośród tagów: poprawka
starszej serii (0.8.4 po 0.9.0) nie może przejąć „najnowszego wydania”,
z którego aplikacje biorą aktualizacje, a strona - linki pobierania.

Moduł korzysta wyłącznie z biblioteki standardowej - workflow uruchamia go
przed instalacją zależności:

    PYTHONPATH=src python3 -m transkryptor.packaging.branches check \\
        --ref release/0.8 --bump patch --version 0.8.1
    PYTHONPATH=src python3 -m transkryptor.packaging.branches latest 0.8.2 \\
        v0.8.1 v0.9.0
"""

from __future__ import annotations

import argparse
import re
import sys

MAIN_BRANCH = "main"
RELEASE_PREFIX = "release/"
BUMPS = ("patch", "minor", "major")

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_RELEASE_BRANCH = re.compile(r"^release/(\d+)\.(\d+)$")


class BranchError(Exception):
    """Wydanie nie może wyjść z tej gałęzi."""


def parse_version(text: str) -> tuple[int, int, int]:
    """``0.8.1`` albo ``v0.8.1`` → ``(0, 8, 1)``."""
    match = _VERSION.match(text.strip())
    if not match:
        raise BranchError(f"Wersja musi mieć postać X.Y.Z (podano: {text}).")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def release_branch(version: str) -> str:
    """Gałąź poprawek serii wersji: ``0.8.1`` → ``release/0.8``."""
    major, minor, _ = parse_version(version)
    return f"{RELEASE_PREFIX}{major}.{minor}"


def check(ref: str, bump: str, version: str, *, release_branch_exists: bool) -> None:
    """Błąd, gdy z gałęzi ``ref`` nie wolno wydać wersji podbitej o ``bump``.

    ``version`` to wersja przed podbiciem, ``release_branch_exists`` - czy
    na remote jest już ``release/X.Y`` jej serii.
    """
    if bump not in BUMPS:
        raise BranchError(f"Nieznana część wersji: {bump}.")
    series = release_branch(version)
    match = _RELEASE_BRANCH.match(ref)
    if match:
        if bump != "patch":
            raise BranchError(
                f"Z gałęzi {ref} wychodzą tylko wydania patch - wydanie {bump} "
                f"uruchom na {MAIN_BRANCH}."
            )
        if ref != series:
            raise BranchError(
                f"Gałąź {ref} ma wersję {version} z serii {series} - "
                "wersja w kodzie nie zgadza się z nazwą gałęzi."
            )
        return
    if ref == MAIN_BRANCH:
        if bump == "patch" and release_branch_exists:
            raise BranchError(
                f"Poprawki serii {version} wydaje się z gałęzi {series}, "
                f"nie z {MAIN_BRANCH}."
            )
        return
    raise BranchError(
        f"Wydanie uruchamia się z {MAIN_BRANCH} albo {RELEASE_PREFIX}X.Y "
        f"(wybrano: {ref})."
    )


def is_latest(version: str, tags: list[str]) -> bool:
    """Czy ``version`` jest nie starsza niż każdy tag wersji z ``tags``."""
    own = parse_version(version)
    versions = [parse_version(tag) for tag in tags if _VERSION.match(tag.strip())]
    return all(own >= other for other in versions)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging.branches",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    checking = commands.add_parser("check", help="czy z gałęzi wolno wydać wersję")
    checking.add_argument("--ref", required=True, help="gałąź uruchomienia")
    checking.add_argument("--bump", required=True, choices=BUMPS)
    checking.add_argument("--version", required=True, help="wersja przed podbiciem")
    checking.add_argument(
        "--release-branch-exists",
        action="store_true",
        help="gałąź release/X.Y bieżącej serii jest już na remote",
    )
    latest = commands.add_parser("latest", help="wypisz true/false")
    latest.add_argument("version", help="wydawana wersja")
    latest.add_argument("tags", nargs="*", help="tagi repozytorium (v*)")
    series = commands.add_parser("series", help="wypisz gałąź release/X.Y wersji")
    series.add_argument("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check":
            check(
                args.ref,
                args.bump,
                args.version,
                release_branch_exists=args.release_branch_exists,
            )
        elif args.command == "latest":
            print("true" if is_latest(args.version, args.tags) else "false")
        else:
            print(release_branch(args.version))
    except BranchError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "MAIN_BRANCH",
    "RELEASE_PREFIX",
    "BranchError",
    "check",
    "is_latest",
    "main",
    "parse_version",
    "release_branch",
]


if __name__ == "__main__":
    sys.exit(main())
