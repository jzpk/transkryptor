"""Testy integracyjne eksportu DOCX z testowym odczytem wygenerowanych plików."""

import pytest
from docx import Document as DocxReader

from transkryptor.document.model import Document
from transkryptor.errors import ExportError
from transkryptor.export.docx_export import export_docx


class TestExport:
    """ACC-09: DOCX zawiera tekst, metadane i format indeksu górnego."""

    def test_docx_contains_text_metadata_and_superscript(self, tmp_path) -> None:
        doc = Document(
            text="pamientam uóna zmar-zły", author="Jan Kowalski", date="2026-09-30"
        )
        doc.superscript_ranges = [(5, 6)]  # nosowe „n” w „pamientam”
        target = tmp_path / "transkrypcja.docx"

        export_docx(doc, target)

        assert target.is_file()
        read = DocxReader(str(target))
        assert read.core_properties.author == "Jan Kowalski"

        metadata_paragraph = read.paragraphs[0]
        assert "Jan Kowalski" in metadata_paragraph.text
        assert "2026-09-30" in metadata_paragraph.text

        text_paragraph = read.paragraphs[1]
        assert text_paragraph.text == "pamientam uóna zmar-zły"
        superscript_runs = [r for r in text_paragraph.runs if r.font.superscript]
        assert len(superscript_runs) == 1
        assert superscript_runs[0].text == "n"
        plain_runs = [r for r in text_paragraph.runs if not r.font.superscript]
        # Pozostały tekst bez formatowania: całość bez nosowego „n”.
        assert "".join(r.text for r in plain_runs) == "pamietam uóna zmar-zły"

    def test_empty_document_exports(self, tmp_path) -> None:
        doc = Document()
        target = tmp_path / "pusty.docx"
        export_docx(doc, target)
        assert target.is_file()

    def test_failed_save_raises_export_error(self, tmp_path) -> None:
        doc = Document(text="tekst")
        with pytest.raises(ExportError) as exc_info:
            export_docx(doc, tmp_path / "nieistniejący" / "plik.docx")
        assert exc_info.value.user_message
        assert exc_info.value.retry_hint

    def test_polish_characters_preserved(self, tmp_path) -> None:
        doc = Document(
            text="żółć gęślą jaźń ąęćłńóśźż", author="Łukasz Żółw", date="1979-01-01"
        )
        target = tmp_path / "znaki.docx"
        export_docx(doc, target)
        read = DocxReader(str(target))
        assert "żółć gęślą jaźń" in read.paragraphs[1].text
        assert "Łukasz Żółw" in read.paragraphs[0].text
