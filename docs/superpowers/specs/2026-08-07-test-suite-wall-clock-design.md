# Test-suite wall clock: design

**Date:** 2026-08-07
**Status:** approved, ready for planning
**Baseline commit:** `828354c9` (clean tree; every measurement below was taken against this exact tree)

## 1. Problem

A full local run takes roughly an hour, and sessions sometimes run it more than
once. That wall clock is the dominant cost of a working session.

**"Full suite" means two separate pytest invocations**, because `pyproject.toml`
pins `addopts = "-q -m 'not e2e'"`:

| Selection | Invocation | Tests | Files | Local wall clock |
|---|---|---|---|---|
| unit / integration | `uv run pytest` | 5,104 | 549 | **not measured** |
| browser e2e | `uv run pytest -m e2e` | 845 | 97 | **not measured** |

**Neither half has been clocked in this investigation.** The "roughly an hour"
is the author's reported experience, not an observation made here. Establishing
the real numbers is the first deliverable (§5.1), and no benefit is claimed
against a baseline that does not yet exist.

Two structural facts about the unit half:

- Most non-e2e tests take pytest-django's `db` fixture, which **rolls back**
  rather than truncating, so Part A's benefit there may be near zero. That is a
  hypothesis, and §5.1 run 2 tests it directly rather than assuming it.
- `addopts` carries **no `-n`**, so a local `uv run pytest` runs all 5,104 tests
  **single-process**, while CI's `unit` job runs the identical selection at
  `-n auto`. This is an untested, zero-risk lever on the half of the hour Part A
  may not touch (§5.1, §5.3, §6).

## 2. What was measured

Unless stated otherwise, e2e timings use the **same 69 tests** —
`test_e2e_tabs.py`, `test_e2e_fillgate.py`, `test_e2e_guessnumber.py` — at
`-n 2`, at `828354c9`. All 69 passed in every configuration.

| Configuration | Sample (69 tests) | Draws |
|---|---|---|
| Windows + local Postgres (today) | 212.8 s / 258.0 s | 2 — replicated |
| Linux container + untuned Postgres | 273.8 s | **1 — provisional** |
| Windows + tuned test Postgres | 136.8 s / 129.2 s | 2 — replicated |
| Linux container + tuned Postgres | 76.7 s | **1 — provisional** |

Separately, and **measured over the real full selection rather than sampled**:
CI runs all 845 e2e tests at `-n 2` in **7 min 47 s**; the whole pipeline, three
parallel jobs, in **8 min 45 s**, consistently green.

**Single-draw rows are marked** because §2.4 forbids load-bearing single timings.
Every conclusion resting on them — the 3.57× tuned/untuned ratio in §2.1, and the
~1.7× sizing the deferred Linux move in §6 — is **provisional**, and §5.4
requires replication.

**"Windows + tuned test Postgres" means the Docker container defined in §3 A1,
reached from a native-Windows pytest over published port 55433** — exactly the
configuration Part A ships, including the Docker Desktop network hop. It was not
a native-Windows Postgres started with durability flags.

### 2.1 Findings that shaped the design

1. **No evidence that more workers help (e2e).** `-n 2` = 212 s, `-n 8` = 238 s.
   **Not a measured slowdown** — 238 s falls *inside* the 212.8–258.0 s band the
   same `-n 2` work produced on two draws. It shows only the absence of a
   demonstrated gain. See §6.
2. **Database creation is not the problem.** Eight test databases, all 78
   migrations: ~20 s total, once per run.
3. **Teardown dominates.** **Per-test means**, from a **28-test sample**
   (`test_e2e_fillgate.py` + `test_e2e_switchgrid.py`) in which **28 of 28 test
   functions take `live_server`** and therefore every one pays a truncate:

   | phase (per-test mean) | Windows + local PG | Linux container + untuned PG |
   |---|---|---|
   | `call` | 3.07 s | 1.66 s |
   | `setup` | 1.42 s | 0.83 s |
   | `teardown` | 3.30 s | 5.90 s |

4. **The quiescence barrier was innocent — under the old timing profile.** That
   run recorded no barrier timeouts and no deadlock retries. Part A changes every
   window that machinery was tuned against, so it must be re-checked (§5.4).
5. **Root cause: `TRUNCATE … CASCADE` across 89 tables**, at teardown of every
   test taking `live_server` — **537 of 630 e2e test functions**. Timed directly
   as a single statement **on the container Postgres**:

   | Postgres configuration | `TRUNCATE` of all 89 tables |
   |---|---|
   | default durability | **2,881 ms** |
   | `fsync=off`, `synchronous_commit=off`, `full_page_writes=off`, tmpfs PGDATA | **78 ms** |

   **37× faster**, with no change to any test.

   **Two honesty notes.** The database *state* for these timings was not
   recorded; §5.4 pins it and re-times both. And the truncate is roughly half of
   the container's 5.90 s teardown mean — **the ~3 s remainder is unidentified**
   (candidates: `live_server` shutdown, browser teardown, fixture finalizers,
   connection close).

   The remainder does **not** imply a ~1.5× ceiling. That inference assumes only
   the truncate improves, and the end-to-end number contradicts it: the same
   container went **273.8 s → 76.7 s (3.57×)** when tuned, because `fsync=off`
   and a tmpfs PGDATA also speed up `setup` and `call` writes. Both figures are
   single draws, so the *mechanism* is established but the *magnitude* awaits
   §5.4's replication.

**Denominators:** 845 is *collected e2e tests* (parametrized cases); 630 is *e2e
test functions* in source; 69 and 28 are collected tests in the named samples.
Per-test figures are per **collected test, over whichever selection the row
names**.

### 2.2 A hypothesis that was tested and rejected

The initial theory was that Windows was the root cause and moving to Linux was
the fix. That is **wrong**. An untuned Linux container was the *slowest*
configuration measured (273.8 s vs Windows' 212.8 s). The Linux runner is
genuinely faster at real test work (`call` 1.66 s vs 3.07 s; `setup` 0.83 s vs
1.42 s), but that was swamped by a database durability setting. The database is
the lever; the operating system is a secondary multiplier.

### 2.3 Why no full-suite wall clock is predicted here

CI runs an **untuned** Linux Postgres over the same 845 tests at `-n 2` in
**7 min 47 s** (0.55 s per collected test). The local untuned container measured
3.97 s per collected test *of its 69-test sample* — **7.2× slower on nominally
the same premise**. Two effects compound:

- **The sample is not representative.** All 69 sample tests take `live_server`
  and pay a truncate. The full 845 includes `test_e2e_math_reflow_dom.py` — 171
  tests, 20% of the selection — which uses no `live_server` and pays none.
- **Local container I/O is not CI I/O.** Docker Desktop nests virtualization and
  its PGDATA sits on a virtual disk, where fsync is far costlier than a GitHub
  runner's ephemeral NVMe. This is why the durability flags buy so much locally
  and comparatively little on CI.

**Consequence — stated precisely, because §5.2 does perform an arithmetic on
sample numbers:** no **full-suite wall-clock prediction** is made anywhere in
this document. §5.2 derives a **dimensionless ratio**; the absolute seconds in
that derivation are scaffolding for the ratio, not forecasts of how long a run
will take. Only §5.1's measured runs produce real wall clocks.

### 2.4 Other measurement caveats

- **Local Postgres has ~21% run-to-run variance** (212.8 s vs 258.0 s for
  identical work), so no single timing is load-bearing — the rule behind §5.2's
  protocol, the provisional container rows, and §5.1's replication requirement.
  The tuned Windows configuration was replicated and is tight, so the variance
  lives mostly in the baseline.
- **Sample speedup as a range:** **1.56× (212.8/136.8) to 2.00× (258.0/129.2)**,
  mean-over-mean ≈ **1.77×**.

## 3. Part A — Dedicated tuned test database

### A1. `docker-compose.test.yml` (new file, repo root)

Service key `test-db`, `container_name: libli-test-db`:

- image `postgres:16`
- ports: **`127.0.0.1:55433:5432`** — loopback-bound, *not* `0.0.0.0`
- **tmpfs sized 1 GB via the long `volumes:` form.** Compose's short-form
  `tmpfs:` key takes target paths only and cannot carry a size; using it would
  silently inherit the daemon default and leave §7's sizing mitigation not in
  force.

  ```yaml
  volumes:
    - type: tmpfs
      target: /var/lib/postgresql/data
      tmpfs:
        size: 1073741824   # 1 GiB
        mode: 0o1777
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U libli"]
    interval: 2s
    timeout: 3s
    retries: 15
  ```

  **`mode` is recorded, not guessed — but only in the docker-flag form.** The
  containers these measurements came from were started with
  `--tmpfs /var/lib/postgresql/data:rw,size=…,mode=1777` and came up cleanly.
  Postgres refuses a group/world-accessible data directory, but the `postgres:16`
  entrypoint tightens permissions after mount, so 1777 on the mount suffices.
  **The Compose `mode: 0o1777` above is a different parsing path** (YAML integer
  vs Docker flag string) and is **unverified**; the plan must confirm it, with a
  `PGDATA` sub-path (`/var/lib/postgresql/data/pgdata`) as the fallback. A4 uses
  the docker-flag form, which *is* the measured one, and carries no such
  obligation.

- command flags: `-c fsync=off -c synchronous_commit=off -c full_page_writes=off`
- env: `POSTGRES_USER=libli`, `POSTGRES_DB=libli`, `POSTGRES_HOST_AUTH_METHOD=trust`

Exact connection string, used verbatim in `.env.example` and the docs:

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli
```

Lifecycle. **The fixed `-p libli-test` project name is required**, not cosmetic:
Compose otherwise derives the project from the directory name, which differs per
worktree, yielding a different container in each.

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
docker compose -p libli-test -f docker-compose.test.yml down
```

`--wait` needs Compose v2.17+. `setup.md` states the minimum and the fallback
(plain `up -d` plus an explicit `pg_isready` poll).

Four properties, each answering a hazard: **non-default port 55433** (cannot be
confused with the instance holding dev and mat-pp data); **loopback binding** (a
`trust`-auth superuser Postgres must not be reachable from the local network);
**tmpfs, 1 GB** (a measured test database is **12 MB**; eight workers need
~96 MB, plus WAL and template databases — on Docker Desktop this is VM memory,
not disk); **`fsync=off`** (safe here and only here — nothing on this server
survives a restart by design).

### A2. Opt-in wiring in `config/settings/test.py`

A pure helper plus its call site, so this section and §5.4's test describe **one**
implementation:

```python
def _resolve_databases(env_value):
    """Return a DATABASES-shaped dict, or None for "no override".

    Raises ImproperlyConfigured on a non-empty but unparseable value.
    """
    if not env_value:
        return None
    try:
        return {"default": env.db_url_config(env_value)}  # noqa: F405
    except Exception as exc:
        raise ImproperlyConfigured(
            f"TEST_DATABASE_URL is not a valid database URL: {env_value!r}"
        ) from exc


_resolved = _resolve_databases(env("TEST_DATABASE_URL", default=""))  # noqa: F405
if _resolved is not None:
    DATABASES = _resolved
```

**Contract:** `None` means no override and the caller leaves `DATABASES`
untouched; any other return is a complete `DATABASES` dict.

Four deliberate choices:

- **`# noqa: F405` on the two lines using star-imported names** (`env`).
  `test.py` opens with `from config.settings.base import *`, so `env` is
  star-imported and ruff's `F` rule set raises `F405`. `STORAGES`, `TEMPLATES`
  and `BASE_DIR` in that file already carry the same suppression. Omitting it
  reds the CI `lint` job.
- **`env.db_url_config` rather than `base.py`'s `env.db(...)`.** `env.db()`
  parses its `default`, so "unset means no override" would need a sentinel URL
  that must itself be valid.
- **Malformed values fail loudly.** `db_url_config` does not validate strictly
  and would otherwise yield a config pointing somewhere unintended.
- **This lives in `test.py`, not `base.py`**, and **replacing `DATABASES`
  wholesale is safe because `base.py` defines only the `default` alias** —
  verified, not assumed. A future second alias makes this a silent drop and must
  change to a targeted update.

**Naming and precedence, for `.env.example` and `testing.md`:**
`TEST_DATABASE_URL` configures the *server the test database is created on*,
unrelated to Django's `DATABASES['default']['TEST']` dict, which configures *the
test database Django creates*. When both `DATABASE_URL` and `TEST_DATABASE_URL`
are present, **under `config.settings.test` the latter wins outright**.

### A3. Documentation

- **`.env.example`** — the commented `TEST_DATABASE_URL` line, the naming note,
  the precedence sentence. A commented line is inert, so **`testing.md` states
  one activation path** (uncomment it in `.env`) and notes a shell export also
  works; `base.py`'s `env.read_env` reads only `.env`.
- **`docs/development/setup.md`** — starting the service, the `--wait` version
  floor, and **Docker Desktop as a prerequisite for the tuned path** (the unset
  fallback remains supported). Its **test-command block at lines 98 and 107**
  points at `testing.md`.
- **`docs/development/conventions.md` — three edits:**
  1. **`## Testing` (lines 27–40)** rewritten to defer to `testing.md`. The
     `fsync=off` warning lands here.
  2. **Line 31's factual error**, corrected while that block is open: it claims
     "Tests live in one top-level **`tests/`** package (not per-app)", but
     `courses/tests/`, `integrations/tests/` and `notifications/tests/` all
     exist, and `tests/` holds only 505 of the 549 files. B2's corpus depends on
     this being right.
  3. **The definition-of-done sentence at line 96**, under **`## Migrations &
     checks`** — *not* under `## Testing` — reads "Both checks are part of the
     definition of done, alongside the ruff and pytest commands above". Its
     back-reference must be amended or it silently reinstates the local full run
     as DoD.
- **Root `README.md` — three edits:** the docs-index table gains a `testing.md`
  row; the **command block at lines 59–61** points at `testing.md`; and **line
  64** ("See `conventions.md` for the full checks CI runs") is redirected too —
  it is the sentence a reader hits immediately after the command block and still
  routes test guidance to the file being rewritten.

### A4. CI: tmpfs only, and why

`ci.yml` defines **two** Postgres services — one in `unit`, one in `e2e`. Both
gain `--tmpfs /var/lib/postgresql/data:rw,size=…,mode=1777` in `options:`.

**CI gets tmpfs but not the durability flags.** GitHub Actions service containers
accept no `command:` key, so `-c fsync=off …` cannot be passed as A1 passes it.
CI captures only part of the measured 37×.

**CI sizing is not A1's sizing.** The `unit` job runs `pytest -n auto` — worker
count is whatever the runner reports, not the 8 A1 sized against — and that job
additionally runs `manage.py migrate` and `setup_roles` against the real `libli`
database on the same mount. The plan must give an explicit CI tmpfs size covering
`-n auto` workers plus the migrated database.

**Each job is measured and judged independently.** They can reasonably diverge —
keep in one, drop in the other:

- **Before** = the median of the **last three green `master` runs** for that job
  (a single 7m47s observation is not a baseline; runner allocation varies).
- **After** = the median of **three runs** of that job with the tmpfs.
- **Keep** if `median_after ≤ median_before × 1.05`; drop otherwise. The 5%
  tolerance exists so a noise-level regression does not discard a change §2.3
  already predicts will be roughly neutral on CI.

### A5. An adoption nudge

The entire win is gated behind a developer starting a container and setting an
env var; without a prompt the speedup will be available and unused.

When e2e tests are selected and `TEST_DATABASE_URL` is unset, pytest emits a
one-line notice naming the compose command. Four things are pinned:

- **Hook location: the root `conftest.py`, not `tests/conftest.py`.** e2e tests
  live outside `tests/` — `integrations/tests/test_e2e.py`,
  `notifications/tests/test_e2e_bell.py`, `test_e2e_email_prefs.py`,
  `test_e2e_notifications.py` — and a directory conftest loads only for its own
  subtree, so the notice would silently never fire for those. The root
  `conftest.py` docstring already states this rule for exactly this reason.
- **Controller only:** guard with `if hasattr(config, "workerinput"): return`.
  Under xdist the hook runs in every worker, where the terminal reporter is
  absent or output swallowed — giving N duplicate lines or silence.
- **"e2e selected" means:** at least one *collected item* carries the `e2e`
  marker (hook: `pytest_collection_finish`). Inspecting `markexpr` would miss
  `-k` and direct-nodeid runs.
- **Suppressed under CI** (`CI` / `GITHUB_ACTIONS` env). CI's `e2e` job sets
  `DATABASE_URL` but not `TEST_DATABASE_URL`, so the notice would otherwise print
  on every CI run, advising a local container CI neither has nor needs.

It must be a **terminal-reporter line, not a `warnings.warn`**: node IDs in the
warnings summary have previously made an unanchored `grep FAILED` report failures
on a green run. `tests/conftest.py`'s barrier warning is the **pre-existing**
source of node IDs there; A5 declines to add a second one and is not responsible
for the existing hazard.

## 4. Part B — Affected-tests workflow

### B1. Documented practice — `docs/development/testing.md` (new file)

- **Locally:** run only affected tests, with per-file justification in the format
  established by `docs/superpowers/notes/2026-07-28-affected-tests-slice2.md`,
  including its "a red here is a REGRESSION, not migration" classification.
- **Branch gate:** push and let CI's 8m45s be the full-suite gate.
- **Never run the full suite locally twice in one session** — except for a
  deliberate benchmarking measurement (§5), which is not a gate run.
- **One run at a time against the shared test server.** `libli-test-db` is
  shared by every worktree, and xdist derives the same database names
  (`test_libli_gw0`…) in each. Two concurrent runs collide, and
  `docker compose down`/`restart` from one worktree destroys another's in-flight
  run. `testing.md` also documents the **per-worktree database-name option**
  (`…/libli_<worktree>`), which removes the name collision though not the restart
  hazard. **No `createdb` step is needed — verified:** pytest was pointed at a
  nonexistent source database and passed, because Django creates the test
  database through a no-db cursor.
- **Troubleshooting:** a connection error at session start almost always means
  `TEST_DATABASE_URL` is set but the container is down; the fix is `up -d --wait`.

The last three bullets plus the activation path are **container-dependent** and
are excised together if the §5.2 gate rejects Part A (§5.3).

### B2. `scripts/affected_tests.py`

Advisory, not authoritative.

**Interface — two pure functions plus a thin wrapper:**

```
normalize_name_status(lines: list[str]) -> list[str]
map_paths(paths: list[str], search: Callable[[str], set[str]]) -> Result
```

`normalize_name_status` consumes raw `--name-status` output and **follows renames
to the new path**. It **drops deleted paths only when they are test files** — a
deleted test file mapped to "itself" emits an unrunnable command that errors at
collection, but a deleted *source* file (a view, a model helper, a template) is a
high-blast-radius change whose referencing tests must still be selected. Deleted
non-test paths therefore flow through the normal per-path rules. It is pure, so
B3 tests it on literal `--name-status` lines; keeping it out of `map_paths` is
deliberate, since a bare `list[str]` carries no status codes.

**Corpus construction — `git ls-files` filtered by the configured `python_files`
pattern.** Not a filesystem walk, and not "derived from the collection
configuration": `pyproject.toml`'s `[tool.pytest.ini_options]` sets no
`testpaths`, so there is nothing to derive from. The tracked-files rule is also
load-bearing for correctness — this working tree contains **five nested
worktrees under `.claude/worktrees/`** holding **2,534** test files against the
repo's **645** real ones. They are gitignored and pytest skips them via the
default `norecursedirs`, but a naive walk or `rg` from the repo root would see
roughly four phantom files for every real one, blowing every breadth cap and
emitting node IDs pointing into a worktree.

`search(term)` returns the corpus files containing `term`. The CLI wrapper owns
**all** git and filesystem access; the two core functions perform none.

`Result` carries `unit_files`, `e2e_files`, `unmapped`, and **a reason per
selection** — `unit_reason` and `e2e_reason`, each `NONE | GLOBAL | CAPPED`. One
shared field cannot work: the caps are independent, so "unit capped, e2e fine"
and "e2e capped, unit fine" are both reachable and would collapse to one value.
`GLOBAL` is necessarily set on both. Each reason determines whether that
selection's emitted command is the candidate list or the full run.

**Diff range:** merge-base with **`origin/master`**, not local `master`, which is
routinely stale in a worktree; `--base` overrides, and a missing ref is a hard
error, never a silent empty diff.

**Global blast-radius class, checked first and short-circuiting.** Membership
criterion: *a path whose change can alter the behaviour of tests that do not
mention it.* Members, all as exact paths or globs so membership is decidable:

`tests/conftest.py`, root `conftest.py`, `tests/factories.py`,
`tests/db_quiesce.py`, `tests/deadlock_retry.py`, `config/settings/*.py`,
`config/urls.py`, `pyproject.toml`, `uv.lock`, `templates/base.html`,
`templates/allauth/layouts/**`, `templates/_*.html`, `locale/**/*.po`,
`locale/**/*.mo`

Two are easy to get wrong. **`config/urls.py`** would otherwise fall to the
module rule and map to almost nothing despite affecting every view test.
**`.mo` files** matter more than `.po`: Django loads compiled catalogs at
runtime, so a `.po` edit without recompilation changes no behaviour while a
committed `.mo` changes every assertion on translated strings — and a binary file
maps to nothing under the per-path rules. Binary paths generally are reported as
unmapped, never silently dropped.

Ordering is the point. `conftest.py` and `factories.py` *are* Python modules, so
without the short-circuit the module rule would emit a small, confidently-wrong
list — the failure mode "advisory only" does not protect against, because the
human sees a plausible list and trusts it.

**Per-path rules**, applied only when no global path is present:

| Changed path | Maps to |
|---|---|
| a test file | itself |
| a Python module | tests referencing its import path, or its module-level public defs/classes, matched on **word boundaries** |
| a template / CSS / JS file | tests referencing that filename |
| a migration | transfer and model tests |

**"A test file" means a path matching the configured `python_files` pattern**
(`test_*.py`), not "lives in a test directory". `tests/capture_help_screenshots.py`
sits in `tests/` and defines `test_`-named functions but is deliberately not
collectible; mapping it to itself would emit a command that exits 5.

**"Its symbols"** is bounded: **module-level public defs and classes only** (no
methods, no private names), word-boundary matched. Unbounded matching on common
names (`Element`, `render`, `save`, `index`) would select a large fraction of the
corpus — indistinguishable from the full suite, and a silent failure.

**Breadth cap, per selection.** Unit: **40 files** of 549. e2e: **15 files** of
97. A joint cap would be dominated by the unit side.

**Unit/e2e classification.** A file is e2e iff its name matches `test_e2e_*.py`
**or** it contains an `e2e` marker; both are checked. The emitted e2e command
**always carries `-m e2e`**, and the output states that **exit code 5 means
"nothing selected", not "green"** — an e2e path in the unit invocation is
silently deselected by the existing `-m 'not e2e'`.

### B3. Tests for the helper — `tests/test_affected_tests.py`

Named explicitly because `scripts/` sits outside every test directory and
`pyproject.toml` sets no `testpaths`; this location guarantees collection by the
existing configuration.

**Core, on stubs:** each mapping rule; the global short-circuit; both breadth
caps; per-selection reason discrimination; binary-path reporting; the unit/e2e
split; the `python_files` definition of "test file"; unmapped reporting; and
`normalize_name_status` on literal `--name-status` lines covering additions,
renames, deleted *test* files (dropped) and deleted *source* files (retained).

**Corpus:** a case asserting that a path under an ignored directory
(`.claude/worktrees/…`) never enters the corpus.

**Wrapper**, where the highest-consequence behaviour lives — the `-m e2e` flag,
the exit-5 caveat, `--name-status` invocation, the `origin/master` hard error,
corpus construction. One integration test against a **deterministic fixture
repository built in `tmp_path`** with a known commit and a known `origin/master`
ref — not "a real recent diff", whose content changes with every branch, making
assertions either vacuous or perpetually broken. Assertions: the e2e command
carries `-m e2e`; the exit-5 caveat appears in the output; a missing base ref
fails loudly.

## 5. Verification

### 5.1 Establish the baselines that do not yet exist

| # | Run | `TEST_DATABASE_URL` | Draws | Purpose |
|---|---|---|---|---|
| 1 | `uv run pytest` (single-process) | unset | 2 | unit baseline |
| 2 | `uv run pytest` (single-process) | **set** | 2 | tests §1's "benefit may be near zero" hypothesis |
| 3 | `uv run pytest -n auto` | **unset** | 2 | isolates the parallelism lever from Part A |
| 4 | `uv run pytest -m e2e` | unset | 2 | e2e baseline |
| 5 | `uv run pytest -m e2e` | **set** | 2 | **the headline full-suite magnitude** |

Run 5 exists because §5.2 deliberately gates on a 69-test sample; without it the
full-suite e2e benefit — the point of the whole design — would be measured
nowhere, and §1's "no benefit is claimed against a baseline that does not yet
exist" would never be discharged.

**Two draws per run, decided on paired medians**, because §2.4's ~21% variance
makes any single-draw comparison unreliable — the same rule that made the
container rows provisional. Runs 1 and 3 in particular feed §5.3's ≥1.25×
threshold, which sits inside the noise band a single draw can produce.

**Instrumentation, required on the e2e runs:** capture `--durations`, and record
the per-test cost of `test_e2e_math_reflow_dom.py` specifically. That is the only
quantity §5.2's 0.4 s assumption concerns, and without it the "recompute the bar"
path cannot recompute anything.

**Execution mechanics**, because long invocations have known failure modes here:

- launch **detached** and poll the PID — a backgrounded run can otherwise be
  reaped mid-flight and read as a fast finish;
- record per run: wall clock **per selection**, worker count, `TEST_DATABASE_URL`
  state, exit code, and the three warning counts below;
- a missing exit code is not a timing — a killed run must never be reported as a
  slow one.

**Cleanup between runs**, or the next dies with `DuplicateDatabase` — and the two
arms differ:

- **Container arm:** `docker compose -p libli-test -f docker-compose.test.yml down`
  wipes everything (tmpfs).
- **Local-instance arm:** `test_libli*` databases are left on the developer's
  **real** Postgres. Dropping them is the one destructive action in this design,
  so the command must target **only** names matching `test_libli%` and must be
  reviewed before running.

**How to observe the "counters" of §5.4 — they are not counters.** All three
surface only as warning text in pytest's warnings summary, which `-q` still
prints. Grep for these strings (line numbers deliberately omitted; the text is
on the line after each `warnings.warn(`):

- `"live_server still busy at teardown of"` — barrier timeout
- `"teardown TRUNCATE deadlocked"` — deadlock retry
- `"could not quiesce the browser at teardown"` — the browser-offline/blank step
  raised, leaving the database **not** quiesced before the truncate. Part A's
  changed timing profile can plausibly perturb this path, and grepping only the
  first two would report a clean run while it fires.

`wait_for_db_quiescence` returns `False` rather than raising, so an implementer
who does not look will report zero by default.

### 5.2 The acceptance gate

**Gate on a fixed named subset, not the full suite.** The gate needs replication,
and replicating full runs would cost hours on a design whose purpose is to
reclaim them. Run 5 supplies the full-suite magnitude separately.

- **Subject:** the 69-test sample named in §2, `-m e2e`.
- **Data:** **four fresh runs at the implementation commit** — §2's draws are
  *not* reused; they predate any Part A code, and the gate must measure what
  ships.
- **Protocol:** two before, two after; *same commit, same machine*, **`-n 2`
  fixed**, toggling **only** `TEST_DATABASE_URL`. **The container must be running
  for all four runs**, including the before arm — otherwise the arms differ by
  the whole cost of the Docker Desktop VM, a confounder the size of the effect.
- **`-n` sweeps (§5.4) happen after the gate is decided and never feed it**, or
  the best `-n` could be reported as the "after".

**Decision statistic: worst-case speedup = fastest *before* ÷ slowest *after*.**
Both are wall-clock seconds; the quotient is dimensionless and exceeds 1 when
Part A helps. (Stated explicitly because the inverted form — slowest-after ÷
fastest-before — yields ≈0.64 on §2's numbers and can never clear a bar above 1.)

**Thresholds — this table is the single authority; no other bar is stated
anywhere:**

| Worst-case speedup | Outcome |
|---|---|
| ≥ 1.45× | accept |
| 1.30× ≤ x < 1.45× | **inconclusive** — take **two additional draws per arm** (4 before, 4 after) and accept iff **median before ÷ median after ≥ 1.45×**; otherwise reject |
| < 1.30× | reject, per §5.3 |

**Where the thresholds come from:**

> Worst-case pairing on §2's data — fastest before (212.8 s) ÷ mean after
> (133.0 s), over 69 tests: 3.08 s/test → 1.93 s/test = **1.60×** on
> truncate-paying tests. This is deliberately lower than §2.4's 1.77×
> mean-over-mean, because it pairs the fastest before draw with the mean after,
> matching the decision statistic's pessimism.
>
> Diluting to the full 845: roughly 171 tests (`math_reflow_dom`) pay no truncate.
> Assuming those cost ~0.4 s each (**unmeasured — the largest assumption here**;
> §5.1 now measures it), the ratio falls to **≈1.57×**. The absolute seconds
> behind that figure are scaffolding for the ratio, not a wall-clock prediction
> (§2.3).

**Population, which the thresholds must match.** The derivation above dilutes to
the full suite, but the gate measures the **sample**, where all 69 tests pay a
truncate and the undiluted ratio is the 1.60×-class number. Applying a diluted
threshold to an undiluted measurement would systematically accept changes whose
full-suite effect is below the intended bar. **The thresholds in the table are
therefore stated for the sample**, and the relationship is:

```
sample_threshold = full_suite_target × (sample_ratio / diluted_ratio)
                 = full_suite_target × (1.60 / 1.57)
```

If §5.1's per-file durations invalidate the 0.4 s assumption, the dilution factor
moves; the thresholds are recomputed through that formula **before the gate is
run**, never after seeing the result.

**On the 674 used in the dilution:** §2.1 says 93 of 630 *functions* skip the
truncate while the derivation assumes 171 of 845 *collected tests* do. These
reconcile through parametrization, but 674 is an **approximation ignoring
non-`live_server` functions outside `math_reflow_dom`**, so it slightly overstates
the truncate-paying share. §5.1's per-file durations replace it.

### 5.3 Revert semantics, per deliverable

| On a rejected gate | Outcome |
|---|---|
| **A1** compose file | removed |
| **A2** settings wiring | removed |
| **A5** adoption notice | removed (it would point at a deleted compose file) |
| **A3** docs | **retained**, container sections excised |
| **A4** CI tmpfs | **judged only by its own rule in §A4**, per job, never by the local gate |
| **Part B** | **retained**, *except* `testing.md`'s container-dependent content — the one-run-at-a-time rule, the per-worktree name option, the troubleshooting line and the activation path — excised on the same rule as A3. `scripts/affected_tests.py` and B1's affected-tests practice have no dependency on Part A and survive intact |

A rejected gate also returns the §6 shared-connection rewrite to scope.

**The `-n auto` result must also produce an action**, or §1's "cheapest available
lever" terminates in a number in a note. Comparing **paired medians of runs 3 and
1** (both unset, two draws each per §5.1): if run 3 beats run 1 by **≥1.25×**,
`testing.md` documents `-n auto` as the local unit command. **`addopts` is not
touched** — it is shared with CI, where `-n auto` is already passed explicitly,
and changing it would alter CI's effective invocation as a side effect.

### 5.4 Also required

- **The suite must stay green** on both selections.
- **All three warning strings must stay at zero**, observed per §5.1. Finding 4
  was taken under the old timing profile, and Part A changes every window that
  machinery was tuned against. Green alone is not evidence: a retried deadlock
  still reports green, so a regression in the apparatus §6 refuses to touch would
  be invisible.

  **Scope limit, stated because the check is otherwise falsely reassuring:** the
  barrier and deadlock-retry fixtures live in `tests/conftest.py`, a *directory*
  conftest, so they never load for the four e2e files outside `tests/`
  (`integrations/tests/test_e2e.py`, `notifications/tests/test_e2e_bell.py`,
  `test_e2e_email_prefs.py`, `test_e2e_notifications.py`). Zero warnings from
  those files is guaranteed regardless of Part A. The must-stay-zero claim is
  therefore scoped to `tests/`, and those four need a separate
  green-and-no-teardown-error check.
- **Time `TRUNCATE` directly on the Windows Postgres**, closing §2.1's inference.
  **Both this and a re-run of the container timings must pin the database state**
  — a freshly migrated test database immediately after one e2e test's fixtures —
  since the original figures did not record theirs, and an empty-table truncate is
  not comparable to a populated one.
- **Replicate the two single-draw container runs** (§2), so the 3.57× figure and
  §6's ~1.7× rest on more than n=1.
- **Record both CI jobs' before/after** per §A4's rule.
- **Test the A2 wiring.** **Do not re-import `config.settings.test` the way
  `tests/test_settings_production.py` re-imports production** — that pattern is
  safe only because production is not the active settings module. `test.py`
  line 24 does
  `TEMPLATES[0]["DIRS"] = [*TEMPLATES[0]["DIRS"], BASE_DIR / "tests" / "templates"]`,
  and since `base` is not popped, `TEMPLATES[0]` is the same dict object
  `django.conf.settings` references — every re-import appends another copy to live
  global state. Test the pure `_resolve_databases` helper instead, covering:
  empty string → `None`; valid URL → parsed `DATABASES`-shaped dict; malformed
  value → `ImproperlyConfigured` quoting the value. Mutant: make the helper
  return a dict for the empty case so the override applies unconditionally, and
  require red.
- **Test A5**, whose three pinned behaviours are each silent-failure modes: assert
  the notice fires exactly once for an e2e-selecting invocation, does not fire
  when `TEST_DATABASE_URL` is set, and does not fire on a unit-only run. Mutant:
  remove the worker guard, require red.
- **Re-measure `-n 4` and `-n 8`** on the e2e selection after Part A lands (§6).

### 5.5 Where results are recorded

All measured numbers land in a new note under `docs/superpowers/notes/`, dated
and naming the commit measured. This spec is pinned to `828354c9` and is **not**
retro-edited with post-implementation results.

## 6. Non-goals

**The shared-connection teardown rewrite is excluded.** Making `live_server`
share the test's connection so e2e could roll back instead of truncating would
address the same 537 tests, but the 37× truncate win already captures most of
that prize. The rewrite would drive a change through the middle of the
`db_quiesce.py` / `deadlock_retry.py` apparatus — machinery built over several
iterations against a real, measured deadlock — for the remainder. Re-enters scope
only if §5.2's gate is rejected.

**More xdist workers on the *e2e* selection: excluded for now, on weak and
perishable evidence.** `-n 8` (238 s) vs `-n 2` (212 s) sits inside the
212.8–258.0 s noise band, so it shows no gain rather than a loss. And the
mechanism that would explain a real loss — `TRUNCATE … CASCADE` taking
`AccessExclusiveLock` on 89 tables, serializing concurrent workers — is largely
removed by Part A. Hence the mandatory re-measurement in §5.4.

**This non-goal does not extend to the unit selection.** Its mechanism does not
apply to `db`-fixture rollback tests, no measurement was ever taken there, and CI
already runs that selection at `-n auto`. Measuring it is a §5.1 deliverable and
acting on it is a §5.3 rule.

**`--no-migrations` and `--reuse-db`: rejected.** They target test-database
creation, ~20 s per run (§2.1) — not the bottleneck. `--reuse-db` is additionally
incompatible with a tmpfs server wiped whenever the container restarts.

**Moving the runner to Linux is deferred**, not rejected. It may be worth a
further ~1.7× on top of Part A — a **provisional, single-draw** figure (§2) that
§5.4 replicates — but it needs root for Chromium's system libraries and so cannot
be automated unattended. Revisit once §5.1's real numbers exist.

## 7. Risks

| Risk | Mitigation |
|---|---|
| `fsync=off` applied to the real instance | Separate container, non-default port 55433, warning in `conventions.md` |
| Trust-auth superuser Postgres exposed to the local network | Bind `127.0.0.1:55433:5432`, never `0.0.0.0` (A1) |
| **`TEST_DATABASE_URL` set but the container is down** — the recurring daily failure, since the var stays set once activated while the container does not stay up | Connection error at session start; `testing.md` troubleshooting maps it to `up -d --wait`. A5 cannot cover this by construction (it fires only when the var is *unset*) |
| Dropping `test_libli*` on the real local instance during §5.1 cleanup | The one destructive action in this design: the command must match only `test_libli%` and be reviewed before running |
| tmpfs too small | 1 GB against a measured 12 MB/database × 8 workers, set via the long `volumes:` form so the size actually applies. Symptom is not an obvious "disk full": Postgres reports `could not extend file …: No space left on device`, or `PANIC: could not write to file`, mid-run |
| Compose `mode: 0o1777` does not reproduce the measured docker-flag `mode=1777` | Container fails to start immediately and visibly; fallback is a `PGDATA` sub-path (A1) |
| CI Postgres fails to start on tmpfs | Job red immediately. Revert = drop the tmpfs line from that job's `options:`; nothing else depends on it |
| CI tmpfs starts but gives no gain | §A4's per-job rule: keep if `median_after ≤ median_before × 1.05` |
| Corpus picks up the 2,534 test files in nested worktrees | Corpus built from `git ls-files`, never a filesystem walk; B3 asserts an ignored path never enters it |
| Compose project name differs per worktree, yielding one container each | Fixed `-p libli-test` in every documented command (A1) |
| Two worktrees run against the shared container at once | One-run-at-a-time rule plus the per-worktree database-name option (B1) |
| `affected_tests.py` misses an affected test | Advisory only; CI full suite remains the gate; global short-circuit, per-selection breadth caps, and explicit unmapped reporting keep gaps visible |
| Developers never adopt the opt-in database | Controller-only terminal notice, suppressed under CI (A5) |
| Developer has no Docker Desktop | Prerequisite in `setup.md`; the unset fallback is a supported configuration |
