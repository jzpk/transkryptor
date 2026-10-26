"""Skan folderu projektów, konkordancja i słownik form (wymagania 7 i 8)."""

from pathlib import Path

import pytest

from transkryptor.corpus.concordance import (
    CONTEXT_CHARS,
    ELLIPSIS,
    concordance,
    make_hit,
    marked_text,
)
from transkryptor.corpus.forms import form_index, form_of, similar_forms
from transkryptor.corpus.projects import CorpusProject, find_projects, scan_folder
from transkryptor.document.project import ProjectState
from transkryptor.document.search import SearchError, SearchOptions, compile_query


def names(projects, folder: Path) -> list[str]:
    return [project.relative_name(folder) for project in projects]


class TestScan:
    def test_finds_projects_in_subfolders_without_hidden(self, corpus_dir) -> None:
        found = find_projects(corpus_dir)
        assert [p.relative_to(corpus_dir).as_posix() for p in found] == [
            "AdK_1954.transkr",
            "uszkodzony.transkr",
            "wies/B_1960.transkr",
        ]

    def test_unreadable_project_is_reported_not_fatal(self, corpus_dir) -> None:
        scan = scan_folder(corpus_dir)
        assert names(scan.projects, corpus_dir) == [
            "AdK_1954.transkr",
            "wies/B_1960.transkr",
        ]
        assert [error.path.name for error in scan.errors] == ["uszkodzony.transkr"]
        assert scan.errors[0].message

    def test_override_replaces_saved_state(self, corpus_dir) -> None:
        live = ProjectState(text="niezapisany tekst")
        scan = scan_folder(corpus_dir, {corpus_dir / "AdK_1954.transkr": live})
        assert scan.projects[0].state is live

    def test_progress_can_cancel(self, corpus_dir) -> None:
        scan = scan_folder(corpus_dir, progress=lambda done, _total: done < 1)
        assert len(scan.projects) == 1

    def test_audio_path_resolves_relative_to_project(self, tmp_path) -> None:
        from transkryptor.document.project import audio_ref, save_project

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"RIFF")
        path = tmp_path / "p.transkr"
        save_project(ProjectState(text="x", audio=audio_ref(audio)), path)
        project = scan_folder(tmp_path).projects[0]
        assert project.audio_path() == audio


class TestConcordance:
    def search(self, corpus_dir, query: str, **options):
        informant = options.pop("informant_only", False)
        scan = scan_folder(corpus_dir)
        pattern = compile_query(query, SearchOptions(**options))
        return concordance(scan.projects, pattern, informant)

    def test_hits_in_all_projects_with_context_speaker_and_time(
        self, corpus_dir
    ) -> None:
        result = self.search(corpus_dir, "jak", whole_words=True)
        assert result.project_count == 2
        first, second = result.hits
        assert first.project.name == "AdK_1954"
        assert (first.left, first.match, first.right) == (
            "No ^bendzie ",
            "jak",
            " było",
        )
        assert first.speaker == "I"
        # Słowo z czasem jest dokładniejsze niż segment.
        assert first.time_ms == (4000, 4500)
        assert second.project.name == "B_1960"
        assert (second.left, second.match, second.right) == ("", "jak", " tak to tak")
        assert second.time_ms is None

    def test_context_stays_in_paragraph(self, corpus_dir) -> None:
        hit = self.search(corpus_dir, "No").hits[0]
        assert hit.left == ""
        assert "\n" not in hit.right and "było?" not in hit.left

    def test_informant_only(self, corpus_dir) -> None:
        result = self.search(corpus_dir, "było", informant_only=True)
        assert [(hit.project.name, hit.start) for hit in result.hits] == [
            ("AdK_1954", 28)
        ]

    def test_limit_truncates(self, corpus_dir) -> None:
        scan = scan_folder(corpus_dir)
        pattern = compile_query("a", SearchOptions())
        result = concordance(scan.projects, pattern, limit=2)
        assert len(result.hits) == 2 and result.truncated

    def test_long_context_is_shortened(self) -> None:
        text = "x" * 100 + " jak " + "y" * 100
        project = CorpusProject(None, ProjectState(text=text), "bieżący")
        hit = make_hit(project, 101, 104)
        assert hit.left.startswith(ELLIPSIS)
        assert len(hit.left) == CONTEXT_CHARS + 1
        assert hit.right.endswith(ELLIPSIS)

    def test_costly_pattern_is_an_error(self, corpus_dir) -> None:
        with pytest.raises(SearchError):
            self.search(corpus_dir, "(", regex=True)

    def test_marked_text(self) -> None:
        assert marked_text("bendzie", ((0, 1), (3, 4)), 0, 7) == "^ben^dzie"
        assert marked_text("bendzie", (), 1, 3) == "en"


class TestForms:
    def test_counts_occurrences_lowercase_with_superscript(self, corpus_dir) -> None:
        scan = scan_folder(corpus_dir)
        entries = {entry.form: entry for entry in form_index(scan.projects)}
        assert entries["było"].count == 2
        assert entries["jak"].count == 2 and entries["jak"].project_count == 2
        assert entries["tak"].count == 2 and entries["tak"].project_count == 1
        assert "^bendzie" in entries and "bendzie" not in entries
        assert entries["jag"].count == 1
        occurrence = entries["jag"].occurrences[0]
        text = occurrence.project.state.text
        assert text[occurrence.start : occurrence.end] == "Jag"

    def test_order_by_count_then_alphabetically(self) -> None:
        project = CorpusProject(None, ProjectState(text="b a b c a b"), "x")
        assert [e.form for e in form_index([project])] == ["b", "a", "c"]

    def test_case_sensitive(self) -> None:
        project = CorpusProject(None, ProjectState(text="Jak jak"), "x")
        assert {e.form for e in form_index([project], case_sensitive=True)} == {
            "Jak",
            "jak",
        }

    def test_informant_only(self, state_a) -> None:
        project = CorpusProject(None, state_a, "x")
        forms = {e.form for e in form_index([project], informant_only=True)}
        assert "jag" not in forms and "jak" in forms

    def test_words_keep_inner_hyphen_and_apostrophe(self) -> None:
        project = CorpusProject(
            None, ProjectState(text="bez-tego [...] (?) O'Neil 12"), "x"
        )
        assert [e.form for e in form_index([project])] == ["bez-tego", "o'neil"]

    def test_form_of_marks_superscript(self) -> None:
        assert form_of("Bendzie", ((0, 1),), 0, 7) == "^bendzie"
        assert form_of("Bendzie", ((0, 1),), 0, 7, case_sensitive=True) == "^Bendzie"

    def test_similar_forms_one_character_apart(self) -> None:
        similar = similar_forms(["jag", "jak", "dom", "^bendzie", "bendzie", "a", "i"])
        assert similar["jag"] == ("jak",)
        assert similar["jak"] == ("jag",)
        assert similar["bendzie"] == ("^bendzie",)
        assert "dom" not in similar
        # Formy jednoliterowe nie są porównywane.
        assert "a" not in similar
