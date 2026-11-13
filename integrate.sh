#!/usr/bin/env sh
# Scala gałąź agenta z worktree do lokalnego main albo release/X.Y
# (tylko fast-forward).
#
# Użycie: ./integrate.sh [cel]   (z worktree agenta, po commicie)
#   cel: main (domyślnie) albo release/X.Y - poprawka do wydanej serii;
#        po fast-forwardzie release/X.Y skrypt scala ją też do main
#        (./merge-forward.sh X.Y).
#
# Kroki: rebase na celu -> lint, typy, testy -> pod blokadą fast-forward celu.
# Kody wyjścia:
#   0  zmiany są w celu (i w main)
#   1  niepowodzenie sprawdzeń (lint/typy/testy) albo zły stan wejściowy
#   3  konflikt przy rebase albo scalaniu do main (patrz komunikat)
#   4  katalog z wybranym celem (np. główny katalog repo) ma niezacommitowane
#      zmiany; scalenie wstrzymane
#   5  cel przesunął się w trakcie sprawdzeń; uruchom ponownie
set -eu

cd "$(git rev-parse --show-toplevel)"
. ./scripts/branch.sh

target="${1:-main}"
case "$target" in
    main) ;;
    release/*.*) ;;
    *)
        echo "Cel musi być main albo release/X.Y (podano: $target)." >&2
        exit 1
        ;;
esac
if ! git rev-parse --verify --quiet "refs/heads/$target" > /dev/null; then
    echo "Nie ma lokalnej gałęzi $target." >&2
    exit 1
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" = "$target" ] || [ "$branch" = "main" ]; then
    echo "Jesteś na $branch - tryb jednego agenta: nie ma czego scalać." >&2
    exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Masz niezacommitowane zmiany. Najpierw zrób commit." >&2
    exit 1
fi

if ! git merge-base --is-ancestor "$target" HEAD; then
    echo "==> rebase na $target"
    if ! git rebase "$target"; then
        cat >&2 <<EOF
Konflikt przy rebase. Rozwiąż konflikty (zachowaj sens obu stron),
\`git add\` + \`git rebase --continue\`, potem uruchom ./integrate.sh $target ponownie.
EOF
        exit 3
    fi
fi

tested="$(git rev-parse HEAD)"
if ! run_checks; then
    echo "Popraw, zacommituj i uruchom ponownie." >&2
    exit 1
fi

if [ "$(git rev-parse HEAD)" != "$tested" ]; then
    echo "HEAD zmienił się w trakcie sprawdzeń; uruchom ponownie." >&2
    exit 5
fi

take_lock
old="$(git rev-parse "refs/heads/$target")"
if ! git merge-base --is-ancestor "$old" HEAD; then
    echo "$target przesunął się w trakcie sprawdzeń; uruchom ponownie." >&2
    exit 5
fi
advance_branch "$target" "$tested" "$old" || exit $?
release_lock
echo "Gałąź $branch jest w $target."

if [ "$target" != "main" ]; then
    ./merge-forward.sh "$target"
fi
