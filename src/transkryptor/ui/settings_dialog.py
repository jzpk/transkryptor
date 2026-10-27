"""Okno „Ustawienia…”: preferencje użytkownika na zakładkach.

Okno tylko edytuje kopię ustawień; zapis i powiadomienie komponentów
wykonuje ``SettingsStore`` po zatwierdzeniu. Każda zakładka dotyczy jednej
części aplikacji (wygląd, odtwarzacz, notacja, walidator, projekt, metryczka,
ASR, dziennik logów). Zakładki z ustawieniami to strony z ``settings_pages``
(``load``/``apply``); nowa sekcja ustawień to nowa strona na liście
``pages``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from transkryptor.asr.manager import ModelManager
from transkryptor.export.docx_template import TemplateCheck
from transkryptor.i18n import tr
from transkryptor.notation.rules import PhoneticRule
from transkryptor.settings import Settings
from transkryptor.ui.log_panel import LogPanel
from transkryptor.ui.rules_editor import RulesEditor
from transkryptor.ui.settings_pages import (
    AppearancePage,
    AsrPage,
    ExportPage,
    MetadataPage,
    NotationPage,
    PlayerPage,
    ProjectPage,
    SettingsPage,
    ShortcutPages,
    ValidatorPage,
    models_root,
)
from transkryptor.ui.shortcuts_editor import ShortcutsEditor, SnippetsEditor


class SettingsDialog(QDialog):
    """Okno edycji ustawień; wynik odczytuje się metodą ``settings()``."""

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        builtin_rules: tuple[PhoneticRule, ...] = (),
        user_rules: tuple[PhoneticRule, ...] = (),
        document_text: str = "",
        model_manager: ModelManager | None = None,
    ) -> None:
        """``model_manager`` - menedżer modeli ASR (model mówców leży w tym
        samym katalogu); None oznacza katalog z ``settings``."""
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setObjectName("settings_dialog")
        self._loaded = settings

        self.appearance_page = AppearancePage(settings.appearance.language)
        self.player_page = PlayerPage()
        self.notation_page = NotationPage(settings.notation.ellipsis_style)
        self.validator_page = ValidatorPage()
        self.rules_editor = RulesEditor(builtin_rules, user_rules, document_text)
        self.shortcut_pages = ShortcutPages()
        self.project_page = ProjectPage()
        self.metadata_page = MetadataPage()
        self.export_page = ExportPage(self.metadata_page.fields)
        self.asr_page = AsrPage(
            model_manager
            or ModelManager(models_root=models_root(settings.asr.models_root))
        )
        self.log_panel = LogPanel()
        # Kolejność wczytywania: metryczka przed eksportem (sprawdzenie
        # szablonu korzysta z pól metryczki).
        self.pages: tuple[SettingsPage, ...] = (
            self.appearance_page,
            self.player_page,
            self.notation_page,
            self.validator_page,
            self.shortcut_pages,
            self.project_page,
            self.metadata_page,
            self.export_page,
            self.asr_page,
        )

        self.tabs = QTabWidget()
        for page, title in (
            (self.appearance_page, "settings.tab.appearance"),
            (self.player_page, "settings.tab.player"),
            (self.notation_page, "settings.tab.notation"),
            (self.validator_page, "settings.tab.validator"),
            (self.rules_editor, "settings.tab.rules"),
            (self.shortcut_pages.shortcuts_editor, "settings.tab.shortcuts"),
            (self.shortcut_pages.snippets_editor, "settings.tab.snippets"),
            (self.project_page, "settings.tab.project"),
            (self.metadata_page, "settings.tab.metadata"),
            (self.export_page, "settings.tab.export"),
            (self.asr_page, "settings.tab.asr"),
            (self.log_panel, "settings.tab.logs"),
        ):
            self.tabs.addTab(page, tr(title))
        self._build_layout()
        self.set_settings(settings)

    def _build_layout(self) -> None:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.restore_defaults_button: QPushButton = buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.restore_defaults_button.setText(tr("settings.restore_defaults"))
        self.restore_defaults_button.clicked.connect(
            lambda: self.set_settings(Settings())
        )

        # Zakładek jest za dużo na jeden wiersz, a przewijany pasek ukrywa
        # dalsze - sekcje są więc listą po lewej, zawsze widoczną w całości.
        self.tabs.tabBar().hide()
        self.sections = QListWidget()
        self.sections.setObjectName("settings_sections")
        for index in range(self.tabs.count()):
            self.sections.addItem(self.tabs.tabText(index))
        self.sections.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.sections.setFixedWidth(self.sections.sizeHintForColumn(0) + 40)
        self.sections.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.sections.setCurrentRow)
        self.sections.setCurrentRow(self.tabs.currentIndex())
        body = QHBoxLayout()
        body.addWidget(self.sections)
        body.addWidget(self.tabs, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(body, stretch=1)
        layout.addWidget(buttons)
        # Lista sekcji + najszersza strona (Wygląd) bez ucinania pól.
        self.setMinimumSize(760, 480)
        self.resize(940, 680)

    def set_settings(self, settings: Settings) -> None:
        """Wypełnia pola wartościami ``settings``.

        Pola bez odpowiednika w oknie (np. model ASR, podpis komentarzy,
        ostatni format eksportu) przechodzą do ``settings()`` bez zmian.
        """
        self._loaded = settings
        for page in self.pages:
            page.load(settings)

    def settings(self) -> Settings:
        """Ustawienia odpowiadające bieżącym wartościom pól."""
        result = self._loaded
        for page in self.pages:
            result = page.apply(result)
        return result

    # --- operacje na stronach ------------------------------------------------

    @property
    def shortcuts_editor(self) -> ShortcutsEditor:
        return self.shortcut_pages.shortcuts_editor

    @property
    def snippets_editor(self) -> SnippetsEditor:
        return self.shortcut_pages.snippets_editor

    def check_template(self) -> TemplateCheck | None:
        return self.export_page.check_template()

    def open_rules_with(self, rule: PhoneticRule) -> None:
        """Zakładka reguł z dopisaną proponowaną regułą (do sprawdzenia)."""
        self.tabs.setCurrentWidget(self.rules_editor)
        self.rules_editor.add_proposed_rule(rule)

    def user_rules(self) -> tuple[PhoneticRule, ...]:
        """Reguły fonetyczne użytkownika po edycji (zapisuje okno główne)."""
        return self.rules_editor.user_rules()

    def shortcut_conflicts(self) -> list[str]:
        """Opisy konfliktów skrótów akcji i wstawek (ACC-43)."""
        return self.shortcut_pages.conflicts()

    def accept(self) -> None:
        """Błędna reguła, wstawka albo konflikt skrótów blokuje zapis."""
        checks: tuple[tuple[QWidget, str | None], ...] = (
            (self.rules_editor, self.rules_editor.first_problem()),
            (self.snippets_editor, self.snippets_editor.first_problem()),
            (self.shortcuts_editor, "\n".join(self.shortcut_conflicts()) or None),
        )
        for page, problem in checks:
            if problem is not None:
                self.tabs.setCurrentWidget(page)
                QMessageBox.warning(
                    self, self.tabs.tabText(self.tabs.indexOf(page)), problem
                )
                return
        super().accept()

    def done(self, result: int) -> None:
        # Zamknięcie ustawień przerywa pobieranie modelu mówców.
        self.asr_page.diarization_box.cancel_and_wait()
        super().done(result)
