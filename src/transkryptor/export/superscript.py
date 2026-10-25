"""Indeks górny w formatach czysto tekstowych (TXT, SRT, WebVTT, TextGrid, EAF).

Tekst bez formatowania nie ma indeksu górnego, więc trzeba go zapisać
znakami. Dwa tryby:

- ``unicode`` (domyślny) - litery modyfikujące Unicode (``ᵐ ⁿ ᵘ``…),
  czytelne w ELAN i Praat; znak bez odpowiednika zapisuje się jak w trybie
  ``caret`` i trafia do raportu eksportu;
- ``caret`` - ``^m`` dla jednego znaku, ``^{mn}`` dla dłuższego zakresu;
  tekst bazowy zostaje bez zmian dla narzędzi wyszukujących.
"""

from __future__ import annotations

from collections.abc import Iterable

from transkryptor.export.model import ExportRun

UNICODE = "unicode"
CARET = "caret"
MODES = (UNICODE, CARET)

_SMALL = "abcdefghijklmnoprstuvwxyz"
_SMALL_UP = "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"
_CAPITAL = "ABDEGHIJKLMNOPRTUVW"
_CAPITAL_UP = "ᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ"
_OTHER = "0123456789+-=()"
_OTHER_UP = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾"

UNICODE_SUPERSCRIPT: dict[str, str] = {
    **dict(zip(_SMALL, _SMALL_UP, strict=True)),
    **dict(zip(_CAPITAL, _CAPITAL_UP, strict=True)),
    **dict(zip(_OTHER, _OTHER_UP, strict=True)),
}


def caret(text: str) -> str:
    """``^m`` dla jednego znaku, ``^{mn}`` dla dłuższego fragmentu."""
    return f"^{text}" if len(text) == 1 else f"^{{{text}}}"


def superscript_text(text: str, mode: str, unmapped: set[str]) -> str:
    """Fragment w indeksie górnym zapisany znakami; ``unmapped`` zbiera braki."""
    if mode == CARET:
        return caret(text)
    result: list[str] = []
    for char in text:
        if char.isspace():
            result.append(char)
        elif char in UNICODE_SUPERSCRIPT:
            result.append(UNICODE_SUPERSCRIPT[char])
        else:
            unmapped.add(char)
            result.append(caret(char))
    return "".join(result)


def render_runs(runs: Iterable[ExportRun], mode: str, unmapped: set[str]) -> str:
    """Tekst runów z indeksem górnym zapisanym w trybie ``mode``."""
    return "".join(
        superscript_text(run.text, mode, unmapped) if run.superscript else run.text
        for run in runs
    )
