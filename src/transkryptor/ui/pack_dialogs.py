"""Okna paczki do przekazania: zawartość przed zapisem i ustawienia przy otwarciu.

``PackExportDialog`` pokazuje, co trafi do paczki, i jej przybliżony
rozmiar (z ostrzeżeniem przy bardzo dużym nagraniu); pole „Dołącz
nagranie” pozwala wysłać paczkę bez nagrania, gdy odbiorca już je ma.
``PackImportDialog`` pyta, co zrobić z regułami, wstawkami i ustawieniami
notacji z paczki (przyjąć, scalić z własnymi albo pominąć) i czy użyć
szablonu DOCX.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.pack import (
    LARGE_AUDIO_BYTES,
    PackManifest,
    PackSettings,
    PackSource,
    audio_size,
    estimated_size,
)
from transkryptor.document.pack_settings import (
    ACCEPT,
    CHOICES,
    MERGE,
    NOTATION,
    available_groups,
)
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props

# Szerokość, przy której zawijane opisy mieszczą się w kilku liniach.
DIALOG_MIN_WIDTH = 460


def format_size(size: int) -> str:
    """Rozmiar w MB z jednym miejscem po przecinku (np. ``12,5 MB``)."""
    megabytes = size / (1024 * 1024)
    return tr("pack.size.value", size=f"{megabytes:.1f}".replace(".", ","))


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    set_props(label, role="muted")
    return label


class PackExportDialog(QDialog):
    """Zawartość paczki, opcja nagrania i rozmiar przed zapisem."""

    def __init__(self, source: PackSource, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pack_export_dialog")
        self.setWindowTitle(tr("pack.export.title"))
        self._source = source
        has_audio = source.audio_path is not None and source.audio_path.is_file()

        header = QLabel(tr("pack.export.header"))
        set_props(header, role="title")
        self.contents = _muted(self._contents_text())
        self.audio_check = QCheckBox(tr("pack.export.include_audio"))
        self.audio_check.setToolTip(tr("pack.export.include_audio.tooltip"))
        self.audio_check.setChecked(has_audio and source.include_audio)
        self.audio_check.setEnabled(has_audio)
        self.audio_check.toggled.connect(self._update_size)
        self.size_label = QLabel()
        self.size_label.setObjectName("pack_size_label")
        self.warning_label = _muted()
        set_props(self.warning_label, role="status", tone="warning")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self.contents)
        layout.addWidget(self.audio_check)
        layout.addWidget(self.size_label)
        layout.addWidget(self.warning_label)
        layout.addWidget(buttons)
        # Zawijane etykiety bez minimalnej szerokości ściskają okno tak,
        # że tekst nie mieści się w pionie.
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self._update_size()

    @property
    def include_audio(self) -> bool:
        return self.audio_check.isChecked()

    def source(self) -> PackSource:
        return replace(self._source, include_audio=self.include_audio)

    def _contents_text(self) -> str:
        source = self._source
        lines = [tr("pack.export.item.project", name=source.project_name)]
        if source.state.audio is not None:
            lines.append(tr("pack.export.item.audio", name=source.state.audio.name))
        settings = source.settings
        if settings.rules_toml:
            lines.append(tr("pack.export.item.rules"))
        if settings.snippets_spec:
            lines.append(tr("pack.export.item.snippets"))
        if settings.has_notation:
            lines.append(tr("pack.export.item.notation"))
        if source.template_path is not None:
            lines.append(
                tr("pack.export.item.template", name=source.template_path.name)
            )
        return "\n".join(f"• {line}" for line in lines)

    def _update_size(self) -> None:
        source = self.source()
        self.size_label.setText(
            tr("pack.size", size=format_size(estimated_size(source)))
        )
        large = self.include_audio and audio_size(source) > LARGE_AUDIO_BYTES
        if large:
            self.warning_label.setText(tr("pack.export.large"))
        elif not self.include_audio and source.state.audio is not None:
            self.warning_label.setText(tr("pack.export.no_audio"))
        else:
            self.warning_label.setText("")
        self.warning_label.setVisible(bool(self.warning_label.text()))
        # Ostrzeżenie pojawia się i znika - okno dopasowuje wysokość.
        self.adjustSize()


class PackImportDialog(QDialog):
    """Decyzje o ustawieniach z paczki: przyjąć, scalić albo pominąć."""

    def __init__(
        self,
        manifest: PackManifest,
        settings: PackSettings,
        has_template: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pack_import_dialog")
        self.setWindowTitle(tr("pack.import.title"))
        header = QLabel(tr("pack.import.header", name=manifest.project))
        set_props(header, role="title")
        layout = QVBoxLayout(self)
        layout.addWidget(header)
        if manifest.audio_name and not manifest.audio_included:
            layout.addWidget(
                _muted(tr("pack.import.no_audio", name=manifest.audio_name))
            )
        form = QFormLayout()
        self.combos: dict[str, QComboBox] = {}
        for group in available_groups(settings):
            combo = QComboBox()
            for choice in CHOICES:
                combo.addItem(tr(f"pack.choice.{choice}"), choice)
            # Notacja z paczki to konwencja projektu - domyślnie ją przyjmujemy.
            default = ACCEPT if group == NOTATION else MERGE
            combo.setCurrentIndex(CHOICES.index(default))
            combo.setObjectName(f"pack_choice_{group}")
            self.combos[group] = combo
            form.addRow(tr(f"pack.group.{group}"), combo)
        layout.addLayout(form)
        self.template_check = QCheckBox(tr("pack.import.template"))
        self.template_check.setChecked(has_template)
        self.template_check.setVisible(has_template)
        layout.addWidget(self.template_check)
        if not self.combos and not has_template:
            layout.addWidget(_muted(tr("pack.import.no_settings")))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(DIALOG_MIN_WIDTH)

    def choices(self) -> dict[str, str]:
        return {group: str(combo.currentData()) for group, combo in self.combos.items()}

    def set_choice(self, group: str, choice: str) -> None:
        self.combos[group].setCurrentIndex(CHOICES.index(choice))

    @property
    def use_template(self) -> bool:
        return self.template_check.isChecked()
