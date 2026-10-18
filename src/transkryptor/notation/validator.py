"""Nieblokujący walidator struktury notacji transkrypcji.

Realizuje reguły VAL-01 do VAL-12 z ``specs/transcription-rules.md``:

- VAL-01: pauza ``...`` lub ``…`` z odstępem przed, ale bez odstępu po.
- VAL-02: dopisek otwarty przez ``[`` bez zamykającego ``]``.
- VAL-03: sekwencja zaczynająca się od ``[…`` inna niż dokładnie ``[…?]``.
- VAL-04: wielokropek przylegający do poprzedniego słowa nigdy nie jest
  zgłaszany — to może być zamierzone urwane słowo.
- VAL-05 (wskazówka): wielokropek w zapisie innym niż wybrany styl; tylko
  gdy wywołujący poda styl.
- VAL-06: ``(!)``/``(?)`` przylegające do następnego słowa.
- VAL-07 (wskazówka): dwie lub więcej spacji z rzędu.
- VAL-08 (wskazówka): odstęp tuż przed ``]``.
- VAL-09: dopisek otwarty wewnątrz innego, niedomkniętego dopisku.
- VAL-10: indeks górny na znaku innym niż ``m``, ``n``, ``u``.
- VAL-11 (wskazówka, domyślnie wyłączona): ``m``/``n``/``u``, które
  wyglądają na nosowość lub labializację, bez indeksu górnego.
- VAL-12 (wskazówka): niepusty akapit bez mówcy w dokumencie, w którym
  przypisano mówców innym akapitom.

Walidator jest czystą funkcją: nie mutuje dokumentu, nie poprawia tekstu
i nie ocenia lingwistycznej poprawności zapisu (VAL-11 jest tylko
heurystyczną wskazówką). Zgodnie z kontraktem ``document -> notation``
wejściem jest tekst z zakresami indeksu górnego, a wynikiem lista
ostrzeżeń z zakresem znaków, kodem i komunikatem.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass

from transkryptor.document.speakers import paragraph_spans
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
VAL_06 = "VAL-06"
VAL_07 = "VAL-07"
VAL_08 = "VAL-08"
VAL_09 = "VAL-09"
VAL_10 = "VAL-10"
VAL_11 = "VAL-11"
VAL_12 = "VAL-12"

SEVERITY_WARNING = "warning"
SEVERITY_HINT = "hint"  # niższa ranga: konwencja zapisu, nie błąd struktury

SUPERSCRIPT_LETTERS = frozenset("mnuMNU")
_VOWELS = frozenset("aeiouyąęóAEIOUYĄĘÓ")
_OMITTED = "[…?]"


@dataclass(frozen=True)
class Warning:
    """Ostrzeżenie walidatora z kodem reguły i zakresem znaków."""

    code: str
    start: int
    end: int
    message: str
    severity: str = SEVERITY_WARNING


@dataclass(frozen=True)
class ValidatorRule:
    """Opis reguły walidatora dla ustawień (włączanie i wyłączanie)."""

    code: str
    label_key: str
    severity: str = SEVERITY_WARNING
    default_enabled: bool = True

    @property
    def label(self) -> str:
        return tr(self.label_key)


# VAL-04 nie ma wpisu: to reguła „nie zgłaszaj”, nie ma czego wyłączać.
VALIDATOR_RULES: tuple[ValidatorRule, ...] = (
    ValidatorRule(VAL_01, "validator.rule.val01"),
    ValidatorRule(VAL_02, "validator.rule.val02"),
    ValidatorRule(VAL_03, "validator.rule.val03"),
    ValidatorRule(VAL_05, "validator.rule.val05", SEVERITY_HINT),
    ValidatorRule(VAL_06, "validator.rule.val06"),
    ValidatorRule(VAL_07, "validator.rule.val07", SEVERITY_HINT),
    ValidatorRule(VAL_08, "validator.rule.val08", SEVERITY_HINT),
    ValidatorRule(VAL_09, "validator.rule.val09"),
    ValidatorRule(VAL_10, "validator.rule.val10"),
    ValidatorRule(VAL_11, "validator.rule.val11", SEVERITY_HINT, False),
    ValidatorRule(VAL_12, "validator.rule.val12", SEVERITY_HINT),
)

DEFAULT_ENABLED: frozenset[str] = frozenset(
    rule.code for rule in VALIDATOR_RULES if rule.default_enabled
)


def enabled_codes(overrides: dict[str, bool]) -> frozenset[str]:
    """Włączone reguły: domyślne z nadpisaniami użytkownika (kod → wł./wył.)."""
    return frozenset(
        rule.code
        for rule in VALIDATOR_RULES
        if overrides.get(rule.code, rule.default_enabled)
    )


def validate(
    text: str,
    ellipsis_style: EllipsisStyle | None = None,
    superscript_ranges: Iterable[tuple[int, int]] = (),
    enabled: Collection[str] | None = None,
    paragraph_speakers: Mapping[int, str] | None = None,
) -> list[Warning]:
    """Zwraca listę ostrzeżeń dla tekstu, posortowaną po pozycji.

    ``ellipsis_style`` włącza wskazówki VAL-05 dla wielokropków zapisanych
    inaczej niż wybrany styl. ``superscript_ranges`` (półotwarte zakresy
    indeksu górnego) są potrzebne regułom VAL-10 i VAL-11. ``enabled`` to
    kody włączonych reguł; ``None`` oznacza zestaw domyślny.
    ``paragraph_speakers`` (indeks akapitu → mówca) jest potrzebne VAL-12.
    """
    active = DEFAULT_ENABLED if enabled is None else frozenset(enabled)
    ranges = sorted(superscript_ranges)
    checks: tuple[tuple[str, Callable[[], list[Warning]]], ...] = (
        (VAL_01, lambda: _check_pause_spacing(text)),
        (VAL_02, lambda: _check_unclosed(text)),
        (VAL_03, lambda: _check_omission_marker(text)),
        (VAL_06, lambda: _check_adjacent_markers(text)),
        (VAL_07, lambda: _check_double_spaces(text)),
        (VAL_08, lambda: _check_space_before_close(text)),
        (VAL_09, lambda: _check_nested(text)),
        (VAL_10, lambda: _check_superscript_letters(text, ranges)),
        (VAL_11, lambda: _check_missing_superscript(text, ranges)),
        (VAL_12, lambda: _check_missing_speaker(text, paragraph_speakers or {})),
    )
    warnings: list[Warning] = []
    for code, check in checks:
        if code in active:
            warnings += check()
    # VAL-04: wielokropek przylegający do słowa nie jest zgłaszany (urwane słowo).
    if ellipsis_style is not None and VAL_05 in active:
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


def _check_unclosed(text: str) -> list[Warning]:
    """VAL-02: dopiski otwarte przez ``[`` bez zamykającego ``]``."""
    unclosed: list[int] = []
    for i, char in enumerate(text):
        if char == "[":
            unclosed.append(i)
        elif char == "]" and unclosed:
            unclosed.pop()
    return [
        Warning(
            code=VAL_02,
            start=open_index,
            end=len(text),
            message=tr("validator.unclosed_bracket"),
        )
        for open_index in unclosed
    ]


def _check_omission_marker(text: str) -> list[Warning]:
    """VAL-03: sekwencja ``[…`` inna niż dokładnie ``[…?]``."""
    warnings: list[Warning] = []
    n = len(text)
    i = 0
    while i + 1 < n:
        if text[i] == "[" and text[i + 1] == "…":
            if not text.startswith(_OMITTED, i):
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


def _check_adjacent_markers(text: str) -> list[Warning]:
    """VAL-06: ``(!)``/``(?)``, po którym od razu zaczyna się słowo."""
    warnings: list[Warning] = []
    for marker in ("(!)", "(?)"):
        start = text.find(marker)
        while start != -1:
            end = start + len(marker)
            if end < len(text) and text[end].isalnum():
                warnings.append(
                    Warning(
                        code=VAL_06,
                        start=start,
                        end=end,
                        message=tr("validator.adjacent_marker", marker=marker),
                    )
                )
            start = text.find(marker, end)
    return warnings


def _check_double_spaces(text: str) -> list[Warning]:
    """VAL-07: dwie lub więcej zwykłych spacji z rzędu (jedna wskazówka na ciąg)."""
    warnings: list[Warning] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != " ":
            i += 1
            continue
        end = i
        while end < n and text[end] == " ":
            end += 1
        if end - i >= 2:
            warnings.append(
                Warning(
                    code=VAL_07,
                    start=i,
                    end=end,
                    message=tr("validator.double_space"),
                    severity=SEVERITY_HINT,
                )
            )
        i = end
    return warnings


def _check_space_before_close(text: str) -> list[Warning]:
    """VAL-08: odstęp (bez nowej linii) tuż przed ``]``."""
    warnings: list[Warning] = []
    for i, char in enumerate(text):
        if char != "]" or i == 0 or text[i - 1] not in " \t ":
            continue
        start = i
        while start > 0 and text[start - 1] in " \t ":
            start -= 1
        warnings.append(
            Warning(
                code=VAL_08,
                start=start,
                end=i + 1,
                message=tr("validator.space_before_close"),
                severity=SEVERITY_HINT,
            )
        )
    return warnings


def _check_nested(text: str) -> list[Warning]:
    """VAL-09: ``[`` otwarty, gdy poprzedni dopisek jest jeszcze otwarty.

    Marker ``[…?]`` jest gotowym znacznikiem, nie dopiskiem — może stać
    wewnątrz dopisku. Zakres ostrzeżenia obejmuje wewnętrzny dopisek.
    """
    warnings: list[Warning] = []
    stack: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith(_OMITTED, i):
            i += len(_OMITTED)
            continue
        char = text[i]
        if char == "[":
            if stack:
                close_index = text.find("]", i + 1)
                end = close_index + 1 if close_index != -1 else i + 1
                warnings.append(
                    Warning(
                        code=VAL_09,
                        start=i,
                        end=end,
                        message=tr("validator.nested_bracket"),
                    )
                )
            stack.append(i)
        elif char == "]" and stack:
            stack.pop()
        i += 1
    return warnings


def _check_superscript_letters(
    text: str, ranges: list[tuple[int, int]]
) -> list[Warning]:
    """VAL-10: ciągi znaków w indeksie górnym innych niż ``m``, ``n``, ``u``."""
    warnings: list[Warning] = []
    for range_start, range_end in ranges:
        i = max(range_start, 0)
        end = min(range_end, len(text))
        while i < end:
            if _allowed_superscript(text[i]):
                i += 1
                continue
            run_end = i
            while run_end < end and not _allowed_superscript(text[run_end]):
                run_end += 1
            warnings.append(
                Warning(
                    code=VAL_10,
                    start=i,
                    end=run_end,
                    message=tr(
                        "validator.superscript_letter", fragment=text[i:run_end]
                    ),
                )
            )
            i = run_end
    return warnings


def _check_missing_speaker(text: str, speakers: Mapping[int, str]) -> list[Warning]:
    """VAL-12: niepusty akapit bez mówcy, gdy dokument używa mówców.

    Sama lista mówców (domyślnie B i I) nie wystarcza — wskazówka pojawia
    się dopiero po przypisaniu mówcy pierwszemu akapitowi. Zakres to
    pierwsze słowo akapitu.
    """
    if not speakers:
        return []
    warnings: list[Warning] = []
    for index, (start, end) in enumerate(paragraph_spans(text)):
        if index in speakers:
            continue
        paragraph = text[start:end]
        stripped = paragraph.lstrip()
        if not stripped:
            continue
        word_start = start + len(paragraph) - len(stripped)
        word_end = word_start + (len(stripped.split()[0]))
        warnings.append(
            Warning(
                code=VAL_12,
                start=word_start,
                end=word_end,
                message=tr("validator.missing_speaker"),
                severity=SEVERITY_HINT,
            )
        )
    return warnings


def _allowed_superscript(char: str) -> bool:
    return char in SUPERSCRIPT_LETTERS or char.isspace()


def _check_missing_superscript(
    text: str, ranges: list[tuple[int, int]]
) -> list[Warning]:
    """VAL-11: heurystyka nosowości i labializacji bez indeksu górnego.

    ``m``/``n`` po samogłosce przed spółgłoską lub na końcu słowa
    (``som``, ``bendzie``) oraz ``u`` przed ``o``/``ó`` na początku słowa
    (``uod``). Tylko wskazówka — nie ocenia poprawności fonetycznej.
    """
    superscript = [False] * len(text)
    for start, end in ranges:
        for i in range(max(start, 0), min(end, len(text))):
            superscript[i] = True
    warnings: list[Warning] = []
    for i, char in enumerate(text):
        if superscript[i] or not char.isalpha():
            continue
        lower = char.lower()
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if lower in "mn":
            suspicious = prev in _VOWELS and (
                not nxt.isalpha() or (nxt not in _VOWELS and nxt.lower() not in "ij")
            )
        elif lower == "u":
            suspicious = not prev.isalpha() and nxt in "oóOÓ"
        else:
            suspicious = False
        if suspicious:
            warnings.append(
                Warning(
                    code=VAL_11,
                    start=i,
                    end=i + 1,
                    message=tr("validator.missing_superscript", letter=char),
                    severity=SEVERITY_HINT,
                )
            )
    return warnings
