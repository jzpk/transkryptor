"""Opcje i raport eksportu wspólne dla wszystkich formatów (bez Qt)."""

from __future__ import annotations

from dataclasses import dataclass, field

from transkryptor.export.superscript import UNICODE
from transkryptor.i18n import tr

# Fragmenty tekstu bez kotwic czasowych w formatach z czasami.
UNTIMED_INTERPOLATE = "interpolate"
UNTIMED_SKIP = "skip"
UNTIMED_MODES = (UNTIMED_INTERPOLATE, UNTIMED_SKIP)

# Najwyżej tyle fragmentów wymienia raport z nazwy; resztę liczy.
REPORT_EXAMPLES = 8


@dataclass(frozen=True)
class ExportOptions:
    """Opcje zapisu; formaty biorą tylko te, które ich dotyczą."""

    superscript: str = UNICODE
    untimed: str = UNTIMED_INTERPOLATE
    template_path: str = ""
    font_family: str = ""


@dataclass
class ExportReport:
    """Ostrzeżenia eksportu dla użytkownika (pusta lista = bez uwag)."""

    warnings: list[str] = field(default_factory=list)

    def warn(self, text: str) -> None:
        self.warnings.append(text)

    def warn_fragments(self, key: str, fragments: list[str]) -> None:
        """Ostrzeżenie z listą fragmentów (pierwsze ``REPORT_EXAMPLES``)."""
        if not fragments:
            return
        shown = "\n".join(f"• {fragment}" for fragment in fragments[:REPORT_EXAMPLES])
        more = len(fragments) - REPORT_EXAMPLES
        if more > 0:
            shown += "\n" + tr("export.report.more", count=more)
        self.warn(tr(key, count=len(fragments), fragments=shown))

    def warn_unmapped(self, unmapped: set[str]) -> None:
        if unmapped:
            self.warn(tr("export.report.unmapped", chars=" ".join(sorted(unmapped))))
