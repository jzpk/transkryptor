# Wspólne kroki integrate.sh i merge-forward.sh (wczytywane przez `.`).
#
# Gałąź może być wybrana w dowolnym worktree (main zwykle w głównym
# katalogu, release/X.Y w worktree agenta albo nigdzie). Przesunięcie gałęzi
# odbywa się tylko fast-forwardem: przez `git merge --ff-only` w worktree,
# w którym jest wybrana (żeby jej pliki się zgadzały), a gdy nigdzie nie jest
# wybrana - przez `git update-ref` z kontrolą starej wartości.

# Katalog worktree, w którym wybrana jest gałąź $1 (pusty, gdy żaden).
branch_worktree() {
    git worktree list --porcelain | awk -v ref="refs/heads/$1" '
        /^worktree / { dir = substr($0, 10) }
        $0 == "branch " ref { print dir; exit }
    '
}

# Sprawdzenia przed scaleniem: lint, formatowanie, typy, testy. Kod 1, gdy
# któreś się nie powiodło (wykonuje wszystkie). TRANSKRYPTOR_CHECKS zastępuje
# je jednym poleceniem - test skryptów na sztucznym repozytorium
# (tests/test_release_branches.py) nie ma czego lintować.
run_checks() {
    if [ -n "${TRANSKRYPTOR_CHECKS:-}" ]; then
        sh -c "$TRANSKRYPTOR_CHECKS"
        return
    fi
    failed=""
    _step lint uv run ruff check .
    _step format uv run black --check .
    _step mypy uv run mypy
    _step test uv run pytest -q
    if [ -n "$failed" ]; then
        echo "Niepowodzenie:$failed." >&2
        return 1
    fi
}

_step() {
    name="$1"
    shift
    echo "==> $name: $*"
    if ! "$@"; then
        failed="$failed $name"
    fi
}

# Blokada wspólna dla wszystkich scaleń w repozytorium (deskryptor 9).
take_lock() {
    exec 9>"$(git rev-parse --git-common-dir)/integrate.lock"
    flock 9
}

release_lock() {
    exec 9>&-
}

# Fast-forward gałęzi $1 z $3 (oczekiwana stara wartość) do $2.
# Kod 4: gałąź jest wybrana w katalogu z niezacommitowanymi zmianami.
# Kod 5: gałąź przesunęła się (stara wartość się nie zgadza).
advance_branch() {
    target="$1"
    new="$2"
    old="$3"
    if [ "$(git rev-parse "refs/heads/$target")" != "$old" ]; then
        echo "$target przesunął się w trakcie sprawdzeń; uruchom ponownie." >&2
        return 5
    fi
    dir="$(branch_worktree "$target")"
    if [ -z "$dir" ]; then
        echo "==> fast-forward $target (gałąź nie jest nigdzie wybrana)"
        git update-ref -m "fast-forward $target" "refs/heads/$target" "$new" "$old"
        return 0
    fi
    if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]; then
        cat >&2 <<MSG
Katalog $dir (gałąź $target) ma niezacommitowane zmiany.
Scalenie wstrzymane, żeby ich nie naruszyć. Zgłoś to użytkownikowi.
MSG
        return 4
    fi
    echo "==> fast-forward $target w $dir"
    git -C "$dir" merge --ff-only "$new"
}
