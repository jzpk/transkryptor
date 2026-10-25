"""Skróty klawiaturowe: wartości domyślne, nadpisania i wykrywanie konfliktów.

Jedno źródło prawdy dla ``MainWindow`` (akcje), ``PlayerBar`` (podpowiedzi
przycisków), instrukcji i testów - wzorem ``ui/markers.py``. Rejestr
``SHORTCUT_ACTIONS`` obejmuje markery i indeks górny, odtwarzacz,
wyszukiwanie oraz akcje projektu; użytkownik nadpisuje skróty w ustawieniach
(``ShortcutSettings``), a :func:`effective_shortcuts` składa domyślne
z nadpisaniami. :func:`find_conflicts` wykrywa skróty przypisane kilku
akcjom albo zajęte przez standardową edycję tekstu (kopiuj, cofnij, skok
o słowo…).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from PySide6.QtGui import QAction, QKeySequence

from transkryptor.i18n import tr
from transkryptor.ui.markers import MARKERS, SUPERSCRIPT_SHORTCUT


@dataclass(frozen=True)
class PlayerAction:
    """Akcja odtwarzacza dostępna z klawiatury przy fokusie w edytorze."""

    key: str
    label_key: str
    shortcuts: tuple[str, ...]

    @property
    def label(self) -> str:
        return tr(self.label_key)


SETTINGS_SHORTCUT = "Ctrl+,"
NEW_SHORTCUT = "Ctrl+N"
OPEN_PROJECT_SHORTCUT = "Ctrl+O"
SAVE_PROJECT_SHORTCUT = "Ctrl+S"
SAVE_PROJECT_AS_SHORTCUT = "Ctrl+Shift+S"
EXPORT_SHORTCUT = "Ctrl+E"
CLOSE_SHORTCUT = "Ctrl+W"

# Wyszukiwanie i zamiana (faza 07). Esc zamyka pasek - tylko z fokusem w pasku.
FIND_SHORTCUT = "Ctrl+F"
REPLACE_SHORTCUT = "Ctrl+H"
FIND_NEXT_SHORTCUT = "F3"
FIND_PREVIOUS_SHORTCUT = "Shift+F3"

PLAY_PAUSE = "play_pause"
SKIP_BACK = "skip_back"
SKIP_FORWARD = "skip_forward"
RATE_DOWN = "rate_down"
RATE_UP = "rate_up"
LOOP_A = "loop_a"
LOOP_B = "loop_b"
LOOP_TOGGLE = "loop_toggle"
PLAY_FROM_CURSOR = "play_from_cursor"
INSERT_TIMESTAMP = "insert_timestamp"

# Ctrl+←/→ zostaje dla skoku o słowo w edytorze. F4 jest zapasowe dla
# Ctrl+Spacja, które na Linuksie bywa przechwytywane przez metodę wprowadzania.
PLAYER_ACTIONS: tuple[PlayerAction, ...] = (
    PlayerAction(PLAY_PAUSE, "player.action.play_pause", ("Ctrl+Space", "F4")),
    PlayerAction(SKIP_BACK, "player.action.skip_back", ("Alt+Left",)),
    PlayerAction(SKIP_FORWARD, "player.action.skip_forward", ("Alt+Right",)),
    PlayerAction(RATE_DOWN, "player.action.rate_down", ("Ctrl+Shift+,",)),
    PlayerAction(RATE_UP, "player.action.rate_up", ("Ctrl+Shift+.",)),
    PlayerAction(LOOP_A, "player.action.loop_a", ("Ctrl+Shift+A",)),
    PlayerAction(LOOP_B, "player.action.loop_b", ("Ctrl+Shift+B",)),
    PlayerAction(LOOP_TOGGLE, "player.action.loop_toggle", ("Ctrl+Shift+L",)),
    # Faza 11: tekst powiązany z nagraniem (kotwice czasowe).
    PlayerAction(
        PLAY_FROM_CURSOR, "player.action.play_from_cursor", ("Ctrl+Shift+Space",)
    ),
    PlayerAction(INSERT_TIMESTAMP, "player.action.insert_timestamp", ("Ctrl+Shift+T",)),
)

PLAYER_ACTIONS_BY_KEY: dict[str, PlayerAction] = {
    action.key: action for action in PLAYER_ACTIONS
}


def native_shortcut(shortcut: str) -> str:
    """Skrót w zapisie właściwym dla systemu (np. „Ctrl+Spacja”)."""
    return QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)


def tooltip_with_shortcut(text: str, *shortcuts: str) -> str:
    """Podpowiedź z dopisanymi skrótami, np. „Odtwórz  (Ctrl+Space, F4)”."""
    if not shortcuts:
        return text
    return f"{text}  ({', '.join(native_shortcut(s) for s in shortcuts)})"


def action_tooltip(
    key: str, text: str | None = None, shortcuts: tuple[str, ...] | None = None
) -> str:
    """Podpowiedź przycisku odtwarzacza z jego skrótami (domyślnymi lub podanymi)."""
    action = PLAYER_ACTIONS_BY_KEY[key]
    sequences = action.shortcuts if shortcuts is None else shortcuts
    return tooltip_with_shortcut(text or action.label, *sequences)


# --- rejestr konfigurowalnych skrótów (propozycja 21) -------------------------

GROUP_NOTATION = "notation"
GROUP_PLAYER = "player"
GROUP_SEARCH = "search"
GROUP_PROJECT = "project"
GROUP_SNIPPETS = "snippets"
GROUP_SPEAKERS = "speakers"
GROUP_REVIEW = "review"

SUPERSCRIPT_ID = "superscript"
SNIPPET_PREFIX = "snippet."
# Podpowiedź akcji bez skrótów - po zmianie skrótu podpowiedź jest składana
# od nowa z tego tekstu (dynamiczna właściwość ``QAction``).
BASE_TOOLTIP = "base_tooltip"


@dataclass(frozen=True)
class ShortcutDef:
    """Akcja ze skrótami konfigurowalnymi w ustawieniach."""

    id: str
    label_key: str
    defaults: tuple[str, ...]
    group: str
    # Numer w etykiecie („Mówca 2”) - akcje numerowane jak przypisanie mówcy.
    number: int | None = None

    @property
    def label(self) -> str:
        if self.number is not None:
            return tr(self.label_key, number=self.number)
        return tr(self.label_key)


def marker_id(key: str) -> str:
    return f"marker.{key}"


def player_id(key: str) -> str:
    return f"player.{key}"


def search_id(key: str) -> str:
    return f"search.{key}"


def project_id(key: str) -> str:
    return f"project.{key}"


# Mówcy (faza 12): n-ty mówca z listy dokumentu i usunięcie mówcy akapitu.
SPEAKER_COUNT = 9
SPEAKER_CLEAR_ID = "speaker.clear"
# Recenzja (faza 14): komentarz do zaznaczenia, jak w Wordzie.
ADD_COMMENT_ID = "review.add_comment"


def speaker_id(number: int) -> str:
    return f"speaker.{number}"


SHORTCUT_ACTIONS: tuple[ShortcutDef, ...] = (
    ShortcutDef(
        SUPERSCRIPT_ID, "toolbar.superscript", (SUPERSCRIPT_SHORTCUT,), GROUP_NOTATION
    ),
    *(
        ShortcutDef(
            marker_id(marker.key),
            marker.label_key,
            (marker.shortcut,),
            GROUP_NOTATION,
        )
        for marker in MARKERS
    ),
    *(
        ShortcutDef(player_id(a.key), a.label_key, a.shortcuts, GROUP_PLAYER)
        for a in PLAYER_ACTIONS
    ),
    ShortcutDef(
        search_id("find"), "search.action.find", (FIND_SHORTCUT,), GROUP_SEARCH
    ),
    ShortcutDef(
        search_id("replace"),
        "search.action.replace",
        (REPLACE_SHORTCUT,),
        GROUP_SEARCH,
    ),
    ShortcutDef(
        search_id("find_next"),
        "search.action.next",
        (FIND_NEXT_SHORTCUT,),
        GROUP_SEARCH,
    ),
    ShortcutDef(
        search_id("find_previous"),
        "search.action.previous",
        (FIND_PREVIOUS_SHORTCUT,),
        GROUP_SEARCH,
    ),
    ShortcutDef(project_id("new"), "toolbar.new", (NEW_SHORTCUT,), GROUP_PROJECT),
    ShortcutDef(
        project_id("open"), "toolbar.open", (OPEN_PROJECT_SHORTCUT,), GROUP_PROJECT
    ),
    ShortcutDef(
        project_id("save"), "toolbar.save", (SAVE_PROJECT_SHORTCUT,), GROUP_PROJECT
    ),
    ShortcutDef(
        project_id("save_as"),
        "toolbar.save_as",
        (SAVE_PROJECT_AS_SHORTCUT,),
        GROUP_PROJECT,
    ),
    ShortcutDef(
        project_id("export"), "toolbar.export", (EXPORT_SHORTCUT,), GROUP_PROJECT
    ),
    ShortcutDef(
        project_id("settings"), "toolbar.settings", (SETTINGS_SHORTCUT,), GROUP_PROJECT
    ),
    ShortcutDef(project_id("close"), "toolbar.close", (CLOSE_SHORTCUT,), GROUP_PROJECT),
    *(
        ShortcutDef(
            speaker_id(number),
            "speakers.action.assign",
            (f"Alt+Shift+{number}",),
            GROUP_SPEAKERS,
            number,
        )
        for number in range(1, SPEAKER_COUNT + 1)
    ),
    ShortcutDef(
        SPEAKER_CLEAR_ID, "speakers.action.clear", ("Alt+Shift+0",), GROUP_SPEAKERS
    ),
    ShortcutDef(ADD_COMMENT_ID, "comments.action.add", ("Ctrl+Alt+M",), GROUP_REVIEW),
)

SHORTCUT_ACTIONS_BY_ID: dict[str, ShortcutDef] = {d.id: d for d in SHORTCUT_ACTIONS}


def normalized(sequence: str) -> str:
    """Zapis skrótu niezależny od systemu i pisowni (``ctrl+n`` → ``Ctrl+N``)."""
    return QKeySequence(sequence).toString(QKeySequence.SequenceFormat.PortableText)


def effective_shortcuts(
    overrides: Mapping[str, Iterable[str]],
) -> dict[str, tuple[str, ...]]:
    """Skróty wszystkich akcji: domyślne z nadpisaniami (pusta lista = brak)."""
    result: dict[str, tuple[str, ...]] = {}
    for definition in SHORTCUT_ACTIONS:
        if definition.id in overrides:
            result[definition.id] = tuple(
                normalized(s) for s in overrides[definition.id] if normalized(s)
            )
        else:
            result[definition.id] = definition.defaults
    return result


def shortcut_overrides(
    mapping: Mapping[str, Iterable[str]],
) -> dict[str, list[str]]:
    """Nadpisania do zapisu: tylko akcje ze skrótami innymi niż domyślne."""
    overrides: dict[str, list[str]] = {}
    for definition in SHORTCUT_ACTIONS:
        if definition.id not in mapping:
            continue
        wanted = [normalized(s) for s in mapping[definition.id] if normalized(s)]
        if wanted != [normalized(s) for s in definition.defaults]:
            overrides[definition.id] = wanted
    return overrides


@dataclass(frozen=True)
class Conflict:
    """Skrót przypisany kilku akcjom albo zajęty przez edycję tekstu."""

    sequence: str
    owners: tuple[str, ...]  # identyfikatory akcji
    standard: str = ""  # nazwa standardowego skrótu edycji tekstu

    @property
    def message(self) -> str:
        names = ", ".join(action_label(owner) for owner in self.owners)
        if self.standard:
            return tr(
                "shortcuts.conflict.standard",
                shortcut=native_shortcut(self.sequence),
                actions=names,
                standard=tr(f"shortcuts.standard.{self.standard}"),
            )
        return tr(
            "shortcuts.conflict",
            shortcut=native_shortcut(self.sequence),
            actions=names,
        )


# Skróty edycji tekstu, których nie wolno przejąć: działają w edytorze.
_STANDARD_EDITING = (
    ("copy", QKeySequence.StandardKey.Copy),
    ("cut", QKeySequence.StandardKey.Cut),
    ("paste", QKeySequence.StandardKey.Paste),
    ("undo", QKeySequence.StandardKey.Undo),
    ("redo", QKeySequence.StandardKey.Redo),
    ("select_all", QKeySequence.StandardKey.SelectAll),
    ("next_word", QKeySequence.StandardKey.MoveToNextWord),
    ("previous_word", QKeySequence.StandardKey.MoveToPreviousWord),
    ("select_next_word", QKeySequence.StandardKey.SelectNextWord),
    ("select_previous_word", QKeySequence.StandardKey.SelectPreviousWord),
    ("delete_start_of_word", QKeySequence.StandardKey.DeleteStartOfWord),
    ("delete_end_of_word", QKeySequence.StandardKey.DeleteEndOfWord),
    ("start_of_document", QKeySequence.StandardKey.MoveToStartOfDocument),
    ("end_of_document", QKeySequence.StandardKey.MoveToEndOfDocument),
)


def standard_editing_shortcuts() -> dict[str, str]:
    """Skrót (zapis przenośny) → nazwa standardowej czynności edycji."""
    result: dict[str, str] = {}
    for name, key in _STANDARD_EDITING:
        for binding in QKeySequence.keyBindings(key):
            text = binding.toString(QKeySequence.SequenceFormat.PortableText)
            if text:
                result.setdefault(text, name)
    return result


def find_conflicts(mapping: Mapping[str, Iterable[str]]) -> list[Conflict]:
    """Konflikty w przypisaniu ``identyfikator akcji → skróty``."""
    owners: dict[str, list[str]] = {}
    for action_id, sequences in mapping.items():
        for sequence in sequences:
            key = normalized(sequence)
            if key and action_id not in owners.setdefault(key, []):
                owners[key].append(action_id)
    standard = standard_editing_shortcuts()
    conflicts: list[Conflict] = []
    for sequence, ids in owners.items():
        if sequence in standard:
            conflicts.append(Conflict(sequence, tuple(ids), standard[sequence]))
        elif len(ids) > 1:
            conflicts.append(Conflict(sequence, tuple(ids)))
    return conflicts


def action_label(action_id: str) -> str:
    """Nazwa akcji do komunikatów (także wstawek ``snippet.N``)."""
    definition = SHORTCUT_ACTIONS_BY_ID.get(action_id)
    if definition is not None:
        return definition.label
    if action_id.startswith(SNIPPET_PREFIX):
        return tr("shortcuts.snippet", number=action_id.removeprefix(SNIPPET_PREFIX))
    return action_id


def set_base_tooltip(action: QAction, tooltip: str) -> None:
    """Zapamiętuje podpowiedź bez skrótów i ustawia ją ze skrótami akcji."""
    action.setProperty(BASE_TOOLTIP, tooltip)
    sequences = [
        s.toString(QKeySequence.SequenceFormat.PortableText) for s in action.shortcuts()
    ]
    action.setToolTip(tooltip_with_shortcut(tooltip, *sequences))


def apply_shortcuts(action: QAction, sequences: Iterable[str]) -> None:
    """Ustawia skróty akcji i odświeża jej podpowiedź (bez restartu)."""
    sequences = tuple(sequences)
    action.setShortcuts([QKeySequence(s) for s in sequences])
    base = action.property(BASE_TOOLTIP)
    if isinstance(base, str) and base:
        action.setToolTip(tooltip_with_shortcut(base, *sequences))
