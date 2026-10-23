#!/usr/bin/env sh
# Scala gałąź agenta z worktree do lokalnego main (tylko fast-forward).
#
# Użycie: ./integrate.sh   (uruchamiane z worktree agenta, po commicie)
#
# Kroki: rebase na main -> lint, typy, testy -> pod blokadą fast-forward main.
# Kody wyjścia:
#   0  zmiany są w main
#   1  niepowodzenie sprawdzeń (lint/typy/testy) albo zły stan wejściowy
#   3  konflikt przy rebase: rozwiąż, `git rebase --continue`, uruchom ponownie
#   4  główny katalog repo ma niezacommitowane zmiany; scalenie wstrzymane
#   5  main przesunął się w trakcie sprawdzeń; uruchom ponownie
set -eu

cd "$(git rev-parse --show-toplevel)"

branch="$(git rev-parse --abbrev-ref HEAD)"
main_root="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"

if [ "$branch" = "main" ] || [ "$(pwd -P)" = "$(cd "$main_root" && pwd -P)" ]; then
    echo "Tryb jednego agenta (main w głównym katalogu): nie ma czego scalać." >&2
    exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Masz niezacommitowane zmiany. Najpierw zrób commit." >&2
    exit 1
fi

if [ "$(git -C "$main_root" rev-parse --abbrev-ref HEAD)" != "main" ]; then
    echo "W głównym katalogu ($main_root) nie jest wybrana gałąź main." >&2
    exit 1
fi

if ! git merge-base --is-ancestor main HEAD; then
    echo "==> rebase na main"
    if ! git rebase main; then
        cat >&2 <<'EOF'
Konflikt przy rebase. Rozwiąż konflikty (zachowaj sens obu stron),
`git add` + `git rebase --continue`, potem uruchom ./integrate.sh ponownie.
EOF
        exit 3
    fi
fi

tested="$(git rev-parse HEAD)"

failed=""
step() {
    name="$1"
    shift
    echo "==> $name: $*"
    if ! "$@"; then
        failed="$failed $name"
    fi
}
step lint uv run ruff check .
step format uv run black --check .
step mypy uv run mypy
step test uv run pytest -q
if [ -n "$failed" ]; then
    echo "Niepowodzenie:$failed. Popraw, zacommituj i uruchom ponownie." >&2
    exit 1
fi

if [ "$(git rev-parse HEAD)" != "$tested" ]; then
    echo "HEAD zmienił się w trakcie sprawdzeń; uruchom ponownie." >&2
    exit 5
fi

lock="$(git rev-parse --git-common-dir)/integrate.lock"
exec 9>"$lock"
flock 9

if ! git merge-base --is-ancestor main HEAD; then
    echo "Main przesunął się w trakcie sprawdzeń; uruchom ponownie." >&2
    exit 5
fi

if [ -n "$(git -C "$main_root" status --porcelain --untracked-files=no)" ]; then
    cat >&2 <<EOF
Główny katalog repo ($main_root) ma niezacommitowane zmiany.
Scalenie wstrzymane, żeby ich nie naruszyć. Zgłoś to użytkownikowi.
EOF
    exit 4
fi

echo "==> fast-forward main do $branch"
git -C "$main_root" merge --ff-only "$branch"
echo "Gałąź $branch jest w main."
