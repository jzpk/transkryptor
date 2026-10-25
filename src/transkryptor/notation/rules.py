"""Reguły kandydatów zapisu fonetycznego jako dane (TOML, bez Qt).

Reguły wbudowane są zasobem pakietu (``notation/data/builtin_rules.toml``),
reguły użytkownika - plikiem w katalogu danych (kody z prefiksem ``USR-``).
Każda reguła to wyrażenie regularne na jednym słowie albo na parze
sąsiednich słów oraz zamiennik w składni ``^x`` (znak ``x`` w indeksie
górnym), ``\\^`` (dosłowny ``^``), ``\\\\`` (dosłowny ``\\``) i ``\\1``…``\\9``
(grupa wzorca).

Ładowanie nigdy nie rzuca wyjątku: błędna reguła trafia do listy błędów
z nazwą pliku, numerem i kodem reguły oraz polem, a pozostałe działają.
Wzorce kompiluje pakiet ``regex`` (składnia zgodna z ``re``) - pozwala to
przerwać dopasowanie z katastrofalnym nawracaniem limitem czasu
(``notation.suggestions``).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

import regex

from transkryptor.i18n import FALLBACK_LANGUAGE, current_language, tr

SCOPE_WORD = "word"
SCOPE_PAIR = "pair"
SCOPES = (SCOPE_WORD, SCOPE_PAIR)
USER_PREFIX = "USR-"
MAX_PATTERN_LENGTH = 200
BUILTIN_SOURCE = "builtin_rules.toml"
# Tekst bez języka (reguły użytkownika) - pokazywany w każdym języku.
ANY_LANGUAGE = "*"

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]*$")
_GROUP_RE = re.compile(r"[1-9]")


@dataclass(frozen=True)
class PhoneticRule:
    """Reguła zapisu fonetycznego.

    ``label`` i ``description`` to teksty w językach interfejsu
    (``{"pl": …, "en": …}`` albo ``{"*": …}``). ``auto_apply`` to domyślne
    zaznaczenie reguły w panelu ASR (stosowanie od razu po wstawieniu szkicu).
    """

    code: str
    label: Mapping[str, str]
    pattern: str
    replacement: str
    confidence: float
    scope: str = SCOPE_WORD
    description: Mapping[str, str] = field(default_factory=dict)
    example: str = ""
    auto_apply: bool = False
    builtin: bool = False

    @property
    def label_text(self) -> str:
        return localized(self.label) or self.code

    @property
    def description_text(self) -> str:
        return localized(self.description) or self.label_text


@dataclass(frozen=True)
class RuleError:
    """Błąd jednej reguły w pliku: plik, numer (od 1), kod, pole i powód."""

    source: str
    index: int
    code: str
    field: str
    reason: str

    @property
    def message(self) -> str:
        return tr(
            "rules.error",
            file=self.source,
            index=self.index,
            code=self.code or "?",
            field=self.field,
            reason=self.reason,
        )


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[PhoneticRule, ...] = ()
    errors: tuple[RuleError, ...] = ()


@dataclass(frozen=True)
class Template:
    """Rozebrany zamiennik: części dosłowne (z flagą indeksu górnego) i grupy."""

    parts: tuple[tuple[str, bool] | int, ...]
    max_group: int

    def expand(self, match: Any) -> tuple[str, tuple[tuple[int, int], ...]]:
        """Tekst zamiennika i zakresy indeksu górnego dla dopasowania."""
        chunks: list[str] = []
        ranges: list[tuple[int, int]] = []
        length = 0
        for part in self.parts:
            if isinstance(part, int):
                text = match.group(part) or ""
                superscript = False
            else:
                text, superscript = part
            if superscript and text:
                if ranges and ranges[-1][1] == length:
                    ranges[-1] = (ranges[-1][0], length + len(text))
                else:
                    ranges.append((length, length + len(text)))
            chunks.append(text)
            length += len(text)
        return "".join(chunks), tuple(ranges)


class TemplateError(ValueError):
    """Błędny zamiennik - komunikat dla użytkownika."""


def localized(texts: Mapping[str, str]) -> str:
    """Tekst w bieżącym języku, potem bez języka, zapasowym albo pierwszy."""
    for key in (current_language(), ANY_LANGUAGE, FALLBACK_LANGUAGE):
        if texts.get(key):
            return texts[key]
    return next((text for text in texts.values() if text), "")


def parse_template(template: str) -> Template:
    """Rozbiera zamiennik reguły; błąd składni → ``TemplateError``."""
    parts: list[tuple[str, bool] | int] = []
    max_group = 0
    i = 0
    while i < len(template):
        char = template[i]
        if char == "\\":
            nxt = template[i + 1 : i + 2]
            if nxt in ("^", "\\"):
                parts.append((nxt, False))
            elif nxt and _GROUP_RE.fullmatch(nxt):
                parts.append(int(nxt))
                max_group = max(max_group, int(nxt))
            else:
                raise TemplateError(tr("rules.reason.escape"))
            i += 2
            continue
        if char == "^":
            if i + 1 >= len(template) or template[i + 1] in "^\\":
                raise TemplateError(tr("rules.reason.caret"))
            parts.append((template[i + 1], True))
            i += 2
            continue
        parts.append((char, False))
        i += 1
    if not parts:
        raise TemplateError(tr("rules.reason.empty"))
    return Template(tuple(parts), max_group)


def compile_pattern(pattern: str) -> regex.Pattern[str]:
    """Kompiluje wzorzec reguły; błąd → ``ValueError`` z czytelnym powodem."""
    if not pattern:
        raise ValueError(tr("rules.reason.empty"))
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(tr("rules.reason.too_long", limit=MAX_PATTERN_LENGTH))
    try:
        return regex.compile(pattern)
    except regex.error as error:
        reason = getattr(error, "msg", None) or str(error)
        raise ValueError(tr("rules.reason.regex", reason=reason)) from error


@dataclass(frozen=True)
class CompiledRule:
    rule: PhoneticRule
    regex: regex.Pattern[str]
    template: Template


def compile_rule(rule: PhoneticRule) -> CompiledRule:
    """Kompiluje regułę już sprawdzoną przy ładowaniu."""
    return CompiledRule(
        rule, compile_pattern(rule.pattern), parse_template(rule.replacement)
    )


# --- ładowanie ------------------------------------------------------------------


def parse_rules(
    raw: str,
    source: str,
    *,
    builtin: bool = False,
    taken_codes: Iterable[str] = (),
) -> RuleSet:
    """Reguły z tekstu TOML; błędne reguły trafiają do ``errors``."""
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as error:
        return RuleSet(errors=(RuleError(source, 0, "", "toml", str(error)),))
    entries = data.get("rule", [])
    if not isinstance(entries, list):
        return RuleSet(
            errors=(RuleError(source, 0, "", "rule", tr("rules.reason.type")),)
        )
    taken = set(taken_codes)
    rules: list[PhoneticRule] = []
    errors: list[RuleError] = []
    for index, entry in enumerate(entries, start=1):
        result = _rule_from_dict(entry, builtin=builtin, taken=taken)
        if isinstance(result, PhoneticRule):
            rules.append(result)
            taken.add(result.code)
        else:
            code, field_name, reason = result
            errors.append(RuleError(source, index, code, field_name, reason))
    return RuleSet(tuple(rules), tuple(errors))


def check_rule(rule: PhoneticRule, taken_codes: Iterable[str] = ()) -> str | None:
    """Powód odrzucenia reguły (dla edytora reguł) albo None."""
    result = _rule_from_dict(
        rule_to_dict(rule), builtin=rule.builtin, taken=set(taken_codes)
    )
    if isinstance(result, PhoneticRule):
        return None
    _code, field_name, reason = result
    return tr("rules.field_error", field=field_name, reason=reason)


def _rule_from_dict(
    entry: Any, *, builtin: bool, taken: set[str]
) -> PhoneticRule | tuple[str, str, str]:
    """Reguła albo ``(kod, pole, powód)`` błędu."""
    if not isinstance(entry, dict):
        return "", "rule", tr("rules.reason.type")
    code = entry.get("code")
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        return str(code or ""), "code", tr("rules.reason.code")
    if builtin == code.startswith(USER_PREFIX):
        reason = (
            tr("rules.reason.builtin_prefix")
            if builtin
            else tr("rules.reason.user_prefix", prefix=USER_PREFIX)
        )
        return code, "code", reason
    if code in taken:
        return code, "code", tr("rules.reason.duplicate")
    label = _texts(entry.get("label"))
    if label is None or not any(label.values()):
        return code, "label", tr("rules.reason.text")
    description = _texts(entry.get("description", {}))
    if description is None:
        return code, "description", tr("rules.reason.text")
    pattern = entry.get("pattern")
    if not isinstance(pattern, str):
        return code, "pattern", tr("rules.reason.type")
    try:
        compiled = compile_pattern(pattern)
    except ValueError as error:
        return code, "pattern", str(error)
    replacement = entry.get("replacement")
    if not isinstance(replacement, str):
        return code, "replacement", tr("rules.reason.type")
    try:
        template = parse_template(replacement)
    except TemplateError as error:
        return code, "replacement", str(error)
    if template.max_group > compiled.groups:
        return code, "replacement", tr("rules.reason.group", group=template.max_group)
    confidence = entry.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not 0 < confidence <= 1
    ):
        return code, "confidence", tr("rules.reason.confidence")
    scope = entry.get("scope", SCOPE_WORD)
    if scope not in SCOPES:
        return code, "scope", tr("rules.reason.scope")
    example = entry.get("example", "")
    if not isinstance(example, str):
        return code, "example", tr("rules.reason.type")
    auto_apply = entry.get("auto_apply", False)
    if not isinstance(auto_apply, bool):
        return code, "auto_apply", tr("rules.reason.type")
    return PhoneticRule(
        code=code,
        label=label,
        pattern=pattern,
        replacement=replacement,
        confidence=float(confidence),
        scope=scope,
        description=description,
        example=example,
        auto_apply=auto_apply,
        builtin=builtin,
    )


def _texts(value: Any) -> dict[str, str] | None:
    """Tekst reguły: napis (bez języka) albo tabela ``{język: tekst}``."""
    if isinstance(value, str):
        return {ANY_LANGUAGE: value} if value else {}
    if isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        return dict(value)
    return None


@cache
def builtin_rules() -> RuleSet:
    """Reguły wbudowane w pakiet (wczytywane raz)."""
    raw = (
        resources.files("transkryptor.notation")
        .joinpath("data", BUILTIN_SOURCE)
        .read_text(encoding="utf-8")
    )
    return parse_rules(raw, BUILTIN_SOURCE, builtin=True)


def builtin_codes() -> frozenset[str]:
    return frozenset(rule.code for rule in builtin_rules().rules)


# --- zapis ----------------------------------------------------------------------


def rule_to_dict(rule: PhoneticRule) -> dict[str, Any]:
    data: dict[str, Any] = {
        "code": rule.code,
        "label": _text_value(rule.label),
        "pattern": rule.pattern,
        "replacement": rule.replacement,
        "confidence": rule.confidence,
    }
    if rule.scope != SCOPE_WORD:
        data["scope"] = rule.scope
    if rule.description:
        data["description"] = _text_value(rule.description)
    if rule.example:
        data["example"] = rule.example
    if rule.auto_apply:
        data["auto_apply"] = True
    return data


def _text_value(texts: Mapping[str, str]) -> str | dict[str, str]:
    if set(texts) == {ANY_LANGUAGE}:
        return texts[ANY_LANGUAGE]
    return dict(texts)


def dumps_rules(rules: Iterable[PhoneticRule]) -> str:
    """Zestaw reguł jako TOML (prosty generator - ``tomllib`` tylko czyta)."""
    lines = [f"# {tr('rules.file_header')}", ""]
    for rule in rules:
        lines.append("[[rule]]")
        for key, value in rule_to_dict(rule).items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(float(value))
    if isinstance(value, dict):
        items = ", ".join(
            f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()
        )
        return "{ " + items + " }"
    return _toml_string(str(value))


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _toml_string(key)


def _toml_string(text: str) -> str:
    """Napis TOML w cudzysłowie z pełnym escapowaniem (bezpieczny dla regexów)."""
    escaped = []
    for char in text:
        if char == "\\":
            escaped.append("\\\\")
        elif char == '"':
            escaped.append('\\"')
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\t":
            escaped.append("\\t")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            escaped.append(f"\\u{ord(char):04x}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'
