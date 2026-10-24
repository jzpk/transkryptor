"""Testy formatów eksportu fazy 12: TXT, SRT, WebVTT, ELAN, Praat, ODT i PDF."""

import os
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from lxml import etree  # type: ignore[import-untyped]

from transkryptor.document.anchors import MANUAL, SEGMENT, WORD, Anchor
from transkryptor.document.model import Document
from transkryptor.errors import ExportError
from transkryptor.export.elan import build_eaf
from transkryptor.export.model import build_export_document
from transkryptor.export.options import (
    UNTIMED_INTERPOLATE,
    UNTIMED_SKIP,
    ExportOptions,
    ExportReport,
)
from transkryptor.export.praat import render_textgrid
from transkryptor.export.registry import EXPORTERS, exporter_by_key, run_export
from transkryptor.export.subtitles import render_srt, render_vtt, timestamp
from transkryptor.export.superscript import CARET, UNICODE, superscript_text
from transkryptor.export.text_export import render_text
from transkryptor.export.timeline import build_units

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    # Na Windows platforma offscreen czyta czcionki z <Qt>/lib/fonts, których
    # PySide6 nie dostarcza — bez czcionek PDF nie ma tekstu ani /FontFile.
    os.environ.setdefault(
        "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    )

XSD = Path("tests/fixtures/elan/EAFv3.0.xsd")
TEXT = "Rok urodzenia?\nTysionc dziewińćset dwadzieścia\nA brat? Umar."
#       0             14 15                            45 46
SEGMENTS = (
    Anchor(0, 14, 0, 1500, SEGMENT),
    Anchor(4, 13, 300, 1400, WORD, probability=0.2),
    Anchor(15, 45, 1600, 4000, SEGMENT),
)


def make_document(**kwargs) -> Document:
    document = Document(
        text=TEXT,
        author="Jan Kowalski",
        date="2026-10-18",
        metadata={"signature": "AdK_1954", "informant": "KA"},
        paragraph_speakers={0: "B", 1: "I"},
        **kwargs,
    )
    document.superscript_ranges = [(20, 21), (30, 31)]  # „n” w „Tysionc”, „ć”
    return document


def export_doc(anchors=SEGMENTS, anonymize=False, audio=None):
    return build_export_document(
        make_document(), anonymize=anonymize, anchors=anchors, audio_path=audio
    )


class TestSuperscript:
    def test_unicode_and_caret(self) -> None:
        unmapped: set[str] = set()
        assert superscript_text("mnu", UNICODE, unmapped) == "ᵐⁿᵘ"
        assert superscript_text("mną", UNICODE, unmapped) == "ᵐⁿ^ą"
        assert unmapped == {"ą"}
        assert superscript_text("m", CARET, set()) == "^m"
        assert superscript_text("mn", CARET, set()) == "^{mn}"


class TestText:
    """ACC-52: metryczka, mówcy i indeks górny w obu trybach."""

    def test_unicode(self) -> None:
        report = ExportReport()
        text = render_text(export_doc(), ExportOptions(superscript=UNICODE), report)
        lines = text.splitlines()
        assert lines[0] == "Sygnatura: AdK_1954"
        assert "Informator (kod): KA" in lines
        assert "Mówcy: B — Badacz; I — Informator" in lines
        assert "Autor: Jan Kowalski    Data: 2026-10-18" in lines
        assert lines[-3] == "B: Rok urodzenia?"
        assert lines[-2] == "I: Tysioⁿc dziewiń^ćset dwadzieścia"
        assert lines[-1] == "A brat? Umar."
        assert report.warnings and "ć" in report.warnings[0]

    def test_caret_and_anonymization(self) -> None:
        report = ExportReport()
        text = render_text(
            export_doc(anonymize=True), ExportOptions(superscript=CARET), report
        )
        assert "I: Tysio^nc dziewiń^ćset dwadzieścia" in text
        assert "KA" not in text
        assert report.warnings == []

    def test_file_is_utf8(self, tmp_path) -> None:
        path = tmp_path / "t.txt"
        report = run_export(exporter_by_key("txt"), export_doc(), path)
        assert "Tysioⁿc" in path.read_text(encoding="utf-8")
        assert report.warnings


class TestTimeline:
    def test_units_follow_segments_and_extrapolate(self) -> None:
        report = ExportReport()
        units = build_units(export_doc(), UNTIMED_INTERPOLATE, report)
        assert [(u.start_ms, u.end_ms, u.text) for u in units[:2]] == [
            (0, 1500, "Rok urodzenia?"),
            (1600, 4000, "Tysionc dziewińćset dwadzieścia"),
        ]
        last = units[2]
        assert (
            last.interpolated and last.start_ms >= 4000 and last.end_ms > last.start_ms
        )
        assert "A brat? Umar." in report.warnings[0]

    def test_skip_option(self) -> None:
        """ACC-54: pominięte fragmenty są wymienione w raporcie."""
        report = ExportReport()
        units = build_units(export_doc(), UNTIMED_SKIP, report)
        assert len(units) == 2
        assert "Pominięte" in report.warnings[0] and "A brat?" in report.warnings[0]

    def test_manual_markers_split_and_interpolate(self) -> None:
        anchors = (
            Anchor(0, 14, 0, 1500, SEGMENT),
            Anchor(54, 54, 9000, 9000, MANUAL),  # przed „Umar.”
        )
        report = ExportReport()
        units = build_units(export_doc(anchors), UNTIMED_INTERPOLATE, report)
        texts = [(u.text, u.start_ms, u.interpolated) for u in units]
        assert texts[0] == ("Rok urodzenia?", 0, False)
        assert texts[-2][0] == "A brat?"
        assert texts[-1] == ("Umar.", 9000, True)  # koniec szacowany
        middle = units[1]
        assert 1500 <= middle.start_ms <= middle.end_ms <= 9000

    def test_draft_line_marker_is_not_a_unit(self) -> None:
        """Smoke test: „[00:00] ” szkicu ASR nie tworzy pustej jednostki."""
        text = "[00:00] Rok urodzenia? [00:29] Tysionc"
        anchors = (
            Anchor(8, 22, 0, 1500, SEGMENT),
            Anchor(31, 38, 1600, 2500, SEGMENT),
        )
        document = build_export_document(Document(text=text), anchors=anchors)
        units = build_units(document, UNTIMED_SKIP, ExportReport())
        assert [(u.text, u.start_ms, u.end_ms) for u in units] == [
            ("Rok urodzenia?", 0, 1500),
            ("Tysionc", 1600, 2500),
        ]

    def test_no_anchors_is_an_error(self) -> None:
        with pytest.raises(ExportError):
            build_units(
                export_doc(anchors=(SEGMENTS[1],)), UNTIMED_INTERPOLATE, ExportReport()
            )


class TestSubtitles:
    def test_srt(self) -> None:
        srt = render_srt(
            export_doc(), ExportOptions(untimed=UNTIMED_SKIP), ExportReport()
        )
        assert srt.startswith("1\n00:00:00,000 --> 00:00:01,500\nB: Rok urodzenia?\n")
        assert "2\n00:00:01,600 --> 00:00:04,000\nI: Tysioⁿc" in srt
        assert "A brat" not in srt

    def test_vtt(self) -> None:
        vtt = render_vtt(export_doc(), ExportOptions(), ExportReport())
        assert vtt.startswith("WEBVTT\n\nNOTE AdK_1954\n")
        assert "00:00:00.000 --> 00:00:01.500\n<v B>Rok urodzenia?" in vtt

    def test_timestamp(self) -> None:
        assert timestamp(3_723_004, ",") == "01:02:03,004"


class TestElan:
    """ACC-53: EAF przechodzi walidację schematem ELAN; warstwa na mówcę."""

    def test_valid_against_xsd(self, tmp_path) -> None:
        audio = tmp_path / "nagrania" / "AdK_1954.aac"
        audio.parent.mkdir()
        audio.write_bytes(b"")
        target = tmp_path / "eksport" / "AdK_1954.eaf"
        target.parent.mkdir()
        tree = build_eaf(
            export_doc(audio=audio),
            target,
            ExportOptions(),
            ExportReport(),
            now=datetime(2026, 10, 18, 12, tzinfo=UTC),
        )
        tree.write(str(target), encoding="UTF-8", xml_declaration=True)

        schema = etree.XMLSchema(etree.parse(str(XSD)))
        parsed = etree.parse(str(target))
        assert schema.validate(parsed), schema.error_log
        root = parsed.getroot()
        media = root.find("HEADER/MEDIA_DESCRIPTOR")
        assert media is not None
        assert media.get("RELATIVE_MEDIA_URL") == "./../nagrania/AdK_1954.aac"
        assert media.get("MEDIA_URL", "").startswith("file:///")
        tiers = {t.get("TIER_ID"): t for t in root.findall("TIER")}
        assert set(tiers) == {"B", "I", "bez mówcy"}
        assert tiers["I"].get("PARTICIPANT") == "Informator"
        value = tiers["B"].find(".//ANNOTATION_VALUE")
        assert value is not None and value.text == "Rok urodzenia?"
        slots = {
            s.get("TIME_SLOT_ID"): int(s.get("TIME_VALUE", "-1"))
            for s in root.findall("TIME_ORDER/TIME_SLOT")
        }
        annotation = tiers["I"].find(".//ALIGNABLE_ANNOTATION")
        assert annotation is not None
        assert slots[annotation.get("TIME_SLOT_REF1")] == 1600
        assert slots[annotation.get("TIME_SLOT_REF2")] == 4000

    def test_document_without_speakers_has_one_tier(self, tmp_path) -> None:
        document = build_export_document(Document(text="tak"), anchors=SEGMENTS[:1])
        path = tmp_path / "a.eaf"
        run_export(exporter_by_key("eaf"), document, path)
        schema = etree.XMLSchema(etree.parse(str(XSD)))
        parsed = etree.parse(str(path))
        assert schema.validate(parsed), schema.error_log
        assert [t.get("TIER_ID") for t in parsed.getroot().findall("TIER")] == [
            "transkrypcja"
        ]


def parse_textgrid(text: str) -> dict[str, list[tuple[float, float, str]]]:
    """Minimalny parser długiego formatu TextGrid (struktura jak w Praat)."""
    assert text.startswith('File type = "ooTextFile"\nObject class = "TextGrid"\n')
    tiers: dict[str, list[tuple[float, float, str]]] = {}
    for block in re.split(r"\n    item \[\d+\]:\n", text)[1:]:
        name = re.search(r'name = "(.*)" ', block)
        assert name is not None
        intervals = re.findall(
            r'xmin = ([\d.]+) \n\s+xmax = ([\d.]+) \n\s+text = "((?:[^"]|"")*)" ', block
        )
        size = re.search(r"intervals: size = (\d+)", block)
        assert size is not None and int(size[1]) == len(intervals)
        tiers[name[1]] = [
            (float(a), float(b), t.replace('""', '"')) for a, b, t in intervals
        ]
    return tiers


class TestPraat:
    """ACC-53: przedziały pokrywają całą oś czasu bez luk i nakładania."""

    def test_structure(self) -> None:
        text = render_textgrid(export_doc(), ExportOptions(), ExportReport())
        tiers = parse_textgrid(text)
        assert list(tiers) == ["B", "I", "bez mówcy"]
        xmax = float(re.search(r"\nxmax = ([\d.]+) \n", text)[1])  # type: ignore[index]
        for intervals in tiers.values():
            assert intervals[0][0] == 0
            assert intervals[-1][1] == xmax
            for (_s1, e1, _t1), (s2, _e2, _t2) in zip(
                intervals, intervals[1:], strict=False
            ):
                assert e1 == s2
        assert (0.0, 1.5, "Rok urodzenia?") in tiers["B"]
        assert (1.6, 4.0, "Tysioⁿc dziewiń^ćset dwadzieścia") in tiers["I"]


class TestRichFormats:
    @pytest.fixture(autouse=True)
    def _app(self, qapp) -> None:
        return None

    def test_odt_has_superscript_and_speaker(self, tmp_path) -> None:
        path = tmp_path / "t.odt"
        run_export(exporter_by_key("odt"), export_doc(), path)
        with zipfile.ZipFile(path) as archive:
            assert (
                archive.read("mimetype") == b"application/vnd.oasis.opendocument.text"
            )
            content = archive.read("content.xml").decode("utf-8")
        assert "text-position" in content and "super" in content
        assert "Rok urodzenia?" in content and "AdK_1954" in content
        assert "B:" in content

    def test_pdf(self, tmp_path) -> None:
        path = tmp_path / "t.pdf"
        run_export(exporter_by_key("pdf"), export_doc(), path)
        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        assert b"/FontFile" in data  # czcionka osadzona

    def test_unwritable_path_is_export_error(self, tmp_path) -> None:
        with pytest.raises(ExportError):
            run_export(exporter_by_key("pdf"), export_doc(), tmp_path / "x" / "t.pdf")


def test_registry() -> None:
    keys = [exporter.key for exporter in EXPORTERS]
    assert keys[0] == "docx"
    assert {"odt", "pdf", "txt", "eaf", "textgrid", "srt", "vtt"} <= set(keys)
    assert exporter_by_key("nieznany").key == "docx"
    assert all(e.timed for e in EXPORTERS if e.key in {"eaf", "textgrid", "srt", "vtt"})
