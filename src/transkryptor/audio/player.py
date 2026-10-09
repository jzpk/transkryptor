"""Moduł audio: import nagrań i sterowanie odtwarzaniem.

Granica modułu: nie interpretuje tekstu. Błędy importu są zgłaszane jako
``ImportAudioError`` z komunikatem dla użytkownika i wskazówką ponowienia
(NFR-03).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from transkryptor.errors import ImportAudioError
from transkryptor.i18n import tr

# Formaty dekodowane zarówno przez Qt Multimedia (odtwarzanie), jak i przez
# PyAV/FFmpeg (ASR). Oba backendy korzystają z FFmpeg.
SUPPORTED_SUFFIXES: tuple[str, ...] = (
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wma",
)
SUPPORTED_FORMATS_LABEL = ", ".join(
    suffix.removeprefix(".").upper() for suffix in SUPPORTED_SUFFIXES
)


def file_dialog_filter() -> str:
    """Filtr okna wyboru pliku dla obsługiwanych nagrań."""
    patterns = " ".join(f"*{suffix}" for suffix in SUPPORTED_SUFFIXES)
    return tr("player.file_filter", patterns=patterns)


# ``positionChanged`` Qt Multimedia przychodzi z ograniczoną częstotliwością;
# przy aktywnej pętli pozycja jest dodatkowo sprawdzana tym interwałem, aby
# powrót do A nie „przestrzelił” B o więcej niż ~150 ms (ACC-21).
LOOP_CHECK_INTERVAL_MS = 30


class AudioPlayer(QObject):
    """Odtwarzacz nagrań oparty na QMediaPlayer.

    Sygnały przenoszą tylko stan odtwarzania (pozycja, czas trwania, stan),
    nigdy obiekty GUI.
    """

    # "qlonglong": milisekundy QMediaPlayer są 64-bitowe. Stuby PySide6
    # nie znają sygnatur podanych jako tekst, choć Qt je obsługuje.
    position_changed = Signal("qlonglong")  # type: ignore[arg-type]
    duration_changed = Signal("qlonglong")  # type: ignore[arg-type]
    playback_state_changed = Signal(bool)  # True = odtwarzanie
    playback_error = Signal(object)  # ImportAudioError
    loop_changed = Signal(object)  # (start_ms, end_ms) | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._player.setAudioOutput(self._output)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self.duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        # Przewinięcie zlecone, zanim nagranie się załadowało (np. pozycja
        # z projektu) — Qt by je zignorował, więc czeka na ``LoadedMedia``.
        self._pending_position: int | None = None
        self._source_path: Path | None = None
        self._last_error: ImportAudioError | None = None
        self._loop: tuple[int, int] | None = None
        self._rewind_armed = False
        self._loop_timer = QTimer(self)
        self._loop_timer.setInterval(LOOP_CHECK_INTERVAL_MS)
        self._loop_timer.timeout.connect(lambda: self._check_loop(self.position_ms))

    @property
    def audio_output(self) -> QAudioOutput:
        """Wyjście audio (do diagnostyki głośności/urządzenia)."""
        return self._output

    @property
    def source_path(self) -> Path | None:
        """Aktualnie załadowany plik lub None."""
        return self._source_path

    @property
    def duration_ms(self) -> int:
        return self._player.duration()

    @property
    def position_ms(self) -> int:
        return self._player.position()

    @property
    def playback_rate(self) -> float:
        return self._player.playbackRate()

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def loop_range(self) -> tuple[int, int] | None:
        """Aktywna pętla A–B (ms) albo None."""
        return self._loop

    @property
    def can_auto_rewind(self) -> bool:
        """Czy wznowienie jest powrotem po pauzie w tym samym miejscu.

        Pierwszy start (stan zatrzymany) i przewinięcie w trakcie pauzy
        (suwak, skok, segment ASR) nie są wznowieniem — wtedy odtwarzanie
        rusza dokładnie od bieżącej pozycji.
        """
        return (
            self._player.playbackState() == QMediaPlayer.PlaybackState.PausedState
            and self._rewind_armed
        )

    def load(self, path: str | Path) -> None:
        """Ładuje nagranie audio. Przy błędzie zgłasza ImportAudioError."""
        candidate = Path(path)
        if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ImportAudioError(
                user_message=tr(
                    "player.error.unsupported",
                    name=candidate.name,
                    formats=SUPPORTED_FORMATS_LABEL,
                ),
                retry_hint=tr("player.error.unsupported.hint"),
            )
        if not candidate.is_file():
            raise ImportAudioError(
                user_message=tr("player.error.not_found", name=candidate.name),
                retry_hint=tr("player.error.not_found.hint"),
            )
        self._last_error = None
        self.clear_loop()
        self._rewind_armed = False
        self._pending_position = None
        self._player.setSource(QUrl.fromLocalFile(str(candidate.resolve())))
        self._source_path = candidate

    def last_error(self) -> ImportAudioError | None:
        """Ostatni błąd odtwarzacza (np. uszkodzony plik), jeśli wystąpił."""
        return self._last_error

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def resume(self, rewind_ms: int) -> None:
        """Wznawia odtwarzanie, cofając się o ``rewind_ms`` (nie przed 0)."""
        self.set_position(self.position_ms - rewind_ms)
        self.play()

    def set_position(self, position_ms: int) -> None:
        """Przewija do pozycji obciętej do zakresu nagrania."""
        self._rewind_armed = False
        position_ms = max(0, position_ms)
        if self.duration_ms > 0:
            position_ms = min(position_ms, self.duration_ms)
        if self._player.mediaStatus() == QMediaPlayer.MediaStatus.LoadingMedia:
            self._pending_position = position_ms
        self._player.setPosition(position_ms)

    def set_loop(self, start_ms: int, end_ms: int) -> None:
        """Włącza pętlę A–B; po dojściu do B odtwarzanie wraca do A."""
        duration = self.duration_ms
        if not (0 <= start_ms < end_ms) or (duration > 0 and end_ms > duration):
            raise ValueError(
                f"Nieprawidłowy zakres pętli {start_ms}–{end_ms} ms "
                f"(nagranie {duration} ms)."
            )
        self._loop = (start_ms, end_ms)
        self._update_loop_timer()
        self.loop_changed.emit(self._loop)

    def clear_loop(self) -> None:
        """Wyłącza pętlę A–B."""
        if self._loop is None:
            return
        self._loop = None
        self._update_loop_timer()
        self.loop_changed.emit(None)

    def set_rate(self, rate: float) -> None:
        self._player.setPlaybackRate(rate)

    def stop_and_unload(self) -> None:
        """Zatrzymuje odtwarzanie i zwalnia załadowane nagranie."""
        self.clear_loop()
        self._rewind_armed = False
        self._pending_position = None
        # Bez ``stop()``: pusty ``setSource`` sam zatrzymuje odtwarzanie, a
        # PySide6 zwalnia przy nim GIL (allow-thread). ``stop()`` wołany z GIL
        # potrafi się zakleszczyć z wątkiem ``QFFmpeg::AudioRenderer``, który
        # w ``~QObject`` trzyma mutex połączeń Qt i czeka na GIL.
        self._player.setSource(QUrl())
        self._source_path = None

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if (
            status == QMediaPlayer.MediaStatus.LoadedMedia
            and self._pending_position is not None
        ):
            position_ms, self._pending_position = self._pending_position, None
            self._player.setPosition(position_ms)

    def _on_position_changed(self, position_ms: int) -> None:
        self.position_changed.emit(position_ms)
        self._check_loop(position_ms)

    def _check_loop(self, position_ms: int) -> None:
        if self._loop is not None and position_ms >= self._loop[1]:
            self._player.setPosition(self._loop[0])

    def _update_loop_timer(self) -> None:
        if self._loop is not None and self.is_playing:
            self._loop_timer.start()
        else:
            self._loop_timer.stop()

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.StoppedState and self._loop is not None:
            # Pętla z B na końcu nagrania: Qt zatrzymuje się na końcu pliku.
            self._player.setPosition(self._loop[0])
            self._player.play()
            return
        # Każda nowa pauza uzbraja auto-cofanie; przewinięcie je rozbraja.
        self._rewind_armed = state == QMediaPlayer.PlaybackState.PausedState
        self._update_loop_timer()
        self.playback_state_changed.emit(
            state == QMediaPlayer.PlaybackState.PlayingState
        )

    def _on_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self._last_error = ImportAudioError(
            user_message=tr(
                "player.error.read",
                reason=error_string or tr("player.error.unknown"),
            ),
            retry_hint=tr("player.error.read.hint"),
        )
        self.playback_error.emit(self._last_error)
