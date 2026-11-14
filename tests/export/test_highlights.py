"""Podświetlenia w eksporcie: tło wybranych słów (zgłoszenie #54)."""

import zipfile

from transkryptor.document.model import Document
from transkryptor.document.parts_of_speech import (
    POS_COLORS,
    PartOfSpeech,
    paper_color,
)
from transkryptor.export.docx_export import write_docx
from transkryptor.export.model import (
    ExportRun,
    build_export_document,
    with_highlights,
)

TEXT = "Kot spał.\nPies biegł."


def export_document(superscript=()):
    return build_export_document(
        Document(text=TEXT, superscript_ranges=list(superscript))
    )


def test_paper_color_is_the_editor_color_on_white() -> None:
    assert paper_color(PartOfSpeech.NOUN) != POS_COLORS[PartOfSpeech.NOUN]
    assert paper_color(PartOfSpeech.NOUN).startswith("#")
    assert len(paper_color(PartOfSpeech.NOUN)) == 7
    # Jaśniejszy w każdym kanale niż kolor bazowy.
    base = POS_COLORS[PartOfSpeech.NOUN]
    mixed = paper_color(PartOfSpeech.NOUN)
    for i in (1, 3, 5):
        assert int(mixed[i : i + 2], 16) >= int(base[i : i + 2], 16)


def test_highlights_split_runs_on_their_edges() -> None:
    highlighted = with_highlights(
        export_document(), [(0, 3, "#aaaaaa"), (10, 14, "#bbbbbb")]
    )
    first, second = highlighted.paragraphs
    assert first.runs == (ExportRun("Kot", highlight="#aaaaaa"), ExportRun(" spał."))
    assert second.runs == (ExportRun("Pies", highlight="#bbbbbb"), ExportRun(" biegł."))
    assert highlighted.paragraphs[0].text == "Kot spał."


def test_highlights_keep_superscript() -> None:
    # „spał” z „p” w indeksie górnym.
    highlighted = with_highlights(export_document([(5, 6)]), [(4, 8, "#cccccc")])
    assert highlighted.paragraphs[0].runs == (
        ExportRun("Kot "),
        ExportRun("s", highlight="#cccccc"),
        ExportRun("p", superscript=True, highlight="#cccccc"),
        ExportRun("ał", highlight="#cccccc"),
        ExportRun("."),
    )


def test_no_highlights_keep_the_document() -> None:
    document = export_document()
    assert with_highlights(document, []) is document


def test_docx_gets_run_shading(tmp_path) -> None:
    target = tmp_path / "out.docx"
    write_docx(with_highlights(export_document(), [(0, 3, "#d5e7fd")]), target)
    xml = zipfile.ZipFile(target).read("word/document.xml").decode("utf-8")
    assert 'w:fill="D5E7FD"' in xml
    assert xml.count("<w:shd ") == 1


def test_docx_shading_precedes_superscript_in_run_properties(tmp_path) -> None:
    """Kolejność schematu: ``w:shd`` przed ``w:vertAlign`` (Word tego wymaga)."""
    target = tmp_path / "out.docx"
    write_docx(with_highlights(export_document([(5, 6)]), [(4, 8, "#cccccc")]), target)
    xml = zipfile.ZipFile(target).read("word/document.xml").decode("utf-8")
    run = xml[xml.index('w:fill="CCCCCC"') - 200 :]
    assert run.index("<w:shd") < run.index("<w:vertAlign")
