"""Katalog metryczek (CSV, XLSX) i eksport TEI XML (wymaganie 9)."""

import csv
import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from transkryptor.corpus.catalog import (
    catalog_columns,
    catalog_table,
    csv_bytes,
    forms_table,
    save_table,
)
from transkryptor.corpus.forms import form_index, similar_forms
from transkryptor.corpus.projects import scan_folder
from transkryptor.corpus.tei import TEI_NS, XML_ID, save_tei, tei_bytes
from transkryptor.corpus.xlsx import column_name
from transkryptor.document.metadata import DEFAULT_FIELDS
from transkryptor.errors import ExportError

NS = {"t": TEI_NS}
SHEET_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@pytest.fixture
def projects(corpus_dir):
    return scan_folder(corpus_dir).projects


class TestCatalog:
    def test_one_row_per_project_with_metadata(self, projects, corpus_dir) -> None:
        table = catalog_table(projects, DEFAULT_FIELDS, folder=corpus_dir)
        assert table.header[0] == "Plik projektu"
        assert "Sygnatura" in table.header and "Informator (kod)" in table.header
        # Pole spoza konfiguracji trafia na koniec metryczki z kluczem.
        assert "custom-x" in table.header
        row = dict(zip(table.header, table.rows[0], strict=True))
        assert row["Plik projektu"] == "AdK_1954.transkr"
        assert row["Sygnatura"] == "AdK_1954"
        assert row["Informator (kod)"] == "INF-7"
        assert row["Mówcy"] == "B - Badacz; I - Informator"
        assert row["Nagranie"] == "AdK_1954.wav"
        assert row["SHA-256 nagrania"] == "abc123"
        assert row["Liczba słów"] == 7
        assert row["Słowa informatorów"] == 4
        other = dict(zip(table.header, table.rows[1], strict=True))
        assert other["Plik projektu"] == "wies/B_1960.transkr"
        assert other["Sygnatura"] == "" and other["Słowa informatorów"] == ""

    def test_anonymized_catalog_skips_personal_fields(self, projects) -> None:
        columns = catalog_columns(projects, DEFAULT_FIELDS, anonymize=True)
        assert not any(field.personal for field in columns)
        table = catalog_table(projects, DEFAULT_FIELDS, anonymize=True)
        assert "INF-7" not in {str(value) for row in table.rows for value in row}

    def test_csv_has_bom_and_quotes(self, projects) -> None:
        payload = csv_bytes(catalog_table(projects))
        assert payload.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
        assert rows[1][0] == "AdK_1954.transkr"
        assert len(rows) == 3

    def test_xlsx_is_readable_workbook(self, projects, tmp_path) -> None:
        path = tmp_path / "katalog.xlsx"
        table = catalog_table(projects)
        save_table(table, path)
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            ET.fromstring(archive.read("xl/workbook.xml"))
        rows = sheet.findall(".//s:row", SHEET_NS)
        assert len(rows) == 1 + len(table.rows)
        first = rows[1].findall("s:c", SHEET_NS)
        assert first[0].get("r") == "A2"
        assert first[0].findtext(".//s:t", namespaces=SHEET_NS) == "AdK_1954.transkr"
        words = table.header.index("Liczba słów")
        assert first[words].findtext("s:v", namespaces=SHEET_NS) == "7"

    def test_csv_by_suffix_and_write_error(self, projects, tmp_path) -> None:
        save_table(catalog_table(projects), tmp_path / "k.csv")
        assert (tmp_path / "k.csv").read_bytes().startswith(b"\xef\xbb\xbf")
        with pytest.raises(ExportError):
            save_table(catalog_table(projects), tmp_path / "brak" / "k.csv")

    def test_forms_table(self, projects) -> None:
        entries = form_index(projects)
        table = forms_table(entries, similar_forms(e.form for e in entries))
        rows = {row[0]: row for row in table.rows}
        assert rows["jag"] == ("jag", 1, 1, "jak")

    def test_column_names(self) -> None:
        assert [column_name(i) for i in (0, 25, 26, 27, 701, 702)] == [
            "A",
            "Z",
            "AA",
            "AB",
            "ZZ",
            "AAA",
        ]


class TestTei:
    def test_corpus_structure_and_header(self, projects, corpus_dir) -> None:
        root = ET.fromstring(tei_bytes(projects, title="Wieś", folder=corpus_dir))
        assert root.tag == f"{{{TEI_NS}}}teiCorpus"
        assert root.findtext("t:teiHeader//t:title", namespaces=NS) == "Wieś"
        tei = root.findall("t:TEI", NS)
        assert [t.get(XML_ID) for t in tei] == ["p1", "p2"]
        header = tei[0].find("t:teiHeader", NS)
        assert header is not None
        assert header.findtext(".//t:titleStmt/t:title", namespaces=NS) == "AdK_1954"
        assert header.findtext(".//t:respStmt/t:name", namespaces=NS) == "Anna"
        assert (
            header.findtext(".//t:idno[@type='signature']", namespaces=NS) == "AdK_1954"
        )
        date = header.find(".//t:recording/t:date", NS)
        assert date is not None and date.get("when") == "1954-07-12"
        media = header.find(".//t:recording/t:media", NS)
        assert media is not None and media.get("url") == "AdK_1954.wav"
        assert header.findtext(".//t:placeName", namespaces=NS) == "Brzezie"
        assert header.findtext(".//t:region", namespaces=NS) == "Kłaj"
        assert header.findtext(".//t:note[@type='informant']", namespaces=NS) == (
            "INF-7"
        )
        persons = header.findall(".//t:person", NS)
        assert [(p.get(XML_ID), p.get("role")) for p in persons] == [
            ("p1-B", "researcher"),
            ("p1-I", "informant"),
        ]

    def test_utterances_with_speakers_times_and_superscript(self, projects) -> None:
        root = ET.fromstring(tei_bytes(projects))
        body = root.find("t:TEI/t:text/t:body", NS)
        assert body is not None
        whens = {
            w.get(XML_ID): w.get("interval") for w in body.findall(".//t:when", NS)
        }
        utterances = body.findall("t:u", NS)
        assert [u.get("who") for u in utterances] == ["#p1-B", "#p1-I"]
        second = utterances[1]
        assert whens[second.get("start", "#")[1:]] == "2000"
        assert whens[second.get("end", "#")[1:]] == "6000"
        assert "".join(second.itertext()) == "No bendzie jak było"
        hi = second.find("t:hi", NS)
        assert hi is not None and hi.text == "b" and hi.get("rend") == "superscript"

    def test_anonymized_tei_has_no_personal_data(self, projects, tmp_path) -> None:
        path = tmp_path / "korpus.xml"
        save_tei(projects, path, anonymize=True)
        raw = path.read_text(encoding="utf-8")
        assert "INF-7" not in raw
        ET.fromstring(raw.encode("utf-8"))
