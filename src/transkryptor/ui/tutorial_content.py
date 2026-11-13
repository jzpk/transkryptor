"""Treść samouczków: lista przewodników i ich kroków.

Krok wskazuje element okna nazwą obiektu Qt (``objectName``) - pierwszą
widoczną z listy ``targets``; bez widocznego elementu karta kroku stoi na
środku okna. Teksty są w katalogach tłumaczeń pod kluczami
``tutorial.<samouczek>.<krok>.title`` / ``.text``. Pola ``{nazwa}`` w tekście
zastępuje bieżący skrót akcji z ``shortcuts`` (skróty da się zmienić
w ustawieniach, więc nie są wpisane na sztywno).

Nowy samouczek to wpis w ``TUTORIALS`` i teksty w obu katalogach.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from transkryptor.i18n import tr
from transkryptor.ui.shortcuts import (
    ADD_COMMENT_ID,
    MARK_VERIFIED_ID,
    NEXT_COMMENT_ID,
    NEXT_GAP_ID,
    NEXT_UNCERTAIN_ID,
    NEXT_UNVERIFIED_ID,
    PLAY_FROM_CURSOR,
    PLAY_PAUSE,
    PREVIOUS_GAP_ID,
    SUPERSCRIPT_ID,
    marker_id,
    player_id,
    project_id,
    search_id,
)

# Menu „Więcej poleceń” przejmuje przyciski paska w wąskim oknie.
MORE = "more_button"


@dataclass(frozen=True)
class TutorialStep:
    """Krok: klucz tekstów, wskazywane elementy i skróty wstawiane do tekstu."""

    key: str
    targets: tuple[str, ...] = ()
    # Pary (pole w tekście, identyfikator akcji z ``ui.shortcuts``).
    shortcuts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Tutorial:
    key: str
    steps: tuple[TutorialStep, ...]

    @property
    def title(self) -> str:
        return tr(f"tutorial.{self.key}.title")

    @property
    def summary(self) -> str:
        return tr(f"tutorial.{self.key}.summary")

    def step_title(self, index: int) -> str:
        return tr(f"tutorial.{self.key}.{self.steps[index].key}.title")

    def step_text(self, index: int, shortcut_text: Callable[[str], str]) -> str:
        """Opis kroku z bieżącymi skrótami (``shortcut_text(id akcji)``)."""
        step = self.steps[index]
        fields = {name: shortcut_text(action) for name, action in step.shortcuts}
        return tr(f"tutorial.{self.key}.{step.key}.text", **fields)


def _step(
    key: str, *targets: str, shortcuts: tuple[tuple[str, str], ...] = ()
) -> TutorialStep:
    return TutorialStep(key, targets, shortcuts)


FIRST_STEPS = "basics"
REVIEW = "review"
WORKFLOW = "workflow"

TUTORIALS: tuple[Tutorial, ...] = (
    Tutorial(
        FIRST_STEPS,
        (
            _step("welcome"),
            _step("player", "player_bar"),
            _step(
                "editor",
                "editor",
                shortcuts=(("play", player_id(PLAY_PAUSE)),),
            ),
            _step("notation", "toolbar_superscript", "main_toolbar"),
            _step("warnings", "warnings_panel", "warnings_card"),
            _step("asr", "toolbar_asr", MORE),
            _step("save", "toolbar_save", MORE),
            _step("export", "toolbar_export"),
            _step(
                "settings",
                "toolbar_settings",
                MORE,
                shortcuts=(("settings", project_id("settings")),),
            ),
            _step("help", "tutorial_button"),
        ),
    ),
    Tutorial(
        "player",
        (
            _step("import", "player_import_button", "player_bar"),
            _step(
                "play",
                "player_play_button",
                "player_bar",
                shortcuts=(("play", player_id(PLAY_PAUSE)),),
            ),
            _step("rate", "player_rate_combo", "player_bar"),
            _step("loop", "player_loop_button", "player_bar"),
            _step("waveform", "waveform_panel", "player_bar"),
            _step(
                "coverage",
                "coverage_label",
                "waveform_panel",
                "player_bar",
                shortcuts=(("next", NEXT_GAP_ID), ("previous", PREVIOUS_GAP_ID)),
            ),
            _step("spectrogram", "spectrogram_toggle", "waveform_panel", "player_bar"),
            _step("sound", "sound_button", "player_bar"),
            _step(
                "sync",
                "editor",
                shortcuts=(("from_cursor", player_id(PLAY_FROM_CURSOR)),),
            ),
        ),
    ),
    Tutorial(
        "notation",
        (
            _step(
                "superscript",
                "toolbar_superscript",
                "main_toolbar",
                shortcuts=(("superscript", SUPERSCRIPT_ID),),
            ),
            _step(
                "markers",
                "toolbar_marker_pause",
                "notation_more_button",
                shortcuts=(("pause", marker_id("pause")),),
            ),
            _step("snippets", "toolbar_snippets", "notation_more_button"),
            _step("warnings", "warnings_panel", "warnings_card"),
        ),
    ),
    Tutorial(
        "search",
        (
            _step(
                "search",
                "search_bar",
                "editor",
                shortcuts=(
                    ("find", search_id("find")),
                    ("next", search_id("find_next")),
                ),
            ),
            _step(
                "replace",
                "search_bar",
                "editor",
                shortcuts=(("replace", search_id("replace")),),
            ),
            _step("highlights", "toolbar_highlights", MORE),
            _step("pos", "toolbar_highlights", MORE),
            _step(
                "corpus",
                "toolbar_corpus",
                MORE,
                shortcuts=(("corpus", project_id("corpus")),),
            ),
        ),
    ),
    Tutorial(
        "asr",
        (
            _step("panel", "toolbar_asr", MORE),
            _step("model", "asr_model_step", "asr_panel"),
            _step("rules", "asr_rules_step", "asr_panel"),
            _step("draft", "asr_transcription_step", "asr_panel"),
            _step("clip", "asr_clip_only_check", "asr_panel"),
            _step("speakers", "asr_speakers_box", "asr_panel"),
            _step("qa", "asr_qa_layout_check", "asr_panel"),
            _step("questionnaire", "asr_questionnaire_button", "asr_panel"),
            _step("segments", "asr_segments_list", "asr_segments_toggle", "asr_panel"),
            _step(
                "review",
                "asr_review_list",
                "asr_review_toggle",
                "asr_panel",
                shortcuts=(("uncertain", NEXT_UNCERTAIN_ID),),
            ),
            _step("style", "toolbar_settings", MORE),
        ),
    ),
    Tutorial(
        REVIEW,
        (
            _step("intro"),
            _step("toggle", "toolbar_comments", MORE),
            _step(
                "comments",
                "comments_panel",
                shortcuts=(
                    ("add", ADD_COMMENT_ID),
                    ("next", NEXT_COMMENT_ID),
                ),
            ),
            _step("filter", "comments_filter", "comments_panel"),
            _step(
                "verification",
                "verification_button",
                "player_bar",
                shortcuts=(
                    ("mark", MARK_VERIFIED_ID),
                    ("next", NEXT_UNVERIFIED_ID),
                ),
            ),
            _step("compare", "toolbar_open", MORE),
            _step("readiness", "toolbar_export"),
        ),
    ),
    Tutorial(
        "project",
        (
            _step(
                "save",
                "toolbar_save",
                MORE,
                shortcuts=(("save", project_id("save")),),
            ),
            _step("open", "toolbar_open", MORE),
            _step("metadata", "metadata_form"),
            _step(
                "export",
                "toolbar_export",
                shortcuts=(("export", project_id("export")),),
            ),
            _step("status", "export_status_label"),
        ),
    ),
    Tutorial(
        WORKFLOW,
        (
            _step("intro"),
            _step("stats", "toolbar_export"),
            _step("goal", "daily_goal_label", "toolbar_settings", MORE),
            _step("snapshot", "toolbar_save", MORE),
            _step("history", "toolbar_save", MORE),
            _step("pack_export", "toolbar_export"),
            _step("pack_open", "toolbar_open", MORE),
        ),
    ),
)

TUTORIALS_BY_KEY: dict[str, Tutorial] = {
    tutorial.key: tutorial for tutorial in TUTORIALS
}
