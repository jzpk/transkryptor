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
    NEXT_UNCERTAIN_ID,
    NEXT_UNVERIFIED_ID,
    PLAY_FROM_CURSOR,
    PLAY_PAUSE,
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
            _step("warnings", "warnings_panel"),
            _step("asr", "toolbar_asr", MORE),
            _step("save", "toolbar_save", MORE),
            _step("export", "toolbar_export"),
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
            _step("warnings", "warnings_panel"),
            _step("metadata", "metadata_form"),
            _step(
                "search",
                "search_bar",
                "editor",
                shortcuts=(("find", search_id("find")),),
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
            _step("segments", "asr_segments_list", "asr_panel"),
            _step(
                "review",
                "asr_review_list",
                "asr_panel",
                shortcuts=(("uncertain", NEXT_UNCERTAIN_ID),),
            ),
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
            _step(
                "export",
                "toolbar_export",
                shortcuts=(("export", project_id("export")),),
            ),
            _step("status", "export_status_label"),
            _step(
                "corpus",
                "toolbar_corpus",
                MORE,
                shortcuts=(("corpus", project_id("corpus")),),
            ),
            _step(
                "settings",
                "toolbar_settings",
                MORE,
                shortcuts=(("settings", project_id("settings")),),
            ),
        ),
    ),
)

TUTORIALS_BY_KEY: dict[str, Tutorial] = {
    tutorial.key: tutorial for tutorial in TUTORIALS
}
