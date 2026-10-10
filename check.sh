#!/usr/bin/env sh
# Formatuje kod (black), a z flagami uruchamia dodatkowo lint, mypy i testy.
#
# Użycie: ./check.sh [-l|--lint] [-m|--mypy] [-t|--test] [-a|--all] [-h|--help]
#
# Wszystkie wybrane kroki są wykonywane nawet po niepowodzeniu wcześniejszego;
# kod wyjścia jest niezerowy, jeśli którykolwiek krok się nie powiódł.
set -eu

cd "$(dirname "$0")"

usage() {
    cat <<'EOF'
Użycie: ./check.sh [opcje]

Zawsze formatuje kod (uv run black .). Dodatkowo:
  -l, --lint    lint (uv run ruff check .)
  -m, --mypy    sprawdzanie typów (uv run mypy)
  -t, --test    testy (uv run pytest -q)
  -a, --all     wszystkie powyższe
  -h, --help    ta pomoc
EOF
}

lint=0
mypy=0
test=0

for arg in "$@"; do
    case "$arg" in
        -l | --lint) lint=1 ;;
        -m | --mypy) mypy=1 ;;
        -t | --test) test=1 ;;
        -a | --all) lint=1 mypy=1 test=1 ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            echo "Nieznana opcja: $arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

failed=""

step() {
    name="$1"
    shift
    echo "==> $name: $*"
    if ! "$@"; then
        failed="$failed $name"
    fi
}

step format uv run black .
[ "$lint" -eq 1 ] && step lint uv run ruff check .
[ "$mypy" -eq 1 ] && step mypy uv run mypy
[ "$test" -eq 1 ] && step test uv run pytest -q

if [ -n "$failed" ]; then
    echo "Niepowodzenie:$failed" >&2
    exit 1
fi
echo "Wszystko OK."
