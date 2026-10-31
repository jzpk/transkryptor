"""Nakładka samouczka: przyciemnione okno z podświetlonym elementem i kartą opisu.

Nakładka przykrywa okno główne (jak ``LoadingOverlay``) i przechwytuje mysz,
więc w trakcie samouczka nic nie zmienia się przypadkiem. Wskazany element
jest „wycięty” z przyciemnienia i obwiedziony pulsującą ramką, a przejście
do kolejnego kroku przesuwa podświetlenie płynną animacją. Karta obok
elementu pokazuje tytuł, opis i postęp oraz przyciski **Wstecz**, **Dalej**
i **Pomiń samouczek**; z klawiatury: strzałki, Enter i Esc.

Element kroku to pierwszy widoczny obiekt okna o nazwie z ``targets``;
zamknięty panel boczny z tym elementem jest najpierw pokazywany.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props
from transkryptor.ui.tutorial_content import Tutorial

CARD_WIDTH = 380
# Odstęp podświetlenia od krawędzi elementu i karty od podświetlenia.
HOLE_PADDING = 6
CARD_GAP = 14
WINDOW_MARGIN = 12
MOVE_DURATION_MS = 280
PULSE_DURATION_MS = 1400
PULSE_SPREAD = 10
DIM_COLOR = QColor(12, 14, 22, 160)


def resolve_target(host: QWidget, names: Iterable[str]) -> QWidget | None:
    """Pierwszy widoczny element okna ``host`` o nazwie z ``names``.

    Element w zamkniętym albo schowanym za kartą panelu bocznym jest
    odsłaniany. Elementy w osobnym oknie (odpięty panel) są pomijane -
    podświetlenie rysuje się tylko w oknie głównym.
    """
    for name in names:
        widget = host.findChild(QWidget, name)
        if widget is None:
            continue
        _reveal(widget)
        if (
            widget.isVisible()
            and not widget.size().isEmpty()
            and widget.window() is host.window()
        ):
            return widget
    return None


def _reveal(widget: QWidget) -> None:
    """Pokazuje panel boczny z elementem i przewija do niego obszar przewijany."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea) and parent.widget() is not None:
            parent.ensureWidgetVisible(widget)
        if isinstance(parent, QDockWidget):
            if not parent.isVisible():
                parent.show()
            parent.raise_()
        parent = parent.parentWidget()


def _visible_rect(widget: QWidget, host: QWidget) -> QRect:
    """Prostokąt elementu w układzie ``host`` przycięty do jego rodziców."""
    rect = QRect(widget.mapTo(host, QPoint(0, 0)), widget.size())
    parent = widget.parentWidget()
    while parent is not None and parent is not host:
        rect = rect.intersected(QRect(parent.mapTo(host, QPoint(0, 0)), parent.size()))
        parent = parent.parentWidget()
    return rect


class TutorialCard(QFrame):
    """Karta kroku: postęp, tytuł, opis i przyciski nawigacji."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("tutorial_card")
        self.setFixedWidth(CARD_WIDTH)
        self.progress_label = QLabel()
        set_props(self.progress_label, role="muted")
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() * 1.2)
        self.title_label.setFont(title_font)
        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.skip_button = QPushButton(tr("tutorial.skip"))
        self.back_button = QPushButton(tr("tutorial.back"))
        self.next_button = QPushButton()
        set_props(self.next_button, variant="primary")
        for button in (self.skip_button, self.back_button, self.next_button):
            # Klawisze obsługuje nakładka (Enter, strzałki, Esc).
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._build_layout()

    def _build_layout(self) -> None:
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.next_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.text_label)
        layout.addSpacing(4)
        layout.addLayout(buttons)

    def show_step(
        self, tutorial: Tutorial, index: int, text: str, *, last: bool
    ) -> None:
        self.progress_label.setText(
            tr(
                "tutorial.progress",
                title=tutorial.title,
                current=index + 1,
                total=len(tutorial.steps),
            )
        )
        self.title_label.setText(tutorial.step_title(index))
        self.text_label.setText(text)
        self.back_button.setEnabled(index > 0)
        self.next_button.setText(tr("tutorial.finish" if last else "tutorial.next"))
        self.adjustSize()


class TutorialOverlay(QWidget):
    """Przewodnik po oknie ``host`` krok po kroku.

    ``finished`` niesie ``True``, gdy użytkownik przeszedł wszystkie kroki,
    i ``False`` po pominięciu samouczka.
    """

    finished = Signal(bool)

    def __init__(
        self,
        host: QWidget,
        shortcut_text: Callable[[str], str] = lambda _action: "",
    ) -> None:
        super().__init__(host)
        self._host = host
        self._shortcut_text = shortcut_text
        self._tutorial: Tutorial | None = None
        self._index = 0
        self._target: QWidget | None = None
        self._hole = QRectF()
        self._pulse = 0.0
        self.setObjectName("tutorial_overlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(
            "#tutorial_card { background-color: palette(base);"
            " border: 1px solid palette(highlight); border-radius: 14px; }"
        )
        self.card = TutorialCard(self)
        self._build_animations()
        self._connect_signals()
        host.installEventFilter(self)
        self.hide()

    def _build_animations(self) -> None:
        self._move = QVariantAnimation(self)
        self._move.setDuration(MOVE_DURATION_MS)
        self._move.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._move.valueChanged.connect(self._set_hole)
        self._pulse_animation = QVariantAnimation(self)
        self._pulse_animation.setStartValue(0.0)
        self._pulse_animation.setEndValue(1.0)
        self._pulse_animation.setDuration(PULSE_DURATION_MS)
        self._pulse_animation.setLoopCount(-1)
        self._pulse_animation.valueChanged.connect(self._set_pulse)

    def _connect_signals(self) -> None:
        self.card.next_button.clicked.connect(self.next)
        self.card.back_button.clicked.connect(self.back)
        self.card.skip_button.clicked.connect(self.skip)

    # --- stan ----------------------------------------------------------------

    @property
    def tutorial(self) -> Tutorial | None:
        return self._tutorial

    @property
    def index(self) -> int:
        return self._index

    @property
    def target(self) -> QWidget | None:
        """Element wskazywany przez bieżący krok (None - karta na środku)."""
        return self._target

    def is_running(self) -> bool:
        return self._tutorial is not None

    def target_rect(self) -> QRect:
        """Obszar podświetlenia w układzie nakładki (pusty bez elementu)."""
        target = self._target
        if target is None or not target.isVisible():
            return QRect()
        visible = _visible_rect(target, self._host)
        if visible.isEmpty():
            return QRect()
        rect = visible.adjusted(
            -HOLE_PADDING, -HOLE_PADDING, HOLE_PADDING, HOLE_PADDING
        )
        return rect.intersected(self.rect())

    # --- nawigacja -----------------------------------------------------------

    def start(self, tutorial: Tutorial) -> None:
        self._tutorial = tutorial
        self._index = 0
        self._hole = QRectF()
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._pulse_animation.start()
        self._show_step()

    def next(self) -> None:
        if self._tutorial is None:
            return
        if self._index + 1 >= len(self._tutorial.steps):
            self._finish(completed=True)
            return
        self._index += 1
        self._show_step()

    def back(self) -> None:
        if self._tutorial is None or self._index == 0:
            return
        self._index -= 1
        self._show_step()

    def skip(self) -> None:
        if self._tutorial is not None:
            self._finish(completed=False)

    def _finish(self, *, completed: bool) -> None:
        self._tutorial = None
        self._target = None
        self._move.stop()
        self._pulse_animation.stop()
        self.hide()
        self.finished.emit(completed)

    def _show_step(self) -> None:
        tutorial = self._tutorial
        if tutorial is None:
            return
        step = tutorial.steps[self._index]
        self._target = resolve_target(self._host, step.targets)
        # Odsłonięty panel boczny wychodzi na wierzch - nakładka musi nad niego.
        self.raise_()
        self.card.show_step(
            tutorial,
            self._index,
            tutorial.step_text(self._index, self._shortcut_text),
            last=self._index + 1 == len(tutorial.steps),
        )
        self._move_hole(animated=not self._hole.isEmpty())
        # Odsłonięty panel boczny dostaje układ dopiero w pętli zdarzeń.
        QTimer.singleShot(0, self._refresh)

    def _refresh(self) -> None:
        if self._tutorial is None:
            return
        running = self._move.state() == QAbstractAnimation.State.Running
        if QRectF(self.target_rect()) != self._hole and not running:
            self._move_hole(animated=not self._hole.isEmpty())
        self._place_card()

    # --- podświetlenie i karta -----------------------------------------------

    def _move_hole(self, *, animated: bool) -> None:
        end = QRectF(self.target_rect())
        self._move.stop()
        if animated and not end.isEmpty():
            self._move.setStartValue(self._hole)
            self._move.setEndValue(end)
            self._move.start()
        else:
            self._set_hole(end)
        self._place_card()

    def _set_hole(self, rect: object) -> None:
        self._hole = QRectF(rect) if isinstance(rect, (QRect, QRectF)) else QRectF()
        self.update()

    def _set_pulse(self, value: object) -> None:
        self._pulse = float(value) if isinstance(value, (int, float)) else 0.0
        if not self._hole.isEmpty():
            self.update()

    def _place_card(self) -> None:
        """Karta obok podświetlenia (pod, nad, z prawej, z lewej) albo na środku."""
        card = self.card
        card.adjustSize()
        area = self.rect().adjusted(
            WINDOW_MARGIN, WINDOW_MARGIN, -WINDOW_MARGIN, -WINDOW_MARGIN
        )
        hole = self.target_rect()
        size = card.size()
        if hole.isEmpty():
            card.move(area.center() - QRect(QPoint(0, 0), size).center())
            return
        width, height = size.width(), size.height()
        centre = hole.center()
        candidates = (
            QPoint(centre.x() - width // 2, hole.bottom() + CARD_GAP),
            QPoint(centre.x() - width // 2, hole.top() - CARD_GAP - height),
            QPoint(hole.right() + CARD_GAP, centre.y() - height // 2),
            QPoint(hole.left() - CARD_GAP - width, centre.y() - height // 2),
        )
        for position in candidates:
            rect = _clamped(QRect(position, size), area)
            if area.contains(rect) and not rect.intersects(hole):
                card.move(rect.topLeft())
                return
        # Duży element (np. edytor): karta w jego środku.
        card.move(
            _clamped(
                QRect(centre - QRect(QPoint(), size).center(), size), area
            ).topLeft()
        )

    # --- zdarzenia -----------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._host.rect())
            if self._tutorial is not None:
                self._move.stop()
                self._set_hole(QRectF(self.target_rect()))
                self._place_card()
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if not self._hole.isEmpty():
            hole = QPainterPath()
            hole.addRoundedRect(self._hole, 10, 10)
            dim = dim.subtracted(hole)
        painter.fillPath(dim, DIM_COLOR)
        if self._hole.isEmpty():
            return
        accent = self.palette().highlight().color()
        painter.setPen(QPen(accent, 2.5))
        painter.drawRoundedRect(self._hole, 10, 10)
        # Pulsująca obwódka: rozchodzi się od ramki i gaśnie.
        spread = PULSE_SPREAD * self._pulse
        glow = QColor(accent)
        glow.setAlphaF(max(0.0, 0.7 * (1.0 - self._pulse)))
        painter.setPen(QPen(glow, 2.0))
        painter.drawRoundedRect(
            self._hole.adjusted(-spread, -spread, spread, spread),
            10 + spread,
            10 + spread,
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.skip()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.next()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Backspace):
            self.back()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Kliknięcia poza kartą nie trafiają do okna pod nakładką.
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.accept()


def _clamped(rect: QRect, area: QRect) -> QRect:
    """``rect`` przesunięty tak, by mieścił się w ``area`` (jeśli to możliwe)."""
    x = min(max(rect.left(), area.left()), area.right() - rect.width() + 1)
    y = min(max(rect.top(), area.top()), area.bottom() - rect.height() + 1)
    return QRect(QPoint(x, y), rect.size())
