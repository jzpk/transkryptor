# Środowisko budowania AppImage.
#
# Ubuntu 22.04 wyznacza najstarszą obsługiwaną glibc (2.35, patrz
# LINUX_GLIBC_BASELINE w src/transkryptor/packaging/metadata.py). Budowanie
# na nowszym systemie deweloperskim dałoby AppImage, który nie uruchomi się
# na starszych dystrybucjach — dlatego zawsze budujemy w tym obrazie.
#
# Kontekst budowania: pyproject.toml, uv.lock i README.md (przygotowuje je
# scripts/build-installers.sh). Kod źródłowy jest montowany przy uruchomieniu.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
# binutils: objdump do analizy zależności PyInstallera; file: dla appimagetool.
# Pozostałe biblioteki są potrzebne, by zaimportować Qt podczas analizy
# PyInstallera i uruchomić --self-test gotowego artefaktu (libpulse0: Qt
# Multimedia; na komputerach użytkowników jest częścią systemu dźwięku).
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates curl binutils file \
        libegl1 libgl1 libxkbcommon-x11-0 libdbus-1-3 libfontconfig1 libglib2.0-0 libpulse0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

ARG APPIMAGETOOL_VERSION=1.9.1
RUN curl -fsSL -o /usr/local/bin/appimagetool \
        "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage" \
    && chmod +x /usr/local/bin/appimagetool

# W kontenerze nie ma FUSE: appimagetool i gotowy AppImage rozpakowują się
# do katalogu tymczasowego zamiast montować obraz.
ENV APPIMAGE_EXTRACT_AND_RUN=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy

# Zależności z uv.lock w osobnej warstwie: obraz przebudowuje się tylko
# po zmianie blokady.
WORKDIR /tmp/project
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --group packaging --no-install-project \
    && chmod -R a+rX /opt/venv /opt/python

WORKDIR /src
