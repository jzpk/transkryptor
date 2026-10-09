"""Wspólna konfiguracja testów."""

import pytest

from transkryptor import i18n


@pytest.fixture(autouse=True)
def polish_ui_language():
    """Testy sprawdzają polskie teksty — niezależnie od języka systemu."""
    i18n.set_language(i18n.POLISH)
    yield
    i18n.set_language(i18n.POLISH)
