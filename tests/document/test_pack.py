"""Paczka do przekazania: format ZIP z manifestem i scalanie ustawień."""

import json
import zipfile
from pathlib import Path

import pytest

from transkryptor.document.pack import (
    MANIFEST,
    PACK_VERSION,
    PackSettings,
    PackSource,
    conflicts,
    estimated_size,
    open_pack,
    read_manifest,
    write_pack,
)
from transkryptor.document.pack_settings import (
    ACCEPT,
    MERGE,
    NOTATION,
    RULES,
    SKIP,
    SNIPPETS,
    apply_pack_settings,
    available_groups,
)
from transkryptor.document.project import AudioRef, ProjectState, load_project
from transkryptor.errors import ProjectError
from transkryptor.notation.rules import PhoneticRule, dumps_rules
from transkryptor.settings import (
    NotationSettings,
    Settings,
    Snippet,
    SnippetSettings,
    ValidatorSettings,
    encode_snippets,
)

RULE_A = PhoneticRule("USR-A", {"*": "a"}, "a", "b", 0.5)
RULE_B = PhoneticRule("USR-B", {"*": "b"}, "b", "c", 0.5)


@pytest.fixture
def source(tmp_path) -> PackSource:
    audio = tmp_path / "nagrania" / "AdK 1954.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"ID3 nagranie")
    template = tmp_path / "szablon.docx"
    template.write_bytes(b"PK szablon")
    state = ProjectState(
        text="raz dwa",
        audio=AudioRef(str(audio), "abc123", relative_path="../nagrania/AdK 1954.mp3"),
    )
    return PackSource(
        state=state,
        project_name="wywiad.transkr",
        audio_path=audio,
        settings=PackSettings(
            rules_toml=dumps_rules([RULE_A]),
            snippets_spec=encode_snippets([Snippet("[śmiech]")]),
            ellipsis_style="unicode",
            validator_spec=json.dumps({"VAL-01": False}),
        ),
        template_path=template,
    )


def test_round_trip_with_audio(tmp_path, source) -> None:
    pack = tmp_path / "wywiad.tkpack"
    write_pack(pack, source)
    target = tmp_path / "odbiorca"
    opened = open_pack(pack, target)

    assert opened.manifest.version == PACK_VERSION
    assert opened.manifest.audio_included
    assert opened.project_path == target / "wywiad.transkr"
    assert opened.audio_path == target / "AdK 1954.mp3"
    assert (target / "AdK 1954.mp3").read_bytes() == b"ID3 nagranie"
    assert opened.template_path == target / "szablon.docx"
    assert opened.settings == source.settings
    state = load_project(opened.project_path)
    assert state.text == "raz dwa"
    assert state.audio is not None
    assert state.audio.relative_path == "AdK 1954.mp3"
    assert state.audio.sha256 == "abc123"


def test_without_audio(tmp_path, source) -> None:
    from dataclasses import replace

    pack = tmp_path / "bez.tkpack"
    write_pack(pack, replace(source, include_audio=False))
    with zipfile.ZipFile(pack) as archive:
        assert not any(name.startswith("audio/") for name in archive.namelist())
    manifest = read_manifest(pack)
    assert manifest.audio_name == "AdK 1954.mp3"
    assert manifest.audio_sha256 == "abc123"
    assert not manifest.audio_included
    opened = open_pack(pack, tmp_path / "odbiorca")
    assert opened.audio_path is None
    assert estimated_size(replace(source, include_audio=False)) < estimated_size(source)


def test_conflicts(tmp_path, source) -> None:
    pack = tmp_path / "p.tkpack"
    write_pack(pack, source)
    target = tmp_path / "odbiorca"
    target.mkdir()
    assert conflicts(read_manifest(pack), target) == []
    (target / "wywiad.transkr").write_text("stary", encoding="utf-8")
    assert conflicts(read_manifest(pack), target) == ["wywiad.transkr"]


def write_zip(path: Path, manifest: dict, members: dict[str, str] | None = None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(MANIFEST, json.dumps(manifest))
        for name, content in (members or {}).items():
            archive.writestr(name, content)


@pytest.mark.parametrize(
    "manifest",
    [
        {"format": "inny", "version": 1, "project": "a.transkr"},
        {"format": "transkryptor-pack", "version": 1, "project": "../a.transkr"},
        {"format": "transkryptor-pack", "version": 1, "project": "a.txt"},
        {
            "format": "transkryptor-pack",
            "version": 1,
            "project": "a.transkr",
            "audio": {"name": "../../etc/x", "included": True},
        },
    ],
)
def test_invalid_or_unsafe_pack_is_rejected(tmp_path, manifest) -> None:
    pack = tmp_path / "zla.tkpack"
    write_zip(pack, manifest)
    with pytest.raises(ProjectError):
        read_manifest(pack)


def test_not_a_zip_is_rejected(tmp_path) -> None:
    pack = tmp_path / "tekst.tkpack"
    pack.write_text("to nie jest zip", encoding="utf-8")
    with pytest.raises(ProjectError):
        open_pack(pack, tmp_path / "x")


def test_newer_pack_asks_for_update(tmp_path) -> None:
    pack = tmp_path / "nowa.tkpack"
    write_zip(
        pack,
        {"format": "transkryptor-pack", "version": PACK_VERSION + 1, "project": "a"},
    )
    with pytest.raises(ProjectError) as info:
        read_manifest(pack)
    assert "nowszą wersją" in info.value.user_message


def test_only_listed_members_are_extracted(tmp_path, source) -> None:
    pack = tmp_path / "p.tkpack"
    write_pack(pack, source)
    with zipfile.ZipFile(pack, "a") as archive:
        archive.writestr("../poza.txt", "x")
    target = tmp_path / "odbiorca"
    open_pack(pack, target)
    assert not (tmp_path / "poza.txt").exists()


class TestSettings:
    PACK = PackSettings(
        rules_toml=dumps_rules([RULE_A, RULE_B]),
        snippets_spec=encode_snippets([Snippet("[śmiech]"), Snippet("[x]", "Ctrl+1")]),
        ellipsis_style="unicode",
        validator_spec=json.dumps({"VAL-01": False, "VAL-02": False}),
    )
    MINE = Settings(
        notation=NotationSettings(ellipsis_style="ascii"),
        validator=ValidatorSettings(overrides_spec=json.dumps({"VAL-01": True})),
        snippets=SnippetSettings(spec=encode_snippets([Snippet("[x]", "Ctrl+2")])),
    )
    MY_RULE = PhoneticRule("USR-A", {"*": "moja"}, "x", "y", 0.5)

    def test_groups(self) -> None:
        assert available_groups(self.PACK) == [RULES, SNIPPETS, NOTATION]
        assert available_groups(PackSettings()) == []

    def test_accept_replaces(self) -> None:
        choices = {RULES: ACCEPT, SNIPPETS: ACCEPT, NOTATION: ACCEPT}
        applied = apply_pack_settings(self.PACK, choices, self.MINE, [self.MY_RULE])
        assert applied.user_rules is not None
        assert [r.code for r in applied.user_rules] == ["USR-A", "USR-B"]
        assert applied.user_rules[0].pattern == "a"
        settings = applied.settings
        assert [s.text for s in settings.snippets.snippets] == ["[śmiech]", "[x]"]
        assert settings.notation.ellipsis_style == "unicode"
        assert settings.validator.overrides == {"VAL-01": False, "VAL-02": False}

    def test_merge_keeps_mine_and_adds_missing(self) -> None:
        choices = {RULES: MERGE, SNIPPETS: MERGE, NOTATION: MERGE}
        applied = apply_pack_settings(self.PACK, choices, self.MINE, [self.MY_RULE])
        assert applied.user_rules is not None
        assert [r.label for r in applied.user_rules] == [{"*": "moja"}, {"*": "b"}]
        settings = applied.settings
        assert [(s.text, s.shortcut) for s in settings.snippets.snippets] == [
            ("[x]", "Ctrl+2"),
            ("[śmiech]", ""),
        ]
        assert settings.notation.ellipsis_style == "ascii"
        assert settings.validator.overrides == {"VAL-01": True, "VAL-02": False}

    def test_skip_changes_nothing(self) -> None:
        choices = {RULES: SKIP, SNIPPETS: SKIP, NOTATION: SKIP}
        applied = apply_pack_settings(self.PACK, choices, self.MINE, [self.MY_RULE])
        assert applied.user_rules is None
        assert applied.settings == self.MINE
