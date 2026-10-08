"""Tworzenie artefaktów Windows/Linux.

Granica modułu: nie jest częścią procesu uruchomieniowego aplikacji —
importuje go wyłącznie narzędzie wydania i jego testy.

Podział odpowiedzialności:

- ``metadata`` — nazwy, wersja, wymagania sprzętowe i nazwy artefaktów;
- ``bundle`` — co PyInstaller ma spakować (ukryte importy, zasoby, wykluczenia);
- ``licenses`` — komplet licencji aplikacji, zależności i bibliotek natywnych;
- ``windows`` — skrypt i kompilacja instalatora Inno Setup;
- ``linux`` — AppDir i obraz AppImage;
- ``checksums`` — sumy kontrolne w formacie ``sha256sum``;
- ``release_notes`` — noty wydania dla użytkownika;
- ``build`` — narzędzie wiersza poleceń spinające powyższe kroki.
"""

from transkryptor.packaging.metadata import APP_NAME, VERSION

__all__ = ["APP_NAME", "VERSION"]
