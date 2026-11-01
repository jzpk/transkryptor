"""Obiekt aplikacji: liczby dla bibliotek C w formacie niezależnym od języka."""

import locale

from transkryptor.audio.processing import AudioFilters, process_audio
from transkryptor.ui.application import Application

SAMPLE_MP3 = "tests/fixtures/audio/sample.mp3"


def test_numeric_locale_is_c_after_qt_start(qapp) -> None:
    assert isinstance(qapp, Application)
    assert locale.setlocale(locale.LC_NUMERIC) == "C"


def test_audio_filters_work_inside_qt_application(qapp, tmp_path) -> None:
    """FFmpeg czyta ``e=12.5`` poprawnie także przy polskim języku systemu."""
    target = tmp_path / "out.flac"
    process_audio(SAMPLE_MP3, target, AudioFilters(normalize=True, highpass=True))
    assert target.stat().st_size > 0
