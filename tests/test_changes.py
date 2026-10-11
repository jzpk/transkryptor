"""Testy historii zmian pokazywanej w aplikacji („Co nowego”)."""

from transkryptor import __version__, changes

SAMPLE = """\
# Historia zmian

Wstęp dla autorów zmian: dopisuj wpisy w sekcji „Nieopublikowane”.

## Nieopublikowane

## 0.3.0 — 2026-10-10

- Nowa funkcja.

## 0.2.0 — 2026-10-08

- Starsza zmiana.
"""


def test_history_skips_intro_and_empty_unreleased() -> None:
    history = changes.history_markdown(SAMPLE)
    assert history.startswith("## 0.3.0 — 2026-10-10\n\n- Nowa funkcja.")
    assert "Wstęp dla autorów" not in history
    assert "Nieopublikowane" not in history
    assert history.endswith("## 0.2.0 — 2026-10-08\n\n- Starsza zmiana.")


def test_unreleased_changes_get_readable_title() -> None:
    text = SAMPLE.replace(
        "## Nieopublikowane\n", "## Nieopublikowane\n\n- W przygotowaniu.\n"
    )
    history = changes.history_markdown(text, "Zmiany w przygotowaniu")
    assert history.startswith("## Zmiany w przygotowaniu\n\n- W przygotowaniu.")


def test_application_reads_its_changelog() -> None:
    """Historia zmian zawiera sekcję zainstalowanej wersji."""
    text = changes.changelog_text()
    assert text is not None
    assert f"## {__version__} — " in text
