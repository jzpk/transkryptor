"""Wspólna konfiguracja testów."""

import pytest

from transkryptor import i18n


@pytest.fixture(autouse=True)
def polish_ui_language():
    """Testy sprawdzają polskie teksty - niezależnie od języka systemu."""
    i18n.set_language(i18n.POLISH)
    yield
    i18n.set_language(i18n.POLISH)


@pytest.fixture(autouse=True)
def no_cuda(monkeypatch):
    """Testy nie zależą od karty graficznej komputera, na którym biegną."""
    monkeypatch.setattr("transkryptor.asr.engine.cuda_device_count", lambda: 0)
