# Tuned Test Database (Part A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut local e2e wall clock by running tests against a disposable Postgres with durability disabled, where the per-test `TRUNCATE … CASCADE` costs ~80 ms instead of 2,881 ms.

**Architecture:** A `docker-compose.test.yml` service on a tmpfs with `fsync=off`, published on loopback port 55433. `config/settings/test.py` reads an optional `TEST_DATABASE_URL` and overrides `DATABASES` only when set, so the change is a no-op for anyone who has not started the container. An end-of-run notice nudges adoption. CI gets the tmpfs but not the durability flags (service containers accept no `command:`).

**Tech Stack:** Docker Compose v2.17+ (this machine reports v5.1.2), postgres:16, django-environ, pytest-django, pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-08-07-test-suite-wall-clock-design.md`. Part B (affected-tests workflow) is a separate plan — the two share no code, and spec §5.3 keeps Part B when Part A reverts.

## Global Constraints

- **All shell blocks in this plan are Git Bash**, not PowerShell. `VAR=value cmd` prefixes, `grep`, `2>&1 |` on native executables and `while read` loops are parse errors or behave differently under `powershell.exe`. Where a PowerShell form is needed it is given explicitly.
- Port **55433**, bound to **`127.0.0.1`** only — never `0.0.0.0`. The server is trust-auth superuser.
- Compose project name **`libli-test`** in every documented command (`-p libli-test`), so every worktree addresses one container.
- tmpfs **1 GiB** (`1073741824`), `mode: 01777`. Verified: the long-form `volumes:` syntax mounts at exactly 1.0 G and Postgres starts healthy in 3.6 s.
- **Local worker ceiling: 8.** The tmpfs and `max_connections` are sized for `-n 8` (this machine reports `nproc` = 8, so `-n auto` = 8). If a machine's `-n auto` exceeds 8, re-check both — see Task 2 Step 1.
- `TEST_DATABASE_URL` unset MUST leave behaviour byte-identical to today.
- `# noqa: F405` on any line using a star-imported name from `config.settings.base` (`env`, `DATABASES`). Ruff's `F` rule set is selected in `pyproject.toml`; the CI `lint` job runs `ruff check .` and fails otherwise. Ruff's `I` (isort) rules are also selected — respect import grouping.
- Never add a second `-q` to a pytest **run** — `addopts` already carries one, and `-qq` suppresses the warnings summary that the blocking teardown check reads. **`--collect-only` is the deliberate exception:** the `file.py: N` per-file format exists only at `-qq`, and a collection has no warnings summary to lose.
- Run tests with `uv run`; `pytest`/`ruff`/`python` are not on PATH. `psql` is likewise not guaranteed — Task 7 gives a `docker exec` alternative.
- `-m e2e` is mandatory for e2e runs, or they silently deselect and exit 5.

## Measured constants used throughout

| Quantity | Value | Where measured |
|---|---|---|
| `TRUNCATE … CASCADE`, 89 tables, default durability | **2,881 ms** | raw `docker run` postgres:16 |
| Same, `fsync=off` + tmpfs, raw `docker run` | **78 ms** | spec §2.1 |
| Same, `fsync=off` + tmpfs, via `docker-compose.test.yml` | **88 ms** | this plan, Task 2 verification |

Use **"~33×"** in user-facing copy (2,881 / 88, the conservative compose figure — the configuration developers actually run). The spec's 37× is 2,881 / 78 from the raw-`docker run` variant. Both are real; they differ by the Compose networking path. Do not mix them.

## Deviations from the spec — three, all deliberate

1. **Task 3's guard compares against `DATABASE_URL`** instead of requiring "an explicit port". The spec's rule would not reject `postgres://libli@127.0.0.1:5432/libli`, the exact case it exists for — 5432 *is* an explicit port. **The comparison must normalise host aliases and ignore `NAME`**: measured, `.env` resolves to `HOST="localhost"` while that URL resolves to `HOST="127.0.0.1"`, so a raw string compare lets the dangerous value straight through. Matching on `NAME` too would be worse still — pointing at the dev *server* under a different database name is equally wrong.
2. **Task 4 emits the notice from `pytest_terminal_summary`, not `pytest_collection_finish`,** and drops the `is_worker` guard. Spec §A5 assumed the controller collects; it does not. **Measured:** `xdist/dsession.py` returns `True` from `pytest_collection` (a `firstresult` hook), so `perform_collect` — and therefore `pytest_collection_finish` — never runs on the controller. Under `-n 2` the spec's hook fires in workers only, where the guard suppresses it: the notice would have printed in exactly zero xdist runs.

   **This costs something, and the cost is acknowledged rather than hidden.** A collection-time notice could still save the current run; a terminal-summary one arrives after the developer has already paid the 40+ minutes. Spec §A5's whole purpose is that "the entire win is gated behind a developer starting a container", so arriving late is a real reduction in the deliverable's value. Task 4 therefore emits **twice**: a cheap pre-run line from `pytest_configure` when `-m` mentions `e2e`, plus the terminal-summary line as the catch-all that also covers `-k` and direct-nodeid runs, which `markexpr` cannot see.
3. **Baselines are measured after implementation, not before** (spec §5.1 sequences them first). This is safe because Task 3 Step 7 proves the unset path is byte-identical to today, and the Task 4 notice adds one line at terminal summary. Reordering would front-load hours of measurement before any code exists.

4. **Spec §5.4's mandated mutant for the xdist worker guard is unsatisfiable, and is not attempted.** The spec requires "remove the worker guard, require red", with an xdist run to make it meaningful. Two things changed that: the guard is gone from `pytest_terminal_summary` entirely (that hook never runs in a worker), and the one that remains — in `pytest_sessionstart` — is belt-and-braces, because a worker has no terminal reporter and the emission would degrade silently anyway. **Measured:** deleting it and running `-n 2 -m e2e` still yields exactly one notice line, so no check can turn red on it. It is kept as defensive clarity, and Task 4's mutation table deliberately does **not** claim to cover it — an unfalsifiable mutant listed as satisfied would be worse than an acknowledged gap.

---

### Task 1: The compose service

**Files:**
- Create: `docker-compose.test.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a Postgres reachable at `postgres://libli@127.0.0.1:55433/libli`, container `libli-test-db`, compose project `libli-test`.

- [ ] **Step 1: Check the Compose version before relying on `--wait`**

Run: `docker compose version`
Expected: `v2.17` or higher. If lower, `--wait` is unavailable and every start command below must become `up -d` followed by the `pg_isready` poll in Step 3.

- [ ] **Step 2: Create `docker-compose.test.yml`**

```yaml
# Disposable Postgres for running the test suite fast.
#
# Durability is deliberately OFF and the data directory is a tmpfs: nothing on
# this server survives a restart, which is correct for a database pytest drops
# and recreates anyway. MEASURED: TRUNCATE of the suite's 89 tables costs
# 2,881 ms on a normal server and 88 ms here -- ~33x.
#
# NEVER apply these settings to the instance holding dev or mat-pp data.
# Port 55433 (not 5432) and the loopback binding are both deliberate.
name: libli-test                     # so a forgotten `-p` still hits this project
services:
  test-db:
    image: postgres:16
    container_name: libli-test-db
    shm_size: 256mb                  # default 64m surfaces as "could not resize
                                     # shared memory segment" under 8 workers,
                                     # which reads as a flaky test, not a config
                                     # problem
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
      - -c
      - max_connections=200           # 8 xdist workers x pooled connections, with headroom
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

- [ ] **Step 3: Start it and verify it reports healthy**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
```
Expected: ends with `Container libli-test-db Healthy`, exit 0, under ~10 s.

Fallback if Step 1 showed Compose < v2.17:
```bash
docker compose -p libli-test -f docker-compose.test.yml up -d
until docker exec libli-test-db pg_isready -U libli; do sleep 1; done
```

- [ ] **Step 4: Verify the tmpfs size AND that the `mode:` key parsed**

```bash
MSYS_NO_PATHCONV=1 docker exec libli-test-db df -h /var/lib/postgresql/data | tail -1
docker inspect libli-test-db --format '{{json .HostConfig.Mounts}}'
```
Expected: a `tmpfs` row showing `1.0G`; and
`"TmpfsOptions":{"SizeBytes":1073741824,"Mode":1023}` — **1023 is decimal for
0o1777**, which is what confirms the `mode:` key parsed.

Three traps, each measured, which is why the probe is `docker inspect` and not
something more obvious:

- **`stat -c '%a'` returns `700`, not `1777`, on a *correct* container.** The
  `postgres:16` entrypoint runs `chmod 00700 "$PGDATA"` after the mount, exactly
  as this plan states elsewhere. Asserting `1777` there fails on a good build.
- **`.HostConfig.Tmpfs` is `null`** for the long `volumes:` form — the parsed
  options live under `.HostConfig.Mounts`.
- **`/proc/mounts` omits `mode=`** because 1777 is the tmpfs default, so it
  cannot distinguish "parsed" from "ignored".

**`MSYS_NO_PATHCONV=1` is required on every `docker exec` naming a
container-absolute path.** Without it Git Bash rewrites `/var/lib/postgresql/data`
to `C:/Program Files/Git/var/lib/postgresql/data` and the command fails with
`No such file or directory`. (`docker inspect` takes no such path, so it needs no
prefix.)

**Fallback**, if `Mode` is not 1023 *or* Postgres refuses to start: add
`PGDATA: /var/lib/postgresql/data/pgdata` to `environment:` and restart. Postgres
then creates its own 0700 directory inside the tmpfs and the mount's mode stops
mattering.

- [ ] **Step 5: Verify the durability flags took effect**

```bash
MSYS_NO_PATHCONV=1 docker exec libli-test-db psql -U libli -d libli -tAc \
  "show fsync; show synchronous_commit; show full_page_writes; show max_connections"
```
Expected: `off`, `off`, `off`, `200`.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.test.yml
git commit -m "feat: add disposable tuned test database compose service"
```

---

### Task 2: Verify the compose service actually delivers the win

**Files:** none — this task only measures. It exists as its own task because a reviewer should be able to reject Task 1 on the numbers before any application code is written.

- [ ] **Step 1: Confirm this machine's `-n auto` worker count matches the sizing**

```bash
nproc
```
Expected: `8`. If higher, revisit the tmpfs size and `max_connections` in Task 1 before continuing (Global Constraints, "Local worker ceiling").

- [ ] **Step 2: Populate the database to the state spec §5.4 pins, then time the truncate**

**The state matters and must not be empty.** Spec §5.4 pins it as "a freshly
migrated test database immediately after one e2e test's fixtures" precisely
because "an empty-table truncate is not comparable to a populated one". Timing
against `tests/test_smoke.py` alone would measure 89 empty tables and produce a
flattering number that the 2,881 ms comparator does not match.

**Use `DATABASE_URL`, not `TEST_DATABASE_URL`.** This task runs *before* Task 3,
which is what teaches `config/settings/test.py` to read the new variable — until
then it is inert, and the run would populate a `test_libli` on the developer's
**real** Postgres while the `docker exec` below died with
`FATAL: database "test_libli" does not exist`. `base.py` reads `DATABASE_URL`
today, and `read_env` uses `setdefault`, so a real environment variable wins over
`.env`.

```bash
DATABASE_URL="postgres://libli@127.0.0.1:55433/libli" \
  uv run pytest tests/test_e2e_catalog.py -m e2e --reuse-db -p no:warnings --verbosity=0

MSYS_NO_PATHCONV=1 docker exec libli-test-db psql -U libli -d test_libli -q -c "\timing on" -c \
"DO \$\$ DECLARE s text; BEGIN
   SELECT 'TRUNCATE ' || string_agg(format('%I.%I',schemaname,tablename), ', ') || ' CASCADE'
   INTO s FROM pg_tables WHERE schemaname='public';
   EXECUTE s;
 END \$\$;"
```
Expected: `1 passed`, then a `Time:` line under **150 ms**. If it reports
seconds, the durability flags are not in effect — stop and fix Task 1.

`--reuse-db` is required: without it pytest-django drops the test database at
session teardown and the `psql` call finds nothing to truncate.

- [ ] **Step 3: Record the measured truncate time and its state**

Note both the milliseconds **and** that the state was "after one `live_server`
e2e test", for Task 7's results note. Task 7 Step 7 re-times the same way, so
that step is a replication rather than a different measurement. This is the
number the whole change rests on.

- [ ] **Step 4: Record the measured values, and update the only file that exists yet**

The plan ships `88 ms` and `~33×` as placeholders from a pre-plan probe. Task 2's
pass band is anything under 150 ms — a value at which "~33×" would be wrong by
nearly a factor of two. Compute `multiplier = round(2881 / measured_ms)` and:

- update `docker-compose.test.yml`'s header comment ("88 ms here -- ~33x");
- update this plan's **Measured constants** table, so the source reads "measured
  at Task 2, populated state", and the later tasks have one place to copy from.

**`conftest.py` and `docs/development/testing.md` cannot be edited here** — Task 4
has not yet created `TEST_DB_NOTICE` and Task 5 has not yet created `testing.md`.
Each of those tasks carries its own substitution instruction at the point the file
comes into existence.

---

### Task 3: Settings wiring

**Files:**
- Modify: `config/settings/test.py` (append after line 26)
- Test: `tests/test_settings_test_db.py` (create)

**Interfaces:**
- Consumes: `env` and `DATABASES` from `config.settings.base` (star import).
- Produces: `_resolve_databases(env_value: str, current: dict) -> dict | None` in `config.settings.test`. Returns `None` for "no override"; otherwise a full `DATABASES`-shaped dict with a `"default"` key. Raises `django.core.exceptions.ImproperlyConfigured` on a non-empty value that is not a usable *separate* postgres server.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_test_db.py`:

```python
"""`TEST_DATABASE_URL` resolution for the disposable test server.

Tests the pure helper directly. Do NOT re-import `config.settings.test` the way
`test_settings_production.py` re-imports production: that pattern is safe only
because production is not the active settings module. Re-executing test.py runs
its `TEMPLATES[0]["DIRS"] = [...]` line again, and because `base` is not popped,
`TEMPLATES[0]` is the same dict object `django.conf.settings` references -- every
re-import appends another copy of the test-templates dir to live global state.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings.test import _resolve_databases

# Mirrors the real .env, which uses the "localhost" spelling.
DEV = {"HOST": "localhost", "PORT": 5432, "NAME": "libli"}
TUNED = "postgres://libli@127.0.0.1:55433/libli"


def test_empty_value_means_no_override():
    assert _resolve_databases("", DEV) is None


def test_valid_url_yields_a_databases_dict():
    resolved = _resolve_databases(TUNED, DEV)

    assert set(resolved) == {"default"}
    assert resolved["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert resolved["default"]["PORT"] == 55433


def test_unparseable_value_is_rejected():
    # django-environ returns {} rather than raising for garbage. MEASURED: the
    # resulting config has no PORT either, so the port check is what actually
    # fires -- assert the specific message rather than merely "it raised".
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("not-a-url", DEV)

    assert "explicit port" in str(exc.value)


def test_a_non_postgres_url_without_a_port_is_rejected():
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("sqlite:///tmp/x.db", DEV)

    assert "explicit port" in str(exc.value)


def test_a_non_postgres_url_WITH_a_port_is_rejected_by_the_engine_check():
    # The only test that pins the ENGINE check. MEASURED: without it, this URL
    # is silently ACCEPTED -- it has an explicit non-5432 port on a loopback
    # host, so neither the port check nor the same-server check catches it.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("mysql://libli@127.0.0.1:3306/libli", DEV)

    assert "must be a postgres" in str(exc.value)


def test_pointing_at_the_dev_instance_is_rejected():
    # The whole point of the guard: this parses cleanly and would run the suite
    # against the developer's real database.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("postgres://libli@localhost:5432/libli", DEV)

    # Assert the distinctive fragment: every message in this helper starts with
    # "TEST_DATABASE_URL", which contains "DATABASE_URL" as a substring, so
    # asserting on that would not discriminate between the three messages.
    assert "points at the same server" in str(exc.value)


def test_the_dev_instance_is_rejected_under_a_host_alias():
    # MEASURED: .env spells the host "localhost" but this URL spells it
    # "127.0.0.1", so a raw string compare passes and the suite runs against the
    # developer's real Postgres. This is the spec's own exemplar.
    with pytest.raises(ImproperlyConfigured):
        _resolve_databases("postgres://libli@127.0.0.1:5432/libli", DEV)


def test_the_dev_server_is_rejected_even_under_a_different_database_name():
    # Same server, different NAME: still the dev instance, still wrong.
    with pytest.raises(ImproperlyConfigured):
        _resolve_databases("postgres://libli@127.0.0.1:5432/something_else", DEV)


def test_a_port_less_url_is_rejected():
    # MEASURED: this parses to PORT '', so the same-server check cannot catch
    # it -- yet Django would connect on the default 5432, the dev instance.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("postgres://libli@localhost/libli", DEV)

    assert "explicit port" in str(exc.value)
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

# "localhost", "127.0.0.1", "::1" and "" all name the same machine. Comparing the
# raw strings would let postgres://...@127.0.0.1:5432/... past a .env that spells
# the same host "localhost" -- MEASURED, and exactly the case the guard exists for.
_LOOPBACK = {"", "localhost", "127.0.0.1", "::1"}


def _same_server(a: dict, b: dict) -> bool:
    """Whether two DATABASES configs name the same Postgres server.

    Compares (host, port) only. NAME is deliberately excluded: pointing at the
    dev server under a different database name is equally wrong, because the
    test run would create and drop databases on the developer's real instance.
    """

    def host(cfg):
        h = (cfg.get("HOST") or "").lower()
        return "localhost" if h in _LOOPBACK else h

    return (host(a), a.get("PORT")) == (host(b), b.get("PORT"))


def _resolve_databases(env_value: str, current: dict) -> dict | None:
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
    # ORDER MATTERS: the PORT check runs FIRST. Both "not-a-url" and
    # "sqlite:///tmp/x.db" parse to an empty PORT, so with the ENGINE check
    # first they raise the postgres message instead -- MEASURED, and it makes
    # two of this task's own tests fail.
    if not cfg.get("PORT"):
        # MEASURED: db_url_config("postgres://libli@localhost/libli") yields
        # PORT ''. Django would then connect on the default 5432 -- the dev
        # instance -- and _same_server below would not catch it, because ''
        # != 5432. An explicit port is the only safe form here.
        raise ImproperlyConfigured(
            "TEST_DATABASE_URL must name an explicit port (the tuned server "
            f"listens on 55433, not the default 5432); got {env_value!r}"
        )
    if cfg.get("ENGINE") != "django.db.backends.postgresql":
        raise ImproperlyConfigured(
            f"TEST_DATABASE_URL must be a postgres:// URL; got {env_value!r}"
        )
    if _same_server(cfg, current):
        raise ImproperlyConfigured(
            "TEST_DATABASE_URL points at the same server as DATABASE_URL "
            f"({env_value!r}). It must be a separate, disposable server -- "
            "see docker-compose.test.yml."
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
Expected: **9 passed**.

- [ ] **Step 5: Falsify the tests — required, do not skip**

Six mutations, so that **every** test has a named victim — an unmutated test is
an unproven one:

| # | Mutation | Must go RED |
|---|---|---|
| 1 | Delete the `if _same_server(cfg, current):` block | `test_pointing_at_the_dev_instance_is_rejected` |
| 2 | In `_same_server`, replace `host()`'s body with `return cfg.get("HOST")` | `test_the_dev_instance_is_rejected_under_a_host_alias` **and** `test_the_dev_server_is_rejected_even_under_a_different_database_name` — both spell the host `127.0.0.1`. Only `test_pointing_at_the_dev_instance_is_rejected`, which spells it `localhost`, stays green: that asymmetry is exactly why normalisation matters |
| 3 | Make `_same_server` compare `NAME` too | `test_the_dev_server_is_rejected_even_under_a_different_database_name` |
| 4 | Delete the `if not cfg.get("PORT"):` block | `test_a_port_less_url_is_rejected`, `test_unparseable_value_is_rejected`, `test_a_non_postgres_url_without_a_port_is_rejected` |
| 5 | Delete the `if cfg.get("ENGINE") != …` block | `test_a_non_postgres_url_WITH_a_port_is_rejected_by_the_engine_check` — **and only that one** |
| 6 | Change `if not env_value:` to `if False:` | `test_empty_value_means_no_override` |

Restore after each. `test_valid_url_yields_a_databases_dict` is the positive
control — it must stay green throughout.

**Mutation 5 is the subtle one, and two earlier drafts of this plan got it
wrong.** MEASURED: with the ENGINE block deleted, `"not-a-url"` and
`"sqlite:///tmp/x.db"` *still* raise — both parse to an empty `PORT`, and the
port check (which now runs first, see Step 3) catches them. Only a URL with an
explicit non-5432 port on a loopback host isolates the engine check, which is why
`test_a_non_postgres_url_WITH_a_port_is_rejected_by_the_engine_check` exists.
Without it, mutation 5 leaves every test green and the check is unproven — while
`mysql://libli@127.0.0.1:3306/libli` would be silently accepted.

**This whole table depends on the PORT-before-ENGINE ordering in Step 3.** With
the checks the other way round, `test_unparseable_value_is_rejected` and
`test_a_non_postgres_url_without_a_port_is_rejected` fail outright — verified by
executing the helper against these exact assertions: ENGINE-first gives
`2 failed, 7 passed`; PORT-first gives `9 passed`.

- [ ] **Step 6: Verify the ACTIVATED path lands on port 55433**

Passing tests alone would not prove this — they would also pass if the override
silently failed and the run used the local server. Assert the resolved port:

```bash
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli" uv run python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test')
django.setup()
from django.conf import settings
d = settings.DATABASES['default']
print(d['HOST'], d['PORT'], d['NAME'])
"
```
Expected: `127.0.0.1 55433 libli`.

Then confirm a real run actually creates its database on that server. **`--reuse-db`
is required**: without it pytest-django drops the test database at session
teardown, so the `psql` call — which runs after pytest exits — returns 0 on a
perfectly correct build.

**Wipe the container first**, or this assertion cannot fail: Task 2 Step 2 already
created `test_libli` on it with `--reuse-db`, and nothing since has torn it down,
so the count would read `>= 1` whether or not `TEST_DATABASE_URL` resolved. The
tmpfs makes the wipe instant.

```bash
COMPOSE="-p libli-test -f docker-compose.test.yml"
docker compose $COMPOSE down && docker compose $COMPOSE up -d --wait

TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli" \
  uv run pytest tests/test_smoke.py --reuse-db -p no:warnings --verbosity=0
MSYS_NO_PATHCONV=1 docker exec libli-test-db psql -U libli -d postgres -tAc \
  "SELECT count(*) FROM pg_database WHERE datname LIKE 'test_libli%'"
```
Expected: `1 passed`, then a count `>= 1`. If the count is 0 and the tests
passed, the override did not take effect.

- [ ] **Step 7: Verify the UNSET path is unchanged**

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
Expected: `localhost 5432 libli` — the `.env` value, untouched. This step is what
licenses deviation 3 (measuring baselines after implementation).

- [ ] **Step 8: Lint, then commit**

```bash
uv run ruff check config/settings/test.py tests/test_settings_test_db.py
uv run ruff format --check config/settings/test.py tests/test_settings_test_db.py
git add config/settings/test.py tests/test_settings_test_db.py
git commit -m "feat: optional TEST_DATABASE_URL override for the disposable test server"
```

---

### Task 4: Adoption notice

**Files:**
- Modify: `conftest.py` (repo root — NOT `tests/conftest.py`)
- Test: `tests/test_test_db_notice.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_should_emit_test_db_notice(*, has_e2e_items: bool, env: Mapping[str, str]) -> bool` and the constant `TEST_DB_NOTICE: str` in the root `conftest`.

**Why the root conftest.** Three e2e files live outside `tests/` —
`notifications/tests/test_e2e_bell.py`, `test_e2e_email_prefs.py`,
`test_e2e_notifications.py` — and a directory conftest loads only for its own
subtree. (`integrations/tests/test_e2e.py` is **not** e2e despite the name: its
`pytestmark` is `django_db` and it collects nothing under `-m e2e`.)

**Why `pytest_terminal_summary` and not `pytest_collection_finish`.** MEASURED
with a probe harness: under a real `-n 2` run, `pytest_collection_finish` fires
in **workers only** — `xdist/dsession.py` returns `True` from `pytest_collection`
(a `firstresult` hook), so the controller never calls `perform_collect`. The spec
assumed otherwise. `pytest_terminal_summary` fires **once, on the controller, in
both `-n 2` and single-process**, and the reports it can see carry the `e2e`
marker in their `keywords`. Because it never runs in a worker, no `is_worker`
guard is needed — the spec's guard was dead code protecting against a case that
cannot occur.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_test_db_notice.py`:

```python
"""The notice that nudges developers onto the tuned test database."""

import pytest

from conftest import TEST_DB_NOTICE
from conftest import _markexpr_selects_e2e
from conftest import _should_emit_test_db_notice

BASE = {"has_e2e_items": True, "env": {}}
TUNED = "postgres://libli@127.0.0.1:55433/libli"


def _emit(**overrides):
    return _should_emit_test_db_notice(**{**BASE, **overrides})


def test_emits_for_an_e2e_run_with_no_test_database_configured():
    assert _emit() is True


def test_silent_on_a_unit_only_run():
    assert _emit(has_e2e_items=False) is False


def test_silent_when_the_test_database_is_already_configured():
    # Bound to a constant deliberately: inline, this line is 94 chars against
    # ruff's default line-length of 88, so `ruff check` (E501) and
    # `ruff format --check` both fail -- as would CI's `ruff check .`.
    assert _emit(env={"TEST_DATABASE_URL": TUNED}) is False


def test_silent_under_ci():
    # CI sets DATABASE_URL but not TEST_DATABASE_URL, so it would otherwise
    # print on every run, advising a container CI neither has nor needs.
    assert _emit(env={"CI": "true"}) is False


def test_silent_under_github_actions():
    assert _emit(env={"GITHUB_ACTIONS": "true"}) is False


def test_silent_when_opted_out():
    assert _emit(env={"LIBLI_NO_TEST_DB_NOTICE": "1"}) is False


def test_the_notice_names_the_command_and_the_opt_out():
    assert "docker compose -p libli-test" in TEST_DB_NOTICE
    assert "LIBLI_NO_TEST_DB_NOTICE" in TEST_DB_NOTICE


@pytest.mark.parametrize(
    "markexpr,selects",
    [
        ("e2e", True),
        (" e2e ", True),
        # The default addopts value. `"e2e" in "not e2e"` is True, so a
        # substring test would fire the pre-run notice on every unit run.
        ("not e2e", False),
        ("", False),
        (None, False),
    ],
)
def test_markexpr_selection(markexpr, selects):
    assert _markexpr_selects_e2e(markexpr) is selects
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_test_db_notice.py -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'TEST_DB_NOTICE' from 'conftest'`.

- [ ] **Step 3: Implement in the root `conftest.py`**

Add the stdlib imports as their **own block above** the existing third-party
imports, separated by a blank line — appending them to the `pytest` /
`django.conf` / `django.utils.translation` block fails ruff's `I001`, which the
CI `lint` job runs as `ruff check .`:

```python
import os
from collections.abc import Mapping

import pytest
...
```

Then append at the end of the file:

```python

TEST_DB_NOTICE = (
    # SUBSTITUTE the multiplier measured at Task 2 Step 4 for "~33x" below.
    "tip: e2e teardown TRUNCATEs 89 tables after each test. Running against the "
    "disposable tuned database makes that ~33x cheaper:\n"
    "       docker compose -p libli-test -f docker-compose.test.yml up -d --wait\n"
    "     then uncomment TEST_DATABASE_URL in your .env. "
    "Silence this with LIBLI_NO_TEST_DB_NOTICE=1."
)


def _should_emit_test_db_notice(*, has_e2e_items: bool, env: Mapping[str, str]) -> bool:
    """Whether to print TEST_DB_NOTICE. Pure, so every branch is unit-testable."""
    if not has_e2e_items:
        return False
    if env.get("TEST_DATABASE_URL"):
        return False
    if env.get("CI") or env.get("GITHUB_ACTIONS"):
        return False
    if env.get("LIBLI_NO_TEST_DB_NOTICE"):
        return False
    return True


def _markexpr_selects_e2e(markexpr: str) -> bool:
    """Whether `-m <markexpr>` selects e2e tests. Substring matching is WRONG here.

    MEASURED: the default `addopts` sets markexpr to "not e2e", and
    `"e2e" in "not e2e"` is True -- so a substring test fires the notice on every
    unit run. Deliberately conservative: only the exact `-m e2e` form counts.
    Anything subtler (`-k`, a nodeid, a compound expression) falls through to
    `pytest_terminal_summary`, which decides from the reports themselves.
    """
    return (markexpr or "").strip() == "e2e"


def pytest_sessionstart(session):
    """Pre-run nudge, so an e2e run can still be saved rather than merely mourned.

    `pytest_sessionstart`, NOT `pytest_configure`: MEASURED, the terminal reporter
    is not yet registered when a rootdir conftest's `pytest_configure` runs (that
    hook is dispatched LIFO and the builtin terminal plugin registers after the
    conftest), so `get_plugin("terminalreporter")` returns None there and the
    emission is dead code. At sessionstart it is present, on the controller, in
    both single-process and `-n 2`.
    """
    config = session.config
    if hasattr(config, "workerinput"):
        return
    if not _markexpr_selects_e2e(config.option.markexpr):
        return
    if not _should_emit_test_db_notice(has_e2e_items=True, env=os.environ):
        return
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:  # `-p no:terminal` -- degrade rather than crash
        reporter.write_line(TEST_DB_NOTICE, yellow=True)
        config._libli_test_db_notice_shown = True


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Nudge toward the tuned test database when an e2e run is not using it.

    `pytest_terminal_summary`, NOT `pytest_collection_finish`: under xdist the
    controller never calls `perform_collect` (dsession returns True from the
    firstresult `pytest_collection` hook), so a collection hook fires in workers
    only. This one fires exactly once, on the controller, in both modes.

    A terminal-reporter line, deliberately NOT a `warnings.warn`: node IDs in the
    warnings summary have previously made an unanchored `grep FAILED` report
    failures on a green run.
    """
    has_e2e = any(
        "e2e" in (getattr(report, "keywords", {}) or {})
        # "deselected" MUST be excluded. MEASURED: it holds collected-but-
        # deselected items, whose keywords still carry `e2e` -- and `addopts`
        # deselects all 845 e2e tests on every plain `uv run pytest`. Including
        # it makes the notice fire on every unit run.
        for key, reports in terminalreporter.stats.items()
        if key != "deselected"
        for report in reports
    )
    if getattr(config, "_libli_test_db_notice_shown", False):
        return  # already said it up front; don't say it twice
    if _should_emit_test_db_notice(has_e2e_items=has_e2e, env=os.environ):
        terminalreporter.write_line(TEST_DB_NOTICE, yellow=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_test_db_notice.py -p no:warnings`
Expected: **12 passed** (7 helper tests + 5 parametrized markexpr cases).

- [ ] **Step 5: Falsify — required**

Every test gets a named victim:

| # | Mutation | Must go RED |
|---|---|---|
| 1 | Delete `if env.get("TEST_DATABASE_URL"): return False` | `test_silent_when_the_test_database_is_already_configured` |
| 2 | Delete `if not has_e2e_items: return False` | `test_silent_on_a_unit_only_run` |
| 3 | Delete `if env.get("CI") or env.get("GITHUB_ACTIONS"): return False` | `test_silent_under_ci` **and** `test_silent_under_github_actions` — the branch that would otherwise nag on every CI run |
| 4 | Delete `if env.get("LIBLI_NO_TEST_DB_NOTICE"): return False` | `test_silent_when_opted_out` |
| 5 | Remove `docker compose -p libli-test` from `TEST_DB_NOTICE` | `test_the_notice_names_the_command_and_the_opt_out` |
| 6 | Change `_markexpr_selects_e2e` to `return "e2e" in (markexpr or "")` | `test_markexpr_selection[not e2e-False]` — the substring form that would nag on every unit run |

Restore after each. `test_emits_for_an_e2e_run_with_no_test_database_configured`
is the positive control.

- [ ] **Step 6: Verify it fires exactly once in a REAL xdist run**

`--collect-only` must NOT be used here: `xdist/plugin.py` registers `DSession`
only when `collectonly` is false, so `--collect-only -n 2` runs in-process and
would report success even on a build where the notice never fires under real
xdist. That is precisely the failure this step exists to catch.

Use the smallest real e2e file (1 test):

```bash
docker compose -p libli-test -f docker-compose.test.yml down
uv run pytest tests/test_e2e_catalog.py -m e2e -n 2 -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `1`.

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli" \
  uv run pytest tests/test_e2e_catalog.py -m e2e -n 2 -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `0`.

```bash
uv run pytest tests/test_smoke.py -n 2 -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `0` (unit-only run).

**The check that actually catches the deselection bug** — the three above cannot,
because `test_smoke.py` deselects nothing and the xdist controller has no
`deselected` key at all. This one runs the *default* selection over a file that
does contain e2e tests, so `addopts`' `-m 'not e2e'` deselects them:

```bash
uv run pytest tests/test_tabs_editor_dnd.py -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `0`. Before the `key != "deselected"` filter this printed `1` —
verified with a probe harness.

**And one check that discriminates the pre-run path from the post-run one**,
because all four counts above are satisfied by the terminal-summary emission
alone — so a dead `pytest_sessionstart` would go unnoticed:

```bash
uv run pytest tests/test_e2e_catalog.py -m e2e -p no:warnings --verbosity=0 2>&1 |
  grep -nE "disposable tuned database|collected [0-9]+ item"
```
Expected: **two** numbered lines, with the notice's number **lower** than the
`collected N items` line's — i.e. it was emitted before collection, not in the
summary. Red on a `pytest_configure` implementation, where the reporter is not
yet registered.

**`--verbosity=0` is required here and is not a second `-q`.** `addopts` sets
verbosity to −1, and `TerminalReporter.report_collect` returns immediately below
0 — measured: without it pytest prints no `collected …` line at all, the grep
yields one line, and the ordering assertion silently proves nothing.

Note: `grep -c` exits **1** when it prints `0`. That is the expected result for
the negative checks, not a failed command.

- [ ] **Step 6b: Record the real "container is down" error text**

Task 5's `testing.md` will tell developers that a connection error means the
container is not running — spec §7 calls this "the recurring daily failure". Ship
the *actual* message, not a guess at it:

```bash
docker compose -p libli-test -f docker-compose.test.yml down
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli" \
  uv run pytest tests/test_smoke.py -p no:warnings --verbosity=0 2>&1 | tail -5
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
```
Quote the resulting error (likely a `django.db.utils.OperationalError` raised
during test-database creation) verbatim in `testing.md`'s Troubleshooting
section, so a developer can grep for what they actually see.

- [ ] **Step 7: Verify the `.env` activation path works**

The documented activation is `.env`, but the helper reads `os.environ`. That
works because `environ.Env.read_env` calls `os.environ.setdefault`, but it is
worth one direct check — if it ever broke, the notice would nag forever at
exactly the developers who adopted.

Temporarily add `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli` to
`.env`, then:
```bash
uv run pytest tests/test_e2e_catalog.py -m e2e -n 2 -p no:warnings 2>&1 | grep -c "disposable tuned database"
```
Expected: `0`. Remove the line from `.env` afterwards.

- [ ] **Step 8: Lint, then commit**

```bash
uv run ruff check conftest.py tests/test_test_db_notice.py
uv run ruff format --check conftest.py tests/test_test_db_notice.py
git add conftest.py tests/test_test_db_notice.py
git commit -m "feat: nudge e2e runs toward the tuned test database"
```

---

### Task 5: Documentation

**Files:**
- Modify: `.env.example` (after the `DATABASE_URL` line, **line 9**)
- Create: `docs/development/testing.md`
- Modify: `docs/development/setup.md` (line 98 block; lines 106–107 block; prerequisites list)
- Modify: `docs/development/conventions.md` (`## Testing`, lines 27–40; line 31; line 96)
- Modify: `README.md` (docs-index table near line 52; command block lines 59–61; line 64)

**Interfaces:**
- Consumes: the connection string from Task 1, the `.env` activation path from Task 3, `LIBLI_NO_TEST_DB_NOTICE` from Task 4.
- Produces: `docs/development/testing.md` as the single source of truth for what runs locally versus what CI gates. Part B's plan appends its affected-tests practice to this same file.

- [ ] **Step 1: Add to `.env.example`, immediately after line 9 (`DATABASE_URL=…`)**

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

The body below is delimited with **four** backticks because it contains
triple-backtick fences. Write the inner content only — not the outer fence.

````markdown
# Running the tests

## The two selections

`pyproject.toml` pins `addopts = "-q -m 'not e2e'"`, so a "full run" is two
commands:

```bash
uv run pytest            # unit + integration selection
uv run pytest -m e2e     # browser e2e selection
```

(Deliberately uncounted: Tasks 3 and 4 add 21 unit tests between them, and both
counts drift with every feature. `--collect-only -q` reports the current numbers.)

`-m e2e` is mandatory for the second. Without it every e2e test is deselected and
pytest exits **5** — which means "nothing selected", not "green".

## Use the tuned test database

e2e teardown runs `TRUNCATE ... CASCADE` over 89 tables after each test that
takes `live_server` — **575 of the 845 collected e2e tests**. On a normal
Postgres that statement costs **2,881 ms**; on a server with durability off and
its data directory on a tmpfs it costs about **88 ms**. Both measured.
<!-- SUBSTITUTE the ms figure measured at Task 2 Step 4. -->



```bash
# start (once per session)
docker compose -p libli-test -f docker-compose.test.yml up -d --wait

# stop and wipe (the data is disposable by design)
docker compose -p libli-test -f docker-compose.test.yml down
```

Then uncomment `TEST_DATABASE_URL` in your `.env`. A shell export works too if
you would rather keep it per-command.

The `-p libli-test` project name is required, not cosmetic: without it Compose
names the project after the current directory, so each worktree would get its own
container.

Requires Docker Desktop, and Compose v2.17+ for `--wait`. Without Docker, leave
`TEST_DATABASE_URL` unset — that is a supported configuration, just slower.

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
````

- [ ] **Step 3: Point `setup.md` at it**

After the `uv run pytest` block at line 98, and after the block at **lines
106–107** (106 is `uv run playwright install chromium`, 107 is the `-m e2e`
invocation; 108 is the closing fence), add:

```markdown
See [`testing.md`](testing.md) for which tests to run locally, and for the
optional tuned test database that makes e2e runs substantially faster.
```

Add to the prerequisites list: **Docker Desktop with Compose v2.17+**, needed
only for the tuned test database, and note the fallback for older Compose
(`up -d` plus a `pg_isready` poll instead of `--wait`).

- [ ] **Step 4: `conventions.md` — three edits, enumerated bullet by bullet**

The `## Testing` block spans lines 27–40 and carries **two** `uv run pytest`
commands, not one — line 30 (`Run with uv run pytest`) and line 39
(`… chromium` then `uv run pytest -m e2e`). Both must go, or Step 6's check
fails. Two other bullets in that block must survive **verbatim**:

| Bullet | Action |
|---|---|
| "pytest via `pytest-django`; settings module is … **Run with `uv run pytest`**" | Drop the command clause; keep the settings-module fact; append: *see [`testing.md`](testing.md) for what to run* |
| "Tests live in one top-level **`tests/`** package (not per-app), with `tests/factories.py` …" | **Correct** the false claim (edit 2 below); keep the `factories.py` pointer |
| "**Never hardcode passwords.** … `tests.factories.TEST_PASSWORD` …" | **Keep unchanged** |
| "**Browser e2e** tests are marked `e2e` … **Run them with `uv run playwright install chromium` then `uv run pytest -m e2e`** … e2e must drive the **real** UI gesture, not a `page.evaluate` shortcut" | Drop the two commands; **keep the real-UI-gesture rule verbatim** — it is a standing convention, not run guidance |

**Edit 1** is that table plus adding to the block: *"The test database is
disposable and runs with `fsync=off`. Never apply those settings to the instance
holding dev or mat-pp data."*
2. **Line 31 is factually wrong** and must be corrected while that block is open.
   It reads "Tests live in one top-level **`tests/`** package (not per-app)".
   `courses/tests/`, `integrations/tests/` and `notifications/tests/` all exist;
   `tests/` holds 505 of the 549 unit files.
3. **Lines 96–97**, under `## Migrations & checks` — *not* under `## Testing` —
   carry the definition-of-done sentence, which **spans both lines**: 96 is
   "Commit the migration in the same change as the model edit. Both checks are
   part" and 97 is "of the definition of done, alongside the ruff and pytest
   commands above." Amend the back-reference so it does not silently reinstate a
   local full run as the definition of done, and **keep the "Commit the
   migration…" clause intact** — editing line 96 alone leaves a broken sentence.

- [ ] **Step 5: `README.md` — three edits**

- Add a row to the docs-index table near line 52, **in the table's existing link
  form** — every other row uses a markdown link, so a bare code span would be the
  only unclickable entry:

  | Know what to run locally vs. in CI | [`docs/development/testing.md`](docs/development/testing.md) |

- After the command block at lines 59–61, point at `testing.md`.
- **Line 64** currently reads "See `docs/development/conventions.md` for the full
  checks CI runs" — redirect it to `testing.md`.

- [ ] **Step 6: Verify no stale instruction survives**

```bash
grep -rc "uv run pytest" README.md docs/development/setup.md \
  docs/development/conventions.md docs/development/testing.md
```
Expected **counts**, not line numbers — the line numbers shift as pointers are
inserted, so counts are the stable assertion:

| File | Expected hits |
|---|---|
| `README.md` | 2 (the command block, each followed by the pointer) |
| `docs/development/setup.md` | 2 (line-98 block and the e2e block) |
| `docs/development/conventions.md` | **0** — both commands removed by Step 4 |
| `docs/development/testing.md` | any (it is the new home) |

- [ ] **Step 7: Commit**

```bash
git add .env.example docs/development/testing.md docs/development/setup.md \
        docs/development/conventions.md README.md
git commit -m "docs: document the tuned test database and what runs locally vs CI"
```

---

### Task 6: CI tmpfs

**Files:**
- Modify: `.github/workflows/ci.yml` (the `postgres` service in the `unit` job; the `postgres` service in the `e2e` job)

**Interfaces:**
- Consumes: nothing.
- Produces: no code interface; changes CI runtime only.

**Both** services get the tmpfs. CI does **not** get the durability flags —
GitHub Actions service containers accept no `command:` key, so `-c fsync=off`
cannot be passed the way Task 1 passes it. CI therefore captures only part of the
win.

Sizing is not Task 1's sizing: the `unit` job runs `pytest -n auto` (worker count
is whatever the runner reports) **and** runs `manage.py migrate` plus
`setup_roles` against the real `libli` database on the same mount. 2 GiB covers
both with headroom.

- [ ] **Step 1: Record the "before" baseline as durations, not timestamps**

A single observation is not a baseline — runner allocation varies. Take the
median (with three runs, the middle value) of the last three green `master` runs
per job:

```bash
gh run list --workflow=ci.yml --branch=master --status=success --limit 3 \
  --json databaseId -q '.[].databaseId' |
while read -r id; do
  gh api "repos/:owner/:repo/actions/runs/$id/jobs" \
    -q '.jobs[] | select(.name=="unit" or .name=="e2e") | "\(.name) \(.started_at) \(.completed_at)"'
done |
while read -r name started completed; do
  s=$(date -d "$started" +%s); c=$(date -d "$completed" +%s)
  echo "$name $((c - s))s"
done | sort
```
Expected: six lines, three per job, in seconds. Record the median per job.

- [ ] **Step 2: Add the tmpfs to both services**

In each job's `services.postgres`, extend the existing `options:` block:

```yaml
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
          --tmpfs /var/lib/postgresql/data:rw,size=2g,mode=1777
```

The docker-flag form (`mode=1777`) is the form the original measurements used;
Task 1's Compose long-form is the separately-verified equivalent.

- [ ] **Step 3: Push AND open a PR — a bare push runs nothing**

`ci.yml` triggers on `push: branches: [master]` and `pull_request` only. This
branch is not `master`, so pushing alone starts no workflow and Steps 4–6 would
have no data.

```bash
branch=$(git branch --show-current)   # expected: test-suite-speed
git add .github/workflows/ci.yml
git commit -m "ci: put both test Postgres services on a tmpfs"
git push -u origin "$branch"
gh pr create --fill --draft
```

The branch is derived rather than hard-coded: no task in this plan creates it,
and `git push -u origin test-suite-speed` fails with "src refspec does not match
any" on any other branch, while Step 5's `gh run list --branch=` would silently
query the wrong one.

All CI observations below are made on the **PR**, not the push.

- [ ] **Step 4: Verify both jobs still start Postgres**

A `postgres:16` PGDATA on tmpfs is a known permissions/init edge case. If either
job goes red at "Initialize containers", the revert is to drop the `--tmpfs` line
from that job's `options:` — nothing else depends on it.

- [ ] **Step 5: Get three "after" data points per job**

Two constraints make this less obvious than it looks:

- **`gh run rerun` does not create a new run** — it adds an *attempt* to the same
  run record. After three reruns `gh run list --branch=test-suite-speed` still
  returns **one** id, and `/actions/runs/{id}/jobs` reports only the latest
  attempt. Step 1's snippet would then yield n=1 for "after" against a genuine
  three-run median for "before" — not comparable.
- **`ci.yml` sets `concurrency: group: ci-${{ github.ref }}` with
  `cancel-in-progress: true`**, so three quick pushes cancel each other.

Rerun three times, then read the **attempts** explicitly:

```bash
branch=$(git branch --show-current)
id=$(gh run list --workflow=ci.yml --branch="$branch" --limit 1 \
       --json databaseId -q '.[0].databaseId')

# The PR's original run is attempt 1, so TWO reruns give attempts 1-3.
# Run these as TWO SEPARATE invocations: the pipeline is ~8m45s, so a single
# loop of two rerun+watch cycles is ~19 min -- past the 10-minute ceiling that
# auto-backgrounds (and can reap) a command in this environment.
gh run rerun "$id" && gh run watch "$id"     # invocation 1 -> attempt 2
gh run rerun "$id" && gh run watch "$id"     # invocation 2 -> attempt 3

attempts=$(gh api "repos/:owner/:repo/actions/runs/$id" -q '.run_attempt')
for a in $(seq 1 "$attempts"); do
  gh api "repos/:owner/:repo/actions/runs/$id/attempts/$a/jobs" \
    -q '.jobs[] | select(.name=="unit" or .name=="e2e") | "\(.name) \(.started_at) \(.completed_at)"' \
    || echo "attempt $a unavailable" >&2
done |
while read -r name started completed; do
  s=$(date -d "$started" +%s); c=$(date -d "$completed" +%s)
  echo "$name $((c - s))s"
done | sort
```
Expected: six lines, three per job. Take the median (middle value) per job.

- [ ] **Step 6: Decide per job, independently**

**Keep** if `median_after ≤ median_before × 1.05`; **drop** that job's tmpfs
otherwise. The 5% tolerance exists because the spec predicts the CI gain will be
roughly neutral, and a noise-level regression should not discard the change. The
two jobs may diverge.

- [ ] **Step 7 (conditional — only if Step 6 said "drop" for a job): revert that job**

First make the edit: in that job's `services.postgres.options:` block, delete the
line

```
          --tmpfs /var/lib/postgresql/data:rw,size=2g,mode=1777
```

leaving the four `--health-*` options intact. Then, substituting the actual job
name for `<job>`:

```bash
git add .github/workflows/ci.yml
git commit -m "ci: drop tmpfs from the <job> job (measured slower)"
```

---

### Task 7: Measure, and decide

**Files:**
- Create: `docs/superpowers/notes/2026-08-07-test-suite-timings.md`
- Create: `scripts/timed_run.sh`
- Modify: `scripts/e2e_chunks.sh` (its stale 565-test coverage claim)
- Modify: `docs/development/testing.md` (recommended local commands, per the outcome)
- Modify: `.env.example` (only if the run-2 rule fires — Step 8)

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: the recorded numbers, and the accept/reject decision for Part A.

**Cost warning.** Spec §5.1 specifies six runs × two draws: eight full unit runs
and four full e2e runs, plausibly 8–12 hours of wall clock — far larger than
anything else in this plan, on a change whose purpose is to reclaim wall clock.
**This plan takes the spec's sanctioned reduction:** one draw per baseline run,
with a second taken *only* when the first lands inside that rule's stated band.
The gate itself (Step 4) keeps full replication, because that is where a wrong
call is expensive.

**The bands, per rule** — "the inconclusive band" is not self-evident and differs
sharply between the two comparisons:

| Rule | Threshold | Re-draw when |
|---|---|---|
| Run 3 ÷ run 1 (`-n auto`) | 1.25× | the first draw lands in **1.15×–1.35×** |
| Run 2 ÷ run 1 (container on unit) | ±5% | **always take two draws** |

**A re-draw always applies to BOTH arms, and run 1 is always taken twice.** Run 1
is the shared denominator of both comparisons, so a median-of-2 numerator over an
n=1 denominator at a 5% threshold inherits exactly the variance the second draw
was meant to remove. The plan's own rationale — "one draw cannot resolve it" —
applies identically to the denominator.

Run 2 gets no single-draw shortcut: spec §2.4 measured ~21% run-to-run variance
on local Postgres, and a 5% threshold sits far inside that. One draw cannot
resolve it, and a noise draw read as a real regression would demote
`TEST_DATABASE_URL` to e2e-only on no evidence. If the two draws disagree about
which side of ±5% they fall, take a third and decide on the median.

- [ ] **Step 1: Set up logging, reusing the harness that already exists**

**Do not background these runs.** `scripts/e2e_chunks.sh` already exists and its
header records why: *"the Bash tool auto-backgrounds anything past a 10-minute
ceiling, and backgrounded runs in this environment were killed three times within
seconds of starting. Chunks each finish inside the ceiling, so nothing is
backgrounded and nothing gets reaped."* That is a solved problem in this repo —
reuse the solution rather than reintroducing the failure it documents.

So: **every full e2e run is executed chunk by chunk, in the foreground, at
`-n 4`.** The unit selection is a single invocation.

**`scripts/e2e_chunks.sh` is used as a source of chunk *file lists* only — never
invoked directly.** Two reasons, both measured: its line 31 runs
`uv run pytest -m e2e -n 4 -q …`, and that `-q` on top of `addopts`' `-q` makes
`-qq`, which suppresses the warnings summary and would render Step 6's blocking
check vacuous; and it redirects to `/tmp/`, outside the `runs/*.log` glob Step 6
asserts over. Timing and warning capture go through `timed_run.sh` instead.

**First, repair the chunk lists — they are badly stale.** Measured: they name
**84 files against the 97** that `-m e2e` collects. Thirteen are missing,
including `tests/test_e2e_math_reflow_dom.py` at **171 tests — 20% of the entire
selection**:

```
test_e2e_callout_container   test_e2e_clipboard          test_e2e_depth3
test_e2e_editor_force_open   test_e2e_editor_scroll_containment
test_e2e_image_size          test_e2e_math_reflow        test_e2e_math_reflow_dom
test_e2e_quote_block         test_e2e_review_shell_isolation
test_e2e_slide_overflow      test_e2e_spoiler_rule       test_e2e_table_cell_images
```

Left unrepaired, run 4 would baseline a different, smaller population than run 5,
and Step 3's dilution recomputation would look for `math_reflow_dom` durations
that were never produced.

Regenerate and verify:

```bash
# The SECOND -q is deliberate and is the one exception to the global "never add
# a second -q" rule: the `file.py: N` format exists only at -qq. On a *run* it
# would suppress the warnings summary; on --collect-only there is none to lose.
uv run python -m pytest -m e2e --collect-only -q 2>/dev/null | tr -d '\r' |
  grep -E "\.py: [0-9]+$" | sort
```

**The character class matters.** An earlier draft used `^[a-z/_]+\.py:` — MEASURED
to match **4 of 97** files, because the class excludes digits and nearly every
e2e filename contains one (`e2e` itself has a `2`). Rebuilding the chunk lists
from a 4-file inventory would be far worse than the 84-file staleness this step
repairs.

Assign the 13 missing files to chunks, giving **`math_reflow_dom` its own
chunk** — 171 tests, and it needs no `live_server`, so it is bulky but fast.
**That makes seven chunks, so `NCHUNKS=7`:** update `e2e_chunks.sh`'s own driver
loop *and* both loops in Steps 2 and 5, or run 4 and run 5 silently skip 20% of
the selection — reintroducing the population mismatch this step exists to remove.

Then assert both totals before proceeding:

```bash
eval "$(sed -n '/^C[0-9]\+=/p' scripts/e2e_chunks.sh)"
[ -n "${C1:-}" ] || { echo "chunk vars not extracted"; exit 1; }
NCHUNKS=$(sed -n '/^C[0-9]\+=/p' scripts/e2e_chunks.sh | wc -l)
all=""; for n in $(seq 1 "$NCHUNKS"); do eval "all=\"\$all \$C$n\""; done
echo "chunks=$NCHUNKS files=$(echo $all | tr ' ' '\n' | grep -c .)"   # expect 7 and 97

# Sum the per-file counts. There is NO "845 tests collected" line to read at
# -qq --collect-only -- measured: the output is 97 `file.py: N` lines followed
# by the warnings summary, so `tail -2` returns the pytest docs URL.
uv run python -m pytest -m e2e $all --collect-only -q 2>/dev/null | tr -d '\r' |
  grep -E "\.py: [0-9]+$" | awk -F': ' '{s+=$2} END {print "tests="s}'
```
Expected: `chunks=7 files=97` and `tests=845`. Only then update the header's
stale "565".

Then create `scripts/timed_run.sh` for timing and warning capture:

```bash
#!/usr/bin/env bash
# Usage: scripts/timed_run.sh <label> <pytest args...>
# Runs in the FOREGROUND by design -- see scripts/e2e_chunks.sh on why
# backgrounded runs get reaped here. Writes runs/<label>.log.
set -u
label="$1"; shift
mkdir -p docs/superpowers/notes/runs
log="docs/superpowers/notes/runs/${label}.log"
start=$(date +%s)
uv run python -m pytest "$@" 2>&1 | tee "$log"
code=${PIPESTATUS[0]}
end=$(date +%s)
{
  echo "--- label=${label}"
  echo "--- exit=${code}"
  echo "--- seconds=$((end - start))"
  # Read the RESOLVED port, not the shell variable: `.env` is the documented
  # activation path, and a .env-activated run would otherwise log "<unset>"
  # while actually using the container -- the exact confounder the +/-5% run-2
  # rule cannot survive.
  echo "--- resolved_db_port=$(uv run python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test')
django.setup()
from django.conf import settings
print(settings.DATABASES['default']['PORT'])" 2>/dev/null)"
  echo "--- container_running=$(docker ps -q -f name=libli-test-db | grep -c . || true)"
  echo "--- barrier_timeouts=$(grep -c 'live_server still busy at teardown of' "$log" || true)"
  echo "--- deadlock_retries=$(grep -c 'teardown TRUNCATE deadlocked' "$log" || true)"
  echo "--- browser_quiesce=$(grep -c 'could not quiesce the browser at teardown' "$log" || true)"
} | tee -a "$log"
```

`exit=` is on its **own line** so Step 6's grep can assert on it, and `tee` (not
`>`) means output is visible live as well as captured. `|| true` guards the
`grep -c` calls, which exit 1 when they legitimately print `0`.

```bash
chmod +x scripts/timed_run.sh
```

`.gitignore` already carries a global `*.log`, so the run logs are ignored
without any edit — no `.gitignore` change is needed.

- [ ] **Step 2: Baselines (runs 1, 3, 4)**

**The container must be running for these too**, even though they do not use it.
Run 1 and run 2 are compared at a **5%** threshold in Step 8 — far tighter than
the gate's — and if run 1 is taken with Docker Desktop idle while run 2 runs with
the VM up, that confounder alone drives the decision. `timed_run.sh` records
`container_running=` on every run so this is auditable afterwards.

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait

scripts/timed_run.sh run1-unit-single
scripts/timed_run.sh run3-unit-nauto -n auto

# run 4: one invocation per repaired chunk. The C<N> assignments are EXTRACTED,
# not sourced -- `source scripts/e2e_chunks.sh` would hit its top-level driver
# and execute every chunk immediately. -n 4 is pinned so runs 4 and 5 compare.
eval "$(sed -n '/^C[0-9]\+=/p' scripts/e2e_chunks.sh)"
[ -n "${C1:-}" ] || { echo "chunk vars not extracted"; exit 1; }
NCHUNKS=$(sed -n '/^C[0-9]\+=/p' scripts/e2e_chunks.sh | wc -l)

for n in $(seq 1 "$NCHUNKS"); do
  eval "files=\$C$n"
  scripts/timed_run.sh "run4-chunk$n" -m e2e $files -n 4 --durations=0 --durations-min=0
done
```

Without the extraction the loop expands to `-m e2e` with **no files** — i.e. the
entire 845-test selection, once per chunk. The `[ -n "$C1" ]` guard is what makes
that failure visible instead of expensive.

Run 4's total is the **sum of the per-chunk seconds**. `-n 4` matches
`e2e_chunks.sh`'s original design (each chunk finishes inside the 10-minute
ceiling) and **must be identical in run 5**, or the headline comparison varies
its most important control.

All three with `TEST_DATABASE_URL` **unset**. `--durations-min=0` is required and
`-vv` is **not** a substitute: pytest's durations filter tests
`get_verbosity() >= 2`, and `addopts`' `-q` cancels one `-v`, so `-vv` still
hides sub-5 ms entries. Measured.

**Cleanup between runs.** The two arms live on different servers, and only one is
dangerous — so the local-instance command comes first, deliberately.

**Local-instance arm (`TEST_DATABASE_URL` unset) — the one destructive action in
this plan.** These databases sit on your **real** Postgres. `psql` is not
guaranteed to be on PATH, so list them through Django, *read the list*, and only
then drop those exact names:

```bash
uv run python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test')
django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute(\"SELECT datname FROM pg_database WHERE datname LIKE 'test_libli%%'\")
    print([r[0] for r in c.fetchall()])
"
```

Then drop the reviewed names, **one at a time, each named explicitly**. `psql` is
not guaranteed on PATH, and `DROP DATABASE` cannot run inside a transaction and
must be issued from a connection to a *different* database — so:

```bash
uv run python -c "
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test')
django.setup()
from django.db import connection
name = sys.argv[1]
assert name.startswith('test_libli'), f'refusing to drop {name!r}'
connection.ensure_connection()
connection.connection.autocommit = True   # DROP DATABASE cannot be in a txn
with connection.cursor() as c:
    c.execute(f'DROP DATABASE IF EXISTS \"{name}\"')
print('dropped', name)
" test_libli_gw0
```

Run it once per reviewed name. **Never issue a pattern-matched `DROP`** — the
`assert` above is a backstop, not a licence to loop over a wildcard.

**Container arm.** No care required — the whole server is disposable:

```bash
docker compose -p libli-test -f docker-compose.test.yml down
```

- [ ] **Step 3: Recompute the gate thresholds from run 4**

Four e2e files use no `live_server` and pay no truncate — they dilute the
full-suite ratio:

| File | e2e tests |
|---|---|
| `tests/test_e2e_math_reflow_dom.py` | 171 |
| `tests/test_table_grid_algebra.py` | 38 |
| `tests/test_link_dialog_behaviour.py` | 32 |
| `tests/test_link_apply.py` | 29 |

**270 of 845 pay no truncate; 575 do.**

Aggregate the per-file mean of `setup+call+teardown` from run 4's log:

```bash
uv run python - <<'PY'
import re, collections, glob
FILES = ("test_e2e_math_reflow_dom", "test_table_grid_algebra",
         "test_link_dialog_behaviour", "test_link_apply")
EXPECTED = {"test_e2e_math_reflow_dom": 171, "test_table_grid_algebra": 38,
            "test_link_dialog_behaviour": 32, "test_link_apply": 29}
tot = collections.Counter(); n = collections.Counter()
logs = sorted(glob.glob("docs/superpowers/notes/runs/run4-chunk*.log"))
if not logs:
    raise SystemExit("no run4 chunk logs found -- did Step 2 complete?")
for path in logs:
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*([\d.]+)s\s+(setup|call|teardown)\s+(\S+)", line)
        if not m:
            continue
        secs, _phase, nodeid = m.groups()
        for f in FILES:
            if f in nodeid:
                tot[f] += float(secs); n[f] += 1
print(f"read {len(logs)} chunk logs")
for f in FILES:
    tests = n[f] / 3                          # three phases per test
    if round(tests) != EXPECTED[f]:
        raise SystemExit(
            f"FATAL {f}: saw {tests:.0f} tests, expected {EXPECTED[f]} -- a chunk "
            "log is missing or a chunk failed. Re-run it; do NOT derive thresholds "
            "from this data."
        )
    print(f"  {f}: per-test mean = {tot[f]/tests:.3f}s")
total_tests = sum(n.values()) / 3
print("weighted c =", f"{sum(tot.values())/total_tests:.3f}s")
PY
```

The script globs **`run4-chunk*.log`** because Step 2 produces one log per chunk,
not a single `run4-e2e-baseline.log`. The per-file count assertion is what catches
a missing chunk: without it, an absent log silently lowers `c` and shifts every
threshold.

Call that weighted per-test cost **c** (the spec assumed `c = 0.4`). With sample
per-test costs `before = 3.08` and `after = 1.93`:

```
diluted_ratio = (575*3.08 + 270*c) / (575*1.93 + 270*c)
```

At `c = 0.4` this is 1.54, which is where the shipped thresholds come from. If
the measured `c` moves it, recompute **before running the gate, never after
seeing its result**:

```
new_sample_threshold = 1.45 * (1.54 / new_diluted_ratio)      # and 1.30 likewise
```

- [ ] **Step 4: The gate — four draws on the 69-test sample**

All four invocations in full — the after arm silently corrupts the decision if
its variable or its cleanup is missed:

```bash
SAMPLE="tests/test_e2e_tabs.py tests/test_e2e_fillgate.py tests/test_e2e_guessnumber.py"
TUNED="postgres://libli@127.0.0.1:55433/libli"
COMPOSE="-p libli-test -f docker-compose.test.yml"

# container up for ALL four draws, including the before arm
docker compose $COMPOSE up -d --wait

unset TEST_DATABASE_URL
scripts/timed_run.sh gate-before-1 -m e2e $SAMPLE -n 2 --verbosity=0
docker compose $COMPOSE down && docker compose $COMPOSE up -d --wait
scripts/timed_run.sh gate-before-2 -m e2e $SAMPLE -n 2 --verbosity=0

export TEST_DATABASE_URL="$TUNED"
docker compose $COMPOSE down && docker compose $COMPOSE up -d --wait
scripts/timed_run.sh gate-after-1 -m e2e $SAMPLE -n 2 --verbosity=0
docker compose $COMPOSE down && docker compose $COMPOSE up -d --wait
scripts/timed_run.sh gate-after-2 -m e2e $SAMPLE -n 2 --verbosity=0
unset TEST_DATABASE_URL
```

**`-p no:warnings` is deliberately absent.** It unregisters pytest's warnings
plugin entirely, so no summary is emitted and `timed_run.sh`'s three counts read
`0` unconditionally — making Step 6's blocking check vacuous for exactly the four
runs that stress the new timing profile hardest. Same trap as `-qq`, different
flag. `--verbosity=0` gives the quiet output without suppressing the summary.
Two draws with `TEST_DATABASE_URL` unset, two with it set (labels
`gate-before-1/2`, `gate-after-1/2`). Same commit, same machine, `-n 2` fixed,
toggling **only** that variable. **The container must be running during all four
draws**, including the unset arm — otherwise the arms differ by the whole cost of
the Docker Desktop VM, a confounder the size of the effect. A `down`/`up -d
--wait` cycle *between* draws is fine and is the required cleanup for the set arm.

**Statistic: worst-case speedup = fastest before ÷ slowest after.** Both are
seconds; the quotient is dimensionless and exceeds 1 when Part A helps. (The
inverted form yields ≈0.64 and can never clear a bar above 1.)

| Worst-case speedup | Outcome |
|---|---|
| ≥ 1.45× | accept |
| 1.30× ≤ x < 1.45× | inconclusive — two more draws **per arm** (4 and 4), accept iff median before ÷ median after ≥ 1.45× |
| < 1.30× | reject |

Median of an even sample = mean of the two middle values. The statistic is always
the ratio of the medians, never the median of the ratios — on before `[100, 140]`
and after `[80, 60]` those give 1.71 and 1.79.

- [ ] **Step 5: Post-implementation runs (2, 5, 6)**

Same cleanup discipline as Step 4 — a `down`/`up` cycle before each run, since
run 6 at `-n auto` reuses the `test_libli_gw*` names `gate-after-2` just created:

```bash
COMPOSE="-p libli-test -f docker-compose.test.yml"
export TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli"

docker compose $COMPOSE down && docker compose $COMPOSE up -d --wait
scripts/timed_run.sh run2-unit-container
docker compose $COMPOSE down && docker compose $COMPOSE up -d --wait
scripts/timed_run.sh run6-unit-nauto-container -n auto
docker compose $COMPOSE down && docker compose $COMPOSE up -d --wait

# run 5: SAME chunks, SAME -n 4 as run 4. A single `-m e2e` invocation here
# would exceed the 10-minute ceiling, be auto-backgrounded, and risk being
# reaped -- the failure Step 1 exists to avoid.
eval "$(sed -n '/^C[0-9]\+=/p' scripts/e2e_chunks.sh)"
[ -n "${C1:-}" ] || { echo "chunk vars not extracted"; exit 1; }
NCHUNKS=$(sed -n '/^C[0-9]\+=/p' scripts/e2e_chunks.sh | wc -l)

for n in $(seq 1 "$NCHUNKS"); do
  eval "files=\$C$n"
  scripts/timed_run.sh "run5-chunk$n" -m e2e $files -n 4 --durations=0 --durations-min=0
done
unset TEST_DATABASE_URL
```

Run 5's total is the sum of its per-chunk seconds, directly comparable to run 4's.
It carries the same instrumentation — without after-side per-file durations there
is no way to confirm the dilution assumption held.

- [ ] **Step 6: Blocking checks — green, and the teardown apparatus quiet**

`scripts/timed_run.sh` already appends the three counts to every log. Check them
for **all six runs plus the four gate draws**:

```bash
grep -h -E "^--- (label|exit|seconds|resolved_db_port|container_running|barrier_timeouts|deadlock_retries|browser_quiesce)" \
  docs/superpowers/notes/runs/*.log
```

Expected: every `exit=0`, every warning count `0`, `container_running=1` on every
run (Step 2), and `resolved_db_port` **55433 on exactly the arms that should be
tuned** (runs 2, 5, 6, `gate-after-*`, `sweep-*`) and **5432 on the rest**. That
field is how a mislabelled arm is caught; a run whose port contradicts its label
is not usable data. A missing `--- exit=` line means the run never reached the
summary block — it was killed, so it is not a timing and must be re-run.

**Remediations differ by warning.** A *barrier timeout* means the 5 s
`DEFAULT_TIMEOUT` no longer suits the new timing profile — retune it at
**`tests/db_quiesce.py:19`** (not `conftest.py`, which only holds the fixture
that consumes it) and re-run; that is a fix, not a rejection. A *deadlock retry* or *browser-quiesce* warning
**rejects Part A** pending investigation, because the spec declines to touch that
machinery precisely on the assumption it stays quiescent.

Note the scope asymmetry: the barrier is function-scoped in `tests/conftest.py`
and never applies to the three notifications e2e files, but the deadlock-retry
patch is **session-scoped and monkeypatches `TransactionTestCase` globally**, so
its warning can fire for them depending on xdist distribution. Those three files
take `live_server` and pay the truncate *without* the barrier — they are the most
exposed to this change, not the least.

- [ ] **Step 7: Recorded measurements (non-blocking, for the note)**

- **Time `TRUNCATE` on the Windows Postgres**, closing spec §2.1's inference.
  Pin the state for comparability: a freshly migrated test database immediately
  after one e2e test's fixtures. Re-time the container the same way.
- **Replicate the two single-draw container runs** (spec §2's 273.8 s and 76.7 s),
  so the 3.57× figure and §6's ~1.7× Linux sizing rest on more than n=1.
- **Re-measure `-n 4` and `-n 8`** now that the truncate cost is gone — spec §6
  calls this mandatory, because the evidence excluding more workers was taken
  under conditions Part A destroys. **Subject: the 69-test gate sample, not the
  full selection** — that is the cheap, spec-consistent choice and keeps this
  from adding two more full e2e runs to a step already warned about for cost.
  One draw each, with the container up and `TEST_DATABASE_URL` set:

  ```bash
  # SAMPLE re-declared: each block is an independent shell, so Step 4's
  # assignment does not survive. Unset, this would run the full 845 twice.
  SAMPLE="tests/test_e2e_tabs.py tests/test_e2e_fillgate.py tests/test_e2e_guessnumber.py"
  export TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli"
  scripts/timed_run.sh sweep-n4 -m e2e $SAMPLE -n 4 --verbosity=0
  scripts/timed_run.sh sweep-n8 -m e2e $SAMPLE -n 8 --verbosity=0
  unset TEST_DATABASE_URL
  ```

  **These run after the gate is decided and never feed it** (spec §5.2) —
  otherwise the best `-n` could be reported as the "after" and inflate the ratio.

None of these gate acceptance; all three go in the note.

- [ ] **Step 8: Apply the decision rules**

| Comparison | Rule |
|---|---|
| Run 2 vs run 1 | If run 2 is **>5% slower**, `testing.md` documents `TEST_DATABASE_URL` as an **e2e-only** activation (exported per command, not set in `.env`), and Task 5 Step 1's `.env.example` guidance changes to match |
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

- [ ] **Step 9 (conditional — only if Step 4 rejected): revert**

Delete **all five** of these, or the unit selection fails at collection with
`ImportError`:

```bash
git rm docker-compose.test.yml tests/test_settings_test_db.py tests/test_test_db_notice.py
# then hand-revert the appended block in config/settings/test.py
# and the appended block plus `import os` in conftest.py
```

Verify the revert left nothing dangling:
```bash
uv run pytest --collect-only -q >/dev/null && echo "collection clean"
uv run pytest tests/test_smoke.py -p no:warnings --verbosity=0
```
Expected: `collection clean`, then `1 passed`.

Also **remove the `TEST_DATABASE_URL` block from `.env.example`** — left behind it
tells developers to uncomment a variable pointing at a server with no compose
definition and no code reading it.

**Keep** Task 5's docs with the container sections excised, and keep Task 6's CI
tmpfs — it is judged only by its own rule in Task 6 Step 6. Part B is unaffected.
A rejected gate also returns the spec's §6 shared-connection rewrite to scope.

- [ ] **Step 10: Record everything, stop the container, and commit**

Write `docs/superpowers/notes/2026-08-07-test-suite-timings.md` with every run's
wall clock, worker count, `TEST_DATABASE_URL` state, exit code, the three warning
counts, the four gate draws, Step 7's recorded measurements, and the resulting
decisions. Name the commit measured. The spec is pinned to `828354c9` and is
**not** retro-edited with these results.

```bash
docker compose -p libli-test -f docker-compose.test.yml down
git add docs/superpowers/notes/2026-08-07-test-suite-timings.md \
        docs/development/testing.md scripts/timed_run.sh scripts/e2e_chunks.sh \
        .env.example
git commit -m "docs: record measured test-suite timings and the Part A decision"
```

(`.env.example` is staged only if Step 8's run-2 rule changed it; `git add` on an
unchanged file is a harmless no-op. No `.gitignore` entry is needed — the global
`*.log` rule already covers the run logs.)

---

## Self-Review

**Spec coverage.** A1→Task 1 (+ Task 2 verification); A2→Task 3; A3→Task 5;
A4→Task 6; A5→Task 4; §5.1→Task 7 Steps 1–2, 5; §5.2→Task 7 Steps 3–4;
§5.3→Task 7 Steps 8–9; §5.4 blocking→Task 7 Step 6, §5.4 recorded→Task 7 Step 7;
§5.5→Task 7 Step 10. §7's risks map to Task 1 Steps 4–5 (tmpfs, mode,
durability), Task 3 Step 5 (dev-instance guard), Task 6 Step 4 (CI start
failure), Task 7 Step 2 (destructive drop). Part B (§4 B1–B3) is deliberately out
of scope — separate plan.

**Three deviations from the spec**, each argued at the top of this document:
the `DATABASE_URL` comparison guard, `pytest_terminal_summary` in place of
`pytest_collection_finish` (the spec's hook provably never fires on the xdist
controller), and baselines measured after implementation.

**Placeholder scan:** no TBD/TODO, and no elided values — the connection string
is spelled out in full at every use. The one remaining `<job>` placeholder (Task 6
Step 7) is explicitly flagged as requiring substitution.

**Type consistency:** `_resolve_databases(env_value: str, current: dict) -> dict | None`
is annotated identically in Task 3's Interfaces block and its implementation.
`_should_emit_test_db_notice(*, has_e2e_items, env) -> bool` and `TEST_DB_NOTICE`
match between Task 4's tests and implementation. The connection string
`postgres://libli@127.0.0.1:55433/libli` is byte-identical in Tasks 1–5 and 7.
