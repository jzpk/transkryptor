"""Stan projektu ↔ widoki okna: zapis (``capture``) i odtworzenie (``restore_*``).

``SessionController`` decyduje, kiedy zapisać albo zastąpić pracę (pytania
o zmiany, nagranie, dokument), a ten moduł tylko przepisuje dane między
``ProjectState`` a widokami sesji (``ui/session_views.py``) i danymi projektu
spoza tekstu (``ProjectAnnotations``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from transkryptor.asr.project_draft import draft_from_result, result_from_draft
from transkryptor.document.model import Document
from transkryptor.document.project import AsrContext, AudioRef, ProjectState
from transkryptor.ui.comments_controller import CommentsController
from transkryptor.ui.notation_controller import IgnoredWarnings
from transkryptor.ui.review import ReviewController
from transkryptor.ui.session_views import SessionViews
from transkryptor.ui.sync_controller import SyncController
from transkryptor.ui.verification import VerificationController
from transkryptor.ui.work_time import WorkTimeTracker


@dataclass(frozen=True)
class ProjectAnnotations:
    """Dane projektu poza tekstem: przegląd reguł, zignorowane ostrzeżenia,
    kotwice czasowe, komentarze, sprawdzone zakresy nagrania i czas pracy."""

    review: ReviewController
    ignored_warnings: IgnoredWarnings
    sync: SyncController
    comments: CommentsController
    verification: VerificationController
    work: WorkTimeTracker


class ProjectStateMapper:
    """Przepisuje stan projektu z widoków i do nich (bez pytań i dialogów)."""

    def __init__(
        self,
        views: SessionViews,
        annotations: ProjectAnnotations,
        active_profile: Callable[[], str],
    ) -> None:
        self._views = views
        self._annotations = annotations
        self._active_profile = active_profile

    def capture(self, document: Document, audio: AudioRef | None) -> ProjectState:
        """Bieżący stan pracy w formacie projektu."""
        views, notes = self._views, self._annotations
        result = views.asr.last_result
        prompt, vocabulary = views.asr.asr_context()
        has_audio = views.player.source_path is not None
        return ProjectState(
            text=document.text,
            superscript_ranges=tuple(document.superscript_ranges),
            author=document.author,
            date=document.date,
            metadata=dict(document.metadata),
            exported=not document.is_dirty,
            audio=audio if has_audio else None,
            player=views.player_bar.state(),
            asr=(
                None
                if result is None
                else draft_from_result(result, views.asr.last_model_key)
            ),
            review=tuple(notes.review.entries()),
            asr_context=AsrContext(
                prompt=prompt,
                vocabulary=vocabulary,
                questionnaire=views.asr.questionnaire(),
                question_marks=views.asr.question_marks(),
            ),
            ignored_warnings=tuple(notes.ignored_warnings.entries()),
            anchors=tuple(notes.sync.entries()),
            speakers=tuple(document.speakers),
            paragraph_speakers=dict(document.paragraph_speakers),
            comments=tuple(notes.comments.entries()),
            verified=notes.verification.entries(),
            work=notes.work.entries(),
            profile=self._active_profile(),
            draft_baseline=notes.review.baseline,
        )

    def restore_content(self, state: ProjectState) -> bool:
        """Tekst, metryczka i kontekst ASR; zwraca, czy data była poprawna."""
        views, notes = self._views, self._annotations
        views.editor.load_content(
            state.text, state.superscript_ranges, state.paragraph_speakers
        )
        notes.ignored_warnings.restore(state.ignored_warnings)
        notes.comments.restore(state.comments)
        date_valid = views.metadata.restore(state.author, state.date, state.metadata)
        views.asr.set_asr_context(
            state.asr_context.prompt, state.asr_context.vocabulary
        )
        views.asr.set_questionnaire(
            state.asr_context.questionnaire, state.asr_context.question_marks
        )
        return date_valid

    def restore_annotations(self, state: ProjectState) -> None:
        """Szkic ASR, przegląd, kotwice, sprawdzone zakresy i czas pracy.

        Wołane po wczytaniu nagrania - kotwice i szkic dotyczą jego czasu.
        """
        views, notes = self._views, self._annotations
        views.asr.restore_result(
            result_from_draft(state.asr),
            model_key=state.asr.model if state.asr is not None else None,
        )
        notes.review.restore(state.review)
        notes.review.restore_baseline(state.draft_baseline)
        notes.sync.restore(state.anchors)
        notes.verification.restore(state.verified)
        notes.work.restore(state.work)

    def clear(self) -> None:
        """Nowy dokument: puste widoki i dane projektu."""
        views, notes = self._views, self._annotations
        views.asr.restore_result(None)
        views.asr.set_asr_context("", ())
        views.asr.set_questionnaire(())
        views.editor.blockSignals(True)
        views.editor.clear()
        views.editor.blockSignals(False)
        notes.sync.clear()
        notes.review.restore_baseline(None)
        notes.comments.clear()
        notes.verification.clear()
        notes.work.clear()
        views.metadata.clear()


__all__ = ["ProjectAnnotations", "ProjectStateMapper"]
