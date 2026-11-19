"""Kolejka komunikatów: okna po kolei, nigdy jedno na drugim."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from transkryptor.ui.notice_queue import NoticeQueue


def modal_notice(name: str, log: list[str], stacked: list[str]):
    """Komunikat z prawdziwym oknem modalnym, zamykanym po chwili."""

    def show() -> None:
        if QApplication.activeModalWidget() is not None:
            stacked.append(name)
        log.append(f"{name}:open")
        dialog = QDialog()
        dialog.setModal(True)
        QTimer.singleShot(50, dialog.accept)
        dialog.exec()
        log.append(f"{name}:closed")

    return show


def test_notices_run_one_after_another_in_order(qtbot) -> None:
    queue = NoticeQueue()
    log: list[str] = []
    stacked: list[str] = []
    for name in ("recovery", "rules", "advisory"):
        queue.post(modal_notice(name, log, stacked))
    qtbot.waitUntil(lambda: len(log) == 6, timeout=5000)
    assert log == [
        "recovery:open",
        "recovery:closed",
        "rules:open",
        "rules:closed",
        "advisory:open",
        "advisory:closed",
    ]
    assert stacked == []


def test_notice_posted_while_another_is_open_waits(qtbot) -> None:
    queue = NoticeQueue()
    log: list[str] = []
    stacked: list[str] = []
    late = modal_notice("late", log, stacked)

    def first() -> None:
        # Komunikat z tła (np. koniec pobierania) w trakcie otwartego okna.
        QTimer.singleShot(10, lambda: queue.post(late))
        modal_notice("first", log, stacked)()

    queue.post(first)
    qtbot.waitUntil(lambda: "late:closed" in log, timeout=5000)
    assert log == ["first:open", "first:closed", "late:open", "late:closed"]
    assert stacked == []


def test_notice_waits_for_a_modal_opened_elsewhere(qtbot) -> None:
    queue = NoticeQueue()
    shown: list[bool] = []
    dialog = QDialog()
    dialog.setModal(True)
    dialog.show()
    queue.post(lambda: shown.append(True))
    qtbot.wait(100)
    assert shown == [] and queue.pending == 1
    dialog.close()
    qtbot.waitUntil(lambda: shown == [True], timeout=5000)


def test_notice_waits_while_busy(qtbot) -> None:
    busy = [True]
    queue = NoticeQueue(busy=lambda: busy[0])
    shown: list[bool] = []
    queue.post(lambda: shown.append(True))
    qtbot.wait(100)
    assert shown == []
    busy[0] = False
    qtbot.waitUntil(lambda: shown == [True], timeout=5000)


def test_failing_notice_does_not_block_the_rest(qtbot) -> None:
    queue = NoticeQueue()
    shown: list[str] = []

    def broken() -> None:
        raise RuntimeError("boom")

    queue.post(broken)
    queue.post(lambda: shown.append("next"))
    qtbot.waitUntil(lambda: shown == ["next"], timeout=5000)
