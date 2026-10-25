"""Reguły fonetyczne: wbudowane i z pliku użytkownika (``rules/user.toml``).

Plik użytkownika leży w katalogu danych aplikacji; zapis jest atomowy
(``document.project.write_atomic``). Błędy ładowania nie blokują pracy -
błędne reguły są pomijane, a ich opis udostępnia ``errors``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from transkryptor import paths
from transkryptor.document.project import write_atomic
from transkryptor.notation.rules import (
    PhoneticRule,
    RuleError,
    RuleSet,
    builtin_codes,
    builtin_rules,
    dumps_rules,
    parse_rules,
)

USER_RULES_FILE = "user.toml"


def user_rules_path() -> Path:
    """Plik reguł użytkownika (podmieniany w testach)."""
    return paths.user_data_dir() / "rules" / USER_RULES_FILE


def read_rules_file(path: Path, taken_codes: Iterable[str]) -> RuleSet:
    """Reguły użytkownika z pliku; brak pliku to pusty zestaw."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return RuleSet()
    except (OSError, UnicodeDecodeError) as error:
        return RuleSet(errors=(RuleError(path.name, 0, "", "toml", str(error)),))
    return parse_rules(raw, path.name, taken_codes=taken_codes)


class RulesStore(QObject):
    """Bieżący zestaw reguł z sygnałem zmiany (bez restartu)."""

    rules_changed = Signal()

    def __init__(self, path: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._path = path
        self._user = RuleSet()

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else user_rules_path()

    def load(self) -> RuleSet:
        self._user = read_rules_file(self.path, builtin_codes())
        return self._user

    @property
    def builtin(self) -> tuple[PhoneticRule, ...]:
        return builtin_rules().rules

    @property
    def user_rules(self) -> tuple[PhoneticRule, ...]:
        return self._user.rules

    @property
    def rules(self) -> tuple[PhoneticRule, ...]:
        return (*self.builtin, *self.user_rules)

    @property
    def errors(self) -> tuple[RuleError, ...]:
        return (*builtin_rules().errors, *self._user.errors)

    def save_user_rules(self, rules: Iterable[PhoneticRule]) -> None:
        """Zapisuje reguły użytkownika i powiadamia komponenty.

        Błąd zapisu (``ProjectError``) przechodzi do wywołującego.
        """
        rules = tuple(rules)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # błąd zgłosi ``write_atomic`` jako ``ProjectError``
        write_atomic(self.path, dumps_rules(rules).encode("utf-8"))
        self._user = RuleSet(rules)
        self.rules_changed.emit()
