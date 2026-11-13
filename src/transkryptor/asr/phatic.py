"""Fatyczne „nie?” i podobne zakończenia wypowiedzi (zgłoszenie #45).

W gwarach (zwłaszcza wielkopolskich) wypowiedź często kończy się fatycznym
„nie?” - jak ogólnopolskie „prawda?”, „co nie?”. Ma intonację pytającą
i w transkrypcji zapisuje się je ze znakiem zapytania („…wybudowali, nie?”),
ale nie jest pytaniem: podtrzymuje kontakt z rozmówcą. Szkic ASR uzyskuje
te „nie?” dzięki przykładowi stylu w prompcie Whispera
(``engine.VERBATIM_PROMPT``); :func:`ends_with_phatic_tag` pozwala odróżnić
je od prawdziwych pytań (np. w układzie „pytanie - odpowiedź”).
"""

from __future__ import annotations

import regex

# Zakończenia fatyczne: „…, nie?”, „co nie?”, „prawda?”, „nieprawdaż?”,
# „no nie?”, „tak?” po przecinku. Samo „Nie?” (odpowiedź-pytanie) się nie
# liczy, dlatego przed znacznikiem musi stać inne słowo.
_PHATIC_RE = regex.compile(
    r"\w[\w\"”)\]]*[,\s…]+(?:(?:co|no|a)\s+)?(?:nie|prawda|nieprawdaż|tak)"
    r"\s*\?[\"”)\]…\s]*$",
    regex.IGNORECASE,
)


# Słowo pytajne tuż przed „nie?” robi z niego pytanie („A dlaczego nie?”).
_INTERROGATIVES = frozenset(
    {"dlaczego", "czemu", "czemuż", "czy", "czyż", "jak", "gdzie", "kiedy", "skąd"}
)
_WORD_RE = regex.compile(r"\w+")


def ends_with_phatic_tag(sentence: str) -> bool:
    """Czy zdanie kończy się fatycznym „nie?” (albo „prawda?”, „co nie?”)."""
    match = _PHATIC_RE.search(sentence.strip())
    if match is None:
        return False
    words = _WORD_RE.findall(sentence.lower())
    return len(words) < 2 or words[-2] not in _INTERROGATIVES


__all__ = ["ends_with_phatic_tag"]
