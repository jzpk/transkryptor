"""Adres formularza zgłoszeń (błędy i pomysły) na stronie projektu.

Formularz na stronie zakłada zgłoszenie na GitHubie za użytkownika, więc nie
trzeba mieć tam konta. Program niczego nie wysyła sam: otwiera tylko stronę
w przeglądarce, a wersję programu i systemu przekazuje w adresie, żeby
wypełnić nimi pola formularza (użytkownik widzi je przed wysłaniem).
"""

from __future__ import annotations

import platform
from urllib.parse import urlencode

from transkryptor import __version__

# Adres strony bez końcowego ukośnika (tak jak w packaging.site).
SITE_URL = "https://transkryptorapp.pl"
REPORT_PAGE = "zglos.html"
REPORT_FORM_URL = f"{SITE_URL}/{REPORT_PAGE}"


def report_form_url() -> str:
    """Formularz z wersją programu i systemu (bez danych osobowych)."""
    query = urlencode({"wersja": __version__, "system": platform.platform()})
    return f"{REPORT_FORM_URL}?{query}"


__all__ = ["REPORT_FORM_URL", "REPORT_PAGE", "SITE_URL", "report_form_url"]
