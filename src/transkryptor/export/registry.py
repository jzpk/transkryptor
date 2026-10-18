"""Rejestr formatów eksportu (propozycja 18).

Eksporter to opis formatu (klucz, nazwa, rozszerzenie, czy wymaga czasów,
które opcje go dotyczą) i funkcja ``write(dokument, ścieżka, opcje, raport)``
zapisująca model wyjścia ``ExportDocument``. Nowy format to nowa funkcja
zapisu i wpis w ``EXPORTERS`` — okno „Eksportuj jako…” bierze listę stąd.
:func:`run_export` zamienia błędy zapisu na ``ExportError`` z komunikatem
dla użytkownika.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from transkryptor.errors import ExportError
from transkryptor.export.docx_export import write_docx
from transkryptor.export.elan import write_eaf
from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.praat import write_textgrid
from transkryptor.export.rich_export import write_odt, write_pdf
from transkryptor.export.subtitles import write_srt, write_vtt
from transkryptor.export.text_export import write_txt
from transkryptor.i18n import tr

# Opcje okna eksportu, które mogą dotyczyć formatu.
OPTION_SUPERSCRIPT = "superscript"
OPTION_UNTIMED = "untimed"

Writer = Callable[[ExportDocument, Path, ExportOptions, ExportReport], None]


@dataclass(frozen=True)
class Exporter:
    key: str
    label_key: str
    suffix: str
    write: Writer
    timed: bool = False
    options: frozenset[str] = frozenset()

    @property
    def label(self) -> str:
        return tr(self.label_key)

    @property
    def file_filter(self) -> str:
        return f"{self.label} (*{self.suffix})"


def _docx(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    write_docx(document, path, options, report)


_TEXT = frozenset({OPTION_SUPERSCRIPT})
_TIMED = frozenset({OPTION_SUPERSCRIPT, OPTION_UNTIMED})

DOCX = "docx"
EXPORTERS: tuple[Exporter, ...] = (
    Exporter(DOCX, "export.format.docx", ".docx", _docx),
    Exporter("odt", "export.format.odt", ".odt", write_odt),
    Exporter("pdf", "export.format.pdf", ".pdf", write_pdf),
    Exporter("txt", "export.format.txt", ".txt", write_txt, options=_TEXT),
    Exporter("eaf", "export.format.eaf", ".eaf", write_eaf, True, _TIMED),
    Exporter(
        "textgrid", "export.format.textgrid", ".TextGrid", write_textgrid, True, _TIMED
    ),
    Exporter("srt", "export.format.srt", ".srt", write_srt, True, _TIMED),
    Exporter("vtt", "export.format.vtt", ".vtt", write_vtt, True, _TIMED),
)
EXPORTERS_BY_KEY = {exporter.key: exporter for exporter in EXPORTERS}


def exporter_by_key(key: str) -> Exporter:
    """Eksporter o kluczu; nieznany klucz → DOCX."""
    return EXPORTERS_BY_KEY.get(key, EXPORTERS_BY_KEY[DOCX])


def run_export(
    exporter: Exporter,
    document: ExportDocument,
    path: str | Path,
    options: ExportOptions | None = None,
) -> ExportReport:
    """Zapisuje plik; błędy jako ``ExportError``, ostrzeżenia w raporcie."""
    target = Path(path)
    report = ExportReport()
    try:
        exporter.write(document, target, options or ExportOptions(), report)
    except ExportError:
        raise
    except OSError as exc:
        raise ExportError(
            user_message=tr(
                "docx_export.error.write",
                name=target.name,
                reason=exc.strerror or exc,
            ),
            retry_hint=tr("docx_export.error.write.hint"),
        ) from exc
    except Exception as exc:
        raise ExportError(
            user_message=tr("docx_export.error.other", reason=exc),
            retry_hint=tr("docx_export.error.other.hint"),
        ) from exc
    return report
