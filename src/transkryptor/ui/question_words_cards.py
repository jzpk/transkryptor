"""Widok „Według pytań”: karta na każde pytanie i lista pytań nieodnalezionych.

Karta pokazuje pytanie, akapit, w którym je odnaleziono (z czasem nagrania,
podobieństwem i informacją, czy wskazano go ręcznie), pytania nieodnalezione,
których odpowiedzi mogą być w tej sekcji, oraz słowa pogrupowane według części
mowy. Słowa z pól tematycznych, spoza pól i nierozpoznane różnią się tłem,
a słowa policzone tylko w „pełniejszej liście” mają znak ≈.

Przycisk „Zmień akapit…” (na karcie i przy pytaniu nieodnalezionym) otwiera
menu podobnych wypowiedzi badacza, akapitu z kursorem w edytorze i - przy
wskazaniu ręcznym - powrotu do rozpoznania automatycznego. Widok tylko ogłasza
wybór sygnałami; wskazania zapisuje kontroler.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from typing import Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.question_words import (
    OUTSIDE,
    Candidate,
    QuestionPlace,
    QuestionSection,
    QuestionWords,
    SectionWord,
    UnlocatedQuestion,
)
from transkryptor.i18n import tr
from transkryptor.ui.question_words_table import (
    PARTS,
    WordFilter,
    section_title,
    visible_sections,
    visible_words,
)
from transkryptor.ui.theme import set_props, tokens

SIMILAR_SHOWN = 5


class CardContext(Protocol):
    """Dane spoza wyniku: podobne akapity i opis akapitu (czas nagrania)."""

    def candidates(self, question: int) -> list[Candidate]: ...

    def paragraph_label(self, paragraph: int) -> str: ...


def _chip(word: SectionWord) -> str:
    colors = tokens()
    if word.part is None:
        background, color, style = colors.warning_soft, colors.warning, "italic"
    elif word.theme:
        background, color, style = colors.accent_soft, colors.accent_text, "normal"
    else:
        background, color, style = colors.surface_alt, colors.text, "normal"
    mark = " ≈" if word.ambiguous else ""
    return (
        f'<span style="background-color:{background}; color:{color}; '
        f'font-style:{style}">&nbsp;{escape(word.lemma)}{mark}'
        f"&nbsp;<small>{word.count}</small>&nbsp;</span>"
    )


def words_html(words: Sequence[SectionWord]) -> str:
    """Słowa w grupach części mowy (nagłówek grupy, gdy grup jest kilka)."""
    groups = [
        (part, [word for word in words if word.part is part]) for part in (*PARTS, None)
    ]
    groups = [(part, chosen) for part, chosen in groups if chosen]
    if not groups:
        return f"<i>{escape(tr('question_words.no_words'))}</i>"
    blocks = []
    for part, chosen in groups:
        name = tr(f"pos.{part.value}") if part else tr("question_words.group.unknown")
        title = f"<b>{escape(name)}</b><br>" if len(groups) > 1 else ""
        blocks.append(title + " &nbsp;".join(_chip(word) for word in chosen))
    return "<br><br>".join(blocks)


class QuestionCards(QScrollArea):
    """Karty pytań z wynikiem filtru; sygnały wskazań akapitów."""

    # (numer pytania od 0, numer akapitu)
    mark_requested = Signal(int, int)
    cursor_mark_requested = Signal(int)
    unmark_requested = Signal(int)
    go_to_requested = Signal(int)

    def __init__(self, context: CardContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("question_words_cards")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._context = context
        self.cards: list[QFrame] = []
        self.unlocated_buttons: list[QPushButton] = []
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self.setWidget(self._body)

    def show_report(self, report: QuestionWords, words_filter: WordFilter) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.cards = [
            self._card(section, visible_words(section, words_filter))
            for section in visible_sections(report, words_filter)
        ]
        for card in self.cards:
            self._layout.addWidget(card)
        self.unlocated_buttons = []
        if report.unlocated:
            self._layout.addWidget(self._unlocated_card(report.unlocated))
        self._layout.addStretch(1)

    # --- karta pytania -----------------------------------------------------------

    def _card(self, section: QuestionSection, words: list[SectionWord]) -> QFrame:
        frame = QFrame()
        set_props(frame, card=True)
        layout = QVBoxLayout(frame)
        title = QLabel(f"<b>{escape(section_title(section))}</b>")
        title.setWordWrap(True)
        header = QHBoxLayout()
        header.addWidget(title, stretch=1)
        if section.number != OUTSIDE:
            button = QPushButton(tr("question_words.mark"))
            button.setToolTip(tr("question_words.mark.tooltip"))
            button.setMenu(self._mark_menu(button, section.number - 1, section))
            header.addWidget(button)
        layout.addLayout(header)
        if section.place is not None:
            layout.addWidget(self._place_label(section, section.place))
        if section.folded:
            folded = QLabel(
                tr(
                    "question_words.folded",
                    numbers=", ".join(str(number) for number in section.folded),
                )
            )
            folded.setWordWrap(True)
            set_props(folded, role="status", tone="warning")
            layout.addWidget(folded)
        content = QLabel(words_html(words))
        content.setWordWrap(True)
        content.setToolTip(tr("question_words.words.tooltip"))
        layout.addWidget(content)
        return frame

    def _place_label(self, section: QuestionSection, place: QuestionPlace) -> QLabel:
        how = (
            tr("question_words.place.manual")
            if place.manual
            else tr("question_words.place.auto", score=round(place.score * 100))
        )
        label = QLabel(
            tr(
                "question_words.place",
                link=f'<a href="{place.paragraph}">'
                f"{escape(self._context.paragraph_label(place.paragraph))}</a>",
                text=escape(_shortened(section.asked)),
                how=escape(how),
            )
        )
        label.setWordWrap(True)
        set_props(label, role="muted")
        label.linkActivated.connect(lambda link: self.go_to_requested.emit(int(link)))
        return label

    def _mark_menu(
        self, owner: QWidget, question: int, section: QuestionSection | None
    ) -> QMenu:
        """Menu wskazania akapitu; podobne akapity liczone przy otwarciu."""
        menu = QMenu(owner)
        menu.aboutToShow.connect(lambda: self._fill_mark_menu(menu, question, section))
        return menu

    def _fill_mark_menu(
        self, menu: QMenu, question: int, section: QuestionSection | None
    ) -> None:
        menu.clear()
        current = section.place.paragraph if section and section.place else None
        for candidate in self._context.candidates(question)[:SIMILAR_SHOWN]:
            action = menu.addAction(
                tr(
                    "question_words.candidate",
                    where=self._context.paragraph_label(candidate.paragraph),
                    text=_shortened(candidate.text),
                    score=round(candidate.score * 100),
                )
            )
            action.setCheckable(True)
            action.setChecked(candidate.paragraph == current)
            action.triggered.connect(
                lambda _checked=False, p=candidate.paragraph: self.mark_requested.emit(
                    question, p
                )
            )
        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction(tr("question_words.mark.cursor")).triggered.connect(
            lambda _checked=False: self.cursor_mark_requested.emit(question)
        )
        if section is not None and section.place is not None and section.place.manual:
            menu.addAction(tr("question_words.mark.auto")).triggered.connect(
                lambda _checked=False: self.unmark_requested.emit(question)
            )

    # --- pytania nieodnalezione ---------------------------------------------------

    def _unlocated_card(self, unlocated: Sequence[UnlocatedQuestion]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("question_words_unlocated")
        set_props(frame, card=True)
        layout = QVBoxLayout(frame)
        title = QLabel(
            f"<b>{escape(tr('question_words.unlocated', count=len(unlocated)))}</b>"
        )
        hint = QLabel(tr("question_words.unlocated.hint"))
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        layout.addWidget(title)
        layout.addWidget(hint)
        for question in unlocated:
            target = (
                tr("question_words.unlocated.into", number=question.folded_into)
                if question.folded_into != OUTSIDE
                else tr("question_words.unlocated.outside")
            )
            text = QLabel(f"<b>{question.number}.</b> {escape(question.question)}")
            text.setWordWrap(True)
            where = QLabel(target)
            set_props(where, role="muted")
            button = QPushButton(tr("question_words.mark.unlocated"))
            button.setMenu(self._mark_menu(button, question.number - 1, None))
            self.unlocated_buttons.append(button)
            row = QHBoxLayout()
            column = QVBoxLayout()
            column.addWidget(text)
            column.addWidget(where)
            row.addLayout(column, stretch=1)
            row.addWidget(button)
            layout.addLayout(row)
        return frame


def _shortened(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
