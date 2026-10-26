"""Blokada interfejsu na czas krótkiej pracy w tle (np. wyszukiwania w korpusie).

``BusyOverlay`` przyciemnia wskazane okno i pokazuje kartę ze spinnerem
(``ui/loading_overlay.Spinner``), opisem postępu i przyciskiem przerwania;
bez karty (``with_card=False``) samo przyciemnia - tak zasłania się okno
główne pod oknem, w którym trwa praca.

``InputBlocker`` to filtr zdarzeń całej aplikacji: dopóki działa, odrzuca
mysz, klawiaturę, kółko, menu kontekstowe i skróty akcji we wszystkich
oknach poza wskazanymi widżetami (przycisk przerwania). Sama nakładka nie
wystarcza - nie zatrzymuje skrótów klawiaturowych ani pracy w innym oknie.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.ui.loading_overlay import Spinner

_BLOCKED_EVENTS = frozenset(
    {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.Wheel,
        QEvent.Type.KeyPress,
        QEvent.Type.KeyRelease,
        QEvent.Type.ShortcutOverride,
        QEvent.Type.ContextMenu,
        QEvent.Type.Drop,
    }
)


class InputBlocker(QObject):
    """Filtr zdarzeń aplikacji przepuszczający wejście tylko do ``allowed``."""

    def __init__(self, allowed: tuple[QWidget, ...], parent: QObject | None = None):
        super().__init__(parent)
        self._allowed = allowed
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._active:
            app.installEventFilter(self)
            self._active = True

    def stop(self) -> None:
        app = QApplication.instance()
        if app is not None and self._active:
            app.removeEventFilter(self)
        self._active = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        # Skrót akcji trafia do samej akcji (QObject), nie do widżetu.
        if kind == QEvent.Type.Shortcut:
            return True
        if kind not in _BLOCKED_EVENTS or not isinstance(watched, QWidget):
            return False
        return not any(
            watched is widget or widget.isAncestorOf(watched)
            for widget in self._allowed
        )


class BusyOverlay(QWidget):
    """Przyciemnienie okna, a z kartą - spinner, opis i przycisk przerwania."""

    cancel_requested = Signal()

    def __init__(self, host: QWidget, with_card: bool = True) -> None:
        super().__init__(host)
        self._host = host
        self.setObjectName("busy_overlay")
        self.setStyleSheet(
            "#busy_card { background-color: palette(base);"
            " border: 1px solid palette(midlight); border-radius: 14px; }"
        )
        self.card = QFrame(self)
        self.card.setObjectName("busy_card")
        self.card.setFixedWidth(340)
        self.spinner = Spinner(self.card, size=64)
        self.title_label = QLabel()
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.detail_label = QLabel()
        self.cancel_button = QPushButton(tr("busy.cancel"))
        self.cancel_button.clicked.connect(self._on_cancel)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(28, 24, 28, 20)
        card_layout.setSpacing(12)
        card_layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignHCenter)
        for label in (self.title_label, self.detail_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            card_layout.addWidget(label)
        card_layout.addWidget(
            self.cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignCenter)
        self.card.setVisible(with_card)
        host.installEventFilter(self)
        self.hide()

    def start(self, title: str) -> None:
        self.title_label.setText(title)
        self.detail_label.setText("")
        self.cancel_button.setEnabled(True)
        self.spinner.set_progress(None)
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        if self.card.isVisibleTo(self):
            self.spinner.start()

    def stop(self) -> None:
        self.spinner.stop()
        self.hide()

    def is_active(self) -> bool:
        return self.isVisible()

    def set_progress(self, done: int, total: int) -> None:
        """Postęp ``done`` z ``total`` projektów (spinner i opis)."""
        if total <= 0:
            return
        self.spinner.set_progress(done / total)
        self.detail_label.setText(tr("busy.progress", done=done, total=total))

    def _on_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.detail_label.setText(tr("busy.cancelling"))
        self.cancel_requested.emit()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._host.rect())
        return super().eventFilter(watched, event)
