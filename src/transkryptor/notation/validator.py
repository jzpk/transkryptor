"""Nieblokujący walidator struktury notacji transkrypcji.

Realizuje reguły VAL-01 do VAL-05 z ``specs/transcription-rules.md``:

- VAL-01: pauza ``...`` lub ``…`` z odstępem przed, ale bez odstępu po.
- VAL-02: dopisek otwarty przez ``[`` bez zamykającego ``]``.
- VAL-03: sekwencja zaczynająca się od ``[…`` inna niż dokładnie ``[…?]``.
- VAL-04: wielokropek przylegający do poprzedniego słowa nigdy nie jest
  zgłaszany — to może być zamierzone urwane słowo.
- VAL-05 (wskazówka): wielokropek w zapisie innym niż wybrany styl; tylko
  gdy wywołujący poda styl.

Walidator jest czystą funkcją: nie mutuje dokumentu, nie poprawia tekstu
i nie ocenia lingwistycznej poprawności zapisu. Zgodnie z kontraktem
``document -> notation`` wejściem jest zwykły tekst, a wynikiem lista
ostrzeżeń z zakresem znaków, kodem i komunikatem.
"""

from __future__ import annotations

from dataclasses import dataclass

from transkryptor.i18n import tr
from transkryptor.notation.ellipsis import (
    EllipsisStyle,
    ellipsis_text,
    foreign_ellipses,
)

VAL_01 = "VAL-01"
VAL_02 = "VAL-02"
VAL_03 = "VAL-03"
VAL_04 = "VAL-04"
VAL_05 = "VAL-05"

SEVERITY_WARNING = "warning"
SEVERITY_HINT = "hint"  # niższa ranga: konwencja zapisu, nie błąd struktury


@dataclass(frozen=True)
class Warning:
    """Ostrzeżenie walidatora z kodem reguły i zakresem znaków."""

    code: str
    start: int
    end: int
    message: str
    severity: str = SEVERITY_WARNING


def validate(text: str, ellipsis_style: EllipsisStyle | None = None) -> list[Warning]:
    """Zwraca listę ostrzeżeń dla tekstu, posortowaną po pozycji.

    ``ellipsis_style`` włącza wskazówki VAL-05 dla wielokropków zapisanych
    inaczej niż wybrany styl.
    """
    warnings = _check_pause_spacing(text) + _check_brackets(text)
    # VAL-04: wielokropek przylegający do słowa nie jest zgłaszany (urwane słowo).
    if ellipsis_style is not None:
        warnings += _check_ellipsis_style(text, ellipsis_style)
    return sorted(warnings, key=lambda warning: (warning.start, warning.code))


def _check_pause_spacing(text: str) -> list[Warning]:
    """VAL-01: ``...``/``…`` poprzedzone odstępem, po którym nie ma odstępu."""
    warnings: list[Warning] = []
    n = len(text)
    i = 0
    while i < n:
        ellipsis = next((e for e in ("...", "…") if text.startswith(e, i)), None)
        if ellipsis is None:
            i += 1
            continue
        end = i + len(ellipsis)
        preceded_by_space = i > 0 and text[i - 1].isspace()
        followed_by_text = end < n and not text[end].isspace()
        if preceded_by_space and followed_by_text:
            warnings.append(
                Warning(
                    code=VAL_01,
                    start=i,
                    end=end,
                    message=tr("validator.pause_spacing", ellipsis=ellipsis),
                )
            )
        i = end
    return warnings


def _check_ellipsis_style(text: str, style: EllipsisStyle) -> list[Warning]:
    """VAL-05: wielokropek w zapisie innym niż wybrany w ustawieniach."""
    wanted = ellipsis_text(style)
    return [
        Warning(
            code=VAL_05,
            start=start,
            end=end,
            message=tr(
                "validator.ellipsis_style", found=text[start:end], wanted=wanted
            ),
            severity=SEVERITY_HINT,
        )
        for start, end in foreign_ellipses(text, style)
    ]


def _check_brackets(text: str) -> list[Warning]:
    """VAL-02 i VAL-03: niedomknięte dopiski oraz wadliwy marker ``[…?]``."""
    warnings: list[Warning] = []
    unclosed: list[int] = []
    n = len(text)
    for i, char in enumerate(text):
        if char == "[":
            unclosed.append(i)
        elif char == "]":
            if unclosed:
                unclosed.pop()
    for open_index in unclosed:
        warnings.append(
            Warning(
                code=VAL_02,
                start=open_index,
                end=n,
                message=tr("validator.unclosed_bracket"),
            )
        )
    i = 0
    while i + 1 < n:
        if text[i] == "[" and text[i + 1] == "…":
            if not text.startswith("[…?]", i):
                close_index = text.find("]", i + 2)
                end = close_index + 1 if close_index != -1 else n
                warnings.append(
                    Warning(
                        code=VAL_03,
                        start=i,
                        end=end,
                        message=tr("validator.omission_marker"),
                    )
                )
            i += 2
        else:
            i += 1
    return warnings
