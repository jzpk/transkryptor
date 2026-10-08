"""Dzienny limit zapytań do GitHub Releases API.

Nieuwierzytelnione API ma limit na adres IP, a wiele instalacji może dzielić
jeden adres (sieć instytucji). Dlatego aplikacja wykonuje najwyżej
``DAILY_LIMIT`` zapytań na dobę, licząc także ręczne sprawdzenia.

Stan leży w pliku JSON w katalogu danych użytkownika::

    {"date": "2026-10-08", "requests": 1, "latest": {...} | null}

Stan z innego dnia jest odrzucany przy odczycie i nadpisywany przy zapisie —
stare dane nie zalegają. ``latest`` to wynik ostatniego zapytania z tego dnia:
ponowienie nieudanego pobrania pliku nie wymaga kolejnego zapytania do API.
Uszkodzony lub nieczytelny plik oznacza stan pusty i nie blokuje startu.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from transkryptor.paths import user_data_dir
from transkryptor.update.releases import ReleaseInfo

DAILY_LIMIT = 2
STATE_FILE_NAME = "update-state.json"


def default_state_path() -> Path:
    return user_data_dir() / STATE_FILE_NAME


@dataclass
class _State:
    day: str
    requests: int = 0
    latest: dict[str, Any] | None = None


class RequestQuota:
    """Licznik zapytań z bieżącej doby, trwały między uruchomieniami."""

    def __init__(self, path: Path | None = None, limit: int = DAILY_LIMIT) -> None:
        self.path = path or default_state_path()
        self.limit = limit
        # Stan, którego nie udało się zapisać (katalog tylko do odczytu):
        # limit działa wtedy przynajmniej do końca bieżącej sesji.
        self._unsaved: _State | None = None

    def remaining(self, today: date) -> int:
        return max(0, self.limit - self._load(today).requests)

    def try_acquire(self, today: date) -> bool:
        """Rezerwuje jedno zapytanie; False, gdy dzienny limit jest wyczerpany."""
        state = self._load(today)
        if state.requests >= self.limit:
            return False
        state.requests += 1
        self._save(state)
        return True

    def refund(self, today: date) -> None:
        """Zwraca rezerwację zapytania, które nie dotarło do serwera (brak sieci)."""
        state = self._load(today)
        if state.requests > 0:
            state.requests -= 1
            self._save(state)

    def cached_release(self, today: date) -> ReleaseInfo | None:
        """Wynik ostatniego zapytania z tej doby (None, gdy go nie ma)."""
        raw = self._load(today).latest
        if raw is None:
            return None
        try:
            return ReleaseInfo.from_dict(raw)
        except ValueError:
            return None

    def remember(self, today: date, release: ReleaseInfo | None) -> None:
        state = self._load(today)
        state.latest = release.to_dict() if release is not None else None
        self._save(state)

    def _load(self, today: date) -> _State:
        day = today.isoformat()
        if self._unsaved is not None and self._unsaved.day == day:
            return replace(self._unsaved)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _State(day)
        if not isinstance(data, dict) or data.get("date") != day:
            return _State(day)
        requests = data.get("requests")
        latest = data.get("latest")
        return _State(
            day,
            requests if isinstance(requests, int) and requests >= 0 else 0,
            latest if isinstance(latest, dict) else None,
        )

    def _save(self, state: _State) -> None:
        """Zapis atomowy: przerwany zapis nie zostawia uciętego pliku."""
        payload: dict[str, Any] = {
            "date": state.day,
            "requests": state.requests,
            "latest": state.latest,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            # Brak zapisu nie może zablokować pracy aplikacji.
            self._unsaved = state
        else:
            self._unsaved = None
