# B2 Release Deploys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release tags cut only from commits libli.pl deployed green, deployed by hand to one school box or all of them, with rollback refused across a migration — while libli.pl's canary deploy keeps working.

**Architecture:** Box-side logic stays in bash (`deploy.sh`, plus three new scripts sent over `ssh` on stdin: `migration_guard.sh`, `preflight.sh`, `remote_deploy.sh`). Runner-side logic that parses JSON or calls the GitHub API is stdlib Python under `scripts/release/` (`canary_guard.py`, `release_checks.py`, `inventory.py`, `report.py`). Two new `workflow_dispatch` workflows (`cut-release.yml`, `deploy-release.yml`) only wire those scripts together; `deploy.yml` gains the D9 expected-sha export.

**Tech Stack:** bash 5, git, GNU coreutils (`setsid`, `tail --pid`), awk; Python 3 stdlib; GitHub Actions; pytest (via `uv run`).

**Spec:** `docs/superpowers/specs/2026-09-27-b2-release-deploys-design.md` — read it alongside this plan. Its owner-decisions table (D1–D9) is VERBATIM and binding; no task re-opens it.

## Global Constraints

- **Deviation from the spec, deliberate:** the spec names the runner-side JSON tools `inventory.sh` / `canary_guard.sh`. They are written in Python (`inventory.py`, `canary_guard.py`, plus `release_checks.py`, `report.py`) because the dev machine has no `jq`, and hand-parsing JSON in bash is exactly where masking and validation bugs hide. Box-side scripts stay bash — the box has no guarantee of Python. Everything else in the spec is unchanged.
- Box paths are literal: `APP_DIR=/opt/libli`, lock `/var/lock/libli-deploy.lock`, state dir `/var/lib/libli-deploy/`, log dir `/var/log/libli-deploy/`. Tests rewrite these strings in a copy of the script; the scripts carry **no** test hooks.
- Version regex everywhere: `^v[0-9]+\.[0-9]+\.[0-9]+$`. Commit sha: `^[0-9a-f]{40}$`. Persisted tag: `^sha-[0-9a-f]{40}$`.
- Frozen cross-version contracts (spec §2 step 6, §3): `migration_guard.sh <current-sha> <target-sha>` (exit 0 pass / non-zero refuse, reasons on stderr, sources nothing, no `jq`, file never removed); env names `LIBLI_DEPLOY_REF`, `LIBLI_DEPLOY_EXPECT_SHA`, `LIBLI_DEPLOY_SKIP_FETCH` never renamed.
- `deploy.sh`'s first non-comment line stays `set -euo pipefail`; `APP_DIR=/opt/libli` stays a top-level line; `compose()`, `env_value()`, `fetch_master()`, `sync_working_tree()` stay top-level functions (other test files extract them); every `$(name …)` it calls is a function it defines or one of `date dirname du echo git mktemp openssl sed wc` (`tests/test_backup_wiring.py::test_every_command_substitution_resolves`).
- Bash scripts are written with LF line endings (`.gitattributes` has `*.sh text eol=lf`). Test fixtures write files with `write_bytes`, never `write_text` (Windows would emit CRLF), set `core.autocrlf false` in every fixture repo they `init`, and CLONE with `git clone -c core.autocrlf=false` — this dev machine has `core.autocrlf=true` in its system and global git config, and a setting applied after the clone arrives too late.
- Refusal output from runner tools: one line `refuse: <reason>` on stderr, exit 1; when `GITHUB_STEP_SUMMARY` is set the same line is appended there. **No refusal ever prints a host, a domain, a school name or a line of `.env.production`.**
- Workflows: every job `if:` includes `github.ref == 'refs/heads/master'`; top-level `permissions: {}`; values reach `run:` through `env:`, never `${{ }}` inside `run:` (the one sanctioned exception is `deploy.yml`'s `script:` D9 export of `github.sha`, spec §4).
- Test mechanics (repo memory): start the test DB first — `docker compose -p libli-test -f docker-compose.test.yml up -d --wait` — every test needs it (autouse `db` fixture). Run tests as `uv run pytest <path>` (never pass `-q`; `addopts` already has it). Lint gates: `uv run ruff check .` AND `uv run ruff format --check .`.
- **Lint is part of every task, not the end.** `pyproject.toml` selects `E, F, I, UP, B, S` (ignores only S101), line length 88, isort `force-single-line = true`. The code in this plan is NOT pre-wrapped: before each task's commit run `uv run ruff check --fix <the task's files>` (splits multi-name imports into single lines — I001 is auto-fixable) and `uv run ruff format <the task's files>`, then fix what remains by hand — wrap long string literals and comments (E501); put `# noqa: S607 -- git on PATH` (or `-- ssh on PATH`) on any argv list whose first element is a bare program name, alongside the existing `# noqa: S603`, as `scripts/affected_tests.py` does. A task is not done until both `ruff check` and `ruff format --check` are clean on its files.
- Every guard test must be shown RED against the named mutant before it counts (repo practice). Revert a mutant **by hand** (re-edit), never with `git checkout` on the file — that destroys uncommitted work.
- Tests needing `setsid`/`tail --pid` (Task 6) are `skipif` when `setsid` is absent (Git Bash on Windows); CI (ubuntu) runs them. Say so in the task report if they were skipped locally.

## Review Focus

Inputs the spec implies but its test list does not pin; each has its test added to the owning task.

1. **A school box whose `.env.production` was saved with CRLF endings** — every line ends `\r`, so the channel reads as invalid and the tag as malformed. Expected: pre-flight refuses with a reason that says "CRLF", not a baffling "not exactly release" (Task 5).
2. **`version` typed with stray whitespace or a capital `V`** (`" v1.0.0"`, `"V1.0.0"`) — expected: refused with the format message (Task 8).
3. **IPv6 `host` in `SCHOOL_HOSTS`** (`2001:db8::10`) — expected: accepted; the `known_hosts` line is `2001:db8::10 <key>` (Task 9).
4. **`SCHOOL_HOSTS` with one entry and `school=all`, or entries in non-sorted order** — expected: a matrix of exactly the keys, sorted, so the summary table is stable (Task 9).
5. **A tag message carrying `canary-run:` twice, or with trailing whitespace** — expected: trailing whitespace tolerated; two `canary-run:` lines refused as ambiguous (Task 8).

## File Structure

| File | Responsibility |
|---|---|
| `scripts/release/migration_guard.sh` (new) | D3 guard: same-version pass, commit existence, postgres major, ancestry + migrations/`uv.lock` diff. Frozen interface. |
| `deploy.sh` (modify) | `main "$@"; exit` wrapper; channel + tag read rules; EXIT-trap restore; ref path; embedded two-copy guard; D9 on the master path; tag persisted just before `up`. |
| `.github/workflows/deploy.yml` (modify) | D9: inline `export LIBLI_DEPLOY_EXPECT_SHA` + fail-closed check. |
| `scripts/release/preflight.sh` (new) | On-box read of `.env.production` (two read rules), forced tag fetch, sha match; `--read-only` mode. |
| `scripts/release/remote_deploy.sh` (new) | On-box detached bootstrap: extract target `deploy.sh`, `setsid nohup` wrapper, pid/status files, `tail --pid`. |
| `scripts/release/_release_common.py` (new) | `Refuse`, `refuse_and_exit`, `git()` helpers for the Python tools. |
| `scripts/release/canary_guard.py` (new) | D2 guard via `gh api` (listing and by-id paths). |
| `scripts/release/release_checks.py` (new) | `resolve` (cut), `tag` (annotated tag → target sha + run id), `containment` (B2). |
| `scripts/release/inventory.py` (new) | `SCHOOL_HOSTS` validation, `plan` (codes + masks), `entry` (masks + known_hosts/host files). |
| `scripts/release/report.py` (new) | Per-leg outcome JSON; run summary table + success/fail verdict. |
| `scripts/release/ssh_box.sh` (new) | The one `ssh` invocation with every pinned option. |
| `.github/workflows/cut-release.yml` (new) | Cut release button. |
| `.github/workflows/deploy-release.yml` (new) | Deploy release button: `plan` / matrix `deploy` / `report`. |
| `docs/deployment.md` (modify) | §8 edits, new §9 *Schools*, Known constraints. |
| `tests/release_harness.py` (new) | Fixture git repos (origin + box clone), deploy.sh runner with stubbed docker/curl/flock. |
| `tests/release_fixtures.py` (new) | Shared channel / `LIBLI_IMAGE_TAG` read-rule fixtures (deploy.sh and preflight.sh must agree). |
| `tests/test_release_migration_guard.py`, `tests/test_deploy_libli_path.py`, `tests/test_deploy_release_path.py`, `tests/test_release_preflight.py`, `tests/test_release_remote_deploy.py`, `tests/test_release_canary_guard.py`, `tests/test_release_checks.py`, `tests/test_release_inventory.py`, `tests/test_release_report.py`, `tests/test_release_workflows.py`, `tests/test_release_runbook.py` (new) | One test file per unit. |
| `tests/test_deploy_wiring.py` (modify) | Existing guards adapted to the new `deploy.sh` shape and the D9 line. |

---

### Task 1: Migration guard

**Files:**
- Create: `scripts/release/migration_guard.sh`
- Create: `tests/release_harness.py` (repo helpers only; Task 2 extends it)
- Test: `tests/test_release_migration_guard.py`

**Interfaces:**
- Produces: `bash scripts/release/migration_guard.sh <current-sha> <target-sha>` run with cwd inside a clone holding both commits. Exit 0 = pass; exit 1 = refuse with `migration guard: refuse: …` on stderr. Refusal texts the tests pin: `current commit unknown`, `target commit unknown`, `postgres major changes`, `cannot read the postgres image line`, `diverged`, and for a migration downgrade a list of files plus `docs/backup-and-restore.md`.
- Produces (harness): `tests.release_harness` with `ROOT`, `BASH`, `posix(path)`, `write(path, text)`, `git(cwd, *args) -> str`, `init_repo(path) -> Path`, `COMPOSE_TMPL` (format key `pg`), `commit_all(repo, msg) -> sha`.

- [ ] **Step 1: Write the harness helpers**

Create `tests/release_harness.py`:

```python
"""Shared fixtures for the B2 release-deploy tests.

Real git everywhere: history, tags and ancestry ARE what these scripts judge,
so a stubbed git would test nothing. Files are written with write_bytes so a
Windows checkout cannot smuggle CRLF into a bash script, and every fixture repo
sets core.autocrlf=false for the same reason.
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")

COMPOSE_TMPL = (
    "services:\n"
    "  db:\n"
    "    image: postgres:{pg}\n"
    "  app:\n"
    "    image: ghcr.io/krzyssikora/libli:${{LIBLI_IMAGE_TAG:?}}\n"
    "    environment:\n"
    "      DATABASE_URL: postgres://u:p@db:5432/libli\n"
)


def posix(path):
    return str(path).replace("\\", "/")


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def git(cwd, *args):
    result = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", *args],  # noqa: S607 -- git on PATH
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def init_repo(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "master")
    for key, value in (
        ("user.name", "test"),
        ("user.email", "test@example.com"),
        ("core.autocrlf", "false"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        git(path, "config", key, value)
    return path


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_release_migration_guard.py`:

```python
"""scripts/release/migration_guard.sh -- D3's guard (spec §5).

Executed against real git history: the guard's whole job is to read ancestry
and diffs, which a stub cannot fake honestly.
"""

import subprocess

import pytest

from tests.release_harness import (
    BASH,
    COMPOSE_TMPL,
    ROOT,
    commit_all,
    git,
    init_repo,
    write,
)

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
    write(repo / "docker-compose.prod.yml", "services:\n  db:\n    image: postgres@sha256:abc\n")
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_release_migration_guard.py`
Expected: FAIL — every test errors because `scripts/release/migration_guard.sh` does not exist.

- [ ] **Step 4: Write the guard**

Create `scripts/release/migration_guard.sh`:

```bash
#!/usr/bin/env bash
# Migration guard for release deploys (B2; spec §5 of
# docs/superpowers/specs/2026-09-27-b2-release-deploys-design.md).
#
#   migration_guard.sh <current-sha> <target-sha>
#   exit 0 = pass, non-zero = refuse; reasons on stderr.
#   Run with the current directory inside a clone that holds both commits.
#
# FROZEN CROSS-VERSION CONTRACT. deploy.sh runs the copy of this file found at
# OLD release tags, and old deploy.sh versions run the copy at newer ones. So:
# never change the arguments or the exit-code meaning, never source another
# file, never need anything beyond bash, git and coreutils (no jq), and never
# delete this file. Add checks; for anything else, add a new script name.
set -euo pipefail

refuse() {
  echo "migration guard: refuse: $*" >&2
  exit 1
}

[ "$#" -eq 2 ] || refuse "usage: migration_guard.sh <current-sha> <target-sha>"
current=$1
target=$2

# 1. A re-deploy of the version the box is on always passes. It is the failure
#    table's recovery path, so no later rule may block it.
if [ "$current" = "$target" ]; then
  echo "migration guard: same version, pass" >&2
  exit 0
fi

# 2. Both commits must exist here, before anything reads them.
git cat-file -e "$current^{commit}" 2>/dev/null || refuse "current commit unknown: $current"
git cat-file -e "$target^{commit}" 2>/dev/null || refuse "target commit unknown: $target"

# 3. Postgres major, in BOTH directions. The pgdata volume is initialised by one
#    major and refused by any other, so either direction takes the site down
#    after `up`. Anchored on `image: postgres:` -- a bare `postgres:` also
#    matches DATABASE_URL. Exactly one such line, with leading digits, or refuse.
pg_major() {
  git show "$1:docker-compose.prod.yml" 2>/dev/null | awk '
    /^[[:space:]]*image:[[:space:]]*postgres:/ {
      n++
      tag = $0
      sub(/^[[:space:]]*image:[[:space:]]*postgres:/, "", tag)
      sub(/[[:space:]].*$/, "", tag)
      sub(/\r$/, "", tag)
      if (match(tag, /^[0-9]+/)) major = substr(tag, 1, RLENGTH); else major = ""
    }
    END { if (n == 1 && major != "") print major }'
}
cur_pg="$(pg_major "$current")" || cur_pg=""
tgt_pg="$(pg_major "$target")" || tgt_pg=""
[ -n "$cur_pg" ] || refuse "cannot read the postgres image line at $current (docker-compose.prod.yml)"
[ -n "$tgt_pg" ] || refuse "cannot read the postgres image line at $target (docker-compose.prod.yml)"
[ "$cur_pg" = "$tgt_pg" ] \
  || refuse "postgres major changes ($cur_pg -> $tgt_pg); that is a manual dump-and-restore procedure, not a release deploy"

# 4. Ancestry. An upgrade is only an upgrade when current is an ancestor of
#    target -- "not a downgrade" is not the same thing.
if git merge-base --is-ancestor "$current" "$target"; then
  echo "migration guard: upgrade, pass" >&2
  exit 0
fi
if ! git merge-base --is-ancestor "$target" "$current"; then
  refuse "the two versions have diverged ($current vs $target); the box may hold migrations the target lacks"
fi

# A downgrade. uv.lock is in the list because Django contrib and allauth
# migrations live in the venv: a dependency bump can migrate the schema with no
# repo migration changing. Conservative on purpose (D3).
changed="$(git diff --name-only "$target" "$current" -- '*/migrations/*.py' uv.lock)"
if [ -n "$changed" ]; then
  {
    echo "migration guard: refuse: rolling back from $current to $target crosses:"
    printf '  %s\n' $changed
    echo "  Restore from a backup taken before the newer version instead: docs/backup-and-restore.md"
  } >&2
  exit 1
fi
echo "migration guard: downgrade with no migration between, pass" >&2
exit 0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_release_migration_guard.py`
Expected: all PASS.

- [ ] **Step 6: Falsify**

Apply each mutant named in a docstring, one at a time, by hand-editing `migration_guard.sh`; run the file; confirm the named test goes RED; revert by hand-editing back. Record each mutant → failing test in the task report.

- [ ] **Step 7: Commit**

```bash
git add scripts/release/migration_guard.sh tests/release_harness.py tests/test_release_migration_guard.py
git commit -m "feat(release): migration guard for school rollbacks (B2 §5)"
```

---

### Task 2: deploy.sh rework — the libli.pl path

Rewrites `deploy.sh` in full (both paths), but this task's tests pin the **libli.pl path** (no channel line). Task 3 pins the release path against the same file.

**Files:**
- Modify: `deploy.sh` (full rewrite below)
- Modify: `tests/release_harness.py` (append the box fixture + runner)
- Modify: `tests/test_deploy_wiring.py` (extract `git_fetch_retry` too; loosen the `compose up` regex)
- Test: `tests/test_deploy_libli_path.py`

**Interfaces:**
- Consumes: `scripts/release/migration_guard.sh` (Task 1) — called by `deploy.sh` on a release-channel box.
- Produces (deploy.sh top-level functions, relied on by Tasks 3 and 5): `channel_state <file>` → prints `absent` | `release` | `invalid`; `image_tag_read <file>` → prints `absent` | `invalid` | `value <text>`; `image_tag_state <file>` → prints `absent` | `invalid` | `sha-<40 hex>`; `git_fetch_retry <fetch args…>`; `fetch_master`; `sync_working_tree`; `run_migration_guards <current> <target>`; `on_exit`; `main`.
- Produces (harness): `Box(tmp)` with `.work`, `.origin`, `.app`, `.log`; `box.commit(**kw) -> sha`; `box.tag(name, sha, run_id="1")`; `box.clone(sha, *, detached, image_tag, channel_line=None, extra_env="")`; `box.bootstrap_to(sha)` (simulates deploy.yml's fetch+reset); `run_deploy(box, env=None) -> CompletedProcess`; `calls(box) -> str`; `env_at_up(box) -> str`; `head(box) -> str`; `on_branch(box) -> bool`.

- [ ] **Step 1: Extend the harness**

Append to `tests/release_harness.py`:

```python
# ---- the box: an origin, a working repo that authors commits, and the clone
# at <tmp>/app that deploy.sh runs in. deploy.sh is committed with its box
# paths rewritten to the fixture -- the shipped script carries no test hooks.


# deploy.sh only needs the GHCR token to be non-empty.
TOKEN_LINE = "LIBLI_GHCR_TOKEN=" + "x" * 8


def deploy_sh_for(app, lock, source=None):
    text = source if source is not None else (ROOT / "deploy.sh").read_text(encoding="utf-8")
    assert "APP_DIR=/opt/libli" in text and "/var/lock/libli-deploy.lock" in text
    return text.replace("APP_DIR=/opt/libli", f"APP_DIR={posix(app)}").replace(
        "/var/lock/libli-deploy.lock", posix(lock)
    )


class Box:
    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.work = init_repo(self.tmp / "work")
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "master", posix(self.origin))
        git(self.work, "remote", "add", "origin", posix(self.origin))
        self.app = self.tmp / "app"
        self.log = self.tmp / "calls"
        write(self.log, "")

    def commit(self, *, pg="16", migrations=(), extra=None, deploy_sh=None, guard=None, msg="c"):
        """One release-shaped commit, pushed to origin/master."""
        write(self.work / "deploy.sh", deploy_sh_for(self.app, self.tmp / "deploy.lock", deploy_sh))
        write(self.work / "docker-compose.prod.yml", COMPOSE_TMPL.format(pg=pg))
        write(self.work / "Caddyfile", "{$SITE_ADDRESS} {\n}\n")
        write(self.work / "uv.lock", "lock\n")
        guard_text = guard if guard is not None else (
            ROOT / "scripts/release/migration_guard.sh"
        ).read_text(encoding="utf-8")
        write(self.work / "scripts/release/migration_guard.sh", guard_text)
        for name in migrations:
            write(self.work / f"courses/migrations/{name}.py", f"# {name}\n")
        for rel, text in (extra or {}).items():
            write(self.work / rel, text)
        sha = commit_all(self.work, msg)
        git(self.work, "push", "-q", "origin", "master")
        return sha

    def tag(self, name, sha, run_id="1", force=False):
        git(self.work, "tag", *(["-f"] if force else []), "-a", name, sha,
            "-m", f"Release {name}", "-m", f"canary-run: {run_id}")
        git(self.work, "push", "-q", *(["-f"] if force else []), "origin", f"refs/tags/{name}")

    def clone(self, sha, *, detached, image_tag, channel_line=None, extra_env=""):
        """The box as provisioned: a clone at `sha` plus .env.production.
        image_tag=None writes no LIBLI_IMAGE_TAG line at all."""
        # `clone -c` writes the setting into the new repo BEFORE the initial
        # checkout. Setting it afterwards is too late: on a machine with
        # core.autocrlf=true in the system/global config, the clone would
        # already have written deploy.sh with CRLF, and a later checkout never
        # rewrites a stat-clean, byte-identical file.
        git(self.tmp, "clone", "-q", "-c", "core.autocrlf=false",
            posix(self.origin), posix(self.app))
        assert b"\r" not in (self.app / "deploy.sh").read_bytes(), "fixture clone got CRLF"
        if detached:
            git(self.app, "checkout", "-q", "--detach", sha)
        else:
            git(self.app, "reset", "-q", "--hard", sha)
        lines = [
            # Built at runtime and neutrally named below: GitGuardian scans this
            # repo and has failed a PR over a secret-SHAPED literal before.
            TOKEN_LINE,
            "SITE_ADDRESS=school.example",
            "DJANGO_SITE_DOMAIN=school.example",
            "SENTINEL_LINE=SENTINEL-LINE-0f9e",
        ]
        if image_tag is not None:
            lines.append(f"LIBLI_IMAGE_TAG={image_tag}")
        if channel_line is not None:
            lines.append(channel_line)
        write(self.app / ".env.production", "\n".join(lines) + "\n" + extra_env)

    def bootstrap_to(self, sha):
        """What deploy.yml's own script does before invoking deploy.sh."""
        git(self.app, "fetch", "-q", "origin", "master")
        git(self.app, "reset", "-q", "--hard", sha)


def _prelude(log):
    """docker, curl, flock and sleep as EXPORTED bash functions: a function
    shadows a PATH lookup on every platform, and `export -f` carries it into
    the `bash deploy.sh` child. FAIL_AT=pull|up|hup makes that step fail
    (hup: SIGHUP to the deploy shell itself, as a terminal hang-up would)."""
    log = posix(log)
    return f"""
docker() {{
  echo "docker $*" >> "{log}"
  case "$*" in
    *" pull"*)
      echo "pull-tag=${{LIBLI_IMAGE_TAG:-<unset>}}" >> "{log}"
      [ "${{FAIL_AT:-}}" = pull ] && return 1
      [ "${{FAIL_AT:-}}" = hup ] && kill -HUP $$
      ;;
    *" up "*)
      cp .env.production "{log}.env-at-up"
      echo "up-shell-tag=${{LIBLI_IMAGE_TAG:-<unset>}}" >> "{log}"
      [ "${{FAIL_AT:-}}" = up ] && return 1
      ;;
    login*) cat > /dev/null ;;
    run*)
      # REWRITE_TARGET/REWRITE_WITH: overwrite the running deploy.sh IN PLACE
      # (same inode), mid-run -- see test_an_in_place_rewrite_of_the_running_script_changes_nothing.
      if [ -n "${{REWRITE_TARGET:-}}" ]; then cat "$REWRITE_WITH" > "$REWRITE_TARGET"; fi
      ;;
  esac
  return 0
}}
curl() {{ echo "curl $*" >> "{log}"; echo '{{"status": "ok"}}'; }}
flock() {{ echo "flock $*" >> "{log}"; }}
sleep() {{ :; }}
# FAIL_FETCHES=N: the first N `git fetch` calls exit 128 (the anonymous-401
# flake); everything else is the real git. The count lands in <log>.fetches.
git() {{
  if [ "$1" = fetch ] && [ -n "${{FAIL_FETCHES:-}}" ]; then
    local n
    n=$(( $(cat "{log}.fetches" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "{log}.fetches"
    if [ "$n" -le "$FAIL_FETCHES" ]; then return 128; fi
  fi
  command git "$@"
}}
export -f docker curl flock sleep git
"""


def run_deploy(box, env=None, script=None):
    """Run the box's deploy.sh (or `script`) the way a host would: `bash <file>`."""
    import os

    clean = {k: v for k, v in os.environ.items() if not k.startswith("LIBLI_")}
    clean.pop("FAIL_AT", None)
    clean.update(env or {})
    target = posix(script or box.app / "deploy.sh")
    return subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [BASH, "-c", _prelude(box.log) + f'\nbash "{target}"'],
        capture_output=True,
        text=True,
        env=clean,
        timeout=120,
        # Never inherit a terminal: git for Windows prompts on stdin when it
        # cannot unlink an open file, which would hang the suite.
        stdin=subprocess.DEVNULL,
    )


def calls(box):
    return box.log.read_text(encoding="utf-8")


def env_at_up(box):
    path = Path(f"{box.log}.env-at-up")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def head(box):
    return git(box.app, "rev-parse", "HEAD")


def on_branch(box):
    result = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", "symbolic-ref", "-q", "HEAD"],  # noqa: S607 -- git on PATH
        cwd=box.app,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
```

- [ ] **Step 2: Write the failing libli.pl-path tests**

Create `tests/test_deploy_libli_path.py`:

```python
"""deploy.sh on libli.pl (no LIBLI_DEPLOY_CHANNEL line): the canary path.

Goal 6 of the spec: the trigger and target are unchanged; three deliberate
behaviour changes (D9 superseded refusal, LIBLI_IMAGE_TAG persisted just before
`up`, restore on a pre-`up` failure) and three no-op additions.
"""

import pytest

from tests.release_harness import (
    BASH,
    TOKEN_LINE,
    Box,
    calls,
    env_at_up,
    head,
    on_branch,
    run_deploy,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


@pytest.fixture
def libli(tmp_path):
    """P deployed and persisted; X and Y merged after it. HEAD on master at P."""
    box = Box(tmp_path)
    p = box.commit(msg="P")
    x = box.commit(extra={"README": "x\n"}, msg="X")
    y = box.commit(extra={"README": "y\n"}, msg="Y")
    box.clone(p, detached=False, image_tag=f"sha-{p}")
    return box, p, x, y


def test_an_ordinary_run_deploys_master_and_persists_the_tag_just_before_up(libli):
    """Mutant: persist LIBLI_IMAGE_TAG after `compose up` instead of before."""
    box, p, x, y = libli
    result = run_deploy(box)
    assert result.returncode == 0, result.stderr
    assert head(box) == y and on_branch(box)
    assert f"pull-tag=sha-{y}" in calls(box)
    assert f"LIBLI_IMAGE_TAG=sha-{y}" in env_at_up(box)


def test_a_pull_failure_restores_the_checkout_and_keeps_the_tag(libli):
    """The bootstrap already moved HEAD to Y; the old image still runs, so a
    backup must not see HEAD=Y. Branch form: reset --hard on master.

    Mutant: drop the EXIT trap (or key it on ERR, which misses compose()).
    """
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(box, env={"FAIL_AT": "pull", "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert head(box) == p and on_branch(box)
    assert f"LIBLI_IMAGE_TAG=sha-{p}" in (box.app / ".env.production").read_text()


def test_a_missing_ghcr_token_restores_the_checkout(libli):
    """The token check leaves through an explicit `exit 1`, which an ERR trap
    never sees. Mutant: ERR trap instead of EXIT."""
    box, p, x, y = libli
    env = (box.app / ".env.production").read_text().replace(TOKEN_LINE + "\n", "")
    (box.app / ".env.production").write_bytes(env.encode())
    box.bootstrap_to(y)
    result = run_deploy(box, env={"LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert head(box) == p
    assert f"LIBLI_IMAGE_TAG=sha-{p}" in (box.app / ".env.production").read_text()


def test_a_failure_of_up_does_not_restore(libli):
    """After `up` starts, the new image's migrate may have run: HEAD and the tag
    must both name the new version.

    Mutant: a trap that ignores reached_up and always restores.
    """
    box, p, x, y = libli
    result = run_deploy(box, env={"FAIL_AT": "up"})
    assert result.returncode != 0
    assert head(box) == y
    assert f"LIBLI_IMAGE_TAG=sha-{y}" in (box.app / ".env.production").read_text()


def test_a_hangup_before_up_restores(libli):
    """Mutant: drop the HUP trap."""
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(box, env={"FAIL_AT": "hup", "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert head(box) == p


def test_an_exported_bogus_tag_never_reaches_up(libli):
    """Mutant: drop `unset LIBLI_IMAGE_TAG`."""
    box, p, x, y = libli
    result = run_deploy(box, env={"LIBLI_IMAGE_TAG": "sha-bogus"})
    assert result.returncode == 0, result.stderr
    assert "up-shell-tag=<unset>" in calls(box)


def test_d9_a_superseded_run_refuses_and_the_trap_restores(libli):
    """The run was for X, but master moved to Y and the bootstrap reset to Y.
    LIBLI_DEPLOY_SKIP_FETCH=1 is what deploy.yml always passes.

    Mutants: skip the check on the unset-ref path; put it inside the fetch branch.
    """
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(
        box, env={"LIBLI_DEPLOY_EXPECT_SHA": x, "LIBLI_DEPLOY_SKIP_FETCH": "1"}
    )
    assert result.returncode != 0
    assert f"superseded by {y}" in result.stderr
    assert "docker " not in calls(box)
    assert head(box) == p
    assert f"LIBLI_IMAGE_TAG=sha-{p}" in (box.app / ".env.production").read_text()


def test_d9_a_current_run_proceeds_exactly_as_today(libli):
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(
        box, env={"LIBLI_DEPLOY_EXPECT_SHA": y, "LIBLI_DEPLOY_SKIP_FETCH": "1"}
    )
    assert result.returncode == 0, result.stderr
    assert head(box) == y


def test_an_absent_tag_proceeds_with_no_restore_target(tmp_path):
    box = Box(tmp_path)
    p = box.commit(msg="P")
    y = box.commit(extra={"README": "y\n"}, msg="Y")
    box.clone(p, detached=False, image_tag=None)
    box.bootstrap_to(y)
    result = run_deploy(box, env={"FAIL_AT": "pull", "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert "no restore target" in result.stderr
    assert head(box) == y


def test_a_malformed_tag_warns_and_proceeds(tmp_path):
    box = Box(tmp_path)
    p = box.commit(msg="P")
    box.clone(p, detached=False, image_tag="sha-short")
    result = run_deploy(box)
    assert result.returncode == 0, result.stderr
    assert "LIBLI_IMAGE_TAG unreadable" in result.stderr


def test_a_successful_run_prints_nothing_from_the_exit_trap(libli):
    """Goal 6: the trap, the unset and the signal traps are no-ops on success."""
    box, p, x, y = libli
    result = run_deploy(box)
    assert result.returncode == 0
    assert "restor" not in result.stderr.lower()
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_deploy_libli_path.py`
Expected: FAIL — e.g. `test_a_pull_failure_restores_the_checkout_and_keeps_the_tag` (today's deploy.sh writes the tag before the pull and never restores), `test_d9_…` (no expected-sha check).

- [ ] **Step 4: Rewrite deploy.sh**

Replace the whole of `deploy.sh` with the following, **as written** — where it differs from today's comments (a few sentences are shortened or dropped), the text below wins.

```bash
#!/usr/bin/env bash
# CI-invoked deploy script for libli.
#
# Lives in the repo rather than being generated on the host, so every change to
# it goes through the normal PR/CI/review path. Two callers:
#   - .github/workflows/deploy.yml on libli.pl, via appleboy/ssh-action:
#       bash /opt/libli/deploy.sh
#   - scripts/release/remote_deploy.sh on a school box (B2), which runs a TEMP
#     COPY of the deploy.sh at the target release tag.
#
# deploy.yml resets the checkout BEFORE invoking this file, so the copy bash
# parses is always the one the current commit ships -- a change here takes
# effect on the deploy that introduces it, not the one after. That ordering is
# also what bootstraps a host whose checkout predates this script existing.
# It is a real dependency, not a tidy-up candidate: see deploy.yml's comment.
#
# The reset below is therefore redundant under CI and load-bearing by hand --
# a by-hand `bash deploy.sh` on the box must still be correct on its own. (The
# §8 ROLLBACK is `LIBLI_DEPLOY_REF=<sha> bash deploy.sh`, the ref path; plain
# `bash deploy.sh` resets to master.)
#
# B2 inputs -- a FROZEN CROSS-VERSION CONTRACT: remote_deploy.sh comes from
# master while the deploy.sh it runs comes from an older release tag, so these
# names and meanings never change (spec §2 step 6):
#   LIBLI_DEPLOY_REF         a vX.Y.Z tag (any box) or a 40-hex sha (libli.pl only)
#   LIBLI_DEPLOY_EXPECT_SHA  the commit the caller verified; refuse on a mismatch
#   LIBLI_DEPLOY_SKIP_FETCH  the caller already fetched
#
# The whole body is main(), called on the LAST line as `main "$@"; exit`. bash
# reads a script file as it executes, and the ref path's checkout rewrites
# /opt/libli/deploy.sh under the running process; a function is parsed whole
# before it runs, and `exit` on the same line means nothing is read after it.
set -euo pipefail

APP_DIR=/opt/libli

# Retry budget for the fetches below. Overridable so the host can widen it
# without a code change; the defaults are what CI runs.
GIT_FETCH_ATTEMPTS=${GIT_FETCH_ATTEMPTS:-3}
GIT_FETCH_DELAY=${GIT_FETCH_DELAY:-5}

# Set by main(), read by on_exit.
REACHED_UP=0
RESTORE_SHA=""
RESTORE_NOTE=""

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}

# Reads one KEY=value out of .env.production. `sed -n s///p` rather than grep so
# a missing key yields an empty string instead of exit 1, which under `set -e`
# would abort the deploy over a value that is only used for verification.
env_value() {
  sed -n "s/^$1=//p" .env.production | head -1
}

# To stderr, ignoring write errors: on_exit uses it, and the trap must not die
# of a closed pipe while cleaning up after one.
say() {
  printf '%s\n' "$*" >&2 2>/dev/null || true
}

die() {
  say "!! $*"
  exit 1
}

# The channel read rule (spec §3). DUPLICATED in scripts/release/preflight.sh --
# deliberately not a shared sourced helper, because this file runs as a temp
# copy at the target version and would source the CURRENT checkout's copy.
# tests/release_fixtures.py feeds both the same cases.
# Prints absent | release | invalid. A commented line naming the key counts as
# present-but-invalid: otherwise a by-hand run would reset a school to master.
channel_state() {
  awk '
    /^[[:space:]]*#.*LIBLI_DEPLOY_CHANNEL/ { n++; bad = 1; next }
    /^[[:space:]]*(export[[:space:]]+)?LIBLI_DEPLOY_CHANNEL[[:space:]]*=/ {
      n++
      if ($0 != "LIBLI_DEPLOY_CHANNEL=release") bad = 1
    }
    END {
      if (n == 0) print "absent"
      else if (n == 1 && !bad) print "release"
      else print "invalid"
    }
  ' "$1"
}

# The LIBLI_IMAGE_TAG read rule (spec §5). DUPLICATED in preflight.sh (see above).
# image_tag_read prints absent | invalid | "value <text>": exactly one line
# matching ^LIBLI_IMAGE_TAG= and no export-prefixed or indented variant.
# image_tag_state adds the shape check and prints absent | invalid | sha-<40 hex>
# (a trailing CR, a short sha or sha-v1.0.0 are all invalid).
image_tag_read() {
  awk '
    /^[[:space:]]*(export[[:space:]]+)?LIBLI_IMAGE_TAG[[:space:]]*=/ {
      any++
      if (index($0, "LIBLI_IMAGE_TAG=") == 1) { anchored++; val = substr($0, 17) }
    }
    END {
      if (any == 0) print "absent"
      else if (any != 1 || anchored != 1) print "invalid"
      else print "value " val
    }
  ' "$1"
}

image_tag_state() {
  local read value
  read="$(image_tag_read "$1")"
  case "$read" in
    "value "*)
      value="${read#value }"
      if [[ $value =~ ^sha-[0-9a-f]{40}$ ]]; then echo "$value"; else echo invalid; fi
      ;;
    *) echo "$read" ;;
  esac
}

# GitHub intermittently answers an ANONYMOUS fetch of this PUBLIC repo with a 401
# challenge, and git then dies on "could not read Username" because a deploy has
# no tty to prompt at. It killed three deploys in two days (#293, #295, #296).
# It is NOT a credential problem: a public fetch needs none, and in #296 the
# fetch 440 ms earlier had SUCCEEDED. Retrying turns it into a slower deploy
# rather than a red one. Arguments are passed to `git fetch origin`.
git_fetch_retry() {
  local attempt=1
  while true; do
    if git fetch origin "$@"; then
      return 0
    fi
    if [ "$attempt" -ge "$GIT_FETCH_ATTEMPTS" ]; then
      echo "==> git fetch failed $GIT_FETCH_ATTEMPTS times; refusing to deploy" >&2
      return 1
    fi
    echo "==> git fetch failed (attempt $attempt/$GIT_FETCH_ATTEMPTS); retrying in ${GIT_FETCH_DELAY}s"
    attempt=$((attempt + 1))
    sleep "$GIT_FETCH_DELAY"
  done
}

fetch_master() {
  git_fetch_retry master
}

sync_working_tree() {
  # fetch + reset --hard, never `git pull`:
  #   - the host checkout is a mirror of master by definition. Any local
  #     divergence is wrong and should be flattened, not merged.
  #   - `git pull` aborts on divergent branches and depends on pull.rebase config
  #     that varies across git versions.
  # .env.production is untracked (.gitignore's `.env*`), so the reset cannot
  # destroy the host's only copy of the secrets.
  #
  # deploy.yml fetches and resets before invoking this file, so this fetch is a
  # SECOND request to github.com inside a second -- and that pair is what tripped
  # #296. CI sets LIBLI_DEPLOY_SKIP_FETCH to drop it. The RESET is never skipped.
  if [ -n "${LIBLI_DEPLOY_SKIP_FETCH:-}" ]; then
    echo "==> CI already fetched; resetting to the ref it fetched"
  else
    fetch_master
  fi
  # D9: a run deploys ONLY its own commit. deploy.yml resets to whatever master
  # is when its job starts, so without this a run for X (or a re-run of X after
  # Y merged) would deploy Y under X's name -- and the canary guard reads a
  # green `deploy` job as "libli.pl ran X". Runs whether or not this run
  # fetched: deploy.yml always passes LIBLI_DEPLOY_SKIP_FETCH=1.
  if [ -n "${LIBLI_DEPLOY_EXPECT_SHA:-}" ]; then
    local tip
    tip="$(git rev-parse origin/master)"
    if [ "$tip" != "$LIBLI_DEPLOY_EXPECT_SHA" ]; then
      echo "!! superseded by $tip; the newer run deploys it (this run was for $LIBLI_DEPLOY_EXPECT_SHA)" >&2
      return 1
    fi
  fi
  git checkout master 2>/dev/null || true
  git reset --hard origin/master
}

# The embedded D3 guard on a release-channel box: BOTH copies -- the current
# release's and the target's -- must pass. On a downgrade the target is older
# and lacks any check added since, so its copy alone would drop exactly the
# newest protections. Every tag carries the guard (B2 containment).
run_migration_guards() {
  local current=$1 target=$2 at copy
  for at in "$current" "$target"; do
    copy="$(mktemp)"
    if ! git show "$at:scripts/release/migration_guard.sh" > "$copy" 2>/dev/null; then
      rm -f "$copy"
      die "no scripts/release/migration_guard.sh at $at; refusing"
    fi
    if ! bash "$copy" "$current" "$target"; then
      rm -f "$copy"
      die "the migration guard (copy at $at) refused; see docs/backup-and-restore.md"
    fi
    rm -f "$copy"
  done
}

# Any exit before `up` puts the checkout back to the commit the running image
# was built from (the persisted LIBLI_IMAGE_TAG), so a nightly backup never
# records a git_sha that disagrees with its own image -- the mismatch
# restore.sh refuses. EXIT, not ERR: without `set -E` an ERR trap does not fire
# inside functions (the pull runs inside compose()), and never on `exit 1`.
# Only if HEAD actually moved: an early refusal must not force-checkout over a
# hand-edited tracked file. (Keep the literal pull command out of comments
# above main(): test_backup_wiring.py finds its FIRST occurrence and requires
# the docker login to come before it.)
on_exit() {
  local rc=$? restored=0 head
  set +e
  # printf is a builtin: a write to a closed pipe would SIGPIPE this shell
  # itself. Ignored, the write fails with EPIPE instead and say() swallows it,
  # so the trap still exits with the deploy's own status.
  trap '' PIPE
  if [ "$rc" -ne 0 ] && [ "$REACHED_UP" != 1 ]; then
    head="$(git rev-parse HEAD 2>/dev/null)"
    if [ -z "$RESTORE_SHA" ]; then
      say "==> deploy failed before up (${RESTORE_NOTE:-no restore target}); the checkout is left as it is"
    elif [ "$head" != "$RESTORE_SHA" ]; then
      if git symbolic-ref -q HEAD > /dev/null 2>&1; then
        git reset -q --hard "$RESTORE_SHA" > /dev/null 2>&1 && restored=1
      else
        git checkout -q --force --detach "$RESTORE_SHA" > /dev/null 2>&1 && restored=1
      fi
      if [ "$restored" = 1 ]; then
        say "==> deploy failed before up; checkout restored to $RESTORE_SHA (the image still running)"
      else
        say "!! deploy failed before up AND the checkout restore FAILED: HEAD is $head, the running image is sha-$RESTORE_SHA; fix by hand before the next backup"
      fi
    fi
  fi
  exit "$rc"
}

main() {
  # An exported LIBLI_IMAGE_TAG (left from a manual first boot, say) would beat
  # .env.production at `up` -- the same shell-over-env-file precedence the pull
  # below relies on. The pull gets it per command; nothing else sees it.
  unset LIBLI_IMAGE_TAG

  cd "$APP_DIR"

  # Shared with backup.sh and restore.sh. A merge landing mid-dump would recreate
  # the app container, restart postgres' dependents and prune images underneath it.
  # deploy.sh WAITS rather than skipping: a silently dropped deploy would report
  # green in Actions having done nothing.
  #
  # Taken before anything else, including the fetch: the point is to hold the lock
  # for the whole run, not merely for the part that touches containers.
  exec 9>/var/lock/libli-deploy.lock
  flock 9

  local channel tag_state ref kind="" target image_tag ghcr_token site_domain
  channel="$(channel_state .env.production)"
  tag_state="$(image_tag_state .env.production)"

  # Spec §5's outcome table. A present-but-invalid channel line takes the
  # release column; the channel catch below refuses it anyway.
  if [ "$tag_state" != absent ] && [ "$tag_state" != invalid ]; then
    RESTORE_SHA="${tag_state#sha-}"
  elif [ "$channel" = invalid ]; then
    # The channel line is the thing to fix first; say so rather than sending
    # the operator down the first-boot path.
    die "LIBLI_DEPLOY_CHANNEL is present in .env.production but not exactly 'release', and LIBLI_IMAGE_TAG is $tag_state; fix both (docs/deployment.md §9)"
  elif [ "$channel" != absent ]; then
    if [ "$tag_state" = absent ]; then
      die "LIBLI_IMAGE_TAG absent in .env.production; a school box is first-booted by hand (docs/deployment.md §9)"
    fi
    die "LIBLI_IMAGE_TAG unreadable in .env.production (need exactly one line LIBLI_IMAGE_TAG=sha-<40 hex>)"
  elif [ "$tag_state" = absent ]; then
    RESTORE_NOTE="no restore target"
  else
    say "!! warning: LIBLI_IMAGE_TAG unreadable; a failure before up cannot restore the checkout"
    RESTORE_NOTE="cannot restore: LIBLI_IMAGE_TAG unreadable"
  fi

  trap on_exit EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  # The channel catch. Without it, `bash deploy.sh` by hand on a school box --
  # the natural manual-rollback reflex -- would silently move it onto master.
  ref="${LIBLI_DEPLOY_REF:-}"
  case "$channel" in
    invalid)
      die "LIBLI_DEPLOY_CHANNEL is present in .env.production but not exactly 'release'; fix it (docs/deployment.md §9)"
      ;;
    release)
      [ -n "$ref" ] || die "this is a release-channel box: pass LIBLI_DEPLOY_REF=vX.Y.Z (or use Deploy release); refusing to reset a school to master"
      ;;
  esac

  if [ -n "$ref" ]; then
    if [[ $ref =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      kind=tag
    elif [ "$channel" = absent ] && [[ $ref =~ ^[0-9a-f]{40}$ ]]; then
      kind=sha
    elif [ "$channel" = release ]; then
      die "LIBLI_DEPLOY_REF must be a vX.Y.Z tag on a release-channel box"
    else
      die "LIBLI_DEPLOY_REF must be a vX.Y.Z tag or a full 40-hex sha"
    fi

    if [ -z "${LIBLI_DEPLOY_SKIP_FETCH:-}" ]; then
      if [ "$kind" = tag ]; then
        # Forced: a re-cut tag must replace a stale local one, and a bare
        # `git fetch origin <tag>` writes only FETCH_HEAD.
        git_fetch_retry "+refs/tags/$ref:refs/tags/$ref"
      else
        git_fetch_retry "$ref"
      fi
    fi
    target="$(git rev-parse --verify --quiet "$ref^{commit}")" || die "$ref does not resolve to a commit"
    if [ -n "${LIBLI_DEPLOY_EXPECT_SHA:-}" ] && [ "$target" != "$LIBLI_DEPLOY_EXPECT_SHA" ]; then
      die "$ref resolves to $target, not the verified $LIBLI_DEPLOY_EXPECT_SHA (re-cut tag?); refusing"
    fi
    if [ "$channel" = release ]; then
      run_migration_guards "$RESTORE_SHA" "$target"
    fi
    echo "==> checking out $ref ($target)"
    git checkout -q --force --detach "$target"
    git reset -q --hard "$target"
  else
    echo "==> resetting the working tree to origin/master"
    sync_working_tree
  fi

  echo "==> validating the Caddyfile"
  # caddy has no healthcheck in docker-compose.prod.yml, so a syntax error here
  # produces a crash loop that `docker compose ps` still reports as `running` --
  # and `--wait` below therefore cannot catch it. Validating BEFORE `up` means a
  # bad Caddyfile fails the deploy with the running site still intact.
  # The Caddyfile opens its site block with {$SITE_ADDRESS}, so that variable has
  # to be set for the parse to succeed; use the real one when it is readable.
  docker run --rm -v "$APP_DIR/Caddyfile:/etc/caddy/Caddyfile:ro" \
    -e SITE_ADDRESS="$(env_value SITE_ADDRESS)" \
    caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile

  image_tag="sha-$(git rev-parse HEAD)"

  echo "==> logging in to ghcr.io"
  # The package is private: it contains the application source of a private repo.
  # An unauthenticated pull fails with an opaque `denied`.
  #
  # Checked explicitly rather than letting an empty value reach docker login: a
  # blank password produces "unauthorized" and, under pipefail, aborts the deploy
  # with an error that reads like a registry outage rather than a missing key.
  ghcr_token="$(env_value LIBLI_GHCR_TOKEN)"
  if [ -z "$ghcr_token" ]; then
    echo "!! LIBLI_GHCR_TOKEN is unset in .env.production." >&2
    echo "   Add a read:packages PAT to it; see docs/deployment.md section 1." >&2
    exit 1
  fi
  printf '%s' "$ghcr_token" | docker login ghcr.io -u krzyssikora --password-stdin

  echo "==> pulling $image_tag"
  # The tag reaches compose from the shell for the pull only (compose
  # interpolation prefers the shell over --env-file). It is persisted below,
  # just before `up`, so LIBLI_IMAGE_TAG always names the newest code that may
  # have run against this database -- what the migration guard reads as
  # "current", and what backup.sh records as the manifest's image.
  LIBLI_IMAGE_TAG="$image_tag" compose pull

  echo "==> pinning the image tag"
  # Written INTO .env.production, not exported: backup.sh reads it hours later
  # under cron with env_value, the encrypted env in each artifact must carry the
  # tag matching its manifest, and compose guards the key with `:?` so any `up`
  # outside this script would abort without a persisted value.
  # Write, THEN set the flag, THEN up: a failed write with the flag unset is a
  # pre-up exit and restores; nothing that can fail sits between flag and up.
  if grep -q '^LIBLI_IMAGE_TAG=' .env.production; then
    sed -i "s|^LIBLI_IMAGE_TAG=.*|LIBLI_IMAGE_TAG=${image_tag}|" .env.production
  else
    printf 'LIBLI_IMAGE_TAG=%s\n' "$image_tag" >> .env.production
  fi
  REACHED_UP=1
  echo "==> recreating the stack"
  compose up -d --wait

  echo "==> verifying the site through caddy"
  # Through the public name, not 127.0.0.1: this is the only step that exercises
  # Caddy, TLS and the proxy hop, and it is what distinguishes "the container is
  # healthy" from "the site is up". --retry covers the seconds Caddy needs to
  # rebind after a recreate.
  site_domain="$(env_value DJANGO_SITE_DOMAIN)"
  curl -fsS --retry 5 --retry-delay 3 --retry-connrefused \
    "https://${site_domain}/healthz/" | grep -q '"status": *"ok"'

  echo "==> pruning dangling images"
  # Every pull leaves the previous image's layers dangling, and nothing else on
  # this host reclaims them. The runbook's 50 GB floor is sized for a ~17 GB
  # import peak, so unbounded image garbage eventually breaks an import rather
  # than the deploy that caused it. Dangling only -- never `-a`, which would also
  # delete the pulled postgres and caddy images while their containers are down.
  docker image prune -f

  echo "==> deploy complete"
}

main "$@"; exit
```

- [ ] **Step 5: Adapt the existing wiring tests**

In `tests/test_deploy_wiring.py`:

1. `test_deploy_script_waits_for_health`: change the regex `r"^compose up .*$"` to `r"^\s*compose up .*$"` (the call is now inside `main`).
2. Every test that builds a script from `_sh_function('fetch_master')` must also include `_sh_function('git_fetch_retry')` **before** it. In `test_deploy_script_retries_a_fetch_that_fails`, `test_deploy_script_gives_up_rather_than_retrying_forever`, `test_deploy_script_skips_its_own_fetch_when_ci_already_fetched` and `test_deploy_script_still_fetches_when_run_by_hand`, replace `{_sh_function('fetch_master')}` with `{_sh_function('git_fetch_retry')}\n{_sh_function('fetch_master')}`.
3. Update the mutant line in the first two docstrings: "Mutant: drop the loop in `git_fetch_retry` and call `git fetch origin` once."
4. In `test_deploy_script_still_fetches_when_run_by_hand`'s docstring, replace "The rollback path in docs/deployment.md is `bash deploy.sh` on the box" with "A by-hand `bash deploy.sh` on the box (the §8 rollback is now `LIBLI_DEPLOY_REF=<sha> bash deploy.sh`)".

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_deploy_libli_path.py tests/test_deploy_wiring.py tests/test_backup_wiring.py tests/test_manage_wiring.py`
Expected: all PASS.

- [ ] **Step 7: Falsify**

For each docstring mutant in `tests/test_deploy_libli_path.py`, hand-edit `deploy.sh`, run that file, confirm the named test goes RED, hand-edit back. Required mutants: tag write moved after `up`; `trap on_exit EXIT` → `trap on_exit ERR`; `REACHED_UP` check removed from `on_exit`; `trap 'exit 129' HUP` removed; `unset LIBLI_IMAGE_TAG` removed; D9 block deleted; D9 block moved inside the `else fetch_master` branch.

- [ ] **Step 8: Commit**

```bash
git add deploy.sh tests/release_harness.py tests/test_deploy_libli_path.py tests/test_deploy_wiring.py
git commit -m "feat(deploy): main() wrapper, pre-up restore, D9 superseded refusal, tag persisted before up"
```

---

### Task 3: deploy.sh — the release path

No production change is expected: Task 2 wrote the whole file. This task pins the release-channel and ref behaviour with tests and proves each by mutant. If a test here fails against Task 2's file, fix `deploy.sh` (that is a Task 2 defect) and say so in the report.

**Files:**
- Test: `tests/test_deploy_release_path.py`

**Interfaces:**
- Consumes: `tests.release_harness.Box`, `run_deploy`, `calls`, `env_at_up`, `head`, `on_branch`, `git` (Task 2); `deploy.sh` (Task 2).

- [ ] **Step 1: Write the tests**

Create `tests/test_deploy_release_path.py`:

```python
"""deploy.sh on a release-channel school box, and the by-hand ref path."""

from pathlib import Path

import pytest

from tests.release_harness import (
    BASH,
    Box,
    calls,
    env_at_up,
    git,
    head,
    on_branch,
    run_deploy,
    write,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")

RELEASE = "LIBLI_DEPLOY_CHANNEL=release"


@pytest.fixture
def school(tmp_path):
    """v1.0.0 = A (deployed), v1.1.0 = B (no migration), v1.2.0 = M (migration)."""
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    b = box.commit(extra={"README": "b\n"}, msg="B")
    box.tag("v1.1.0", b)
    m = box.commit(migrations=["0002_more"], msg="M")
    box.tag("v1.2.0", m)
    box.clone(a, detached=True, image_tag=f"sha-{a}", channel_line=RELEASE)
    return box, a, b, m


def test_no_ref_is_refused_before_any_fetch_or_docker(school):
    box, a, b, m = school
    result = run_deploy(box)
    assert result.returncode != 0
    assert "release-channel box" in result.stderr
    assert "docker " not in calls(box)
    assert head(box) == a


def test_an_early_refusal_leaves_a_hand_edited_file_alone(school):
    """HEAD never moved (it equals the persisted tag's commit), so the trap must
    not force-checkout: `git checkout --force` onto the SAME commit still
    discards local edits to tracked files.

    Mutant: drop the `!= RESTORE_SHA` comparison in on_exit and always restore.
    """
    box, a, b, m = school
    write(box.app / "Caddyfile", "# patched during an incident\n")
    result = run_deploy(box)
    assert result.returncode != 0
    assert (box.app / "Caddyfile").read_text() == "# patched during an incident\n"


@pytest.mark.parametrize("ref", ["master", "v1.0", "V1.1.0"])
def test_a_malformed_ref_is_refused(school, ref):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": ref})
    assert result.returncode != 0
    assert "vX.Y.Z" in result.stderr


def test_a_sha_ref_is_refused_on_a_release_box(school):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": b})
    assert result.returncode != 0
    assert "must be a vX.Y.Z tag on a release-channel box" in result.stderr


def test_an_upgrade_by_tag_deploys_it(school):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b and not on_branch(box)
    assert f"LIBLI_IMAGE_TAG=sha-{b}" in env_at_up(box)


def test_a_tag_present_only_after_the_fetch_is_guarded_and_deployed(school):
    """The clone predates v1.1.0 until deploy.sh fetches it. The guard must run
    AFTER the fetch. Mutant: move the `target="$(git rev-parse ...)"` line and
    the `run_migration_guards` call above the fetch block -- the tag is not yet
    in the clone, so the run goes RED on the return code ("does not resolve")."""
    box, a, b, m = school
    git(box.app, "tag", "-d", "v1.1.0")
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b


def test_a_downgrade_across_a_migration_is_refused_by_the_embedded_guard(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    m = box.commit(migrations=["0002_more"], msg="M")
    box.tag("v1.2.0", m)
    box.clone(m, detached=True, image_tag=f"sha-{m}", channel_line=RELEASE)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "0002_more" in result.stderr
    assert "docker " not in calls(box)
    assert head(box) == m


def test_only_the_newer_guard_copy_refusing_is_enough(tmp_path):
    """The current release's guard refuses; the older target's would pass.

    Mutant: run only the target's copy in run_migration_guards.
    """
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    strict = "#!/usr/bin/env bash\necho 'newer guard: refuse' >&2\nexit 1\n"
    c = box.commit(guard=strict, extra={"README": "c\n"}, msg="C")
    box.tag("v1.3.0", c)
    box.clone(c, detached=True, image_tag=f"sha-{c}", channel_line=RELEASE)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "newer guard: refuse" in result.stderr
    assert head(box) == c


def test_the_ref_fetch_retries(school):
    """The anonymous-401 flake hits tag fetches too. Mutant: call
    `git fetch origin "+refs/tags/..."` once instead of git_fetch_retry."""
    box, a, b, m = school
    git(box.app, "tag", "-d", "v1.1.0")
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0", "FAIL_FETCHES": "2"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b
    assert Path(f"{box.log}.fetches").read_text().strip() == "3"


def test_a_stale_local_tag_is_replaced_by_the_forced_fetch(school):
    """Mutant: fetch with `git fetch origin tag <v>` (no +refspec)."""
    box, a, b, m = school
    git(box.app, "tag", "-f", "v1.1.0", a)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b


def test_an_expected_sha_mismatch_is_refused(school):
    box, a, b, m = school
    result = run_deploy(
        box,
        env={"LIBLI_DEPLOY_REF": "v1.1.0", "LIBLI_DEPLOY_EXPECT_SHA": m},
    )
    assert result.returncode != 0
    assert "not the verified" in result.stderr
    assert head(box) == a


def test_an_absent_tag_on_a_release_box_is_refused_before_any_fetch(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    b = box.commit(extra={"README": "b\n"}, msg="B")
    box.clone(a, detached=True, image_tag=None, channel_line=RELEASE)
    box.tag("v1.1.0", b)  # on origin only, after the clone
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode != 0
    assert "LIBLI_IMAGE_TAG absent" in result.stderr
    assert git(box.app, "tag", "-l", "v1.1.0") == ""


def test_a_duplicated_tag_line_on_a_release_box_is_refused(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(
        a, detached=True, image_tag=f"sha-{a}", channel_line=RELEASE,
        extra_env=f"LIBLI_IMAGE_TAG=sha-{a}\n",
    )
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "LIBLI_IMAGE_TAG unreadable" in result.stderr


@pytest.mark.parametrize(
    "line",
    [
        "#LIBLI_DEPLOY_CHANNEL=release",
        "LIBLI_DEPLOY_CHANNEL=",
        "export LIBLI_DEPLOY_CHANNEL=release",
        "  LIBLI_DEPLOY_CHANNEL=release",
        "LIBLI_DEPLOY_CHANNEL=relase",
        "LIBLI_DEPLOY_CHANNEL=Release",
    ],
)
def test_a_present_but_invalid_channel_line_is_refused(tmp_path, line):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(a, detached=True, image_tag=f"sha-{a}", channel_line=line)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "not exactly 'release'" in result.stderr


def test_a_pull_failure_on_a_detached_box_restores_by_checkout(school):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0", "FAIL_AT": "pull"})
    assert result.returncode != 0
    assert head(box) == a and not on_branch(box)


def test_libli_by_hand_sha_fetches_a_commit_the_clone_lacks(tmp_path):
    """The runbook's §8 recipe runs WITHOUT skip-fetch, through
    `git_fetch_retry "$ref"` with a bare sha. R is pushed after the clone (as
    master's tip, so the local bare origin advertises it).
    Mutant: fetch `"+refs/tags/$ref:refs/tags/$ref"` on the sha path too."""
    box = Box(tmp_path)
    p = box.commit(msg="P")
    box.clone(p, detached=False, image_tag=f"sha-{p}")
    r = box.commit(extra={"README": "r\n"}, msg="R")
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": r})
    assert result.returncode == 0, result.stderr
    assert head(box) == r


def test_libli_by_hand_sha_then_an_ordinary_run_returns_to_master(tmp_path):
    box = Box(tmp_path)
    p = box.commit(msg="P")
    q = box.commit(extra={"README": "q\n"}, msg="Q")
    box.clone(q, detached=False, image_tag=f"sha-{q}")
    git(box.app, "fetch", "-q", "origin")
    first = run_deploy(box, env={"LIBLI_DEPLOY_REF": p, "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert first.returncode == 0, first.stderr
    assert head(box) == p and not on_branch(box)
    second = run_deploy(box)
    assert second.returncode == 0, second.stderr
    assert head(box) == q and on_branch(box)


def test_an_in_place_rewrite_of_the_running_script_changes_nothing(tmp_path):
    """While deploy.sh runs, its file is overwritten IN PLACE (same inode) with a
    version carrying, right after the `set` line, more blank lines than the
    whole old file is long and then one `echo NEW-FILE-EXECUTED` line. Without the
    `main "$@"; exit` wrapper bash resumes reading at its old byte offset --
    inside that block.

    Why in place rather than via `git checkout`: on Linux git replaces a file
    with a NEW inode, so a running bash keeps reading the old one and a
    checkout-based test could never go red. (On Windows git cannot replace an
    open file at all, and prompts interactively.) The wrapper is what makes
    every kind of rewrite safe; this pins it deterministically. Every other
    fixture commit shares a byte-identical deploy.sh, so no test checks out a
    different one while it runs.

    Mutant: delete `main() {`, its closing `}`, and `main "$@"; exit`, leaving
    the body at top level -- AND turn every `local` in that body into a plain
    assignment (`local` is an error outside a function, and `set -e` would
    exit before the rewrite happens). The RED must come from the
    NEW-FILE-EXECUTED assertion, not the return code; a mutant that fails
    only on the return code proves nothing about the wrapper.
    """
    box = Box(tmp_path)
    p = box.commit(msg="P")
    box.clone(p, detached=False, image_tag=f"sha-{p}")
    current = (box.app / "deploy.sh").read_text(encoding="utf-8")
    head_text, rest = current.split("set -euo pipefail\n", 1)
    # Blank lines longer than the whole old file, then ONE marker line: from
    # any old byte offset bash reads only empty commands until the marker. (A
    # block of repeated `echo` lines would usually be entered mid-line -- `cho
    # NEW...` exits 127 without printing the marker, a RED on the return code
    # alone, which proves nothing.)
    block = "\n" * (len(current) + 50) + "echo NEW-FILE-EXECUTED\n"
    replacement = box.tmp / "replacement.sh"
    write(replacement, head_text + "set -euo pipefail\n" + block + rest)
    result = run_deploy(
        box,
        env={
            "REWRITE_TARGET": str(box.app / "deploy.sh").replace("\\", "/"),
            "REWRITE_WITH": str(replacement).replace("\\", "/"),
        },
    )
    assert "NEW-FILE-EXECUTED" not in result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_deploy_release_path.py`
Expected: all PASS against Task 2's `deploy.sh`.

- [ ] **Step 3: Falsify**

Apply each docstring mutant to `deploy.sh` by hand, run this file, confirm the named test goes RED, revert by hand. Additionally: delete the `release)` arm of the channel `case` → `test_no_ref_is_refused…` RED; accept `^[0-9a-f]{40}$` refs on a release box → `test_a_sha_ref_is_refused…` RED. The wrapper mutant (with every `local` in the body made a plain assignment, per the docstring) must turn `test_an_in_place_rewrite…` RED **on the `NEW-FILE-EXECUTED` assertion** — check the failure output; a RED on the return-code assertion alone does not count. If it does not, report the actual behaviour observed rather than adjusting the test until it passes.

- [ ] **Step 4: Commit**

```bash
git add tests/test_deploy_release_path.py
git commit -m "test(deploy): pin the release-channel and by-hand ref paths"
```

---

### Task 4: deploy.yml — D9 expected-sha export

**Files:**
- Modify: `.github/workflows/deploy.yml` (the `script:` block of the `Deploy to production` step)
- Modify: `tests/test_deploy_wiring.py` (`_yml_script_for` substitutes `${{ github.sha }}`; new D9 tests)

**Interfaces:**
- Consumes: `deploy.sh`'s `LIBLI_DEPLOY_EXPECT_SHA` handling on the unset-ref path (Task 2).
- Produces: `deploy.yml`'s remote script exports `LIBLI_DEPLOY_EXPECT_SHA` before invoking `deploy.sh`. The canary guard (Task 7) relies on this for soundness (spec §4).

- [ ] **Step 1: Write the failing tests**

In `tests/test_deploy_wiring.py`, change `_yml_script_for` to take the sha and substitute it (every existing caller keeps working with the default):

```python
FAKE_RUN_SHA = "0123456789abcdef0123456789abcdef01234567"


def _yml_script_for(tmp_path, stub, run_sha=FAKE_RUN_SHA):
    """deploy.yml's script with the host paths pointed at tmp_path and the
    `${{ github.sha }}` expression Actions would substitute replaced by
    `run_sha`. The retry loop itself runs exactly as shipped."""
    app = _app_dir()
    return (
        _deploy_yml_script()
        .replace("${{ github.sha }}", run_sha)
        .replace(f"bash {app}/deploy.sh", f'bash "{str(stub).replace(chr(92), "/")}"')
        .replace(f"cd {app}", f'cd "{str(tmp_path).replace(chr(92), "/")}"')
    )
```

Append these tests:

```python
# ---- D9: a run deploys only its own commit --------------------------------


def test_d9_the_runs_own_sha_is_exported_inside_the_remote_script():
    """appleboy/ssh-action passes a step's env: to the remote only when it is
    also listed in `envs:`, so the value must be exported INSIDE `script:`.
    Without it deploy.sh sees nothing, D9 is silently off, and the canary
    guard reads a green deploy job for X that actually deployed Y.

    Mutants: delete the export line; move the value to the step's `env:` only.
    """
    script = _deploy_yml_script()
    export = re.search(
        r"^export LIBLI_DEPLOY_EXPECT_SHA='\$\{\{ github\.sha \}\}'$", script, re.MULTILINE
    )
    invoke = re.search(r"^\s*(?:\S+=\S+ )?bash \S+/deploy\.sh$", script, re.MULTILINE)
    assert export, "deploy.yml's script no longer exports LIBLI_DEPLOY_EXPECT_SHA"
    assert invoke and export.start() < invoke.start()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.parametrize("bad", ["", "abc", "g" * 40, "0" * 39])
def test_d9_a_missing_or_malformed_sha_fails_closed(tmp_path, bad):
    """Mutant: delete the fail-closed check -- deploy.sh would then run with
    an empty value, treat it as unset, and deploy whatever master is."""
    calls = tmp_path / "calls"
    calls.write_text("")
    marker = tmp_path / "deployed"
    stub = tmp_path / "stub-deploy.sh"
    stub.write_bytes(f'touch "{str(marker).replace(chr(92), "/")}"\n'.encode())
    result = _run_bash(f"{_harness(calls, 0)}\n{_yml_script_for(tmp_path, stub, bad)}")
    assert result.returncode != 0
    assert not marker.exists(), "deployed with no verified sha"


def test_d9_the_deploy_job_keeps_its_bare_id_as_its_name():
    """The canary guard finds the job named `deploy` in the jobs API, which
    reports the display name -- the job id only while the job has no `name:`.
    Mutant: add `name: Deploy` to the deploy job."""
    lines = DEPLOY_YML.read_text(encoding="utf-8").splitlines()
    start = lines.index("  deploy:")
    block = []
    for ln in lines[start + 1 :]:
        if ln.startswith("  ") and not ln.startswith("   ") and ln.strip():
            break
        block.append(ln)
    assert not [ln for ln in block if re.match(r"^    name:", ln)], block
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_deploy_wiring.py`
Expected: `test_d9_the_runs_own_sha_is_exported_inside_the_remote_script` and `test_d9_a_missing_or_malformed_sha_fails_closed` FAIL; everything else PASSes.

- [ ] **Step 3: Edit deploy.yml**

In the `script: |` block, insert after `cd /opt/libli` (keep `set -e` first and everything else unchanged):

```yaml
            export LIBLI_DEPLOY_EXPECT_SHA='${{ github.sha }}'
            case "$LIBLI_DEPLOY_EXPECT_SHA" in
              *[!0-9a-f]*|'') echo "LIBLI_DEPLOY_EXPECT_SHA is not a 40-hex sha; refusing" >&2; exit 1 ;;
            esac
            [ "${#LIBLI_DEPLOY_EXPECT_SHA}" -eq 40 ] || { echo "LIBLI_DEPLOY_EXPECT_SHA is not a 40-hex sha; refusing" >&2; exit 1; }
```

POSIX `case` + `${#}` rather than the spec's `[[ =~ ]]`: drone-ssh runs the script in the login shell, and this keeps it correct even if that is not bash. Same effect.

Also reword two existing comment lines in that block that call plain `bash deploy.sh` the rollback: change "(the rollback path in docs/deployment.md §8)" to "(a by-hand run; the §8 rollback is `LIBLI_DEPLOY_REF=<sha> bash deploy.sh`)", and "deploy.sh keeps its own fetch for the by-hand rollback path." to "deploy.sh keeps its own fetch for a by-hand run."

Add to the long comment above `script:` a paragraph:

```yaml
          # D9 (spec 2026-09-27-b2-release-deploys-design.md): deploy.sh refuses
          # when origin/master is no longer this run's commit, so a green deploy
          # job proves libli.pl ran THIS commit -- which the release canary guard
          # relies on. The value is exported inside the script because a step
          # env: reaches the remote only via `envs:`. `${{ github.sha }}` is 40 hex
          # that Actions controls, so the no-expressions-in-scripts rule (which
          # exists for secrets and untrusted input) does not apply; the check
          # after it fails closed if it is ever empty. A superseded run goes red
          # and harmless -- docs/deployment.md §8.
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_deploy_wiring.py`
Expected: all PASS.

- [ ] **Step 5: Falsify** — both mutants in the first test's docstring, and removing the `case` block (the `"g" * 40` case goes RED) and the length line (the `"0" * 39` case goes RED); and insert `    name: Deploy` under `  deploy:` in deploy.yml → `test_d9_the_deploy_job_keeps_its_bare_id_as_its_name` RED. Revert by hand.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/deploy.yml tests/test_deploy_wiring.py
git commit -m "feat(deploy): D9 -- libli.pl deploys refuse when master moved past the run"
```

---

### Task 5: Pre-flight script and the shared read-rule fixtures

**Files:**
- Create: `scripts/release/preflight.sh`
- Create: `tests/release_fixtures.py`
- Test: `tests/test_release_preflight.py`

**Interfaces:**
- Consumes: `tests.release_harness` (`Box`, `BASH`, `ROOT`, `git`, `posix`, `write`).
- Produces: `ssh <box> bash -s -- <version> <target-sha> < scripts/release/preflight.sh` → stdout exactly `image_tag=sha-<40hex>\nchannel=release\n`, exit 0; or `refuse: <reason>\n`, exit 1. `… bash -s -- --read-only …` → `image_tag=sha-<40hex>\n` or `refuse: …`. Task 12's workflow parses these lines.
- Produces: `tests.release_fixtures.CHANNEL_CASES`, `IMAGE_TAG_CASES` (lists of `(id, file_text, expected)`); `extract_function(script_path, name) -> str`; `run_function(script_path, names, call, env_file) -> str` (defines the listed functions in order, runs `call <env_file>`, returns stripped stdout); `env_file(tmp_path, text) -> Path`.

- [ ] **Step 1: Write the shared fixtures**

Create `tests/release_fixtures.py`:

```python
"""The two .env.production read rules, as ONE set of cases.

deploy.sh and preflight.sh each carry their own copy of channel_state and
image_tag_state -- deliberately not a shared sourced helper, because deploy.sh
runs as a temp copy at the target release and would source the CURRENT
checkout's file (spec §2 step 4). These cases are what keeps the copies equal.
"""

import re
import subprocess

from tests.release_harness import BASH, posix, write

SHA = "0123456789abcdef0123456789abcdef01234567"

CHANNEL_CASES = [
    ("absent", "", "absent"),
    ("release", "LIBLI_DEPLOY_CHANNEL=release\n", "release"),
    ("export", "export LIBLI_DEPLOY_CHANNEL=release\n", "invalid"),
    ("indented", "  LIBLI_DEPLOY_CHANNEL=release\n", "invalid"),
    ("empty", "LIBLI_DEPLOY_CHANNEL=\n", "invalid"),
    ("typo", "LIBLI_DEPLOY_CHANNEL=relase\n", "invalid"),
    ("capital", "LIBLI_DEPLOY_CHANNEL=Release\n", "invalid"),
    ("trailing-space", "LIBLI_DEPLOY_CHANNEL=release \n", "invalid"),
    ("commented", "#LIBLI_DEPLOY_CHANNEL=release\n", "invalid"),
    ("crlf", "LIBLI_DEPLOY_CHANNEL=release\r\n", "invalid"),
    ("duplicate", "LIBLI_DEPLOY_CHANNEL=release\nLIBLI_DEPLOY_CHANNEL=release\n", "invalid"),
]

IMAGE_TAG_CASES = [
    ("valid", f"LIBLI_IMAGE_TAG=sha-{SHA}\n", f"sha-{SHA}"),
    ("absent", "", "absent"),
    ("duplicate", f"LIBLI_IMAGE_TAG=sha-{SHA}\nLIBLI_IMAGE_TAG=sha-{SHA}\n", "invalid"),
    ("export", f"export LIBLI_IMAGE_TAG=sha-{SHA}\n", "invalid"),
    ("indented", f"  LIBLI_IMAGE_TAG=sha-{SHA}\n", "invalid"),
    ("crlf", f"LIBLI_IMAGE_TAG=sha-{SHA}\r\n", "invalid"),
    ("short", "LIBLI_IMAGE_TAG=sha-0123abc\n", "invalid"),
    ("tag-name", "LIBLI_IMAGE_TAG=sha-v1.0.0\n", "invalid"),
]


def extract_function(script_path, name):
    text = script_path.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{$.*?^\}}$", text, re.MULTILINE | re.DOTALL)
    assert match, f"{script_path.name} defines no top-level {name}()"
    return match.group(0)


def run_function(script_path, names, call, env_file):
    """Define `names` (in order) from script_path, then run `call <env_file>`."""
    body = "\n".join(extract_function(script_path, n) for n in names)
    result = subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [BASH, "-c", f'set -euo pipefail\n{body}\n{call} "{posix(env_file)}"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def env_file(tmp_path, text):
    path = tmp_path / "env"
    write(path, "OTHER=1\n" + text)
    return path
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_release_preflight.py`:

```python
"""scripts/release/preflight.sh -- the on-box pre-flight (spec §2 step 4)."""

import os
import subprocess

import pytest

from tests.release_fixtures import (
    CHANNEL_CASES,
    IMAGE_TAG_CASES,
    env_file,
    run_function,
)
from tests.release_harness import BASH, ROOT, Box, git, posix

PREFLIGHT = ROOT / "scripts/release/preflight.sh"
DEPLOY_SH = ROOT / "deploy.sh"

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


@pytest.mark.parametrize("case_id,text,expected", CHANNEL_CASES, ids=[c[0] for c in CHANNEL_CASES])
def test_the_channel_rule_is_identical_in_both_scripts(tmp_path, case_id, text, expected):
    """Mutant: edit either copy's regex (e.g. accept an `export` prefix)."""
    f = env_file(tmp_path, text)
    for script in (DEPLOY_SH, PREFLIGHT):
        assert run_function(script, ["channel_state"], "channel_state", f) == expected, script.name


@pytest.mark.parametrize("case_id,text,expected", IMAGE_TAG_CASES, ids=[c[0] for c in IMAGE_TAG_CASES])
def test_the_image_tag_rule_is_identical_in_both_scripts(tmp_path, case_id, text, expected):
    f = env_file(tmp_path, text)
    for script in (DEPLOY_SH, PREFLIGHT):
        got = run_function(script, ["image_tag_read", "image_tag_state"], "image_tag_state", f)
        assert got == expected, script.name


def _script(box):
    return (
        PREFLIGHT.read_text(encoding="utf-8")
        .replace("APP_DIR=/opt/libli", f"APP_DIR={posix(box.app)}")
    )


def _preflight(box, *args):
    return subprocess.run(  # noqa: S603 -- fixed argv
        [BASH, "-s", "--", *args],
        input=_script(box),
        capture_output=True,
        text=True,
        env=dict(os.environ, GIT_FETCH_DELAY="0"),
        timeout=60,
    )


@pytest.fixture
def school(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    b = box.commit(extra={"README": "b\n"}, msg="B")
    box.tag("v1.1.0", b)
    box.clone(a, detached=True, image_tag=f"sha-{a}", channel_line="LIBLI_DEPLOY_CHANNEL=release")
    return box, a, b


def test_success_prints_exactly_two_lines(school):
    box, a, b = school
    result = _preflight(box, "v1.1.0", b)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [f"image_tag=sha-{a}", "channel=release"]


def test_read_only_prints_one_line_and_does_not_fetch(school):
    box, a, b = school
    git(box.app, "remote", "set-url", "origin", "/nonexistent/origin.git")
    result = _preflight(box, "--read-only")
    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines() == [f"image_tag=sha-{a}"]


def test_a_box_without_the_channel_line_is_refused(tmp_path):
    """Mutant: drop the channel check from preflight.sh."""
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(a, detached=True, image_tag=f"sha-{a}")
    result = _preflight(box, "v1.0.0", a)
    assert result.returncode != 0
    assert result.stdout.startswith("refuse: ")
    assert "LIBLI_DEPLOY_CHANNEL" in result.stdout


def test_an_absent_tag_is_refused(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(a, detached=True, image_tag=None, channel_line="LIBLI_DEPLOY_CHANNEL=release")
    result = _preflight(box, "v1.0.0", a)
    assert result.returncode != 0
    assert "LIBLI_IMAGE_TAG absent" in result.stdout


def test_no_refusal_ever_echoes_the_file(tmp_path):
    """The box's .env.production holds every secret. A sentinel secret sits next
    to a malformed tag line whose VALUE is also a sentinel.

    Mutant: include the offending line in the refusal message.
    """
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(
        a, detached=True, image_tag="sha-SENTINEL-TAG-77",
        channel_line="LIBLI_DEPLOY_CHANNEL=release",
    )
    for args in (("v1.0.0", a), ("--read-only",)):
        result = _preflight(box, *args)
        assert result.returncode != 0
        out = result.stdout + result.stderr
        assert "SENTINEL" not in out, out


def test_a_crlf_env_file_is_refused_with_a_reason_that_says_so(tmp_path):
    """Review focus 1: an env file saved on Windows."""
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(a, detached=True, image_tag=f"sha-{a}", channel_line="LIBLI_DEPLOY_CHANNEL=release")
    path = box.app / ".env.production"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    result = _preflight(box, "v1.0.0", a)
    assert result.returncode != 0
    assert "CRLF" in result.stdout


def test_a_stale_local_tag_is_replaced_by_the_forced_fetch(school):
    """Mutant: fetch `refs/tags/<v>:refs/tags/<v>` without the leading `+`."""
    box, a, b = school
    git(box.app, "tag", "-f", "v1.1.0", a)
    result = _preflight(box, "v1.1.0", b)
    assert result.returncode == 0, result.stdout


def test_a_tag_resolving_to_another_commit_is_refused(school):
    """Mutant: drop the target-sha comparison."""
    box, a, b = school
    result = _preflight(box, "v1.1.0", a)
    assert result.returncode != 0
    assert "different commit" in result.stdout


GIT_FLAKE_STUB = """git() {
  if [ "$1" = fetch ]; then
    n=$(( $(cat "@@COUNTER@@" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "@@COUNTER@@"
    if [ "$n" -le 2 ]; then return 128; fi
  fi
  command git "$@"
}
"""


def test_the_tag_fetch_retries(school):
    """The first two fetches fail (the anonymous-401 flake), the third works.
    Mutant: a single `git fetch` with no loop."""
    box, a, b = school
    git(box.app, "tag", "-d", "v1.1.0")
    counter = box.tmp / "fetches"
    stub = GIT_FLAKE_STUB.replace("@@COUNTER@@", posix(counter))
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [BASH, "-s", "--", "v1.1.0", b],
        input=stub + _script(box),
        capture_output=True,
        text=True,
        env=dict(os.environ, GIT_FETCH_DELAY="0"),
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert counter.read_text().strip() == "3"


def test_an_unfetchable_tag_names_both_causes(school):
    box, a, b = school
    git(box.app, "remote", "set-url", "origin", "/nonexistent/origin.git")
    result = _preflight(box, "v1.1.0", b)
    assert result.returncode != 0
    assert "re-run" in result.stdout and "deploy key" in result.stdout


@pytest.mark.parametrize("args", [("v1.1", "a" * 40), ("v1.1.0", "abc")])
def test_malformed_arguments_are_refused(school, args):
    box, a, b = school
    result = _preflight(box, *args)
    assert result.returncode != 0
    assert result.stdout.startswith("refuse: ")
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_release_preflight.py`
Expected: FAIL — `scripts/release/preflight.sh` does not exist (the `DEPLOY_SH` halves of the parametrised rule tests pass; the `PREFLIGHT` halves fail).

- [ ] **Step 4: Write preflight.sh**

Create `scripts/release/preflight.sh`. The three read-rule functions are **byte-for-byte** copies of `deploy.sh`'s (Task 2):

```bash
#!/usr/bin/env bash
# Pre-flight for a school deploy (B2; spec §2 step 4). Sent over ssh on stdin:
#   ssh <box> bash -s -- <version> <target-sha> < scripts/release/preflight.sh
#   ssh <box> bash -s -- --read-only             < scripts/release/preflight.sh
#
# .env.production holds every box secret, so it is parsed HERE and never
# copied off the box. Output on stdout, exactly:
#   image_tag=sha-<40 hex>
#   channel=release          (not printed in --read-only mode)
# or one line `refuse: <reason>` and exit 1. No refusal echoes a line of the
# file, and none names the host.
set -euo pipefail

APP_DIR=/opt/libli
GIT_FETCH_ATTEMPTS=${GIT_FETCH_ATTEMPTS:-3}
GIT_FETCH_DELAY=${GIT_FETCH_DELAY:-5}

refuse() {
  echo "refuse: $*"
  exit 1
}

# channel_state, image_tag_read and image_tag_state are VERBATIM copies of
# deploy.sh's. Not a sourced helper on purpose (deploy.sh runs as a temp copy at
# the target release); tests/release_fixtures.py holds both to the same cases.
channel_state() {
  awk '
    /^[[:space:]]*#.*LIBLI_DEPLOY_CHANNEL/ { n++; bad = 1; next }
    /^[[:space:]]*(export[[:space:]]+)?LIBLI_DEPLOY_CHANNEL[[:space:]]*=/ {
      n++
      if ($0 != "LIBLI_DEPLOY_CHANNEL=release") bad = 1
    }
    END {
      if (n == 0) print "absent"
      else if (n == 1 && !bad) print "release"
      else print "invalid"
    }
  ' "$1"
}

image_tag_read() {
  awk '
    /^[[:space:]]*(export[[:space:]]+)?LIBLI_IMAGE_TAG[[:space:]]*=/ {
      any++
      if (index($0, "LIBLI_IMAGE_TAG=") == 1) { anchored++; val = substr($0, 17) }
    }
    END {
      if (any == 0) print "absent"
      else if (any != 1 || anchored != 1) print "invalid"
      else print "value " val
    }
  ' "$1"
}

image_tag_state() {
  local read value
  read="$(image_tag_read "$1")"
  case "$read" in
    "value "*)
      value="${read#value }"
      if [[ $value =~ ^sha-[0-9a-f]{40}$ ]]; then echo "$value"; else echo invalid; fi
      ;;
    *) echo "$read" ;;
  esac
}

# A file saved on Windows makes every rule fail at once; say why.
crlf_hint() {
  if grep -q $'\r' .env.production; then
    echo " (.env.production has CRLF line endings; convert it to LF)"
  fi
}

main() {
  local mode=deploy version target_sha tag attempt got
  if [ "${1:-}" = --read-only ]; then
    mode=read
    shift
  fi
  cd "$APP_DIR" 2> /dev/null || refuse "no checkout at $APP_DIR"
  [ -r .env.production ] || refuse ".env.production is missing"

  tag="$(image_tag_state .env.production)"
  case "$tag" in
    absent) refuse "LIBLI_IMAGE_TAG absent in .env.production$(crlf_hint)" ;;
    invalid) refuse "LIBLI_IMAGE_TAG malformed in .env.production (need exactly one line LIBLI_IMAGE_TAG=sha-<40 hex>)$(crlf_hint)" ;;
  esac
  if [ "$mode" = read ]; then
    echo "image_tag=$tag"
    return 0
  fi

  version=${1:-}
  target_sha=${2:-}
  [[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || refuse "version is not vX.Y.Z"
  [[ $target_sha =~ ^[0-9a-f]{40}$ ]] || refuse "target sha is not 40 hex"
  [ "$(channel_state .env.production)" = release ] \
    || refuse "LIBLI_DEPLOY_CHANNEL is not exactly 'release' in .env.production (docs/deployment.md §9)$(crlf_hint)"

  # Forced: a tag deleted and re-cut under the same name must replace the box's
  # stale local one, or the box would deploy a commit the canary never checked.
  attempt=1
  until git fetch -q origin "+refs/tags/$version:refs/tags/$version" > /dev/null 2>&1; do
    if [ "$attempt" -ge "$GIT_FETCH_ATTEMPTS" ]; then
      refuse "cannot fetch $version after $GIT_FETCH_ATTEMPTS attempts: a transient GitHub refusal (re-run the workflow) or a missing/broken deploy key (docs/deployment.md §9)"
    fi
    attempt=$((attempt + 1))
    sleep "$GIT_FETCH_DELAY"
  done
  got="$(git rev-parse --verify --quiet "$version^{commit}")" || refuse "$version does not resolve to a commit on the box"
  [ "$got" = "$target_sha" ] || refuse "$version resolves to a different commit on the box than the one checked (was the tag re-cut?)"

  echo "image_tag=$tag"
  echo "channel=release"
}

main "$@"; exit
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_release_preflight.py`
Expected: all PASS.

- [ ] **Step 6: Falsify** — each docstring mutant, plus: in preflight.sh's `channel_state`, change `bad = 1` on the commented-line rule to nothing → the `commented` channel case goes RED for PREFLIGHT only. Revert by hand.

- [ ] **Step 7: Commit**

```bash
git add scripts/release/preflight.sh tests/release_fixtures.py tests/test_release_preflight.py
git commit -m "feat(release): on-box pre-flight with shared read-rule fixtures"
```

---

### Task 6: Detached remote deploy bootstrap

**Files:**
- Create: `scripts/release/remote_deploy.sh`
- Test: `tests/test_release_remote_deploy.py`

**Interfaces:**
- Consumes: the target tag's `deploy.sh` honouring `LIBLI_DEPLOY_REF`, `LIBLI_DEPLOY_EXPECT_SHA`, `LIBLI_DEPLOY_SKIP_FETCH` (Task 2).
- Produces: `ssh <box> bash -s -- <version> <target-sha> < scripts/release/remote_deploy.sh`. Streams the deploy log; exits with `deploy.sh`'s status; `1` with `!! …` on stderr for its own refusals. Task 12 calls it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release_remote_deploy.py`:

```python
"""scripts/release/remote_deploy.sh -- the detached bootstrap (spec §2 step 6).

Real bash, setsid, nohup and tail: faking bash would leave the wrapper's quoting
unparsed, and faking setsid/nohup would remove the very detachment under test.
Only git history (real, in a fixture) and the target deploy.sh (a fake that
reports what it received) are stand-ins. Needs util-linux setsid and GNU
`tail --pid`: skipped on Git Bash for Windows, run in CI.
"""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.release_harness import BASH, ROOT, Box, posix, write

SCRIPT = ROOT / "scripts/release/remote_deploy.sh"

pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("setsid") is None,
    reason="needs bash and util-linux setsid (Linux; runs in CI)",
)

FAKE_DEPLOY = """#!/usr/bin/env bash
# fake target deploy.sh -- knows LIBLI_DEPLOY_REF LIBLI_DEPLOY_EXPECT_SHA LIBLI_DEPLOY_SKIP_FETCH
echo "SCRIPT=$0"
echo "ref=$LIBLI_DEPLOY_REF expect=$LIBLI_DEPLOY_EXPECT_SHA skip=$LIBLI_DEPLOY_SKIP_FETCH"
if read -r line; then echo "GOT-STDIN:$line"; else echo "STDIN-EOF"; fi
for i in $(seq 1 "${FAKE_LINES:-3}"); do echo "line $i"; done
sleep "${FAKE_SLEEP:-0}"
test -f "$0" && echo SELF-PRESENT
if [ -n "${FAKE_KILL_WRAPPER:-}" ]; then kill -9 "$PPID"; fi
echo FAKE-DONE
exit "${FAKE_RC:-0}"
"""


@pytest.fixture
def box(tmp_path):
    b = Box(tmp_path)
    sha = b.commit(extra={"deploy.sh": FAKE_DEPLOY}, msg="A")
    b.tag("v1.0.0", sha)
    b.clone(sha, detached=True, image_tag=f"sha-{sha}", channel_line="LIBLI_DEPLOY_CHANNEL=release")
    b.sha = sha
    b.state = tmp_path / "state"
    b.logs = tmp_path / "logs"
    return b


def _text(box, *, pid_wait=None, start_cmd=None):
    text = (
        SCRIPT.read_text(encoding="utf-8")
        .replace("APP_DIR=/opt/libli", f"APP_DIR={posix(box.app)}")
        .replace("/var/lib/libli-deploy", posix(box.state))
        .replace("/var/log/libli-deploy", posix(box.logs))
    )
    if pid_wait is not None:
        text = text.replace("PID_WAIT_SECONDS=30", f"PID_WAIT_SECONDS={pid_wait}")
    if start_cmd is not None:
        text = text.replace("setsid nohup bash -c", f"{start_cmd} bash -c")
    return text


def _start(box, *, extra_stdin="", env=None, **text_kw):
    e = dict(os.environ)
    e.update(env or {})
    proc = subprocess.Popen(  # noqa: S603 -- fixed argv
        [BASH, "-s", "--", "v1.0.0", box.sha],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=e,
        start_new_session=True,
    )
    proc.stdin.write(_text(box, **text_kw) + extra_stdin)
    proc.stdin.close()
    return proc


def _run(box, **kw):
    proc = _start(box, **kw)
    out, err = proc.communicate(timeout=60)
    return proc.returncode, out, err


def _wait_for(predicate, seconds=15):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _status_files(box):
    """Finished status files only: the wrapper writes status.X.tmp and renames
    it, and a poll that caught the .tmp could read it empty or lose it."""
    return sorted(p for p in box.state.glob("status.*") if p.suffix != ".tmp")


def _log_text(box):
    if not box.logs.is_dir():
        return ""
    return "".join(p.read_text() for p in sorted(box.logs.glob("*.log")))


def _deploy_started(box):
    """The detached run EXISTS: a non-empty pid file (the wrapper wrote it)
    and the fake deploy's first line in the log. The mktemp placeholder the
    script creates and deletes is empty, so matching the glob alone would
    race it and kill the session before setsid ran."""
    return _pid_written(box) and "SCRIPT=" in _log_text(box)


def _pid_written(box):
    return box.state.is_dir() and any(p.stat().st_size > 0 for p in box.state.glob("pid.*"))


def test_the_deploy_receives_ref_expected_sha_and_skip_fetch(box):
    """Mutant: drop the positional hand-off to the wrapper (use "$version" etc.
    inside the single-quoted body)."""
    rc, out, err = _run(box)
    assert rc == 0, err
    assert f"ref=v1.0.0 expect={box.sha} skip=1" in out


def test_the_deploy_reads_eof_not_the_rest_of_the_script(box):
    """remote_deploy.sh itself arrives on stdin. Mutant: replace `< /dev/null`
    with `<&0` (re-attach the session's stdin). Merely DROPPING `< /dev/null`
    cannot go red: a non-interactive bash already gives an `&` command
    /dev/null as stdin. The explicit redirect stays as documentation."""
    rc, out, err = _run(box, extra_stdin="\necho SWALLOWED-LINE\n")
    assert rc == 0, err
    assert "STDIN-EOF" in out and "GOT-STDIN" not in out


def test_killing_the_session_leaves_the_detached_run_to_finish(box):
    """The ssh session dying (job timeout, cancel) must not stop the deploy.
    Mutant: run deploy.sh in the foreground instead of under setsid nohup."""
    proc = _start(box, env={"FAKE_SLEEP": "2"})
    assert _wait_for(lambda: _deploy_started(box))
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    assert _wait_for(lambda: _status_files(box))
    assert _status_files(box)[0].read_text().strip() == "0"
    assert "FAKE-DONE" in _log_text(box)
    assert "SELF-PRESENT" in _log_text(box)


def test_a_closed_session_pipe_does_not_kill_the_run(box):
    """Mutant: drop the `>>"$log" 2>&1` redirect (the run inherits the
    session's stdout and dies of SIGPIPE when it closes). The start condition
    here is the pid file alone, NOT the log. Under the mutant the wrapper itself
    writes nothing to stdout, so it survives and records the fake deploy's
    SIGPIPE death as status 141: the RED must come from the `== "0"` status
    assertion -- the run died -- not from the log being empty."""
    proc = _start(box, env={"FAKE_SLEEP": "2"})
    assert _wait_for(lambda: _pid_written(box))
    time.sleep(0.5)
    proc.stdout.close()
    os.killpg(proc.pid, signal.SIGKILL)
    assert _wait_for(lambda: _status_files(box))
    assert _status_files(box)[0].read_text().strip() == "0"
    assert "FAKE-DONE" in _log_text(box)


def test_the_session_returns_promptly_and_cleans_up(box):
    start = time.time()
    rc, out, err = _run(box)
    assert rc == 0, err
    assert time.time() - start < 20  # tail --pid polls every second; generous under -n auto
    assert not list(box.state.glob("pid.*")) and not _status_files(box)


def test_a_non_zero_status_becomes_the_exit_code(box):
    rc, out, err = _run(box, env={"FAKE_RC": "3"})
    assert rc == 3


def test_no_recorded_status_exits_1(box):
    rc, out, err = _run(box, env={"FAKE_KILL_WRAPPER": "1"})
    assert rc == 1
    assert "no status" in err


def test_a_hung_up_session_leaves_the_script_for_the_run(box):
    """A real dropped session ends with a TRAPPABLE signal (HUP/PIPE/TERM),
    which runs the session's EXIT trap -- unlike the SIGKILL in the kill test.
    Mutant: remove the temp script from an EXIT trap in the SESSION instead of
    in the wrapper -> the detached run finds its script gone (no SELF-PRESENT)."""
    proc = _start(box, env={"FAKE_SLEEP": "2"})
    assert _wait_for(lambda: _deploy_started(box))
    os.killpg(proc.pid, signal.SIGHUP)
    proc.wait(timeout=10)
    assert _wait_for(lambda: _status_files(box))
    assert "SELF-PRESENT" in _log_text(box)


def test_the_temp_script_is_removed_by_the_wrapper(box):
    """Present while the run needs it, gone afterwards. Mutant: never remove
    it. (Removing it from a SESSION trap instead is caught by
    test_a_hung_up_session_leaves_the_script_for_the_run.)"""
    rc, out, err = _run(box)
    assert rc == 0, err
    assert "SELF-PRESENT" in out
    script = next(ln[len("SCRIPT="):] for ln in out.splitlines() if ln.startswith("SCRIPT="))
    assert not Path(script).exists(), script


def test_every_early_line_is_shown(box):
    """Mutant: `tail -f` without `-n +1` (starts at the last 10 lines)."""
    rc, out, err = _run(box, env={"FAKE_LINES": "40"})
    assert all(f"line {i}\n" in out for i in range(1, 41))


def test_logs_are_capped_at_twenty(box):
    box.logs.mkdir(parents=True)
    now = time.time()
    for i in range(25):
        p = box.logs / f"old-{i:02d}.log"
        write(p, "x\n")
        os.utime(p, (now - 1000 + i, now - 1000 + i))
    rc, out, err = _run(box)
    assert rc == 0, err
    remaining = sorted(p.name for p in box.logs.glob("*.log"))
    assert len(remaining) == 20
    assert "old-05.log" not in remaining and "old-06.log" in remaining


def test_stale_state_files_are_swept_at_start(box):
    box.state.mkdir(parents=True)
    stale = box.state / "status.stale"
    fresh = box.state / "status.fresh"
    write(stale, "0\n")
    write(fresh, "0\n")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    rc, out, err = _run(box)
    assert rc == 0, err
    assert not stale.exists() and fresh.exists()


def test_a_wrapper_that_never_reports_its_pid_says_it_may_still_start(box):
    rc, out, err = _run(box, pid_wait=2, start_cmd="true")
    assert rc == 1
    assert "may still start" in err


def test_a_target_deploy_sh_missing_a_required_variable_is_refused(tmp_path):
    b = Box(tmp_path)
    old = FAKE_DEPLOY.replace("LIBLI_DEPLOY_EXPECT_SHA", "X")
    sha = b.commit(extra={"deploy.sh": old}, msg="old")
    b.tag("v1.0.0", sha)
    b.clone(sha, detached=True, image_tag=f"sha-{sha}", channel_line="LIBLI_DEPLOY_CHANNEL=release")
    b.sha, b.state, b.logs = sha, tmp_path / "state", tmp_path / "logs"
    rc, out, err = _run(b)
    assert rc == 1
    assert "LIBLI_DEPLOY_EXPECT_SHA" in err
    assert not list(b.logs.glob("*.log"))


def test_both_state_directories_are_created(box):
    assert not box.state.exists() and not box.logs.exists()
    rc, out, err = _run(box)
    assert rc == 0, err
    assert box.state.is_dir() and box.logs.is_dir()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_release_remote_deploy.py`
Expected on Linux: FAIL (script missing). On Git Bash for Windows: SKIPPED — then run this task's tests in a Linux container or rely on CI, and say which in the report:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/src" -w /src python:3.12 bash -c \
  "pip install -q pytest && git config --global user.email t@t && git config --global user.name t && python -m pytest -p no:cacheprovider -o addopts='' --noconftest tests/test_release_remote_deploy.py"
```

(`--noconftest` skips the Django/DB fixtures these tests do not need; `-o addopts=''` drops the repo's `-m 'not e2e'` which is harmless here.)

- [ ] **Step 3: Write remote_deploy.sh**

Create `scripts/release/remote_deploy.sh`:

```bash
#!/usr/bin/env bash
# Detached deploy bootstrap for a school box (B2; spec §2 step 6). Sent over ssh:
#   ssh <box> bash -s -- <version> <target-sha> < scripts/release/remote_deploy.sh
#
# Runs the deploy.sh that the TARGET tag ships (bash must parse that version),
# without moving the checkout itself: only deploy.sh does that, under the lock
# backup.sh also takes. The run is DETACHED from this session, so a dropped ssh
# connection (job timeout, cancel) cannot kill it mid-pull or mid-up: a non-pty
# session sends the command no signal, and it would otherwise die of SIGPIPE at
# its next write. This session only follows the log and relays the status.
#
# The env names handed to deploy.sh are a FROZEN CROSS-VERSION CONTRACT: this
# file comes from master, the deploy.sh it runs from an older release tag.
set -euo pipefail

APP_DIR=/opt/libli
STATE_DIR=/var/lib/libli-deploy
LOG_DIR=/var/log/libli-deploy
PID_WAIT_SECONDS=30

# A rollback to a release whose deploy.sh predates a variable this script
# passes would silently drop it, so refuse instead.
REQUIRED_VARS="LIBLI_DEPLOY_REF LIBLI_DEPLOY_EXPECT_SHA LIBLI_DEPLOY_SKIP_FETCH"

main() {
  local version=${1:-} target_sha=${2:-}
  local script var status pidf log pid rc i
  [[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "!! version is not vX.Y.Z" >&2; exit 1; }
  [[ $target_sha =~ ^[0-9a-f]{40}$ ]] || { echo "!! target sha is not 40 hex" >&2; exit 1; }

  cd "$APP_DIR"
  # Neither exists on a freshly provisioned box.
  mkdir -p -m 700 "$STATE_DIR" "$LOG_DIR"
  # Status/pid files left by a session that dropped before collecting them.
  find "$STATE_DIR" -maxdepth 1 -type f -mmin +60 -delete
  # Deploy logs name the school's domain -- an unmasked copy on the box, so
  # keep only the newest 19 before adding this run's (at most 20 exist).
  find "$LOG_DIR" -maxdepth 1 -type f -name '*.log' -printf '%T@ %p\n' \
    | sort -rn | tail -n +20 | cut -d' ' -f2- | xargs -r rm -f --

  script="$(mktemp)"
  if ! git show "refs/tags/$version:deploy.sh" > "$script" 2> /dev/null; then
    rm -f "$script"
    echo "!! no deploy.sh at $version in the box's clone; refusing" >&2
    exit 1
  fi
  for var in $REQUIRED_VARS; do
    if ! grep -q "$var" "$script"; then
      rm -f "$script"
      echo "!! the deploy.sh at $version does not know $var; refusing (it predates this machinery)" >&2
      exit 1
    fi
  done

  # Unique paths, created by the wrapper, not here: an absent status file is
  # how a run that died without recording one is recognised.
  status="$(mktemp "$STATE_DIR/status.XXXXXX")"
  pidf="$(mktemp "$STATE_DIR/pid.XXXXXX")"
  rm -f "$status" "$pidf"
  # Created BEFORE the run starts, so the follower below never races a missing
  # file (plain `tail -f` exits at once on one).
  log="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ)-$version.log"
  : > "$log"

  # Everything the wrapper needs arrives as POSITIONAL ARGUMENTS: a
  # single-quoted body cannot see this shell's unexported variables. No fd is
  # shared with the session: this script itself is on the session's stdin, so
  # an inherited stdin would let any child swallow the rest of it, and an
  # inherited stdout both holds sshd's session open and brings back SIGPIPE.
  # The wrapper's own pid ($$) is what the follower waits on -- never $! of
  # setsid, which forks when its caller leads a process group.
  setsid nohup bash -c '
    echo "$$" > "$4"
    LIBLI_DEPLOY_REF="$2" LIBLI_DEPLOY_EXPECT_SHA="$3" LIBLI_DEPLOY_SKIP_FETCH=1 bash "$1"
    rc=$?
    rm -f "$1"
    echo "$rc" > "$5.tmp" && mv "$5.tmp" "$5"
  ' remote-deploy-wrapper "$script" "$version" "$target_sha" "$pidf" "$status" \
    < /dev/null >> "$log" 2>&1 &

  i=0
  until [ -s "$pidf" ]; do
    i=$((i + 1))
    if [ "$i" -gt $((PID_WAIT_SECONDS * 10)) ]; then
      # The temp script is deliberately left in place: a late-starting wrapper
      # still needs it, and removes it itself when done. If the wrapper never
      # starts, one small file stays in /tmp -- accepted.
      echo "!! the detached run has not reported its pid after ${PID_WAIT_SECONDS} s -- it may still start; check the box's LIBLI_IMAGE_TAG and the deploy log $log" >&2
      exit 1
    fi
    sleep 0.1
  done
  pid="$(head -n 1 "$pidf")"

  tail -n +1 --pid="$pid" -f "$log"

  rm -f "$pidf"
  if [ ! -s "$status" ]; then
    echo "!! the detached run recorded no status; check the box's LIBLI_IMAGE_TAG and the deploy log $log" >&2
    exit 1
  fi
  rc="$(head -n 1 "$status")"
  rm -f "$status"
  exit "$rc"
}

main "$@"; exit
```

- [ ] **Step 4: Run the tests** (Linux / container as in Step 2)
Expected: all PASS.

- [ ] **Step 5: Falsify** — each docstring mutant, applied by hand, one at a time, in the Linux run. Revert by hand. For each, record WHICH assertion went red — it must be the one the docstring names. One known soft spot: `test_every_early_line_is_shown` goes red under its mutant only if the fake writes its 40 lines before `tail` attaches (likely — the session polls for the pid every 0.1 s — but not forced); a green mutant there means a timing gap, and the report must say so rather than call the test proven.

- [ ] **Step 6: Commit**

```bash
git add scripts/release/remote_deploy.sh tests/test_release_remote_deploy.py
git commit -m "feat(release): detached on-box deploy bootstrap"
```

---

### Task 7: Canary guard

**Files:**
- Create: `scripts/release/_release_common.py`
- Create: `scripts/release/canary_guard.py`
- Test: `tests/test_release_canary_guard.py`

**Interfaces:**
- Produces: `_release_common.Refuse(Exception)`, `refuse_and_exit(message)` (prints `refuse: <message>` to stderr, appends `**refuse: …**` to `$GITHUB_STEP_SUMMARY` when set, exits 1), `run_main(fn)`, `git(*args) -> subprocess.CompletedProcess` (cwd, never raises). Tasks 8–10 import these.
- Produces: `python3 scripts/release/canary_guard.py <commit> [<run-id>]` → stdout the run id, exit 0; or a refusal. Importable functions: `is_master_deploy(run: dict, commit: str) -> bool`, `deploy_job_succeeded(jobs: list[dict]) -> bool`, `check(commit: str, run_id: str | None = None) -> str`. The `gh` command is `gh` unless `LIBLI_GH` names another (a shlex-split command line). Repo from `GITHUB_REPOSITORY`.
- Consumes: D9 (Task 4) for soundness — documented in the module docstring.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release_canary_guard.py`:

```python
"""scripts/release/canary_guard.py -- D2's guard (spec §4)."""

import json
import os
import shlex
import subprocess
import sys

import pytest

from tests.release_harness import ROOT, commit_all, git, init_repo, posix, write

GUARD = ROOT / "scripts/release/canary_guard.py"
REPO = "o/r"

FAKE_GH = """
import json, os, sys
responses = json.load(open(os.environ["FAKE_GH_RESPONSES"], encoding="utf-8"))
path = sys.argv[2]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as fh:
    fh.write(path + "\\n")
body = responses.get(path.split("?")[0], 404)
if body == 404:
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)
print(json.dumps(body))
"""


def run(sha, run_id, head_branch="master", event="push", path=".github/workflows/deploy.yml"):
    return {"id": run_id, "head_sha": sha, "head_branch": head_branch, "event": event,
            "path": path, "created_at": f"2026-09-27T10:00:{run_id % 60:02d}Z"}


def job(conclusion, name="deploy"):
    return {"name": name, "conclusion": conclusion}


@pytest.fixture
def repo(tmp_path):
    r = init_repo(tmp_path / "r")
    write(r / "a", "a\n")
    on_master = commit_all(r, "on master")
    git(r, "update-ref", "refs/remotes/origin/master", on_master)
    git(r, "checkout", "-q", "-b", "side")
    write(r / "b", "b\n")
    off_master = commit_all(r, "off master")
    git(r, "checkout", "-q", "master")
    return r, on_master, off_master


def _guard(tmp_path, repo_dir, responses, *args):
    stub = tmp_path / "fake_gh.py"
    write(stub, FAKE_GH)
    resp = tmp_path / "responses.json"
    write(resp, json.dumps(responses))
    log = tmp_path / "gh.log"
    write(log, "")
    env = dict(
        os.environ,
        LIBLI_GH=shlex.join([posix(sys.executable), posix(stub)]),
        FAKE_GH_RESPONSES=str(resp),
        FAKE_GH_LOG=str(log),
        GITHUB_REPOSITORY=REPO,
    )
    env.pop("GITHUB_STEP_SUMMARY", None)
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(GUARD), *args], cwd=repo_dir, capture_output=True, text=True, env=env
    )
    return result, log.read_text(encoding="utf-8")


LIST = f"repos/{REPO}/actions/workflows/deploy.yml/runs"


def RUN(i):
    return f"repos/{REPO}/actions/runs/{i}"


def JOBS(i):
    return f"repos/{REPO}/actions/runs/{i}/jobs"


def test_listing_finds_a_green_master_push(tmp_path, repo):
    r, sha, _ = repo
    result, log = _guard(tmp_path, r, {
        LIST: {"workflow_runs": [run(sha, 7)]},
        JOBS(7): {"jobs": [job("success"), job("success", "publish")]},
    }, sha)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "7"
    assert "filter=all" in log


def test_listing_refuses_a_red_deploy_job(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {
        LIST: {"workflow_runs": [run(sha, 7)]},
        JOBS(7): {"jobs": [job("failure")]},
    }, sha)
    assert result.returncode != 0
    assert "no successful deploy" in result.stderr


def test_listing_refuses_when_there_is_no_run(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {LIST: {"workflow_runs": []}}, sha)
    assert result.returncode != 0
    assert "no master deploy run" in result.stderr


def test_a_commit_not_on_master_is_refused(tmp_path, repo):
    """Mutant: drop the merge-base check."""
    r, _, off = repo
    result, _ = _guard(tmp_path, r, {
        LIST: {"workflow_runs": [run(off, 7)]},
        JOBS(7): {"jobs": [job("success")]},
    }, off)
    assert result.returncode != 0
    assert "not on master" in result.stderr


def test_a_skipped_jobs_success_run_from_a_feature_dispatch_is_refused(tmp_path, repo):
    """The run concludes `success` with every job skipped. Two independent
    defences stop it -- `head_branch == master` and the deploy JOB's
    conclusion -- so no single mutant turns this red. Mutant (both at once):
    drop the head_branch check AND read the run's own conclusion."""
    r, sha, _ = repo
    feature = dict(run(sha, 7, head_branch="feature", event="workflow_dispatch"), conclusion="success")
    result, _ = _guard(tmp_path, r, {
        LIST: {"workflow_runs": [feature]},
        JOBS(7): {"jobs": [job("skipped")]},
    }, sha)
    assert result.returncode != 0
    assert "no master deploy run" in result.stderr


def test_by_id_passes_for_a_matching_run(tmp_path, repo):
    r, sha, _ = repo
    result, log = _guard(tmp_path, r, {
        RUN(9): run(sha, 9),
        JOBS(9): {"jobs": [job("success")]},
    }, sha, "9")
    assert result.returncode == 0, result.stderr
    assert "filter=all" in log


def test_by_id_refuses_a_run_for_another_commit(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {
        RUN(9): run("f" * 40, 9),
        JOBS(9): {"jobs": [job("success")]},
    }, sha, "9")
    assert result.returncode != 0
    assert "is not a master deploy" in result.stderr


def test_by_id_refuses_a_run_of_another_workflow(tmp_path, repo):
    """deploy-release.yml also has a job named `deploy` that runs as a master
    workflow_dispatch. Mutant: drop the `path` check."""
    r, sha, _ = repo
    other = run(sha, 9, event="workflow_dispatch", path=".github/workflows/deploy-release.yml")
    result, _ = _guard(tmp_path, r, {RUN(9): other, JOBS(9): {"jobs": [job("success")]}}, sha, "9")
    assert result.returncode != 0
    assert "is not a master deploy" in result.stderr


def test_a_404_on_the_listing_is_a_refusal_not_a_traceback(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {}, sha)
    assert result.returncode == 1
    assert "refuse: the deploy.yml runs listing was not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_by_id_404_is_its_own_refusal(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {}, sha, "9")
    assert result.returncode != 0
    assert "canary run 9 no longer exists" in result.stderr


@pytest.mark.parametrize("by_id", [False, True])
def test_a_later_failed_rerun_does_not_undo_a_green_attempt(tmp_path, repo, by_id):
    """Jobs are read with filter=all; any attempt's green deploy job counts.
    Mutant: require every deploy job entry to be green (or use filter=latest)."""
    r, sha, _ = repo
    responses = {
        LIST: {"workflow_runs": [run(sha, 7)]},
        RUN(7): run(sha, 7),
        JOBS(7): {"jobs": [job("success"), job("failure")]},
    }
    args = (sha, "7") if by_id else (sha,)
    result, _ = _guard(tmp_path, r, responses, *args)
    assert result.returncode == 0, result.stderr


def test_refusals_reach_the_step_summary(tmp_path, repo):
    r, sha, _ = repo
    summary = tmp_path / "summary.md"
    write(summary, "")
    stub = tmp_path / "fake_gh.py"
    write(stub, FAKE_GH)
    resp = tmp_path / "responses.json"
    write(resp, "{}")
    env = dict(
        os.environ,
        LIBLI_GH=shlex.join([posix(sys.executable), posix(stub)]),
        FAKE_GH_RESPONSES=str(resp),
        FAKE_GH_LOG=str(tmp_path / "log"),
        GITHUB_REPOSITORY=REPO,
        GITHUB_STEP_SUMMARY=str(summary),
    )
    subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(GUARD), sha, "9"], cwd=r, capture_output=True, text=True, env=env
    )
    assert "refuse: canary run 9 no longer exists" in summary.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_release_canary_guard.py`
Expected: FAIL — the script does not exist.

- [ ] **Step 3: Write the shared helpers**

Create `scripts/release/_release_common.py`:

```python
"""Helpers shared by the runner-side release tools (B2).

A refusal is ONE line that is safe to print into a (possibly public) Actions
log: never a host, a domain, a school name or a line of .env.production.
"""

import os
import subprocess
import sys


class Refuse(Exception):
    """Stop, with a message safe to print."""


def refuse_and_exit(message):
    line = f"refuse: {message}"
    print(line, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"**{line}**\n")
    sys.exit(1)


def run_main(fn):
    try:
        fn()
    except Refuse as exc:
        refuse_and_exit(str(exc))


def git(*args):
    """git in the current directory. Returns the CompletedProcess; never raises."""
    return subprocess.run(  # noqa: S603 -- fixed argv
        ["git", *args],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
    )
```

- [ ] **Step 4: Write the guard**

Create `scripts/release/canary_guard.py`:

```python
#!/usr/bin/env python3
"""Canary guard (B2, spec §4): refuse unless libli.pl deployed <commit> green.

    canary_guard.py <commit>            Cut release: find the run; prints its id
    canary_guard.py <commit> <run-id>   Deploy release: check that exact run

<commit> is a 40-hex COMMIT sha -- callers peel tags first.

"libli.pl ran X" is measured as: a deploy.yml run for X, on master, from a push
or a dispatch, whose `deploy` JOB succeeded in any attempt. The run's own
conclusion is not enough (a feature-branch dispatch skips every job and still
concludes `success`), and the check is only sound because of D9: deploy.yml
passes LIBLI_DEPLOY_EXPECT_SHA, so a green deploy job can only have deployed
its own head_sha.

Runs `gh` (or the command in LIBLI_GH), which needs GH_TOKEN in Actions.
"""

import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse, git, run_main  # noqa: E402

WORKFLOW_PATH = ".github/workflows/deploy.yml"
SHA_RE = re.compile(r"[0-9a-f]{40}")


class NotFound(Exception):
    pass


def repo():
    return os.environ.get("GITHUB_REPOSITORY", "krzyssikora/libli")


def gh_api(path):
    cmd = shlex.split(os.environ.get("LIBLI_GH", "gh")) + ["api", path]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        if "404" in result.stderr or "Not Found" in result.stderr:
            raise NotFound(path)
        raise Refuse(f"the GitHub API call for {path.split('?')[0]} failed")
    return json.loads(result.stdout)


def is_master_deploy(run, commit):
    return (
        str(run.get("path", "")).split("@")[0] == WORKFLOW_PATH
        and run.get("head_sha") == commit
        and run.get("head_branch") == "master"
        and run.get("event") in ("push", "workflow_dispatch")
    )


def deploy_job_succeeded(jobs):
    return any(j.get("name") == "deploy" and j.get("conclusion") == "success" for j in jobs)


def jobs_for(run_id):
    return gh_api(f"repos/{repo()}/actions/runs/{run_id}/jobs?filter=all&per_page=100").get(
        "jobs", []
    )


def check(commit, run_id=None):
    if not SHA_RE.fullmatch(commit):
        raise Refuse("the commit must be a full 40-hex sha")
    if git("merge-base", "--is-ancestor", commit, "origin/master").returncode != 0:
        raise Refuse(f"{commit} is not on master")
    if run_id is None:
        try:
            runs = gh_api(
                f"repos/{repo()}/actions/workflows/deploy.yml/runs?head_sha={commit}&per_page=100"
            ).get("workflow_runs", [])
        except NotFound:
            raise Refuse("the deploy.yml runs listing was not found") from None
        candidates = [r for r in runs if is_master_deploy(r, commit)]
        if not candidates:
            raise Refuse(
                f"no master deploy run of {commit} (a commit inside a multi-commit "
                "push never gets its own run -- tag the tip instead)"
            )
        for run in sorted(candidates, key=lambda r: r.get("created_at", ""), reverse=True):
            try:
                jobs = jobs_for(run["id"])
            except NotFound:
                continue  # deleted between the listing and this call
            if deploy_job_succeeded(jobs):
                return str(run["id"])
        raise Refuse(f"libli.pl has no successful deploy of {commit}")
    if not re.fullmatch(r"[0-9]+", run_id):
        raise Refuse("the canary run id must be a number")
    try:
        run = gh_api(f"repos/{repo()}/actions/runs/{run_id}")
        jobs = jobs_for(run_id)
    except NotFound:
        raise Refuse(f"canary run {run_id} no longer exists") from None
    if not is_master_deploy(run, commit):
        raise Refuse(f"run {run_id} is not a master deploy of {commit}")
    if not deploy_job_succeeded(jobs):
        raise Refuse(f"libli.pl has no successful deploy of {commit} (run {run_id})")
    return run_id


def main():
    args = sys.argv[1:]
    if len(args) not in (1, 2):
        raise Refuse("usage: canary_guard.py <commit> [<run-id>]")
    print(check(*args))


if __name__ == "__main__":
    run_main(main)
```

- [ ] **Step 5: Run the tests** — `uv run pytest tests/test_release_canary_guard.py` → all PASS.

- [ ] **Step 6: Falsify** — each docstring mutant (the feature-dispatch one is a double mutant, as its docstring says; each half alone stays green, and the report should say so). Revert by hand.

- [ ] **Step 7: Commit**

```bash
git add scripts/release/_release_common.py scripts/release/canary_guard.py tests/test_release_canary_guard.py
git commit -m "feat(release): canary guard -- a release only of what libli.pl ran green"
```

---

### Task 8: Release checks (resolve, tag, containment)

**Files:**
- Create: `scripts/release/release_checks.py`
- Test: `tests/test_release_checks.py`

**Interfaces:**
- Consumes: `_release_common` (Task 7).
- Produces: `release_checks.py resolve <version> <commit-ish>` → `sha=<40hex>`; `release_checks.py tag <version>` → `target_sha=<40hex>\nrun_id=<digits>`; `release_checks.py containment <sha>` → no output, exit 0. Stdout lines are `key=value` so workflows append them to `$GITHUB_OUTPUT`. Importable: `check_version(v)`, `resolve(version, commitish) -> dict`, `inspect_tag(version) -> dict`, `containment(sha) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release_checks.py`:

```python
"""scripts/release/release_checks.py -- version, tag and B2-containment checks."""

import subprocess
import sys

import pytest

from tests.release_harness import ROOT, commit_all, git, init_repo, write

CHECKS = ROOT / "scripts/release/release_checks.py"


def _run(repo, *args):
    return subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(CHECKS), *args], cwd=repo, capture_output=True, text=True
    )


def _b2_tree(repo, *, ref=True, expect=True, guard=True):
    body = "#!/usr/bin/env bash\n"
    body += "# LIBLI_DEPLOY_REF\n" if ref else ""
    body += "# LIBLI_DEPLOY_EXPECT_SHA\n" if expect else ""
    write(repo / "deploy.sh", body)
    if guard:
        write(repo / "scripts/release/migration_guard.sh", "#!/usr/bin/env bash\n")


@pytest.fixture
def repo(tmp_path):
    r = init_repo(tmp_path / "r")
    _b2_tree(r)
    sha = commit_all(r, "b2")
    return r, sha


@pytest.mark.parametrize("bad", [" v1.0.0", "v1.0.0 ", "V1.0.0", "1.0.0", "v1.0", "v1.0.0-rc1"])
def test_a_malformed_version_is_refused_with_the_format_message(repo, bad):
    """Review focus 2."""
    r, sha = repo
    for args in (("resolve", bad, sha), ("tag", bad)):
        result = _run(r, *args)
        assert result.returncode != 0
        assert "vX.Y.Z" in result.stderr


def test_resolve_turns_a_short_sha_into_the_full_one(repo):
    r, sha = repo
    result = _run(r, "resolve", "v1.0.0", sha[:8])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"sha={sha}"


def test_resolve_refuses_an_existing_tag(repo):
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "x")
    result = _run(r, "resolve", "v1.0.0", sha)
    assert result.returncode != 0
    assert "already exists" in result.stderr


def test_tag_peels_an_annotated_tag_to_its_commit(repo):
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "Release v1.0.0", "-m", "canary-run: 42")
    result = _run(r, "tag", "v1.0.0")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"target_sha={sha}", "run_id=42"]


def test_a_lightweight_tag_is_refused_even_if_its_commit_says_canary_run(tmp_path):
    """Mutant: drop the cat-file -t check (%(contents) then reads the commit)."""
    r = init_repo(tmp_path / "r")
    _b2_tree(r)
    sha = commit_all(r, "canary-run: 42")
    git(r, "tag", "v1.0.0", sha)
    result = _run(r, "tag", "v1.0.0")
    assert result.returncode != 0
    assert "lightweight" in result.stderr


def test_an_annotated_tag_without_the_line_is_refused(repo):
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "Release v1.0.0")
    result = _run(r, "tag", "v1.0.0")
    assert result.returncode != 0
    assert "no canary-run line" in result.stderr


def test_two_canary_run_lines_are_refused_and_trailing_space_is_tolerated(repo):
    """Review focus 5."""
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "R", "-m", "canary-run: 1\ncanary-run: 2")
    assert "more than one" in _run(r, "tag", "v1.0.0").stderr
    # --cleanup=verbatim: git tag's default cleanup strips trailing whitespace,
    # which would leave the .rstrip() in inspect_tag untested.
    git(r, "tag", "--cleanup=verbatim", "-a", "v1.0.1", sha, "-m", "R\n\ncanary-run: 7   ")
    result = _run(r, "tag", "v1.0.1")
    assert result.returncode == 0, result.stderr
    assert "run_id=7" in result.stdout


def test_a_missing_tag_is_refused(repo):
    r, sha = repo
    result = _run(r, "tag", "v9.9.9")
    assert result.returncode != 0
    assert "no tag v9.9.9" in result.stderr


def test_containment_passes_a_b2_commit(repo):
    r, sha = repo
    assert _run(r, "containment", sha).returncode == 0


@pytest.mark.parametrize(
    "missing,kw",
    [
        ("LIBLI_DEPLOY_REF", {"ref": False}),
        ("LIBLI_DEPLOY_EXPECT_SHA", {"expect": False}),
        ("migration_guard.sh", {"guard": False}),
    ],
)
def test_containment_refuses_a_pre_b2_commit(tmp_path, missing, kw):
    """Mutants: drop each of the three checks."""
    r = init_repo(tmp_path / "r")
    _b2_tree(r, **kw)
    sha = commit_all(r, "old")
    result = _run(r, "containment", sha)
    assert result.returncode != 0
    assert missing in result.stderr
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_release_checks.py` → FAIL (script missing).

- [ ] **Step 3: Write the script**

Create `scripts/release/release_checks.py`:

```python
#!/usr/bin/env python3
"""Release checks for B2 (spec §1, §2).

    release_checks.py resolve <version> <commit-ish>   -> sha=<40 hex>
    release_checks.py tag <version>                    -> target_sha=..., run_id=...
    release_checks.py containment <sha>                -> (nothing; exit 0)

Output lines are key=value, for $GITHUB_OUTPUT. Runs git in the current
directory, which must be a full clone (fetch-depth: 0) with tags.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse, git, run_main  # noqa: E402

VERSION_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
CANARY_RE = re.compile(r"canary-run: ([0-9]+)")
B2_MARKERS = ("LIBLI_DEPLOY_REF", "LIBLI_DEPLOY_EXPECT_SHA")


def check_version(version):
    if not VERSION_RE.fullmatch(version):
        raise Refuse("version must be vX.Y.Z (e.g. v1.0.0), with no spaces")


def _tag_exists(version):
    return git("rev-parse", "--verify", "--quiet", f"refs/tags/{version}").returncode == 0


def resolve(version, commitish):
    check_version(version)
    if _tag_exists(version):
        raise Refuse(f"tag {version} already exists")
    result = git("rev-parse", "--verify", "--quiet", f"{commitish}^{{commit}}")
    if result.returncode != 0:
        raise Refuse(f"{commitish} does not resolve to a commit")
    return {"sha": result.stdout.strip()}


def inspect_tag(version):
    check_version(version)
    if not _tag_exists(version):
        raise Refuse(f"no tag {version}")
    if git("cat-file", "-t", f"refs/tags/{version}").stdout.strip() != "tag":
        raise Refuse(f"{version} is a lightweight tag; releases are annotated tags made by Cut release")
    contents = git("tag", "-l", "--format=%(contents)", version).stdout
    ids = [m.group(1) for ln in contents.splitlines() if (m := CANARY_RE.fullmatch(ln.rstrip()))]
    if not ids:
        raise Refuse(f"tag {version} has no canary-run line")
    if len(ids) > 1:
        raise Refuse(f"tag {version} has more than one canary-run line")
    target = git("rev-parse", "--verify", f"{version}^{{commit}}").stdout.strip()
    return {"target_sha": target, "run_id": ids[0]}


def containment(sha):
    for marker in B2_MARKERS:
        if git("grep", "-q", marker, sha, "--", "deploy.sh").returncode != 0:
            raise Refuse(f"the deploy.sh at {sha} predates B2 (no {marker}); release a later commit")
    if git("cat-file", "-e", f"{sha}:scripts/release/migration_guard.sh").returncode != 0:
        raise Refuse(f"{sha} has no scripts/release/migration_guard.sh; release a later commit")


def main():
    args = sys.argv[1:]
    if args[:1] == ["resolve"] and len(args) == 3:
        out = resolve(args[1], args[2])
    elif args[:1] == ["tag"] and len(args) == 2:
        out = inspect_tag(args[1])
    elif args[:1] == ["containment"] and len(args) == 2:
        containment(args[1])
        return
    else:
        raise Refuse("usage: release_checks.py resolve <v> <commit> | tag <v> | containment <sha>")
    for key, value in out.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    run_main(main)
```

- [ ] **Step 4: Run the tests** → all PASS.
- [ ] **Step 5: Falsify** — each docstring mutant. Revert by hand.
- [ ] **Step 6: Commit**

```bash
git add scripts/release/release_checks.py tests/test_release_checks.py
git commit -m "feat(release): version, annotated-tag and B2-containment checks"
```

---

### Task 9: School inventory

**Files:**
- Create: `scripts/release/inventory.py`
- Test: `tests/test_release_inventory.py`

**Interfaces:**
- Consumes: `_release_common` (Task 7). Reads the secret from env var `SCHOOL_HOSTS`.
- Produces: `inventory.py plan <school> --output <file>` → prints `::add-mask::<v>` for every host and domain, appends `codes=<json list>` to `<file>`. `inventory.py entry <code> --dir <dir>` → prints `::add-mask::` for that entry's host and domain FIRST, then writes `<dir>/host` (`<host>\n`) and `<dir>/known_hosts` (`<host> <host_key>\n`). Importable: `load(raw) -> dict`, `resolve(inventory, school) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release_inventory.py`:

```python
"""scripts/release/inventory.py -- SCHOOL_HOSTS (spec §6)."""

import json
import os
import subprocess
import sys

import pytest

from tests.release_harness import ROOT

INV = ROOT / "scripts/release/inventory.py"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def entry(host="203.0.113.10", domain="szkola.pl", host_key=KEY):
    return {"host": host, "domain": domain, "host_key": host_key}


def _run(raw, *args):
    env = dict(os.environ)
    env["SCHOOL_HOSTS"] = raw
    return subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(INV), *args], capture_output=True, text=True, env=env
    )


def test_all_resolves_every_code_sorted_and_masks_every_value(tmp_path):
    """Review focus 4."""
    raw = json.dumps({"school-02": entry(host="h2.example"), "school-01": entry(domain="lo1.pl")})
    out = tmp_path / "out"
    result = _run(raw, "plan", "all", "--output", str(out))
    assert result.returncode == 0, result.stderr
    assert out.read_text().strip() == 'codes=["school-01", "school-02"]'
    for value in ("h2.example", "lo1.pl", "203.0.113.10", "szkola.pl"):
        assert f"::add-mask::{value}" in result.stdout


def test_a_single_entry_and_all_is_a_matrix_of_one(tmp_path):
    out = tmp_path / "out"
    assert _run(json.dumps({"school-01": entry()}), "plan", "all", "--output", str(out)).returncode == 0
    assert out.read_text().strip() == 'codes=["school-01"]'


def test_a_single_code_resolves_to_itself(tmp_path):
    out = tmp_path / "out"
    raw = json.dumps({"school-01": entry(), "school-02": entry()})
    assert _run(raw, "plan", "school-02", "--output", str(out)).returncode == 0
    assert out.read_text().strip() == 'codes=["school-02"]'


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("not json", "not valid JSON"),
        ("[]", "JSON object"),
        ("{}", "no schools"),
        (json.dumps({"liceum-krakow": entry()}), "school-NN"),
        (json.dumps({"school-01": {"host": "h", "host_key": KEY}}), "school-01: domain is empty"),
        (json.dumps({"school-01": entry(host="")}), "school-01: host is empty"),
        (json.dumps({"school-01": entry(host="bad host")}), "school-01: host is malformed"),
        (json.dumps({"school-01": entry(host="-oProxyCommand=x")}), "school-01: host is malformed"),
        (json.dumps({"school-01": entry(domain="liceum,krakow.pl")}), "school-01: domain is malformed"),
        (json.dumps({"school-01": entry(host_key="AAAA")}), "school-01: host_key is malformed"),
    ],
)
def test_malformed_inventories_are_refused_without_echoing_values(tmp_path, raw, reason):
    """Mutant: include the offending value in the message."""
    result = _run(raw, "plan", "all", "--output", str(tmp_path / "out"))
    assert result.returncode != 0
    assert reason in result.stderr
    for leaked in ("liceum", "bad host", "ProxyCommand", "AAAA", "203.0.113.10", "szkola"):
        assert leaked not in result.stderr + result.stdout


def test_an_unknown_code_is_refused(tmp_path):
    result = _run(json.dumps({"school-01": entry()}), "plan", "school-09", "--output", str(tmp_path / "o"))
    assert result.returncode != 0
    assert "unknown school code" in result.stderr


def test_entry_masks_first_then_writes_the_files(tmp_path):
    raw = json.dumps({"school-01": entry(host="h1.example", domain="lo1.pl")})
    d = tmp_path / "box"
    result = _run(raw, "entry", "school-01", "--dir", str(d))
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[:2] == ["::add-mask::h1.example", "::add-mask::lo1.pl"]
    assert (d / "host").read_text() == "h1.example\n"
    assert (d / "known_hosts").read_text() == f"h1.example {KEY}\n"


def test_an_ipv6_host_is_accepted(tmp_path):
    """Review focus 3."""
    raw = json.dumps({"school-01": entry(host="2001:db8::10")})
    d = tmp_path / "box"
    result = _run(raw, "entry", "school-01", "--dir", str(d))
    assert result.returncode == 0, result.stderr
    assert (d / "known_hosts").read_text() == f"2001:db8::10 {KEY}\n"
```

- [ ] **Step 2: Run to verify they fail** — script missing.

- [ ] **Step 3: Write the script**

Create `scripts/release/inventory.py`:

```python
#!/usr/bin/env python3
"""The school inventory (B2, spec §6), read from the SCHOOL_HOSTS secret:

    {"school-01": {"host": "<ip-or-name>", "host_key": "ssh-ed25519 AAAA...",
                   "domain": "<registrable domain>"}, ...}

    inventory.py plan <school|all> --output <file>   masks all; codes=<json>
    inventory.py entry <code> --dir <dir>            masks one; host, known_hosts

GitHub masks the whole secret, not the values inside it, and the plan job runs
before any mask exists -- so no message here ever prints a field value, a key
that is not a school code, or the school argument. Masks are printed before
anything is written anywhere.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse, run_main  # noqa: E402

CODE_RE = re.compile(r"school-[0-9]{2}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]*")
KEY_RE = re.compile(r"(ssh-ed25519|ecdsa-sha2-nistp(256|384|521)|ssh-rsa) [A-Za-z0-9+/]+={0,2}")
FIELDS = ("host", "host_key", "domain")


def load(raw):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise Refuse("SCHOOL_HOSTS is not valid JSON") from None
    if not isinstance(data, dict):
        raise Refuse("SCHOOL_HOSTS must be a JSON object of school code -> entry")
    for code, item in data.items():
        if not CODE_RE.fullmatch(code):
            raise Refuse("an inventory key is not of the form school-NN")
        if not isinstance(item, dict):
            raise Refuse(f"{code}: the entry is not an object")
        for field in FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value:
                raise Refuse(f"{code}: {field} is empty")
            pattern = KEY_RE if field == "host_key" else NAME_RE
            if not pattern.fullmatch(value):
                raise Refuse(f"{code}: {field} is malformed")
    return data


def resolve(inventory, school):
    if school == "all":
        codes = sorted(inventory)
    elif school in inventory:
        codes = [school]
    else:
        raise Refuse("unknown school code (use a key of SCHOOL_HOSTS, or all)")
    if not codes:
        raise Refuse("no schools to deploy to (SCHOOL_HOSTS is empty)")
    return codes


def _mask(item):
    print(f"::add-mask::{item['host']}", flush=True)
    print(f"::add-mask::{item['domain']}", flush=True)


def _option(args, name):
    if name not in args or args.index(name) + 1 >= len(args):
        raise Refuse(f"missing {name}")
    return args[args.index(name) + 1]


def main():
    args = sys.argv[1:]
    inventory = load(os.environ.get("SCHOOL_HOSTS", ""))
    if args[:1] == ["plan"] and len(args) == 4:
        codes = resolve(inventory, args[1])
        for item in inventory.values():
            _mask(item)
        with open(_option(args, "--output"), "a", encoding="utf-8") as fh:
            fh.write(f"codes={json.dumps(codes)}\n")
    elif args[:1] == ["entry"] and len(args) == 4:
        code = args[1]
        if code not in inventory:
            raise Refuse("unknown school code")
        item = inventory[code]
        _mask(item)
        target = Path(_option(args, "--dir"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "host").write_bytes(f"{item['host']}\n".encode())
        (target / "known_hosts").write_bytes(f"{item['host']} {item['host_key']}\n".encode())
    else:
        raise Refuse("usage: inventory.py plan <school|all> --output <f> | entry <code> --dir <d>")


if __name__ == "__main__":
    run_main(main)
```

- [ ] **Step 4: Run the tests** → all PASS.
- [ ] **Step 5: Falsify** — the docstring mutant; delete the `_mask(item)` call in `entry` → `test_entry_masks_first…` RED; delete the mask loop in `plan` → `test_all_resolves…` RED. Revert by hand.
- [ ] **Step 6: Commit**

```bash
git add scripts/release/inventory.py tests/test_release_inventory.py
git commit -m "feat(release): school inventory with value-free refusals and masks"
```

---

### Task 10: Outcome records and the run report

**Files:**
- Create: `scripts/release/report.py`
- Test: `tests/test_release_report.py`

**Interfaces:**
- Consumes: `_release_common` (Task 7).
- Produces: `report.py outcome --code C --attempt N --from F --to V --deploy-outcome O --now-on T` → prints one JSON object `{"code","run_attempt","from","to","result","now_on"}` (`result` = `success` iff O == `success`, else `failure`). `report.py summarise --plan-result R --codes JSON --attempt N --dir D --summary FILE` → appends a markdown table to FILE, prints `success` or `fail`. Importable: `outcome(...) -> dict`, `load_outcomes(dir) -> dict`, `verdict(plan_result, codes, attempt, outcomes) -> str`, `table(plan_result, codes, attempt, outcomes) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release_report.py`:

```python
"""scripts/release/report.py -- per-leg outcomes and the run summary (spec §2)."""

import importlib.util
import json
import subprocess
import sys

from tests.release_harness import ROOT, write

SCRIPT = ROOT / "scripts/release/report.py"
sys.path.insert(0, str(SCRIPT.parent))
_spec = importlib.util.spec_from_file_location("report", SCRIPT)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def rec(code, result="success", attempt=1):
    return {"code": code, "run_attempt": attempt, "from": "sha-a", "to": "v1.1.0",
            "result": result, "now_on": "sha-b"}


def test_outcome_derives_result_from_the_deploy_steps_outcome():
    assert report.outcome("school-01", 1, "sha-a", "v1", "success", "sha-b")["result"] == "success"
    for other in ("failure", "skipped", "cancelled", ""):
        assert report.outcome("school-01", 1, "sha-a", "v1", other, "unknown")["result"] == "failure"


def test_all_green_this_attempt_is_success():
    outs = {"school-01": rec("school-01"), "school-02": rec("school-02")}
    assert report.verdict("success", ["school-01", "school-02"], 1, outs) == "success"


def test_a_plan_refusal_is_fail_even_with_no_codes():
    """Otherwise "every planned code succeeded" is vacuously true.
    Mutant: return success when codes is empty."""
    assert report.verdict("failure", [], 1, {}) == "fail"
    assert report.verdict("success", [], 1, {}) == "fail"
    lines = report.table("failure", [], 1, {})
    assert any("plan refused" in ln for ln in lines)


def test_a_missing_artifact_is_a_no_result_fail():
    outs = {"school-01": rec("school-01")}
    assert report.verdict("success", ["school-01", "school-02"], 1, outs) == "fail"
    assert any("school-02" in ln and "no result" in ln
               for ln in report.table("success", ["school-01", "school-02"], 1, outs))


def test_an_earlier_attempts_green_is_marked_and_does_not_count():
    """Mutant: ignore run_attempt in verdict()."""
    outs = {"school-01": rec("school-01", attempt=1)}
    assert report.verdict("success", ["school-01"], 2, outs) == "fail"
    assert any("(attempt 1)" in ln for ln in report.table("success", ["school-01"], 2, outs))


def test_summarise_cli_tolerates_a_missing_outcomes_directory(tmp_path):
    summary = tmp_path / "summary.md"
    write(summary, "")
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(SCRIPT), "summarise", "--plan-result", "failure", "--codes", "",
         "--attempt", "1", "--dir", str(tmp_path / "absent"), "--summary", str(summary)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "fail"
    assert "plan refused" in summary.read_text(encoding="utf-8")


def test_summarise_cli_reads_the_artifacts(tmp_path):
    d = tmp_path / "outcomes"
    write(d / "outcome-school-01.json", json.dumps(rec("school-01")))
    summary = tmp_path / "summary.md"
    write(summary, "")
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(SCRIPT), "summarise", "--plan-result", "success",
         "--codes", '["school-01"]', "--attempt", "1", "--dir", str(d), "--summary", str(summary)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "success"
    assert "school-01" in summary.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify they fail** — script missing.

- [ ] **Step 3: Write the script**

Create `scripts/release/report.py`:

```python
#!/usr/bin/env python3
"""Per-leg outcomes and the Deploy release summary (B2, spec §2).

    report.py outcome --code C --attempt N --from F --to V --deploy-outcome O --now-on T
    report.py summarise --plan-result R --codes JSON --attempt N --dir D --summary FILE

A row from an earlier run attempt is marked "(attempt N)" and never counts
toward success; a planned code with no artifact is "no result"; a plan refusal
(no codes) is always a fail -- otherwise "every planned code succeeded" would
be vacuously true on exactly the runs whose alert matters most.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse, run_main  # noqa: E402


def outcome(code, attempt, frm, to, deploy_outcome, now_on):
    return {
        "code": code,
        "run_attempt": int(attempt),
        "from": frm,
        "to": to,
        "result": "success" if deploy_outcome == "success" else "failure",
        "now_on": now_on,
    }


def load_outcomes(directory):
    found = {}
    path = Path(directory)
    if not path.is_dir():
        return found
    for f in sorted(path.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "code" in data:
            found[data["code"]] = data
    return found


def verdict(plan_result, codes, attempt, outcomes):
    if plan_result != "success" or not codes:
        return "fail"
    for code in codes:
        o = outcomes.get(code)
        if not o or o.get("result") != "success" or int(o.get("run_attempt", 0)) != int(attempt):
            return "fail"
    return "success"


def table(plan_result, codes, attempt, outcomes):
    lines = ["## Deploy release", "", "| School | Result | From | To | Now on |",
             "|---|---|---|---|---|"]
    if plan_result != "success" or not codes:
        lines.append("| — | ❌ plan refused — see the plan job | | | |")
        return lines
    for code in codes:
        o = outcomes.get(code)
        if not o:
            lines.append(f"| {code} | ❌ no result | | | |")
            continue
        mark = "✅" if o.get("result") == "success" else "❌"
        if int(o.get("run_attempt", 0)) != int(attempt):
            mark += f" (attempt {o.get('run_attempt')})"
        lines.append(f"| {code} | {mark} | {o.get('from', '')} | {o.get('to', '')} | {o.get('now_on', '')} |")
    return lines


def _opts(args, required):
    if len(args) % 2:
        raise Refuse("options come in --name value pairs")
    found = {args[i].lstrip("-"): args[i + 1] for i in range(0, len(args), 2)}
    missing = [name for name in required if name not in found]
    if missing:
        raise Refuse(f"missing --{missing[0]}")
    return found


def main():
    args = sys.argv[1:]
    if args[:1] == ["outcome"]:
        o = _opts(args[1:], ("code", "attempt", "from", "to", "deploy-outcome", "now-on"))
        print(json.dumps(outcome(o["code"], o["attempt"], o["from"], o["to"],
                                 o["deploy-outcome"], o["now-on"])))
    elif args[:1] == ["summarise"]:
        o = _opts(args[1:], ("plan-result", "codes", "attempt", "dir", "summary"))
        codes = json.loads(o["codes"]) if o["codes"].strip() else []
        outs = load_outcomes(o["dir"])
        with open(o["summary"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(table(o["plan-result"], codes, o["attempt"], outs)) + "\n")
        print(verdict(o["plan-result"], codes, o["attempt"], outs))
    else:
        raise Refuse("usage: report.py outcome ... | summarise ...")


if __name__ == "__main__":
    run_main(main)
```

- [ ] **Step 4: Run the tests** → all PASS.
- [ ] **Step 5: Falsify** — each docstring mutant. Revert by hand.
- [ ] **Step 6: Commit**

```bash
git add scripts/release/report.py tests/test_release_report.py
git commit -m "feat(release): per-leg outcomes and the run summary verdict"
```

---

### Task 11: ssh helper and the Cut release workflow

**Files:**
- Create: `scripts/release/ssh_box.sh`
- Create: `.github/workflows/cut-release.yml`
- Test: `tests/test_release_workflows.py` (helpers + cut-release + ssh tests; Task 12 appends)

**Interfaces:**
- Consumes: `release_checks.py resolve|containment` (Task 8), `canary_guard.py` (Task 7).
- Produces: `bash scripts/release/ssh_box.sh <dir> <remote command…>` where `<dir>` holds `host`, `known_hosts`, `key` (Task 12 uses it). Test helpers `jobs(text) -> dict[str, list[str]]`, `job_if(block) -> str` (asserts exactly one), `steps(block) -> list[str]`, `step_index(steps, needle) -> int`, `run_blocks(text) -> list[str]` (Task 12 reuses them).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_release_workflows.py`:

```python
"""Wiring guards for the B2 workflows and ssh helper.

Textual, like test_deploy_wiring.py: pyyaml is not a dependency, and every
property here (a key's presence, one step preceding another) survives a regex.
"""

import re

import pytest

from tests.release_harness import ROOT

CUT = ROOT / ".github/workflows/cut-release.yml"
DEPLOY_RELEASE = ROOT / ".github/workflows/deploy-release.yml"
DEPLOY_YML = ROOT / ".github/workflows/deploy.yml"
SSH_BOX = ROOT / "scripts/release/ssh_box.sh"
MASTER = "github.ref == 'refs/heads/master'"
NEW_WORKFLOWS = [CUT]  # Task 12 adds DEPLOY_RELEASE


def jobs(text):
    lines = text.splitlines()
    start = lines.index("jobs:")
    out, name = {}, None
    for ln in lines[start + 1 :]:
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", ln)
        if m:
            name = m.group(1)
            out[name] = []
            continue
        if ln and not ln.startswith(" ") and not ln.startswith("#"):
            break
        if name:
            out[name].append(ln)
    return out


def job_if(block):
    found = [ln[len("    if: ") :] for ln in block if ln.startswith("    if: ")]
    assert len(found) == 1, f"a job must carry exactly one if:, found {found}"
    return found[0]


def steps(block):
    out, cur = [], None
    for ln in block:
        if re.match(r"^      - ", ln):
            cur = [ln]
            out.append(cur)
        elif cur is not None and (ln.startswith("        ") or not ln.strip()):
            cur.append(ln)
        elif ln.strip():
            cur = None
    return ["\n".join(s) for s in out]


def step_index(step_list, needle):
    hits = [i for i, s in enumerate(step_list) if needle in s]
    assert hits, f"no step contains {needle!r}"
    return hits[0]


def run_blocks(text):
    blocks = re.findall(r"run: \|\n((?:\s{10,}.*\n|\s*\n)+)", text)
    blocks += re.findall(r"run: (?!\|)(.+)", text)
    return blocks


def test_job_if_refuses_a_duplicate_key():
    """Two `if:` keys are a duplicate YAML key a parser collapses to the last;
    the helper must fail instead of picking one."""
    with pytest.raises(AssertionError):
        job_if(["    if: always()", f"    if: {MASTER}"])


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_every_job_is_master_gated(path):
    """workflow_dispatch can run the file from any branch, and the guard
    scripts come from that branch. Mutant: drop a job's if:."""
    for name, block in jobs(path.read_text(encoding="utf-8")).items():
        assert MASTER in job_if(block), name


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_nothing_inherits_the_repo_default_permissions(path):
    assert re.search(r"^permissions: \{\}$", path.read_text(encoding="utf-8"), re.MULTILINE)


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_no_expression_inside_a_run_block(path):
    """Values reach the shell through env:. Mutant: `${{ inputs.version }}`
    inlined in a run: line."""
    for block in run_blocks(path.read_text(encoding="utf-8")):
        assert "${{" not in block, block


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_every_canary_guard_call_carries_gh_token(path):
    """gh does not pick up GITHUB_TOKEN by itself. Mutant: drop GH_TOKEN."""
    for block in jobs(path.read_text(encoding="utf-8")).values():
        for step in steps(block):
            if "canary_guard.py" in step:
                assert "GH_TOKEN: ${{ github.token }}" in step, step


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_every_guard_checkout_has_full_history(path):
    """Mutant: drop fetch-depth: 0 -- merge-base then misreports on a depth-1 clone."""
    text = path.read_text(encoding="utf-8")
    for name, block in jobs(text).items():
        joined = "\n".join(block)
        if "actions/checkout" in joined and ("release_checks.py" in joined or "migration_guard.sh" in joined):
            assert "fetch-depth: 0" in joined, name


def test_cut_release_is_a_button_only():
    text = CUT.read_text(encoding="utf-8")
    on = text[text.index("\non:") : text.index("\npermissions:")]
    assert "workflow_dispatch:" in on and "push:" not in on


def test_cut_release_permissions():
    block = jobs(CUT.read_text(encoding="utf-8"))["cut"]
    joined = "\n".join(block)
    assert "      contents: write" in joined and "      actions: read" in joined


def test_cut_release_validates_the_version_before_the_checkout():
    s = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])
    assert step_index(s, "Validate the version") < step_index(s, "actions/checkout")


def test_cut_release_runs_the_checks_in_order_then_tags():
    s = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])
    order = [
        step_index(s, "release_checks.py resolve"),
        step_index(s, "canary_guard.py"),
        step_index(s, "release_checks.py containment"),
        step_index(s, "git tag -a"),
    ]
    assert order == sorted(order)


def test_cut_release_sets_an_identity_and_records_the_canary_run():
    """A fresh runner has no identity; `git tag -a` would die after every
    guard passed. Mutant: drop the git config lines."""
    step = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])[-1]
    assert "git config user.name 'github-actions[bot]'" in step
    assert "41898282+github-actions[bot]@users.noreply.github.com" in step
    assert step.index("git config user.email") < step.index("git tag -a")
    assert '-m "canary-run: $RUN_ID"' in step


def test_the_commit_input_reaches_the_shell_through_env():
    step = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])[
        step_index(steps(jobs(CUT.read_text(encoding="utf-8"))["cut"]), "release_checks.py resolve")
    ]
    assert "COMMIT: ${{ inputs.commit }}" in step


def test_ssh_box_pins_every_option():
    """Mutants: drop any option; add accept-new or StrictHostKeyChecking=no."""
    text = SSH_BOX.read_text(encoding="utf-8")
    for opt in (
        "BatchMode=yes",
        "ConnectTimeout=15",
        "ServerAliveInterval=30",
        "ServerAliveCountMax=4",
        "StrictHostKeyChecking=yes",
        'UserKnownHostsFile="$dir/known_hosts"',
        "IdentitiesOnly=yes",
    ):
        assert f"-o {opt}" in text, opt
    assert "accept-new" not in text and "StrictHostKeyChecking=no" not in text


def test_the_remote_bootstrap_never_moves_the_checkout():
    """Only deploy.sh, under the lock backup.sh also takes, may move HEAD
    (spec §2 step 6). Textual, so it runs everywhere, unlike the setsid tests.
    Mutants: add `git checkout`, `git reset` or `git fetch` to remote_deploy.sh;
    replace the `git show "refs/tags/...` extraction; replace mktemp with a
    fixed path."""
    body = [
        ln
        for ln in (ROOT / "scripts/release/remote_deploy.sh")
        .read_text(encoding="utf-8")
        .splitlines()
        if not ln.lstrip().startswith("#")
    ]
    text = "\n".join(body)
    assert 'git show "refs/tags/$version:deploy.sh"' in text
    assert 'script="$(mktemp)"' in text
    for forbidden in ("git checkout", "git reset", "git fetch"):
        assert forbidden not in text, forbidden
    # The log exists before the run starts, so `tail -f` never meets a missing
    # file. Pinned textually: the session-side `>> "$log"` on the setsid line
    # also creates it before the pid is published, so no executed test can
    # tell the two apart. Mutant: delete the `: > "$log"` line.
    assert text.index(': > "$log"') < text.index("setsid nohup")
    # The followed pid is the wrapper's, read from the pid file -- never $!.
    # In the tests (and on the box) setsid happens not to fork, so $! would
    # pass every executed test; pinned textually. Mutant: `pid=$!`.
    assert 'pid="$(head -n 1 "$pidf")"' in text
    assert "$!" not in text


@pytest.mark.parametrize("name", ["preflight.sh", "remote_deploy.sh", "ssh_box.sh", "migration_guard.sh"])
def test_release_shell_scripts_stop_on_the_first_error(name):
    lines = (ROOT / "scripts/release" / name).read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#!")
    real = next(ln for ln in lines[1:] if ln.strip() and not ln.lstrip().startswith("#"))
    assert real == "set -euo pipefail", real
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_release_workflows.py` → FAIL (files missing).

- [ ] **Step 3: Write ssh_box.sh**

Create `scripts/release/ssh_box.sh`:

```bash
#!/usr/bin/env bash
# The one ssh invocation for release deploys (B2; spec §2). Every option is
# pinned here so no workflow step can quietly drop one:
#   BatchMode, ConnectTimeout, ServerAlive*   fail fast and legibly, never hang
#   StrictHostKeyChecking=yes + UserKnownHostsFile
#                                             enforce the host_key pinned in
#                                             SCHOOL_HOSTS; never accept-new or
#                                             no, which on an ephemeral runner
#                                             trust whatever answers
#   IdentitiesOnly                            offer only SCHOOLS_SSH_KEY
#
# Usage: ssh_box.sh <dir> <remote command...>
# <dir> holds host and known_hosts (inventory.py entry) and key (the workflow).
set -euo pipefail

dir=$1
shift
host="$(head -n 1 "$dir/host")"
exec ssh -i "$dir/key" \
  -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=4 \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$dir/known_hosts" \
  -o IdentitiesOnly=yes \
  "root@$host" "$@"
```

- [ ] **Step 4: Write cut-release.yml**

Create `.github/workflows/cut-release.yml`:

```yaml
name: cut-release

# B2: make a release tag (docs/superpowers/specs/2026-09-27-b2-release-deploys-design.md
# §1; runbook docs/deployment.md §9). Pushing the tag does nothing by itself
# (D1) -- a tag pushed with GITHUB_TOKEN triggers no workflow. A release is only
# ever made of a commit libli.pl deployed green (D2).
#
# Master-only: workflow_dispatch can run this file from any branch, and the
# guard scripts come from that branch's checkout.

on:
  workflow_dispatch:
    inputs:
      version:
        description: "Release version, vX.Y.Z"
        required: true
      commit:
        description: "Commit to release (default: the tip of master)"
        required: false
        default: ""

permissions: {}

jobs:
  cut:
    if: github.ref == 'refs/heads/master'
    runs-on: ubuntu-latest
    permissions:
      contents: write
      actions: read
    steps:
      - name: Validate the version
        env:
          VERSION: ${{ inputs.version }}
        run: |
          if [[ ! $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "refuse: version must be vX.Y.Z (e.g. v1.0.0), with no spaces" >&2
            echo "**refuse: version must be vX.Y.Z**" >> "$GITHUB_STEP_SUMMARY"
            exit 1
          fi

      # Full history and tags: the ancestry and containment checks need them,
      # and a depth-1 clone makes merge-base --is-ancestor misreport.
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Resolve the commit
        id: resolve
        env:
          VERSION: ${{ inputs.version }}
          COMMIT: ${{ inputs.commit }}
        run: python3 scripts/release/release_checks.py resolve "$VERSION" "${COMMIT:-origin/master}" >> "$GITHUB_OUTPUT"

      - name: Canary guard
        id: canary
        env:
          GH_TOKEN: ${{ github.token }}
          SHA: ${{ steps.resolve.outputs.sha }}
        run: |
          run_id="$(python3 scripts/release/canary_guard.py "$SHA")"
          echo "run_id=$run_id" >> "$GITHUB_OUTPUT"

      - name: B2 containment
        env:
          SHA: ${{ steps.resolve.outputs.sha }}
        run: python3 scripts/release/release_checks.py containment "$SHA"

      - name: Tag and push
        env:
          VERSION: ${{ inputs.version }}
          SHA: ${{ steps.resolve.outputs.sha }}
          RUN_ID: ${{ steps.canary.outputs.run_id }}
        run: |
          git config user.name 'github-actions[bot]'
          git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
          git tag -a "$VERSION" "$SHA" -m "Release $VERSION" -m "canary-run: $RUN_ID"
          git push origin "refs/tags/$VERSION"
          echo "Tagged $VERSION at $SHA (canary run $RUN_ID)" >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 5: Run the tests** — `uv run pytest tests/test_release_workflows.py` → all PASS.
- [ ] **Step 6: Falsify** — each docstring mutant, on the YAML / `ssh_box.sh`. Revert by hand.
- [ ] **Step 7: Commit**

```bash
git add scripts/release/ssh_box.sh .github/workflows/cut-release.yml tests/test_release_workflows.py
git commit -m "feat(release): Cut release workflow and the pinned ssh helper"
```

---

### Task 12: The Deploy release workflow

**Files:**
- Create: `.github/workflows/deploy-release.yml`
- Modify: `tests/test_release_workflows.py` (add `DEPLOY_RELEASE` to `NEW_WORKFLOWS`; append tests)

**Interfaces:**
- Consumes: `release_checks.py tag|containment` (Task 8), `canary_guard.py` (Task 7), `inventory.py plan|entry` (Task 9), `ssh_box.sh` (Task 11), `preflight.sh` (Task 5), `migration_guard.sh` (Task 1), `remote_deploy.sh` (Task 6), `report.py outcome|summarise` (Task 10).

- [ ] **Step 1: Write the failing tests**

In `tests/test_release_workflows.py`: change `NEW_WORKFLOWS = [CUT]` to `NEW_WORKFLOWS = [CUT, DEPLOY_RELEASE]`; extend the imports at the TOP of the file (not mid-file — ruff E402) to

```python
import os
import re
import subprocess
import sys

import pytest

from tests.release_harness import BASH, ROOT, posix, write
```

and append:

```python
def _dr():
    return DEPLOY_RELEASE.read_text(encoding="utf-8")


def test_report_runs_always_but_only_on_master():
    """One expression. Mutants: drop `always()` (report is skipped exactly when
    plan refused or a leg failed); drop the ref check."""
    expr = job_if(jobs(_dr())["report"])
    assert "always()" in expr and MASTER in expr


def test_plan_orders_its_checks():
    s = steps(jobs(_dr())["plan"])
    assert step_index(s, "Validate the version") == 0
    checkout = step_index(s, "actions/checkout")
    assert step_index(s, "release_checks.py tag") == checkout + 1
    assert checkout < step_index(s, "canary_guard.py") < step_index(s, "release_checks.py containment")
    assert step_index(s, "release_checks.py containment") < step_index(s, "inventory.py plan")


def test_plan_passes_the_tags_run_id_to_the_canary_guard():
    step = steps(jobs(_dr())["plan"])[step_index(steps(jobs(_dr())["plan"]), "canary_guard.py")]
    assert "RUN_ID: ${{ steps.tag.outputs.run_id }}" in step
    assert '"$SHA" "$RUN_ID"' in step


def test_the_deploy_matrix_is_isolated_per_school():
    joined = "\n".join(jobs(_dr())["deploy"])
    assert "fail-fast: false" in joined
    assert "code: ${{ fromJSON(needs.plan.outputs.codes) }}" in joined
    assert "group: deploy-school-${{ matrix.code }}" in joined
    assert "cancel-in-progress: false" in joined
    assert "timeout-minutes: 45" in joined


def test_masks_come_before_any_ssh():
    """Mutant: move the inventory step below pre-flight."""
    s = steps(jobs(_dr())["deploy"])
    entry = step_index(s, "inventory.py entry")
    assert "ssh_box.sh" not in s[entry]
    assert all(i > entry for i, st in enumerate(s) if "ssh_box.sh" in st)


def test_no_step_before_the_mask_carries_the_inventory():
    """Mutant: put SCHOOL_HOSTS in the checkout step's env: (its values would
    be in the log before any ::add-mask::)."""
    s = steps(jobs(_dr())["deploy"])
    entry = step_index(s, "inventory.py entry")
    assert not any("SCHOOL_HOSTS" in st for st in s[:entry])


def test_plan_and_deploy_call_the_release_scripts_rather_than_inlining_them():
    """Every run: step except the version check delegates to scripts/release/.
    Mutant: inline a guard's logic into a run: block."""
    for job in ("plan", "deploy"):
        for st in steps(jobs(_dr())[job]):
            if "run:" in st and "Validate the version" not in st:
                assert "scripts/release/" in st, st


def test_no_value_is_handed_on_through_the_environment_file():
    """A value in $GITHUB_ENV appears in every later step's env: header,
    printed before that step's commands -- before any mask. Checked on the
    whole file, comments included, so comments must not name it either.
    Mutant: `echo "HOST=..." >> "$GITHUB_ENV"` in any step."""
    assert "GITHUB_ENV" not in _dr()


def test_every_ssh_goes_through_the_pinned_helper():
    """Mutant: a step calls `ssh -o StrictHostKeyChecking=accept-new root@...`
    directly (or reads now_on with plain ssh)."""
    text = _dr()
    assert "accept-new" not in text and "StrictHostKeyChecking=no" not in text
    for block in run_blocks(text):
        stripped = block.replace("scripts/release/ssh_box.sh", "")
        assert not re.search(r"(?<![\w/.-])ssh\s", stripped), block


def test_the_box_env_file_never_leaves_the_box():
    """Whole file, comments included. Mutant: `scp root@...:/opt/libli/.env.production .`"""
    text = _dr()
    assert "scp" not in text and ".env.production" not in text
    assert "< scripts/release/preflight.sh" in text


def test_the_deploy_leg_runs_the_guard_and_the_detached_bootstrap():
    s = steps(jobs(_dr())["deploy"])
    guard = step_index(s, "migration_guard.sh")
    deploy = step_index(s, "remote_deploy.sh")
    assert step_index(s, "preflight.sh") < guard < deploy
    assert "id: deploy" in s[deploy]


def test_the_outcome_is_always_recorded_and_uploaded():
    s = steps(jobs(_dr())["deploy"])
    rec = s[step_index(s, "report.py outcome")]
    assert "if: always()" in rec
    assert "DEPLOY_OUTCOME: ${{ steps.deploy.outcome }}" in rec
    assert 'if [ "$MASKED" = success ]' in rec and "MASKED: ${{ steps.entry.outcome }}" in rec
    up = s[step_index(s, "actions/upload-artifact")]
    assert "if: always()" in up and "overwrite: true" in up
    assert "name: outcome-${{ matrix.code }}" in up


def test_report_tolerates_zero_artifacts():
    s = steps(jobs(_dr())["report"])
    assert "continue-on-error: true" in s[step_index(s, "actions/download-artifact")]


def test_job_permissions_are_least_privilege():
    j = jobs(_dr())
    assert "      contents: read\n      actions: read" in "\n".join(j["plan"])
    deploy = "\n".join(j["deploy"])
    assert "      contents: read" in deploy and "actions:" not in deploy
    assert "      contents: read\n      actions: read" in "\n".join(j["report"])


def test_libli_and_schools_never_share_secrets():
    """Mutant: aim either workflow at the other's host or key."""
    school = ("SCHOOL_HOSTS", "SCHOOLS_SSH_KEY", "HEALTHCHECKS_SCHOOL_DEPLOY_URL")
    assert not any(s in DEPLOY_YML.read_text(encoding="utf-8") for s in school)
    assert not re.search(r"secrets\.SSH_(HOST|KEY)\b", _dr())


def _report_script(tmp_path):
    s = steps(jobs(_dr())["report"])
    step = s[step_index(s, "report.py summarise")]
    body = step.split("run: |\n", 1)[1]
    lines = [ln[10:] if ln.startswith(" " * 10) else ln.strip() for ln in body.splitlines()]
    return "\n".join(lines).replace(
        "scripts/release/report.py", posix(ROOT / "scripts/release/report.py")
    )


@pytest.mark.skipif(BASH is None, reason="bash not on PATH")
@pytest.mark.parametrize(
    "plan_result,codes,hc_url,expect_ping",
    [
        ("failure", "", "https://hc.example/u", "https://hc.example/u/fail"),
        ("success", '["school-01"]', "https://hc.example/u", "https://hc.example/u/fail"),
        ("failure", "", "", None),
        ("success", '["school-01"]', "https://hc.example/u", "https://hc.example/u"),
    ],
)
def test_the_report_shell_pings_fail_on_a_refusal(tmp_path, plan_result, codes, hc_url, expect_ping):
    """A plan refusal (no matrix, no artifacts) must still produce a summary
    row and a /fail ping; no artifact for a planned code is a /fail; an unset
    secret pings nothing and does not fail; and a fully green run pings the
    PLAIN url (the last row writes a this-attempt ✅ artifact).
    Mutant: hard-code `endpoint="$HC_URL/fail"` -- the check could then never
    recover from its first failure."""
    summary = tmp_path / "summary.md"
    write(summary, "")
    if expect_ping == "https://hc.example/u":
        write(
            tmp_path / "outcomes/outcome-school-01.json",
            '{"code": "school-01", "run_attempt": 1, "from": "sha-a", '
            '"to": "v1.1.0", "result": "success", "now_on": "sha-b"}',
        )
    calls = tmp_path / "curl"
    write(calls, "")
    prelude = (
        f'python3() {{ "{posix(sys.executable)}" "$@"; }}\n'
        f'curl() {{ echo "$@" >> "{posix(calls)}"; return 7; }}\n'
    )
    env = dict(
        os.environ,
        PLAN_RESULT=plan_result,
        CODES=codes,
        RUN_ATTEMPT="1",
        HC_URL=hc_url,
        RUN_URL="https://run/1",
        GITHUB_STEP_SUMMARY=str(summary),
    )
    result = subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [BASH, "-e", "-c", prelude + _report_script(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    if expect_ping:
        assert calls.read_text().strip().endswith(expect_ping)
        if not expect_ping.endswith("/fail"):
            assert "/fail" not in calls.read_text()
    else:
        assert calls.read_text().strip() == ""
    if plan_result == "failure":
        assert "plan refused" in summary.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_release_workflows.py` → the new tests FAIL (file missing).

- [ ] **Step 3: Write deploy-release.yml**

Create `.github/workflows/deploy-release.yml`:

```yaml
name: deploy-release

# B2: deploy a release tag to one school box, or all of them
# (docs/superpowers/specs/2026-09-27-b2-release-deploys-design.md §2; runbook
# docs/deployment.md §9). The ONLY way a school changes version (D1);
# rollback is this button with an older version.
#
# Master-only: workflow_dispatch can run this file from any branch, and the
# guard scripts come from that branch's checkout. Nothing here names a school:
# boxes are opaque codes (D4), and every host and domain is masked before any
# command could print it.

on:
  workflow_dispatch:
    inputs:
      school:
        description: "School code (school-NN), or all"
        required: true
      version:
        description: "Release tag, vX.Y.Z"
        required: true

permissions: {}

jobs:
  plan:
    if: github.ref == 'refs/heads/master'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read
    outputs:
      codes: ${{ steps.inventory.outputs.codes }}
      target_sha: ${{ steps.tag.outputs.target_sha }}
    steps:
      # Before anything uses the value: it is later spliced into a root shell.
      - name: Validate the version
        env:
          VERSION: ${{ inputs.version }}
        run: |
          if [[ ! $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "refuse: version must be vX.Y.Z" >&2
            echo "**refuse: version must be vX.Y.Z**" >> "$GITHUB_STEP_SUMMARY"
            exit 1
          fi

      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Inspect the release tag
        id: tag
        env:
          VERSION: ${{ inputs.version }}
        run: python3 scripts/release/release_checks.py tag "$VERSION" >> "$GITHUB_OUTPUT"

      - name: Canary guard
        env:
          GH_TOKEN: ${{ github.token }}
          SHA: ${{ steps.tag.outputs.target_sha }}
          RUN_ID: ${{ steps.tag.outputs.run_id }}
        run: python3 scripts/release/canary_guard.py "$SHA" "$RUN_ID"

      - name: B2 containment
        env:
          SHA: ${{ steps.tag.outputs.target_sha }}
        run: python3 scripts/release/release_checks.py containment "$SHA"

      - name: Resolve the schools
        id: inventory
        env:
          SCHOOL_HOSTS: ${{ secrets.SCHOOL_HOSTS }}
          SCHOOL: ${{ inputs.school }}
        run: python3 scripts/release/inventory.py plan "$SCHOOL" --output "$GITHUB_OUTPUT"

  deploy:
    needs: plan
    if: github.ref == 'refs/heads/master'
    runs-on: ubuntu-latest
    # deploy.yml's command_timeout (30m) plus headroom for pre-flight retries
    # and deploy.sh waiting on the lock behind a running backup. A timed-out leg
    # is NOT proof of a failed deploy: the run is detached on the box.
    timeout-minutes: 45
    permissions:
      contents: read
    strategy:
      fail-fast: false
      matrix:
        code: ${{ fromJSON(needs.plan.outputs.codes) }}
    # A deploy interrupted mid-migrate is worse than one that finishes late.
    concurrency:
      group: deploy-school-${{ matrix.code }}
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      # Read AND mask in one step: a value handed to a later step via the
      # workflow's environment file would be printed in that step's env:
      # header before any mask. (Tests forbid the file's variable name here.)
      - name: Read and mask the inventory entry
        id: entry
        env:
          SCHOOL_HOSTS: ${{ secrets.SCHOOL_HOSTS }}
          SCHOOLS_SSH_KEY: ${{ secrets.SCHOOLS_SSH_KEY }}
          CODE: ${{ matrix.code }}
        run: |
          python3 scripts/release/inventory.py entry "$CODE" --dir "$RUNNER_TEMP/box"
          printf '%s\n' "$SCHOOLS_SSH_KEY" > "$RUNNER_TEMP/box/key"
          chmod 600 "$RUNNER_TEMP/box/key"

      # The box's env file is parsed ON THE BOX; only validated values come back.
      - name: Pre-flight
        id: preflight
        env:
          VERSION: ${{ inputs.version }}
          TARGET_SHA: ${{ needs.plan.outputs.target_sha }}
        run: |
          if ! out="$(bash scripts/release/ssh_box.sh "$RUNNER_TEMP/box" bash -s -- "$VERSION" "$TARGET_SHA" < scripts/release/preflight.sh)"; then
            printf '%s\n' "$out" >&2
            exit 1
          fi
          image_tag="$(printf '%s\n' "$out" | sed -n 's/^image_tag=//p')"
          echo "from=$image_tag" >> "$GITHUB_OUTPUT"

      - name: Migration guard
        env:
          FROM: ${{ steps.preflight.outputs.from }}
          TARGET_SHA: ${{ needs.plan.outputs.target_sha }}
        run: bash scripts/release/migration_guard.sh "${FROM#sha-}" "$TARGET_SHA"

      - name: Deploy
        id: deploy
        env:
          VERSION: ${{ inputs.version }}
          TARGET_SHA: ${{ needs.plan.outputs.target_sha }}
        run: bash scripts/release/ssh_box.sh "$RUNNER_TEMP/box" bash -s -- "$VERSION" "$TARGET_SHA" < scripts/release/remote_deploy.sh

      - name: Record the outcome
        if: always()
        env:
          CODE: ${{ matrix.code }}
          RUN_ATTEMPT: ${{ github.run_attempt }}
          FROM: ${{ steps.preflight.outputs.from }}
          VERSION: ${{ inputs.version }}
          DEPLOY_OUTCOME: ${{ steps.deploy.outcome }}
          MASKED: ${{ steps.entry.outcome }}
        run: |
          now_on=unknown
          # Never connect before the mask exists: a connection error prints the host.
          if [ "$MASKED" = success ]; then
            if out="$(bash scripts/release/ssh_box.sh "$RUNNER_TEMP/box" bash -s -- --read-only < scripts/release/preflight.sh)"; then
              now_on="${out#image_tag=}"
            fi
          fi
          python3 scripts/release/report.py outcome --code "$CODE" --attempt "$RUN_ATTEMPT" \
            --from "${FROM:-unknown}" --to "$VERSION" --deploy-outcome "$DEPLOY_OUTCOME" \
            --now-on "$now_on" > "outcome-$CODE.json"

      - name: Upload the outcome
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: outcome-${{ matrix.code }}
          path: outcome-${{ matrix.code }}.json
          overwrite: true

  report:
    needs: [plan, deploy]
    # One expression: the ref check alone reintroduces the implicit success()
    # and would skip this job exactly when plan refused or a leg failed.
    if: always() && github.ref == 'refs/heads/master'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read
    steps:
      - uses: actions/checkout@v4

      # Zero artifacts (a plan refusal, every leg dead early) must not fail
      # the job: those are the runs whose /fail ping matters most.
      - uses: actions/download-artifact@v4
        continue-on-error: true
        with:
          pattern: outcome-*
          path: outcomes
          merge-multiple: true

      - name: Summarise and report
        env:
          PLAN_RESULT: ${{ needs.plan.result }}
          CODES: ${{ needs.plan.outputs.codes }}
          RUN_ATTEMPT: ${{ github.run_attempt }}
          HC_URL: ${{ secrets.HEALTHCHECKS_SCHOOL_DEPLOY_URL }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          verdict="$(python3 scripts/release/report.py summarise --plan-result "$PLAN_RESULT" --codes "$CODES" --attempt "$RUN_ATTEMPT" --dir outcomes --summary "$GITHUB_STEP_SUMMARY")"
          echo "verdict: $verdict"
          if [ -z "$HC_URL" ]; then
            echo "HEALTHCHECKS_SCHOOL_DEPLOY_URL is unset; not reporting this run"
            exit 0
          fi
          endpoint="$HC_URL"
          if [ "$verdict" != success ]; then
            endpoint="$HC_URL/fail"
          fi
          curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "$RUN_URL" "$endpoint" \
            || echo "healthchecks ping failed; the check's own period is the backstop"
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_release_workflows.py tests/test_deploy_wiring.py` → all PASS.
- [ ] **Step 5: Falsify** — each docstring mutant in the YAML. Revert by hand.
- [ ] **Step 6: Commit**

```bash
git add .github/workflows/deploy-release.yml tests/test_release_workflows.py
git commit -m "feat(release): Deploy release workflow -- plan, per-school legs, report"
```

---

### Task 13: Runbook

**Files:**
- Modify: `docs/deployment.md`
- Test: `tests/test_release_runbook.py`

**Interfaces:**
- Consumes: every earlier task's names (workflow names, secrets, script paths, refusal messages).

- [ ] **Step 1: Write the failing test**

Create `tests/test_release_runbook.py`:

```python
"""The runbook facts an operator acts on for B2 (spec §9)."""

import re

from tests.release_harness import ROOT

RUNBOOK = ROOT / "docs/deployment.md"


def _text():
    return RUNBOOK.read_text(encoding="utf-8")


def _section(title):
    text = _text()
    start = text.index(title)
    nxt = re.search(r"^## ", text[start + len(title) :], re.MULTILINE)
    return text[start : start + len(title) + (nxt.start() if nxt else len(text))]


def test_the_schools_section_exists_and_names_the_secrets():
    s = _section("## 9. Schools")
    for fact in ("SCHOOL_HOSTS", "SCHOOLS_SSH_KEY", "HEALTHCHECKS_SCHOOL_DEPLOY_URL",
                 "cut-release", "deploy-release", "registrable domain"):
        assert fact in s, fact


def test_first_boot_adds_the_channel_line_only_after_up():
    """The only order in which no step resets a school to master."""
    s = _section("## 9. Schools")
    assert s.index("up -d") < s.index("LIBLI_DEPLOY_CHANNEL=release")


def test_provisioning_includes_the_admin_and_the_backup_cron():
    """Mutant: drop the §5/§7 sentence -- a box built by §9 alone has no
    admin and no backups, so D3's restore path has nothing to restore."""
    s = _section("## 9. Schools")
    assert "**§5**" in s and "**§7**" in s and "nightly backup" in s


def test_the_cited_canary_run_must_never_be_deleted():
    assert "never delete a `deploy.yml` run" in _section("## 9. Schools").lower()


def test_the_in_place_restore_is_documented():
    s = _section("## 9. Schools")
    assert "git checkout --force --detach <manifest git_sha>" in s
    assert "restore.sh" in s


def test_the_d9_red_run_is_explained():
    assert "superseded by" in _section("## 8. Continuous deployment")


def test_section_8_no_longer_says_a_pull_failure_takes_the_site_down():
    """After B2 a login or pull failure is pre-`up`: site up, checkout restored."""
    s = _section("## 8. Continuous deployment")
    assert "The first two happen before" in s
    assert "The other three do not" not in s
    assert "the\n  rollback path below" not in s
    assert "the rollback path below" not in s


def test_the_libli_rollback_recipe_uses_deploy_sh_with_a_ref():
    """A bare `compose up` after a reset starts whatever LIBLI_IMAGE_TAG
    already says; `bash deploy.sh` with no ref resets straight back to master."""
    text = _text()
    assert "LIBLI_DEPLOY_REF=<last-good-sha> bash deploy.sh" in text
    assert "git reset --hard <last-good-sha>\ndocker compose" not in text
    assert "`git reset --hard <last-good-sha>` then `bash deploy.sh`" not in text
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_release_runbook.py` → FAIL.

- [ ] **Step 3: Edit docs/deployment.md**

1. **Top "Scope" paragraph (line 7):** append one sentence: "School boxes are the same install, one per school, updated only by release tags — see §9."

2. **§8 *When a deploy goes red*** — insert AFTER the paragraph "(The second point used to be "the build fails". …compilation one.)" — not before "Past that point", whose "that point" refers to the fetch paragraph above it:

```markdown
**A red run ending in `superseded by <sha>; the newer run deploys it` is benign.**
Master moved on while this run waited in the queue (D9). `deploy.yml` had reset the
checkout to the newer commit; `deploy.sh` refused before touching any container and put
the checkout back to the commit the running image was built from. The site stays on its
previous version until the newer run deploys, and the deploy alert clears when that run
goes green. Nothing to do. (Why it refuses rather than deploying: a release may only be
cut from a commit libli.pl ran, and a green deploy job must mean exactly that commit.)
```

3. **§8 recovery block** — replace

````markdown
There is no automatic rollback. Recovery is manual and takes one pull:

```bash
ssh root@<ip>
cd /opt/libli
git reset --hard <last-good-sha>
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --wait
```

`git reset --hard <sha>` still does what it always did — `deploy.sh` derives
`LIBLI_IMAGE_TAG` from the checkout, so moving the checkout moves the image.
````

with

````markdown
There is no automatic rollback. Recovery on libli.pl is manual and takes one pull:

```bash
ssh root@<ip>
cd /opt/libli
LIBLI_DEPLOY_REF=<last-good-sha> bash deploy.sh
```

A full 40-hex sha. `deploy.sh` checks it out, pulls `sha-<it>` and persists the tag. Do
not `git reset` and `compose up` by hand: a bare `up` starts whatever `LIBLI_IMAGE_TAG`
already says, not the reset commit's image — and plain `bash deploy.sh` resets straight
back to master. The next ordinary deploy re-attaches the checkout to `master`.

**A school box is never recovered by hand** — use *Deploy release* with the previous
version (§9). By-hand `bash deploy.sh` on a school box is refused.
````

3a. **The paragraph right after that block** — replace

   ```text
   A migration that fails part-way is the case that needs care — the schema may be ahead of
   the code you just reset to. Read `logs app | grep '==>'` before assuming a rebuild fixes it.
   ```

   with

   ```text
   A migration that fails part-way is the case that needs care — the schema may be ahead of
   the version you just rolled back to (`deploy.sh` does not undo a migration). Read
   `logs app | grep '==>'` first; if the schema is ahead, the path is a restore.
   ```

4. **Known constraints**, the "Rollback is one pull" bullet — replace the WHOLE bullet (four lines, 2-space continuation, exactly as in the file):

   ```text
   - **Rollback is one pull.** `git reset --hard <last-good-sha>` then `bash deploy.sh`: the
     tag follows the checkout, so the previous image is pulled rather than rebuilt. What this
     cannot undo is an **already-applied migration** — the schema stays ahead of the code, and
     that case needs a restore from `docs/backup-and-restore.md`, not a rollback.
   ```

   with:

   ```text
   - **Rollback is one pull.** On libli.pl, `LIBLI_DEPLOY_REF=<last-good-sha> bash deploy.sh`
     pulls the previous image rather than rebuilding it; on a school, *Deploy release* with the
     older version. What this cannot undo is an **already-applied migration** — the schema
     stays ahead of the code, and that case needs a restore from `docs/backup-and-restore.md`,
     not a rollback. On a school box the migration guard refuses such a rollback outright and
     points to the restore (§9).
   ```

   The old recipe was wrong as written: `bash deploy.sh` with no ref resets straight back to `origin/master`.

   This bullet together with the Scope sentence in item 1 is what the spec's "the *Known constraints* entry about single-host CD is replaced" maps to: the runbook has no dedicated single-host-CD bullet, and those two are the only places that describe deploys as one-host-only.

4a. **§8 "Past that point" paragraph** — replace

   ```text
   Past that point `deploy.sh` fails loudly at four places, in order: the Caddyfile does not
   parse, **the GHCR login or the pull fails**, the app container never reports healthy
   (`--wait`), or the public URL does not answer `/healthz/`. The first leaves the running site
   untouched. The other three do not: the old container is already gone, so a red run means the
   site is **down**, not merely un-updated.
   ```

   with

   ```text
   Past that point `deploy.sh` fails loudly at four places, in order: the Caddyfile does not
   parse, **the GHCR login or the pull fails**, the app container never reports healthy
   (`--wait`), or the public URL does not answer `/healthz/`. The first two happen before
   `up`: the running site is untouched, and `deploy.sh` puts the checkout back to the commit
   the running image was built from. The last two happen after `up` started: the old
   container is already gone, so a red run there means the site is **down**, not merely
   un-updated.
   ```

4b. **§8 "Two things about `deploy.sh`"**, first bullet — replace the whole bullet

   ```text
   - **The reset happens twice, on purpose — the fetch no longer does.** `deploy.yml` resets
     the checkout before it runs `deploy.sh`, and `deploy.sh` resets again. The workflow copy
     bootstraps a host that has no `deploy.sh` yet and guarantees bash parses the version this
     commit ships; the script copy is what makes running `bash deploy.sh` by hand -- the
     rollback path below -- correct on its own. Deleting either one breaks a case the other
     does not cover. The **fetch** is a different matter: two requests to github.com inside a
     second is what tripped #296, so `deploy.yml` sets `LIBLI_DEPLOY_SKIP_FETCH=1` and
     `deploy.sh` resets to the ref CI just fetched. Run by hand the variable is unset, so the
     fetch happens — which is exactly what the rollback path needs.
   ```

   with

   ```text
   - **The reset happens twice, on purpose — the fetch no longer does.** `deploy.yml` resets
     the checkout before it runs `deploy.sh`, and `deploy.sh` resets again. The workflow copy
     bootstraps a host that has no `deploy.sh` yet and guarantees bash parses the version this
     commit ships; the script copy is what makes a by-hand `bash deploy.sh` correct on its own
     (plain, it resets to master; the rollback is `LIBLI_DEPLOY_REF=<sha> bash deploy.sh`,
     above). Deleting either one breaks a case the other does not cover. The **fetch** is a
     different matter: two requests to github.com inside a second is what tripped #296, so
     `deploy.yml` sets `LIBLI_DEPLOY_SKIP_FETCH=1` and `deploy.sh` resets to the ref CI just
     fetched. Run by hand the variable is unset, so the fetch happens — which is exactly what
     a by-hand run needs.
   ```

5. **New section**, inserted before the `---` line that precedes `## Known constraints` (so §9 sits above that rule), preceded by its own `---` line and a blank line — every numbered section in the runbook is separated from the previous one by a rule — and followed by a blank line:

````markdown
## 9. Schools

School boxes run **release tags**, never `master`. libli.pl is the canary: a release can
only be made of a commit libli.pl deployed green (D2), and a school changes version only
when you press *Deploy release* (D1). Design and every rule's reason:
`docs/superpowers/specs/2026-09-27-b2-release-deploys-design.md`.

### School secrets (one-time setup)

Three repo secrets, all distinct from libli.pl's:

- **`SCHOOLS_SSH_KEY`** — one key for every school box, never libli.pl's `SSH_KEY`:
  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/libli_schools -C "github-actions-libli-schools" -N ""
  gh secret set SCHOOLS_SSH_KEY --repo krzyssikora/libli < ~/.ssh/libli_schools
  ```
- **`SCHOOL_HOSTS`** — JSON, one entry per box, keyed by an **opaque code**:
  ```json
  {"school-01": {"host": "203.0.113.10", "host_key": "ssh-ed25519 AAAA...", "domain": "szkola.pl"}}
  ```
  Codes are `school-NN`. The code → school mapping lives only in your own notes: nothing
  in the repo, the run logs or the UI names a customer (D4). `domain` is the school's
  **registrable domain**, and every name in the box's `SITE_ADDRESS` and its
  `DJANGO_SITE_DOMAIN` must contain it — it exists only to be masked in logs. Keep the
  JSON file outside the repo and set it with
  `gh secret set SCHOOL_HOSTS --repo krzyssikora/libli < school_hosts.json`.
- **`HEALTHCHECKS_SCHOOL_DEPLOY_URL`** — a new healthchecks.io check *libli school
  deploys*, period set to the maximum. School deploys are rare and manual, so the absence
  alert is only a yearly liveness check; the `/fail` ping is the alert.

### Provisioning a school box

§1–§4 as for libli.pl, with these differences, **in this order** — it is the only order in
which no step resets the school to `master`:

1. **Deploy key first.** Give the box its own read-only deploy key (§8 *Fetching over
   SSH*, host side) and clone over SSH: `git clone git@github.com:krzyssikora/libli.git
   /opt/libli`. A full clone, never `--depth`: the migration guard reads history.
2. **Check out a release tag**, not master: `git checkout --detach v1.0.0`. The tag must
   already exist and must have been made by *cut-release* (see *Cutting a release*
   below) — for the very first school, cut `v1.0.0` before provisioning.
3. In `.env.production`, set `LIBLI_IMAGE_TAG=sha-<40 hex>` by hand — the value of
   `git rev-parse 'v1.0.0^{commit}'` — as exactly one line in exactly that form. Do **not**
   add the channel line yet.
4. First boot as §3 (`up -d`) and the §4 checks. This deliberately does not use
   `deploy.sh`: on a release-channel box it refuses a box with no persisted tag.
   Then **§5** (Platform Admin, first-run wizard) and **§7** (scheduled jobs, including
   the nightly backup cron) exactly as for libli.pl. A school box without backups has
   nothing to restore from when the migration guard refuses a rollback (below).
5. **Then** add `LIBLI_DEPLOY_CHANNEL=release` to `.env.production` — exactly that: no
   `export`, no spaces, LF line endings.
6. Runner access: `ssh-copy-id -i ~/.ssh/libli_schools.pub root@<ip>`. Capture the host
   key with `ssh-keyscan -t ed25519 <ip>` and keep only the `ssh-ed25519 AAAA...` part
   for `host_key`.
7. Add the entry to `SCHOOL_HOSTS`.
8. Run *Deploy release* for the box with the same tag — a same-version pass that proves
   the workflow reaches it.

### Cutting a release

Actions → *cut-release* → *Run workflow*: a version `vX.Y.Z` and, optionally, a commit
(default: master's tip). It refuses unless libli.pl's deploy of that commit went green.
Hotfix path: merge, let libli.pl deploy, then cut. Tags are created **only** here — the
by-hand path on a box cannot re-check D2.

**Never delete a `deploy.yml` run that a release tag cites** (the tag's `canary-run:`
line). Every deploy of that release, rollbacks included, re-checks that run; if it is
gone, cut a new release on a later green commit.

### Deploying and rolling back

Actions → *deploy-release*: a school code or `all`, and a version. Rollback is the same
button with an older version. Per school the run masks the box's names, runs pre-flight
on the box, runs the migration guard, and deploys **detached** from the ssh session —
the log stays on the box in `/var/log/libli-deploy/` (newest 20 kept).

Reading the summary:

- **`❌ no result`** — the leg died before recording, or a later dispatch for the same
  school superseded it (GitHub keeps one pending run per school).
- **`(attempt N)`** — a row from an earlier attempt, not this one. After "Re-run failed
  jobs" the ping is `/fail` even if every row is ✅; dispatch a fresh *Deploy release*
  (a same-version pass for schools already on it) for a clean ping.
- **A timed-out leg is not a failed deploy.** The run is detached and may have finished:
  read the box's `LIBLI_IMAGE_TAG` and the newest log in `/var/log/libli-deploy/`.

### What each refusal means

| Refusal | Site | What to do |
|---|---|---|
| canary guard / B2 containment (plan) | untouched | release a commit libli.pl deployed green |
| unknown code / malformed `SCHOOL_HOSTS` | untouched | fix the secret |
| host key mismatch / ssh unreachable | untouched | check the box; re-capture `host_key` only if the box was rebuilt |
| `LIBLI_DEPLOY_CHANNEL is not exactly 'release'` | untouched | fix `.env.production` (a CRLF file is reported as such) |
| `LIBLI_IMAGE_TAG absent` / `malformed` | untouched | one line `LIBLI_IMAGE_TAG=sha-<40 hex>` |
| tag resolves to a different commit | untouched | the tag on origin no longer matches what `plan` checked: dispatch a fresh *Deploy release* (a re-run reuses the old check), and treat a tag not made by *cut-release* as untrusted |
| cannot fetch the tag | untouched | re-run (GitHub refusal) or fix the box's deploy key |
| migration guard | untouched | restore (below) |
| failure inside `deploy.sh` before `up` | untouched, checkout restored | fix the cause, re-deploy the same version |
| `up --wait` / `/healthz/` failure | **down** | fix the cause, re-deploy **the same version**; the previous version only if no migration lies between |
| prune failure after `/healthz/` passed | up on the new version | ignore, or re-deploy the same version |

### Rolling back across a migration: restore in place

The migration guard refuses a rollback that crosses a migration, a `uv.lock` change or a
postgres major version (D3). The path is a restore from a backup taken before the newer
version (`docs/backup-and-restore.md`), in place on the existing box:

```bash
cd /opt/libli
git fetch origin '+refs/tags/*:refs/tags/*'
git checkout --force --detach <manifest git_sha>
# then restore.sh exactly as docs/backup-and-restore.md describes
```

No `deploy.sh` and no *Deploy release* is involved. `restore.sh` writes the restored image
into `LIBLI_IMAGE_TAG`, and the backup's `.env.production` keeps the channel line, so the
next *Deploy release* treats the restored version as current.

### By hand on a box

`LIBLI_DEPLOY_REF=vX.Y.Z bash /opt/libli/deploy.sh` — tags only. It runs the migration
guard (both the current and the target copy) but **not** the canary guard. Plain
`bash deploy.sh` is refused on a school box.

### Going private

1. libli.pl gets its read-only deploy key and fetches over SSH (§8 *Fetching over SSH*)
   **before** the flip — or its first deploy after it fails at the fetch.
2. Every school box has its own deploy key (step 1 above; GitHub does not reuse a deploy
   key across boxes).
3. Flip the repo to private. GHCR is already private and every box already logs in.
````

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_release_runbook.py tests/test_deploy_wiring.py tests/test_backup_wiring.py` → all PASS (`test_backup_wiring.py` also reads the runbook).
- [ ] **Step 4b: Falsify** — delete the §5/§7 sentence from §9 → `test_provisioning_includes_the_admin_and_the_backup_cron` RED; restore the old "Past that point" paragraph → `test_section_8_no_longer_says…` RED; restore the old §8 recovery block → `test_the_libli_rollback_recipe…` RED. Revert each by hand.
- [ ] **Step 5: Commit**

```bash
git add docs/deployment.md tests/test_release_runbook.py
git commit -m "docs(deploy): §9 Schools runbook; libli.pl rollback via LIBLI_DEPLOY_REF; D9 red runs"
```

---

### Task 14: Branch gate

**Files:** none new.

- [ ] **Step 1: Lint** — `uv run ruff check .` and `uv run ruff format --check .` (run `uv run ruff format .` first if needed). Both clean.
- [ ] **Step 2: The deploy/release suites together** — with the test DB container up:
  `uv run pytest tests/test_deploy_wiring.py tests/test_backup_wiring.py tests/test_manage_wiring.py tests/test_release_migration_guard.py tests/test_deploy_libli_path.py tests/test_deploy_release_path.py tests/test_release_preflight.py tests/test_release_remote_deploy.py tests/test_release_canary_guard.py tests/test_release_checks.py tests/test_release_inventory.py tests/test_release_report.py tests/test_release_workflows.py tests/test_release_runbook.py`
  Grep the summary line (the exit code can lie). Report skips by name (`test_release_remote_deploy.py` skips without `setsid`).
- [ ] **Step 3: Syntax** — `bash -n` on `deploy.sh` and every `scripts/release/*.sh`.
- [ ] **Step 4: Record in the PR body** — the rehearsal is the definition of done (spec *Rehearsal*); list its steps as unchecked items, plus Rollout step 2 (libli.pl deploy key) as Krzysztof's action. The first `deploy.yml` run after merge is the libli.pl regression check: say so.

---

## Self-review notes (for the reviewer)

- **Spec coverage:** §1 → Tasks 8, 11; §2 → Tasks 5, 6, 9, 10, 12; §3 → Tasks 2, 3; §4 → Tasks 4, 7; §5 → Task 1 (+ embedded use in Task 2); §6 → Tasks 9, 11; §7 → Tasks 2–6 tests, runbook table in Task 13; §8/§9 → Task 13; Testing → every task; Rehearsal/Rollout → Task 14 Step 4 (human actions, not code).
- **Deliberate deviations:** Python for the runner-side JSON tools (Global Constraints); `deploy.yml`'s fail-closed check uses POSIX `case` rather than `[[ =~ ]]` (Task 4); the script-rewrite test rewrites in place rather than via `git checkout`, because git replaces the file with a new inode (Task 3).

