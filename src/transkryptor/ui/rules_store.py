"""Reguły fonetyczne: wbudowane i z pliku użytkownika (``rules/user.toml``).

Plik użytkownika leży w katalogu danych aplikacji; zapis jest atomowy
(``fileio.write_atomic``). Błędy ładowania nie blokują pracy -
błędne reguły są pomijane, a ich opis udostępnia ``errors``. W tym samym
pliku są propozycje reguł z poprawek odrzucone przez transkrybenta
(``dismissed``) - plik jest roboczą kopią profilu notacji, więc odrzucenia
trafiają do profilu i jego eksportu (zgłoszenie #74).
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from transkryptor import paths
from transkryptor.fileio import write_atomic
from transkryptor.notation.rules import (
    DismissedKey,
    PhoneticRule,
    RuleError,
    RuleSet,
    builtin_codes,
    builtin_rules,
    dumps_rules,
    parse_dismissed,
    parse_rules,
)

USER_RULES_FILE = "user.toml"


def user_rules_path() -> Path:
    """Plik reguł użytkownika (podmieniany w testach)."""
    return paths.user_data_dir() / "rules" / USER_RULES_FILE


def read_rules_file(path: Path, taken_codes: Iterable[str]) -> RuleSet:
    """Reguły użytkownika z pliku; brak pliku to pusty zestaw."""
    return _read(path, taken_codes)[0]


def _read(
    path: Path, taken_codes: Iterable[str]
) -> tuple[RuleSet, tuple[DismissedKey, ...]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return RuleSet(), ()
    except (OSError, UnicodeDecodeError) as error:
        return RuleSet(errors=(RuleError(path.name, 0, "", "toml", str(error)),)), ()
    return parse_rules(raw, path.name, taken_codes=taken_codes), parse_dismissed(raw)


class RulesStore(QObject):
    """Bieżący zestaw reguł z sygnałem zmiany (bez restartu)."""

    rules_changed = Signal()

    def __init__(self, path: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._path = path
        self._user = RuleSet()
        self._dismissed: tuple[DismissedKey, ...] = ()

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else user_rules_path()

    def load(self) -> RuleSet:
        self._user, self._dismissed = _read(self.path, builtin_codes())
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

    @property
    def dismissed(self) -> tuple[DismissedKey, ...]:
        """Odrzucone propozycje reguł z poprawek (klucze zmian)."""
        return self._dismissed

    def save_user_rules(
        self,
        rules: Iterable[PhoneticRule],
        dismissed: Iterable[DismissedKey] | None = None,
    ) -> None:
        """Zapisuje reguły użytkownika (i odrzucenia) i powiadamia komponenty.

        ``dismissed`` None zostawia bieżące odrzucenia. Błąd zapisu
        (``ProjectError``) przechodzi do wywołującego.
        """
        rules = tuple(rules)
        kept = self._dismissed if dismissed is None else tuple(dict.fromkeys(dismissed))
        # Błąd zgłosi ``write_atomic`` jako ``ProjectError``.
        with contextlib.suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self.path, dumps_rules(rules, kept).encode("utf-8"))
        self._user = RuleSet(rules)
        self._dismissed = kept
        self.rules_changed.emit()

    def set_dismissed(self, key: DismissedKey, dismissed: bool = True) -> None:
        """Odrzuca propozycję (albo cofa odrzucenie) i zapisuje plik."""
        keys = [k for k in self._dismissed if k != key]
        if dismissed:
            keys.append(key)
        if tuple(keys) != self._dismissed:
            self.save_user_rules(self.user_rules, keys)
