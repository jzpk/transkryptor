"""Strony okna wniosków z poprawek poza regułami (zgłoszenie #74).

- **Słowa poprawiane w całości** - kandydaci do słownika ASR (projektu albo
  globalnego), z oznaczeniem słów, które już w nim są;
- **Wstawki i wtrącenia** - słowa dopisane przez transkrybenta (model je
  pominął) i usunięte (model je dodał), z podpowiedzią „Zapisu dosłownego”;
- **Interpunkcja i wielka litera** - podpowiedzi ustawień „Zapisu szkicu”;
- **Mówcy** - akapity ze zmienionym mówcą (bez akcji: ocena podziału).

Przycisk akcji jest tylko tam, gdzie program ma odpowiedni mechanizm; strony
ogłaszają go sygnałami, a wykonuje kontroler.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.notation.draft_insights import Punctuation, Repeated, SpeakerEdit
from transkryptor.ui.corpus_table import table_widget
from transkryptor.ui.insights_common import context, fill_table
from transkryptor.ui.theme import set_props

VERBATIM = "verbatim"
PLAIN = "lowercase_plain"
EXPAND = "expand_abbreviations"


def _label(text: str = "", role: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if role:
        set_props(label, role=role)
    return label


def _setting_button(name: str) -> QPushButton:
    button = QPushButton(tr(f"insights.setting.{name}"))
    button.setObjectName(f"insights_setting_{name}")
    return button


class WordsPage(QWidget):
    """Wymiany całych słów i dodanie ich do słownika ASR."""

    add_requested = Signal(list, bool)  # słowa, do słownika globalnego

    def __init__(
        self, project_vocabulary: bool = True, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._words: list[Repeated] = []
        self._known: frozenset[str] = frozenset()
        self.hint = _label(tr("insights.words.hint"), role="status")
        set_props(self.hint, tone="accent")
        columns = ["asr", "fixed", "count", "kind"]
        if not project_vocabulary:
            columns.insert(3, "projects")
        self._columns = columns
        self.table = table_widget(
            [tr(f"insights.words.column.{name}") for name in columns]
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.project_radio = QRadioButton(tr("insights.words.project"))
        self.global_radio = QRadioButton(tr("insights.words.global"))
        group = QButtonGroup(self)
        group.addButton(self.project_radio)
        group.addButton(self.global_radio)
        (self.project_radio if project_vocabulary else self.global_radio).setChecked(
            True
        )
        self.project_radio.setVisible(project_vocabulary)
        self.add_button = QPushButton(tr("insights.words.add"))
        self.add_button.setObjectName("insights_add_words")
        self.add_button.clicked.connect(self._add)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("insights.words.target")))
        row.addWidget(self.project_radio)
        row.addWidget(self.global_radio)
        row.addStretch(1)
        row.addWidget(self.add_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(row)

    def set_words(self, words: Sequence[Repeated], known: Collection[str]) -> None:
        """Wymiany słów i hasła, które już są w słowniku (casefold)."""
        self._words, self._known = list(words), frozenset(w.casefold() for w in known)
        rows = []
        for item in self._words:
            values: dict[str, object] = {
                "asr": item.original,
                "fixed": item.corrected,
                "count": item.count,
                "projects": item.projects,
                "kind": self._kind(item),
            }
            rows.append([values[name] for name in self._columns])
        fill_table(self.table, rows)
        self.add_button.setEnabled(bool(self._words))

    def _kind(self, item: Repeated) -> str:
        if item.corrected.casefold() in self._known:
            return tr("insights.words.known")
        if item.corrected[:1].isupper():
            return tr("insights.words.proper")
        return tr("insights.words.dialect")

    def selected_words(self) -> list[str]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        chosen = [self._words[row] for row in rows] or self._words
        return [
            item.corrected
            for item in chosen
            if item.corrected.casefold() not in self._known
        ]

    def _add(self) -> None:
        words = self.selected_words()
        if words:
            self.add_requested.emit(words, self.global_radio.isChecked())


class FillersPage(QWidget):
    """Wstawki dopisane i usunięte, z podpowiedzią zapisu dosłownego."""

    setting_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hint = _label(role="status")
        set_props(self.hint, tone="accent")
        self.verbatim_button = _setting_button(VERBATIM)
        self.verbatim_button.clicked.connect(
            lambda: self.setting_requested.emit(VERBATIM)
        )
        top = QHBoxLayout()
        top.addWidget(self.hint, stretch=1)
        top.addWidget(self.verbatim_button)
        self.added_table = table_widget(
            [
                tr("insights.fillers.text"),
                tr("insights.fillers.count"),
                tr("insights.fillers.example"),
            ]
        )
        self.removed_table = table_widget(
            [
                tr("insights.fillers.text"),
                tr("insights.fillers.count"),
                tr("insights.fillers.example"),
            ]
        )
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(_label(tr("insights.fillers.added"), role="title"))
        layout.addWidget(self.added_table, stretch=1)
        layout.addWidget(_label(tr("insights.fillers.removed"), role="title"))
        layout.addWidget(self.removed_table, stretch=1)

    def set_fillers(
        self,
        added: Sequence[Repeated],
        removed: Sequence[Repeated],
        text: str,
        total_added: int,
        suggest: bool,
    ) -> None:
        self.hint.setText(
            tr(
                "insights.fillers.suggest" if suggest else "insights.fillers.hint",
                count=total_added,
            )
        )
        self.verbatim_button.setVisible(suggest)
        fill_table(
            self.added_table,
            [(i.corrected, i.count, context(text, i.positions[0])) for i in added],
        )
        fill_table(
            self.removed_table,
            [(i.original, i.count, context(text, i.positions[0])) for i in removed],
        )


class PunctuationPage(QWidget):
    """Interpunkcja, wielka litera i skróty - podpowiedzi zapisu szkicu."""

    setting_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plain_label = _label(role="")
        self.plain_button = _setting_button(PLAIN)
        self.plain_button.clicked.connect(lambda: self.setting_requested.emit(PLAIN))
        self.expand_label = _label(role="")
        self.expand_button = _setting_button(EXPAND)
        self.expand_button.clicked.connect(lambda: self.setting_requested.emit(EXPAND))
        layout = QVBoxLayout(self)
        for label, button in (
            (self.plain_label, self.plain_button),
            (self.expand_label, self.expand_button),
        ):
            frame = QFrame()
            set_props(frame, card=True)
            row = QHBoxLayout(frame)
            row.addWidget(label, stretch=1)
            row.addWidget(button)
            layout.addWidget(frame)
        layout.addWidget(_label(tr("insights.punctuation.where")))
        layout.addStretch(1)

    def set_punctuation(
        self, punctuation: Punctuation, suggested: Collection[str]
    ) -> None:
        self.plain_label.setText(
            tr(
                "insights.punctuation.plain",
                commas=punctuation.commas_removed,
                periods=punctuation.periods_removed,
                others=punctuation.others_removed,
                lowercased=punctuation.lowercased,
            )
        )
        self.expand_label.setText(
            tr("insights.punctuation.expand", count=punctuation.abbreviations)
        )
        self.plain_button.setVisible(PLAIN in suggested)
        self.expand_button.setVisible(EXPAND in suggested)


class SpeakersPage(QWidget):
    """Akapity ze zmienionym mówcą."""

    go_to_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edits: list[SpeakerEdit] = []
        self.hint = _label(role="status")
        self.table = table_widget(
            [
                tr(f"insights.speakers.column.{name}")
                for name in ("paragraph", "before", "after", "text")
            ]
        )
        self.show_button = QPushButton(tr("insights.speakers.show"))
        self.show_button.clicked.connect(self._show)
        self.table.itemActivated.connect(lambda _item: self._show())
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.show_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(row)

    def set_speakers(
        self, edits: Sequence[SpeakerEdit], labels: Mapping[str, str], estimated: bool
    ) -> None:
        self._edits = list(edits)
        self.hint.setText(
            tr("insights.speakers.estimated")
            if estimated
            else tr("insights.speakers.hint", count=len(self._edits))
        )

        def name(key: str | None) -> str:
            return tr("insights.speakers.none") if key is None else labels.get(key, key)

        fill_table(
            self.table,
            [
                (
                    e.paragraph + 1,
                    name(e.before),
                    name(e.after),
                    " ".join(e.text.split()),
                )
                for e in self._edits
            ],
        )
        self.show_button.setEnabled(bool(self._edits))

    def _show(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._edits):
            self.go_to_requested.emit(self._edits[row].start)


class SummaryPage(QWidget):
    """Podsumowanie: po jednej karcie na rodzaj wniosków z przejściem do strony."""

    open_requested = Signal(int)

    def __init__(self, titles: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.texts: list[QLabel] = []
        layout = QVBoxLayout(self)
        for index, title in enumerate(titles):
            frame = QFrame()
            set_props(frame, card=True)
            column = QVBoxLayout()
            column.addWidget(_label(title, role="title"))
            text = _label()
            self.texts.append(text)
            column.addWidget(text)
            button = QPushButton(tr("insights.summary.open"))
            button.clicked.connect(
                lambda _checked=False, page=index + 1: self.open_requested.emit(page)
            )
            row = QHBoxLayout(frame)
            row.addLayout(column, stretch=1)
            row.addWidget(button)
            layout.addWidget(frame)
        layout.addStretch(1)

    def set_texts(self, texts: Sequence[str]) -> None:
        for label, text in zip(self.texts, texts, strict=True):
            label.setText(text)


__all__ = [
    "EXPAND",
    "PLAIN",
    "VERBATIM",
    "FillersPage",
    "PunctuationPage",
    "SpeakersPage",
    "SummaryPage",
    "WordsPage",
]
