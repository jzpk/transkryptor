"""Profile notacji (bez Qt): przechwycenie ustawień, format pliku, biblioteka."""

import json
from dataclasses import replace

import pytest

from transkryptor.document.metadata import DEFAULT_FIELDS, encode_fields
from transkryptor.document.project import ProjectState, load_project, save_project
from transkryptor.document.project.migrations import migrate
from transkryptor.errors import ProfileError
from transkryptor.profiles import (
    PROFILE_FORMAT,
    DraftNotation,
    NotationProfile,
    ProfileLibrary,
    apply_profile,
    capture,
    dumps_profile,
    loads_profile,
    read_profile,
    unique_name,
)
from transkryptor.settings import (
    AppearanceSettings,
    AsrSettings,
    EditorSettings,
    ExportSettings,
    MetadataSettings,
    NotationSettings,
    Settings,
    SnippetSettings,
    ValidatorSettings,
    from_mapping,
    to_mapping,
)

RULES = '[[rule]]\ncode = "USR-A"\npattern = "a"\nreplacement = "å"\n'


def team_settings() -> Settings:
    fields = (*DEFAULT_FIELDS[:2], replace(DEFAULT_FIELDS[2], enabled=False))
    return Settings(
        validator=ValidatorSettings(overrides_spec='{"NOT-1": false}'),
        snippets=SnippetSettings(spec='[{"text": "a^1", "shortcut": "Ctrl+Alt+1"}]'),
        editor=EditorSettings(autocomplete=True, font_size_pt=14),
        notation=NotationSettings(ellipsis_style="ascii"),
        export=ExportSettings(template_path="/zespol/szablon.docx"),
        metadata=MetadataSettings(fields_spec=encode_fields(fields)),
        asr=AsrSettings(
            expand_abbreviations=False,
            lowercase_plain=False,
            verbatim=False,
            qa_layout=True,
            region="gorny-slask",
        ),
    )


class TestCaptureAndApply:
    def test_round_trip_through_settings(self) -> None:
        profile = capture("Zespół A", team_settings(), RULES)
        applied = apply_profile(profile, Settings())
        assert capture("Zespół A", applied, RULES) == profile
        assert applied.profiles.active == "Zespół A"
        assert applied.asr.qa_layout is True
        assert applied.asr.region == "gorny-slask"

    def test_draft_notation_switches_but_model_stays(self) -> None:
        settings = replace(
            team_settings(), asr=replace(team_settings().asr, model_key="small")
        )
        applied = apply_profile(NotationProfile("Pusty"), settings)
        assert applied.asr.model_key == "small"
        assert applied.asr.region == ""
        assert applied.asr.qa_layout is False
        assert applied.asr.expand_abbreviations is True

    def test_apply_keeps_fields_outside_the_profile(self) -> None:
        settings = replace(
            Settings(),
            editor=EditorSettings(font_size_pt=20, zoom_pct=150),
            appearance=AppearanceSettings(theme="dark"),
        )
        applied = apply_profile(NotationProfile("Pusty"), settings)
        assert applied.editor.font_size_pt == 20
        assert applied.editor.zoom_pct == 150
        assert applied.appearance.theme == "dark"
        assert applied.validator.overrides_spec == ""


class TestFileFormat:
    def test_round_trip(self) -> None:
        profile = capture("Gwara śląska", team_settings(), RULES)
        assert loads_profile(dumps_profile(profile), "plik.json") == profile

    def test_file_is_readable_json(self) -> None:
        data = json.loads(dumps_profile(capture("A", team_settings(), RULES)))
        assert data["format"] == PROFILE_FORMAT
        assert data["validator"] == {"NOT-1": False}
        assert data["snippets"] == [{"text": "a^1", "shortcut": "Ctrl+Alt+1"}]
        assert data["docx_template"] == "/zespol/szablon.docx"
        assert data["metadata_fields"][2]["enabled"] is False
        assert data["asr_draft"] == {
            "expand_abbreviations": False,
            "lowercase_plain": False,
            "verbatim": False,
            "qa_layout": True,
            "region": "gorny-slask",
        }

    def test_older_profile_without_draft_gets_defaults(self) -> None:
        raw = json.dumps({"format": PROFILE_FORMAT, "version": 1, "name": "A"})
        assert loads_profile(raw, "a.json").draft == DraftNotation()

    def test_unknown_region_falls_back_to_none(self) -> None:
        raw = json.dumps(
            {
                "format": PROFILE_FORMAT,
                "version": 1,
                "name": "A",
                "asr_draft": {"region": "atlantyda", "qa_layout": True},
            }
        )
        draft = loads_profile(raw, "a.json").draft
        assert draft.region == ""
        assert draft.qa_layout is True

    def test_default_profile_has_no_metadata_override(self) -> None:
        data = json.loads(dumps_profile(NotationProfile("A")))
        assert data["metadata_fields"] is None
        assert loads_profile(json.dumps(data), "a.json") == NotationProfile("A")

    @pytest.mark.parametrize(
        "raw",
        [
            "nie json",
            "[]",
            json.dumps({"format": "coś innego", "version": 1, "name": "A"}),
            json.dumps({"format": PROFILE_FORMAT, "version": 1, "name": ""}),
            json.dumps(
                {"format": PROFILE_FORMAT, "version": 1, "name": "A", "snippets": 5}
            ),
            json.dumps(
                {
                    "format": PROFILE_FORMAT,
                    "version": 1,
                    "name": "A",
                    "ellipsis_style": "kropki",
                }
            ),
            json.dumps(
                {
                    "format": PROFILE_FORMAT,
                    "version": 1,
                    "name": "A",
                    "asr_draft": {"verbatim": "tak"},
                }
            ),
        ],
    )
    def test_invalid_file_is_rejected(self, raw: str) -> None:
        with pytest.raises(ProfileError, match="zly.json"):
            loads_profile(raw, "zly.json")

    def test_newer_format_is_rejected(self) -> None:
        raw = json.dumps({"format": PROFILE_FORMAT, "version": 99, "name": "A"})
        with pytest.raises(ProfileError, match="nowszej wersji"):
            loads_profile(raw, "nowy.json")

    def test_missing_file(self, tmp_path) -> None:
        with pytest.raises(ProfileError):
            read_profile(tmp_path / "brak.json")


class TestLibrary:
    def test_save_list_load_delete(self, tmp_path) -> None:
        library = ProfileLibrary(tmp_path / "profiles")
        assert library.names() == []
        library.save(NotationProfile("Zespół B", autocomplete=True))
        library.save(NotationProfile("Ąfryka"))
        library.save(NotationProfile("zespół a"))
        assert library.names() == ["Ąfryka", "zespół a", "Zespół B"]
        loaded = library.load("Zespół B")
        assert loaded is not None
        assert loaded.autocomplete
        library.delete("Ąfryka")
        assert library.names() == ["zespół a", "Zespół B"]

    def test_save_overwrites_profile_with_same_name(self, tmp_path) -> None:
        library = ProfileLibrary(tmp_path)
        library.save(NotationProfile("A"))
        library.save(NotationProfile("A", ellipsis_style="ascii"))
        assert len(list(tmp_path.glob("*.json"))) == 1
        assert library.load("A") == NotationProfile("A", ellipsis_style="ascii")

    def test_names_with_same_file_stem_get_separate_files(self, tmp_path) -> None:
        library = ProfileLibrary(tmp_path)
        library.save(NotationProfile("Zespół/A"))
        library.save(NotationProfile("Zespół A"))
        assert library.names() == ["Zespół A", "Zespół/A"]
        assert len(list(tmp_path.glob("*.json"))) == 2

    def test_rename_keeps_contents(self, tmp_path) -> None:
        library = ProfileLibrary(tmp_path)
        library.save(NotationProfile("Stary", rules_toml=RULES))
        renamed = library.rename("Stary", "Nowy")
        assert renamed == NotationProfile("Nowy", rules_toml=RULES)
        assert library.names() == ["Nowy"]
        assert library.rename("Brak", "X") is None

    def test_broken_file_is_skipped(self, tmp_path) -> None:
        (tmp_path / "zepsuty.json").write_text("{", encoding="utf-8")
        library = ProfileLibrary(tmp_path)
        library.save(NotationProfile("Dobry"))
        assert library.names() == ["Dobry"]


def test_unique_name() -> None:
    assert unique_name("  Zespół   A ", []) == "Zespół A"
    assert unique_name("A", ["A", "A (2)"]) == "A (3)"
    assert unique_name("", []) == "Domyślny"


class TestProjectProfile:
    def test_project_remembers_profile(self, tmp_path) -> None:
        path = tmp_path / "wywiad.transkr"
        save_project(ProjectState(text="tekst", profile="Zespół A"), path)
        assert load_project(path).profile == "Zespół A"

    def test_old_project_has_no_profile(self) -> None:
        migrated = migrate(
            {"schema_version": 7, "document": {"text": ""}, "work": {"seconds": 0}}
        )
        assert migrated["profile"] == ""
        assert migrated["schema_version"] == 8


class TestAccessibilitySettings:
    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.editor.zoom_pct == 100
        assert settings.appearance.ui_scale_pct == 100
        assert not settings.appearance.reduce_motion
        assert settings.profiles.active == ""

    def test_round_trip(self) -> None:
        settings = Settings(
            editor=EditorSettings(zoom_pct=150),
            appearance=AppearanceSettings(
                theme="high_contrast", ui_scale_pct=175, reduce_motion=True
            ),
        )
        assert from_mapping(to_mapping(settings)) == settings

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("editor/zoom_pct", 20),
            ("editor/zoom_pct", 1000),
            ("appearance/ui_scale_pct", 50),
            ("appearance/ui_scale_pct", 300),
        ],
    )
    def test_out_of_range_falls_back(self, key: str, value: int) -> None:
        assert from_mapping({key: value}) == Settings()
