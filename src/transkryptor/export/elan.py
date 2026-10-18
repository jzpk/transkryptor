"""Eksport do ELAN (``.eaf``, format 3.0) z czasami z kotwic.

Warstwa (``TIER``) na mówcę z uczestnikiem (``PARTICIPANT``) = opis mówcy,
jednostki czasowe jako ``ALIGNABLE_ANNOTATION`` z parą ``TIME_SLOT``.
Nagłówek wskazuje nagranie (``MEDIA_DESCRIPTOR``: adres bezwzględny
i względny do pliku eksportu), a metryczka trafia do ``PROPERTY``.
Plik przechodzi walidację schematem ``EAFv3.0.xsd`` (test ACC-53).
"""

from __future__ import annotations

import mimetypes
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.superscript import render_runs
from transkryptor.export.timeline import build_units, tiers

LINGUISTIC_TYPE = "transcription"
SCHEMA_URL = "http://www.mpi.nl/tools/elan/EAFv3.0.xsd"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
# Standardowe stereotypy ograniczeń ELAN (jak w plikach tworzonych przez ELAN).
CONSTRAINTS = (
    (
        "Time_Subdivision",
        "Time subdivision of parent annotation's time interval, "
        "no time gaps allowed within this interval",
    ),
    (
        "Symbolic_Subdivision",
        "Symbolic subdivision of a parent annotation. "
        "Annotations refering to the same parent are ordered",
    ),
    ("Symbolic_Association", "1-1 association with a parent annotation"),
    (
        "Included_In",
        "Time alignable annotations within the parent annotation's "
        "time interval, gaps are allowed",
    ),
)
_AUDIO_MIME = {".aac": "audio/aac", ".m4a": "audio/mp4", ".wav": "audio/x-wav"}


def media_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _AUDIO_MIME:
        return _AUDIO_MIME[suffix]
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "audio/*"


def build_eaf(
    document: ExportDocument,
    target: Path,
    options: ExportOptions,
    report: ExportReport,
    now: datetime | None = None,
) -> ET.ElementTree:
    units = build_units(document, options.untimed, report)
    stamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    ET.register_namespace("xsi", XSI)
    root = ET.Element(
        "ANNOTATION_DOCUMENT",
        {
            "AUTHOR": document.author,
            "DATE": stamp,
            "FORMAT": "3.0",
            "VERSION": "3.0",
            f"{{{XSI}}}noNamespaceSchemaLocation": SCHEMA_URL,
        },
    )
    header = ET.SubElement(
        root, "HEADER", {"MEDIA_FILE": "", "TIME_UNITS": "milliseconds"}
    )
    if document.audio_path is not None:
        media = document.audio_path.resolve()
        attributes = {"MEDIA_URL": media.as_uri(), "MIME_TYPE": media_mime(media)}
        try:
            relative = os.path.relpath(media, target.resolve().parent)
        except ValueError:  # inny dysk w Windows
            relative = ""
        if relative:
            attributes["RELATIVE_MEDIA_URL"] = "./" + Path(relative).as_posix()
        ET.SubElement(header, "MEDIA_DESCRIPTOR", attributes)
    for label, value in document.header_rows():
        ET.SubElement(header, "PROPERTY", {"NAME": label}).text = value

    time_order = ET.SubElement(root, "TIME_ORDER")
    unmapped: set[str] = set()
    slot = 0
    annotation = 0
    tier_elements: list[ET.Element] = []
    for tier in tiers(document, units):
        attributes = {"LINGUISTIC_TYPE_REF": LINGUISTIC_TYPE, "TIER_ID": tier.name}
        if tier.participant:
            attributes["PARTICIPANT"] = tier.participant
        if document.author:
            attributes["ANNOTATOR"] = document.author
        tier_element = ET.Element("TIER", attributes)
        for unit in tier.units:
            slot_ids = []
            for time_ms in (unit.start_ms, unit.end_ms):
                slot += 1
                slot_ids.append(f"ts{slot}")
                ET.SubElement(
                    time_order,
                    "TIME_SLOT",
                    {"TIME_SLOT_ID": f"ts{slot}", "TIME_VALUE": str(time_ms)},
                )
            annotation += 1
            wrapper = ET.SubElement(tier_element, "ANNOTATION")
            alignable = ET.SubElement(
                wrapper,
                "ALIGNABLE_ANNOTATION",
                {
                    "ANNOTATION_ID": f"a{annotation}",
                    "TIME_SLOT_REF1": slot_ids[0],
                    "TIME_SLOT_REF2": slot_ids[1],
                },
            )
            ET.SubElement(alignable, "ANNOTATION_VALUE").text = render_runs(
                unit.runs, options.superscript, unmapped
            )
        tier_elements.append(tier_element)
    root.extend(tier_elements)
    ET.SubElement(
        root,
        "LINGUISTIC_TYPE",
        {
            "GRAPHIC_REFERENCES": "false",
            "LINGUISTIC_TYPE_ID": LINGUISTIC_TYPE,
            "TIME_ALIGNABLE": "true",
        },
    )
    for stereotype, description in CONSTRAINTS:
        ET.SubElement(
            root, "CONSTRAINT", {"DESCRIPTION": description, "STEREOTYPE": stereotype}
        )
    report.warn_unmapped(unmapped)
    ET.indent(root)
    return ET.ElementTree(root)


def write_eaf(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    tree = build_eaf(document, path, options, report)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
