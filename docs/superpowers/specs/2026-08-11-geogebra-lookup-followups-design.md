# GeoGebra lookup follow-ups: bound the in-lock network stall, clear stale dimensions on any URL change

## Purpose

PR #238 (GeoGebra share-link sizing, merged at `d5b20dbd`) left four findings recorded but
unverified — they came from a `code-review` that was aimed at a different branch and reviewed #238
by accident. All four have now been checked against `master` (`d197a4c7`). Two are real and are
fixed here; one is a note; one is dropped.

This spec covers the two verified defects. **De-locking the lookup is explicitly out of scope** and
is named as a follow-up PR (see "Out of scope").

### Defect 1 — a blocking outbound HTTP GET inside the unit row lock, unbounded

The lookup runs inside the editor's save transaction, while the unit's `ContentNode` row is locked,
and its timeout does not bound the call.

The chain, verified against `master`:

| Step | Location |
|---|---|
| `save_element` is `@transaction.atomic` | `courses/builder.py:1195` |
| `_locked_unit(...)` takes `select_for_update()` on the `ContentNode` row | `courses/builder.py:1204` → `:1579` |
| `_check_token(...)` runs **after** the lock | `courses/builder.py:1205` |
| generic dispatch `FORM_FOR_TYPE[type_key](...).is_valid()` | `courses/builder.py:1548-1551` |
| `IframeElementForm.clean_url` calls `fetch_geogebra_dimensions(mid)` | `courses/element_forms.py:218` |

Because the row lock is taken at `:1204` and the token is only checked at `:1205`, the `unit_token`
409 cannot shed this load — the lock is already held before validation begins. Every other editor
request touching that unit queues behind it.

**Measured.** `urllib`'s `timeout=` bounds each socket operation, not the total call. Replicating the
exact transport shape (`build_opener(_NoRedirect).open(request, timeout=3)` then
`read(_MAX_BODY_BYTES + 1)`) against a peer dribbling one body byte per second produced:

```
timeout=3s; peer dribbles 16 bytes at 1.0s each
RESULT: read b'{"x":1234567890}' in 16.18s
VERDICT: PER-OP (timeout does NOT bound the call)
```

The module's own comment at `courses/geogebra.py:46-53` already concedes this; nothing enforces it.
`ATOMIC_REQUESTS` is unset, so the lock is held for `save_element`'s duration rather than the whole
request — narrower than the original finding implied, still unbounded.

### Defect 2 — stale dimensions survive a provider change

`courses/element_forms.py:196` clears a stored `(width, height)` pair only when the **new** URL is a
GeoGebra material:

```python
if url_changed and not usable_dimensions(width, height) and mid:
```

`mid` is `geogebra_material_id(url)` for the new URL, so replacing a GeoGebra URL with a Vimeo or
YouTube one leaves the GeoGebra applet's pair in place.

**Measured** by binding the real form to an unsaved instance holding `(880, 660)` and a GeoGebra URL:

| New URL | stored pair | `frame_ratio` | `size_unknown` |
|---|---|---|---|
| `player.vimeo.com/video/76979871` | `(880, 660)` | `'880 / 660'` | `False` |
| `www.youtube.com/embed/dQw4w9WgXcQ` | `(880, 660)` | `'880 / 660'` | `False` |
| another GeoGebra material (control) | `(None, None)` | `'800 / 600'` | `True` |

`frame_ratio` step 2 (`courses/models.py:865-867`) is documented as "the branch every non-GeoGebra
provider reaches", so a 16:9 video renders in a 4:3 box, badge-less — the same pillarbox defect #238
existed to remove, entered through a different door.

## Architecture

Two independent changes. **No migration, no `FORMAT_VERSION` bump** — `width`/`height` already exist
on `IframeElement`.

| Component | File | Change |
|---|---|---|
| A — total deadline | `courses/geogebra.py` | extract `_fetch_body`, run it on a daemon thread bounded by a new `_DEADLINE_SECONDS`; rewrite the now-false `_TIMEOUT_SECONDS` comment at `:46-53` |
| B — stale-pair clear | `courses/element_forms.py` | drop the `and mid` conjunct **on the clear guard at `:196` only**; rewrite two comments |

`clean_url` carries `and mid` **twice**: at `:196` (the stale-pair clear) and at `:217` (the lookup
guard). Only the first is removed. Dropping the second instead would issue a live GET to
`https://api.geogebra.org/v1.0/materials/?scope=basic` with an empty id on every dimensionless
non-GeoGebra paste — precisely what `test_form_non_geogebra_dimensionless_paste_never_looks_up`
(`tests/test_iframe_dimensions.py:376`) exists to catch.

### Component A — a total deadline around the lookup

Extract the two network-touching lines into a private helper:

```python
def _fetch_body(request):
    with _open(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read(_MAX_BODY_BYTES + 1)  # +1 so oversize is detectable
```

`fetch_geogebra_dimensions` runs `_fetch_body` on a plain `threading.Thread(daemon=True)` — named
`f"geogebra-lookup-{material_id}"`, so a thread dump shows how many lookups are parked — with a
**function-local** result box created per invocation, then `join(_DEADLINE_SECONDS)`.

**The box is discriminated by key presence, never by truthiness.** A dict with at most one of
`box["body"]` / `box["exc"]` set. This is load-bearing: a legitimate `read()` returning `b""` is
falsy, and a truthiness check would route a real empty response to the deadline branch instead of
today's unparseable-payload failure, silently changing the logged reason.

**The outcome is decided by inspecting the box, never by `is_alive()`.** `join(timeout)` can return
while the thread has stored its result but not yet finished unwinding, so an `is_alive()`-first
implementation would discard a good body as a timeout. After the join, in this order:

1. **`box["exc"]` set** → **re-raise on the main thread**, so the existing
   `except urllib.error.HTTPError` and bare-`except Exception` handlers run exactly as today,
   including `exc.close()`.
2. **`box["body"]` set** → the existing parse path runs unchanged.
3. **Neither set** → `_fail("deadline exceeded")`. This is the residual case, so it also covers the
   pathological "thread finished having set neither slot" (e.g. a `BaseException` the wrapper's
   `except Exception` does not catch). Falling through with `body = None` would reach `len(body)`,
   raise `TypeError` into `clean_url` and break the never-raises contract — so the fallback must be
   `_fail`, never a fall-through.

`_DEADLINE_SECONDS` is read from the module global **at call time**, mirroring the existing
`GEOGEBRA_API_LOOKUP` rule ("Read the flag on EVERY call — capturing it at import would make every
`override_settings` a silent no-op"). Binding it as a default argument or capturing it in a closure
at import would make every test patch a silent no-op.

The thread target catches broadly and **never propagates**. Precisely: **once the box has been read**,
nothing the thread does can affect the caller or any later call. A store landing in the narrow
join→read window *is* observed — `join(timeout)` expiring creates no happens-before edge — and that
is deliberately allowed, because every such outcome (a good body, an `HTTP 400`, a transport error)
is at least as informative as the deadline report it replaces. A body arriving after the read is
discarded.

**The wrapper closes an `HTTPError`'s `fp` when it stores it.** #238 added the explicit `exc.close()`
because a 4xx/5xx raises from inside `_open`, so the `with` is never entered and the error's `fp` is
never closed. After the deadline, nobody reads that box — so without a close in the wrapper an
abandoned thread leaks the socket and emits a `ResourceWarning` from a non-main thread. The
main-thread handler's own `exc.close()` stays and is harmless when already closed.

Ruff's `select` is `["E","F","I","UP","B","S"]`; `BLE` is not selected, so the wrapper's broad
`except Exception` needs no `noqa`.

**This is the repository's first production background thread** — `threading` appears nowhere outside
`tests/`. The boundary rule that keeps it safe: the worker does **no ORM, no cache, and no logging**;
it only calls `_open`, reads bytes, and stores into the box. Nothing crosses a database connection,
so Django's per-thread connection handling and `close_old_connections` are not implicated. Worker-model
interactions remain hypothetical because there is no deployment.

**Only `_open` and `read` move to the thread.** The `GEOGEBRA_API_LOOKUP` check, both cache reads and
the cache write, and all logging stay on the main thread. This is load-bearing three times over: it
keeps `_open` the universal patch seam every existing test relies on, it keeps `caplog` able to see
the warnings, and it prevents an abandoned thread from racing the negative-cache write.

**The existing `try` structure is preserved exactly.** The `urllib.request.Request(...)` construction,
the thread start, the join, and the box inspection all stay **inside** the current
`try` / `except urllib.error.HTTPError` / `except Exception` block. Moving the `Request` construction
out of the `try` — a natural misreading of "build the request, then hand it to the thread" — would let
a construction-time raise escape into `clean_url` and 500 the save. The load-bearing `# noqa: S310`
comment travels with the construction if it moves at all.

**Constants.** `_TIMEOUT_SECONDS = 3` is unchanged and remains the *per-socket-operation* timeout.
`_DEADLINE_SECONDS = 5` is new and is the *total* bound. It is deliberately larger than a **single**
socket operation, so a failure in the *first* operation still surfaces as itself — the existing
blackhole/connect path times out at ~3.29s and must keep doing so rather than racing the deadline.

**Accepted, and stated rather than glossed:** this does **not** hold for a failure in a *later* leg.
A peer that connects in 2.9s and then stalls hits its own read timeout at ~5.9s, past the 5s
deadline, so it is reported as `deadline exceeded` rather than `lookup failed (timeout)`. Only the
logged reason differs — the return value, the badge, and the negative-cache write are identical — so
the 5s bound on lock-hold time is preferred over a 7s value that would preserve the label at the cost
of a 40% worse worst case.

**Three comments in `geogebra.py` become false and must be rewritten with the code** — the same
false-mechanism standard Component B is held to:

1. **`:46-53`, the `_TIMEOUT_SECONDS` comment.** It states that a slow-drip peer can hold the lock
   "well past 3s" and that this is **"Accepted"** — the very claim this change refutes, and the
   comment this spec cites as evidence for the defect. New text: per-op still 3s, total now bounded
   by `_DEADLINE_SECONDS`, no longer accepted. The new constant needs its own comment explaining why
   it exceeds the per-op timeout.
2. **`:376-378`, the `except urllib.error.HTTPError` comment.** It reads *"A 4xx/5xx raises from
   INSIDE `_open`, so the `with` above is never entered…"* — but after the change there is no `with`
   *above*; it moved into `_fetch_body` on the worker. New text: `_open` raises on the worker, the
   wrapper stores the error in `box["exc"]`, the main thread re-raises it here, and the explicit
   `exc.close()` is still required because the `with` inside `_fetch_body` was never entered.
3. **`:332-338`, `fetch_geogebra_dimensions`'s docstring.** It explains the never-raises contract as
   *"a bare `except Exception` … urlopen can raise RemoteDisconnected, ConnectionResetError,
   ssl.SSLError, UnicodeDecodeError and ValueError"*. None of those raise on this frame any more —
   they raise on the worker, cross back through the box, and are re-raised here. The contract still
   holds; the stated mechanism does not. New text must say so, and add that a deadline with neither
   slot set degrades via `_fail` rather than raising.

### Component B — the stale-pair clear

```python
if url_changed and not usable_dimensions(width, height):   # was: ... and mid
    self.instance.width = self.instance.height = None
```

The invariant being stated is **a stored pair belongs to the URL it was captured from**.

Two comments must be rewritten with the code, or they become false mechanism:

- the justification block above `:196`, which argues for the GeoGebra scoping being removed;
- the `mid` hoist comment at `:189` ("hoisted: both guards below use it") — after this change only
  the lookup guard uses `mid`.

## Data flow

**Save path (unchanged in shape).** `views_manage.py:2250` → `builder.save_element` (atomic) →
`_locked_unit` (row lock) → `_check_token` → `FORM_FOR_TYPE["iframe"](...).is_valid()` →
`IframeElementForm.clean_url` → optional `fetch_geogebra_dimensions`.

**`clean_url`, after the change**, for a URL edit whose paste carries no usable dimensions:

1. `url_changed` is true → the pair is cleared unconditionally.
2. `stored_usable` is therefore `False`.
3. If the new URL is a GeoGebra material (`mid` truthy) → the lookup fires, exactly as today.
4. If it is not (`mid == ""`) → no lookup; `width`/`height` stay `None`.
5. At render, `frame_ratio` reaches step 4 and returns `None` → `.embed-frame`'s 16:9 CSS default.

**Interactions that must be preserved:**

- A **title-only** edit has `url_changed == False`, so it neither clears nor fires a network call.
  The documented INVARIANT at `element_forms.py:199-207` is untouched.
- A paste that **carries its own** `width`/`height` has `usable_dimensions(width, height) == True`,
  so nothing is cleared and `:220` assigns the new pair. A known size is never discarded.
- A **fresh create** has `self.instance.url == ""`, so `url_changed` is true and the clear is a no-op
  on already-`None` fields.
- **GeoGebra → GeoGebra** still clears and then re-looks-up, as today.

**Fetch path, after the change.** Flag check → cache read → build `Request` → *[thread]* `_open` +
`read` → join with deadline → parse → cache write on failure. Only the bracketed step is off the
main thread.

## Error handling

| Condition | Behaviour |
|---|---|
| Deadline reached with the thread still running | `_fail("deadline exceeded")` → logs a warning naming the material id, writes the 60s negative-cache sentinel, returns `(None, None)` |
| Thread raised `HTTPError` | re-raised on the main thread → existing handler closes `exc.fp` and calls `_fail(f"HTTP {exc.code}")` |
| Thread raised anything else | re-raised → existing bare-`except` → `_fail(f"lookup failed ({type})")` |
| Oversize body | unchanged — the single `read(_MAX_BODY_BYTES + 1)` still makes it detectable |
| Kill switch off | unchanged — returns before any thread is created, no cache read, no cache write |

`fetch_geogebra_dimensions` keeps its never-raises contract: nothing new can escape into `clean_url`
and 500 the save. A GeoGebra element whose lookup fails shows the existing "size unknown" badge.

**Negative-caching a deadline is deliberate, and it is stickier than the other failure modes.**
Unlike an HTTP 400 or an unparseable body, a deadline usually means the API is merely *slow*, and the
abandoned thread may well complete successfully a moment later — that late body is discarded, because
cache writes are main-thread-only by design. So for up to 60s the sentinel suppresses exactly the
retry the badge invites, including during a window in which the API has already recovered.

That is the intended trade: the alternative is that every save of that element pays another 5s stall
**inside the row lock**, which is the cost this change exists to bound. Protecting the lock beats
re-probing a slow API promptly. The 60s TTL is unchanged; the discarded-late-body behaviour is
recorded in the accepted gaps.

## Testing

Every test names the mutant that must turn it RED, per the project's falsify-don't-run rule.

### `tests/test_geogebra.py` — the deadline (four NEW tests)

**All four MUST carry `@override_settings(GEOGEBRA_API_LOOKUP=True)`,** as every existing fetch test
in the file does. `config/settings/test.py:30` sets the flag `False`, and the kill switch returns
`(None, None)` before any thread is created — byte-identical to what tests 1 and 2 assert. A test
missing the decorator is green on the fixed build *and* on its own mutant: an assertion that cannot
fail.

**Blocking fakes must be bounded.** There is no `pytest-timeout` in the project and
`pyproject.toml:49` sets `addopts = "-q -m 'not e2e'"`, so a fake that blocks forever makes the
*mutant* run hang rather than fail — indistinguishable from this project's known "test-DB container
is down, suite looks hung for 4m21s" mode. Every fake therefore blocks on `Event.wait(<a few
seconds>)`, never unbounded, so the mutant build produces an observable bounded FAIL. Each test also
sets its event in teardown so no thread stays parked for the rest of the worker's session.

**Every blocking fake MUST return a successful, dimension-bearing result once its wait elapses.**
This is the difference between a real test and a vacuous one. If a fake waits and then returns `b""`
(or `None`, or falls off the end), then on the *mutant* build the call simply completes with an
empty/unparseable body and `fetch_geogebra_dimensions` returns `(None, None)` anyway — the same value
the test asserts, so it is green on the fix **and** on its mutant. Test 1's `read` therefore returns
a real payload (`_payload("wseg.json")`, so the mutant yields `(880, 660)`), and test 2's `_open`
returns a working response over the same payload. The only route to `(None, None)` must be the
deadline firing.

**The fakes must be context managers.** `_patch_open`'s docstring
(`tests/test_geogebra.py:267-269`) records that the double *must* support `__enter__`/`__exit__`
because the fetch uses `with _open(...) as resp:` — and that `with` survives inside `_fetch_body`. A
hand-rolled fake returning a bare object fails with an `AttributeError`, which the wrapper reports as
`lookup failed (AttributeError)`: a misleading `(None, None)` that looks like a pass. The new fakes
reuse or mirror `_patch_open._Resp`'s shape, and **test 4's log assertion is what catches this
mistake**, because the logged reason would read `lookup failed` rather than `deadline exceeded`.

**All four tests patch `_DEADLINE_SECONDS` via `monkeypatch.setattr`** — which also exercises the
read-at-call-time rule above. Pin the margin: a deadline on the order of **0.1s** against a fake wait
on the order of **2-3s**, i.e. wait ≫ deadline by more than an order of magnitude. Leaving the real
5s in place would cost 5s of wall clock per test, and too tight a margin makes test 2's mutant
("wrap only the read") flaky, because the mutant's post-`_open` read can itself miss the join window
and turn the mutant green.

1. **Slow body → `(None, None)`.** The fake `read` blocks on a bounded `Event.wait(...)` the test
   never sets, with `_DEADLINE_SECONDS` patched small. Assert the **result**, never elapsed
   wall-clock — no timing assertion, so no flake. *Mutant:* restore the direct `_fetch_body(request)`
   call.
2. **Slow headers → `(None, None)`,** by patching `_open` itself to block on its own bounded event,
   released in teardown exactly as in test 1. Pins that the bound wraps `_open` and not merely the
   read. *Mutant:* wrap only the read.
3. **A deadline negative-caches.** Second call short-circuits; `_open` called once.
   *Mutant:* bare `return (None, None)` without `_fail`.
4. **The deadline logs and names the material id,** matching every other logged failure mode in the
   module. *Mutant:* drop the log line.

### The constant relationship — one assertion, not a behaviour test

Every test above patches `_DEADLINE_SECONDS` to a small value, so **nothing in the suite ever
observes the shipped relationship** between the two constants. A future edit setting
`_DEADLINE_SECONDS = 2` would silently invert the design argued under "Constants" — the connect-leg
failure would start reporting `deadline exceeded` — and every test would stay green. Add a one-line
assertion that `_DEADLINE_SECONDS > _TIMEOUT_SECONDS`, in the same spirit as the existing
`test_fetch_sends_the_explicit_user_agent_and_the_configured_timeout`. *Mutant:* swap the two
constants' values.

### `tests/test_geogebra.py` — existing fetch tests as Component A's real gate

Component A rewires **every** fetch path through a worker thread and a re-raise, so the existing
fetch tests — not the four new ones — are what pin that behaviour is preserved end to end. They must
stay green unchanged, and each now proves something specific about the threaded path:

| Existing test | What it now proves about the threaded path |
|---|---|
| `test_fetch_degrades_on_http_error_and_logs_it` (`:340`) | `HTTPError` crosses the box and re-raises with fidelity; the `400` in the message pins `exc.close()` and the exc-slot ordering |
| `test_fetch_degrades_on_any_transport_exception` (`:360`) | three non-`URLError` types survive the box round-trip |
| `test_fetch_degrades_on_unparseable_body` (`:366`) | a body returned through the box still reaches the parse path |
| `test_fetch_treats_an_oversized_body_as_a_distinct_failure` (`:398`) | oversize detection still works on the boxed body |
| `test_fetch_negative_caches_a_failure_for_the_same_id` (`:427`) | the cache write stays on the main thread and still fires |
| `test_fetch_kill_switch_makes_no_request_and_writes_no_sentinel` (`:449`) | the flag short-circuits **before any thread is created** |

### `tests/test_iframe_dimensions.py` — the stale pair (two REWRITTEN tests)

These are not additions. Both already exist and currently assert the **exact opposite**, so they are
rewritten in place — name, body and comment:

5. **`test_form_geogebra_to_non_geogebra_url_change_keeps_the_geogebra_pair` (`:498`)** → GeoGebra →
   Vimeo now **clears**; `frame_ratio is None`, `size_unknown` is `False`. Its comment currently
   reads *"A KNOWN, ACCEPTED gap … pinned so a future change to it is deliberate"* — this change is
   that deliberate future change, and the comment must be replaced with the new invariant, not
   merely deleted. Rename to
   **`test_form_geogebra_to_non_geogebra_url_change_clears_the_stale_pair`**.
   *Mutant:* restore `and mid`. This is the defect itself.
6. **`test_form_non_geogebra_url_change_keeps_its_dimensions` (`:481`)** → a same-provider swap
   (Vimeo A → Vimeo B) now **clears**. Its comment currently states the provider-neutral-clear
   objection verbatim and must be replaced. Rename to
   **`test_form_same_provider_url_change_clears_the_stale_pair`**.
   *Mutant:* a provider-change rule — this is the test that distinguishes the chosen rule from the
   rejected provider-change alternative.

Explicit names are given because the current ones assert the literal inverse ("keeps"); a free-hand
rename risks leaving a stale name on an inverted test.

**Both rewritten tests MUST retain their existing `lookup.assert_not_called()`** (`:494` and
`:510`). That assertion is the *second* guard on which `and mid` survives: it is what distinguishes
"dropped the `:196` conjunct" from "dropped both conjuncts". Without it, neither test would notice a
build that also removed the `:217` lookup guard and started issuing empty-id GETs.

### Existing tests — regression coverage that must stay green

The earlier claim that this change touches no existing test was **wrong**; tests 5 and 6 above are
existing tests being inverted. Beyond those two, the following already cover behaviour this change
must preserve, and are deliberately **not** duplicated by new tests:

| Behaviour | Existing test |
|---|---|
| Title-only edit never looks up | `test_form_title_only_edit_of_a_sized_element_never_looks_up` (`:410`) |
| A plain URL edit preserves existing dimensions | `test_form_plain_url_edit_preserves_existing_dimensions` (`:293`) |
| A re-paste overwrites dimensions | `test_form_re_paste_overwrites_dimensions` (`:304`) |
| GeoGebra → GeoGebra clears and re-looks-up | `test_form_url_change_clears_the_stale_pair_and_looks_up_afresh` (`:425`) |
| A failed lookup does not keep the old pair | `test_form_url_change_with_a_failed_lookup_does_not_keep_the_old_pair` (`:437`) |
| A dimensionless non-GeoGebra paste never looks up | `test_form_non_geogebra_dimensionless_paste_never_looks_up` (`:376`) |

That last one guards the `:217` lookup guard, whose comment ("THE guard on the `and mid` conjunct")
becomes ambiguous once the `:196` conjunct is gone — it must be re-worded to name *which* guard.

`test_fetch_sends_the_explicit_user_agent_and_the_configured_timeout` also stays green unchanged: it
pins `opener.call_args.kwargs["timeout"] == _TIMEOUT_SECONDS`, still true because the per-op timeout
is unchanged and `_open` is still called with it.

### Run scope

Narrow: `tests/test_geogebra.py` and `tests/test_iframe_dimensions.py`, with a whole-branch gate
before the PR. **Start the test-DB container first.** No e2e — neither change has a UI surface beyond
what #238's e2e already covers.

## Out of scope

**De-locking the lookup** — moving the fetch outside `save_element`'s transaction so a slow API
stalls only the author who pasted, never the unit's other editors. That is the complete fix for
defect 1; this PR only bounds the stall. It needs its own design (pre-resolve before the lock, versus
defer via `transaction.on_commit`) and its own PR, because it changes the control flow of the most
concurrency-sensitive function in `builder.py`.

## Rejected alternatives

- **A chunked-read budget** so an abandoned thread self-terminates. `tests/test_geogebra.py:273-274`'s
  `_patch_open._Resp.read` is **stateless** — it returns `body[:n]` from the start on every call — so
  a loop of small reads would re-read the same first chunk forever. Adding the budget therefore means
  rewriting the shared double used by ~15 fetch tests, to buy a bounded, theoretical improvement in
  orphan lifetime. The 60s negative cache already suppresses repeat attempts per material.
- **`ThreadPoolExecutor`.** Its context-manager form calls `shutdown(wait=True)` and would block on
  the very thread being abandoned, defeating the deadline; its workers are also non-daemon, so
  interpreter exit joins them.
- **A socket-level absolute deadline** (shrinking the per-op timeout as the budget burns). Correct and
  thread-free, but requires a custom handler reaching into `urllib` connection internals.
- **Clearing the pair only when the provider changes.** It under-fixes: `player.vimeo.com/video/111`
  → `/video/222` is the same staleness class, and the provider rule would preserve video 111's
  dimensions. It also costs a host-equality helper that the chosen rule does not need.
- **Gating `_dimensions_from_payload` on `payload.get("type") != "ws"`** (finding 3). Dropped — see
  below.

## Accepted gaps, to be recorded in the PR body

- The lock is **still held** during the lookup, now for up to 5s. De-locking is the named follow-up.
- An abandoned thread holds one socket until its single `read()` completes or its per-op timeout
  fires — one thread per dimensionless GeoGebra save, suppressed 60s per material by the negative
  cache.
- **The negative cache is per-process.** There is no `CACHES` setting outside
  `config/settings/test.py:19`, so Django's default `LocMemCache` applies and the sentinel suppresses
  retries only in the worker that failed. Recorded as a note: there is no deployment, so
  worker-count multiplication is hypothetical.
- **Finding 3 is dropped as unverified.** `_dimensions_from_payload` (`courses/geogebra.py:294`) does
  return a top-level `settings` block before scanning `elements`, but the fixture cited as evidence,
  `tests/fixtures/geogebra/ws_layout_settings.json`, carries `appName`/`scale` and **no**
  width/height — it pins the opposite of the claim. Meanwhile `tests/fixtures/geogebra/wseg.json`
  (`type: "wseg"`) carries width/height **only** at top level, so that read is load-bearing. No
  observed payload has a ws-level width/height, and a worksheet declaring its own size is arguably
  the right size for a worksheet-wide iframe. Not actionable without a real captured payload.
- **A late-arriving body is discarded.** An abandoned thread that completes after the deadline cannot
  write to the cache (main-thread-only by design), so its result is thrown away and the negative
  sentinel stands for the full 60s. See "Error handling" for why that trade is chosen.
- **No cap on concurrent lookup threads, deliberately.** The 60s suppression is per *material* and
  per *process*, so N authors pasting N distinct dimensionless materials produce N parked threads
  with no ceiling and no counter. Accepted as bounded in practice by editor concurrency; a cap would
  add a queue whose wait would itself be inside the row lock, which is the opposite of the goal.
- **Prior design docs are left as historical record.** `docs/superpowers/specs/2026-08-10-geogebra-share-link-sizing-design.md`
  and its plan document the GeoGebra-scoped clear and its accepted gap. They are not annotated or
  amended; this spec supersedes them.
- **The chosen rule's known cost, stated in full.** A URL edit on a hand-pasted non-GeoGebra embed
  loses the captured pair. For non-GeoGebra providers there is no lookup and no badge
  (`size_unknown` requires `is_geogebra_iframe_url`), so a genuinely 4:3 archive video whose URL is
  edited silently drops to `.embed-frame`'s 16:9 with no signal — a badge-less wrong frame, the same
  *class* of outcome this spec is fixing. Recovery is also weaker than "just re-paste": the edit
  textarea is prefilled with the stored canonical URL, not the author's original snippet, so they
  must go back to the provider for the embed code.

  **Why the rule is still preferred.** The competing failure is not symmetric. Keeping the pair is
  wrong whenever the new URL has a *different* ratio from the old — and after a provider swap that is
  the common case, since the pair was captured from an unrelated embed. Clearing is wrong only when
  the new URL happens to share the old one's non-default ratio *and* the author pasted a bare URL.
  The first is a stale assertion about a different resource; the second is a lost measurement the
  author can restore. A provider-change rule would trade the first failure for a narrower version of
  itself (same-provider swaps keep a stale pair) rather than eliminating it — see "Rejected
  alternatives".
