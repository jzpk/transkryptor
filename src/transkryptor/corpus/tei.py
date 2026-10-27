"""Eksport korpusu do TEI XML (P5, moduł „spoken”) bez Qt.

Plik to ``teiCorpus`` z nagłówkiem korpusu i jednym elementem ``TEI`` na
projekt. Nagłówek projektu zawiera metryczkę: sygnaturę (``idno``),
autora i datę transkrypcji, nagranie (``recordingStmt``), miejscowość
i gminę (``settingDesc``), mówców (``particDesc``) oraz pozostałe pola
jako ``note`` z kluczem pola w ``@type``. Tekst to wypowiedzi ``u`` -
akapit z mówcą (``@who``), czasem z kotwic (``@start``/``@end`` wskazujące
punkty ``timeline`` w milisekundach) i indeksem górnym jako
``<hi rend="superscript">``.

``anonymize`` działa jak w eksporcie DOCX: bez pól osobowych i etykiet
informatorów.
"""

from __future__ import annotations

import mimetypes
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from pathlib import Path

from transkryptor import __version__
from transkryptor.corpus.catalog import write_file
from transkryptor.corpus.projects import CorpusProject
from transkryptor.document.anchors import time_span
from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    DISTRICT,
    PLACE,
    SIGNATURE,
    MetadataField,
)
from transkryptor.document.model import Document
from transkryptor.export.model import ExportDocument, build_export_document
from transkryptor.i18n import tr

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI_SUFFIX = ".xml"
RECORDING_DATE = "recording_date"
_ISO_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
# Pola zapisywane w dedykowanych elementach nagłówka, a nie w ``note``.
_HEADER_KEYS = frozenset({SIGNATURE, PLACE, DISTRICT, RECORDING_DATE})
# Znaki niedozwolone w XML 1.0 (sterujące poza tabulacją i końcem wiersza).
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _tag(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _sub(parent: ET.Element, name: str, text: str = "", **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, _tag(name), attrs)
    if text:
        element.text = _clean(text)
    return element


def _clean(text: str) -> str:
    return _XML_INVALID.sub("", text)


def tei_bytes(
    projects: Sequence[CorpusProject],
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
    title: str = "",
    folder: Path | None = None,
) -> bytes:
    """Dokument ``teiCorpus`` z projektami w podanej kolejności (UTF-8)."""
    configured = tuple(fields)
    ET.register_namespace("", TEI_NS)
    corpus = ET.Element(_tag("teiCorpus"))
    header = _sub(corpus, "teiHeader")
    file_desc = _sub(header, "fileDesc")
    _sub(_sub(file_desc, "titleStmt"), "title", title or tr("corpus.tei.title"))
    _sub(_sub(file_desc, "publicationStmt"), "p", f"Transkryptor {__version__}")
    _sub(
        _sub(file_desc, "sourceDesc"),
        "p",
        tr("corpus.tei.source", count=len(projects)),
    )
    for index, project in enumerate(projects, start=1):
        _project_tei(corpus, project, f"p{index}", configured, anonymize, folder)
    ET.indent(corpus, space=" ")
    return ET.tostring(corpus, encoding="utf-8", xml_declaration=True)


def save_tei(
    projects: Sequence[CorpusProject],
    path: str | Path,
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
    title: str = "",
    folder: Path | None = None,
) -> None:
    target = Path(path)
    write_file(target, tei_bytes(projects, fields, anonymize, title, folder))


def export_document(
    project: CorpusProject,
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
) -> ExportDocument:
    """Model wyjścia projektu (ten sam, z którego korzystają eksportery)."""
    state = project.state
    document = Document(
        text=state.text,
        superscript_ranges=list(state.superscript_ranges),
        author=state.author,
        date=state.date,
        metadata=dict(state.metadata),
        speakers=list(state.speakers),
        paragraph_speakers=dict(state.paragraph_speakers),
    )
    return build_export_document(
        document, fields, anonymize=anonymize, anchors=state.anchors
    )


def _project_tei(
    corpus: ET.Element,
    project: CorpusProject,
    pid: str,
    fields: tuple[MetadataField, ...],
    anonymize: bool,
    folder: Path | None,
) -> None:
    document = export_document(project, fields, anonymize)
    tei = _sub(corpus, "TEI", **{XML_ID: pid})
    header = _sub(tei, "teiHeader")
    file_desc = _sub(header, "fileDesc")
    _title_stmt(file_desc, project, document)
    _publication_stmt(file_desc, project, document, folder)
    _notes_stmt(file_desc, document)
    _source_desc(file_desc, project, document)
    _profile_desc(header, document, pid)
    body = _sub(_sub(tei, "text"), "body")
    _utterances(body, document, pid)


def _title_stmt(
    file_desc: ET.Element, project: CorpusProject, document: ExportDocument
) -> None:
    title_stmt = _sub(file_desc, "titleStmt")
    _sub(title_stmt, "title", document.value(SIGNATURE) or project.name)
    if project.state.author:
        resp = _sub(title_stmt, "respStmt")
        _sub(resp, "resp", tr("corpus.tei.transcription"))
        _sub(resp, "name", project.state.author)


def _publication_stmt(
    file_desc: ET.Element,
    project: CorpusProject,
    document: ExportDocument,
    folder: Path | None,
) -> None:
    publication = _sub(file_desc, "publicationStmt")
    _sub(publication, "authority", "Transkryptor")
    if document.value(SIGNATURE):
        _sub(publication, "idno", document.value(SIGNATURE), type="signature")
    _sub(publication, "idno", project.relative_name(folder), type="project")
    if project.state.date:
        _date(publication, project.state.date)


def _notes_stmt(file_desc: ET.Element, document: ExportDocument) -> None:
    notes = [(f, v) for f, v in document.metadata if f.key not in _HEADER_KEYS]
    if notes:
        notes_stmt = _sub(file_desc, "notesStmt")
        for field, value in notes:
            _sub(notes_stmt, "note", value, type=field.key, n=field.display_label)


def _source_desc(
    file_desc: ET.Element, project: CorpusProject, document: ExportDocument
) -> None:
    source = _sub(file_desc, "sourceDesc")
    audio = project.state.audio
    recording_date = document.value(RECORDING_DATE)
    if audio is None and not recording_date:
        _sub(source, "p", tr("corpus.tei.no_recording"))
        return
    recording = _sub(_sub(source, "recordingStmt"), "recording", type="audio")
    if recording_date:
        _date(recording, recording_date)
    if audio is not None:
        mime_type = mimetypes.guess_type(audio.name)[0] or "audio"
        _sub(recording, "media", mimeType=mime_type, url=audio.name)
        if audio.sha256:
            _sub(recording, "note", audio.sha256, type="sha256")


def _profile_desc(header: ET.Element, document: ExportDocument, pid: str) -> None:
    """Mówcy i miejsce nagrania; bez nich ``profileDesc`` jest pomijany."""
    profile = _sub(header, "profileDesc")
    if document.uses_speakers:
        persons = _sub(_sub(profile, "particDesc"), "listPerson")
        for speaker in document.speakers:
            person = _sub(
                persons, "person", **{XML_ID: f"{pid}-{speaker.key}"}, role=speaker.role
            )
            _sub(person, "persName", speaker.description)
    place, district = document.value(PLACE), document.value(DISTRICT)
    if place or district:
        setting = _sub(_sub(profile, "settingDesc"), "setting")
        if place:
            _sub(setting, "placeName", place)
        if district:
            _sub(setting, "region", district)
    if not len(profile):
        header.remove(profile)


def _date(parent: ET.Element, value: str) -> None:
    attrs = {"when": value} if _ISO_DATE.match(value) else {}
    _sub(parent, "date", value, **attrs)


def _utterances(body: ET.Element, document: ExportDocument, pid: str) -> None:
    spans = [
        time_span(document.anchors, paragraph.start, paragraph.end, False)
        for paragraph in document.paragraphs
    ]
    points = sorted({ms for span in spans if span is not None for ms in span})
    ids: dict[int, str] = {}
    if points:
        timeline = _sub(body, "timeline", unit="ms", origin=f"#{pid}-T0")
        _sub(timeline, "when", **{XML_ID: f"{pid}-T0"}, absolute="00:00:00")
        for number, ms in enumerate(points, start=1):
            ids[ms] = f"{pid}-T{number}"
            _sub(
                timeline,
                "when",
                **{XML_ID: ids[ms]},
                interval=str(ms),
                since=f"#{pid}-T0",
            )
    for paragraph, span in zip(document.paragraphs, spans, strict=True):
        if not paragraph.text.strip():
            continue
        attrs: dict[str, str] = {}
        if paragraph.speaker is not None:
            attrs["who"] = f"#{pid}-{paragraph.speaker.key}"
        if span is not None:
            attrs["start"] = f"#{ids[span[0]]}"
            attrs["end"] = f"#{ids[span[1]]}"
        utterance = _sub(body, "u", **attrs)
        last: ET.Element | None = None
        for run in paragraph.runs:
            text = _clean(run.text)
            if run.superscript:
                last = _sub(utterance, "hi", rend="superscript")
                last.text = text
            elif last is None:
                utterance.text = (utterance.text or "") + text
            else:
                last.tail = (last.tail or "") + text
