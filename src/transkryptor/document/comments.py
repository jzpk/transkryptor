"""Komentarze recenzji do fragmentów tekstu (faza 14, REQ-27; bez Qt).

Komentarz to zakres tekstu ``[start, end)`` (pozycje Pythona) z autorem,
datą i treścią oraz jednopoziomowym wątkiem odpowiedzi. ``quote`` to treść
fragmentu w chwili zapisu - pokazuje, czego dotyczył komentarz, gdy
fragment zmieniono albo usunięto. ``resolved`` oznacza komentarz
rozwiązany (sprawa załatwiona); zostaje w projekcie, ale nie jest już
„otwarty” - np. w raporcie gotowości do oddania. Komentarz, którego fragment usunięto,
zostaje jako punkt (``start == end``): komentarzy nie usuwa się po cichu.

Kotwice przesuwające się z edycją śledzi warstwa UI (kursory edytora,
``ui/comments_controller.py``); tu są dane w chwili zapisu i odczytu.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime

# Data komentarza: lokalny czas do minut, ISO 8601 (np. 2026-10-24T14:05).
DATE_FORMAT = "%Y-%m-%dT%H:%M"


def now() -> str:
    return datetime.now().strftime(DATE_FORMAT)


def display_date(value: str) -> str:
    """Data komentarza do wyświetlenia (``2026-10-24 14:05``)."""
    return value.replace("T", " ")


@dataclass(frozen=True)
class Reply:
    author: str
    created: str
    text: str


@dataclass(frozen=True)
class Comment:
    id: str
    start: int
    end: int
    author: str
    created: str
    text: str
    quote: str = ""
    replies: tuple[Reply, ...] = ()
    resolved: bool = False

    @property
    def is_point(self) -> bool:
        return self.start == self.end

    def with_reply(self, reply: Reply) -> Comment:
        return replace(self, replies=(*self.replies, reply))


def new_comment(
    start: int, end: int, quote: str, author: str, text: str, created: str = ""
) -> Comment:
    """Nowy komentarz z unikalnym identyfikatorem i bieżącą datą."""
    return Comment(
        id=uuid.uuid4().hex,
        start=start,
        end=end,
        author=author,
        created=created or now(),
        text=text,
        quote=quote,
    )


def check_comment(comment: Comment, text_length: int) -> None:
    """``ValueError``, gdy komentarz nie pasuje do tekstu o danej długości."""
    if not comment.id:
        raise ValueError("komentarz bez identyfikatora")
    if not 0 <= comment.start <= comment.end <= text_length:
        raise ValueError("komentarz poza tekstem")
