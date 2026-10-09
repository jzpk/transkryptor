"""Ikony interfejsu rysowane z wbudowanych definicji SVG.

Ikony są liniowe (siatka 24×24, obrys 2 px) i barwione w czasie działania
kolorem motywu, więc pasują do trybu jasnego i ciemnego bez osobnych plików.
Definicje są autorskie — projekt nie dołącza zewnętrznych zestawów ikon.

Ikony widżetów ustawia się przez ``set_icon``/``set_pixmap`` z nazwami
tokenów motywu (np. ``"text"``), a nie z gotowymi kolorami: po zmianie
motywu ``refresh(root)`` przerysowuje je w nowych kolorach.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QLabel

from transkryptor.ui.theme import tokens

#: Właściwość Qt z opisem ikony zależnej od motywu (``nazwa:kolor:nieaktywny``).
THEMED_ICON_PROPERTY = "themed_icon"
#: Jak wyżej dla ``QLabel`` z obrazkiem (``nazwa:kolor:rozmiar``).
THEMED_PIXMAP_PROPERTY = "themed_pixmap"

_PATHS: dict[str, str] = {
    "superscript": (
        '<path d="M4 8l8 11M12 8l-8 11"/>'
        '<path d="M15.5 6.5a2 2 0 1 1 3.3 1.5L15.5 11h4"/>'
    ),
    "pause_marker": (
        '<circle cx="6" cy="12" r="1.2" fill="currentColor"/>'
        '<circle cx="12" cy="12" r="1.2" fill="currentColor"/>'
        '<circle cx="18" cy="12" r="1.2" fill="currentColor"/>'
    ),
    "new": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5M12 11v6M9 14h6"/>'
    ),
    "export": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5M12 11v6M9.5 14.5L12 17l2.5-2.5"/>'
    ),
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "open": (
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5'
        'a2 2 0 0 1-2-2z"/>'
    ),
    "save": (
        '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z"/>'
        '<path d="M8 3v5h7V3M8 21v-7h8v7"/>'
    ),
    "import": (
        '<path d="M9 18V6l11-2v12"/>'
        '<circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>'
    ),
    "play": '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
    "pause": ('<path d="M8 5.5v13M16 5.5v13" stroke-width="3"/>'),
    "sparkles": (
        '<path d="M10 3l1.8 4.7L16.5 9.5l-4.7 1.8L10 16l-1.8-4.7L3.5 9.5l4.7-1.8z"/>'
        '<path d="M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z"/>'
    ),
    "download": ('<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19.5h14"/>'),
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "check_circle": (
        '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16.5 9.5"/>'
    ),
    "alert": (
        '<path d="M12 3.5L2.8 19.5h18.4z"/><path d="M12 10v4.5"/>'
        '<circle cx="12" cy="17" r=".6" fill="currentColor"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/>'
        '<circle cx="12" cy="7.8" r=".6" fill="currentColor"/>'
    ),
    "redo": '<path d="M20 8H9.5a5.5 5.5 0 0 0 0 11H13"/><path d="M16 4l4 4-4 4"/>',
    "list_check": (
        '<path d="M11 6h9M11 12h9M11 18h9"/>'
        '<path d="M3.5 6l1.5 1.5L8 4.5M3.5 12l1.5 1.5L8 10.5"/>'
        '<circle cx="5.5" cy="18" r="1.4"/>'
    ),
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    "settings": (
        '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/>'
        '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/>'
        '<circle cx="17" cy="18" r="2"/>'
    ),
    "loop": (
        '<path d="M17 2.5l3 3-3 3"/><path d="M4 11.5v-2a4 4 0 0 1 4-4h12"/>'
        '<path d="M7 21.5l-3-3 3-3"/><path d="M20 12.5v2a4 4 0 0 1-4 4H4"/>'
    ),
    "audio_file": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5M9 13.5v3M12 11.5v7M15 13v4"/>'
    ),
}


def available() -> tuple[str, ...]:
    """Nazwy wszystkich ikon."""
    return tuple(_PATHS)


def _svg(name: str, color: str) -> bytes:
    body = _PATHS[name].replace("currentColor", color)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    ).encode()


def pixmap(
    name: str, color: str, size: int, device_pixel_ratio: float = 1.0
) -> QPixmap:
    """Rysuje ikonę o boku ``size`` (w pikselach logicznych)."""
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    physical = max(1, round(size * device_pixel_ratio))
    image = QPixmap(physical, physical)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, physical, physical))
    painter.end()
    image.setDevicePixelRatio(device_pixel_ratio)
    return image


@lru_cache(maxsize=256)
def icon(name: str, color: str, disabled_color: str | None = None) -> QIcon:
    """Ikona w kolorze ``color`` (i ``disabled_color`` dla stanu nieaktywnego)."""
    result = QIcon()
    for size in (16, 20, 24, 32):
        for ratio in (1.0, 2.0):
            result.addPixmap(pixmap(name, color, size, ratio), QIcon.Mode.Normal)
            if disabled_color:
                result.addPixmap(
                    pixmap(name, disabled_color, size, ratio), QIcon.Mode.Disabled
                )
    return result


ICON_SIZE = QSize(18, 18)


def themed(name: str, color: str, disabled: str | None = None) -> QIcon:
    """Ikona w kolorach tokenów aktywnego motywu (``color``, ``disabled``)."""
    t = tokens()
    return icon(name, getattr(t, color), getattr(t, disabled) if disabled else None)


def set_icon(
    target: QAction | QAbstractButton,
    name: str,
    color: str,
    disabled: str | None = None,
) -> None:
    """Ustawia ikonę w kolorach motywu i zapamiętuje ją dla ``refresh``."""
    target.setProperty(THEMED_ICON_PROPERTY, f"{name}:{color}:{disabled or ''}")
    target.setIcon(themed(name, color, disabled))


def set_pixmap(label: QLabel, name: str, color: str, size: int) -> None:
    """Obrazek etykiety w kolorze motywu, zapamiętany dla ``refresh``."""
    label.setProperty(THEMED_PIXMAP_PROPERTY, f"{name}:{color}:{size}")
    label.setPixmap(
        pixmap(name, getattr(tokens(), color), size, label.devicePixelRatioF())
    )


def refresh(root: QObject) -> None:
    """Przerysowuje ikony ``root`` i jego potomków w kolorach bieżącego motywu."""
    for obj in (root, *root.findChildren(QObject)):
        spec = obj.property(THEMED_ICON_PROPERTY)
        if isinstance(spec, str) and isinstance(obj, QAction | QAbstractButton):
            name, color, disabled = spec.split(":")
            obj.setIcon(themed(name, color, disabled or None))
        spec = obj.property(THEMED_PIXMAP_PROPERTY)
        if isinstance(spec, str) and isinstance(obj, QLabel):
            name, color, size = spec.split(":")
            set_pixmap(obj, name, color, int(size))
