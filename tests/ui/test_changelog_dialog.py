"""Przycisk i okno „Co nowego” z historią zmian."""

from transkryptor import __version__, i18n
from transkryptor.ui.changelog_dialog import ChangelogDialog
from transkryptor.ui.main_window import MainWindow

SAMPLE = """\
# Historia zmian

Wstęp.

## Nieopublikowane

## 0.3.0 — 2026-10-10

- Nowa funkcja **pogrubiona**.
"""


def test_status_bar_button_sits_in_bottom_left_corner(qtbot, add_window) -> None:
    window = add_window(MainWindow())
    window.resize(1200, 800)
    window.show()
    qtbot.waitExposed(window)
    button = window.changelog_button
    assert __version__ in button.text()
    status = window.statusBar()
    left = button.mapTo(status, button.rect().topLeft()).x()
    label = window.export_status_label
    assert left < status.width() // 4
    assert left < label.mapTo(status, label.rect().topLeft()).x()


def test_button_opens_dialog(qtbot, add_window, monkeypatch) -> None:
    window = add_window(MainWindow())
    opened: list[ChangelogDialog] = []

    def fake_exec(dialog: ChangelogDialog) -> int:
        opened.append(dialog)
        return 0

    monkeypatch.setattr(ChangelogDialog, "exec", fake_exec)
    window.changelog_button.click()
    assert len(opened) == 1
    assert __version__ in opened[0].browser.toPlainText()


def test_dialog_renders_markdown_without_intro(qtbot) -> None:
    dialog = ChangelogDialog(text=SAMPLE)
    qtbot.addWidget(dialog)
    text = dialog.browser.toPlainText()
    assert "0.3.0 — 2026-10-10" in text
    assert "Nowa funkcja pogrubiona." in text
    assert "**" not in text
    assert "Wstęp" not in text
    assert "Nieopublikowane" not in text
    assert dialog.language_note.isHidden()


def test_missing_changelog_is_explained(qtbot, monkeypatch) -> None:
    monkeypatch.setattr("transkryptor.ui.changelog_dialog.changelog_text", lambda: None)
    dialog = ChangelogDialog()
    qtbot.addWidget(dialog)
    assert "nie jest dostępna" in dialog.browser.toPlainText()


def test_english_interface_mentions_polish_only(qtbot) -> None:
    i18n.set_language(i18n.ENGLISH)
    dialog = ChangelogDialog(text=SAMPLE)
    qtbot.addWidget(dialog)
    assert not dialog.language_note.isHidden()
    assert "Polish only" in dialog.language_note.text()


def test_dialog_explains_how_to_report_a_problem(qtbot, monkeypatch, tmp_path) -> None:
    opened: list[str] = []

    def open_url(url) -> bool:
        opened.append(url.toString())
        return True

    monkeypatch.setattr(
        "transkryptor.ui.changelog_dialog.QDesktopServices.openUrl", open_url
    )
    monkeypatch.setattr(
        "transkryptor.ui.changelog_dialog.diagnostics.log_dir",
        lambda: tmp_path / "logs",
    )
    dialog = ChangelogDialog(text=SAMPLE)
    qtbot.addWidget(dialog)
    assert "transkryptor.log" in dialog.report_note.text()

    dialog.open_logs_button.click()
    assert (tmp_path / "logs").is_dir()
    assert opened[-1].startswith("file://")
    assert opened[-1].endswith("/logs")

    dialog.report_button.click()
    assert opened[-1].startswith("https://github.com/jzpk/transkryptor/issues/new?")
    assert __version__ in opened[-1]
