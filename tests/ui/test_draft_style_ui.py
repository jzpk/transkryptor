"""Zapis szkicu ASR według ustawień (zgłoszenia #42 i #37)."""

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


def set_asr(window, **changes) -> None:
    current = window.settings_store.current
    window.settings_store.save(replace(current, asr=replace(current.asr, **changes)))


def test_default_draft_is_spelled_out_lowercase_and_plain(window) -> None:
    window.asr.insert_draft(
        result("Ma tzw. myszkę, np. na ręce. Kasia mówi: co to? Nie wiem...")
    )
    assert window.editor.plain_text() == (
        "[00:00] ma tak zwaną myszkę na przykład na ręce Kasia mówi co to?"
        " nie wiem…"  # wielokropek w stylu z ustawień notacji
    )


def test_settings_keep_model_spelling(window) -> None:
    set_asr(window, expand_abbreviations=False, lowercase_plain=False)
    window.asr.insert_draft(result("Np. kot, pies."))
    assert window.editor.plain_text() == "[00:00] Np. kot, pies."


def test_abbreviations_without_plain_style(window) -> None:
    set_asr(window, lowercase_plain=False)
    window.asr.insert_draft(result("Ma tzw. myszkę."))
    assert window.editor.plain_text() == "[00:00] Ma tak zwaną myszkę."


def test_settings_page_round_trip(qtbot, window) -> None:
    from transkryptor.asr.manager import ModelManager

    page = AsrPage(ModelManager())
    qtbot.addWidget(page)
    settings = window.settings_store.current
    page.load(settings)
    assert page.expand_abbreviations_check.isChecked()
    assert page.lowercase_plain_check.isChecked()
    page.expand_abbreviations_check.setChecked(False)
    page.lowercase_plain_check.setChecked(False)
    applied = page.apply(settings).asr
    assert not applied.expand_abbreviations
    assert not applied.lowercase_plain
