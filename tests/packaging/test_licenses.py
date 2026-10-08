"""Testy kompletu licencji dołączanego do artefaktu wydania.

Wymaganie wydania: „licencje aplikacji, zależności i modelu są dołączone do
artefaktu” (specs/acceptance.md).
"""

from importlib import metadata as importlib_metadata
from typing import cast

import pytest

from transkryptor.packaging import licenses


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """Pełny komplet licencji zbudowany raz dla całego modułu testów."""
    destination = tmp_path_factory.mktemp("release") / "licenses"
    return licenses.write_license_bundle(destination)


def test_runtime_closure_contains_direct_and_transitive_dependencies() -> None:
    names = {dist.metadata["Name"].lower() for dist in licenses.runtime_distributions()}
    assert {"pyside6", "faster-whisper", "av", "httpx", "python-docx"} <= names
    # Zależności przechodnie stosu ASR.
    assert {"ctranslate2", "onnxruntime", "tokenizers", "numpy"} <= names


def test_runtime_closure_excludes_development_tools() -> None:
    names = {dist.metadata["Name"].lower() for dist in licenses.runtime_distributions()}
    assert "pytest" not in names
    assert "pyinstaller" not in names


def test_optional_extras_are_not_pulled_into_the_artifact() -> None:
    assert licenses._is_optional('requests>=2 ; extra == "http"')
    assert not licenses._is_optional('numpy>=1.26 ; python_version >= "3.9"')


def test_every_dependency_has_a_license_text(bundle) -> None:
    missing = [dist.name for dist in bundle.without_text()]
    assert missing == [], f"brak tekstu licencji: {missing}"


def test_application_license_is_included(bundle) -> None:
    text = (bundle.root / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text


def test_qt_license_text_is_supplied_even_though_the_wheel_omits_it(bundle) -> None:
    """Koła PySide6 nie zawierają tekstu LGPL — wydawca musi go dołożyć."""
    pyside = next(dist for dist in bundle.distributions if dist.name == "PySide6")
    assert pyside.has_text
    assert pyside.from_wheel is False
    text = (bundle.root / "third-party" / pyside.files[0]).read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text


def test_notices_list_native_libraries_and_their_sources(bundle) -> None:
    notices = bundle.notices.read_text(encoding="utf-8")
    assert "libx264" in notices
    assert "libx265" in notices
    assert "ffmpeg.org" in notices
    assert "GPL-2.0-or-later" in notices


def test_notices_explain_how_qt_can_be_replaced(bundle) -> None:
    """Warunek zgodności z LGPL-3.0 dla pakietowanego Qt."""
    notices = bundle.notices.read_text(encoding="utf-8")
    assert "podmienić" in notices
    assert "appimage-extract" in notices


def test_notices_mark_which_texts_came_from_the_publisher(bundle) -> None:
    notices = bundle.notices.read_text(encoding="utf-8")
    assert "koło PyPI" in notices
    assert "tekst kanoniczny dołączony przez wydawcę" in notices


def test_model_notice_states_it_is_not_redistributed(bundle) -> None:
    notice = (bundle.root / "MODEL-LICENSE.md").read_text(encoding="utf-8")
    assert "nie są częścią tego artefaktu" in notice
    assert "Systran/faster-whisper-medium" in notice
    assert "MIT" in notice


def test_license_identifier_prefers_spdx_expression() -> None:
    class FakeMetadata(dict):
        def get_all(self, _key):
            return ["License :: OSI Approved :: MIT License"]

    class FakeDistribution:
        metadata = FakeMetadata({"License-Expression": "BSD-3-Clause"})

    assert licenses.license_id_of(
        cast(importlib_metadata.Distribution, FakeDistribution())
    ) == ("BSD-3-Clause")


def test_license_identifier_falls_back_to_classifiers() -> None:
    class FakeMetadata(dict):
        def get_all(self, _key):
            return ["License :: OSI Approved :: MIT License"]

    class FakeDistribution:
        metadata = FakeMetadata()

    assert "MIT License" in licenses.license_id_of(
        cast(importlib_metadata.Distribution, FakeDistribution())
    )


def test_vendored_fallback_matches_lgpl_before_gpl() -> None:
    """„LGPL-3.0-only OR GPL-3.0-only” nie może trafić na tekst GPL."""
    files = licenses.vendored_license_files(
        "PySide6", "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
    )
    assert [path.name for path in files] == ["LGPL-3.0.txt"]


def test_vendored_fallback_is_empty_for_unknown_license() -> None:
    assert licenses.vendored_license_files("cokolwiek", "WTFPL") == []


def test_collecting_with_an_explicit_distribution_list(tmp_path) -> None:
    dist = importlib_metadata.distribution("httpx")
    collected = licenses.collect_distribution_licenses(tmp_path, [dist])
    assert len(collected) == 1
    assert collected[0].name == "httpx"
    assert collected[0].has_text


def test_missing_application_license_is_reported(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        licenses.write_license_bundle(
            tmp_path / "licenses", app_license=tmp_path / "nie-ma.txt"
        )
