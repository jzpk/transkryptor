"""Zapis szkicu ASR według ustawień (zgłoszenie #42)."""

from dataclasses import replace

import pytest

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_asr_page import AsrPage


@pytest.fixture
def window(add_window):
    window = add_window(MainWindow())
    for box in window.asr_panel.review.rule_checkboxes.values():
        box.setChecked(False)
    return window


def result(text: str) -> TranscriptionResult:
    segment = SegmentResult(0.0, 2.0, f" {text}", 0.9)
    return TranscriptionResult(text=text, language="pl", segments=(segment,))


def test_draft_has_abbreviations_spelled_out(window) -> None:
    window.asr.insert_draft(result("Ma tzw. myszkę, np. na ręce."))
    assert (
        window.editor.plain_text()
        == "[00:00] Ma tak zwaną myszkę, na przykład na ręce."
    )


def test_setting_keeps_abbreviations(window) -> None:
    current = window.settings_store.current
    window.settings_store.save(
        replace(current, asr=replace(current.asr, expand_abbreviations=False))
    )
    window.asr.insert_draft(result("np. kot"))
    assert window.editor.plain_text() == "[00:00] np. kot"


def test_settings_page_round_trip(qtbot, window) -> None:
    from transkryptor.asr.manager import ModelManager

    page = AsrPage(ModelManager())
    qtbot.addWidget(page)
    settings = window.settings_store.current
    page.load(settings)
    assert page.expand_abbreviations_check.isChecked()
    page.expand_abbreviations_check.setChecked(False)
    assert not page.apply(settings).asr.expand_abbreviations
