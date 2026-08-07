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

**This failure is not fast.** Expect to wait about **4 minutes 20 seconds**
before the error appears — psycopg's default `connect_timeout` is 130s, and
Django attempts two databases in sequence (the `postgres` maintenance database,
then `libli`), so the timeout is paid twice. The eventual error is a
`django.db.utils.OperationalError` about a connection timeout. If the suite
seems to have hung right after starting, this is almost certainly why — let it
finish erroring out rather than assuming it is stuck, and start the container.

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
