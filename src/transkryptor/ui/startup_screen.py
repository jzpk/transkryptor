"""Ekran startowy: sprawdzanie dostępnych aktualizacji.

Ekran pojawia się przed oknem głównym, które powstaje w tym czasie. Pokazuje
„Sprawdzanie dostępnych aktualizacji…” i zamyka się, gdy sprawdzenie
(``UpdateThread``) się skończy. Nic nie jest tu pobierane - nowa wersja
pojawia się w pasku stanu okna z przyciskiem „Pobierz i zainstaluj”.
„Pomiń” zamyka ekran od razu, a sprawdzenie kończy się w tle.
"""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor import __version__
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props
from transkryptor.ui.update_controller import UpdateThread


class StartupScreen(QWidget):
    """Okno bez ramki ze sprawdzaniem aktualizacji i przyciskiem „Pomiń”."""

    skipped = Signal()

    def __init__(self) -> None:
        super().__init__(
            None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
        )
        self.setObjectName("startup_screen")
        self.setWindowTitle("Transkryptor")
        self._done = False
        self._loop: QEventLoop | None = None

        frame = QFrame()
        frame.setObjectName("startup_frame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.title_label = QLabel("Transkryptor")
        set_props(self.title_label, role="title")
        self.version_label = QLabel(tr("startup.version", version=__version__))
        set_props(self.version_label, role="muted")
        self.status_label = QLabel(tr("startup.checking"))
        self.status_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.skip_button = QPushButton(tr("startup.skip"))
        self.skip_button.setToolTip(tr("startup.skip.tooltip"))
        self.skip_button.clicked.connect(self.skip)

        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.skip_button)

        content = QVBoxLayout(frame)
        content.setContentsMargins(24, 20, 24, 20)
        content.setSpacing(10)
        content.addWidget(self.title_label)
        content.addWidget(self.version_label)
        content.addWidget(self.status_label)
        content.addWidget(self.progress)
        content.addLayout(footer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(frame)
        self.setFixedWidth(420)

    def attach(self, thread: UpdateThread) -> None:
        """Zakończenie sprawdzenia zamyka ekran."""
        thread.finished_with.connect(lambda _outcome: self.finish())

    @property
    def is_done(self) -> bool:
        return self._done

    def finish(self) -> None:
        """Sprawdzenie zakończone albo pominięte - ekran znika."""
        if self._done:
            return
        self._done = True
        self.close()

    def skip(self) -> None:
        self.skipped.emit()
        self.finish()

    def wait(self) -> None:
        """Lokalna pętla zdarzeń do zakończenia sprawdzenia albo pominięcia."""
        if self._done:
            return
        self._loop = QEventLoop()
        self._loop.exec()
        self._loop = None

    def closeEvent(self, event: QCloseEvent) -> None:
        self._done = True
        if self._loop is not None:
            self._loop.quit()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.skip()
            return
        super().keyPressEvent(event)
