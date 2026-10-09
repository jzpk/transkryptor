"""Konwencja zgłaszania błędów importu, eksportu i pobierania modelu.

Zgodnie z NFR-03 każdy błąd operacyjny jest prezentowany zrozumiałym
komunikatem oraz możliwością ponowienia działania. Klasy zdefiniowane tutaj
są wykorzystywane przez moduły audio, export i asr w kolejnych fazach.
"""


class AppError(Exception):
    """Bazowy błąd aplikacji z komunikatem dla użytkownika i wskazówką ponowienia."""

    def __init__(self, user_message: str, retry_hint: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.retry_hint = retry_hint


class ImportAudioError(AppError):
    """Nie udało się zaimportować lub odczytać pliku audio."""


class ExportError(AppError):
    """Nie udało się wyeksportować dokumentu DOCX."""


class ModelDownloadError(AppError):
    """Nie udało się pobrać lub zweryfikować lokalnego modelu ASR."""


class UpdateError(AppError):
    """Nie udało się sprawdzić, pobrać lub zweryfikować nowej wersji aplikacji."""


class ProjectError(AppError):
    """Nie udało się zapisać lub otworzyć pliku projektu."""


class ImportDocxError(AppError):
    """Nie udało się zaimportować dokumentu DOCX."""
