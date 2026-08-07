# Running the tests

## The two selections

`pyproject.toml` pins `addopts = "-q -m 'not e2e'"`, so a "full run" is two
commands:

```bash
uv run pytest            # unit + integration selection
uv run pytest -m e2e     # browser e2e selection
```

(Deliberately uncounted: the suite grows with every feature, and any count
written here would drift immediately. `--collect-only -q` reports the current
numbers.)

`-m e2e` is mandatory for the second. Without it every e2e test is deselected and
pytest exits **5** — which means "nothing selected", not "green".

## Use the tuned test database

e2e teardown runs `TRUNCATE ... CASCADE` over 89 tables after each test that
takes `live_server` — **575 of the 845 collected e2e tests** (as of 2026-08). On
a normal Postgres that statement costs **2,881 ms**; on a server with
durability off and its data directory on a tmpfs it costs about **78.5 ms** —
roughly **37x** faster. Both measured against a populated database.

```bash
# start (once per session)
docker compose -p libli-test -f docker-compose.test.yml up -d --wait

# stop and wipe (the data is disposable by design)
docker compose -p libli-test -f docker-compose.test.yml down
```

Then uncomment `TEST_DATABASE_URL` in your `.env`. A shell export works too if
you would rather keep it per-command.

`docker-compose.test.yml` pins its own Compose project name via a top-level
`name: libli-test`, which outranks the directory-basename default (Compose
precedence: `-p` > `COMPOSE_PROJECT_NAME` > the file's `name:` key > directory
basename). So `-p libli-test` above is redundant — a forgotten `-p` still hits
the same project — but it is kept in the documented commands for explicitness.

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

It fails in about **12 seconds** with a
`django.db.utils.OperationalError` about a connection timeout.

That is deliberate. `TEST_DATABASE_URL` configs get `connect_timeout: 5`, because
psycopg's default is **130 s** and Django attempts two databases in sequence (the
`postgres` maintenance database, then `libli`) — so the timeout is paid twice and
the unmodified failure took **4 minutes 21 seconds** of complete silence.
Measured before and after: **261.71 s → 11.6 s**. A four-minute silent wait reads
as a hung suite rather than a stopped container, which is the wrong thing to
learn from the most common daily failure.

If you deliberately want a different timeout, put `?connect_timeout=N` in the
URL — an explicit value in `TEST_DATABASE_URL` is respected and not overridden.

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

Run the affected tests locally — `scripts/affected_tests.py` below works out
which those are — and let CI run the full suite. CI does both
selections plus lint in about **8m45s**, in three parallel jobs, and it does not
consume your session.

Do not run the full suite locally twice in one session. The exception is a
deliberate before/after benchmark, which is a measurement, not a gate.

## Which tests are affected

```bash
uv run python scripts/affected_tests.py            # vs origin/master
uv run python scripts/affected_tests.py --base HEAD~3
```

It prints one command per selection, or explicitly says a selection mapped
nothing. **It is advisory.** CI's full suite is the gate; the script only decides
what is worth running while iterating.

Read its output with three things in mind:

- **`unmapped` is the interesting part.** Anything listed there matched no rule
  — a binary asset, a new file type, something the tool does not understand.
  Judge those by hand rather than assuming they are safe.
- **A full run is a real answer — and it usually means "push".** Changing
  `conftest.py`, `config/settings/`, `config/urls.py`, `pyproject.toml` or a
  compiled `.mo` catalog can alter tests that never mention it, so the script
  stops mapping and tells you to run everything. Same when a selection exceeds
  its breadth cap: a list that long is no longer meaningfully narrower than the
  suite.

  This does **not** override the two rules above. A full-run answer normally
  means commit and let CI's 8m45s be the gate — that is what the branch gate is
  for. Run it locally only if you have not already spent your one full run this
  session, and only when you need the answer before pushing.
- **Exit code 5 means "nothing selected", not "green"** — for either command.
  Some files hold only e2e tests, so a unit command built from them is entirely
  deselected by the default `-m 'not e2e'`.

### Justify the selection before a slice

Before a multi-task slice, write down the files you will treat as the local gate
and why each one can be affected — the format is
`docs/superpowers/notes/2026-07-28-affected-tests-slice2.md`: a table of file,
baseline exit code, test count, and the reason the slice can touch it.

The point is the classification it lets you make later. Mark each file as either
encoding behaviour the slice **changes** — where a red is expected migration —
or behaviour it must **preserve**, where **a red is a REGRESSION, not
migration**. Without that written down first, every red mid-slice becomes an
argument with yourself about whether it was intended.

Baseline the selection green before you start. A red you cannot attribute to a
before-state is a red you will spend an hour on.
