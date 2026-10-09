"""Motyw wizualny aplikacji: paleta kolorów, arkusz stylów i czcionka.

Jedno źródło prawdy dla wyglądu. Widżety nie ustawiają kolorów same —
oznaczają się właściwościami (``card``, ``role``, ``variant``, ``tone``),
a arkusz QSS nadaje im wygląd. Dzięki temu motyw jasny i ciemny różnią się
wyłącznie tokenami w ``LIGHT``/``DARK``.

Bazą jest styl Fusion: wygląda tak samo na Windows i Linuksie i w pełni
respektuje arkusz stylów.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from transkryptor.settings import THEME_DARK, THEME_LIGHT

#: Zmienna środowiskowa wymuszająca motyw (``light``/``dark``) zamiast
#: ustawienia systemu; jawny wybór w oknie „Ustawienia…” ma pierwszeństwo.
THEME_ENV = "TRANSKRYPTOR_THEME"


@dataclass(frozen=True)
class Tokens:
    """Kolory motywu (#RRGGBB)."""

    name: str
    bg: str  # tło okna
    surface: str  # karty, edytor, listy
    surface_alt: str  # najechanie, tła pomocnicze
    border: str
    border_strong: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str  # zaznaczenie w listach, tło wciśniętego przycisku
    accent_text: str  # tekst na ``accent_soft``
    on_accent: str  # tekst na ``accent``
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str


LIGHT = Tokens(
    name="light",
    bg="#F3F4F7",
    surface="#FFFFFF",
    surface_alt="#EEF0F4",
    border="#E1E4EA",
    border_strong="#C9CED7",
    text="#1D2129",
    text_muted="#5E6878",
    accent="#4A5BD4",
    accent_hover="#3E4FC2",
    accent_pressed="#3442A6",
    accent_soft="#E7EAFB",
    accent_text="#2E3B99",
    on_accent="#FFFFFF",
    success="#1B7F4C",
    success_soft="#E2F3E9",
    warning="#946200",
    warning_soft="#FFF3D3",
    danger="#C0392B",
    danger_soft="#FCE7E4",
)

DARK = Tokens(
    name="dark",
    bg="#15171C",
    surface="#1E2128",
    surface_alt="#292D36",
    border="#30343D",
    border_strong="#444A55",
    text="#E5E7EB",
    text_muted="#99A2AF",
    accent="#7D8CFF",
    accent_hover="#909DFF",
    accent_pressed="#6B7AEF",
    accent_soft="#2B3163",
    accent_text="#C9CFFF",
    on_accent="#10131F",
    success="#4DC38A",
    success_soft="#1B3327",
    warning="#E2B341",
    warning_soft="#3A2F12",
    danger="#F0766B",
    danger_soft="#3E201D",
)

_current: Tokens = LIGHT


def tokens() -> Tokens:
    """Tokeny aktywnego motywu (np. do kolorowania ikon i rysowania)."""
    return _current


def detect_tokens(app: QGuiApplication | None = None) -> Tokens:
    """Wybiera motyw: zmienna ``TRANSKRYPTOR_THEME``, potem ustawienie systemu."""
    forced = os.environ.get(THEME_ENV, "").strip().lower()
    if forced in ("light", "dark"):
        return DARK if forced == "dark" else LIGHT
    if app is None:
        instance = QGuiApplication.instance()
        app = instance if isinstance(instance, QGuiApplication) else None
    if app is not None:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return DARK
    return LIGHT


def resolve_tokens(choice: str, app: QGuiApplication | None = None) -> Tokens:
    """Tokeny dla wyboru z ustawień (``system``, ``light``, ``dark``)."""
    if choice == THEME_DARK:
        return DARK
    if choice == THEME_LIGHT:
        return LIGHT
    return detect_tokens(app)


def apply_theme(app: QApplication, theme: Tokens | None = None) -> Tokens:
    """Nadaje aplikacji styl Fusion, paletę, czcionkę i arkusz stylów."""
    global _current
    _current = theme or detect_tokens(app)
    app.setStyle("Fusion")
    app.setPalette(build_palette(_current))
    font = app.font()
    if font.pointSizeF() < 10:
        font.setPointSizeF(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet(_current))
    return _current


def build_palette(t: Tokens) -> QPalette:
    """Paleta Qt zgodna z tokenami — dla elementów rysowanych przez styl."""
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.surface,
        QPalette.ColorRole.AlternateBase: t.surface_alt,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.surface,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.on_accent,
        QPalette.ColorRole.ToolTipBase: t.text,
        QPalette.ColorRole.ToolTipText: t.surface,
        QPalette.ColorRole.PlaceholderText: t.text_muted,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.Mid: t.border_strong,
        QPalette.ColorRole.Midlight: t.border,
        QPalette.ColorRole.Dark: t.border_strong,
        QPalette.ColorRole.Light: t.surface,
        QPalette.ColorRole.Shadow: "#000000",
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(disabled, role, QColor(t.text_muted))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor(t.surface_alt))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor(t.border_strong))
    return palette


def set_props(widget: QWidget, **props: str | bool) -> QWidget:
    """Ustawia właściwości używane przez selektory QSS i odświeża styl."""
    for name, value in props.items():
        widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def section_font(base: QFont) -> QFont:
    """Czcionka nagłówków sekcji (półgruba, nieco większa)."""
    font = QFont(base)
    font.setPointSizeF(base.pointSizeF() * 1.08)
    font.setWeight(QFont.Weight.DemiBold)
    return font


def stylesheet(t: Tokens) -> str:
    """Arkusz stylów dla podanych tokenów."""
    return f"""
QMainWindow, QDialog, QMessageBox {{
    background: {t.bg};
}}
QWidget#central {{
    background: {t.bg};
}}
QToolTip {{
    background: {t.text};
    color: {t.surface};
    border: none;
    border-radius: 4px;
    padding: 5px 8px;
}}

/* --- karty i etykiety -------------------------------------------------- */
QFrame[card="true"] {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 10px;
}}
QFrame[card="true"] QLabel {{
    background: transparent;
}}
QLabel[role="section"] {{
    color: {t.text};
    font-weight: 600;
}}
QLabel[role="caption"] {{
    color: {t.text_muted};
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel[role="muted"] {{
    color: {t.text_muted};
}}
QLabel[role="title"] {{
    color: {t.text};
    font-weight: 600;
}}
QLabel[role="badge"] {{
    background: {t.surface_alt};
    color: {t.text_muted};
    border-radius: 9px;
    padding: 1px 8px;
    font-weight: 600;
}}
QLabel[role="badge"][tone="warning"] {{
    background: {t.warning_soft};
    color: {t.warning};
}}
QLabel[role="badge"][tone="success"] {{
    background: {t.success_soft};
    color: {t.success};
}}
QLabel[role="status"] {{
    border-radius: 6px;
    padding: 6px 10px;
    background: {t.surface_alt};
    color: {t.text_muted};
}}
QLabel[role="status"][tone="success"] {{
    background: {t.success_soft};
    color: {t.success};
}}
QLabel[role="status"][tone="warning"] {{
    background: {t.warning_soft};
    color: {t.warning};
}}
QLabel[role="status"][tone="accent"] {{
    background: {t.accent_soft};
    color: {t.accent_text};
}}
QLabel[role="status"][tone="danger"] {{
    background: {t.danger_soft};
    color: {t.danger};
}}
QLabel[role="step"] {{
    background: {t.accent_soft};
    color: {t.accent_text};
    border-radius: 11px;
    min-width: 22px; max-width: 22px;
    min-height: 22px; max-height: 22px;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}}

/* --- przyciski ---------------------------------------------------------- */
QPushButton {{
    background: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 7px;
    padding: 6px 14px;
    min-height: 20px;
}}
QPushButton:hover {{
    background: {t.surface_alt};
}}
QPushButton:pressed {{
    background: {t.accent_soft};
    border-color: {t.accent};
}}
QPushButton:focus {{
    border-color: {t.accent};
}}
QPushButton:disabled {{
    color: {t.text_muted};
    background: {t.surface_alt};
    border-color: {t.border};
}}
QPushButton[variant="primary"] {{
    background: {t.accent};
    color: {t.on_accent};
    border: 1px solid {t.accent};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background: {t.accent_hover};
    border-color: {t.accent_hover};
}}
QPushButton[variant="primary"]:pressed {{
    background: {t.accent_pressed};
}}
QPushButton[variant="primary"]:disabled {{
    background: {t.surface_alt};
    color: {t.text_muted};
    border-color: {t.border};
    font-weight: 600;
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    border-color: transparent;
    color: {t.text_muted};
}}
QPushButton[variant="ghost"]:hover {{
    background: {t.surface_alt};
    color: {t.text};
}}
QPushButton[variant="ghost"]:disabled {{
    background: transparent;
}}
QPushButton[variant="danger"] {{
    color: {t.danger};
}}
QPushButton[variant="danger"]:hover {{
    background: {t.danger_soft};
    border-color: {t.danger};
}}

/* --- pasek narzędzi ----------------------------------------------------- */
QToolBar {{
    background: {t.surface};
    border: none;
    border-bottom: 1px solid {t.border};
    padding: 6px 12px;
    spacing: 2px;
}}
QToolBar::separator {{
    background: {t.border};
    width: 1px;
    margin: 6px 8px;
}}
QToolBar QLabel[role="caption"] {{
    padding: 0 6px 0 2px;
}}
QToolButton {{
    background: transparent;
    color: {t.text};
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 9px;
}}
QToolButton:hover {{
    background: {t.surface_alt};
}}
QToolButton:pressed, QToolButton:checked {{
    background: {t.accent_soft};
    color: {t.accent_text};
}}
QToolButton:disabled {{
    color: {t.text_muted};
}}
QToolButton[variant="primary"] {{
    background: {t.accent};
    color: {t.on_accent};
    font-weight: 600;
    padding: 5px 12px;
}}
QToolButton[variant="primary"]:hover {{
    background: {t.accent_hover};
}}
QToolButton[variant="primary"]:pressed {{
    background: {t.accent_pressed};
}}
QToolButton[variant="primary"]:disabled {{
    background: {t.surface_alt};
    color: {t.text_muted};
}}

/* Menu „Więcej poleceń”: ikona ☰ sama mówi, że to lista — bez strzałki. */
QToolButton#more_button::menu-indicator {{
    image: none;
    width: 0;
}}

QToolButton#rules_toggle {{
    color: {t.accent_text};
    padding: 3px 6px;
}}
QToolButton#rules_toggle:checked {{
    background: transparent;
}}
QToolButton#rules_toggle:hover {{
    background: {t.accent_soft};
}}

/* --- pola edycyjne ------------------------------------------------------ */
QLineEdit, QDateEdit, QComboBox {{
    background: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 7px;
    padding: 5px 8px;
    min-height: 20px;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}
QLineEdit:hover, QDateEdit:hover, QComboBox:hover {{
    border-color: {t.text_muted};
}}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus {{
    border: 1px solid {t.accent};
}}
QLineEdit:disabled, QDateEdit:disabled, QComboBox:disabled {{
    background: {t.surface_alt};
    color: {t.text_muted};
    border-color: {t.border};
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 4px;
    selection-background-color: {t.accent_soft};
    selection-color: {t.accent_text};
    outline: none;
}}
QTextEdit#editor {{
    background: {t.surface};
    color: {t.text};
    border: none;
    border-top: 1px solid {t.border};
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}

/* --- listy -------------------------------------------------------------- */
QListWidget {{
    background: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget[flat="true"] {{
    border: none;
    border-top: 1px solid {t.border};
    border-radius: 0;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}}
QListWidget::item {{
    padding: 5px 6px;
    border-radius: 6px;
}}
QListWidget::item:hover {{
    background: {t.surface_alt};
}}
QListWidget::item:selected {{
    background: {t.accent_soft};
    color: {t.accent_text};
}}

/* --- suwak, postęp, przewijanie ----------------------------------------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {t.border};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {t.accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {t.surface};
    border: 2px solid {t.accent};
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {t.accent_soft};
}}
QSlider::sub-page:horizontal:disabled {{
    background: {t.border};
}}
QSlider::handle:horizontal:disabled {{
    border-color: {t.border_strong};
    background: {t.surface_alt};
}}
QProgressBar {{
    background: {t.surface_alt};
    border: none;
    border-radius: 4px;
    max-height: 8px;
    min-height: 8px;
}}
QProgressBar::chunk {{
    background: {t.accent};
    border-radius: 4px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {t.border_strong};
    border-radius: 3px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {t.text_muted};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* --- zakładki ----------------------------------------------------------- */
QTabWidget::pane {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {t.text_muted};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 6px 14px;
}}
QTabBar::tab:hover {{
    color: {t.text};
}}
QTabBar::tab:selected {{
    color: {t.text};
    border-bottom-color: {t.accent};
    font-weight: 600;
}}

/* --- pozostałe ---------------------------------------------------------- */
QFrame[role="divider"] {{
    background: {t.border};
}}
QCheckBox {{
    spacing: 8px;
    color: {t.text};
    padding: 2px 0;
}}
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:hover {{
    background: {t.accent_soft};
}}
QDockWidget {{
    color: {t.text};
    font-weight: 600;
}}
QDockWidget::title {{
    background: {t.surface};
    border-bottom: 1px solid {t.border};
    border-left: 1px solid {t.border};
    padding: 8px 12px;
    text-align: left;
}}
QDockWidget > QWidget {{
    font-weight: normal;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QWidget#asr_panel_content {{
    background: {t.surface};
}}
QWidget#asr_panel {{
    background: {t.surface};
    border-left: 1px solid {t.border};
}}
QStatusBar {{
    background: {t.surface};
    border-top: 1px solid {t.border};
    color: {t.text_muted};
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    padding: 2px 8px;
}}
"""
