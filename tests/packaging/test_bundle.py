"""Testy zawartości artefaktu: co PyInstaller musi spakować."""

from pathlib import Path

import pytest

from transkryptor.packaging import bundle


def test_entry_script_is_the_application_entry_point() -> None:
    assert bundle.ENTRY_SCRIPT.is_file()
    assert bundle.ENTRY_SCRIPT.name == "__main__.py"
    assert (bundle.SOURCE_ROOT / "transkryptor").is_dir()


def test_vad_asset_is_collected() -> None:
    """Bez modelu Silero VAD transkrypcja w artefakcie kończy się błędem."""
    datas = bundle.collect_datas()
    sources = [Path(source).name for source, _ in datas]
    destinations = {destination for _, destination in datas}
    assert any(name.endswith(".onnx") for name in sources)
    assert "faster_whisper/assets" in destinations


def test_collected_data_sources_exist() -> None:
    for source, _ in bundle.collect_datas():
        assert Path(source).is_file()


def test_hidden_imports_cover_lazily_loaded_stack() -> None:
    """Silnik ASR i pobieranie modelu importują się dopiero w czasie pracy."""
    assert {"faster_whisper", "ctranslate2", "httpx", "huggingface_hub"} <= set(
        bundle.HIDDEN_IMPORTS
    )


def test_excludes_do_not_remove_modules_the_application_uses() -> None:
    used = {
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        "PySide6.QtCore",
        "PySide6.QtMultimedia",
        "PySide6.QtSvg",
        "docx",
        "av",
        "onnxruntime",
    }
    assert used.isdisjoint(bundle.EXCLUDED_MODULES)


def test_excludes_drop_development_tools() -> None:
    assert {"pytest", "PyInstaller"} <= set(bundle.EXCLUDED_MODULES)


def test_analysis_options_describe_a_windowed_onedir_build() -> None:
    options = bundle.analysis_options("linux")
    assert options["console"] is False
    # UPX psuje biblioteki Qt i bywa wykrywany jako zagrożenie.
    assert options["upx"] is False
    assert options["name"] == bundle.BUNDLE_NAME
    assert options["pathex"] == [str(bundle.SOURCE_ROOT)]


def test_icon_matches_platform() -> None:
    assert str(bundle.icon_for("win32")).endswith(".ico")
    assert str(bundle.icon_for("linux")).endswith(".png")


def test_native_libraries_are_never_stripped() -> None:
    """strip uszkadza OpenBLAS z numpy w AppImage — ASR przestaje działać."""
    assert bundle.analysis_options("linux")["strip"] is False
    assert bundle.analysis_options("win32")["strip"] is False


def test_missing_package_reports_the_build_group() -> None:
    with pytest.raises(FileNotFoundError) as error:
        bundle.package_directory("pakiet_ktorego_nie_ma")
    assert "--group packaging" in str(error.value)
