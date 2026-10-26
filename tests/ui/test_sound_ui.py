"""Menu „Dźwięk” odtwarzacza: głośność i filtry odsłuchu w oknie."""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from transkryptor.audio.processing import CHANNEL_LEFT, AudioFilters
from transkryptor.settings import PlayerSettings, ReviewSettings, Settings
from transkryptor.ui import audio_filters
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")


@pytest.fixture
def audio(tmp_path) -> Path:
    target = tmp_path / "nagranie.mp3"
    shutil.copy(SAMPLE_MP3, target)
    return target


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    return add_window(MainWindow())


def load(window: MainWindow, qtbot, audio: Path) -> None:
    window._on_import_audio(str(audio))
    qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)


class TestSoundMenu:
    def test_menu_shows_saved_settings(self, window) -> None:
        current = window.settings_store.current
        window.settings_store.save(
            replace(
                current,
                player=replace(
                    current.player,
                    volume_pct=40,
                    normalize_audio=True,
                    audio_channel=CHANNEL_LEFT,
                ),
            )
        )
        menu = window.player_bar.sound_menu
        assert menu.volume_slider.value() == 40
        assert menu.volume_label.text() == "40%"
        assert menu.normalize_action.isChecked()
        assert not menu.highpass_action.isChecked()
        assert menu.channel == CHANNEL_LEFT
        assert window.player.volume == pytest.approx(0.4)

    def test_volume_changes_player_and_is_remembered(self, window) -> None:
        window.player_bar.sound_menu.volume_slider.setValue(25)
        assert window.player.volume == pytest.approx(0.25)
        assert window.settings_store.current.player.volume_pct == 25

    def test_filters_are_remembered(self, window) -> None:
        menu = window.player_bar.sound_menu
        menu.highpass_action.trigger()
        menu.channel_actions["right"].trigger()
        player = window.settings_store.current.player
        assert player.highpass_filter
        assert player.audio_channel == "right"
        assert window.audio_filters.filters == AudioFilters(
            highpass=True, channel="right"
        )

    def test_settings_dialog_keeps_sound_and_comment_author(self, window) -> None:
        settings = Settings(
            player=PlayerSettings(volume_pct=30, normalize_audio=True),
            review=ReviewSettings(comment_author="Anna"),
        )
        dialog = SettingsDialog(settings, window)
        result = dialog.settings()
        assert result.player.volume_pct == 30
        assert result.player.normalize_audio
        assert result.review.comment_author == "Anna"


class TestFilteredPlayback:
    def test_copy_is_prepared_and_played(
        self, qtbot, window, audio, isolated_playback_cache
    ) -> None:
        load(window, qtbot, audio)
        assert window.player.playback_path is None
        statuses: list[str] = []
        window.audio_filters.status_changed.connect(statuses.append)
        window.player_bar.sound_menu.normalize_action.trigger()
        qtbot.waitUntil(lambda: window.player.playback_path is not None, timeout=10000)
        path = window.player.playback_path
        assert path is not None
        assert path.parent == isolated_playback_cache
        assert path.suffix == ".flac"
        assert statuses[0].startswith("Przygotowanie dźwięku")
        assert statuses[-1] == ""
        assert window.player.source_path == audio

        # Wyłączenie filtrów wraca do oryginału; ponowne włączenie - z cache.
        window.player_bar.sound_menu.normalize_action.trigger()
        assert window.player.playback_path is None
        window.player_bar.sound_menu.normalize_action.trigger()
        assert window.player.playback_path == path
        assert not window.audio_filters.is_busy

    def test_new_recording_gets_its_own_copy(
        self, qtbot, window, audio, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(window.session, "_confirm_audio_change", lambda _path: True)
        load(window, qtbot, audio)
        window.player_bar.sound_menu.highpass_action.trigger()
        qtbot.waitUntil(lambda: window.player.playback_path is not None, timeout=10000)
        other = tmp_path / "drugie.mp3"
        shutil.copy(SAMPLE_MP3, other)
        first = window.player.playback_path
        load(window, qtbot, other)
        qtbot.waitUntil(lambda: window.player.playback_path is not None, timeout=10000)
        assert window.player.source_path == other
        assert window.player.playback_path != first

    def test_failure_keeps_original(self, qtbot, window, audio, monkeypatch) -> None:
        def broken(*_args, **_kwargs):
            raise OSError("brak miejsca")

        monkeypatch.setattr(audio_filters, "process_audio", broken)
        load(window, qtbot, audio)
        statuses: list[str] = []
        window.audio_filters.status_changed.connect(statuses.append)
        window.player_bar.sound_menu.normalize_action.trigger()
        qtbot.waitUntil(lambda: not window.audio_filters.is_busy, timeout=10000)
        assert window.player.playback_path is None
        assert (
            statuses[-1]
            == "Nie udało się zastosować filtrów - odtwarzany jest oryginał"
        )
        assert window.player_bar.sound_status_label.text() == statuses[-1]

    def test_without_filters_nothing_is_prepared(
        self, qtbot, window, audio, isolated_playback_cache
    ) -> None:
        load(window, qtbot, audio)
        assert not window.audio_filters.is_busy
        assert not isolated_playback_cache.exists()
