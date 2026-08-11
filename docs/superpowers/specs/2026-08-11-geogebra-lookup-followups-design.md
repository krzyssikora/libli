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

Extract the network-touching lines into a private helper that reads the body **in chunks against its
own budget**, so the worker self-terminates rather than parking indefinitely:

```python
class _BudgetExceeded(Exception):
    """The worker's own read budget ran out. Never escapes to clean_url."""


def _fetch_body(request, deadline):          # deadline: a monotonic() instant
    with _open(request, timeout=_TIMEOUT_SECONDS) as response:
        chunks, total = [], 0
        while total <= _MAX_BODY_BYTES:      # <= so the +1 oversize byte is still read
            if time.monotonic() >= deadline:
                raise _BudgetExceeded
            chunk = response.read(_CHUNK_BYTES)
            if not chunk:                    # EOF
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks)
```

**Two bounds, and both are needed.** The chunk budget cannot cover `connect()` or the header read —
those happen inside `_open`, before a single body byte is available — so the thread deadline still
does that work. Conversely the thread deadline releases only the *main* thread; without the chunk
budget the worker itself would keep reading. Together: the main thread returns at
`_DEADLINE_SECONDS`, and the orphan dies at `_DEADLINE_SECONDS` **plus at most one per-op timeout**
(the in-flight `recv` that the budget check cannot interrupt), i.e. ~8s worst case.

The worker measures its budget from the **same start instant** the main thread joins against, so a
slow-but-successful fetch that completes at 4.9s still succeeds.

**`_BudgetExceeded` stores nothing.** `_run` catches it specifically and leaves the box empty, so the
main thread's residual branch reports `deadline exceeded`. It must **not** land in `box["exc"]` —
that would surface as `lookup failed (_BudgetExceeded)` — and a partial body must **not** be stored,
or it would be parsed as truncated JSON and mislabelled `unparseable payload`.

New constant: `_CHUNK_BYTES = 8192`.

`fetch_geogebra_dimensions` runs `_fetch_body` on a plain `threading.Thread(daemon=True)` — named
`f"geogebra-lookup-{material_id}"`, so a thread dump shows how many lookups are parked — with a
**function-local** result box created per invocation, then `join(_DEADLINE_SECONDS)`.

**Structure.** `_fetch_body(request)` stays **module-level** for readability and to keep the
per-invocation box out of a module-level signature. Note this is *not* a patch-seam requirement:
tests patch `courses.geogebra._open` by module attribute and `_open` resolves as a module global at
call time, so nesting `_fetch_body` would not disturb the seam either. The wrapper that catches,
stores and closes is a
**nested `def _run():` inside `fetch_geogebra_dimensions`**, closing over both `request` and `box` —
not a module-level target taking `box` through `Thread(args=...)`, which would put the per-invocation
box in a module-level signature for no gain.

**The box is discriminated by key presence, never by truthiness.** A dict with at most one of
`box["body"]` / `box["exc"]` set. This is load-bearing: a legitimate `read()` returning `b""` is
falsy, and a truthiness check would route a real empty response to the deadline branch instead of
today's unparseable-payload failure, silently changing the logged reason.

**The outcome is decided by inspecting the box, never by `is_alive()`.** `join(timeout)` can return
while the thread has stored its result but not yet finished unwinding, so an `is_alive()`-first
implementation would discard a good body as a timeout.

**Take one snapshot, then branch on it.** After the join, copy once — `result = dict(box)` — and
decide from `result`, not from three sequential `in` checks against a dict the worker may still be
writing. Every interleaving yields a valid outcome either way, but only a single snapshot gives the
join→read window below a single referent. Branch on the snapshot in this order:

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

**The wrapper closes an `HTTPError`'s `fp`, in this exact order: store first, then close.** #238
added the explicit `exc.close()` because a 4xx/5xx raises from inside `_open`, so the `with` is never
entered and the error's `fp` is never closed. After a deadline nobody reads that box, so without a
close in the wrapper an abandoned thread leaks the socket and emits a `ResourceWarning` from a
non-main thread.

The ordering is load-bearing. The natural-but-wrong reading —
`except Exception as exc: exc.close(); box["exc"] = exc` — means that if the close itself raises on a
real socket, `box["exc"]` is never set, the main thread reports `deadline exceeded` instead of
`HTTP 4xx`, and an unhandled exception escapes the worker through `threading.excepthook`, violating
the never-propagates invariant. Required shape:

```python
box["exc"] = exc          # store FIRST
try:
    exc.close()           # then close, guarded exactly like the main-thread one
except Exception:         # noqa: BLE001, S110 - closing must never mask the original
    pass
```

The guard mirrors `geogebra.py:379-384`, whose handler line reads `# noqa: BLE001, S110`. Match that
token list exactly rather than trimming it: `BLE` is **not** in ruff's `select`
(`["E","F","I","UP","B","S"]`), so `BLE001` is inert today — but every other broad except in this
file carries it (`:383`, `:386`, `:400`), and `geogebra.py:366-369` already warns that an inert
`noqa` becomes a duplicate the moment `RUF100` is selected. Being the file's lone divergence is worse
than sharing its convention. `S110` (try-except-pass) **is** selected and does fire here. The
main-thread handler's own `exc.close()` stays and is harmless on an already-closed error.

**This is the repository's first production background thread** — `threading` appears nowhere outside
`tests/`. The boundary rule that keeps it safe: the worker does **no ORM, no cache, and no logging**;
it only calls `_open`, reads bytes, and stores into the box. Nothing crosses a database connection,
so Django's per-thread connection handling and `close_old_connections` are not implicated. Worker-model
interactions remain hypothetical because there is no deployment.

**Only `_open` and `read` move to the thread.** The `GEOGEBRA_API_LOOKUP` check, the single cache
read (`:345`) and both cache writes (`:351` in `_fail`, `:404` in the no-usable-dimensions tail), and
all logging stay on the main thread. This is load-bearing three times over: it
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

**Four comments in `geogebra.py` must be rewritten with the code** — the same false-mechanism
standard Component B is held to. The first three are now *false*; the fourth is merely *incomplete*:

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
4. **`:7-14`, the module docstring** (orientation, not false). It describes the module as "the single
   place the GeoGebra API is called" whose "one network function performs a single capped GET behind
   the `GEOGEBRA_API_LOOKUP` kill switch". Still true, but it now omits the one architectural fact a
   reader most needs up front: that the GET runs on a background thread under a total deadline. Add
   that, plus the no-ORM / no-cache / no-logging worker boundary rule.

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
| Oversize body | unchanged in outcome — the chunk loop's `while total <= _MAX_BODY_BYTES` still accumulates the one byte past the cap that makes oversize detectable at `:389` |
| Worker's chunk budget expires | `_run` catches `_BudgetExceeded`, stores **nothing**, and the main thread's residual branch reports `deadline exceeded`. Never `box["exc"]` (that would read `lookup failed`), never a partial body (that would read `unparseable payload`) |
| `thread.start()` fails (`RuntimeError: can't start new thread`) | falls into the bare `except Exception` and degrades as `lookup failed (RuntimeError)` — the correct outcome, named here rather than left to be derived. Reachable precisely because no cap is placed on concurrent lookup threads (see accepted gaps) |
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

**The operator-visible symptom of this trade is silence, not repetition.** The cache-hit
short-circuit (`geogebra.py:345-346`) returns `(None, None)` **without logging**, so an author who
sees the badge and re-saves within the window produces no log line at all. A deadline therefore
appears exactly **once per material per 60s** — worth stating, because the whole justification above
rests on the deadline being diagnosable.

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
This is the difference between a real test and a vacuous one. If a fake waits and then returns `b""`,
the *mutant* build completes with an empty/unparseable body and `fetch_geogebra_dimensions` returns
`(None, None)` anyway — the same value the test asserts, so it is green on the fix **and** on its
mutant.

A fake returning **`None`** is worse still, and fails differently: key presence routes
`box["body"] = None` to the body branch, and `if len(body) > _MAX_BODY_BYTES:` (`geogebra.py:389`)
sits **outside** the `try`, so `len(None)` raises `TypeError` straight out of
`fetch_geogebra_dimensions` and into `clean_url` — the never-raises breach this spec otherwise works
hard to prevent. It errors; it does not return `(None, None)`. Because that hole is reachable from a
`None` in the box, the body branch **must additionally require `isinstance(result["body"], bytes)`**,
routing anything else to `_fail`. (Moving the `len()` inside the `try` would also work but changes
existing oversize-handling structure for no gain.)

Test 1's `read` therefore returns
a real payload (`_payload("wseg.json")`, so the mutant yields `(880, 660)`), and test 2's `_open`
returns a working response over the same payload. The only route to `(None, None)` must be the
deadline firing.

**`_patch_open._Resp.read` must be made STATEFUL** (`tests/test_geogebra.py:273-274`). It currently
returns `body[:n]` from the start on every call, so the chunked loop would re-read the same first
chunk forever and never reach EOF. Give `_Resp` a read offset:

```python
class _Resp:
    def __init__(self):
        self._pos = 0

    def read(self, n=-1):
        chunk = body[self._pos:] if n is None or n < 0 else body[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk
```

This is a change to **one helper**, not to the ~15 tests that use it: they call `_patch_open(body)`
and never touch `_Resp`. Single-read semantics are preserved (first call returns the same bytes as
before, the next returns `b""` = EOF), so every existing fetch test — including the oversize test,
which still accumulates past `_MAX_BODY_BYTES` — passes unchanged. **Verify that claim by running
them, not by assuming it.**

**The fakes must be context managers.** `_patch_open`'s docstring
(`tests/test_geogebra.py:267-269`) records that the double *must* support `__enter__`/`__exit__`
because the fetch uses `with _open(...) as resp:` — and that `with` survives inside `_fetch_body`. A
hand-rolled fake returning a bare object fails with an `AttributeError`, which the wrapper reports as
`lookup failed (AttributeError)`: a misleading `(None, None)` that looks like a pass. The new fakes
reuse or mirror `_patch_open._Resp`'s shape, and **test 4's log assertion is what catches this
mistake**, because the logged reason would read `lookup failed` rather than `deadline exceeded`.

**All four tests patch `_DEADLINE_SECONDS` via `monkeypatch.setattr`** — which also exercises the
read-at-call-time rule above. Leaving the real 5s in place would cost 5s of wall clock per test.

Pin **concrete values**, not ranges: `_DEADLINE_SECONDS = 0.3` against `Event.wait(3)`. Two
constraints are in play, and stating them as independent ranges is a trap — a reader picking legal
endpoints from each (wait 2s, deadline 0.5s) gets a ratio of 4 and violates the first:

1. **`wait ≥ 10 × deadline`** — governs whether the *fixed* build deadlines at all.
2. **`deadline ≥ 0.3s` (a floor)** — governs the thread-start-plus-scheduler race described under
   test 3. A 0.1s deadline is not defensible against scheduling latency on a loaded xdist or Windows
   run.

**The floor is not about test 2.** Under test 2's mutant ("wrap only the read") `_open` runs on the
**main** thread — before any thread is started and before any `join` — so the main thread simply
blocks in the fake for its full wait and returns `(880, 660)`. That mutant is deterministically RED
at any deadline value; there is no race to lose. The floor is justified by test 3 alone.

**`(None, None)` alone is never a sufficient assertion.** It is this function's *universal*
degradation value — the kill switch, a cache hit, an `HTTPError`, an unparseable body, an oversize
body and every transport exception all return it. A test asserting only the tuple is green whenever
the call fails **for any reason at all**, including a broken fake the wrapper reports as
`lookup failed (TypeError)`. So tests 1 and 2 additionally assert, via `caplog` filtered on
`courses.geogebra`, that the logged reason is the **deadline** reason — the pattern
`test_fetch_degrades_on_http_error_and_logs_it` already uses at `:346-347`. That closes the whole
class, not one instance of it.

1. **Slow body → deadline.** The fake `read` blocks on a bounded `Event.wait(...)` that is never set
   *during the test body* and is released in teardown, then returns a real payload. Assert
   `(None, None)` **and** the deadline reason in the log;
   never elapsed wall-clock, so no timing assertion and no flake.
   *Mutant:* restore the direct `_fetch_body(request)` call.
2. **Slow headers → deadline,** by patching `_open` itself to block on its own bounded event,
   released in teardown exactly as in test 1. Same two assertions. Pins that the bound wraps `_open`
   and not merely the read. *Mutant:* wrap only the read.
3. **A deadline negative-caches.** Reuses **test 1's blocking-`read` fake**. Second call
   short-circuits; `_open` called once. *Mutant:* bare `return (None, None)` without `_fail`.

   **Both directions race, and the fixed-build direction is the dangerous one.** Asserting
   `call_count == 1` on the *correct* build requires the first worker to have reached `_open` before
   the main thread's post-join assertion runs; lose that and the test reads `call_count == 0` and
   turns a **correct build RED** — worse than the flaky-green case. The deadline floor alone is not
   sufficient here. Remove the race by synchronisation, not timing: the fake sets an "entered"
   `Event` on entry, and the test waits on it before asserting `call_count`.
4. **The deadline log names the material id AND the reason.** Asserting the id alone would be
   vacuous: `_fail` logs `"geogebra %s: %s"`, so `lookup failed (AttributeError)` from a broken fake
   also names the id — meaning a test asserting only the id is green on precisely the mistake this
   test is designated to catch. Assert both the id and the reason substring (e.g. `"deadline"`).
   *Mutants:* drop the log line; and pass `_fail` the generic reason string instead of the deadline
   one.

### The chunk budget — a FIFTH new test, driving `_fetch_body` directly

`_fetch_body` is module-level and takes its deadline as an argument, so the budget is tested
**without any thread, any `join`, or any `_DEADLINE_SECONDS` patching** — no concurrency in the test
at all. Two cases, both deterministic:

5a. **Deadline already past → `_BudgetExceeded`, and `read` is never called.** Pass
    `deadline = time.monotonic() - 1`. Pins that the budget is checked *before* each read rather
    than only after data arrives. *Mutant:* drop the check entirely — the fake's finite body is read
    to EOF and returned, no exception, RED.

5b. **Deadline expires mid-loop → `_BudgetExceeded` after exactly N reads.** Patch
    `courses.geogebra.time.monotonic` with a **fake clock** that returns a scripted increasing
    sequence, chosen so the check trips on the third iteration; assert `read` was called exactly
    twice. A fake clock, not `sleep`, is what makes this exact rather than timing-dependent.
    *Mutant:* hoist the check out of the loop so it runs once before iterating — `read` is then
    called to EOF, RED. This is the mutant 5a alone cannot kill.

Both cases use a **finite** fake body (a few KB delivered one chunk per call), so a mutant build
terminates and FAILS rather than hanging — the same bounded-fake rule as the deadline tests.

### The constant relationship — a SIXTH new test in the same file

This is a fifth new test in `tests/test_geogebra.py`, deliberately outside the numbered list above
because the "all four" rules do **not** apply to it: it must **not** patch `_DEADLINE_SECONDS` (it
exists to observe the shipped value) and it needs no `@override_settings`, since it touches no
transport at all. It is one assertion, not a behaviour test.

Every test above patches `_DEADLINE_SECONDS` to a small value, so **nothing in the suite ever
observes the shipped relationship** between the two constants. A future edit setting
`_DEADLINE_SECONDS = 2` would silently invert the design argued under "Constants" — the connect-leg
failure would start reporting `deadline exceeded` — and every test would stay green.

Assert **`_DEADLINE_SECONDS >= _TIMEOUT_SECONDS + 1`**, not merely `>`. A bare `>` is satisfied by
`_DEADLINE_SECONDS = 3.5`, which re-introduces exactly the mislabelling the "Constants" paragraph
forbids: the measured connect-leg failure takes **~3.29s**, so the deadline must clear the measured
figure, not just the nominal constant. Cite the 3.29s measurement in the assertion's comment.
*Mutant:* swap the two constants' values.

**`daemon=True` is deliberately not falsified.** It is the property that stops a parked lookup from
holding worker shutdown open, but every test in the suite is green with `daemon=False` — the bounded
fakes all complete within seconds, so no test can distinguish them without asserting on the `Thread`
object itself. Rather than add a mock-shaped assertion that pins construction rather than behaviour,
this is recorded as untested, in the same style as the existing "deliberately untested: a branch that
cannot be driven cannot be falsified to RED" note at `geogebra.py:356-359`.

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
   Vimeo now **clears**. The load-bearing assertions are `(width, height) == (None, None)` and
   `frame_ratio is None`. A `size_unknown is False` assertion may be kept as documentation but is
   **not** discriminating and must be labelled as such: `size_unknown` is
   `is_geogebra_iframe_url(self.url) and not usable_dimensions(...)` (`models.py:886-888`), and the
   new URL is a Vimeo one, so the first conjunct is `False` whether or not the pair was cleared — the
   Defect-2 table above shows `False` in both the buggy and the fixed row. Under this test's own
   mutant it stays green, which is exactly the assertion-that-cannot-fail class this project treats
   as a recurring defect. Its comment currently
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

**Both rewritten tests MUST retain their existing `lookup.assert_not_called()`** (`:493` and
`:507`). That assertion is the *second* guard on which `and mid` survives: it is what distinguishes
"dropped the `:196` conjunct" from "dropped both conjuncts". Without it, neither test would notice a
build that also removed the `:217` lookup guard and started issuing empty-id GETs.

### One NEW form test — the coverage hole the inversions open

7. **A non-GeoGebra element with a stored pair keeps it when the URL is unchanged.** Create a Vimeo
   element with `(640, 360)`, re-submit its own stored URL with a changed title, assert the pair
   survives and `lookup.assert_not_called()`.

   This is needed because `:481` and `:498` are the **only** two form tests using a non-GeoGebra
   stored pair, and both are being inverted to assert clearing. The two "preserves" tests in the
   regression table below (`:293`, `:410`) both use the GeoGebra `URL` constant, so after this change
   nothing would pin that a non-GeoGebra pair survives an unchanged URL — Component B's
   highest-risk failure mode, since `url_changed` is `extract_embed_url(raw) != self.instance.url`
   and any future non-idempotent canonicalisation for a new provider would then wipe every such
   element's pair on every save, with no lookup to restore it and no badge to signal it.

   *Mutant:* invert the scoping — clear only when the new URL is **non**-GeoGebra
   (`if not usable_dimensions(width, height) and not mid`). `:410` and `:293` both survive it because
   they use the GeoGebra `URL` constant; test 7's Vimeo/unchanged-URL case goes RED.

   **Note the mutant that does *not* work here:** "drop the `url_changed` conjunct" is already killed
   by two existing tests, so it would not justify a new test. Under it the guard becomes
   `if not usable_dimensions(width, height)`, so `:410` clears the stored `(880, 660)` on a
   title-only edit, `stored_usable` goes `False`, `mid` is truthy, the lookup fires and its
   `lookup.assert_not_called()` goes RED; `:293` goes RED too, saving `(None, None)` instead of
   `(800, 760)`.

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

That last one guards the `:217` lookup guard. Its own comment at
`tests/test_iframe_dimensions.py:377-382` ("THE guard on the `and mid` conjunct") becomes ambiguous
once the `:196` conjunct is gone — it must be re-worded to name *which* guard.

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

- **A single `read(_MAX_BODY_BYTES + 1)` with no chunk budget** — the original shape of this design,
  now rejected. It leaves the orphan effectively unbounded: a peer dribbling one byte per second
  never trips the 3s per-op timeout (that is exactly what Defect 1's `16.18s` / `VERDICT: PER-OP`
  measurement proves), so the read loops until 65,537 bytes arrive — ~18 hours holding a socket and a
  thread stack, against the same adversary this change bounds the lock against. The 60s negative
  cache limits how often a *new* orphan is created per material but does nothing about one already
  parked. The cost of the chunked alternative is one test-helper change (see Testing), which does not
  justify leaving an unbounded resource behind.
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
- **Thread creation and thread abandonment are different rates.** One thread is *created* per lookup
  that reaches the network (a dimensionless GeoGebra save, suppressed 60s per material by the
  negative cache); a thread is only *abandoned* when the deadline actually fires. The common case
  leaves nothing parked.
- **An abandoned thread is bounded at ~8s** — `_DEADLINE_SECONDS` plus at most one per-op timeout for
  the `recv` already in flight when the budget expires. It holds one socket and one thread stack for
  that period. Note the per-op timeout alone would **not** bound it: a peer dribbling one byte per
  second never trips it, which is what Defect 1's `16.18s` / `VERDICT: PER-OP` measurement proves —
  the chunk budget, not the socket timeout, is what makes this finite.
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
  with no ceiling and no counter. A cap would add a queue whose wait would itself be inside the row
  lock, which is the opposite of the goal.

  **The ceiling is "distinct dimensionless materials pasted within one orphan lifetime"** — and
  because the chunk budget caps that lifetime at ~8s, this reduces to instantaneous editor
  concurrency rather than growing monotonically while the API misbehaves. Accepted, with the note
  that nothing makes it observable: there is no counter, and `thread.start()` failing surfaces only
  as `lookup failed (RuntimeError)` in the log.
- **Prior design docs are left as historical record.** `docs/superpowers/specs/2026-08-10-geogebra-share-link-sizing-design.md`
  and its plan document the GeoGebra-scoped clear and its accepted gap. They are not annotated or
  amended; this spec supersedes them.
- **`docs/development/architecture.md:106` gets a one-line update.** It currently describes
  `geogebra.py` as "Embed-URL canonicalization for video / GeoGebra". Introducing the repository's
  only production background thread is an architecture-level fact, and this spec holds itself to
  rewriting every comment the change makes false or incomplete — the same standard applies to the
  architecture doc. Unlike the historical design docs above, this one describes the code as it is
  *now*, so it is in scope.
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
