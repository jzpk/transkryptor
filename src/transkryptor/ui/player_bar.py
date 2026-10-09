"""Karta odtwarzacza nagrań: import, nazwa pliku, transport, pozycja i prędkość.

UI jedynie steruje modułem ``audio`` i prezentuje jego stan; nie zawiera
logiki odczytu plików. Publiczne metody (``toggle_play``, ``skip``,
``step_rate``, ``mark_a``/``mark_b``/``toggle_loop``) wywołują zarówno
przyciski karty, jak i skróty klawiaturowe z ``ui/shortcuts.py``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from transkryptor.audio.player import (
    FILE_DIALOG_FILTER,
    SUPPORTED_FORMATS_LABEL,
    AudioPlayer,
)
from transkryptor.document.project import PlayerState
from transkryptor.settings import PlayerSettings
from transkryptor.ui import icons
from transkryptor.ui.shortcuts import (
    LOOP_A,
    LOOP_B,
    LOOP_TOGGLE,
    PLAY_PAUSE,
    RATE_DOWN,
    RATE_UP,
    action_tooltip,
)
from transkryptor.ui.theme import set_props, tokens

PLAYBACK_RATES: tuple[tuple[str, float], ...] = (
    ("0.5x", 0.5),
    ("0.75x", 0.75),
    ("1x", 1.0),
    ("1.25x", 1.25),
    ("1.5x", 1.5),
    ("2x", 2.0),
)
DEFAULT_RATE_INDEX = 2  # 1x

NO_MEDIA_TITLE = "Nie wczytano nagrania"
NO_MEDIA_HINT = "Zaimportuj nagranie audio, aby odsłuchiwać i tworzyć szkic ASR."


def _clamp(value: int | None, maximum: int) -> int | None:
    return None if value is None else max(0, min(value, maximum))


def format_ms(milliseconds: int) -> str:
    """Formatuje milisekundy jako mm:ss."""
    total_seconds = max(0, milliseconds // 1000)
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def format_loop(start_ms: int | None, end_ms: int | None) -> str:
    """Etykieta zakresu pętli, np. „A 01:12 – B 01:18”; pusta bez znaczników."""
    if start_ms is None:
        return ""
    label = f"A {format_ms(start_ms)}"
    if end_ms is not None:
        label += f" – B {format_ms(end_ms)}"
    return label


class PlayerBar(QFrame):
    """Karta sterowania odtwarzaniem umieszczana nad edytorem."""

    import_requested = Signal(str)  # ścieżka wybranego nagrania
    media_available_changed = Signal(bool)

    def __init__(
        self,
        player: AudioPlayer,
        settings: PlayerSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._player = player
        self._settings = settings or PlayerSettings()
        self._seeking = False
        self._has_media = False
        self._loop_a: int | None = None
        self._loop_b: int | None = None
        self._pending_state: PlayerState | None = None

        t = tokens()
        set_props(self, card=True)
        self.setObjectName("player_bar")

        self.import_button = QPushButton("Import nagrania…")
        self.import_button.setIcon(icons.icon("import", t.text, t.text_muted))
        self.import_button.setIconSize(icons.ICON_SIZE)
        self.import_button.setToolTip(
            f"Wybierz nagranie do odsłuchu ({SUPPORTED_FORMATS_LABEL})"
        )
        self.play_button = QPushButton("Odtwórz")
        set_props(self.play_button, variant="primary")
        self._play_icon = icons.icon("play", t.on_accent, t.text_muted)
        self._pause_icon = icons.icon("pause", t.on_accent, t.text_muted)
        self.play_button.setIcon(self._play_icon)
        self.play_button.setIconSize(icons.ICON_SIZE)
        # Stała szerokość: przycisk nie skacze przy zmianie „Odtwórz”/„Pauza”.
        self.play_button.setMinimumWidth(116)
        self.play_button.setEnabled(False)
        self.play_button.setToolTip(action_tooltip(PLAY_PAUSE))
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setEnabled(False)
        self.time_label = QLabel("00:00 / 00:00")
        set_props(self.time_label, role="muted")
        time_font = self.time_label.font()
        time_font.setFamily("monospace")
        time_font.setStyleHint(time_font.StyleHint.Monospace)
        self.time_label.setFont(time_font)
        self.rate_combo = QComboBox()
        for label, _rate in PLAYBACK_RATES:
            self.rate_combo.addItem(label)
        self.rate_combo.setCurrentIndex(DEFAULT_RATE_INDEX)
        self.rate_combo.setEnabled(False)
        self.rate_combo.setToolTip(
            "Prędkość odtwarzania\n"
            + action_tooltip(RATE_DOWN)
            + "\n"
            + action_tooltip(RATE_UP)
        )

        self.loop_a_button = QPushButton("A")
        self.loop_a_button.setToolTip(
            action_tooltip(LOOP_A, "Początek pętli w bieżącym miejscu")
        )
        self.loop_b_button = QPushButton("B")
        self.loop_b_button.setToolTip(
            action_tooltip(LOOP_B, "Koniec pętli w bieżącym miejscu")
        )
        self.loop_button = QPushButton("Pętla")
        self.loop_button.setCheckable(True)
        self.loop_button.setIcon(icons.icon("loop", t.text, t.text_muted))
        self.loop_button.setIconSize(icons.ICON_SIZE)
        self.loop_button.setToolTip(
            action_tooltip(
                LOOP_TOGGLE,
                "Odtwarzaj fragment A–B w kółko (bez B — do końca nagrania); "
                "wyłączenie czyści znaczniki",
            )
        )
        for button in (self.loop_a_button, self.loop_b_button):
            button.setFixedWidth(40)
        for button in (self.loop_a_button, self.loop_b_button, self.loop_button):
            button.setEnabled(False)
        self.loop_label = QLabel()
        set_props(self.loop_label, role="muted")
        self.loop_label.setFont(time_font)

        file_icon = QLabel()
        file_icon.setPixmap(
            icons.pixmap("audio_file", t.accent, 28, self.devicePixelRatioF())
        )
        self.file_label = QLabel(NO_MEDIA_TITLE)
        set_props(self.file_label, role="title")
        self.file_hint_label = QLabel(NO_MEDIA_HINT)
        set_props(self.file_hint_label, role="muted")
        file_text = QVBoxLayout()
        file_text.setSpacing(0)
        file_text.addWidget(self.file_label)
        file_text.addWidget(self.file_hint_label)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(file_icon)
        header.addLayout(file_text, stretch=1)
        header.addWidget(self.import_button)

        rate_caption = QLabel("TEMPO")
        set_props(rate_caption, role="caption")
        transport = QHBoxLayout()
        transport.setSpacing(12)
        transport.addWidget(self.play_button)
        transport.addWidget(self.position_slider, stretch=1)
        transport.addWidget(self.time_label)
        transport.addSpacing(4)
        transport.addWidget(rate_caption)
        transport.addWidget(self.rate_combo)
        transport.addSpacing(4)
        transport.addWidget(self.loop_a_button)
        transport.addWidget(self.loop_b_button)
        transport.addWidget(self.loop_button)
        transport.addWidget(self.loop_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(transport)

        self._connect_signals()

    def _connect_signals(self) -> None:
        self.import_button.clicked.connect(self._on_import_clicked)
        self.play_button.clicked.connect(self.toggle_play)
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        self.position_slider.sliderPressed.connect(self._on_seek_start)
        self.position_slider.sliderReleased.connect(self._on_seek_end)
        self.loop_a_button.clicked.connect(self.mark_a)
        self.loop_b_button.clicked.connect(self.mark_b)
        self.loop_button.clicked.connect(self.toggle_loop)
        self._player.position_changed.connect(self._on_position_changed)
        self._player.duration_changed.connect(self._on_duration_changed)
        self._player.playback_state_changed.connect(self._on_playback_changed)
        self._player.loop_changed.connect(self._on_loop_changed)

    @property
    def has_media(self) -> bool:
        """Czy załadowane nagranie ma znany czas trwania (można nim sterować)."""
        return self._has_media

    def state(self) -> PlayerState:
        """Pozycja i pętla A–B do zapisu w projekcie."""
        if self._pending_state is not None:
            return self._pending_state
        return PlayerState(
            position_ms=self._player.position_ms if self._has_media else 0,
            loop_a_ms=self._loop_a,
            loop_b_ms=self._loop_b,
            loop_active=self._player.loop_range is not None,
        )

    def restore_state(self, state: PlayerState) -> None:
        """Przywraca pozycję i pętlę z projektu.

        Qt Multimedia ładuje nagranie asynchronicznie — gdy czas trwania nie
        jest jeszcze znany, stan czeka na ``duration_changed``.
        """
        if not self._has_media:
            self._pending_state = state
            return
        self._pending_state = None
        duration = self._player.duration_ms
        self._player.set_position(min(state.position_ms, duration))
        self._loop_a = _clamp(state.loop_a_ms, duration)
        self._loop_b = _clamp(state.loop_b_ms, duration)
        if self._loop_a is not None and self._loop_b is not None:
            if self._loop_b <= self._loop_a:
                self._loop_b = None
        self._player.clear_loop()
        if state.loop_active and self._loop_a is not None:
            end = self._loop_b if self._loop_b is not None else duration
            if end > self._loop_a:
                self._player.set_loop(self._loop_a, end)
        self._update_loop_controls()

    def apply_settings(self, settings: PlayerSettings) -> None:
        """Przyjmuje nowe ustawienia odtwarzacza bez restartu."""
        self._settings = settings

    def _on_import_clicked(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Import nagrania", "", FILE_DIALOG_FILTER
        )
        if path:
            self.import_requested.emit(path)

    # --- sterowanie (przyciski i skróty) ---------------------------------------

    def toggle_play(self) -> None:
        """Odtwórz/pauza; wznowienie po pauzie cofa nagranie (auto-cofanie)."""
        if not self._has_media:
            return
        if self._player.is_playing:
            self._player.pause()
        elif self._settings.auto_rewind_enabled and self._player.can_auto_rewind:
            self._player.resume(self._settings.auto_rewind_ms)
        else:
            self._player.play()

    def skip(self, direction: int) -> None:
        """Przewija o długość skoku z ustawień: ``direction`` = -1 albo 1."""
        if not self._has_media:
            return
        self._player.set_position(
            self._player.position_ms + direction * self._settings.skip_ms
        )

    def step_rate(self, delta: int) -> None:
        """Zmienia tempo o ``delta`` pozycji listy; combo pozostaje źródłem tempa."""
        if not self._has_media:
            return
        index = self.rate_combo.currentIndex() + delta
        self.rate_combo.setCurrentIndex(max(0, min(len(PLAYBACK_RATES) - 1, index)))

    def mark_a(self) -> None:
        """Ustawia początek pętli w bieżącym miejscu."""
        if not self._has_media:
            return
        self._loop_a = self._player.position_ms
        if self._loop_b is not None and self._loop_b <= self._loop_a:
            self._loop_b = None
        self._sync_active_loop()

    def mark_b(self) -> None:
        """Ustawia koniec pętli; bez A pętla zaczyna się od początku nagrania."""
        if not self._has_media:
            return
        position = self._player.position_ms
        start = self._loop_a if self._loop_a is not None else 0
        if position <= start:
            QApplication.beep()
            return
        self._loop_a = start
        self._loop_b = position
        self._sync_active_loop()

    def toggle_loop(self) -> None:
        """Włącza pętlę A–B albo ją wyłącza i czyści znaczniki."""
        if not self._has_media:
            self._update_loop_controls()
            return
        if self._player.loop_range is not None:
            self._loop_a = None
            self._loop_b = None
            self._player.clear_loop()
        elif self._loop_a is not None:
            end = self._loop_b if self._loop_b is not None else self._player.duration_ms
            if end > self._loop_a:
                self._player.set_loop(self._loop_a, end)
        self._update_loop_controls()

    def _sync_active_loop(self) -> None:
        """Przy aktywnej pętli zmiana znaczników od razu zmienia jej zakres."""
        if self._player.loop_range is not None:
            end = self._loop_b if self._loop_b is not None else self._player.duration_ms
            if self._loop_a is not None and end > self._loop_a:
                self._player.set_loop(self._loop_a, end)
        self._update_loop_controls()

    def _on_loop_changed(self, _loop: tuple[int, int] | None) -> None:
        # Znaczniki A–B przy zmianie nagrania czyści ``reset()``.
        self._update_loop_controls()

    def _update_loop_controls(self) -> None:
        active = self._player.loop_range is not None
        self.loop_a_button.setEnabled(self._has_media)
        self.loop_b_button.setEnabled(self._has_media)
        self.loop_button.setEnabled(self._has_media and self._loop_a is not None)
        self.loop_button.setChecked(active)
        self.loop_label.setText(format_loop(self._loop_a, self._loop_b))

    def _on_rate_changed(self, index: int) -> None:
        self._player.set_rate(PLAYBACK_RATES[index][1])

    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek_end(self) -> None:
        self._seeking = False
        self._player.set_position(self.position_slider.value())

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._seeking:
            self.position_slider.setValue(position_ms)
        self._update_time_label(position_ms, self._player.duration_ms)

    def _on_duration_changed(self, duration_ms: int) -> None:
        has_media = duration_ms > 0
        if has_media != self._has_media:
            self._has_media = has_media
            self.media_available_changed.emit(has_media)
        self.position_slider.setEnabled(has_media)
        self.position_slider.setRange(0, max(0, duration_ms))
        self.play_button.setEnabled(has_media)
        self.rate_combo.setEnabled(has_media)
        self._update_time_label(self._player.position_ms, duration_ms)
        self._update_loop_controls()
        source = self._player.source_path
        if has_media and source is not None:
            self.file_label.setText(source.name)
            self.file_label.setToolTip(str(source))
            self.file_hint_label.setText(f"Długość {format_ms(duration_ms)}")
        if has_media and self._pending_state is not None:
            self.restore_state(self._pending_state)

    def _on_playback_changed(self, is_playing: bool) -> None:
        self.play_button.setText("Pauza" if is_playing else "Odtwórz")
        self.play_button.setIcon(self._pause_icon if is_playing else self._play_icon)

    def _update_time_label(self, position_ms: int, duration_ms: int) -> None:
        self.time_label.setText(f"{format_ms(position_ms)} / {format_ms(duration_ms)}")

    def reset(self) -> None:
        """Przywraca stan pusty po zwolnieniu nagrania."""
        self.position_slider.setValue(0)
        self.position_slider.setEnabled(False)
        self.play_button.setEnabled(False)
        self.play_button.setText("Odtwórz")
        self.play_button.setIcon(self._play_icon)
        self.rate_combo.setEnabled(False)
        self.rate_combo.setCurrentIndex(DEFAULT_RATE_INDEX)
        self._update_time_label(0, 0)
        self.file_label.setText(NO_MEDIA_TITLE)
        self.file_label.setToolTip("")
        self.file_hint_label.setText(NO_MEDIA_HINT)
        self._loop_a = None
        self._loop_b = None
        self._pending_state = None
        if self._has_media:
            self._has_media = False
            self.media_available_changed.emit(False)
        self._update_loop_controls()
