"""Blokada okna na czas transkrypcji: polecenia, które zmieniają tekst albo projekt.

Okno głównie wyłącza panel ASR, paski narzędzi i akcje edycji, a kontrolery
z własnymi przyciskami dostają ``set_locked``. Nowe polecenie, które nie może
działać w trakcie transkrypcji, dopisuje się tutaj, a nie w ``MainWindow``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QToolBar

from transkryptor.ui.shortcuts import MARK_VERIFIED_ID, NEXT_UNVERIFIED_ID

if TYPE_CHECKING:
    from transkryptor.ui.main_window import MainWindow


def lock_window(window: MainWindow, locked: bool) -> None:
    """Wyłącza (``locked``) albo przywraca polecenia okna."""
    window._central.setEnabled(not locked)
    window.asr_panel.setEnabled(not locked)
    for toolbar in window.findChildren(QToolBar):
        toolbar.setEnabled(not locked)
    for action in (
        window.superscript_action,
        *window.marker_actions.values(),
        window.new_action,
        window.open_action,
        window.save_action,
        window.save_as_action,
        window.import_docx_action,
        window.compare_action,
        window.corpus_action,
        window.comments.add_action,
        *(
            action
            for action_id, action in window.review_actions.items()
            if action_id not in (MARK_VERIFIED_ID, NEXT_UNVERIFIED_ID)
        ),
        window.export_action,
        window.export_anonymized_action,
        window.export_as_action,
        window.readiness_action,
        window.settings_action,
        window.unify_ellipses_action,
        *window.search_actions.values(),
        *window.snapshots.actions,
        window.progress.stats_action,
    ):
        action.setEnabled(not locked)
    window.player_controller.set_locked(locked)
    window.snippets.set_locked(locked)
    window.speakers.set_locked(locked)
    window.verification.set_locked(locked)
    window.corpus.set_locked(locked)
    window.learning.set_locked(locked)
    window.packs.set_locked(locked)
    window.series.set_locked(locked)
    window.coverage.set_locked(locked)
    window.profiles.set_locked(locked)
    window.analysis.set_locked(locked)
