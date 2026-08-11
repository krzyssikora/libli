# GeoGebra lookup follow-ups: bound the lookup, clear the stale pair

Two independent follow-ups from #238's review.

**Component A — bound the GeoGebra API lookup.** `fetch_geogebra_dimensions` runs inside
`save_element`'s `@transaction.atomic` while `_locked_unit` holds `select_for_update()` on the
`ContentNode` row. `urllib`'s `timeout=` bounds each individual socket operation, not the total
call — measured, a peer dribbling one byte per second held a single `read()` for **16.18s** against
a 3s timeout. The transport now runs on a named daemon thread joined for `_DEADLINE_SECONDS = 5`,
and the body read inside that thread is itself chunked (`read1(_CHUNK_BYTES)`) against the same
budget, so neither the main thread nor the worker can be parked indefinitely by a slow peer.
`read1` rather than `read` is load-bearing: `HTTPResponse.read(n)` loops over `recv` until it has
`n` bytes, so each `recv` returns inside the per-op timeout and the timeout never fires — measured,
`read(8192)` blocked 10.13s where `read1(8192)` returned in 0.05s.

**Component B — clear a stored `(width, height)` pair on any URL change.** `IframeElementForm.clean_url`
gated the stale-pair clear on the *new* URL being a GeoGebra material, so swapping a GeoGebra
element to a Vimeo or YouTube one kept the applet's 880x660 and rendered a 16:9 video in a 4:3 box
with no badge. One conjunct removed; the *lookup* guard keeps its `and mid`.

Signature and return contract of `fetch_geogebra_dimensions` are unchanged: `(int, int) | (None, None)`,
never raises. No migration, no `FORMAT_VERSION` bump.

## Change surface

- `courses/geogebra.py` — `_BudgetExceeded`, `_CHUNK_BYTES`, `_DEADLINE_SECONDS`, `from time import monotonic`,
  `import threading`, `_fetch_body`, threaded `fetch_geogebra_dimensions`, four comment rewrites
- `courses/element_forms.py` — one conjunct dropped at the stale-pair clear, two comment rewrites
- `docs/development/architecture.md:106` — one-line update. This introduces the repository's **only**
  production background thread, which is an architecture-level fact; the row is shared with
  `video_url.py`, so the thread is attributed to `geogebra.py` explicitly rather than appended to the
  shared cell.
- `tests/test_geogebra.py` — `_Resp` hoisted to module scope and given a read offset; 8 new tests
- `tests/test_iframe_dimensions.py` — 2 tests rewritten in place, 1 new

## Accepted gaps

These are recorded here deliberately — the design accepted each one, and several are the honest
caveats of the approach rather than oversights.

- **The lock is still held during the lookup**, now for up to `_DEADLINE_SECONDS` (5s). This PR bounds
  the hold; it does not remove it. De-locking the fetch — moving it outside `_locked_unit` — is the
  named follow-up PR and is explicitly **out of scope** here.

- **The orphan bound is conditional.** An abandoned worker is bounded at **~8s once response headers
  have arrived** (`_DEADLINE_SECONDS` plus at most one per-op timeout for the `recv` already in
  flight), holding one socket and one thread stack for that period. The per-op timeout alone would
  *not* bound it — a peer dribbling one byte per second never trips it, which is exactly what the
  16.18s measurement shows. The chunk budget, not the socket timeout, is what makes the orphan finite.

- **That bound does not cover the pre-header legs.** The budget is only checked after `_open` returns,
  so a peer that dribbles the TLS handshake or the response headers parks the orphan *inside* `_open`,
  bounded only by `http.client`'s `_MAXLINE`/`_MAXHEADERS`. The main thread is still released at
  `_DEADLINE_SECONDS`, so the row lock is unaffected; only the orphan is exposed, and only to an
  adversary controlling the response headers rather than merely the body rate.

- **Thread creation and thread abandonment are different rates.** One thread is *created* per lookup
  that reaches the network (a dimensionless GeoGebra save, suppressed 60s per material by the negative
  cache). A thread is only *abandoned* when the deadline actually fires. The common case leaves
  nothing parked.

- **No cap on concurrent lookup threads, deliberately.** The 60s suppression is per material and per
  process, so N authors pasting N distinct dimensionless materials produce N parked threads with no
  ceiling and no counter. A cap would add a queue whose wait would itself sit inside the row lock —
  the opposite of this PR's goal. The ceiling is "distinct dimensionless materials pasted within one
  orphan lifetime", and because the chunk budget caps that lifetime at ~8s it reduces to instantaneous
  editor concurrency rather than growing while the API misbehaves. Accepted, with the note that
  **nothing makes it observable**: there is no counter, and `thread.start()` failing surfaces only as
  `lookup failed (RuntimeError)` in the log.

- **A late-arriving body is discarded.** An abandoned thread that completes after the deadline cannot
  write to the cache — cache writes are main-thread-only by design — so its result is thrown away and
  the negative sentinel stands for the full 60s.

- **The negative cache is per-process.** There is no `CACHES` setting outside
  `config/settings/test.py:19`, so Django's default `LocMemCache` applies and the sentinel suppresses
  retries only in the worker that failed. Recorded as a note only: there is no deployment, so
  worker-count multiplication is hypothetical.

- **A deadline appears exactly once per material per 60s.** The cache-hit short-circuit returns
  `(None, None)` *without logging*, so an author who sees the badge and re-saves within the window
  produces no log line at all. The operator-visible symptom of the sticky suppression is therefore
  **silence, not repetition** — worth stating, because the justification for the whole trade rests on
  the deadline being diagnosable.

- **`daemon=True` and the `isinstance(bytes)` body guard are deliberately untested.** Every test in the
  suite is green with `daemon=False` — the bounded fakes all complete within seconds, so no test can
  distinguish them without asserting on the `Thread` object itself rather than on behaviour. The
  `isinstance` guard is unreachable by construction (`b"".join()` returns bytes or raises on the
  worker, landing in `box["exc"]`). Both are kept and annotated in place, matching the file's existing
  "a branch that cannot be driven cannot be falsified to RED" convention at the `_API_PREFIX` guard.

- **Component B reverses a decision #238 pinned as deliberate.** `tests/test_iframe_dimensions.py:498`
  carried the comment *"A KNOWN, ACCEPTED gap … pinned so a future change to it is deliberate"*. This
  is that deliberate change, not a fresh bug fix: #238 knowingly scoped the clear to GeoGebra, and
  this PR knowingly widens it. The pinning test is rewritten in place — name, body and comment — so
  the repository no longer asserts the old rule.

- **Component B's known cost.** A URL edit on a hand-pasted non-GeoGebra embed loses the captured pair.
  For non-GeoGebra providers there is no lookup and no badge (`size_unknown` requires
  `is_geogebra_iframe_url`), so a genuinely 4:3 archive video whose URL is edited silently drops to
  `.embed-frame`'s 16:9 with no signal — a badge-less wrong frame, the same *class* of outcome this PR
  fixes elsewhere. Recovery is weaker than "just re-paste": the edit textarea is prefilled with the
  stored canonical URL, not the author's original snippet, so they must go back to the provider for
  the embed code. The rule is still preferred because the competing failure is not symmetric — keeping
  the pair is wrong whenever the new URL has a different ratio, which after a provider swap is the
  common case; clearing is wrong only when the new URL happens to share the old one's non-default
  ratio *and* the author pasted a bare URL.

- **Finding 3 from the original review is dropped as unverified.** The claim was that
  `_dimensions_from_payload` should not read a top-level (`ws`-level) `settings` block. It does return
  one before scanning `elements`, but the fixture cited as evidence,
  `tests/fixtures/geogebra/ws_layout_settings.json`, carries `appName`/`scale` and **no** width/height
  — it pins the opposite of the claim. Meanwhile `tests/fixtures/geogebra/wseg.json` (`type: "wseg"`)
  carries width/height *only* at top level, so that read is load-bearing. Not actionable without a real
  captured payload.

- **Prior design docs are left as historical record.** #238's spec and plan document the
  GeoGebra-scoped clear and its accepted gap. They are **not** annotated or amended; this PR's spec
  supersedes them.

## Verification

- `tests/test_geogebra.py`: **112 passed** (104 at the branch point + 8 new). `tests/test_iframe_dimensions.py`:
  **54 passed** (B1 and B2 rewritten in place, so only B3 adds to the count). Branch-point
  selected-collection count recorded as **5974**.
- Every new test was falsified against a named mutant, applied and then edited back out by hand —
  17 mutants in total. Where one mutant reddens several tests, each test additionally has a mutant it
  alone kills: notably B2's provider-change mutant (the rejected alternative), which leaves B1 green
  and reddens only B2, and B3's, which reddens only B3 out of 54.
- Each falsification was checked to fail *for the stated reason*, not merely to fail: the wrong `_run`
  handler order logs `lookup failed (_BudgetExceeded)`, and a stored partial body logs
  `unparseable payload (JSONDecodeError)`.

- **Whole-branch gate green.** Full unit suite: `5983 passed, 912 deselected, 4097 warnings in
  2216.18s (0:36:56)` — zero failures, zero errors. Selected-collection count **5983** against a
  branch-point **5974**, i.e. **exactly +9**: 8 in `tests/test_geogebra.py` and 1 in
  `tests/test_iframe_dimensions.py`, with B1 and B2 rewritten in place and so not adding to the count.
  Both sides of that comparison are the left-hand (selected) figure, not a `passed` count — they
  differ by deselected e2e tests and runtime skips.
- `ruff check --no-cache .` → `All checks passed!`; `ruff format --check .` → `933 files already
  formatted`; `manage.py makemigrations --check --dry-run` → `No changes detected`.

## Deferred review finding

A `high`-effort review of this diff raised two low-severity items. The first — the module docstring
overclaiming that the chunk budget prevents an abandoned worker parking indefinitely, contradicting
the accepted gap above — is **fixed in this PR**. The second is deferred:

- **`_fetch_body`'s loop has no progress check.** It breaks on a falsy `chunk` and exits when `total`
  passes the cap, relying otherwise on the deadline for liveness. A `read1` returning a *truthy*
  object of length 0 therefore spins at 100% CPU for the full `_DEADLINE_SECONDS`, appending to
  `chunks`. Unreachable with a real `HTTPResponse` — but reachable from the test suite via the idiom
  already present at `tests/test_transfer_import.py:313` (`with patch("courses.geogebra._open") as
  opener:` with no `side_effect`): a bare `MagicMock` is truthy, and `len(MagicMock())` is `0`, so
  `total` never advances. That existing test is safe only because it asserts `opener.assert_not_called()`;
  the next test written the same way that *does* reach `_open` would burn 5s of CPU and unbounded mock
  memory rather than failing fast. Before this change the same mock failed immediately via
  `json.loads` → `TypeError` → `unparseable payload`.

  Deferred rather than patched because the fix (breaking on `len(chunk) == 0`, or asserting
  `isinstance(chunk, bytes)`) alters the loop's EOF semantics, and that loop shape was pinned verbatim
  through the spec review. It wants its own change with its own falsification, not a late edit here.
