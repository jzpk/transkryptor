"""Zakładka „Dziennik logów”: odnośnik do folderu i zgłoszenie problemu."""

import pytest

from transkryptor import __version__
from transkryptor.settings import Settings
from transkryptor.ui.log_panel import LogPanel
from transkryptor.ui.settings_dialog import SettingsDialog


@pytest.fixture
def opened(monkeypatch, tmp_path) -> list[str]:
    urls: list[str] = []

    def open_url(url) -> bool:
        urls.append(url.toString())
        return True

    monkeypatch.setattr("transkryptor.ui.log_panel.QDesktopServices.openUrl", open_url)
    monkeypatch.setattr(
        "transkryptor.ui.log_panel.diagnostics.log_dir", lambda: tmp_path / "logs"
    )
    return urls


def test_settings_have_log_tab(qtbot, opened) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    index = dialog.tabs.indexOf(dialog.log_panel)
    assert dialog.tabs.tabText(index) == "Dziennik logów"


def test_folder_link_opens_log_folder(qtbot, opened, tmp_path) -> None:
    panel = LogPanel()
    qtbot.addWidget(panel)
    folder = tmp_path / "logs"
    assert str(folder) in panel.folder_link.text()
    assert "href=" in panel.folder_link.text()

    panel.folder_link.linkActivated.emit("file://ignored")
    assert folder.is_dir()
    assert opened == [f"file://{folder}"]

    panel.open_button.click()
    assert opened[-1] == f"file://{folder}"


def test_report_opens_issue_form(qtbot, opened) -> None:
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.report_button.click()
    assert opened[-1].startswith("https://github.com/jzpk/transkryptor/issues/new?")
    assert __version__ in opened[-1]
