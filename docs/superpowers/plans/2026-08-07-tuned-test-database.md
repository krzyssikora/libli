# Tuned Test Database (Part A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut local e2e wall clock by running tests against a disposable Postgres with durability disabled, where the per-test `TRUNCATE … CASCADE` costs 88 ms instead of 2,881 ms.

**Architecture:** A `docker-compose.test.yml` service on a tmpfs with `fsync=off`, published on loopback port 55433. `config/settings/test.py` reads an optional `TEST_DATABASE_URL` and overrides `DATABASES` only when set, so the change is a no-op for anyone who has not started the container. A collection-time notice nudges adoption. CI gets the tmpfs but not the durability flags (service containers accept no `command:`).

**Tech Stack:** Docker Compose v2.17+ (local machine has v5.1.2), postgres:16, django-environ, pytest-django, pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-08-07-test-suite-wall-clock-design.md`. Part B (affected-tests workflow) is a separate plan — the two share no code, and spec §5.3 keeps Part B when Part A reverts.

## Global Constraints

- Port **55433**, bound to **`127.0.0.1`** only — never `0.0.0.0`. The server is trust-auth superuser.
- Compose project name **`libli-test`** in every documented command (`-p libli-test`), so every worktree addresses one container.
- tmpfs **1 GiB** (`1073741824`), `mode: 01777`. **Verified working** — the long-form `volumes:` syntax mounts at exactly 1.0 G and Postgres starts healthy in 3.6 s.
- `TEST_DATABASE_URL` unset MUST leave behaviour byte-identical to today.
- `# noqa: F405` on any line using a star-imported name from `config.settings.base` (`env`, `DATABASES`). Ruff's `F` rule set is selected in `pyproject.toml`; the CI `lint` job fails otherwise.
- Never add a second `-q` to a pytest command — `addopts` already carries one, and `-qq` suppresses the warnings summary.
- Run tests with `uv run`; `pytest`/`ruff`/`python` are not on PATH.
- `-m e2e` is mandatory for e2e runs, or they silently deselect and exit 5.

---

### Task 1: The compose service

**Files:**
- Create: `docker-compose.test.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a Postgres reachable at `postgres://libli@127.0.0.1:55433/libli`, container `libli-test-db`, compose project `libli-test`.

- [ ] **Step 1: Create `docker-compose.test.yml`**

```yaml
# Disposable Postgres for running the test suite fast.
#
# Durability is deliberately OFF and the data directory is a tmpfs: nothing on
# this server survives a restart, which is correct for a database pytest drops
# and recreates anyway. MEASURED: TRUNCATE of the suite's 89 tables costs
# 2,881 ms on a normal server and 88 ms here.
#
# NEVER apply these settings to the instance holding dev or mat-pp data.
# Port 55433 (not 5432) and the loopback binding are both deliberate.
services:
  test-db:
    image: postgres:16
    container_name: libli-test-db
    ports:
      - "127.0.0.1:55433:5432"        # loopback only: this server is trust-auth superuser
    environment:
      POSTGRES_USER: libli
      POSTGRES_DB: libli
      POSTGRES_HOST_AUTH_METHOD: trust
    command:
      - -c
      - fsync=off
      - -c
      - synchronous_commit=off
      - -c
      - full_page_writes=off
    volumes:
      # Long form, not the short `tmpfs:` key: only this syntax carries a size.
      - type: tmpfs
        target: /var/lib/postgresql/data
        tmpfs:
          size: 1073741824            # 1 GiB; a test database measures 12 MB, 8 workers ~96 MB
          mode: 01777
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U libli"]
      interval: 2s
      timeout: 3s
      retries: 15
```

- [ ] **Step 2: Start it and verify it reports healthy**

Run:
```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
```
Expected: ends with `Container libli-test-db Healthy`, exit 0, in under ~10 s.

- [ ] **Step 3: Verify the tmpfs is mounted at the requested size**

Run:
```bash
docker exec libli-test-db df -h /var/lib/postgresql/data | tail -1
```
Expected: a `tmpfs` row showing `1.0G` total. If it shows the daemon default instead, the `mode`/`size` keys did not apply — stop and fix before continuing.

- [ ] **Step 4: Verify the durability flags took effect**

Run:
```bash
docker exec libli-test-db psql -U libli -d libli -tAc "show fsync; show synchronous_commit; show full_page_writes"
```
Expected: `off`, `off`, `off`.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.test.yml
git commit -m "feat: add disposable tuned test database compose service"
```

---

### Task 2: Settings wiring

**Files:**
- Modify: `config/settings/test.py` (append after line 26)
- Test: `tests/test_settings_test_db.py` (create)

**Interfaces:**
- Consumes: `env` and `DATABASES` from `config.settings.base` (star import).
- Produces: `_resolve_databases(env_value: str, current: dict) -> dict | None` in `config.settings.test`. Returns `None` for "no override"; otherwise a full `DATABASES`-shaped dict with a `"default"` key. Raises `django.core.exceptions.ImproperlyConfigured` on a non-empty value that is not a usable *separate* postgres server.

**Why the guard compares against `DATABASE_URL`.** The spec proposed requiring "an explicit port", but that does not reject the dangerous case it was written for: `postgres://libli@127.0.0.1:5432/libli` has an explicit port and would point the whole suite at the developer's real Postgres. Comparing `(HOST, PORT, NAME)` against the already-resolved `DATABASE_URL` rejects it directly. This is a deliberate refinement of spec §A2.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_test_db.py`:

```python
"""`TEST_DATABASE_URL` resolution for the disposable test server.

Tests the pure helper directly. Do NOT re-import `config.settings.test` the way
`test_settings_production.py` re-imports production: that pattern is safe only
because production is not the active settings module. Re-executing test.py runs
its `TEMPLATES[0]["DIRS"] = [...]` line again, and because `base` is not popped,
`TEMPLATES[0]` is the same dict object `django.conf.settings` references — every
re-import appends another copy of the test-templates dir to live global state.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings.test import _resolve_databases

DEV = {"HOST": "localhost", "PORT": 5432, "NAME": "libli"}


def test_empty_value_means_no_override():
    assert _resolve_databases("", DEV) is None


def test_valid_url_yields_a_databases_dict():
    resolved = _resolve_databases("postgres://libli@127.0.0.1:55433/libli", DEV)

    assert set(resolved) == {"default"}
    assert resolved["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert resolved["default"]["PORT"] == 55433


def test_unparseable_value_is_rejected():
    # django-environ returns {} rather than raising for garbage, so the explicit
    # engine check — not the try/except — is what catches this. MEASURED.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("not-a-url", DEV)

    assert "not-a-url" in str(exc.value)


def test_a_non_postgres_url_is_rejected():
    with pytest.raises(ImproperlyConfigured):
        _resolve_databases("sqlite:///tmp/x.db", DEV)


def test_pointing_at_the_dev_instance_is_rejected():
    # The whole point of the guard: this parses cleanly and would run the suite
    # against the developer's real database.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("postgres://libli@localhost:5432/libli", DEV)

    assert "DATABASE_URL" in str(exc.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_settings_test_db.py -p no:warnings`
Expected: FAIL — `ImportError: cannot import name '_resolve_databases'`.

- [ ] **Step 3: Implement the helper**

Append to `config/settings/test.py`:

```python

# --- optional: run against the disposable tuned server (docker-compose.test.yml) ---
# Unset, everything below is a no-op and behaviour is identical to before.
# See docs/development/testing.md.
from django.core.exceptions import ImproperlyConfigured  # noqa: E402  (settings module)


def _resolve_databases(env_value, current):
    """Return a DATABASES-shaped dict for `env_value`, or None for "no override".

    Raises ImproperlyConfigured when a value is set but unusable. django-environ
    does NOT raise for garbage -- `db_url_config("not-a-url")` returns `{}` --
    so the explicit checks below, not the try/except, do the real work.
    """
    if not env_value:
        return None
    try:
        cfg = env.db_url_config(env_value)  # noqa: F405
    except Exception as exc:  # defensive: non-string input, future parser changes
        raise ImproperlyConfigured(
            f"TEST_DATABASE_URL could not be parsed: {env_value!r}"
        ) from exc
    if cfg.get("ENGINE") != "django.db.backends.postgresql":
        raise ImproperlyConfigured(
            f"TEST_DATABASE_URL must be a postgres:// URL; got {env_value!r}"
        )
    keys = ("HOST", "PORT", "NAME")
    if tuple(cfg.get(k) for k in keys) == tuple(current.get(k) for k in keys):
        raise ImproperlyConfigured(
            "TEST_DATABASE_URL points at the same server and database as "
            f"DATABASE_URL ({env_value!r}). It must be a separate, disposable "
            "server -- see docker-compose.test.yml."
        )
    return {"default": cfg}


_resolved_test_db = _resolve_databases(
    env("TEST_DATABASE_URL", default=""),  # noqa: F405
    DATABASES["default"],  # noqa: F405
)
if _resolved_test_db is not None:
    DATABASES = _resolved_test_db
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_settings_test_db.py -p no:warnings`
Expected: 5 passed.

- [ ] **Step 5: Falsify the tests — required, do not skip**

Delete the `if tuple(cfg.get(k) ...)` block. Run the tests again.
Expected: `test_pointing_at_the_dev_instance_is_rejected` FAILS. Restore the block.

Then change `if not env_value:` to `if False:`. Run again.
Expected: `test_empty_value_means_no_override` FAILS. Restore.

A test that stays green under both mutations is not testing anything — fix it before moving on.

- [ ] **Step 6: Verify the unset path is unchanged**

Run:
```bash
uv run python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test')
django.setup()
from django.conf import settings
d = settings.DATABASES['default']
print(d['HOST'], d['PORT'], d['NAME'])
"
```
Expected: `localhost 5432 libli` — the `.env` value, untouched.

- [ ] **Step 7: Verify the set path reaches the container**

Run:
```bash
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli" uv run pytest tests/test_smoke.py -p no:warnings --verbosity=0
```
Expected: 1 passed.

- [ ] **Step 8: Lint, then commit**

```bash
uv run ruff check config/settings/test.py tests/test_settings_test_db.py
uv run ruff format --check config/settings/test.py tests/test_settings_test_db.py
git add config/settings/test.py tests/test_settings_test_db.py
git commit -m "feat: optional TEST_DATABASE_URL override for the disposable test server"
```

---

### Task 3: Adoption notice

**Files:**
- Modify: `conftest.py` (repo root — NOT `tests/conftest.py`)
- Test: `tests/test_test_db_notice.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_should_emit_test_db_notice(*, is_worker: bool, has_e2e_items: bool, env: Mapping[str, str]) -> bool` and the constant `TEST_DB_NOTICE: str` in the root `conftest`.

**Why the root conftest.** Three e2e files live outside `tests/` — `notifications/tests/test_e2e_bell.py`, `test_e2e_email_prefs.py`, `test_e2e_notifications.py` — and a directory conftest loads only for its own subtree. (`integrations/tests/test_e2e.py` is **not** e2e despite the name: its `pytestmark` is `django_db` and it collects nothing under `-m e2e`.)

**Why `is_worker` is a parameter rather than read inside the hook:** it makes the xdist guard falsifiable by a plain unit test. A guard only reachable under `-n` would otherwise need a subprocess to break, and the repo has been bitten before by assertions that cannot fail.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_test_db_notice.py`:

```python
"""The notice that nudges developers onto the tuned test database."""

from conftest import TEST_DB_NOTICE
from conftest import _should_emit_test_db_notice

BASE = {"is_worker": False, "has_e2e_items": True, "env": {}}


def _emit(**overrides):
    return _should_emit_test_db_notice(**{**BASE, **overrides})


def test_emits_for_an_e2e_run_with_no_test_database_configured():
    assert _emit() is True


def test_silent_in_an_xdist_worker():
    # Without this the notice prints once per worker, or not at all.
    assert _emit(is_worker=True) is False


def test_silent_on_a_unit_only_run():
    assert _emit(has_e2e_items=False) is False


def test_silent_when_the_test_database_is_already_configured():
    assert _emit(env={"TEST_DATABASE_URL": "postgres://libli@127.0.0.1:55433/libli"}) is False


def test_silent_under_ci():
    # CI sets DATABASE_URL but not TEST_DATABASE_URL, so it would otherwise
    # print on every run, advising a container CI neither has nor needs.
    assert _emit(env={"CI": "true"}) is False
    assert _emit(env={"GITHUB_ACTIONS": "true"}) is False


def test_silent_when_opted_out():
    assert _emit(env={"LIBLI_NO_TEST_DB_NOTICE": "1"}) is False


def test_the_notice_names_the_command_and_the_opt_out():
    assert "docker compose -p libli-test" in TEST_DB_NOTICE
    assert "LIBLI_NO_TEST_DB_NOTICE" in TEST_DB_NOTICE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_test_db_notice.py -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'TEST_DB_NOTICE' from 'conftest'`.

- [ ] **Step 3: Implement in the root `conftest.py`**

Add `import os` to the existing imports, then append:

```python

TEST_DB_NOTICE = (
    "tip: e2e teardown TRUNCATEs 89 tables after each test. Running against the "
    "disposable tuned database makes that ~37x cheaper:\n"
    "       docker compose -p libli-test -f docker-compose.test.yml up -d --wait\n"
    "     then uncomment TEST_DATABASE_URL in your .env. "
    "Silence this with LIBLI_NO_TEST_DB_NOTICE=1."
)


def _should_emit_test_db_notice(*, is_worker, has_e2e_items, env):
    """Whether to print TEST_DB_NOTICE. Pure, so every branch is unit-testable.

    `is_worker` is passed in rather than read from the config here so the xdist
    guard can be falsified without spawning a subprocess.
    """
    if is_worker:
        return False
    if not has_e2e_items:
        return False
    if env.get("TEST_DATABASE_URL"):
        return False
    if env.get("CI") or env.get("GITHUB_ACTIONS"):
        return False
    if env.get("LIBLI_NO_TEST_DB_NOTICE"):
        return False
    return True


def pytest_collection_finish(session):
    """Nudge toward the tuned test database when an e2e run is not using it.

    A terminal-reporter line, deliberately NOT a `warnings.warn`: node IDs in the
    warnings summary have previously made an unanchored `grep FAILED` report
    failures on a green run.
    """
    config = session.config
    if not _should_emit_test_db_notice(
        is_worker=hasattr(config, "workerinput"),
        has_e2e_items=any(item.get_closest_marker("e2e") for item in session.items),
        env=os.environ,
    ):
        return
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(TEST_DB_NOTICE, yellow=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_test_db_notice.py -p no:warnings`
Expected: 8 passed.

- [ ] **Step 5: Falsify — required**

Delete the `if is_worker: return False` block. Run the tests.
Expected: `test_silent_in_an_xdist_worker` FAILS. Restore it.

- [ ] **Step 6: Verify it fires exactly once under xdist, and not otherwise**

`--collect-only` is enough — the hook runs at collection, and this takes ~9 s rather than the ~45 min a real e2e run costs.

```bash
uv run pytest -m e2e --collect-only -n 2 -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `1` — exactly one, from the controller.

```bash
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli" \
  uv run pytest -m e2e --collect-only -n 2 -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `0`.

```bash
uv run pytest tests/test_smoke.py --collect-only -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `0` (unit-only run).

- [ ] **Step 7: Lint, then commit**

```bash
uv run ruff check conftest.py tests/test_test_db_notice.py
uv run ruff format --check conftest.py tests/test_test_db_notice.py
git add conftest.py tests/test_test_db_notice.py
git commit -m "feat: nudge e2e runs toward the tuned test database"
```

---

### Task 4: Documentation

**Files:**
- Modify: `.env.example` (after the `DATABASE_URL` line, ~line 8)
- Create: `docs/development/testing.md`
- Modify: `docs/development/setup.md` (line 98 block; lines 107–108 block)
- Modify: `docs/development/conventions.md` (`## Testing`, lines 27–40; line 31; line 96)
- Modify: `README.md` (docs-index table; command block lines 59–61; line 64)

**Interfaces:**
- Consumes: the connection string from Task 1, the `.env` activation path from Task 2, `LIBLI_NO_TEST_DB_NOTICE` from Task 3.
- Produces: `docs/development/testing.md` as the single source of truth for what runs locally versus what CI gates. Part B's plan appends its affected-tests practice to this same file.

- [ ] **Step 1: Add to `.env.example`, immediately after the `DATABASE_URL` line**

```
# Optional: run the test suite against the disposable tuned server started by
# docker-compose.test.yml. Uncomment to activate. Unset, tests use DATABASE_URL
# exactly as before. This names the SERVER the test database is created on; it is
# unrelated to Django's DATABASES['default']['TEST'] dict, which configures the
# test database Django creates. Under config.settings.test this wins outright
# over DATABASE_URL. See docs/development/testing.md.
# TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli
```

- [ ] **Step 2: Create `docs/development/testing.md`**

```markdown
# Running the tests

## The two selections

`pyproject.toml` pins `addopts = "-q -m 'not e2e'"`, so a "full run" is two
commands:

```bash
uv run pytest            # unit + integration: 5,104 tests
uv run pytest -m e2e     # browser e2e: 845 tests
```

`-m e2e` is mandatory for the second. Without it every e2e test is deselected and
pytest exits **5** — which means "nothing selected", not "green".

## Use the tuned test database

e2e teardown runs `TRUNCATE ... CASCADE` over 89 tables after each of the 537
tests that take `live_server`. On a normal Postgres that statement costs
**2,881 ms**; on a server with durability off and its data directory on a tmpfs
it costs **88 ms**. Both measured.

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
```

Then uncomment `TEST_DATABASE_URL` in your `.env`. A shell export works too if
you would rather keep it per-command.

The `-p libli-test` project name is required, not cosmetic: without it Compose
names the project after the current directory, so each worktree would get its own
container.

Requires Docker Desktop. Without it, leave `TEST_DATABASE_URL` unset — that is a
supported configuration, just slower.

To silence the reminder without starting the container: `LIBLI_NO_TEST_DB_NOTICE=1`.

**The server is disposable by design.** `fsync=off` and a tmpfs data directory
mean nothing survives a restart — correct for a database pytest drops and
recreates anyway. **Never apply these settings to the instance holding your dev
or mat-pp data.** That is why it listens on 55433 rather than 5432, and only on
127.0.0.1.

### Troubleshooting

A connection error at the start of a run almost always means `TEST_DATABASE_URL`
is set but the container is not running. Start it with the command above.

### One run at a time

The container is shared by every worktree, and xdist derives the same database
names (`test_libli_gw0`, ...) in each. Two concurrent runs collide, and a
`docker compose down` or `restart` from one worktree kills another's run.

If you need concurrent runs, give each worktree its own database name in
`TEST_DATABASE_URL` (e.g. `.../libli_myworktree`). No `createdb` is needed —
Django creates the test database through a no-db cursor, verified against a
source database that did not exist. This removes the name collision but not the
restart hazard.

## What runs where

Run the affected tests locally; let CI run the full suite. CI does both
selections plus lint in about **8m45s**, in three parallel jobs, and it does not
consume your session.

Do not run the full suite locally twice in one session. The exception is a
deliberate before/after benchmark, which is a measurement, not a gate.
```

- [ ] **Step 3: Point `setup.md` at it**

After the `uv run pytest` block at line 98, and after the block at lines 107–108
(107 is `uv run playwright install chromium`, 108 is the `-m e2e` invocation),
add:

```markdown
See [`testing.md`](testing.md) for which tests to run locally, and for the
optional tuned test database that makes e2e runs substantially faster.
```

Also add Docker Desktop to the prerequisites list, marked as needed only for the
tuned test database.

- [ ] **Step 4: Rewrite `conventions.md` `## Testing` (lines 27–40)**

Three edits in that file:

1. In the `## Testing` block, replace the "Run with `uv run pytest`" guidance
   with a pointer to `testing.md`, and add: *"The test database is disposable and
   runs with `fsync=off`. Never apply those settings to the instance holding dev
   or mat-pp data."*
2. **Line 31 is factually wrong** and must be corrected while that block is open.
   It reads "Tests live in one top-level **`tests/`** package (not per-app)".
   `courses/tests/`, `integrations/tests/` and `notifications/tests/` all exist;
   `tests/` holds 505 of the 549 unit files.
3. **Line 96**, under `## Migrations & checks` — *not* under `## Testing` —
   reads "Both checks are part of the definition of done, alongside the ruff and
   pytest commands above". Amend the back-reference so it does not silently
   reinstate a local full run as the definition of done.

- [ ] **Step 5: Update `README.md`**

- Add a `testing.md` row to the docs-index table (near the `conventions.md` row
  at line 52): `| Know what to run locally vs. in CI | `docs/development/testing.md` |`
- After the command block at lines 59–61, and at **line 64** (which currently
  routes readers to `conventions.md` for "the full checks CI runs"), point at
  `testing.md` instead.

- [ ] **Step 6: Verify no stale instruction survives**

Run:
```bash
grep -rn "uv run pytest" README.md docs/development/*.md
```
Expected: every hit either lives in `testing.md`, or sits adjacent to a pointer
to `testing.md`. No file should still present a bare local full run as the
definition of done.

- [ ] **Step 7: Commit**

```bash
git add .env.example docs/development/testing.md docs/development/setup.md \
        docs/development/conventions.md README.md
git commit -m "docs: document the tuned test database and what runs locally vs CI"
```

---

### Task 5: CI tmpfs

**Files:**
- Modify: `.github/workflows/ci.yml` (the `postgres` service in the `unit` job; the `postgres` service in the `e2e` job)

**Interfaces:**
- Consumes: nothing.
- Produces: no code interface; changes CI runtime only.

**Both** services get the tmpfs. CI does **not** get the durability flags —
GitHub Actions service containers accept no `command:` key, so `-c fsync=off`
cannot be passed the way Task 1 passes it. CI therefore captures only part of the
37×.

Sizing is not Task 1's sizing: the `unit` job runs `pytest -n auto` (worker count
is whatever the runner reports) **and** runs `manage.py migrate` plus
`setup_roles` against the real `libli` database on the same mount. 2 GiB covers
both with headroom.

- [ ] **Step 1: Add the tmpfs to both services**

In each job's `services.postgres`, extend the existing `options:` block with:

```
--tmpfs /var/lib/postgresql/data:rw,size=2g,mode=1777
```

so it reads:

```yaml
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
          --tmpfs /var/lib/postgresql/data:rw,size=2g,mode=1777
```

The docker-flag form (`mode=1777`) is the form these measurements were taken
with; Task 1's Compose long-form is the separately-verified equivalent.

- [ ] **Step 2: Record the "before" baseline**

Before pushing, capture the median of the last three green `master` runs for each
job — a single observation is not a baseline, since runner allocation varies:

```bash
gh run list --workflow=ci.yml --branch=master --status=success --limit 3 --json databaseId -q '.[].databaseId' |
  while read id; do
    gh api repos/:owner/:repo/actions/runs/$id/jobs \
      -q '.jobs[] | select(.name=="unit" or .name=="e2e") | "\(.name) \(.started_at) \(.completed_at)"'
  done
```

Record both medians in the note from Task 6.

- [ ] **Step 3: Push and let CI run**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: put both test Postgres services on a tmpfs"
git push -u origin test-suite-speed
```

- [ ] **Step 4: Verify both jobs still start Postgres**

A `postgres:16` PGDATA on tmpfs is a known permissions/init edge case. If either
job goes red at "Initialize containers", the revert is to drop the `--tmpfs` line
from that job's `options:` — nothing else depends on it.

- [ ] **Step 5: Decide per job, independently**

Take three runs of each job with the tmpfs. **Keep** if
`median_after ≤ median_before × 1.05`; **drop** that job's tmpfs otherwise. The
5% tolerance exists because spec §2.3 predicts the CI gain will be roughly
neutral, and a noise-level regression should not discard the change. The two jobs
may diverge — keep in one, drop in the other.

- [ ] **Step 6: Commit any revert**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: drop tmpfs from the <unit|e2e> job (measured slower)"
```

---

### Task 6: Measure, and decide

**Files:**
- Create: `docs/superpowers/notes/2026-08-07-test-suite-timings.md`
- Modify: `docs/development/testing.md` (the recommended local commands, per the outcome)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: the recorded numbers, and the accept/reject decision for Part A.

**Cost warning — read before starting.** Spec §5.1 specifies six runs × two
draws: eight full unit runs and four full e2e runs, plausibly 8–12 hours of wall
clock. That is far larger than anything else in this plan, on a change whose
purpose is to reclaim wall clock. **This plan takes the spec's own sanctioned
reduction:** one draw for each baseline run, with a second draw taken *only* when
the first lands inside the inconclusive band of its decision rule. The gate
itself (Step 3) keeps full replication, because that is where a wrong call is
expensive.

- [ ] **Step 1: Baselines (runs 1, 3, 4)**

Launch each detached and poll the PID — a backgrounded run can otherwise be
reaped mid-flight and read as a fast finish. Between runs, drop leftover test
databases or the next dies with `DuplicateDatabase`.

```bash
uv run pytest                          # run 1: unit, single-process, no TEST_DATABASE_URL
uv run pytest -n auto                  # run 3: unit, parallel,        no TEST_DATABASE_URL
uv run pytest -m e2e --durations=0 --durations-min=0    # run 4: e2e baseline
```

`--durations-min=0` is required and `-vv` is **not** a substitute: pytest's
durations filter tests `get_verbosity() >= 2`, and `addopts`' `-q` cancels one
`-v`, so `-vv` still hides sub-5 ms entries. Measured.

Do **not** add `-q` to any of these — `addopts` supplies one already, and `-qq`
suppresses the warnings summary that Step 5 depends on.

Record for each: wall clock, worker count, `TEST_DATABASE_URL` state, exit code.
A missing exit code is not a timing.

**Cleanup between runs.** For the no-container arm the test databases sit on your
**real** Postgres, and dropping them is the one destructive action in this plan —
the command must match only `test_libli%`, and read it before running it:

```bash
psql -U libli -d postgres -c "\
SELECT datname FROM pg_database WHERE datname LIKE 'test_libli%';"
```
Review that list, then drop those names explicitly. For the container arm,
`docker compose -p libli-test -f docker-compose.test.yml down` wipes everything.

- [ ] **Step 2: Recompute the gate thresholds from run 4**

From run 4's durations, take the mean of `setup+call+teardown` for each of the
four e2e files that use no `live_server` — they pay no truncate and dilute the
full-suite ratio:

| File | e2e tests |
|---|---|
| `tests/test_e2e_math_reflow_dom.py` | 171 |
| `tests/test_table_grid_algebra.py` | 38 |
| `tests/test_link_dialog_behaviour.py` | 32 |
| `tests/test_link_apply.py` | 29 |

270 of 845 pay no truncate; 575 do. The spec's thresholds assume those 270 cost
~0.4 s each, giving a diluted ratio of 1.54. If the measured mean differs
materially, recompute **before running the gate, never after seeing its result**:

```
new_sample_threshold = 1.45 × (1.54 / new_diluted_ratio)      # and 1.30 likewise
```

- [ ] **Step 3: The gate — four draws on the 69-test sample**

```bash
uv run pytest -m e2e tests/test_e2e_tabs.py tests/test_e2e_fillgate.py \
  tests/test_e2e_guessnumber.py -n 2 -p no:warnings --verbosity=0
```

Two draws with `TEST_DATABASE_URL` unset, two with it set. Same commit, same
machine, `-n 2` fixed, toggling **only** that variable. **The container must be
running during all four draws**, including the unset arm — otherwise the arms
differ by the whole cost of the Docker Desktop VM, a confounder the size of the
effect. A `down`/`up -d --wait` cycle *between* draws is fine and is the required
cleanup for the set arm.

**Statistic: worst-case speedup = fastest before ÷ slowest after.** Both are
seconds; the quotient is dimensionless and exceeds 1 when Part A helps. (The
inverted form yields ≈0.64 and can never clear a bar above 1.)

| Worst-case speedup | Outcome |
|---|---|
| ≥ 1.45× | accept |
| 1.30× ≤ x < 1.45× | inconclusive — two more draws per arm (4 and 4), accept iff median before ÷ median after ≥ 1.45× |
| < 1.30× | reject |

Median of an even sample = mean of the two middle values. The statistic is always
the ratio of the medians, never the median of the ratios — on before `[100, 140]`
and after `[80, 60]` those give 1.71 and 1.79.

- [ ] **Step 4: Post-implementation runs (2, 5, 6)**

```bash
TEST_DATABASE_URL=... uv run pytest              # run 2: unit + container
TEST_DATABASE_URL=... uv run pytest -m e2e       # run 5: the headline full-suite magnitude
TEST_DATABASE_URL=... uv run pytest -n auto      # run 6: both levers together
```

- [ ] **Step 5: Check the suite is green and the teardown apparatus is quiet**

Grep the warnings summary for all three strings:

- `live_server still busy at teardown of` — barrier timeout
- `teardown TRUNCATE deadlocked` — deadlock retry
- `could not quiesce the browser at teardown` — the offline/blank step raised

**Blocking, with different remediations.** A *barrier timeout* means the 5 s
`DEFAULT_TIMEOUT` no longer suits the new timing profile — retune and re-run;
that is a fix, not a rejection. A *deadlock retry* or *browser-quiesce* warning
rejects Part A pending investigation, because the spec declines to touch that
machinery precisely on the assumption it stays quiescent.

Note the scope asymmetry: the barrier is function-scoped in `tests/conftest.py`
and never applies to the three notifications e2e files, but the deadlock-retry
patch is **session-scoped and monkeypatches `TransactionTestCase` globally**, so
its warning can fire for them depending on xdist distribution. Those three files
take `live_server` and pay the truncate *without* the barrier — they are the most
exposed to this change, not the least.

- [ ] **Step 6: Apply the decision rules**

| Comparison | Rule |
|---|---|
| Run 2 vs run 1 | If run 2 is **>5% slower**, `testing.md` documents `TEST_DATABASE_URL` as an **e2e-only** activation (exported per command, not set in `.env`), and Task 4's `.env.example` guidance changes to match |
| Run 3 vs run 1 | If run 3 wins by **≥1.25×**, `testing.md` documents `-n auto` as the local unit command |

| Run 2 | Run 3 | `testing.md` recommends |
|---|---|---|
| within 5% | ≥1.25× | faster of run 3 and run 6 |
| within 5% | <1.25× | single-process; `TEST_DATABASE_URL` may stay in `.env` |
| >5% slower | ≥1.25× | run 3's command — `-n auto`, no container |
| >5% slower | <1.25× | single-process, no container; container for e2e only |

**`addopts` is not touched in any branch** — it is shared with CI, where
`-n auto` is already passed explicitly, so editing it would change CI's effective
command as a side effect.

**If the gate rejects:** remove `docker-compose.test.yml` (Task 1), the settings
wiring (Task 2) and the notice (Task 3). **Keep** Task 4's docs with the
container sections excised, and keep Task 5's CI tmpfs — it is judged only by its
own rule. Part B is unaffected.

- [ ] **Step 7: Record everything and commit**

Write `docs/superpowers/notes/2026-08-07-test-suite-timings.md` with every run's
wall clock, worker count, `TEST_DATABASE_URL` state, exit code, warning counts,
the gate draws, and the resulting decisions. Name the commit measured. The spec
is pinned to `828354c9` and is **not** retro-edited with these results.

```bash
git add docs/superpowers/notes/2026-08-07-test-suite-timings.md docs/development/testing.md
git commit -m "docs: record measured test-suite timings and the Part A decision"
```

---

## Self-Review

**Spec coverage.** A1→Task 1; A2→Task 2; A3→Task 4; A4→Task 5; A5→Task 3;
§5.1/§5.2/§5.3/§5.4/§5.5→Task 6. §7's risks map to Task 1 Steps 3–4 (tmpfs,
durability), Task 2 Step 5 (dev-instance guard), Task 5 Step 4 (CI start
failure), Task 6 Step 1 (destructive drop). Part B (§4 B1–B3) is deliberately out
of scope — separate plan.

**Two deliberate deviations from the spec, both flagged in place:**

1. **Task 2's guard compares against `DATABASE_URL`** instead of merely requiring
   "an explicit port". The spec's rule would not reject
   `postgres://libli@127.0.0.1:5432/libli`, which is the exact case it was
   written to catch — 5432 *is* an explicit port.
2. **Task 6 Step 1 takes one draw per baseline run** rather than two, escalating
   only inside the inconclusive band. The spec's §5.1 flags its own 8–12 hour
   cost and delegates this call to the plan.

**Placeholder scan:** no TBD/TODO. Every code step carries the actual content;
every verification step names the command and the expected output.

**Type consistency:** `_resolve_databases(env_value, current) -> dict | None`
used identically in Task 2's tests, implementation and call site.
`_should_emit_test_db_notice(*, is_worker, has_e2e_items, env) -> bool` and
`TEST_DB_NOTICE` used identically in Task 3's tests and implementation. The
connection string `postgres://libli@127.0.0.1:55433/libli` is byte-identical in
Tasks 1, 2, 3 and 4.
