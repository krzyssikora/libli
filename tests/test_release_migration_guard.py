"""scripts/release/migration_guard.sh -- D3's guard (spec §5).

Executed against real git history: the guard's whole job is to read ancestry
and diffs, which a stub cannot fake honestly.
"""

import subprocess

import pytest

from tests.release_harness import BASH
from tests.release_harness import COMPOSE_TMPL
from tests.release_harness import ROOT
from tests.release_harness import commit_all
from tests.release_harness import git
from tests.release_harness import init_repo
from tests.release_harness import write

GUARD = ROOT / "scripts/release/migration_guard.sh"

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


def _guard(repo, current, target):
    return subprocess.run(  # noqa: S603 -- fixed argv
        [BASH, str(GUARD), current, target], cwd=repo, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    r = init_repo(tmp_path / "r")
    write(r / "docker-compose.prod.yml", COMPOSE_TMPL.format(pg="16"))
    write(r / "uv.lock", "lock-1\n")
    write(r / "courses/migrations/0001_initial.py", "# 1\n")
    return r


def test_same_version_passes(repo):
    a = commit_all(repo, "a")
    assert _guard(repo, a, a).returncode == 0


def test_same_version_passes_even_with_an_unparseable_postgres_line(repo):
    """The same-version pass precedes the postgres rule: re-deploying the
    version a box is on is the failure table's recovery path.

    Mutant: move the `current = target` check below the postgres check.
    """
    write(
        repo / "docker-compose.prod.yml",
        "services:\n  db:\n    image: postgres@sha256:abc\n",
    )
    a = commit_all(repo, "a")
    result = _guard(repo, a, a)
    assert result.returncode == 0, result.stderr


def test_upgrade_passes_even_across_a_migration(repo):
    a = commit_all(repo, "a")
    write(repo / "courses/migrations/0002_more.py", "# 2\n")
    b = commit_all(repo, "b")
    assert _guard(repo, a, b).returncode == 0


def test_downgrade_with_no_migration_between_passes(repo):
    a = commit_all(repo, "a")
    write(repo / "README", "x\n")
    b = commit_all(repo, "b")
    assert _guard(repo, b, a).returncode == 0


def test_downgrade_across_a_migration_is_refused_and_names_it(repo):
    """Mutant: drop the migrations pathspec from the diff."""
    a = commit_all(repo, "a")
    write(repo / "courses/migrations/0002_more.py", "# 2\n")
    b = commit_all(repo, "b")
    result = _guard(repo, b, a)
    assert result.returncode != 0
    assert "courses/migrations/0002_more.py" in result.stderr
    assert "docs/backup-and-restore.md" in result.stderr


def test_downgrade_across_a_uv_lock_only_change_is_refused(repo):
    """Contrib/allauth migrations live in the venv, so a lockfile bump can
    migrate the schema with no repo migration changing.

    Mutant: drop `uv.lock` from the pathspec.
    """
    a = commit_all(repo, "a")
    write(repo / "uv.lock", "lock-2\n")
    b = commit_all(repo, "b")
    result = _guard(repo, b, a)
    assert result.returncode != 0
    assert "uv.lock" in result.stderr


@pytest.mark.parametrize("direction", ["downgrade", "upgrade"])
def test_postgres_major_change_is_refused_both_ways(repo, direction):
    """Mutant: only check the postgres line on a downgrade."""
    a = commit_all(repo, "a")
    write(repo / "docker-compose.prod.yml", COMPOSE_TMPL.format(pg="17"))
    b = commit_all(repo, "b")
    current, target = (b, a) if direction == "downgrade" else (a, b)
    result = _guard(repo, current, target)
    assert result.returncode != 0
    assert "postgres major changes" in result.stderr


def test_a_minor_postgres_tag_change_is_not_a_major_change(repo):
    a = commit_all(repo, "a")
    write(repo / "docker-compose.prod.yml", COMPOSE_TMPL.format(pg="16-alpine"))
    b = commit_all(repo, "b")
    assert _guard(repo, b, a).returncode == 0


def test_a_non_postgres_compose_change_is_not_refused(repo):
    a = commit_all(repo, "a")
    write(
        repo / "docker-compose.prod.yml",
        COMPOSE_TMPL.format(pg="16") + "  caddy:\n    image: caddy:2\n",
    )
    b = commit_all(repo, "b")
    assert _guard(repo, b, a).returncode == 0


def test_the_database_url_line_is_not_mistaken_for_the_image(repo):
    """COMPOSE_TMPL carries `DATABASE_URL: postgres://...`. A bare `postgres:`
    match would see two lines and refuse every deploy.

    Mutant: match `postgres:` instead of `^\\s*image:\\s*postgres:`.
    """
    a = commit_all(repo, "a")
    write(repo / "README", "x\n")
    b = commit_all(repo, "b")
    assert _guard(repo, b, a).returncode == 0


def test_a_missing_postgres_image_line_refuses(repo):
    a = commit_all(repo, "a")
    write(repo / "docker-compose.prod.yml", "services: {}\n")
    b = commit_all(repo, "b")
    result = _guard(repo, b, a)
    assert result.returncode != 0
    assert "cannot read the postgres image line" in result.stderr


def test_diverged_history_is_refused(repo):
    """Mutant: treat "target is not an ancestor of current" as an upgrade."""
    a = commit_all(repo, "a")
    git(repo, "checkout", "-q", "-b", "side")
    write(repo / "courses/migrations/0002_side.py", "# side\n")
    side = commit_all(repo, "side")
    git(repo, "checkout", "-q", "master")
    write(repo / "README", "x\n")
    b = commit_all(repo, "b")
    assert a != b
    result = _guard(repo, side, b)
    assert result.returncode != 0
    assert "diverged" in result.stderr


def test_unknown_current_commit_is_refused_with_its_own_message(repo):
    """Mutant: run the postgres rule before the existence check -- the
    refusal then reads as a postgres-line problem."""
    a = commit_all(repo, "a")
    result = _guard(repo, "f" * 40, a)
    assert result.returncode != 0
    assert "current commit unknown" in result.stderr


def test_the_guard_contract_is_frozen():
    """Spec §3: future deploy.sh versions run old copies of this file and vice
    versa, so it sources nothing, needs no jq, and takes exactly two args."""
    text = GUARD.read_text(encoding="utf-8")
    body = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not any(ln.lstrip().startswith(("source ", ". ")) for ln in body)
    assert "jq" not in "\n".join(body)
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [BASH, str(GUARD), "only-one"], capture_output=True, text=True
    )
    assert result.returncode != 0
