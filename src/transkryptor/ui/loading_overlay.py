"""Nakładka ładowania blokująca okno na czas transkrypcji ASR.

Praca nadal odbywa się w wątku w tle — pętla zdarzeń Qt pozostaje
responsywna (spinner się kręci, anulowanie działa), ale nakładka
przechwytuje mysz nad całym oknem, a główne okno na ten czas wyłącza
edycję i skróty. Jedynym aktywnym elementem jest przycisk anulowania.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MESSAGE_INTERVAL_MS = 12_000
SPINNER_INTERVAL_MS = 16
ETA_TICK_MS = 1_000
# Szacunek pokazujemy dopiero po tylu sekundach od pierwszego postępu —
# wcześniej tempo jest zbyt chwiejne, by cokolwiek obiecywać.
ETA_MIN_SAMPLE_S = 10.0
ETA_PENDING_TEXT = "Szacowanie pozostałego czasu…"

LOADING_MESSAGES: tuple[str, ...] = (
    "Szukanie zgubionych przecinków…",
    "Odkurzanie samogłosek…",
    "Prostowanie pogiętych spółgłosek…",
    "Liczenie „yyy” i „eee”…",
    "Tłumaczenie mruczenia na polski…",
    "Wyciąganie słów ze szumu…",
    "Parzenie kawy dla modelu…",
    "Rozplątywanie zdań wielokrotnie złożonych…",
    "Polerowanie ogonków przy ą i ę…",
    "Dopasowywanie kropek do końców zdań…",
    "Przesłuchiwanie podejrzanie cichych fragmentów…",
    "Łapanie słów, które uciekły mówiącemu…",
    "Sortowanie „sz”, „cz” i „rz”…",
    "Nastawianie uszu na maksimum…",
    "Odróżnianie „ż” od „rz” na słuch…",
    "Wymiatanie echa z kątów nagrania…",
    "Konsultacje z duchem Słownika Języka Polskiego…",
    "Ważenie każdej sylaby z osobna…",
    "Przewijanie taśmy ołówkiem…",
    "Wyjaśnianie modelowi, czym jest „no weź”…",
    "Rozdzielanie sklejonych wyrazów…",
    "Doklejanie urwanych końcówek…",
    "Układanie słów w kolejności alfabetycznej… (żart)",
    "Sprawdzanie, czy „tego” to słowo, czy westchnienie…",
    "Negocjacje z pauzami o ich długość…",
    "Wyławianie sensu z potoku słów…",
    "Ostrzenie ołówka transkrybenta…",
    "Uspokajanie rozgadanych neuronów…",
    "Zaglądanie między wiersze…",
    "Jeszcze tylko chwilka, słowo daję…",
)


def format_remaining(seconds: float) -> str:
    """Zgrubny, zaokrąglony w górę opis pozostałego czasu."""
    if seconds <= 0:
        return "Jeszcze chwila…"
    if seconds < 60:
        return "Pozostało mniej niż minuta"
    minutes = math.ceil(seconds / 60)
    if minutes < 60:
        return f"Pozostało ok. {minutes} min"
    hours, minutes = divmod(minutes, 60)
    if not minutes:
        return f"Pozostało ok. {hours} godz."
    return f"Pozostało ok. {hours} godz. {minutes} min"


class Spinner(QWidget):
    """Pierścień postępu z gradientem, rysowany co klatkę bez zasobów.

    Dopóki postęp jest nieznany (ładowanie modelu, analiza ciszy), po
    pierścieniu krąży gradientowa „kometa”. Po :meth:`set_progress` łuk
    wypełnia się od góry zgodnie z postępem, w środku widać procent,
    a przygaszona kometa krąży dalej jako znak, że praca trwa.
    """

    def __init__(self, parent=None, size: int = 88) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._progress: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(SPINNER_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def progress(self) -> float | None:
        return self._progress

    def set_progress(self, fraction: float | None) -> None:
        """Ustawia postęp 0.0–1.0; ``None`` wraca do trybu nieokreślonego."""
        self._progress = None if fraction is None else min(1.0, max(0.0, fraction))
        self.update()

    def percent_text(self) -> str:
        if self._progress is None:
            return ""
        return f"{int(self._progress * 100)}%"

    def _advance(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def _gradient_colors(self) -> tuple[QColor, QColor, QColor]:
        """Turkus → akcent motywu → fiolet, wyprowadzone z barwy akcentu."""
        accent = self.palette().highlight().color()
        hue = max(0, accent.hsvHue())
        sat, val = accent.hsvSaturation(), accent.value()
        cool = QColor.fromHsv((hue - 45) % 360, sat, min(255, val + 20))
        warm = QColor.fromHsv((hue + 55) % 360, sat, val)
        return cool, accent, warm

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(3.0, self.width() / 11)
        margin = width / 2 + 1
        rect = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        center = rect.center()
        cool, accent, warm = self._gradient_colors()

        track = QColor(accent)
        track.setAlpha(40)
        pen = QPen(track, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(rect)

        # Kąty QPainter i QConicalGradient liczone są przeciwnie do zegara
        # (drawArc w 1/16 stopnia); łuki rysujemy zgodnie z zegarem.
        if self._progress is not None:
            # Gradient przesunięty o kilka stopni, żeby zaokrąglony początek
            # łuku na górze nie łapał koloru z drugiego końca gradientu.
            gradient = QConicalGradient(center, 96)
            gradient.setColorAt(0.0, cool)
            gradient.setColorAt(0.5, accent)
            gradient.setColorAt(0.97, warm)
            gradient.setColorAt(1.0, warm)
            pen.setBrush(QBrush(gradient))
            painter.setPen(pen)
            span = -int(round(self._progress * 360 * 16))
            if span:
                painter.drawArc(rect, 90 * 16, span)
            painter.setOpacity(0.35)

        head = QColor(cool)
        tail = QColor(warm)
        tail.setAlpha(0)
        comet = QConicalGradient(center, -self._angle)
        comet.setColorAt(0.0, head)
        comet.setColorAt(0.15, accent)
        comet.setColorAt(0.3, tail)
        comet.setColorAt(0.98, tail)
        comet.setColorAt(1.0, head)
        pen.setBrush(QBrush(comet))
        painter.setPen(pen)
        painter.drawArc(rect, -self._angle * 16, 105 * 16)
        painter.setOpacity(1.0)

        if self._progress is not None:
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(max(10, int(rect.height() * 0.26)))
            painter.setFont(font)
            painter.setPen(self.palette().text().color())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.percent_text())


class LoadingOverlay(QWidget):
    """Półprzezroczysta nakładka ze spinnerem i rotującym, zabawnym tekstem.

    Rodzicem musi być okno, które nakładka ma zasłonić; jej rozmiar podąża
    za rozmiarem rodzica.
    """

    cancel_requested = Signal()

    def __init__(
        self,
        parent: QWidget,
        messages: tuple[str, ...] = LOADING_MESSAGES,
        interval_ms: int = MESSAGE_INTERVAL_MS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._host = parent
        self._clock = clock
        # Pierwsza próbka postępu (czas, ułamek) i przewidywany koniec.
        # Tempo liczymy od pierwszej próbki, a nie od startu, żeby ładowanie
        # modelu nie zawyżało szacunku.
        self._first_sample: tuple[float, float] | None = None
        self._eta_deadline: float | None = None
        self._messages = list(messages)
        self._queue: list[str] = []
        self.setObjectName("loading_overlay")
        self.setStyleSheet(
            "#loading_card { background-color: palette(base);"
            " border: 1px solid palette(midlight); border-radius: 14px; }"
        )

        card = QFrame(self)
        card.setObjectName("loading_card")
        card.setFixedWidth(420)
        self.spinner = Spinner(card)
        self.title_label = QLabel("Trwa transkrypcja nagrania")
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() * 1.2)
        self.title_label.setFont(title_font)
        self.eta_label = QLabel(ETA_PENDING_TEXT)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        message_font = self.message_label.font()
        message_font.setItalic(True)
        self.message_label.setFont(message_font)
        # Miejsce na dwa wiersze, żeby karta nie skakała przy zmianie tekstu.
        self.message_label.setMinimumHeight(
            self.message_label.fontMetrics().lineSpacing() * 2
        )
        self.hint_label = QLabel(
            "Przetwarzanie odbywa się lokalnie i może potrwać kilka minut."
        )
        self.hint_label.setWordWrap(True)
        self.cancel_button = QPushButton("Anuluj transkrypcję")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 24)
        card_layout.setSpacing(14)
        card_layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignHCenter)
        for label in (
            self.title_label,
            self.eta_label,
            self.message_label,
            self.hint_label,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(label)
        card_layout.addWidget(
            self.cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        layout = QVBoxLayout(self)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        self._message_timer = QTimer(self)
        self._message_timer.setInterval(interval_ms)
        self._message_timer.timeout.connect(self.next_message)
        self._eta_timer = QTimer(self)
        self._eta_timer.setInterval(ETA_TICK_MS)
        self._eta_timer.timeout.connect(self._refresh_eta)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

        parent.installEventFilter(self)
        self.hide()

    # --- sterowanie --------------------------------------------------------

    def start(self) -> None:
        """Pokazuje nakładkę nad rodzicem i uruchamia animację oraz teksty."""
        self.cancel_button.setEnabled(True)
        self.spinner.set_progress(None)
        self._first_sample = None
        self._eta_deadline = None
        self.eta_label.setText(ETA_PENDING_TEXT)
        self._queue = []
        self.next_message()
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        self.cancel_button.setFocus()
        self.spinner.start()
        self._message_timer.start()
        self._eta_timer.start()

    def stop(self) -> None:
        """Ukrywa nakładkę i zatrzymuje timery."""
        self._message_timer.stop()
        self._eta_timer.stop()
        self.spinner.stop()
        self.hide()

    def set_progress(self, fraction: float) -> None:
        """Pokazuje postęp w spinnerze i aktualizuje szacowany czas."""
        self.spinner.set_progress(fraction)
        now = self._clock()
        if self._first_sample is None:
            self._first_sample = (now, fraction)
            return
        first_time, first_fraction = self._first_sample
        elapsed = now - first_time
        done = fraction - first_fraction
        if elapsed >= ETA_MIN_SAMPLE_S and done > 0:
            self._eta_deadline = now + (1.0 - fraction) * elapsed / done
            self._refresh_eta()

    def _refresh_eta(self) -> None:
        """Odlicza do przewidywanego końca między kolejnymi próbkami."""
        if self._eta_deadline is not None:
            self.eta_label.setText(format_remaining(self._eta_deadline - self._clock()))

    def is_active(self) -> bool:
        return self._message_timer.isActive()

    def next_message(self) -> None:
        """Pokazuje kolejny tekst; wszystkie pojawią się przed powtórką."""
        if not self._messages:
            return
        if not self._queue:
            current = self.message_label.text()
            self._queue = random.sample(self._messages, len(self._messages))
            # Bez powtórzenia tego samego tekstu na styku dwóch tasowań.
            if len(self._queue) > 1 and self._queue[0] == current:
                self._queue.append(self._queue.pop(0))
        self.message_label.setText(self._queue.pop(0))

    def _on_cancel_clicked(self) -> None:
        self.cancel_button.setEnabled(False)
        self.message_label.setText("Anulowanie… kończymy bieżący fragment.")
        self._message_timer.stop()
        self._eta_timer.stop()
        self.eta_label.setText("")
        self.cancel_requested.emit()

    # --- rysowanie i dopasowanie do rodzica --------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 140))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._host.rect())
        return super().eventFilter(watched, event)
