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
is the author's reported experience, not an observation made here. Every
sample-based projection has been removed (§2.3 explains why they were
untrustworthy). Establishing the two real numbers is the first deliverable
(§5.1), and no benefit is claimed against a baseline that does not yet exist.

Two structural facts about the unit half, neither previously noted:

- Most non-e2e tests take pytest-django's `db` fixture, which **rolls back**
  rather than truncating, so Part A's benefit there may be near zero.
- `addopts` carries **no `-n`**, so a local `uv run pytest` runs all 5,104 tests
  **single-process**, while CI's `unit` job runs the identical selection at
  `-n auto`. This is an untested, zero-risk lever on the half of the hour Part A
  may not touch (§5.1, §6).

## 2. What was measured

Unless stated otherwise, e2e timings use the **same 69 tests** —
`test_e2e_tabs.py`, `test_e2e_fillgate.py`, `test_e2e_guessnumber.py` — at
`-n 2`, at `828354c9`. All 69 passed in every configuration.

| Configuration | Sample (69 tests) |
|---|---|
| Windows + local Postgres (today) | 212.8 s / 258.0 s |
| Linux container + untuned Postgres | 273.8 s |
| Windows + tuned test Postgres | 136.8 s / 129.2 s |
| Linux container + tuned Postgres | 76.7 s |

Separately, and **measured over the real full selection rather than sampled**:
CI runs all 845 e2e tests at `-n 2` in **7 min 47 s**; the whole pipeline, three
parallel jobs, in **8 min 45 s**, consistently green.

**"Windows + tuned test Postgres" means the Docker container defined in §3 A1,
reached from a native-Windows pytest over published port 55433** — i.e. exactly
the configuration Part A ships, including the Docker Desktop network hop. It was
not a native-Windows Postgres started with durability flags.

### 2.1 Findings that shaped the design

1. **No evidence that more workers help.** The same 69 tests: `-n 2` = 212 s,
   `-n 8` = 238 s. **This is not a measured slowdown** — 238 s falls *inside* the
   212.8–258.0 s band the same `-n 2` work produced on two draws (§2.4). It
   establishes only the absence of a demonstrated gain. See §6.
2. **Database creation is not the problem.** Eight test databases, all 78
   migrations: ~20 s total, once per run.
3. **Teardown dominates.** Figures below are **per-test means**, from a
   **28-test sample** (`test_e2e_fillgate.py` + `test_e2e_switchgrid.py`) in
   which **28 of 28 test functions take `live_server`** and therefore every one
   pays a truncate:

   | phase (per-test mean) | Windows + local PG | Linux container + untuned PG |
   |---|---|---|
   | `call` | 3.07 s | 1.66 s |
   | `setup` | 1.42 s | 0.83 s |
   | `teardown` | 3.30 s | 5.90 s |

4. **The quiescence barrier was innocent — under the old timing profile.** That
   run recorded 0 barrier timeouts and 0 deadlock retries. Part A changes every
   window that machinery was tuned against, so the counters must be re-checked
   (§5.4).
5. **Root cause: `TRUNCATE … CASCADE` across 89 tables**, run at teardown of
   every test taking `live_server` — **537 of 630 e2e test functions**. Timed
   directly as a single statement **on the container Postgres**:

   | Postgres configuration | `TRUNCATE` of all 89 tables |
   |---|---|
   | default durability | **2,881 ms** |
   | `fsync=off`, `synchronous_commit=off`, `full_page_writes=off`, tmpfs PGDATA | **78 ms** |

   **37× faster**, with no change to any test.

   **Two honesty notes.** The database *state* for these two timings was not
   recorded; §5.4 pins the state and re-times both. And the truncate accounts for
   roughly half of the container's 5.90 s teardown mean — **the ~3 s remainder is
   unidentified** (candidates: `live_server` shutdown, browser teardown, fixture
   finalizers, connection close). The Windows truncate was **not** timed in
   isolation at all; its 3.30 s teardown mean is *consistent with* a truncate of
   similar magnitude, but that is an inference, and §5.4 closes it.

   The unidentified remainder does **not** imply a ~1.5× ceiling on Part A. That
   inference assumes only the truncate improves, and it is falsified by direct
   measurement: the same container went **273.8 s → 76.7 s (3.57×)** when tuned,
   because `fsync=off` and a tmpfs PGDATA speed up `setup` and `call` writes too,
   not merely the truncate.

**Denominators:** 845 is *collected e2e tests* (parametrized cases); 630 is
*e2e test functions* in source; 69 and 28 are collected tests in the named
samples. Per-test figures are per **collected test, over whichever selection the
row names** — sample rows divide by 69 or 28, the CI figure by 845.

### 2.2 A hypothesis that was tested and rejected

The initial theory was that Windows was the root cause and that moving the
runner to Linux was the fix. That is **wrong**. An untuned Linux container was
the *slowest* configuration measured (273.8 s vs Windows' 212.8 s). The Linux
runner is genuinely faster at real test work (`call` 1.66 s vs 3.07 s; `setup`
0.83 s vs 1.42 s), but that advantage was swamped by a database durability
setting. The database is the lever; the operating system is a secondary
multiplier.

### 2.3 Why no full-suite figure is extrapolated here

CI runs an **untuned** Linux Postgres over the same 845 tests at the same `-n 2`
in **7 min 47 s** (0.55 s per collected test). The local untuned Linux container
measured 3.97 s per collected test *of its 69-test sample* — **7.2× slower on
nominally the same premise**. Two effects compound, both in the same direction:

- **The sample is not representative.** All 69 sample tests take `live_server`
  and pay a truncate. The full 845 includes `test_e2e_math_reflow_dom.py` — 171
  tests, 20% of the selection — which uses no `live_server` and pays none.
  Per-test extrapolation from the sample therefore *overstates* full-suite time.
- **Local container I/O is not CI I/O.** Docker Desktop nests virtualization and
  its PGDATA sits on a virtual disk, where fsync is far more expensive than a
  GitHub runner's ephemeral NVMe. This is precisely why the durability flags buy
  so much locally and comparatively little on CI.

**Consequence:** the sample predicts the *direction and mechanism* of the win,
not its magnitude. No full-suite cell is derived from it anywhere in this
document. Only §5.1's measured runs settle the size of the benefit, and Part A
is gated on §5.2.

### 2.4 Other measurement caveats

- **Local Postgres has ~21% run-to-run variance** (212.8 s vs 258.0 s for
  identical work), so no single timing is load-bearing — a rule §5.2's gate
  protocol is built to respect. The tuned configuration was replicated and is
  tight (136.8 s / 129.2 s), so the variance lives mostly in the baseline.
- **Sample speedup as a range:** **1.56× (212.8/136.8) to 2.00× (258.0/129.2)**,
  mean-over-mean ≈ **1.77×**. Quoting a single "1.8×" would silently pair the
  slow baseline with the fast tuned run.

## 3. Part A — Dedicated tuned test database

### A1. `docker-compose.test.yml` (new file, repo root)

Service key `test-db`, with `container_name: libli-test-db`:

- image `postgres:16`
- ports: **`127.0.0.1:55433:5432`** — loopback-bound, *not* `0.0.0.0`
- **tmpfs sized 1 GB via the long `volumes:` form**, because Compose's short-form
  `tmpfs:` key takes target paths only and cannot carry a size — using it would
  silently inherit the daemon default and leave §7's sizing mitigation not
  actually in force:

  ```yaml
  volumes:
    - type: tmpfs
      target: /var/lib/postgresql/data
      tmpfs:
        size: 1073741824   # 1 GiB
  ```

- command flags: `-c fsync=off -c synchronous_commit=off -c full_page_writes=off`
- env: `POSTGRES_USER=libli`, `POSTGRES_DB=libli`, `POSTGRES_HOST_AUTH_METHOD=trust`
- `healthcheck`: `pg_isready -U libli`

Exact connection string, used verbatim in `.env.example` and the docs:

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli
```

Lifecycle commands. **The fixed `-p libli-test` project name is required**, not
cosmetic: Compose otherwise derives the project from the directory name, which
differs per worktree, so the same file would yield a different container in each.

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
docker compose -p libli-test -f docker-compose.test.yml down
```

`--wait` needs Compose v2.17+. `setup.md` states the minimum and gives the
fallback: plain `up -d` followed by an explicit `pg_isready` poll.

Four properties matter, each answering a specific hazard:

- **Non-default port 55433** — cannot be confused with the instance holding dev
  and mat-pp data.
- **Loopback binding** — a `trust`-auth superuser Postgres must not be reachable
  from the local network. Docker's default publishing binds `0.0.0.0`.
- **tmpfs, 1 GB** — a measured test database is **12 MB**; eight xdist workers
  need ~96 MB, plus WAL and template databases. On Docker Desktop a tmpfs
  consumes VM memory, not disk.
- **`fsync=off`** — safe here and only here: the server holds nothing that is
  not regenerated by the next run.

### A2. Opt-in wiring in `config/settings/test.py`

```python
_test_db = env("TEST_DATABASE_URL", default="")  # noqa: F405
if _test_db:
    DATABASES = {"default": env.db_url_config(_test_db)}  # noqa: F405
```

Three deliberate choices:

- **`# noqa: F405`** is required. `test.py` opens with
  `from config.settings.base import *`, so `env` is a star-imported name and
  ruff's `F` rule set raises `F405`. Every existing star-imported name in that
  file — `STORAGES`, `TEMPLATES`, `BASE_DIR` — already carries the same
  suppression. Omitting it reds the CI `lint` job.
- **`env.db_url_config` rather than `base.py`'s `env.db(...)` idiom.** `env.db()`
  parses its `default`, so expressing "unset means no override" through it would
  require a sentinel URL that must itself be valid.
- **This lives in `test.py`, not `base.py`.** No code path lets dev or production
  point at the throwaway server.

**Naming note for `.env.example` and the docs:** `TEST_DATABASE_URL` configures
the *server the test database is created on*. It is unrelated to Django's
`DATABASES['default']['TEST']` dict, which configures *the test database Django
creates*.

### A3. Documentation

- **`.env.example`** gains the commented `TEST_DATABASE_URL` line plus the naming
  note. A commented line is inert, so **`testing.md` states one activation path
  explicitly** — uncomment it in your `.env` — and notes that a shell export
  works too. `base.py`'s `env.read_env` reads only `.env`.
- **`docs/development/setup.md`** covers starting the service, the `--wait`
  flag and its version floor, and **lists Docker Desktop as a prerequisite for
  the tuned path** — the fallback (no `TEST_DATABASE_URL`) remains the supported
  configuration for anyone without it. Its **test-command block at lines 98 and
  107** must point at `testing.md`.
- **`docs/development/conventions.md` — two separate edits, at two anchors that
  must not be conflated:**
  1. **`## Testing` (lines 27–40)** is rewritten to defer to `testing.md` for
     what runs locally versus what CI gates. The `fsync=off` warning lands here.
  2. **The definition-of-done sentence at line 96**, which lives under
     **`## Migrations & checks`** — *not* under `## Testing` — reads "Both checks
     are part of the definition of done, alongside the ruff and pytest commands
     above". Its back-reference to "the pytest commands above" must be amended,
     or it silently reinstates the local full run as DoD.
- **Root `README.md`** — the docs-index table gains a `testing.md` row, **and its
  command block at lines 59–61**, which presents `uv run pytest` as the way to
  run tests, points at `testing.md`. An index row alone leaves the contradiction
  live in a second file.

### A4. CI: tmpfs only, and why

`.github/workflows/ci.yml` defines **two** Postgres services — one in the `unit`
job, one in the `e2e` job. **Both** gain a sized tmpfs in their `options:`.

**CI gets tmpfs but not the durability flags.** GitHub Actions service containers
accept no `command:` key, so `-c fsync=off …` cannot be passed the way A1 passes
it. CI therefore captures only part of the measured 37×.

**CI sizing is not A1's sizing, and must be stated explicitly.** The `unit` job
runs `pytest -n auto` — worker count is whatever the runner reports, not the 8
that A1 sized against — and that job additionally runs `manage.py migrate` and
`setup_roles` against the real `libli` database on the same mount. The plan must
give an explicit CI tmpfs size covering `-n auto` workers plus the migrated
database, rather than inheriting A1's 1 GB reasoning.

No CI gain is claimed in advance; the before/after is recorded per §5.4. Because
a `postgres:16` PGDATA on tmpfs is a known permissions/init edge case, §7 carries
the failure mode and its revert.

### A5. An adoption nudge

The entire win is gated behind a developer starting a container and setting an
env var. Without a prompt, the realistic outcome is that the speedup is
available and unused.

When e2e tests are selected and `TEST_DATABASE_URL` is unset, pytest emits a
one-line notice naming the compose command. Three things must be pinned, or the
feature silently does nothing or spams:

- **Hook:** `pytest_collection_finish` in `tests/conftest.py`.
- **Controller only:** guard with `if hasattr(config, "workerinput"): return`.
  Under xdist the hook runs in every worker, where the terminal reporter is
  absent or output is swallowed — giving N duplicate lines or total silence.
- **"e2e selected" means:** at least one *collected item* carries the `e2e`
  marker. Inspecting `markexpr` instead would miss `-k` and direct-nodeid runs.

It must be a **terminal-reporter line, not a `warnings.warn`**: node IDs in the
warnings summary have previously made an unanchored `grep FAILED` report
failures on a green run.

## 4. Part B — Affected-tests workflow

### B1. Documented practice — `docs/development/testing.md` (new file)

- **Locally:** run only affected tests, with per-file justification in the
  format established by
  `docs/superpowers/notes/2026-07-28-affected-tests-slice2.md`, including its
  "a red here is a REGRESSION, not migration" classification.
- **Branch gate:** push and let CI's 8m45s be the full-suite gate.
- **Never run the full suite locally twice in one session** — except for a
  deliberate benchmarking measurement (§5), which is not a gate run.
- **One run at a time against the shared test server.** `libli-test-db` is a
  single container shared by every worktree, and xdist derives the same database
  names (`test_libli_gw0`…) in each. Two concurrent runs collide, and
  `docker compose down`/`restart` from one worktree destroys another's in-flight
  run. `testing.md` also mentions the **per-worktree database-name option**
  (`…/libli_<worktree>` in `TEST_DATABASE_URL`), which removes the name
  collision entirely though not the restart hazard.

### B2. `scripts/affected_tests.py`

Advisory, not authoritative.

**Interface.** The core cannot be a pure function of the changed paths alone: to
answer "which tests reference this symbol or filename" it must consult the test
corpus. That dependency is *injected* rather than performed, which is what keeps
it testable:

```
map_paths(paths: list[str], search: Callable[[str], set[str]]) -> Result
```

`search(term)` returns the test files containing `term`. The CLI wrapper builds
it over `tests/` (and the per-app test packages) and owns **all** git and
filesystem access; `map_paths` performs none. B3's fixtures therefore supply a
plain path list plus a stub `search`, with no temporary repository or corpus.

`Result` carries `unit_files`, `e2e_files`, `unmapped`, and a **`full_reason`
enum** — `NONE | GLOBAL | CAPPED`. A single boolean cannot distinguish the two
independent causes of a full-suite recommendation, and B3 must assert on the
distinction.

**Diff consumption:** the wrapper reads `--name-status`, **drops deleted paths**
(mapping a deleted test file to "itself" emits an unrunnable command that errors
at collection), and **follows renames to the new path**. The default range is
merge-base with **`origin/master`**, not local `master`, which is routinely stale
in a worktree; `--base` overrides, and a missing ref is a hard error, never a
silent empty diff.

**Global blast-radius class, checked first and short-circuiting.** Membership
criterion, so future additions are decidable rather than guessed: *a path whose
change can alter the behaviour of tests that do not mention it.* Current members:

`tests/conftest.py`, `conftest.py`, `tests/factories.py`, `tests/db_quiesce.py`,
`tests/deadlock_retry.py`, `config/settings/*.py`, `config/urls.py`,
`pyproject.toml`, `uv.lock`, the base/layout templates, `locale/**/*.po`,
`locale/**/*.mo`

Two of these are easy to get wrong. **`config/urls.py`** would otherwise fall to
the module rule and map to almost nothing despite affecting every view test.
**`.mo` files** matter more than `.po`: Django loads the compiled catalogs at
runtime, so a `.po` edit without recompilation changes no behaviour while a
committed `.mo` changes every assertion on translated strings — and a binary file
maps to nothing under the per-path rules. Binary paths generally are reported as
unmapped, never silently dropped.

Ordering is the point. `conftest.py` and `factories.py` *are* Python modules, so
without the short-circuit the module rule would fire and emit a small,
confidently-wrong candidate list — the one failure mode "advisory only" does not
protect against, because the human sees a plausible list and trusts it.

**Per-path rules**, applied only when no global path is present:

| Changed path | Maps to |
|---|---|
| a test file | itself |
| a Python module | tests referencing its import path, or its module-level public defs/classes, matched on **word boundaries** |
| a template / CSS / JS file | tests referencing that filename |
| a migration | transfer and model tests |

"Its symbols" is bounded deliberately: **module-level public defs and classes
only** (no methods, no private names), word-boundary matched. Unbounded matching
on common names (`Element`, `render`, `save`, `index`) would select a large
fraction of 549 files — indistinguishable from the full suite, and a silent
failure.

**Breadth cap, evaluated per selection, not jointly.** Unit: **40 files** of 549.
e2e: **15 files** of 97. A joint cap would be dominated by the unit side and push
most non-trivial changes straight to "too broad", making the script useless. Over
the cap, that selection reports `CAPPED` and recommends its full run.

**Unit/e2e classification.** A file is e2e iff its name matches `test_e2e_*.py`
**or** it contains an `e2e` marker; both are checked, not assumed equivalent. The
emitted e2e command **always carries `-m e2e`**, and the output states that
**exit code 5 means "nothing selected", not "green"** — an e2e path landing in
the unit invocation is silently deselected by the existing `-m 'not e2e'`.

### B3. Tests for the helper

Fixture path-lists plus a stub `search`, exercising each mapping rule, the global
short-circuit, both breadth caps, `full_reason` discrimination, deletion/rename
handling, binary-path reporting, the unit/e2e split, and unmapped reporting.

## 5. Verification

### 5.1 Establish the baselines that do not yet exist

One measured run of **each selection** (`uv run pytest` and
`uv run pytest -m e2e`), producing the numbers §1 currently lacks. Additionally,
and independently of Part A, measure **`uv run pytest -n auto` on the unit
selection** — CI already runs it that way and local does not, making it a
zero-risk candidate for the unmeasured half of the hour.

**Execution mechanics**, because a long invocation has known failure modes here:

- launch **detached** and poll the PID — a backgrounded run can otherwise be
  reaped mid-flight and read as a fast finish;
- **clean up test databases between runs**, or the next dies with
  `DuplicateDatabase`;
- record per run: wall clock **per selection**, worker count, whether
  `TEST_DATABASE_URL` was set, the exit code, and **barrier-timeout and
  deadlock-retry counts** (see §5.4);
- a missing exit code is not a timing — a killed run must never be reported as a
  slow one.

### 5.2 The acceptance gate

**Gate on a fixed named subset, not the full suite.** The gate needs replication
(§2.4: a 21% baseline swing can move a single-run ratio from 1.2× to 1.8×,
making a single-timing gate partly a coin flip), and replicating full runs would
cost hours on a design whose whole purpose is to reclaim them. So:

- **Subject:** the 69-test sample named in §2, `-m e2e`.
- **Protocol:** **two before and two after**, *same commit, same machine*,
  **`-n 2` fixed**, toggling **only** `TEST_DATABASE_URL`. Part A is opt-in, so
  the comparison is an env-var toggle — never two commits, which admit
  confounders.
- **Decision:** gate on the **worst-case ratio** — slowest after ÷ fastest
  before.
- **The `-n` sweep of §5.4 happens after the gate is decided and never feeds
  it.** Otherwise the best `-n` could be reported as the "after" and inflate the
  ratio.

**Bar: worst-case ratio ≥ 1.4×**, derived rather than asserted:

> Sample means: before 3.08 s/test (212.8/69), after 1.93 s/test (133.0/69) —
> **1.60×** on truncate-paying tests. Over the full 845, roughly 171 tests
> (`math_reflow_dom`) pay no truncate and are unchanged. Assuming those cost
> ~0.4 s each (**unmeasured — the largest assumption here**), expected full-suite
> wall clock goes 674×3.08 + 171×0.4 = 2,144 s → 674×1.93 + 171×0.4 = 1,369 s,
> i.e. **≈1.57×**. Dilution is small because the cheap tests contribute little
> wall clock.

1.4× therefore sits a **~10% margin below the expected 1.57×** — a floor, not a
coin toss. If the 0.4 s assumption proves badly wrong, §5.1's real numbers
supersede this arithmetic and the bar is recomputed *before* the gate is run,
never after seeing the result.

### 5.3 Revert semantics, per deliverable

"Part A is reverted" is meaningless across five separable deliverables, so:

| On a missed bar | Outcome |
|---|---|
| **A1** compose file | removed |
| **A2** settings wiring | removed |
| **A5** adoption notice | removed (it would point at a deleted compose file) |
| **A3** docs | **retained**, with the container sections excised. Reverting it would either restore the `conventions.md` contradiction or orphan Part B |
| **A4** CI tmpfs | **judged only by §5.4's CI figure**, never by the local result; its own revert trigger is in §7 |
| **Part B** entirely | **retained** — it has no dependency on Part A |

A missed bar also returns the §6 shared-connection rewrite to scope.

### 5.4 Also required

- **The suite must stay green** on both selections. All 69 sample tests passed
  under every configuration measured; the full runs confirm that at scale.
- **Barrier timeouts and deadlock retries must both stay zero.** Finding 4 was
  taken under the old timing profile, and Part A changes every window that
  machinery was tuned against. §5.3-green is not sufficient evidence: a retried
  deadlock still reports green, so a regression in the very apparatus §6 refuses
  to touch would otherwise be invisible. A non-zero count is a finding.
- **Time `TRUNCATE` directly on the Windows Postgres**, closing the §2.1
  inference. **Both this and a re-run of the container timings must pin the
  database state** — a freshly migrated test database immediately after one e2e
  test's fixtures — since the original 2,881 ms / 78 ms figures did not record
  theirs, and an empty-table truncate is not comparable to a populated one.
- **Record the CI e2e job before/after** the tmpfs change.
- **Test the A2 settings wiring**, which nothing else covers even though it is
  the design's safety property. **Do not re-import `config.settings.test` the way
  `tests/test_settings_production.py` re-imports production.** That pattern is
  safe only because production is not the active settings module; `test.py`
  line 24 does
  `TEMPLATES[0]["DIRS"] = [*TEMPLATES[0]["DIRS"], BASE_DIR / "tests" / "templates"]`,
  and since `base` is not popped, `TEMPLATES[0]` is the same dict object
  `django.conf.settings` references — every re-import appends another copy to
  live global state. Instead extract a pure helper
  (`_resolve_databases(env_value)`) and test that directly. Mutant: make the
  helper ignore its empty-string case so the override applies unconditionally,
  and require red.
- **Re-measure `-n 4` and `-n 8`** on the e2e selection after Part A lands, and
  `-n auto` on the unit selection (§6).

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
only if §5.2's bar is missed.

**More xdist workers on the *e2e* selection: excluded for now, on weak and
perishable evidence.** `-n 8` (238 s) vs `-n 2` (212 s) sits inside the
212.8–258.0 s noise band, so it shows no gain rather than a loss. And the
mechanism that would explain a real loss — `TRUNCATE … CASCADE` taking
`AccessExclusiveLock` on 89 tables, serializing concurrent workers — is largely
removed by Part A. Hence the mandatory re-measurement in §5.4.

**This non-goal does not extend to the unit selection.** Its mechanism does not
apply to `db`-fixture rollback tests, no measurement was ever taken there, and
CI already runs that selection at `-n auto`. Measuring it is a §5.1 deliverable,
not a non-goal.

**`--no-migrations` and `--reuse-db`: rejected.** They target test-database
creation, ~20 s per run (§2.1) — not the bottleneck. `--reuse-db` is
additionally incompatible with a tmpfs server wiped whenever the container
restarts.

**Moving the runner to Linux is deferred**, not rejected. It is worth a further
~1.7× on top of Part A, but it needs root for Chromium's system libraries and so
cannot be automated unattended. Revisit once §5.1's real numbers exist.

## 7. Risks

| Risk | Mitigation |
|---|---|
| `fsync=off` applied to the real instance | Separate container, non-default port 55433, warning in `conventions.md` |
| Trust-auth superuser Postgres exposed to the local network | Bind `127.0.0.1:55433:5432`, never `0.0.0.0` (A1) |
| tmpfs too small | 1 GB against a measured 12 MB/database × 8 workers, set via the long `volumes:` form so the size is actually applied. Symptom is not an obvious "disk full": Postgres reports `could not extend file …: No space left on device`, or `PANIC: could not write to file`, mid-run |
| CI Postgres fails to start on tmpfs (PGDATA permissions/init) | Both jobs red immediately and visibly. Revert = drop the tmpfs line from `options:`; nothing else depends on it |
| Compose project name differs per worktree, yielding one container each | Fixed `-p libli-test` in every documented command (A1) |
| Two worktrees run against the shared container at once | One-run-at-a-time rule plus the per-worktree database-name option (B1); restarting the container kills any in-flight run |
| `affected_tests.py` misses an affected test | Advisory only; CI full suite remains the gate; global short-circuit, per-selection breadth caps, and explicit unmapped reporting keep gaps visible |
| Developers never adopt the opt-in database | Controller-only terminal notice when e2e is selected and `TEST_DATABASE_URL` is unset (A5) |
| Developer has no Docker Desktop | Listed as a prerequisite in `setup.md`; the unset fallback is a supported configuration |
| Developers forget to start it anyway | Unset falls back to today's behaviour — slower, never broken |
