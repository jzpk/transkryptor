"""Testy modelu dokumentu: tekst, indeksy górne, metadane, stan zmian."""

import pytest

from transkryptor.document.model import Document


class TestText:
    def test_polish_characters_and_markers_are_preserved(self) -> None:
        """ACC-01 na poziomie domeny: tekst i polskie znaki bez zamiany."""
        doc = Document(text="pamientam uóna zmar-zły jeż...")
        assert doc.text == "pamientam uóna zmar-zły jeż..."

    def test_replace_inserts_text(self) -> None:
        doc = Document(text="sóm")
        doc.replace(3, 3, " pani")
        assert doc.text == "sóm pani"

    def test_replace_rejects_invalid_range(self) -> None:
        doc = Document(text="bendzie")
        with pytest.raises(ValueError):
            doc.replace(5, 2, "x")
        with pytest.raises(ValueError):
            doc.replace(0, 99, "x")


class TestSuperscriptRanges:
    def test_enable_superscript(self) -> None:
        doc = Document(text="pamientam")
        doc.set_superscript(3, 4)
        assert doc.superscript_ranges == [(3, 4)]

    def test_adjacent_ranges_merge(self) -> None:
        doc = Document(text="buo")
        doc.set_superscript(0, 1)
        doc.set_superscript(1, 2)
        assert doc.superscript_ranges == [(0, 2)]

    def test_disable_superscript_subtracts_middle(self) -> None:
        doc = Document(text="pamientam")
        doc.set_superscript(0, 9)
        doc.set_superscript(3, 6, enabled=False)
        assert doc.superscript_ranges == [(0, 3), (6, 9)]

    def test_replace_before_range_shifts_it(self) -> None:
        doc = Document(text="pamientam")
        doc.set_superscript(3, 4)
        doc.replace(0, 0, "xx")
        assert doc.text == "xxpamientam"
        assert doc.superscript_ranges == [(5, 6)]

    def test_replace_after_range_keeps_it(self) -> None:
        doc = Document(text="pamientam")
        doc.set_superscript(0, 2)
        doc.replace(7, 9, "em")
        assert doc.superscript_ranges == [(0, 2)]

    def test_replace_inside_range_truncates_it(self) -> None:
        doc = Document(text="pamientam")
        doc.set_superscript(2, 6)
        doc.replace(4, 9, "o")
        assert doc.text == "pamio"
        assert doc.superscript_ranges == [(2, 4)]

    def test_replace_spanning_range_splits_it(self) -> None:
        doc = Document(text="pamientam")
        doc.set_superscript(0, 9)
        doc.replace(3, 6, "XYZ")
        assert doc.text == "pamXYZtam"
        assert doc.superscript_ranges == [(0, 3), (6, 9)]

    def test_inserted_text_is_not_superscript(self) -> None:
        doc = Document(text="bendzie")
        doc.set_superscript(1, 3)
        doc.replace(2, 2, "ZZ")
        assert doc.text == "beZZndzie"
        assert doc.superscript_ranges == [(1, 2), (4, 5)]

    def test_range_fully_replaced_is_removed(self) -> None:
        doc = Document(text="pamientam")
        doc.set_superscript(3, 5)
        doc.replace(2, 7, "u")
        assert doc.superscript_ranges == []


class TestDirtyState:
    def test_new_document_is_clean(self) -> None:
        assert not Document().is_dirty

    def test_edit_marks_document_dirty(self) -> None:
        doc = Document(text="tekst")
        doc.replace(0, 0, "x")
        assert doc.is_dirty

    def test_metadata_change_marks_document_dirty(self) -> None:
        doc = Document()
        doc.set_metadata("Jan Kowalski", "2026-09-23")
        assert doc.is_dirty
        assert doc.author == "Jan Kowalski"
        assert doc.date == "2026-09-23"

    def test_unchanged_metadata_does_not_dirty(self) -> None:
        doc = Document()
        doc.set_metadata("", "")
        assert not doc.is_dirty

    def test_mark_exported_clears_dirty_state(self) -> None:
        doc = Document(text="kuosa")
        doc.replace(0, 0, "!")
        doc.mark_exported()
        assert not doc.is_dirty

    def test_edit_after_export_marks_dirty_again(self) -> None:
        doc = Document(text="kuosa")
        doc.replace(0, 0, "!")
        doc.mark_exported()
        doc.set_superscript(0, 1)
        assert doc.is_dirty

    def test_revision_increments_on_every_mutation(self) -> None:
        doc = Document()
        doc.replace(0, 0, "a")
        doc.set_metadata("autor", "data")
        doc.set_superscript(0, 1)
        assert doc.revision == 3
        assert doc.exported_revision == 0


class TestMetadataAndSaveState:
    """Faza 08: metryczka i rozróżnienie „niezapisany” / „niewyeksportowany”."""

    def test_metadata_values_bump_revision_only_on_change(self) -> None:
        doc = Document()
        doc.set_metadata_values({"signature": "AdK_1954", "place": ""})
        assert doc.metadata == {"signature": "AdK_1954"}
        assert doc.revision == 1
        doc.set_metadata_values({"place": ""})
        assert doc.revision == 1
        doc.set_metadata_values({"signature": ""})
        assert doc.metadata == {}
        assert doc.revision == 2

    def test_saved_and_exported_are_independent(self) -> None:
        doc = Document(text="sóm")
        doc.replace(3, 3, " pani")
        doc.mark_saved()
        assert not doc.is_unsaved
        assert doc.is_dirty  # zapisany, ale niewyeksportowany
        doc.mark_exported()
        doc.touch()
        assert doc.is_unsaved and doc.is_dirty
