# Faster CI via parallelism

## Purpose

CI is a single serial job whose wall-clock is the *sum* of lint, ~2,533 unit tests,
`migrate` + `setup_roles`, Playwright install, and ~186 e2e tests. A red build means
waiting the full serial run again. This change cuts wall-clock **without changing what is
tested**, using two independent, low-risk levers:

1. **Parallelize within a run** with `pytest-xdist` (multiple worker processes per job).
2. **Split the one serial job into three concurrent jobs** (`lint`, `unit`, `e2e`), so
   wall-clock becomes roughly `max(unit, e2e)` instead of their sum, and lint fails fast
   on its own.

Path-based skipping of test suites (e.g. skip e2e on backend-only diffs) is explicitly
**out of scope** for this change — it carries a wrong-green-build risk and is deferred
until the pure-speedup levers are proven.

## Architecture / components

Two artifacts change: the dev dependency set and the CI workflow.

### Dependency

- Add `pytest-xdist` to the existing `[dependency-groups] dev` group in `pyproject.toml`
  (alongside `pytest`), so the current bare `uv sync` installs it unchanged — a separate
  non-default group would leave `uv sync` without it and make `-n auto` fail with
  "unrecognized arguments: -n". Refresh the lockfile (`uv lock`). No production dependency
  changes.

### Workflow — from one job to three concurrent jobs

`.github/workflows/ci.yml` currently defines a single `test` job. It is replaced by three
jobs that GitHub Actions runs concurrently (no `needs:` edges between them):

Every job first runs the shared prelude the current workflow already uses —
`actions/checkout@v5` then `astral-sh/setup-uv@v6` with `python-version: "3.13"` and
`enable-cache: true` — before the steps below. Commands are shown logically; each retains
the current workflow's `uv run` (and `python -m` / `python manage.py`) invocation form and
would be `command not found` without it.

| Job    | Steps (after the shared checkout + setup-uv prelude)                                                          | Postgres service |
|--------|--------------------------------------------------------------------------------------------------------------|------------------|
| `lint` | `uv sync` → `uv run ruff check .` → `uv run ruff format --check .`                                            | no               |
| `unit` | `uv sync` → `uv run python -m pytest -n auto` → `uv run python manage.py migrate` → `… setup_roles`           | yes              |
| `e2e`  | `uv sync` → cache + `uv run playwright install --with-deps chromium` → `uv run python -m pytest -m e2e -n 2`  | yes              |

Design decisions baked in:

- **`migrate` + `setup_roles` stay in `unit`.** They verify the real deploy path against
  the real (non-test) database and are independent of the parallel test databases;
  folding them into `unit` avoids spinning up a fourth Postgres service. Removing them
  from the (previously serial) e2e path is a no-op: e2e tests run on per-worker
  `test_libli_*` databases created and seeded by fixtures, never on the `libli` database
  that `setup_roles` targets, so no e2e test depended on the pre-e2e seed.
- **Each DB-bound job carries its own Postgres `services` block and its own `env`
  block** (`DJANGO_SETTINGS_MODULE`, `DATABASE_URL`, `DJANGO_SECRET_KEY`). `lint` needs
  neither. The repeated `uv sync` is made cheap by `setup-uv`'s cache
  (`enable-cache: true`), retained on every job.
- **Playwright browser cache.** Add `actions/cache` for `~/.cache/ms-playwright`, keyed on
  the resolved Playwright version. `playwright` is pulled in transitively (via
  `pytest-playwright`) with no direct pin, so the key is derived in a step —
  `PLAYWRIGHT_VERSION=$(uv run playwright --version | awk '{print $2}')` exported to
  `$GITHUB_ENV`. That derivation step must run **before** the `actions/cache` step, or the
  key substitutes empty and never hits; the required order is `uv sync` → derive+export
  `PLAYWRIGHT_VERSION` → `actions/cache` → `playwright install`. (Keying on a hash of
  `uv.lock` instead sidesteps the ordering entirely and is the simpler option.) The cache
  elides only the browser-binary download; `playwright install --with-deps chromium` still
  runs its system-package (apt) step on every run, hit or miss. The `e2e` job is on the
  critical path, so even the binary-download saving shaves cold-start. Fail-safe: a
  wrong/stale/empty key just re-triggers the download — correct, only not faster.
- **Branch-protection required checks must be renamed (rollout, chicken-and-egg).** The
  current single job is named `test`. Splitting into `lint` + `unit` + `e2e` means any
  required status check named `test` never reports again — and the *introducing PR itself*
  cannot merge, because the new checks can't be marked required until GitHub has observed
  them report on a commit at least once. Sequence: an admin first drops `test` from the
  required checks (or admin-merges this PR), lets `lint`/`unit`/`e2e` report once, then adds
  those three as required. If `test` is not a required check today, none of this applies.
- **Per-worker DB creation needs CREATEDB.** Each xdist worker issues
  `CREATE DATABASE test_libli_gwN` concurrently, so the connecting role must hold the
  CREATEDB privilege. That role is `libli` (from the service's `POSTGRES_USER: libli`),
  which the `postgres:16` image provisions as a superuser — hence CREATEDB. Noted so a
  future hardened, non-superuser role doesn't silently break parallel runs.
- **No `needs:` gate between jobs (deliberate).** Unlike today's serial job — where e2e
  never starts if unit fails — concurrent jobs mean e2e runs even when unit is already red,
  spending some runner minutes on a doomed build. This is the accepted trade for full
  parallel signal on every run; omitting a `needs:` edge is intentional, not an oversight.
- **Per-job `timeout-minutes` (hardening).** With no `needs:` gate and a flakiness-prone
  browser suite, a hung `e2e` worker could otherwise burn the default 6-hour runner budget.
  Give each job a modest `timeout-minutes` (tightest on `e2e`) so a hang fails fast rather
  than idling paid minutes.
- **Concurrency block unchanged.** The existing top-level
  `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }` is preserved
  verbatim so superseded runs still cancel.
- **Trigger unchanged.** `on: { push: [master], pull_request: {} }` is preserved.

### Parallelism model

- **Unit: `pytest -n auto`.** `-n auto` uses the runner's available cores (currently ~4 on
  `ubuntu-latest`, though the count is not contractually pinned). `pytest-django` creates a
  distinct test database per worker (`…_gw0`, `_gw1`, …) automatically against the CI
  Postgres service; no test-code change is needed in the happy path. Unit inherits the
  `-m 'not e2e'` marker from `addopts` (`-q -m 'not e2e'` in `pyproject.toml`), so it still
  excludes the e2e suite; the e2e job's explicit command-line `-m e2e` intentionally
  overrides that default (last `-m` wins). Neither marker should be "tidied" out of
  `addopts`.
- **e2e: `pytest -m e2e -n 2`.** Two workers — a deliberate cap. Each worker gets its own
  browser instance and its own per-worker test DB. Two-way concurrency gives a meaningful
  speedup while limiting the browser-concurrency that most readily surfaces timing
  flakiness (this suite has needed de-flaking before).

## Data flow

A push or PR triggers the workflow. GitHub schedules `lint`, `unit`, and `e2e`
concurrently. Each job independently checks out, sets up `uv` (cached), and syncs deps.
`unit` and `e2e` each wait on their own Postgres service healthcheck, then run their
xdist-parallelized pytest invocation; `unit` additionally runs the migrate/seed deploy
checks; `e2e` restores/saves the Playwright browser cache around its install. The overall
run is green iff all three jobs are green. Wall-clock ≈ `max(lint, unit, e2e)` ≈
`max(unit, e2e)`.

## Error handling

- **Parallel-unsafe tests (the one real risk).** xdist runs tests in multiple processes
  and reorders them. Two failure modes can surface: (a) filesystem collisions when two
  workers write the same path (e.g. under `media/` or `transfer_staging/`), and (b) hidden
  inter-test ordering assumptions exposed by reordering. The remedy is **not** to abandon
  xdist but to isolate the offending tests — per-worker temp directories (e.g. keying a
  path on the `PYTEST_XDIST_WORKER` env var / `tmp_path`) or marking a genuinely
  order-dependent test to run serially. The plan's definition-of-done is the full suite
  green under `-n auto` (unit) and `-n 2` (e2e); any collision found during implementation
  is fixed under that DoD.
- **CI-config errors** (YAML shape, service healthcheck, cache key) surface as a red
  Actions run and are iterated on the branch.
- **Non-goal safety.** Because no suite is conditionally skipped, there is no path by which
  this change makes a build green that should have been red.

## Testing

This is primarily a CI-configuration change, so the authoritative signal is a **green
GitHub Actions run on the pipeline branch** exercising the new three-job workflow end to
end.

Supporting local verification, to the extent the local environment allows before the
branch is pushed:

- Run the unit suite under `pytest -n auto` to shake out parallel-unsafety (filesystem
  collisions, ordering assumptions) ahead of CI.
- Run the e2e suite under `pytest -m e2e -n 2` where a local browser + Postgres are
  available.
- Confirm `pyproject.toml` / lockfile resolve with `pytest-xdist` added (`uv sync`).
- Lint the workflow YAML for well-formedness.

The true definition-of-done remains the branch's CI going green with the new jobs.
