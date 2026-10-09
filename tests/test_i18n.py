"""Testy katalogów tłumaczeń i mechanizmu wyboru języka."""

import ast
import re
from pathlib import Path

import pytest

from transkryptor import i18n
from transkryptor.i18n import ENGLISH, LANGUAGES, POLISH, catalog, tr

SOURCE_ROOT = Path(i18n.__file__).resolve().parents[1]
_FIELD_RE = re.compile(r"\{(\w+)\}")


def test_every_language_has_a_catalog() -> None:
    for language in LANGUAGES:
        assert catalog(language), language


def test_catalogs_have_the_same_keys() -> None:
    reference = set(catalog(POLISH))
    for language in LANGUAGES:
        assert set(catalog(language)) == reference, language


def test_translations_keep_format_fields() -> None:
    for key, text in catalog(POLISH).items():
        fields = set(_FIELD_RE.findall(text))
        for language in LANGUAGES:
            assert set(_FIELD_RE.findall(catalog(language)[key])) == fields, key


def test_no_empty_translations() -> None:
    for language in LANGUAGES:
        assert all(text.strip() for text in catalog(language).values()), language


def test_every_key_used_in_the_source_exists() -> None:
    """Literał ``tr("…")`` bez wpisu w katalogu pokazałby użytkownikowi klucz."""
    known = set(catalog(POLISH))
    missing: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else None
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            if name == "tr":
                if first.value not in known:
                    missing.append(f"{path.name}: {first.value}")
            if name == "tr_plural":
                for form in ("one", "few", "many"):
                    if f"{first.value}.{form}" not in known:
                        missing.append(f"{path.name}: {first.value}.{form}")
    assert missing == []


def test_tr_uses_the_current_language() -> None:
    assert tr("settings.title") == "Ustawienia"
    i18n.set_language(ENGLISH)
    assert tr("settings.title") == "Settings"


def test_tr_formats_fields() -> None:
    i18n.set_language(ENGLISH)
    assert tr("search.position", current=3, total=12) == "3 of 12"


def test_unknown_key_falls_back_to_the_key() -> None:
    assert tr("brak.takiego.klucza") == "brak.takiego.klucza"


def test_missing_format_field_does_not_raise() -> None:
    assert "{total}" in tr("search.position", current=1)


def test_unknown_language_falls_back_to_polish() -> None:
    assert i18n.set_language("xx") == POLISH


@pytest.mark.parametrize(
    ("setting", "system", "expected"),
    [
        ("system", "pl_PL", POLISH),
        ("system", "en_US", ENGLISH),
        ("system", "de_DE", ENGLISH),
        ("system", "C", ENGLISH),
        ("pl", "en_US", POLISH),
        ("en", "pl_PL", ENGLISH),
    ],
)
def test_resolve_language(setting, system, expected) -> None:
    assert i18n.resolve_language(setting, system) == expected


@pytest.mark.parametrize(
    ("count", "polish", "english"),
    [
        (1, "słowo", "word"),
        (2, "słowa", "words"),
        (5, "słów", "words"),
        (12, "słów", "words"),
        (22, "słowa", "words"),
    ],
)
def test_plural_forms(count, polish, english) -> None:
    assert i18n.tr_plural("main.words", count) == polish
    i18n.set_language(ENGLISH)
    assert i18n.tr_plural("main.words", count) == english


def test_all_translations_lists_every_language() -> None:
    assert i18n.all_translations("docx.author") == ("Autor", "Author")
