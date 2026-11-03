"""Dostępność dla czytników ekranu: nazwy i opisy elementów, ogłoszenia.

Qt wyprowadza nazwę przycisku z jego tekstu, ale przyciski z samą ikoną
i pola bez etykiety byłyby dla czytnika ekranu anonimowe. :func:`describe`
uzupełnia brakujące nazwy i opisy z tekstu albo podpowiedzi (jawnie
ustawionych nie zmienia), a :func:`announce` przekazuje czytnikowi krótki
komunikat (np. z paska stanu) bez przenoszenia fokusu.
"""

from __future__ import annotations

from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import QAbstractButton, QWidget


def plain_label(text: str) -> str:
    """Tekst bez akceleratorów (``&``) i dopisanych skrótów w nawiasie."""
    first_line = text.splitlines()[0] if text else ""
    # Podpowiedzi akcji mają skróty po dwóch spacjach: „Zapisz  (Ctrl+S)”.
    return (
        first_line.split("  (", 1)[0]
        .replace("&&", "\0")
        .replace("&", "")
        .replace("\0", "&")
        .strip()
    )


def describe(root: QWidget) -> None:
    """Brakujące nazwy i opisy dostępności przycisków pod ``root``."""
    for button in root.findChildren(QAbstractButton):
        describe_button(button)


def describe_button(button: QAbstractButton) -> None:
    tooltip = button.toolTip()
    if not button.accessibleName():
        name = plain_label(button.text()) or plain_label(tooltip)
        if name:
            button.setAccessibleName(name)
    if not button.accessibleDescription() and tooltip:
        description = plain_label(tooltip)
        if description and description != button.accessibleName():
            button.setAccessibleDescription(description)


def announce(widget: QWidget, text: str) -> None:
    """Ogłasza ``text`` czytnikowi ekranu (bez zmiany fokusu)."""
    if not text:
        return
    QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(widget, text))
