"""Scenariusz gałęzi wydań na sztucznym repozytorium.

Poprawki serii 0.8 powstają na ``release/0.8`` (``integrate.sh release/0.8``)
i są scalane w przód do ``main`` (``merge-forward.sh``), a ``main`` szykuje
0.9.0. Wydanie 0.8.x z ``release/0.8`` nie może zawierać zmian z ``main``,
a fragmenty changeloga 0.9.0 muszą przetrwać scalenie wydanej poprawki.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from transkryptor.packaging import changelog

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("integrate.sh", "merge-forward.sh", "scripts/branch.sh")

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("flock") is None,
    reason="skrypty scalania wymagają sh i flock",
)


class Repo:
    """Sztuczne repozytorium z kopiami skryptów scalania."""

    def __init__(self, root: Path, home: Path) -> None:
        self.root = root
        self.env = {
            **os.environ,
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "TRANSKRYPTOR_CHECKS": "true",
        }

    def run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            cwd=cwd or self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def git(self, *args: str, cwd: Path | None = None) -> str:
        result = self.run("git", *args, cwd=cwd)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def write(self, relative: str, text: str, cwd: Path | None = None) -> None:
        path = (cwd or self.root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str, cwd: Path | None = None) -> None:
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "-m", message, cwd=cwd)

    def show(self, ref: str, path: str) -> str | None:
        result = self.run("git", "show", f"{ref}:{path}")
        return result.stdout if result.returncode == 0 else None

    def release(self, version: str, cwd: Path) -> None:
        """Jak job „wersja” workflow: changelog, wersja, commit, tag."""
        changelog.release(version, date(2026, 12, 1), cwd / "CHANGELOG.md")
        self.write("VERSION", f"{version}\n", cwd)
        self.commit(f"Wydanie v{version}", cwd)
        self.git("tag", f"v{version}", cwd=cwd)


@pytest.fixture
def repo(tmp_path) -> Repo:
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "home").mkdir()
    repo = Repo(root, tmp_path / "home")
    repo.git("init", "-q", "-b", "main")
    for name in SCRIPTS:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, target)
    repo.write(
        "CHANGELOG.md", "# Historia zmian\n\n## 0.8.1 - 2026-11-13\n\n- Stare.\n"
    )
    repo.write("changelog.d/README.md", "# Fragmenty\n")
    repo.write("VERSION", "0.8.1\n")
    repo.write("app.txt", "podstawa\n")
    repo.commit("Wydanie v0.8.1")
    repo.git("tag", "v0.8.1")
    repo.git("branch", "release/0.8")
    return repo


def _agent_fix(repo: Repo, tmp_path: Path, name: str) -> Path:
    """Poprawka agenta w worktree na gałęzi z release/0.8."""
    worktree = tmp_path / name
    repo.git("worktree", "add", "-q", "-b", name, str(worktree), "release/0.8")
    repo.write(f"{name}.txt", "poprawka\n", worktree)
    repo.write(f"changelog.d/{name}.md", f"- Poprawka {name}.\n", worktree)
    repo.commit(f"fix: {name}\n\nCloses #1", worktree)
    return worktree


def test_patch_releases_skip_main_work_and_merge_forward(repo, tmp_path) -> None:
    # main szykuje 0.9.0 (praca w głównym katalogu, tryb jednego agenta).
    repo.write("feature09.txt", "nowość\n")
    repo.write("changelog.d/feature09.md", "- Nowość 0.9.\n")
    repo.commit("feat: feature for 0.9")

    # Poprawka do 0.8.2 przez integrate.sh: release/0.8 i od razu main.
    worktree = _agent_fix(repo, tmp_path, "fix-a")
    result = repo.run("./integrate.sh", "release/0.8", cwd=worktree)
    assert result.returncode == 0, result.stdout + result.stderr
    assert repo.show("release/0.8", "fix-a.txt") == "poprawka\n"
    assert repo.show("main", "fix-a.txt") == "poprawka\n"
    assert repo.show("release/0.8", "feature09.txt") is None
    assert (repo.root / "fix-a.txt").is_file()  # main w głównym katalogu

    # Wydanie 0.8.2 z release/0.8 i scalenie w przód.
    release_dir = tmp_path / "release"
    repo.git("worktree", "add", "-q", str(release_dir), "release/0.8")
    repo.release("0.8.2", release_dir)
    result = repo.run("./merge-forward.sh", "0.8", cwd=release_dir)
    assert result.returncode == 0, result.stdout + result.stderr

    # Kolejna poprawka i wydanie 0.8.3 - nadal bez zmian z main.
    worktree = _agent_fix(repo, tmp_path, "fix-b")
    result = repo.run("./integrate.sh", "release/0.8", cwd=worktree)
    assert result.returncode == 0, result.stdout + result.stderr
    repo.git("merge", "-q", "--ff-only", "release/0.8", cwd=release_dir)
    repo.release("0.8.3", release_dir)
    result = repo.run("./merge-forward.sh", "release/0.8", cwd=release_dir)
    assert result.returncode == 0, result.stdout + result.stderr

    assert repo.show("v0.8.3", "feature09.txt") is None
    assert repo.show("v0.8.3", "changelog.d/feature09.md") is None
    released = repo.show("v0.8.3", "CHANGELOG.md") or ""
    assert changelog.section(released, "0.8.2") == "- Poprawka fix-a."
    assert changelog.section(released, "0.8.3") == "- Poprawka fix-b."

    main_log = repo.show("main", "CHANGELOG.md")
    assert main_log == released
    assert repo.show("main", "VERSION") == "0.8.3\n"
    assert repo.show("main", "feature09.txt") == "nowość\n"
    assert repo.show("main", "changelog.d/feature09.md") == "- Nowość 0.9.\n"
    assert repo.show("main", "changelog.d/fix-a.md") is None
    assert repo.show("main", "changelog.d/fix-b.md") is None
    assert repo.git("status", "--porcelain") == ""

    # Nic do scalenia: kod 0 bez zmian w main.
    head = repo.git("rev-parse", "main")
    assert repo.run("./merge-forward.sh", "0.8").returncode == 0
    assert repo.git("rev-parse", "main") == head


def test_merge_forward_conflict_is_resolved_and_resumed(repo) -> None:
    repo.write("app.txt", "main\n")
    repo.commit("feat: change on main")
    repo.git("checkout", "-q", "release/0.8")
    repo.write("app.txt", "poprawka\n")
    repo.commit("fix: change on release")

    result = repo.run("./merge-forward.sh", "0.8")
    assert result.returncode == 3
    merge_dir = Path(
        repo.git("rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    merge_dir = merge_dir / "merge-forward"
    assert str(merge_dir) in result.stderr
    assert repo.run("./merge-forward.sh", "0.8").returncode == 3  # nadal konflikt

    repo.write("app.txt", "main + poprawka\n", merge_dir)
    repo.git("add", "app.txt", cwd=merge_dir)
    repo.git("commit", "-q", "--no-edit", cwd=merge_dir)
    result = repo.run("./merge-forward.sh", "0.8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert repo.show("main", "app.txt") == "main + poprawka\n"
    # main nie jest nigdzie wybrany (główny katalog na release/0.8).
    assert repo.git("rev-parse", "--abbrev-ref", "HEAD") == "release/0.8"


def test_dirty_main_checkout_blocks_the_merge(repo) -> None:
    repo.git("checkout", "-q", "release/0.8")
    repo.write("fix.txt", "x\n")
    repo.commit("fix: something")
    repo.git("checkout", "-q", "main")
    repo.write("app.txt", "niezacommitowane\n")
    result = repo.run("./merge-forward.sh", "0.8")
    assert result.returncode == 4
    assert repo.show("main", "fix.txt") is None


def test_integrate_refuses_unknown_targets(repo, tmp_path) -> None:
    worktree = _agent_fix(repo, tmp_path, "fix-c")
    assert repo.run("./integrate.sh", "develop", cwd=worktree).returncode == 1
    assert repo.run("./integrate.sh", "release/0.9", cwd=worktree).returncode == 1
