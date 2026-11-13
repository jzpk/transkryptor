"""Menu i odnośniki stopki strony projektu, wspólne dla wszystkich podstron.

Szablony ``pages/*.html`` mają w pasku górnym pole ``${nav}``, a w stopce
``${footer_links}``. Generator (``site.py``) wypełnia je osobno dla każdej
strony: bieżąca pozycja menu dostaje ``aria-current="page"``, a strona 404
- ścieżki absolutne, bo GitHub Pages pokazuje ją pod dowolnym adresem.

W menu są same podstrony i wyróżniony przycisk „Pobierz” (sekcja pobierania
na stronie głównej). Nazwa programu w lewym rogu prowadzi na stronę główną.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass

from transkryptor.feedback import REPORT_PAGE

HOME_PAGE = "index.html"
NOT_FOUND_PAGE = "404.html"
CHANGES_PAGE = "zmiany.html"
ISSUES_PAGE = "zgloszenia.html"
DOWNLOAD_ANCHOR = "pobierz"


@dataclass(frozen=True)
class NavItem:
    """Pozycja menu: strona, pełna etykieta i krótka (wąskie ekrany)."""

    page: str
    label: str
    short: str | None = None


NAV_ITEMS = (
    NavItem("faq.html", "FAQ"),
    NavItem(CHANGES_PAGE, "Historia zmian", "Zmiany"),
    NavItem(REPORT_PAGE, "Zgłoś problem", "Zgłoś"),
    NavItem(ISSUES_PAGE, "Status zgłoszeń", "Zgłoszenia"),
    NavItem("autor.html", "O autorze", "Autor"),
)
DOWNLOAD_LABEL = "Pobierz"

# Odnośniki stopki: (pole szablonu z adresem, etykieta).
FOOTER_ITEMS = (
    ("repo_url", "Kod źródłowy"),
    ("guide_url", "Instrukcja użytkownika"),
)


def _prefix(page: str) -> str:
    return "/" if page == NOT_FOUND_PAGE else ""


def _label_html(item: NavItem) -> str:
    if item.short is None:
        return html.escape(item.label)
    return (
        f'<span class="nav-full">{html.escape(item.label)}</span>'
        f'<span class="nav-short">{html.escape(item.short)}</span>'
    )


def download_href(page: str) -> str:
    """Adres sekcji pobierania widziany ze strony ``page``."""
    if page == HOME_PAGE:
        return f"#{DOWNLOAD_ANCHOR}"
    home = "/" if page == NOT_FOUND_PAGE else HOME_PAGE
    return f"{home}#{DOWNLOAD_ANCHOR}"


def nav_html(page: str) -> str:
    """Odnośniki paska górnego strony ``page``."""
    prefix = _prefix(page)
    links = []
    for item in NAV_ITEMS:
        current = ' aria-current="page"' if item.page == page else ""
        links.append(f'<a href="{prefix}{item.page}"{current}>{_label_html(item)}</a>')
    links.append(
        f'<a class="nav-download" href="{download_href(page)}">{DOWNLOAD_LABEL}</a>'
    )
    return "\n".join(links)


def footer_links_html(fields: Mapping[str, str]) -> str:
    """Odnośniki stopki (adresy z pól strony, np. repozytorium)."""
    return "\n".join(
        f'<a href="{html.escape(fields[key])}">{html.escape(label)}</a>'
        for key, label in FOOTER_ITEMS
    )


__all__ = [
    "CHANGES_PAGE",
    "FOOTER_ITEMS",
    "HOME_PAGE",
    "ISSUES_PAGE",
    "NAV_ITEMS",
    "NOT_FOUND_PAGE",
    "NavItem",
    "download_href",
    "footer_links_html",
    "nav_html",
]
