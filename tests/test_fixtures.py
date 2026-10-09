"""Testy nie mogą zależeć od lokalnych nagrań z katalogu ``test/``.

Ten katalog jest w ``.gitignore`` i istnieje tylko na maszynie autora; w CI
go nie ma. Próbki audio dla testów leżą w ``tests/fixtures/``.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).parent
LOCAL_DIR_REFERENCE = re.compile(r"""["']test/""")


def test_no_test_references_local_recordings() -> None:
    offenders = [
        f"{path.relative_to(TESTS_DIR)}:{number}"
        for path in sorted(TESTS_DIR.rglob("*.py"))
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if LOCAL_DIR_REFERENCE.search(line)
    ]
    assert not offenders, f"odwołania do lokalnego katalogu test/: {offenders}"
