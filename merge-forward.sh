#!/usr/bin/env sh
# Scala gałąź poprawek release/X.Y do main („w przód”).
#
# Użycie: ./merge-forward.sh X.Y   (albo release/X.Y)
#
# Poprawki do wydanej serii (np. 0.8.x) powstają na release/X.Y i od razu
# trafiają też do main - nigdy odwrotnie, więc wydanie z release/X.Y nie
# zawiera zmian szykowanych na main. Workflow „Wydanie” scala gałąź po
# wydaniu sam; ten skrypt robi to lokalnie po każdej poprawce (wywołuje go
# też `./integrate.sh release/X.Y`).
#
# Kroki: w osobnym worktree ($GIT_COMMON_DIR/merge-forward, odłączony HEAD,
# zachowywany między uruchomieniami razem z .venv) `git merge --no-ff`
# gałęzi do main -> lint, typy, testy -> pod blokadą fast-forward main do
# commitu scalenia. Main w głównym katalogu ani w worktree agentów nie jest
# ruszany inaczej niż fast-forwardem.
#
# Kody wyjścia:
#   0  gałąź jest w main (także gdy nie było czego scalać)
#   1  niepowodzenie sprawdzeń albo zły stan wejściowy
#   3  konflikt: rozwiąż go w katalogu scalenia (ścieżka w komunikacie),
#      `git add` + `git commit --no-edit`, uruchom ponownie
#   4  main jest wybrany w katalogu z niezacommitowanymi zmianami
#   5  main przesunął się w trakcie sprawdzeń; uruchom ponownie
set -eu

root="$(git rev-parse --show-toplevel)"
. "$root/scripts/branch.sh"

if [ $# -ne 1 ]; then
    echo "Użycie: ./merge-forward.sh X.Y" >&2
    exit 1
fi
series="${1#release/}"
branch="release/$series"
if ! git rev-parse --verify --quiet "refs/heads/$branch" > /dev/null; then
    echo "Nie ma lokalnej gałęzi $branch." >&2
    exit 1
fi

dir="$(git rev-parse --path-format=absolute --git-common-dir)/merge-forward"
message="chore: merge $branch into main"

if [ -d "$dir" ] && git -C "$dir" rev-parse --verify --quiet MERGE_HEAD > /dev/null; then
    echo "Scalenie w $dir ma nierozwiązane konflikty: rozwiąż je," >&2
    echo "\`git add\` + \`git commit --no-edit\`, potem uruchom ponownie." >&2
    exit 3
fi

old_main="$(git rev-parse refs/heads/main)"
tip="$(git rev-parse "refs/heads/$branch")"

if [ -d "$dir" ] && [ "$(git -C "$dir" log -1 --format=%s)" = "$message" ] \
    && [ "$(git -C "$dir" rev-parse HEAD^1)" = "$old_main" ] \
    && [ "$(git -C "$dir" rev-parse HEAD^2)" = "$tip" ]; then
    echo "==> kontynuacja rozwiązanego scalenia w $dir"
elif git merge-base --is-ancestor "$tip" "$old_main"; then
    echo "Gałąź $branch jest już w main."
    exit 0
else
    if [ ! -d "$dir" ]; then
        git worktree add --detach "$dir" "$old_main"
    else
        git -C "$dir" checkout --quiet --detach "$old_main"
    fi
    echo "==> scalenie $branch do main w $dir"
    if ! git -C "$dir" merge --no-ff "$branch" -m "$message"; then
        cat >&2 <<EOF
Konflikt przy scalaniu $branch do main. Rozwiąż konflikty w:
  $dir
(zachowaj sens obu stron), \`git add\` + \`git commit --no-edit\`,
potem uruchom ./merge-forward.sh $series ponownie.
EOF
        exit 3
    fi
fi

merged="$(git -C "$dir" rev-parse HEAD)"
if ! (cd "$dir" && run_checks); then
    echo "Popraw błędy na $branch, zacommituj i uruchom ponownie." >&2
    exit 1
fi

take_lock
advance_branch main "$merged" "$old_main" || exit $?
echo "Gałąź $branch jest w main."
