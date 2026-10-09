"""Testy definicji pól metryczki (faza 08, propozycja 16)."""

from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    SIGNATURE,
    MetadataField,
    decode_fields,
    encode_fields,
    export_items,
    new_custom_field,
    signature_from_audio,
)


def test_default_fields_mark_informant_data_as_personal() -> None:
    personal = {field.key for field in DEFAULT_FIELDS if field.personal}
    assert personal == {"informant", "informant_birth_year"}
    assert DEFAULT_FIELDS[0].key == SIGNATURE


def test_encode_decode_round_trip_with_custom_field() -> None:
    custom = new_custom_field("Numer taśmy", personal=False)
    fields = (custom, *DEFAULT_FIELDS[:2])
    decoded = decode_fields(encode_fields(fields))
    assert decoded is not None
    assert decoded[:3] == fields
    assert custom.is_custom and not DEFAULT_FIELDS[0].is_custom


def test_missing_default_fields_are_appended() -> None:
    decoded = decode_fields(encode_fields(DEFAULT_FIELDS[1:]))
    assert decoded is not None
    assert decoded[-1].key == SIGNATURE
    assert {field.key for field in decoded} == {field.key for field in DEFAULT_FIELDS}


def test_empty_spec_means_defaults_and_garbage_is_rejected() -> None:
    assert decode_fields("") == DEFAULT_FIELDS
    for raw in ("nie json", "{}", '[{"key": 1}]', '[{"key": "a", "label": ""}]'):
        assert decode_fields(raw) is None
    duplicate = '[{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]'
    assert decode_fields(duplicate) is None


def test_export_items_keep_order_skip_empty_and_anonymize() -> None:
    metadata = {
        "informant": "KA",
        SIGNATURE: "AdK_1954",
        "place": " ",
        "obce": "wartość",
    }
    items = export_items(metadata, DEFAULT_FIELDS)
    assert [(f.key, v) for f, v in items] == [
        (SIGNATURE, "AdK_1954"),
        ("informant", "KA"),
        ("obce", "wartość"),  # pole spoza konfiguracji nie ginie
    ]
    anonymized = export_items(metadata, DEFAULT_FIELDS, anonymize=True)
    assert [f.key for f, _v in anonymized] == [SIGNATURE, "obce"]


def test_hidden_field_values_are_exported_after_visible() -> None:
    fields = tuple(
        MetadataField(f.key, f.label, f.personal, enabled=f.key != SIGNATURE)
        for f in DEFAULT_FIELDS
    )
    items = export_items({SIGNATURE: "X", "place": "Ocieszyn"}, fields)
    assert [f.key for f, _v in items] == ["place", SIGNATURE]


def test_signature_hint_from_audio_file_name() -> None:
    assert signature_from_audio("/nagrania/AdK_1954.aac") == "AdK_1954"
    assert signature_from_audio("JaE_1979_przesądy.mp3") == "JaE_1979_przesądy"
