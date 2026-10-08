#!/usr/bin/env sh
# Uruchamia aplikację Transkryptor.
# Przy pierwszym uruchomieniu (lub po zmianie uv.lock) synchronizuje środowisko.
set -eu

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Tworzę środowisko (uv sync)..."
    uv sync
fi

exec uv run transkryptor "$@"
