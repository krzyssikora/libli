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
| browser e2e | `uv run pytest -m e2e` | 845 | 97 | ~43–53 min (see §2) |

The unit half of the reported hour has **never been measured**, and this design
makes no claim about it. Most non-e2e tests take pytest-django's `db` fixture,
which rolls back rather than truncating, so Part A's benefit there may be near
zero. Measuring both selections is a required deliverable (§5.1), and the
headline benefit is stated only for the e2e selection until that lands.

## 2. What was measured

Unless stated otherwise, e2e timings use the **same 69 tests** —
`test_e2e_tabs.py`, `test_e2e_fillgate.py`, `test_e2e_guessnumber.py` — at
`-n 2`, at `828354c9`. All 69 passed in every configuration.

| Configuration | Sample (69 tests) | Full e2e (indicative only — see §2.3) |
|---|---|---|
| Windows + local Postgres (today) | 212.8 s / 258.0 s | ~43–53 min |
| Linux container + untuned Postgres | 273.8 s | — |
| Windows + tuned test Postgres | 136.8 s / 129.2 s | — |
| Linux container + tuned Postgres | 76.7 s | — |
| **CI today (all 845 e2e tests, `-n 2`)** | — | **7 min 47 s (measured, not extrapolated)** |

Whole CI pipeline, three parallel jobs: **8 min 45 s**, consistently green.

**"Windows + tuned test Postgres" means the Docker container defined in §3 A1,
reached from a native-Windows pytest over published port 55433** — i.e. exactly
the configuration Part A ships, including the Docker Desktop network hop. It was
not a native-Windows Postgres started with durability flags.

### 2.1 Findings that shaped the design

1. **Parallelism is exhausted *at today's truncate cost*.** The same 69 tests:
   `-n 2` = 212 s, `-n 8` = 238 s. See §6 for why this evidence does not survive
   Part A.
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

4. **The quiescence barrier is innocent.** That run recorded 0 barrier timeouts
   and 0 deadlock retries. `db_quiesce.py` is not the cost.
5. **Root cause: `TRUNCATE … CASCADE` across 89 tables**, run at teardown of
   every test taking `live_server` — **537 of 630 e2e test functions**. Timed
   directly as a single statement **on the container Postgres**:

   | Postgres configuration | `TRUNCATE` of all 89 tables |
   |---|---|
   | default durability | **2,881 ms** |
   | `fsync=off`, `synchronous_commit=off`, `full_page_writes=off`, tmpfs PGDATA | **78 ms** |

   **37× faster**, with no change to any test. The container's 5.90 s teardown
   mean is consistent with a 2.9 s truncate inside it. The Windows truncate was
   **not** timed in isolation; its 3.30 s teardown mean is consistent with a
   truncate of similar magnitude, but that is an inference, not a measurement.
   Timing it directly is a §5 deliverable.

**Denominators:** 845 is *collected e2e tests* (parametrized cases); 630 is
*e2e test functions* in source. The 537/630 ratio is over functions. All
per-test arithmetic in this document uses collected tests (845).

### 2.2 A hypothesis that was tested and rejected

The initial theory was that Windows was the root cause and that moving the
runner to Linux was the fix. That is **wrong**. An untuned Linux container was
the *slowest* configuration measured (273.8 s vs Windows' 212.8 s). The Linux
runner is genuinely faster at real test work (`call` 1.66 s vs 3.07 s; `setup`
0.83 s vs 1.42 s), but that advantage was swamped by a database durability
setting. The database is the lever; the operating system is a secondary
multiplier.

### 2.3 Why the extrapolation column is untrustworthy

CI runs an **untuned** Linux Postgres over the same 845 tests at the same `-n 2`
in **7 min 47 s** (0.55 s/test). The local untuned Linux container measured
3.97 s/test — **7.2× slower on nominally the same premise**. Two effects
compound, both pushing the same direction:

- **The sample is not representative.** All 69 sample tests take `live_server`
  and pay a truncate. The full 845 includes `test_e2e_math_reflow_dom.py` — 171
  tests, 20% of the selection — which uses no `live_server` and pays none.
  Per-test extrapolation from the sample therefore *overstates* full-suite time.
- **Local container I/O is not CI I/O.** Docker Desktop nests virtualization and
  its PGDATA sits on a virtual disk, where fsync is far more expensive than a
  GitHub runner's ephemeral NVMe. This is precisely why the durability flags buy
  so much locally and comparatively little on CI.

**Consequence:** the model predicts the *direction and mechanism* of the win,
not its magnitude. Every "full e2e" cell except the measured CI row has been
removed from the table for this reason. Only §5.1's measured before/after run
settles the size of the benefit, and Part A is gated on it (§5.2).

### 2.4 Other measurement caveats

- **Local Postgres has ~21% run-to-run variance** (212.8 s vs 258.0 s for
  identical work), so no single timing is load-bearing. The tuned configuration
  was replicated and is tight (136.8 s / 129.2 s).
- **Stated as a range, not a point.** Sample-level speedup spans
  **1.56× (212.8/136.8) to 2.00× (258.0/129.2)**, mean-over-mean ≈ **1.77×**.
  Quoting a single "1.8×" would silently pair the slow baseline with the fast
  tuned run.

## 3. Part A — Dedicated tuned test database

### A1. `docker-compose.test.yml` (new file, repo root)

One service, container name `libli-test-db`:

- image `postgres:16`
- ports: **`127.0.0.1:55433:5432`** — loopback-bound, *not* `0.0.0.0`
- `tmpfs: /var/lib/postgresql/data` sized **1 GB**
- command flags: `-c fsync=off -c synchronous_commit=off -c full_page_writes=off`
- env: `POSTGRES_USER=libli`, `POSTGRES_DB=libli`, `POSTGRES_HOST_AUTH_METHOD=trust`
- `healthcheck`: `pg_isready -U libli`, so `docker compose up -d --wait` returns
  only once the server accepts connections

Exact connection string, used verbatim in `.env.example` and the docs:

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli
```

Lifecycle commands, to appear in the docs:

```bash
docker compose -f docker-compose.test.yml up -d --wait   # start
docker compose -f docker-compose.test.yml down           # stop and wipe
```

Four properties matter, and each answers a specific hazard:

- **Non-default port 55433** — cannot be confused with the instance holding dev
  and mat-pp data.
- **Loopback binding** — a `trust`-auth superuser Postgres must not be reachable
  from the local network. Docker's default publishing binds `0.0.0.0`; this
  overrides that.
- **tmpfs, 1 GB** — a measured test database is **12 MB**; eight xdist workers
  need ~96 MB, plus WAL and template databases. 1 GB is ~10× headroom while
  keeping the VM RAM commitment modest. On Docker Desktop a tmpfs consumes VM
  memory, not disk.
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
  ruff's `F` rule set (selected in `pyproject.toml`) raises `F405`. Every
  existing star-imported name in that file — `STORAGES`, `TEMPLATES`,
  `BASE_DIR` — already carries the same suppression. Omitting it reds the CI
  `lint` job.
- **`env.db_url_config` rather than `base.py`'s `env.db(...)` idiom.** `env.db()`
  parses its `default`, so expressing "unset means no override" through it would
  require a sentinel URL that must itself be valid. Reading the raw string and
  parsing only the non-empty case keeps the unset branch a true no-op.
- **This lives in `test.py`, not `base.py`.** That placement is the safety
  property: no code path lets dev or production point at the throwaway server.

**Naming note for `.env.example` and the docs:** `TEST_DATABASE_URL` configures
the *server the test database is created on*. It is unrelated to Django's
`DATABASES['default']['TEST']` dict, which configures *the test database Django
creates*. One sentence must say so, because the names invite the opposite
reading.

### A3. Documentation

- **`.env.example`** gains the commented `TEST_DATABASE_URL` line above,
  verbatim, plus the naming note.
- **`docs/development/setup.md`** covers starting the service, the
  `--wait` flag's role, and points at the speed rationale.
- **`docs/development/conventions.md` §Testing is rewritten**, not merely
  appended to. It currently says "Run with `uv run pytest`", and its closing
  line makes that "part of the definition of done, alongside the ruff and pytest
  commands above". Left alone it would contradict the new `testing.md` outright.
  §Testing and that DoD sentence must both defer to `testing.md` as the single
  source of truth for what runs locally versus what CI gates. The `fsync=off`
  warning also lands here.
- **Root `README.md`** — its docs index table (the rows pointing at
  `setup.md`, `architecture.md`, `conventions.md`) gains a row for the new
  `testing.md`, so the file is discoverable.

### A4. CI: tmpfs only, and why

`.github/workflows/ci.yml` defines **two** Postgres services — one in the `unit`
job, one in the `e2e` job. **Both** gain `--tmpfs /var/lib/postgresql/data` in
their `options:`.

**CI gets tmpfs but not the durability flags.** GitHub Actions service
containers accept no `command:` key, so `-c fsync=off …` cannot be passed the
way A1 passes it. CI therefore captures only part of the measured 37×; the
remainder is unavailable without restructuring the job to run Postgres as a
plain `docker run` step.

No CI gain is claimed in advance. The e2e job is 7m47s today; the before/after
figure is recorded per §5.4. Because a `postgres:16` PGDATA on tmpfs is a known
permissions/init edge case, §7 carries the failure mode and its revert.

### A5. An adoption nudge

The entire win is gated behind a developer starting a container and setting an
env var, and §7 explicitly blesses not doing so. Without a prompt, the realistic
outcome is that the measured speedup is available and unused.

When **e2e tests are selected and `TEST_DATABASE_URL` is unset**, pytest emits a
one-line notice through the terminal reporter naming the compose command.

It must be a **terminal-reporter line, not a `warnings.warn`**. The project
already avoids polluting the warnings summary: node IDs printed there have
previously made an unanchored `grep FAILED` report failures on a green run.

## 4. Part B — Affected-tests workflow

### B1. Documented practice — `docs/development/testing.md` (new file)

- **Locally:** run only affected tests, with per-file justification in the
  format established by
  `docs/superpowers/notes/2026-07-28-affected-tests-slice2.md`, including its
  "a red here is a REGRESSION, not migration" classification.
- **Branch gate:** push and let CI's 8m45s be the full-suite gate.
- **Never run the full suite locally twice in one session** — with one named
  exception below.
- **Benchmarking is not a gate run.** A deliberate before/after measurement
  (§5.1) is exempt from the rule above. Without this carve-out the verification
  step would violate the practice it ships alongside.
- **One run at a time against the shared test server.** `libli-test-db` is a
  single container shared by every worktree, and xdist derives the same database
  names (`test_libli_gw0`…) in each. Two concurrent runs collide, and
  `docker compose down`/`restart` from one worktree destroys another's in-flight
  run. This is the existing `:5432` contention hazard, sharpened by a server
  people will feel free to restart.

### B2. `scripts/affected_tests.py`

Advisory, not authoritative.

**Interface — a pure core with a thin CLI wrapper**, so the tests in B3 and the
mutants in §5.3 have a seam to target:

```
map_paths(paths: list[str]) -> (unit_files, e2e_files, unmapped, global_hit)
```

The CLI resolves a diff range (default: merge-base with `master`), converts it
to a path list, and calls the core. **All git invocation lives in the wrapper**;
`map_paths` touches no subprocess, so fixtures are plain lists rather than
throwaway repositories.

**Diff consumption:** the wrapper reads `--name-status` output, **drops deleted
paths** (mapping a deleted test file to "itself" emits an unrunnable command
that errors at collection), and **follows renames to the new path**.

**Global blast-radius class, checked first and short-circuiting.** These paths
force a full-selection recommendation and bypass every per-module rule:

`tests/conftest.py`, `conftest.py`, `tests/factories.py`, `tests/db_quiesce.py`,
`tests/deadlock_retry.py`, `config/settings/*.py`, `pyproject.toml`,
`locale/**/*.po`

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
only** (no methods, no private names), word-boundary matched. Unbounded symbol
matching on common names (`Element`, `render`, `save`, `index`) would select a
large fraction of 549 files — a candidate set indistinguishable from the full
suite, and a silent failure.

**Breadth cap.** If the candidate set exceeds **40 files**, the script stops
listing and recommends the full selection instead. A near-full list presented as
a narrow one is worse than an honest "too broad".

**Unit/e2e classification.** A file is e2e iff its name matches `test_e2e_*.py`
**or** it contains an `e2e` marker; the two are checked, not assumed equivalent.
The emitted e2e command **always carries `-m e2e`**, and the output states that
**exit code 5 means "nothing selected", not "green"** — an e2e path landing in
the unit invocation is silently deselected by the existing
`addopts = "-m 'not e2e'"`, a trap already documented in the referenced notes
file.

The script **reports what it could not map**, so gaps stay visible. The human
still writes the justification; the script removes the tedium of finding
candidates.

### B3. Tests for the helper

Fixture path-lists exercising each mapping rule, the global short-circuit, the
breadth cap, deletion/rename handling, the unit/e2e split, and the
unmapped-reporting path.

## 5. Verification

### 5.1 Measured before/after

One measured run of **both selections** (`uv run pytest` and
`uv run pytest -m e2e`), before and after Part A, replacing every extrapolated
figure in §2. This closes the §1 gap that the unit selection has never been
timed.

**Execution mechanics**, because a ~50-minute invocation has known failure modes
here:

- launch **detached** and poll the PID — a backgrounded run can otherwise be
  reaped mid-flight and read as a fast finish;
- **clean up the test databases between the before and after runs**, or the next
  run dies with `DuplicateDatabase`;
- record: wall clock **per selection**, worker count, whether
  `TEST_DATABASE_URL` was set, and the exit code;
- a killed run must be distinguishable from a slow one — a missing exit code is
  not a timing.

### 5.2 Acceptance bar

Part A is **accepted only if the measured e2e selection improves by ≥1.4×**.
The sample-level range is 1.56×–2.00× (§2.4) and the full-suite figure is
expected to land below it (§2.3); 1.4× leaves room for that shrinkage while
still being worth the operational cost of a second database.

**If the measured gain is below 1.4×**, Part A is reverted and the design
revisited — the shared-connection rewrite excluded in §6 comes back into scope.
No claim is made about the unit selection; whatever it measures is recorded, not
graded.

### 5.3 The suite must stay green

All 69 sample tests passed under every configuration measured; the full run must
confirm that at scale, on both selections.

For `scripts/affected_tests.py`, per the project's "falsify tests, don't run
them" rule, **each mapping rule, the global short-circuit, and the breadth cap
get a named mutant** — delete the rule, require the corresponding test to go red.

### 5.4 Also required

- **Time `TRUNCATE` directly on the Windows Postgres**, closing the §2.1
  finding-5 inference with a measurement.
- **Record the CI e2e job before/after** the tmpfs change.
- **Test the A2 settings wiring**, which nothing else covers even though it is
  the safety property of the whole design: unset `TEST_DATABASE_URL` leaves
  `DATABASES` equal to base's `DATABASE_URL`-derived config; set produces the
  parsed override. `tests/test_settings_production.py` establishes the repo
  pattern for asserting on settings modules. Mutant: delete the `if _test_db:`
  guard so the override applies unconditionally, and require red.
- **Re-measure `-n 4` and `-n 8`** after Part A lands (see §6).

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
iterations against a real, measured deadlock — for the remainder. Re-enters
scope only if §5.2's bar is missed.

**More xdist workers: excluded *for now*, and the evidence is known to be
perishable.** `-n 8` measured slower than `-n 2` (§2.1), but `TRUNCATE …
CASCADE` takes `AccessExclusiveLock` on 89 tables, so eight workers truncating
concurrently serialize against each other. Part A removes ~97% of that cost, so
the parallelism ceiling plausibly moves. The measurement that justifies this
non-goal was taken under conditions Part A destroys — hence the mandatory
re-measurement in §5.4.

**`--no-migrations` and `--reuse-db`: rejected.** They target test-database
creation, measured at ~20 s per run (§2.1) — not the bottleneck. `--reuse-db` is
additionally incompatible with a tmpfs server that is wiped whenever the
container restarts.

**Moving the runner to Linux is deferred**, not rejected. It is worth a further
~1.7× on top of Part A, but it needs root for Chromium's system libraries and so
cannot be automated unattended. Revisit once §5.1's real numbers exist.

## 7. Risks

| Risk | Mitigation |
|---|---|
| `fsync=off` applied to the real instance | Separate container, non-default port 55433, warning in `conventions.md` |
| Trust-auth superuser Postgres exposed to the local network | Bind `127.0.0.1:55433:5432`, never `0.0.0.0` (A1) |
| tmpfs too small | 1 GB against a measured 12 MB/database × 8 workers. Symptom is not an obvious "disk full": Postgres reports `could not extend file …: No space left on device`, or `PANIC: could not write to file`, mid-run |
| CI Postgres fails to start on tmpfs (PGDATA permissions/init) | Both jobs red immediately and visibly. Revert = drop the `--tmpfs` line from `options:`; no other change depends on it |
| Two worktrees run against the shared container at once | One-run-at-a-time rule in `testing.md` (B1); restarting the container kills any in-flight run |
| `affected_tests.py` misses an affected test | Advisory only; CI full suite remains the gate; global short-circuit, breadth cap, and explicit unmapped reporting keep gaps visible |
| Developers never adopt the opt-in database | Terminal notice when e2e is selected and `TEST_DATABASE_URL` is unset (A5) |
| Developers forget to start it anyway | Unset falls back to today's behaviour — slower, never broken |
