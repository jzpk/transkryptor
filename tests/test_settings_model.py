"""Testy modelu ustawień (bez Qt): wartości domyślne i walidacja (ACC-18)."""

from transkryptor.settings import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_KEY,
    EditorSettings,
    PlayerSettings,
    Settings,
    from_mapping,
    to_mapping,
)


def test_defaults_match_phase_decision() -> None:
    settings = Settings()
    assert settings.player == PlayerSettings(
        skip_ms=3000,
        auto_rewind_enabled=True,
        auto_rewind_ms=1500,
        segment_preroll_ms=500,
    )
    assert settings.editor == EditorSettings(font_family="", font_size_pt=0)


def test_round_trip() -> None:
    settings = Settings(
        player=PlayerSettings(
            skip_ms=5000,
            auto_rewind_enabled=False,
            auto_rewind_ms=2000,
            segment_preroll_ms=0,
        ),
        editor=EditorSettings(font_family="Gentium", font_size_pt=16),
    )
    mapping = to_mapping(settings)
    assert mapping[SCHEMA_VERSION_KEY] == SCHEMA_VERSION
    assert mapping["player/skip_ms"] == 5000
    assert from_mapping(mapping) == settings


def test_empty_mapping_gives_defaults() -> None:
    assert from_mapping({}) == Settings()


def test_accepts_ini_strings() -> None:
    """QSettings w formacie INI zwraca wartości jako tekst."""
    settings = from_mapping(
        {
            "player/skip_ms": "4000",
            "player/auto_rewind_enabled": "false",
            "editor/font_size_pt": " 14 ",
        }
    )
    assert settings.player.skip_ms == 4000
    assert settings.player.auto_rewind_enabled is False
    assert settings.editor.font_size_pt == 14


def test_invalid_fields_fall_back_individually() -> None:
    settings = from_mapping(
        {
            "player/skip_ms": "dużo",  # nie liczba
            "player/auto_rewind_ms": 999_999,  # poza zakresem
            "player/auto_rewind_enabled": "może",  # nie bool
            "player/segment_preroll_ms": -1,  # poza zakresem
            "editor/font_family": 12,  # zły typ
            "editor/font_size_pt": 2,  # poza zakresem
            "player/unknown": 1,  # nieznany klucz
            "schema_version": "x",
        }
    )
    assert settings == Settings()


def test_valid_fields_survive_next_to_invalid() -> None:
    settings = from_mapping({"player/skip_ms": "bzdura", "player/auto_rewind_ms": 0})
    assert settings.player.skip_ms == PlayerSettings().skip_ms
    assert settings.player.auto_rewind_ms == 0


def test_bool_is_not_accepted_as_number() -> None:
    assert from_mapping({"player/skip_ms": True}).player.skip_ms == 3000


def test_ellipsis_style_defaults_to_unicode() -> None:
    """Decyzja fazy 07: domyślny zapis wielokropka to `…`."""
    from transkryptor.notation.ellipsis import EllipsisStyle

    assert Settings().notation.ellipsis is EllipsisStyle.UNICODE


def test_ellipsis_style_round_trip_and_unknown_value() -> None:
    from transkryptor.settings import NotationSettings

    settings = Settings(notation=NotationSettings(ellipsis_style="ascii"))
    mapping = to_mapping(settings)
    assert mapping["notation/ellipsis_style"] == "ascii"
    assert from_mapping(mapping) == settings
    assert from_mapping({"notation/ellipsis_style": "kropki"}) == Settings()


def test_project_and_metadata_settings_round_trip() -> None:
    from transkryptor.document.metadata import DEFAULT_FIELDS, encode_fields
    from transkryptor.settings import MetadataSettings, ProjectSettings

    spec = encode_fields(reversed(DEFAULT_FIELDS))
    settings = Settings(
        project=ProjectSettings(autosave_enabled=False, autosave_interval_s=120),
        metadata=MetadataSettings(fields_spec=spec),
    )
    restored = from_mapping(to_mapping(settings))
    assert restored == settings
    assert restored.metadata.fields[0].key == DEFAULT_FIELDS[-1].key


def test_invalid_project_and_metadata_values_fall_back() -> None:
    settings = from_mapping(
        {
            "project/autosave_interval_s": 5,  # poniżej 30 s
            "project/autosave_enabled": "nie wiem",
            "metadata/fields_spec": "[zepsute",
        }
    )
    assert settings == Settings()
    assert Settings().project.autosave_enabled
    assert Settings().project.autosave_interval_s == 60


def test_push_recent_moves_to_front_without_duplicates() -> None:
    from transkryptor.settings import push_recent

    paths = [f"/p/{i}.transkr" for i in range(8)]
    result = push_recent(paths, "/p/3.transkr")
    assert result[0] == "/p/3.transkr"
    assert len(result) == 8 and len(set(result)) == 8
    assert push_recent(paths, "/p/nowy.transkr")[-1] == "/p/6.transkr"


def test_theme_defaults_to_system_and_validates() -> None:
    from transkryptor.settings import AppearanceSettings

    assert Settings().appearance.theme == "system"
    settings = Settings(appearance=AppearanceSettings(theme="dark"))
    assert to_mapping(settings)["appearance/theme"] == "dark"
    assert from_mapping(to_mapping(settings)) == settings
    assert from_mapping({"appearance/theme": "różowy"}) == Settings()


def test_language_defaults_to_system_and_validates() -> None:
    from transkryptor.settings import AppearanceSettings

    assert Settings().appearance.language == "system"
    settings = Settings(appearance=AppearanceSettings(language="en"))
    assert to_mapping(settings)["appearance/language"] == "en"
    assert from_mapping(to_mapping(settings)) == settings
    assert from_mapping({"appearance/language": "klingoński"}) == Settings()
