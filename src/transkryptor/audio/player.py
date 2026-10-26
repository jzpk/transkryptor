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
    # Podmiana pliku odsłuchu (filtry): None - oryginał, ścieżka - kopia.
    playback_file_changed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._player.setAudioOutput(self._output)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        # Przewinięcie zlecone, zanim nagranie się załadowało (np. pozycja
        # z projektu) - Qt by je zignorował, więc czeka na ``LoadedMedia``.
        self._pending_position: int | None = None
        self._source_path: Path | None = None
        self._last_error: ImportAudioError | None = None
        self._loop: tuple[int, int] | None = None
        # Pętla słowa (Ctrl+klik w niepewne słowo): niezależna od pętli A-B,
        # kończy ją pauza albo przewinięcie.
        self._temporary_loop: tuple[int, int] | None = None
        self._rewind_armed = False
        # Plik faktycznie odtwarzany zamiast ``_source_path`` (kopia
        # przefiltrowana, ``audio/processing.py``) albo None - oryginał.
        self._playback_path: Path | None = None
        # Trwa podmiana pliku odsłuchu: pozycja i stan wracają po załadowaniu,
        # a chwilowe zero czasu trwania i pozycji nie wychodzi poza odtwarzacz.
        self._swapping = False
        self._swap_loading = False
        self._resume_after_swap = False
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
    def playback_path(self) -> Path | None:
        """Przefiltrowana kopia odtwarzana zamiast oryginału albo None."""
        return self._playback_path

    @property
    def duration_ms(self) -> int:
        return self._player.duration()

    @property
    def position_ms(self) -> int:
        if self._swapping and self._pending_position is not None:
            return self._pending_position
        return self._player.position()

    @property
    def volume(self) -> float:
        """Głośność 0.0-1.0."""
        return self._output.volume()

    def set_volume(self, volume: float) -> None:
        self._output.setVolume(max(0.0, min(1.0, volume)))

    @property
    def playback_rate(self) -> float:
        return self._player.playbackRate()

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def loop_range(self) -> tuple[int, int] | None:
        """Aktywna pętla A-B (ms) albo None."""
        return self._loop

    @property
    def temporary_loop(self) -> tuple[int, int] | None:
        """Tymczasowa pętla fragmentu (ms) albo None."""
        return self._temporary_loop

    @property
    def can_auto_rewind(self) -> bool:
        """Czy wznowienie jest powrotem po pauzie w tym samym miejscu.

        Pierwszy start (stan zatrzymany) i przewinięcie w trakcie pauzy
        (suwak, skok, segment ASR) nie są wznowieniem - wtedy odtwarzanie
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
        self._temporary_loop = None
        self.clear_loop()
        self._rewind_armed = False
        self._pending_position = None
        self._end_swap()
        self._set_playback_path(None)
        self._player.setSource(QUrl.fromLocalFile(str(candidate.resolve())))
        self._source_path = candidate

    def set_playback_file(self, path: Path | None) -> None:
        """Odtwarza kopię nagrania (``path``) albo z powrotem oryginał (None).

        Kopia ma tę samą długość co oryginał: pozycja, pętla A-B, tempo
        i stan odtwarzania zostają. ``source_path`` nadal wskazuje oryginał.
        """
        if self._source_path is None or path == self._playback_path:
            return
        target = path if path is not None else self._source_path
        self._pending_position = self.position_ms
        self._resume_after_swap = self.is_playing or (
            self._swapping and self._resume_after_swap
        )
        self._swapping = True
        self._swap_loading = False
        self._temporary_loop = None
        self._set_playback_path(path)
        self._player.setSource(QUrl.fromLocalFile(str(target.resolve())))

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
        """Przewija do pozycji obciętej do zakresu nagrania.

        Przewinięcie kończy tymczasową pętlę fragmentu.
        """
        self._rewind_armed = False
        if self._temporary_loop is not None:
            self._temporary_loop = None
            self._update_loop_timer()
        position_ms = max(0, position_ms)
        if self.duration_ms > 0:
            position_ms = min(position_ms, self.duration_ms)
        if self._player.mediaStatus() == QMediaPlayer.MediaStatus.LoadingMedia:
            self._pending_position = position_ms
        self._player.setPosition(position_ms)

    def set_loop(self, start_ms: int, end_ms: int) -> None:
        """Włącza pętlę A-B; po dojściu do B odtwarzanie wraca do A."""
        duration = self.duration_ms
        if not (0 <= start_ms < end_ms) or (duration > 0 and end_ms > duration):
            raise ValueError(
                f"Nieprawidłowy zakres pętli {start_ms}-{end_ms} ms "
                f"(nagranie {duration} ms)."
            )
        self._loop = (start_ms, end_ms)
        self._update_loop_timer()
        self.loop_changed.emit(self._loop)

    def play_loop_once(self, start_ms: int, end_ms: int) -> None:
        """Odtwarza fragment w tymczasowej pętli (bez zmiany pętli A-B).

        Pętla trwa do pauzy albo przewinięcia.
        """
        start_ms = max(0, start_ms)
        if self.duration_ms > 0:
            end_ms = min(end_ms, self.duration_ms)
        if end_ms <= start_ms:
            return
        self.set_position(start_ms)
        self._temporary_loop = (start_ms, end_ms)
        self._update_loop_timer()
        self.play()

    def clear_loop(self) -> None:
        """Wyłącza pętlę A-B."""
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
        self._temporary_loop = None
        self._rewind_armed = False
        self._pending_position = None
        self._end_swap()
        self._set_playback_path(None)
        # Bez ``stop()``: pusty ``setSource`` sam zatrzymuje odtwarzanie, a
        # PySide6 zwalnia przy nim GIL (allow-thread). ``stop()`` wołany z GIL
        # potrafi się zakleszczyć z wątkiem ``QFFmpeg::AudioRenderer``, który
        # w ``~QObject`` trzyma mutex połączeń Qt i czeka na GIL.
        self._player.setSource(QUrl())
        self._source_path = None

    def _set_playback_path(self, path: Path | None) -> None:
        if path != self._playback_path:
            self._playback_path = path
            self.playback_file_changed.emit(path)

    def _end_swap(self) -> None:
        self._swapping = False
        self._swap_loading = False
        self._resume_after_swap = False

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._swapping:
            # Po zmianie źródła Qt potrafi jeszcze zgłosić ``LoadedMedia``
            # poprzedniego pliku - liczy się dopiero ładowanie nowego.
            if status == QMediaPlayer.MediaStatus.LoadingMedia:
                self._swap_loading = True
            if not self._swap_loading:
                return
        if status != QMediaPlayer.MediaStatus.LoadedMedia:
            return
        if self._pending_position is not None:
            position_ms, self._pending_position = self._pending_position, None
            self._player.setPosition(position_ms)
        if self._swapping:
            resume = self._resume_after_swap
            self._end_swap()
            if resume:
                self._player.play()

    def _on_duration_changed(self, duration_ms: int) -> None:
        # Podmiana pliku: chwilowe zero nie jest „brakiem nagrania”.
        if self._swapping and duration_ms <= 0:
            return
        self.duration_changed.emit(duration_ms)

    def _on_position_changed(self, position_ms: int) -> None:
        if self._swapping:
            return
        self.position_changed.emit(position_ms)
        self._check_loop(position_ms)

    def _check_loop(self, position_ms: int) -> None:
        loop = self._temporary_loop or self._loop
        if loop is not None and position_ms >= loop[1]:
            self._player.setPosition(loop[0])

    def _update_loop_timer(self) -> None:
        looping = self._loop is not None or self._temporary_loop is not None
        if looping and self.is_playing:
            self._loop_timer.start()
        else:
            self._loop_timer.stop()

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if self._swapping:
            # Zatrzymanie przy zmianie źródła - stan wróci po załadowaniu kopii.
            return
        if state == QMediaPlayer.PlaybackState.StoppedState and self._loop is not None:
            # Pętla z B na końcu nagrania: Qt zatrzymuje się na końcu pliku.
            self._player.setPosition(self._loop[0])
            self._player.play()
            return
        if state != QMediaPlayer.PlaybackState.PlayingState:
            self._temporary_loop = None
        # Każda nowa pauza uzbraja auto-cofanie; przewinięcie je rozbraja.
        self._rewind_armed = state == QMediaPlayer.PlaybackState.PausedState
        self._update_loop_timer()
        self.playback_state_changed.emit(
            state == QMediaPlayer.PlaybackState.PlayingState
        )

    def _on_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        if self._playback_path is not None:
            # Nie da się odtworzyć kopii: wraca oryginał, bez komunikatu.
            self.set_playback_file(None)
            return
        self._last_error = ImportAudioError(
            user_message=tr(
                "player.error.read",
                reason=error_string or tr("player.error.unknown"),
            ),
            retry_hint=tr("player.error.read.hint"),
        )
        self.playback_error.emit(self._last_error)
