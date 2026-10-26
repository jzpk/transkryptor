"""Przycisk „Zgłoś problem lub pomysł” na pasku stanu."""

from transkryptor import __version__
from transkryptor.feedback import REPORT_FORM_URL
from transkryptor.ui.main_window import MainWindow


def test_report_button_opens_the_form_on_the_site(
    qtbot, add_window, monkeypatch
) -> None:
    opened: list[str] = []

    def open_url(url) -> bool:
        opened.append(url.toString())
        return True

    monkeypatch.setattr(
        "transkryptor.ui.main_window.QDesktopServices.openUrl", open_url
    )
    window = add_window(MainWindow())
    button = window.report_button
    assert button.text() == "Zgłoś problem lub pomysł"

    button.click()
    assert len(opened) == 1
    assert opened[0].startswith(f"{REPORT_FORM_URL}?")
    assert f"wersja={__version__}" in opened[0]


def test_report_button_sits_next_to_changelog(qtbot, add_window) -> None:
    window = add_window(MainWindow())
    window.resize(1200, 800)
    window.show()
    qtbot.waitExposed(window)
    status = window.statusBar()
    changelog = window.changelog_button
    report = window.report_button
    assert report.isVisible()
    changelog_right = changelog.mapTo(status, changelog.rect().topRight()).x()
    report_left = report.mapTo(status, report.rect().topLeft()).x()
    assert changelog_right < report_left < status.width() // 2
