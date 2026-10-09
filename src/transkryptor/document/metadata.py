"""Pola metryczki nagrania (bez zależności od Qt).

Metryczka to dane opisowe nagrania zapisywane w ``Document.metadata`` jako
słownik klucz → wartość, obok autora i daty transkrypcji. Ten moduł
definiuje pola (klucz, etykieta, czy zawierają dane osobowe), ich domyślny
zestaw oraz kodowanie konfiguracji zespołu (kolejność, widoczność, własne
pola) używane przez ustawienia, formularz, eksport i import DOCX.

Pola „osobowe” są pomijane w eksporcie anonimizowanym.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from transkryptor.i18n import all_translations, tr

SIGNATURE = "signature"
PLACE = "place"


@dataclass(frozen=True)
class MetadataField:
    """Pole metryczki: ``enabled`` = widoczne w formularzu i w eksporcie."""

    key: str
    label: str
    personal: bool = False
    enabled: bool = True

    @property
    def is_custom(self) -> bool:
        return self.key not in DEFAULT_KEYS

    @property
    def display_label(self) -> str:
        """Etykieta do pokazania: pola domyślne w języku interfejsu.

        ``label`` pól domyślnych to wartość kanoniczna (zapis ustawień
        i projektów); zespół nie może jej zmienić, więc wyświetla się
        tłumaczenie. Pola własne mają etykietę nadaną przez zespół.
        """
        return self.label if self.is_custom else tr(label_key(self.key))


def label_key(key: str) -> str:
    """Klucz tłumaczenia etykiety pola domyślnego."""
    return f"metadata.field.{key}"


def label_variants(field: MetadataField) -> tuple[str, ...]:
    """Etykiety, pod którymi pole może wystąpić w dokumencie (wszystkie języki)."""
    if field.is_custom:
        return (field.label,)
    return (field.label, *all_translations(label_key(field.key)))


DEFAULT_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(SIGNATURE, "Sygnatura"),
    MetadataField(PLACE, "Miejscowość"),
    MetadataField("district", "Gmina/powiat"),
    MetadataField("informant", "Informator (kod)", personal=True),
    MetadataField("informant_birth_year", "Rok urodzenia informatora", personal=True),
    MetadataField("recording_date", "Data nagrania"),
    MetadataField("researcher", "Badacz"),
    MetadataField("notes", "Uwagi"),
)
DEFAULT_KEYS = frozenset(field.key for field in DEFAULT_FIELDS)
CUSTOM_KEY_PREFIX = "custom-"


def new_custom_field(label: str, personal: bool = False) -> MetadataField:
    """Własne pole zespołu z unikalnym kluczem."""
    return MetadataField(
        f"{CUSTOM_KEY_PREFIX}{uuid.uuid4().hex[:8]}", label.strip(), personal
    )


def encode_fields(fields: Iterable[MetadataField]) -> str:
    """Konfiguracja pól jako JSON (wartość ustawienia ``metadata/fields``)."""
    return json.dumps(
        [
            {
                "key": field.key,
                "label": field.label,
                "personal": field.personal,
                "enabled": field.enabled,
            }
            for field in fields
        ],
        ensure_ascii=False,
    )


def decode_fields(raw: str) -> tuple[MetadataField, ...] | None:
    """Odczytuje konfigurację pól; None, gdy zapis jest uszkodzony.

    Pusty napis oznacza zestaw domyślny. Pola domyślne nieobecne w zapisie
    (np. dodane w nowszej wersji) są dopisywane na końcu jako widoczne.
    """
    if not raw.strip():
        return DEFAULT_FIELDS
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    fields: list[MetadataField] = []
    seen: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            return None
        key, label = entry.get("key"), entry.get("label")
        personal, enabled = entry.get("personal", False), entry.get("enabled", True)
        if not (isinstance(key, str) and key and isinstance(label, str) and label):
            return None
        if not (isinstance(personal, bool) and isinstance(enabled, bool)):
            return None
        if key in seen:
            return None
        seen.add(key)
        fields.append(MetadataField(key, label, personal, enabled))
    fields.extend(field for field in DEFAULT_FIELDS if field.key not in seen)
    return tuple(fields)


def enabled_fields(fields: Iterable[MetadataField]) -> tuple[MetadataField, ...]:
    return tuple(field for field in fields if field.enabled)


def export_items(
    metadata: Mapping[str, str],
    fields: Iterable[MetadataField],
    anonymize: bool = False,
) -> list[tuple[MetadataField, str]]:
    """Niepuste pola metryczki do eksportu w kolejności konfiguracji.

    Wartości pól spoza konfiguracji (np. z projektu innego zespołu albo
    pola ukrytego) nie giną: trafiają na koniec z etykietą domyślną albo
    kluczem. ``anonymize`` pomija pola osobowe.
    """
    configured = list(fields)
    known = {field.key: field for field in (*DEFAULT_FIELDS, *configured)}
    order = [field.key for field in configured if field.enabled]
    order += [key for key in metadata if key not in order]
    items: list[tuple[MetadataField, str]] = []
    for key in order:
        value = metadata.get(key, "").strip()
        if not value:
            continue
        field = known.get(key, MetadataField(key, key))
        if anonymize and field.personal:
            continue
        items.append((replace(field, enabled=True), value))
    return items


def signature_from_audio(path: str | Path) -> str:
    """Podpowiedź sygnatury z nazwy nagrania: ``AdK_1954.aac`` → ``AdK_1954``."""
    return Path(path).stem.strip()


def normalized(values: Mapping[str, str]) -> dict[str, str]:
    """Słownik bez pustych wartości (porównywalny między zapisami)."""
    return {key: value for key, value in values.items() if value.strip()}
