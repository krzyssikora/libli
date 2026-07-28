# Builder tree performance probes

Two scripts measure the course builder's tree render before and after the
lazy-open-scope work in this project. Keep numbers from both scripts
comparable **only within the same script** — they measure different bases,
described below.

## Database

Both probes expect a dev database reachable via the project's `DATABASE_URL`
(see `.env`) that already contains the target course — default slug
`mat-pp`. Nothing here seeds that course; it must already exist. If it does
not, seed a synthetic equivalent of comparable size (~944 nodes) and record
in the PR that the baseline is synthetic, then use that slug everywhere
`mat-pp` appears below.

Verify it first:

```bash
uv run python manage.py shell -c "
from courses.models import Course
c = Course.objects.filter(slug='mat-pp').first()
print('mat-pp nodes:', c.nodes.count() if c else 'MISSING')"
```

## `probe_tree_render.py` — offline, server-side

Renders `courses/manage/_scope.html` directly (no HTTP, no browser) and times
it. This is the primary gate: it isolates template/query cost from browser
and network overhead.

```bash
SLUG=mat-pp OPEN=all uv run python manage.py shell -c \
  "exec(open('scripts/perf/probe_tree_render.py').read())"
```

`OPEN` controls which container scopes are treated as open:
- `all` (default) — every non-unit container is open, i.e. today's
  fully-expanded render.
- `` (empty string) — nothing open, i.e. the fully-collapsed render.
- a comma-separated pk list — only those containers (and, once the lazy-tree
  change lands, their descendants) are open.

Reports: warm render time (ms, after a warm-up render to prime template
caching), byte size of the rendered HTML, total open-tag count, `<li>` row
count, and SQL query count.

**Basis note:** this HTML has no CSRF hidden inputs and no browser-injected
markup — it is exactly what `render_to_string` returns.

## `probe_browser.py` — real page, real browser

Loads the actual builder page in headless Chromium via Playwright and reads
Navigation Timing + DOM counts. This is the "does it feel fast to a real
user" check, run occasionally, not as the primary gate.

Prerequisites (none automatic):

1. The dev database with the course, as above.
2. `uv run python manage.py runserver` listening on `127.0.0.1:8000`.
3. A session cookie for a user allowed to manage that course. Mint one with:

   ```bash
   MINT=1 uv run python manage.py shell -c \
     "exec(open('scripts/perf/probe_browser.py').read())"
   ```

   This prints `SESSION <key>`.

Then run the measurement as a plain script (not through `manage.py shell` —
it needs Playwright's sync API, which does not run inside the shell's
event loop):

```bash
SESSION=<key> uv run python scripts/perf/probe_browser.py
```

Reports (as JSON): total DOM element count, `.tree__row` count, elements per
row, TTFB, `domInteractive`, transfer size in KB, HTTP status, and wall-clock
time for `page.goto`.

**Basis note:** this HTML includes CSRF hidden inputs (one per form) and
whatever the browser itself adds to the DOM — its element/byte counts will
not match `probe_tree_render.py`'s for the same course and open-set. Compare
each probe's post-change numbers only against its own pre-change numbers,
never across the two scripts.
