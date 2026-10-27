"""Filtry odsłuchu: wzmocnienie cichych fragmentów, kanał i filtr szumu (bez Qt).

Qt Multimedia nie pozwala filtrować dźwięku w trakcie odtwarzania, więc
odtwarzacz dostaje kopię nagrania przetworzoną przez filtry FFmpeg (PyAV -
ta sama zależność co ASR i fala dźwiękowa):

- ``speechnorm`` - normalizacja mowy: ciche wypowiedzi (np. informatora
  daleko od mikrofonu) są wzmacniane, głośne - nie;
- ``pan`` - jeden kanał nagrania stereo (lewy albo prawy mikrofon);
- ``highpass`` - tłumienie dudnienia, szumu wiatru i brumu sieci.

Filtry nie zmieniają długości nagrania, więc czasy (pozycja, kotwice tekstu,
pętla A-B) pasują do oryginału. Kopia jest bezstratna (FLAC) i trafia do
katalogu pamięci podręcznej pod kluczem z pliku i zestawu filtrów;
zostaje tylko kilka ostatnio używanych kopii. Oryginał nigdy nie jest
zmieniany, a ASR i eksport korzystają z oryginału.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transkryptor.paths import user_cache_dir

CHANNEL_BOTH = "both"
CHANNEL_LEFT = "left"
CHANNEL_RIGHT = "right"
CHANNELS = (CHANNEL_BOTH, CHANNEL_LEFT, CHANNEL_RIGHT)

# Umiarkowane i powolne wzmocnienie (przykład z dokumentacji FFmpeg): mowa
# nie „pompuje”, a cichy głos zbliża się do głośnego.
SPEECHNORM_ARGS = "e=12.5:r=0.0001:l=1"
HIGHPASS_HZ = 100
# Wersja przetwarzania w kluczu cache - zmiana parametrów unieważnia kopie.
_VERSION = 1
# Tyle ostatnio użytych kopii zostaje w cache (każda to bezstratny FLAC).
CACHE_KEEP = 3

# Domyślny układ dla nagrań bez opisu kanałów (np. WAV z rejestratora bez
# maski kanałów, „2 channels”): filtry FFmpeg wybierają kanały po układzie
# i bez niego przepuszczają dźwięk bez zmian.
DEFAULT_LAYOUTS = {
    1: "mono",
    2: "stereo",
    3: "3.0",
    4: "quad",
    5: "5.0",
    6: "5.1",
    7: "6.1",
    8: "7.1",
}

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[float], None]


@dataclass(frozen=True)
class AudioFilters:
    """Zestaw filtrów odsłuchu; bez żadnego filtru odtwarzany jest oryginał."""

    normalize: bool = False
    channel: str = CHANNEL_BOTH
    highpass: bool = False

    @property
    def active(self) -> bool:
        return self.normalize or self.highpass or self.channel != CHANNEL_BOTH

    def chain(self, channels: int) -> list[tuple[str, str]]:
        """Filtry FFmpeg (nazwa, argumenty) dla nagrania o ``channels`` kanałach.

        Wybór kanału nagrania mono nic nie zmienia, więc jest pomijany.
        """
        chain: list[tuple[str, str]] = []
        if self.channel != CHANNEL_BOTH and channels > 1:
            source = "FL" if self.channel == CHANNEL_LEFT else "FR"
            chain.append(("pan", f"mono|c0={source}"))
        if self.highpass:
            chain.append(("highpass", f"f={HIGHPASS_HZ}"))
        if self.normalize:
            chain.append(("speechnorm", SPEECHNORM_ARGS))
        return chain

    @property
    def key(self) -> str:
        return (
            f"v{_VERSION}-n{int(self.normalize)}-c{self.channel}-h{int(self.highpass)}"
        )


def playback_cache_dir() -> Path:
    return user_cache_dir() / "playback"


def cache_path(source: str | Path, filters: AudioFilters, directory: Path) -> Path:
    """Plik kopii dla nagrania (ścieżka, rozmiar, czas zmiany) i filtrów.

    Klucz nie wymaga sumy SHA-256 - kopia jest gotowa bez czytania całego
    pliku, a zmieniony plik (inny rozmiar lub czas) dostaje nową kopię.
    """
    path = Path(source).resolve()
    info = path.stat()
    raw = f"{path}\0{info.st_size}\0{info.st_mtime_ns}\0{filters.key}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return directory / f"{digest}.flac"


def process_audio(
    source: str | Path,
    target: Path,
    filters: AudioFilters,
    should_cancel: CancelCheck | None = None,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Zapisuje przefiltrowaną kopię nagrania jako FLAC (atomowo).

    ``should_cancel`` przerywa przetwarzanie (``InterruptedError``); błąd
    odczytu albo zapisu - ``OSError`` lub wyjątek PyAV (``av.FFmpegError``).
    Częściowy plik nigdy nie zostaje pod nazwą docelową.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.stem}.", suffix=".flac", delete=False
    ) as handle:
        temp = Path(handle.name)
    try:
        _process(Path(source), temp, filters, should_cancel, on_progress)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def _process(
    source: Path,
    target: Path,
    filters: AudioFilters,
    should_cancel: CancelCheck | None,
    on_progress: ProgressCallback | None,
) -> None:
    import av

    cancel = should_cancel or (lambda: False)
    with av.open(str(source)) as container:
        stream = container.streams.audio[0]
        duration_s = (
            container.duration / av.time_base if container.duration else 0.0
        ) or float((stream.duration or 0) * (stream.time_base or 0))
        layout = stream.codec_context.layout
        channels = len(layout.channels)
        chain = filters.chain(channels)
        if layout.name.endswith(" channels") and channels in DEFAULT_LAYOUTS:
            chain.insert(0, ("aformat", f"channel_layouts={DEFAULT_LAYOUTS[channels]}"))
        chain.append(("aformat", "sample_fmts=s16"))
        graph = av.filter.Graph()
        nodes: list[Any] = [graph.add_abuffer(template=stream)]
        for name, args in chain:
            nodes.append(graph.add(name, args))
        nodes.append(graph.add("abuffersink"))
        for upstream, downstream in zip(nodes, nodes[1:], strict=False):
            upstream.link_to(downstream)
        graph.configure()
        with av.open(str(target), "w", format="flac") as output:
            encoder: Any = None

            def drain() -> None:
                nonlocal encoder
                while True:
                    try:
                        frame = graph.pull()
                    except (av.error.BlockingIOError, av.error.EOFError):
                        return
                    if not isinstance(frame, av.AudioFrame):
                        raise TypeError(f"unexpected filter output: {frame!r}")
                    if encoder is None:
                        encoder = output.add_stream(
                            "flac", rate=frame.sample_rate, layout=frame.layout.name
                        )
                    frame.pts = None
                    for packet in encoder.encode(frame):
                        output.mux(packet)

            for frame in container.decode(stream):
                if cancel():
                    raise InterruptedError(str(source))
                graph.push(frame)
                drain()
                if on_progress is not None and duration_s > 0 and frame.time:
                    on_progress(min(1.0, float(frame.time) / duration_s))
            graph.push(None)
            drain()
            if encoder is not None:
                for packet in encoder.encode(None):
                    output.mux(packet)


def prune_cache(
    directory: Path, keep: Path | None = None, limit: int = CACHE_KEEP
) -> None:
    """Zostawia ``limit`` ostatnio użytych kopii (i zawsze ``keep``)."""
    try:
        files = sorted(
            directory.glob("*.flac"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for index, path in enumerate(files):
        if index >= limit and path != keep:
            path.unlink(missing_ok=True)


def touch(path: Path) -> None:
    """Oznacza kopię jako użytą (kolejność usuwania z cache)."""
    with contextlib.suppress(OSError):
        os.utime(path)
