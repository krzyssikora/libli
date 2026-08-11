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

`frame_ratio` step 2 (`courses/models.py:866`) is documented as "the branch every non-GeoGebra
provider reaches", so a 16:9 video renders in a 4:3 box, badge-less — the same pillarbox defect #238
existed to remove, entered through a different door.

## Architecture

Two independent changes. **No migration, no `FORMAT_VERSION` bump** — `width`/`height` already exist
on `IframeElement`.

| Component | File | Change |
|---|---|---|
| A — total deadline | `courses/geogebra.py` | extract `_fetch_body`, run it on a daemon thread bounded by a new `_DEADLINE_SECONDS` |
| B — stale-pair clear | `courses/element_forms.py` | drop the `and mid` conjunct; rewrite two comments |

### Component A — a total deadline around the lookup

Extract the two network-touching lines into a private helper:

```python
def _fetch_body(request):
    with _open(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read(_MAX_BODY_BYTES + 1)  # +1 so oversize is detectable
```

`fetch_geogebra_dimensions` runs `_fetch_body` on a plain `threading.Thread(daemon=True)` with a
mutable result box, then `join(_DEADLINE_SECONDS)`. Three outcomes:

1. **Body returned** → the existing parse path runs unchanged.
2. **Thread raised** → the exception is captured in the box and **re-raised on the main thread**, so
   the existing `except urllib.error.HTTPError` and bare-`except Exception` handlers run exactly as
   today, including `exc.close()`.
3. **Still alive at the deadline** → `_fail("deadline exceeded")`.

**Only `_open` and `read` move to the thread.** The `GEOGEBRA_API_LOOKUP` check, both cache reads and
the cache write, and all logging stay on the main thread. This is load-bearing three times over: it
keeps `_open` the universal patch seam every existing test relies on, it keeps `caplog` able to see
the warnings, and it prevents an abandoned thread from racing the negative-cache write.

**Constants.** `_TIMEOUT_SECONDS = 3` is unchanged and remains the *per-socket-operation* timeout.
`_DEADLINE_SECONDS = 5` is new and is the *total* bound. The deadline is deliberately **larger** than
the per-op timeout so that single-operation failures still surface as themselves — the existing
blackhole path times out at ~3.29s and must keep doing so rather than racing the deadline. 5s becomes
the worst case the unit row lock can be held, against unbounded today.

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
and 500 the save. A deadline is a failure like any other, so a GeoGebra element shows the existing
"size unknown" badge and the author can retry — which is why `_NEGATIVE_TTL_SECONDS` is only 60.

## Testing

Every test names the mutant that must turn it RED, per the project's falsify-don't-run rule.

### `tests/test_geogebra.py` — the deadline

1. **Slow body → `(None, None)`.** The fake `read` blocks on a `threading.Event` the test never sets,
   with `_DEADLINE_SECONDS` patched small. Assert the **result**, never elapsed wall-clock — no
   timing assertion, so no flake. Set the event afterwards so the orphan thread dies with the test.
   *Mutant:* restore the direct `_fetch_body(request)` call.
2. **Slow headers → `(None, None)`,** by patching `_open` itself to block. Pins that the bound wraps
   `_open` and not merely the read. *Mutant:* wrap only the read.
3. **A deadline negative-caches.** Second call short-circuits; `_open` called once.
   *Mutant:* bare `return (None, None)` without `_fail`.
4. **The deadline logs and names the material id,** matching the other four failure modes.
   *Mutant:* drop the log line.

### `tests/test_iframe_dimensions.py` — the stale pair

5. **GeoGebra → Vimeo clears**; `frame_ratio is None`, `size_unknown` is `False`.
   *Mutant:* restore `and mid`. This is the defect itself.
6. **Same-provider swap** (Vimeo A → Vimeo B) clears. *Mutant:* a provider-change rule. This test
   exists specifically to pin the rule that was chosen over the provider-change alternative.
7. **Title-only edit** neither clears nor fires a lookup. *Mutant:* drop `url_changed`.
8. **A paste carrying `width`/`height` keeps them.** *Mutant:* clear unconditionally.
9. **Control: GeoGebra → GeoGebra** still clears and re-looks-up.

### Existing tests

No existing test changes. In particular
`test_fetch_sends_the_explicit_user_agent_and_the_configured_timeout` pins
`opener.call_args.kwargs["timeout"] == _TIMEOUT_SECONDS`, which stays true because the per-op timeout
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

- **A chunked-read budget** so an abandoned thread self-terminates. `tests/test_geogebra.py:273`'s
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
- **The chosen rule's known cost:** a trivial URL edit on a hand-pasted embed loses the captured pair.
  Re-pasting the embed code restores it.
