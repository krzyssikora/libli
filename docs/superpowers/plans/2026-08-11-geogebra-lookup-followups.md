# GeoGebra Lookup Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound the GeoGebra API lookup that runs inside `save_element`'s unit row lock, and clear a stored `(width, height)` pair whenever the element's URL changes.

**Architecture:** Two independent changes. Component A moves the transport onto a bounded daemon thread whose body read is itself chunked against a budget, so neither the row lock nor the worker can be held indefinitely by a slow peer. Component B removes one conjunct from `IframeElementForm.clean_url`'s stale-pair guard so the pair is cleared on any URL change, not only a GeoGebra one.

**Tech Stack:** Python 3.13.12, Django 5.2.15, pytest 9 + pytest-django, `urllib.request`, stdlib `threading`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-11-geogebra-lookup-followups-design.md` — read it before starting. It exited an 8-round review with 95 catches applied; the code shapes, constants and test parameters below were arrived at by measurement or by traced falsification. **Carry them forward verbatim. Do not re-derive or paraphrase them** — several paraphrases were themselves defects the review removed.

## Global Constraints

- **Worktree only.** All work happens in `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/geogebra-lookup-followups` on branch `pipeline/geogebra-lookup-followups` (off `master` at `d197a4c7`). Never edit the main repo at `C:/Users/krzys/Documents/Python/own/libli`.
- **No migration, no `FORMAT_VERSION` bump.** `IframeElement.width`/`height` already exist.
- **`uv run` prefix is mandatory** — `pytest`, `ruff` and `python` are not on PATH. Use `uv run pytest`, `uv run ruff`.
- **The test-DB container must be up before any pytest run.** Verified running at plan time: `libli-test-db` (healthy, `127.0.0.1:55433`) and `bonnot-postgres` (healthy, `5432`). If a run appears to hang for ~4 minutes, the container is down — check first, don't debug the test.
- **`.env` and this worktree.** A git worktree has **no** `.env`. Verified empirically at plan time: both `tests/test_geogebra.py` (104 passed) and a DB-backed test from `tests/test_iframe_dimensions.py` (1 passed) run fine without one, because `config/settings/base.py:80-84` defaults `DATABASE_URL` to `postgres://libli:libli@localhost:5432/libli`. **Caveat:** the main repo's `.env` sets `TEST_DATABASE_URL` at the tuned `libli-test-db` (55433), so worktree runs use a *different* server (5432) than normal runs. That is acceptable for this plan's unit-only scope. If you want parity, copy `.env` from the main repo into the worktree first.
- **⚠️ PREFIX EVERY pytest RUN WITH A DEDICATED TEST DATABASE.** Discovered during Task 1: a second pipeline worktree (`uniform-tinted-block-width`) is running e2e tests concurrently. It also has no `.env`, so it defaults to the *same* `test_libli` on 5432 this worktree would — Task 1's first gate run failed with `DuplicateDatabase: database "test_libli" already exists` and then `OperationalError: ... being accessed by other users`. Use:

  ```bash
  TEST_DATABASE_URL="postgres://libli:libli@127.0.0.1:55433/libli_gg" uv run pytest ...
  ```

  This puts this worktree on `test_libli_gg` on the tuned server — a name no other consumer touches (the other worktrees use `test_libli` on 5432; the main repo's `.env` uses `test_libli` on 55433). Verified working. Note `config/settings/test.py` **refuses** a `TEST_DATABASE_URL` on the same server as `DATABASE_URL`, so renaming the DB on 5432 is not an option — the port must differ.

- **If a run still collides, do NOT kill the competing pytest.** Dropping the database under live workers poisons the survivor (it produced 61 phantom `SystemExit: 2` errors in unrelated files once). Wait, or re-target as above.
- **Falsify, don't just run.** Every test below names a mutant. Apply the mutant, observe RED, then **edit the mutant back out by hand**. Never `git checkout` to revert a mutant — that destroys uncommitted work.
- **Scope test runs narrowly** during tasks (the two named files). The whole-suite sweep is Task 6 only.
- **Every task has a format-and-lint step immediately before its commit** — `uv run ruff format .` plus `uv run ruff check --no-cache <the files that task touched>`. Do not skip it: `ruff format --check` is a separate CI gate from `ruff check`, `ruff format` does **not** sort imports (`I001` is only caught by `ruff check`), and the embedded code blocks here are written for readability rather than in already-formatted shape. Discovering either at Task 6 means re-touching files from five earlier commits.
- **Ruff import order is `order-by-type = true` (the default).** Found during Task 2: within a from-import group, **CONSTANTS sort before classes before functions**, so `from courses.geogebra import _CHUNK_BYTES` must precede `from courses.geogebra import _BudgetExceeded`, which precedes `_fetch_body`. The plan's embedded test blocks list `_BudgetExceeded` first in places; that is an `I001` and must be reordered. `ruff format` does **not** fix it — only `ruff check` catches it.
- **Ruff:** `select = ["E","F","I","UP","B","S"]`. `BLE` is *not* selected, but every broad except in `geogebra.py` still carries `BLE001` in its `noqa` — match the file's convention rather than trimming it. Run `ruff` with `--no-cache`; a cached run reports "All checks passed" on a file that previously warned.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `courses/geogebra.py` | the only place the GeoGebra API is called | Component A: `_BudgetExceeded`, `_CHUNK_BYTES`, `_DEADLINE_SECONDS`, `from time import monotonic`, `import threading`, `_fetch_body`, threaded `fetch_geogebra_dimensions`, 4 comment rewrites |
| `courses/element_forms.py` | `IframeElementForm.clean_url` | Component B: drop one conjunct at `:196`, 2 comment rewrites |
| `docs/development/architecture.md` | module map | one line at `:106` |
| `tests/test_geogebra.py` | fetch/parser unit tests | hoist `_Resp`; **8** new tests (5a, 5b, tests 1-4, 5c, constant-relationship) |
| `tests/test_iframe_dimensions.py` | form + render tests | 2 tests rewritten in place, 1 new |

---

### Task 1: Make the response double stateful and reachable

The chunked loop reads repeatedly, so the existing double — which returns `body[:n]` from the start on **every** call — would re-read chunk one forever and never reach EOF. It is also defined *inside* `_patch_open`, so tests that must assert on its call count have no handle on the instance. Both are fixed before any production code changes, and the existing suite proves the change is behaviour-preserving.

**Files:**
- Modify: `tests/test_geogebra.py:264-287`

**Interfaces:**
- Consumes: nothing.
- Produces: module-level `class _Resp` with `__init__(self, body)`, `read(n=-1)`, `read1` (alias), `calls: int`, `__enter__`/`__exit__`. Tasks 2–4 construct it directly as `_Resp(body)`.

- [x] **Step 0: Capture the branch-point test count — before changing anything**

Task 6 compares the final suite against this figure, and **now** is the only moment it can be taken cleanly: the worktree currently differs from `d197a4c7` only by the spec and plan documents, which contribute no tests. Capturing it later would need a detached checkout of `d197a4c7`, which would **delete the plan and spec from disk** while the executing agent is reading them.

```bash
uv run pytest --collect-only --verbosity=0 | tail -1
```

Record the **left-hand number** of the `A/B` pair it prints (e.g. `5974/6886 tests collected (912 deselected)` → record **5974**). The right-hand figure includes deselected e2e tests. Write it into this step as you go, so it survives a session boundary:

> Branch-point selected-collection count: `5974`

- [x] **Step 1: Read the current helper**

Read `tests/test_geogebra.py:264-287`. Note that `_Resp` is nested inside `_patch_open`, closes over `body`, and that `_side_effect` returns a fresh `_Resp()` per call.

- [x] **Step 2: Replace it with the module-scope version**

Hoist `_Resp` **above** `_patch_open` and rewrite `_patch_open` to construct it. Keep `_patch_open`'s signature exactly — its ~17 callers must not change.

```python
class _Resp:
    """Stateful response double: a read offset, so a chunked loop reaches EOF.

    Module scope (not nested in _patch_open) so tests that assert on `calls` can
    hold the instance -- unittest.mock does not record return values, so a test
    using `with _patch_open(body)` has no other handle on it.
    """

    def __init__(self, body):
        self._body = body
        self._pos = 0
        self.calls = 0

    def read(self, n=-1):
        self.calls += 1
        if n is None or n < 0:
            chunk = self._body[self._pos :]
        else:
            chunk = self._body[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    read1 = read  # same offset, same counter -- read1 is what _fetch_body calls

    def __enter__(self):  # the fetch uses `with _open(...) as resp`
        return self

    def __exit__(self, *exc_info):
        return False


def _patch_open(body=None, exc=None):
    """Patch the transport seam; return the mock so tests can assert on call args.

    The double MUST be a context manager: fetch_geogebra_dimensions uses
    `with _open(...) as resp:` (needed because the read is capped, so the connection is
    never drained and an unclosed response leaks a socket per call).
    """

    def _side_effect(request, timeout=None):
        if exc is not None:
            raise exc
        return _Resp(body)

    return patch("courses.geogebra._open", side_effect=_side_effect)
```

Note one deliberate semantic change: the old double treated `n == 0` as "read everything"; the new one returns `b""`, as a real file object does. No caller passes `0`.

- [x] **Step 3: Run the existing suite — it must be green with no production change**

Run: `uv run pytest tests/test_geogebra.py --verbosity=0`
Expected: **104 passed**. This is the whole point of doing it first — if anything reddens here, the double is not behaviour-preserving and Task 2 would be debugging two changes at once.

- [x] **Step 4: Format and lint the files this task touched**

```bash
uv run ruff format .
uv run ruff check --no-cache tests/test_geogebra.py
```

Do this **before** the commit, not at Task 6. `ruff format` does not sort imports, and `ruff format --check` is a separate CI gate — discovering either at the end means re-touching files from several earlier commits.

- [x] **Step 5: Commit**

```bash
git add tests/test_geogebra.py
git commit -m "test(geogebra): hoist the response double to module scope and give it a read offset"
```

---

### Task 2: `_fetch_body` — the chunked read under its own budget

Extracts the transport into a module-level helper that reads in `read1` chunks and abandons the read when its budget expires. Still synchronous — the thread arrives in Task 3 — so the existing suite stays green throughout.

**Files:**
- Modify: `courses/geogebra.py` (imports, constants block, new class + function, `fetch_geogebra_dimensions` body)
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: `_Resp` (Task 1), existing `_open`, `_TIMEOUT_SECONDS`, `_MAX_BODY_BYTES`.
- Produces: `class _BudgetExceeded(Exception)`; `_CHUNK_BYTES = 8192`; `_DEADLINE_SECONDS = 5`; `_fetch_body(request, deadline) -> bytes`, raising `_BudgetExceeded`; module-level name `monotonic`. Task 3 wraps `_fetch_body` in a thread; Task 4 asserts on the two constants.

- [x] **Step 1: Write the failing tests (5a and 5b)**

Add to `tests/test_geogebra.py`. Neither needs `@override_settings` — `_fetch_body` never reads the kill switch.

```python
def test_fetch_body_refuses_to_read_once_the_budget_is_spent():
    # 5a: the budget is checked BEFORE each read, not only after data arrives.
    from courses.geogebra import _BudgetExceeded
    from courses.geogebra import _fetch_body
    from courses.geogebra import monotonic

    resp = _Resp(b"x" * 100)
    with patch("courses.geogebra._open", return_value=resp):
        with pytest.raises(_BudgetExceeded):
            _fetch_body(object(), monotonic() - 1)
    assert resp.calls == 0


def test_fetch_body_rechecks_the_budget_on_every_iteration(monkeypatch):
    # 5b: the check is INSIDE the loop. A fake clock, not sleep, so this is exact.
    # itertools.count never exhausts: a finite scripted list would hard-code how
    # many times the implementation calls monotonic() and would StopIteration out
    # of a legal variant, failing a correct build for an unrelated reason.
    from courses.geogebra import _BudgetExceeded
    from courses.geogebra import _CHUNK_BYTES
    from courses.geogebra import _fetch_body

    clock = itertools.count(start=0.0, step=1.0)
    monkeypatch.setattr("courses.geogebra.monotonic", lambda: next(clock))

    # 3 chunks' worth, so reads 1 and 2 do NOT hit EOF and the loop is still
    # running when the third budget check trips.
    resp = _Resp(b"x" * (3 * _CHUNK_BYTES))
    with patch("courses.geogebra._open", return_value=resp):
        with pytest.raises(_BudgetExceeded):
            # ticks: check1 -> 0.0 (ok), check2 -> 1.0 (ok), check3 -> 2.0 (trips)
            _fetch_body(object(), 2.0)
    assert resp.calls == 2
```

Add `import itertools` to the test module's imports. Placement is not free — `I` is selected and `force-single-line = true`, so it must sit in the stdlib block in sort order. Tasks 2 and 3 between them add three test imports; the resulting stdlib block is:

```python
import itertools
import json
import logging
import threading
```

(plus whatever else the file already imports, in the same alphabetical run — `itertools` before `json`, `logging` and `threading` after it.) Getting this wrong surfaces as `I001`, which `ruff format` does **not** fix.

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_geogebra.py -k "fetch_body" --verbosity=0`
Expected: FAIL — `ImportError: cannot import name '_BudgetExceeded'`.

- [x] **Step 3: Add the import and the constants**

In `courses/geogebra.py`, add to the import block (`:17-22`). `pyproject.toml:43-44` sets `force-single-line = true`, and ruff's default section ordering puts `from time import ...` in the same stdlib block sorted by module name — so it goes **after `import urllib.request` and before `from urllib.parse import urlsplit`**:

```python
import json
import logging
import re
import urllib.error
import urllib.request
from time import monotonic
from urllib.parse import urlsplit
```

Getting this wrong surfaces as `I001` only at Task 6's lint gate, which means re-touching files from earlier commits — so run `uv run ruff check --no-cache courses/geogebra.py` before this task's commit, not just `ruff format`.

Import the **bare name**, not the module. `courses.geogebra.time` *is* the stdlib module object, so patching `courses.geogebra.time.monotonic` would rebind `time.monotonic` process-wide, where `threading`, `logging`, `socket` and pytest's own internals would consume the test's scripted clock values. The bare name gives the clock the same module-local patch seam `_open` already has.

Then rewrite the `_TIMEOUT_SECONDS` comment (`:46-53`) and add the two new constants:

```python
_API_PREFIX = "https://api.geogebra.org/"
# A module constant rather than a setting, matching the pattern of
# integrations/delivery.py :: TIMEOUT_SECONDS = 10. This bounds urllib's SOCKET
# ops -- connect() and each individual read() -- NOT the total call. That is why
# it is no longer sufficient on its own: the total call is bounded separately,
# by _DEADLINE_SECONDS. Measured: a peer dribbling one byte per second held a
# single read for 16.18s against this 3s timeout.
_TIMEOUT_SECONDS = 3
# Total bound on the lookup. Deliberately LARGER than a single socket op so a
# failure in the FIRST op still surfaces as itself -- the blackhole/connect path
# times out at a measured ~3.29s and must keep reporting "lookup failed (timeout)"
# rather than racing this deadline.
_DEADLINE_SECONDS = 5
# Chunk size for the body read. Larger chunks mean fewer syscalls but coarser
# budget-check granularity; the loop may overshoot the cap by up to one chunk
# (peak buffer _MAX_BODY_BYTES + _CHUNK_BYTES = 73,728 bytes). Need not divide
# _MAX_BODY_BYTES.
_CHUNK_BYTES = 8192
_MAX_BODY_BYTES = 65536  # ~55x the measured 1,177-byte ws response
```

- [x] **Step 4: Add `_BudgetExceeded` and `_fetch_body`**

Place both immediately below `_open` (`:251-253`), so `_fetch_body` sits adjacent to the transport seam it wraps:

```python
class _BudgetExceeded(Exception):
    """The worker's own read budget ran out. Never escapes to clean_url."""


def _fetch_body(request, deadline):  # deadline: a monotonic() instant
    """Read the response body in chunks, abandoning it when the budget expires.

    read1, NOT read: HTTPResponse.read(n) delegates to a BufferedReader that loops
    over recv until it has n bytes or hits EOF, so each individual recv returns
    inside _TIMEOUT_SECONDS and the timeout never fires. Measured against a peer
    dripping one byte per 50ms: read(8192) blocked 10.13s for the whole body,
    read1(8192) returned in 0.05s on the first available bytes. With read, this
    loop would not bound anything -- it would only divide the unbounded wait by
    _MAX_BODY_BYTES / _CHUNK_BYTES.
    """
    with _open(request, timeout=_TIMEOUT_SECONDS) as response:
        chunks, total = [], 0
        # loop past the cap so oversize stays detectable
        while total <= _MAX_BODY_BYTES:
            if monotonic() >= deadline:
                raise _BudgetExceeded
            chunk = response.read1(_CHUNK_BYTES)
            if not chunk:  # EOF
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks)
```

- [x] **Step 5: Call it from `fetch_geogebra_dimensions` (still synchronous)**

Inside the existing `try` block, replace the `with _open(...) as response: body = response.read(...)` pair with:

```python
        budget = _DEADLINE_SECONDS
        deadline = monotonic() + budget
        body = _fetch_body(request, deadline)
```

Leave the `Request` construction, its `# noqa: S310` comment, and both `except` handlers exactly where they are.

- [x] **Step 6: Run 5a/5b and the whole file**

Run: `uv run pytest tests/test_geogebra.py --verbosity=0`
Expected: **106 passed** (104 existing + 5a + 5b). The existing oversize test still passes: a 65,537-byte body is delivered in 9 `read1` calls, `total` passes the cap, and `len(body) > _MAX_BODY_BYTES` still fires.

- [x] **Step 7: Falsify 5a**

Delete the two `if monotonic() >= deadline: raise _BudgetExceeded` lines.
Run: `uv run pytest tests/test_geogebra.py -k "budget_is_spent" --verbosity=0`
Expected: FAIL — the finite body is read to EOF and returned, no exception raised.

Note this mutant reddens **both** 5a and 5b (the `-k` filter scopes the run to 5a). That is expected: 5b's distinct value is proved by Step 8's mutant, which 5a survives.
**Edit the lines back in by hand.** Re-run: PASS.

- [x] **Step 8: Falsify 5b**

Hoist the budget check out of the loop, so it runs once before iterating:

```python
        if monotonic() >= deadline:
            raise _BudgetExceeded
        while total <= _MAX_BODY_BYTES:
```

Run: `uv run pytest tests/test_geogebra.py -k "every_iteration" --verbosity=0`
Expected: FAIL — only one check happens (at t=0.0), so `read1` runs to EOF and no exception is raised. This is the mutant 5a alone cannot kill.
**Edit it back by hand.** Re-run: PASS.

- [x] **Step 9: Format and lint the files this task touched**

```bash
uv run ruff format .
uv run ruff check --no-cache courses/geogebra.py tests/test_geogebra.py
```

Do this **before** the commit, not at Task 6. `ruff format` does not sort imports, and `ruff format --check` is a separate CI gate — discovering either at the end means re-touching files from several earlier commits.

- [x] **Step 10: Commit**

```bash
git add courses/geogebra.py tests/test_geogebra.py
git commit -m "feat(geogebra): read the body in read1 chunks under an explicit budget"
```

---

### Task 3: Move the transport onto a bounded daemon thread

The chunk budget cannot cover `connect()`, the TLS handshake or the header read — those all happen inside `_open`, before a single body byte exists. The thread deadline is what releases the **main** thread (and therefore the row lock) regardless of what the peer does.

**Files:**
- Modify: `courses/geogebra.py` (`fetch_geogebra_dimensions`, three comments), `docs/development/architecture.md:106`
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: `_fetch_body`, `_BudgetExceeded`, `_DEADLINE_SECONDS`, `monotonic` (Task 2); `_Resp` (Task 1).
- Produces: `fetch_geogebra_dimensions` unchanged in signature and return contract — `(int, int) | (None, None)`, never raises.

- [x] **Step 1: Write the four failing tests**

Add to `tests/test_geogebra.py`. All four carry `@override_settings(GEOGEBRA_API_LOOKUP=True)` — `config/settings/test.py:30` sets it `False`, and the kill switch returns `(None, None)` before any thread is created, which is byte-identical to what tests 1 and 2 assert. Without the decorator each test is green on the fix *and* on its mutant.

`_DEADLINE_SECONDS` is patched to **0.3** against `Event.wait(3)`. Two constraints, jointly: `wait >= 10 x deadline`, and `deadline >= 0.3` as a floor against thread-start plus scheduler latency on a loaded Windows/xdist run.

```python
def _slow_resp_cls(released, entered=None):
    """A _Resp whose read1 blocks until `released` (bounded), then returns the body.

    Bounded, never unbounded: there is no pytest-timeout in this project, so a fake
    that blocks forever makes the MUTANT run hang rather than fail -- indistinguishable
    from the "test-DB container is down" mode.
    """

    class _SlowResp(_Resp):
        def read1(self, n=-1):
            if entered is not None:
                entered.set()
            released.wait(3)
            return super().read1(n)

    return _SlowResp


def _geogebra_reasons(caplog):
    return [r.message for r in caplog.records if r.name == "courses.geogebra"]


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_abandons_a_slow_body_at_the_deadline(monkeypatch, caplog):
    # Test 1. NOTE: (None, None) alone is NOT a sufficient assertion -- it is this
    # function's universal degradation value. Under this test's own mutant the call
    # also returns (None, None), so the caplog reason is the SOLE discriminator.
    monkeypatch.setattr("courses.geogebra._DEADLINE_SECONDS", 0.3)
    released = threading.Event()
    resp = _slow_resp_cls(released)(_payload("wseg.json"))
    try:
        with caplog.at_level(logging.WARNING, logger="courses.geogebra"):
            with patch("courses.geogebra._open", return_value=resp):
                assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    finally:
        released.set()  # release in teardown; never leave a thread parked
    assert any("deadline" in m for m in _geogebra_reasons(caplog))


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_abandons_slow_HEADERS_at_the_deadline(monkeypatch, caplog):
    # Test 2. Pins that the bound wraps _open itself, not merely the read -- the
    # leg a chunk budget alone cannot cover.
    monkeypatch.setattr("courses.geogebra._DEADLINE_SECONDS", 0.3)
    released = threading.Event()

    def _slow_open(request, timeout=None):
        released.wait(3)
        return _Resp(_payload("wseg.json"))

    try:
        with caplog.at_level(logging.WARNING, logger="courses.geogebra"):
            with patch("courses.geogebra._open", side_effect=_slow_open):
                assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    finally:
        released.set()
    assert any("deadline" in m for m in _geogebra_reasons(caplog))


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_negative_caches_a_deadline(monkeypatch):
    # Test 3. BOTH directions race here and the fixed-build one is the dangerous
    # one: asserting call_count == 1 on a CORRECT build needs the first worker to
    # have reached _open before the post-join assertion runs. Synchronise on an
    # event rather than trusting the deadline floor -- and BOUND the wait, or a
    # never-started thread hangs the suite instead of failing it.
    monkeypatch.setattr("courses.geogebra._DEADLINE_SECONDS", 0.3)
    released, entered = threading.Event(), threading.Event()
    cls = _slow_resp_cls(released, entered)
    try:
        opener_patch = patch(
            "courses.geogebra._open",
            side_effect=lambda *a, **k: cls(_payload("wseg.json")),
        )
        with opener_patch as opener:
            assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
            assert entered.wait(5)
            assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
            assert opener.call_count == 1
    finally:
        released.set()


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_deadline_log_names_the_id_AND_the_reason(monkeypatch, caplog):
    # Test 4. Asserting the id alone would be vacuous: _fail logs "geogebra %s: %s",
    # so `lookup failed (AttributeError)` from a broken fake also names the id --
    # green on precisely the mistake this test is designated to catch.
    monkeypatch.setattr("courses.geogebra._DEADLINE_SECONDS", 0.3)
    released = threading.Event()
    resp = _slow_resp_cls(released)(_payload("wseg.json"))
    try:
        with caplog.at_level(logging.WARNING, logger="courses.geogebra"):
            with patch("courses.geogebra._open", return_value=resp):
                fetch_geogebra_dimensions("wgzr7tsu")
    finally:
        released.set()
    messages = _geogebra_reasons(caplog)
    assert any("wgzr7tsu" in m and "deadline" in m for m in messages)
```

Add `import logging` and `import threading` to the stdlib block (per Task 2 Step 1's ordering). **`from django.test import override_settings` is already imported at `tests/test_geogebra.py:9`** — every existing fetch test uses the decorator, so there is nothing to add; adding it again is an `F811` duplicate that this task's lint step would catch. `ruff format` does not sort imports — run `ruff check` (the format/lint step does) or a misordering surfaces only at Task 6.

- [x] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_geogebra.py -k "deadline or HEADERS" --verbosity=0`
Expected: **3 failed, 1 passed** — and read this carefully, because the naive expectation is wrong.

At this point `_fetch_body(request, deadline)` is already wired up (Task 2 Step 5) and these tests patch `_DEADLINE_SECONDS` to 0.3. So after the fake's 3s wait, the *next* loop-top budget check raises `_BudgetExceeded`, which escapes into the main `except Exception` and yields `_fail("lookup failed (_BudgetExceeded)")` → `(None, None)`. **No call returns `(880, 660)`.** Tests 1, 2 and 4 therefore fail on their **caplog** assertion (reason reads `lookup failed`, not `deadline`), not on the tuple.

`test_fetch_negative_caches_a_deadline` (test 3) **passes already**: `_fail` writes the sentinel either way, `entered` gets set, and `opener.call_count == 1`. It has no RED-first evidence, so **its Step 7 mutant is its only gate** — do not skip it.

- [x] **Step 3: Thread the fetch**

In `fetch_geogebra_dimensions`, inside the existing `try`, replace Task 2's three synchronous lines with the threaded form. **The ordering here is load-bearing in three places** — read the inline comments before changing anything.

```python
        budget = _DEADLINE_SECONDS  # ONE read of the global, at call time
        deadline = monotonic() + budget  # computed immediately before start()
        box = {}

        def _run():
            try:
                box["body"] = _fetch_body(request, deadline)
            except _BudgetExceeded:  # MUST precede `except Exception`
                return  # store nothing -> caller reports the deadline
            except Exception as exc:  # noqa: BLE001 - the never-raises contract
                box["exc"] = exc  # store FIRST
                try:
                    exc.close()  # then close; HTTPError only, harmless otherwise
                # the guard below: closing must never mask the original
                except Exception:  # noqa: BLE001, S110
                    pass

        thread = threading.Thread(
            target=_run, name=f"geogebra-lookup-{material_id}", daemon=True
        )
        thread.start()
        thread.join(budget)  # same value as the deadline -- no clock skew

        result = dict(box)  # ONE snapshot; never three `in` checks on a live dict
        if "exc" in result:
            raise result["exc"]  # re-raise so the handlers below run as they do today
        if "body" not in result:
            return _fail("deadline exceeded")
        body = result["body"]
        if not isinstance(body, bytes):
            # Defensive and DELIBERATELY UNTESTED, in the style of the _API_PREFIX
            # guard above: b"".join() returns bytes or raises on the worker (landing
            # in box["exc"]), so this cannot be driven. Kept because len() at the
            # oversize check sits outside this try, so being wrong would be a 500.
            # Distinct reason string -- never "deadline exceeded", or a broken fake
            # would be indistinguishable from a real deadline in tests 1/2/4/5c.
            return _fail("lookup returned a non-bytes body")
```

Add `import threading` to the module's imports — first in the stdlib block's sort order after `import re`, i.e. `import json / import logging / import re / import threading / import urllib.error / ...`.

Also extend the `_DEADLINE_SECONDS` comment now that the mechanism it names exists. Task 2 deliberately shipped it without the worker clause, because at that commit no worker existed and the comment would have described machinery that had not arrived. Replace the whole block with:

```python
# Total bound on the lookup, enforced by joining the worker thread. Deliberately
# LARGER than a single socket op so a failure in the FIRST op still surfaces as
# itself -- the blackhole/connect path times out at a measured ~3.29s and must
# keep reporting "lookup failed (timeout)" rather than racing this deadline.
_DEADLINE_SECONDS = 5
```

Three traps, each already paid for:

1. **`except _BudgetExceeded` must come first.** It subclasses `Exception`, so a broad-handler-first order puts it in `box["exc"]` and the caller reports `lookup failed (_BudgetExceeded)` instead of the deadline.
2. **Store into `box["exc"]` before closing.** If `close()` raises on a real socket and the close came first, the error is never stored, the caller reports `deadline exceeded` instead of `HTTP 4xx`, and the exception escapes via `threading.excepthook`. (`HTTPError(..., fp=None)` never calls `addinfourl.__init__`, so `close()` genuinely can raise `AttributeError`.)
3. **Compute `deadline` immediately before `start()`, from one read of the global.** Test 2's mutant is only reliably RED under this placement; computed before `_open`, the mutant's worker starts already expired and the test would pass on its own mutant.

- [x] **Step 4: Run the file**

Run: `uv run pytest tests/test_geogebra.py --verbosity=0`
Expected: **110 passed**. The six existing fetch tests are Component A's real gate — they are what pins that the box round-trip preserves today's behaviour end to end (`HTTPError` fidelity, three non-`URLError` types, the parse path, oversize detection, the negative cache, and the kill switch short-circuiting before any thread is created).

- [x] **Step 5: Falsify test 1**

Replace the threading block with Task 2 Step 5's synchronous three lines — note that `budget`/`deadline` must be **kept**, since the threading block is where they are defined and a bare `body = _fetch_body(request, deadline)` would raise `NameError` rather than failing on the assertion:

```python
        budget = _DEADLINE_SECONDS
        deadline = monotonic() + budget
        body = _fetch_body(request, deadline)
```

Run: `uv run pytest tests/test_geogebra.py -k "slow_body" --verbosity=0`
Expected: FAIL — on the caplog assertion. The mutant still returns `(None, None)` (it blocks 3s, returns the payload, then trips the budget at the next loop top and logs `lookup failed (_BudgetExceeded)`), which is exactly why the reason assertion is this test's sole discriminator.
**Edit it back by hand.** Re-run: PASS.

- [x] **Step 6: Falsify test 2**

This mutant cannot be made by editing one line — `_fetch_body` owns the `with _open(...)` block — so apply exactly this restructuring inside `fetch_geogebra_dimensions`, which wraps *only* the read:

```python
        # MUTANT: _open on the main thread, only the read on the worker.
        response = _open(request, timeout=_TIMEOUT_SECONDS)
        budget = _DEADLINE_SECONDS
        deadline = monotonic() + budget      # NOTE: computed AFTER _open, as the
        box = {}                             # real code computes it before start()

        def _run():
            try:
                chunks, total = [], 0
                while total <= _MAX_BODY_BYTES:
                    if monotonic() >= deadline:
                        raise _BudgetExceeded
                    chunk = response.read1(_CHUNK_BYTES)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                box["body"] = b"".join(chunks)
            except _BudgetExceeded:
                return
            except Exception as exc:  # noqa: BLE001
                box["exc"] = exc
```

Keeping `deadline` *after* the `_open` call is essential: computed before it, the mutant's worker would start already expired and report `deadline exceeded`, turning test 2 **green on its own mutant**.

Run: `uv run pytest tests/test_geogebra.py -k "HEADERS" --verbosity=0`
Expected: FAIL — `_open` blocks on the main thread for its full wait, the worker then starts with a fresh budget and its non-blocking `read1` returns at once, so the call yields `(880, 660)`.
**Edit it back by hand.** Re-run: PASS.

- [x] **Step 7: Falsify tests 3 and 4**

For test 3: replace `return _fail("deadline exceeded")` with a bare `return None, None`. This removes the only `"deadline exceeded"` log line, so tests 1, 2 and 4 (and 5c once Task 4 lands) also redden on their caplog assertions — the `-k` filter scopes the run to test 3.
Run: `uv run pytest tests/test_geogebra.py -k "negative_caches_a_deadline" --verbosity=0`
Expected: FAIL — no sentinel is written, so the second call also reaches `_open` and `call_count == 2`. **This is test 3's only gate** (see Step 2 — it was green before the fix), so do not skip it.

For test 4: pass `_fail` a generic reason string instead of the deadline one. Every deadline test asserts the `"deadline"` substring, so this reddens tests 1, 2 and 4 together — the `-k` filter scopes the run to test 4.
Run: `uv run pytest tests/test_geogebra.py -k "names_the_id" --verbosity=0`
Expected: FAIL — the id is still logged but the reason substring is absent.

The spec names a second mutant for test 4, "drop the log line". It is **deliberately not run here**: removing `logger.warning` from `_fail` reddens several existing tests (`test_fetch_refuses_to_guess_on_a_multi_applet_worksheet`, `test_fetch_logs_a_valid_json_non_object_body`, `test_fetch_treats_an_oversized_body_as_a_distinct_failure`), so it does not uniquely justify test 4 and its RED would be uninformative.

**Edit both back by hand.** Re-run: PASS.

- [x] **Step 8: Rewrite the three remaining comments**

These are now false or incomplete. Leaving them is the false-mechanism failure this project treats as a defect class. Use this text.

1. **`fetch_geogebra_dimensions`'s docstring** (was `:332-338`):

```python
    """The material's authored (width, height), or (None, None). All-or-nothing.

    Never raises. The transport now runs on a bounded worker thread, so the
    exceptions urlopen can produce -- RemoteDisconnected, ConnectionResetError,
    ssl.SSLError, UnicodeDecodeError, ValueError, none of them URLError
    subclasses -- no longer raise on THIS frame. The worker catches them, stores
    them in the result box, and they are re-raised here for the handlers below to
    degrade. A deadline (neither box slot set) degrades via _fail rather than
    raising. Anything escaping into clean_url would 500 the save.
    """
```

2. **The `except urllib.error.HTTPError` comment** (was `:376-378`):

```python
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx raises from inside _open ON THE WORKER, so the `with` inside
        # _fetch_body is never entered and the error's own fp is never closed. The
        # worker closes it when it stores the error (store first, then close), and
        # the main thread re-raises it here. This close stays: it is harmless on an
        # already-closed error, and without it the 400 test would surface an
        # unexplained ResourceWarning if the worker path ever changed.
```

3. **The module docstring** (`:7-14`): extend the kill-switch clause **in place**. Do not append a paragraph restating it — that would leave the clause twice with the incomplete original still standing, and would displace the `Nothing here raises` sentence, which sits in the **same paragraph** immediately after it and which item 1's docstring rewrite relies on still being stated at module level.

Replace lines 7–14 with exactly this (note the retained `Nothing here raises` sentence and the file's ``double-backtick`` markup):

```
This module is both the single GeoGebra URL parser and the single place the GeoGebra
API is called. Parsing functions rebuild recognized ``https`` inputs from scratch
(host + material id, dropping any width/height/border cruft) and return everything
else unchanged for ``validate_embed_url`` to judge; the one network function performs
a single capped GET behind the ``GEOGEBRA_API_LOOKUP`` kill switch, on a bounded
background daemon thread under a total deadline (``_DEADLINE_SECONDS``), with the body
read chunked against the same budget so an abandoned worker cannot park indefinitely.
Nothing here raises — every failure degrades to a neutral value, because these run
inside form validation and inside page render, where an exception would 500 a save or
a student unit page.

This is the repository's only production background thread. The worker's boundary
rule: NO ORM, NO cache, NO logging — it only calls ``_open``, reads bytes, and stores
into a result box; everything else stays on the main thread.
```

- [x] **Step 9: Update the architecture doc**

`docs/development/architecture.md:106` is a **shared row** covering two modules:

```
| `video_url.py` / `geogebra.py` | Embed-URL canonicalization for video / GeoGebra. |
```

So attribute the thread explicitly rather than appending to the shared cell, which would ascribe it to `video_url.py` too:

```
| `video_url.py` / `geogebra.py` | Embed-URL canonicalization for video / GeoGebra. `geogebra.py` also performs the API dimension lookup, on a bounded background thread. |
```

- [x] **Step 10: Format and lint the files this task touched**

```bash
uv run ruff format .
uv run ruff check --no-cache courses/geogebra.py tests/test_geogebra.py
```

Do this **before** the commit, not at Task 6. `ruff format` does not sort imports, and `ruff format --check` is a separate CI gate — discovering either at the end means re-touching files from several earlier commits.

- [x] **Step 11: Commit**

```bash
git add courses/geogebra.py tests/test_geogebra.py docs/development/architecture.md
git commit -m "feat(geogebra): bound the API lookup with a thread deadline

The lookup runs inside save_element's @transaction.atomic while _locked_unit
holds select_for_update() on the ContentNode row, and urllib's timeout is
per-socket-op rather than total (measured: 16.18s against a 1 byte/s peer).
The main thread now returns no later than _DEADLINE_SECONDS."
```

---

### Task 4: Falsify the worker's failure handling, and pin the shipped constants

Tasks 2–3 left two behaviours the design calls load-bearing with **no test that can fail**: 5a/5b drive `_fetch_body` in isolation and never touch `_run` or the box, and in tests 1/3 the budget trips only after the main thread has returned and its assertions have run. A build that stores `_BudgetExceeded` in `box["exc"]`, or that stores the partial body, is green in everything written so far — and pytest surfaces worker fallout only as `PytestUnhandledThreadExceptionWarning`, which `pyproject.toml:46-50` does not escalate.

**Files:**
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3. Produces: nothing consumed later.

- [ ] **Step 1: Write test 5c and the constant-relationship test**

```python
@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_reports_a_worker_budget_trip_as_the_deadline(monkeypatch, caplog):
    # 5c: the budget trips INSIDE the join window, so this is the only test that
    # exercises _run's `except _BudgetExceeded` branch and the empty-box outcome.
    #
    # Clock arithmetic -- the main thread consumes the FIRST tick computing
    # `deadline = monotonic() + budget`, so the worker's ticks are offset by one:
    #   tick 1 (main)   -> 0.0   deadline = 0.0 + 2.0 = 2.0
    #   tick 2 (check1) -> 1.0   < 2.0, read1 #1
    #   tick 3 (check2) -> 2.0   >= 2.0, raise _BudgetExceeded
    # Body is 3 chunks so read1 #1 does not hit EOF.
    monkeypatch.setattr("courses.geogebra._DEADLINE_SECONDS", 2.0)
    clock = itertools.count(start=0.0, step=1.0)
    monkeypatch.setattr("courses.geogebra.monotonic", lambda: next(clock))

    from courses.geogebra import _CHUNK_BYTES

    resp = _Resp(b"x" * (3 * _CHUNK_BYTES))
    with caplog.at_level(logging.WARNING, logger="courses.geogebra"):
        with patch("courses.geogebra._open", return_value=resp):
            assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    assert any("deadline" in m for m in _geogebra_reasons(caplog))


def test_the_deadline_clears_the_measured_connect_leg_failure():
    # Every other test patches _DEADLINE_SECONDS, so nothing else observes the
    # SHIPPED relationship. `>` alone is satisfied by 3.5, which reintroduces the
    # mislabelling: the measured blackhole/connect failure takes ~3.29s, so the
    # deadline must clear the MEASURED figure, not merely the nominal constant.
    from courses.geogebra import _DEADLINE_SECONDS
    from courses.geogebra import _TIMEOUT_SECONDS

    assert _DEADLINE_SECONDS >= _TIMEOUT_SECONDS + 1
```

- [ ] **Step 2: Run — both should PASS immediately**

Run: `uv run pytest tests/test_geogebra.py -k "budget_trip or connect_leg" --verbosity=0`
Expected: PASS. These are falsification tests for code Task 3 already wrote, not new behaviour, so RED-first does not apply. Their value is proven by the mutants in Steps 3–5, not by an initial failure.

- [ ] **Step 3: Falsify 5c — mutant one (wrong handler order)**

In `_run`, move `except _BudgetExceeded: return` *below* `except Exception as exc:`.
Run: `uv run pytest tests/test_geogebra.py -k "budget_trip" --verbosity=0`
Expected: FAIL — the logged reason becomes `lookup failed (_BudgetExceeded)`, so the `"deadline"` assertion misses.
**Edit it back by hand.** Re-run: PASS.

- [ ] **Step 4: Falsify 5c — mutant two (partial body stored)**

Change `_fetch_body` to return `b"".join(chunks)` instead of raising on budget expiry. This removes the only `raise _BudgetExceeded`, so it also reddens 5a and 5b — the `-k` filter scopes the run to 5c.
Run: `uv run pytest tests/test_geogebra.py -k "budget_trip" --verbosity=0`
Expected: FAIL — the truncated body reaches the parse path and the reason becomes `unparseable payload`.
**Edit it back by hand.** Re-run: PASS.

- [ ] **Step 5: Falsify the constant test**

Swap the two constants' values (`_TIMEOUT_SECONDS = 5`, `_DEADLINE_SECONDS = 3`).
Run: `uv run pytest tests/test_geogebra.py -k "connect_leg" --verbosity=0`
Expected: FAIL on the assertion.
**Edit both back by hand.** Re-run: PASS.

- [ ] **Step 6: Run the whole file, then format and lint**

Run: `uv run pytest tests/test_geogebra.py --verbosity=0`
Expected: **112 passed**.

```bash
uv run ruff format .
uv run ruff check --no-cache tests/test_geogebra.py
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_geogebra.py
git commit -m "test(geogebra): falsify the worker's budget-trip handling and pin the constant relationship"
```

---

### Task 5: Component B — clear the stale pair on any URL change

`clean_url` carries `and mid` **twice**: at `:196` (the stale-pair clear) and at `:217` (the lookup guard). **Only the first is removed.** Dropping the second instead would issue a live GET to `https://api.geogebra.org/v1.0/materials/?scope=basic` with an empty id on every dimensionless non-GeoGebra paste.

Note what this reverses: `tests/test_iframe_dimensions.py:498` currently pins the old behaviour with the comment *"A KNOWN, ACCEPTED gap … pinned so a future change to it is deliberate"*. This is that deliberate change.

**Files:**
- Modify: `courses/element_forms.py:189`, `:192-197` (replace the justification comment block AND the guard, not just the `if` line)
- Modify: `tests/test_iframe_dimensions.py:377-382` (comment only — see Step 3b)
- Test: `tests/test_iframe_dimensions.py:481-508` (rewrite two in place), plus one new

**Interfaces:**
- Consumes: nothing from Tasks 1–4 (fully independent — this task may be done first if preferred).
- Produces: no new symbols.

- [ ] **Step 1: Rewrite B1 and B2 in place, and add B3**

Rewrite `test_form_non_geogebra_url_change_keeps_its_dimensions` (`:481`) and `test_form_geogebra_to_non_geogebra_url_change_keeps_the_geogebra_pair` (`:498`) — name, body **and comment**; their current comments argue for the behaviour being removed. Both **retain `lookup.assert_not_called()`**: that assertion is the second guard on which `and mid` survives, and it is what distinguishes "dropped the `:196` conjunct" from "dropped both".

```python
@pytest.mark.django_db
def test_form_same_provider_url_change_clears_the_stale_pair():
    # B2. A stored pair belongs to the URL it was captured FROM. Vimeo video A ->
    # video B is the same staleness class as a provider swap: 640x360 described
    # the old video, and there is no lookup for Vimeo to re-derive the new one.
    obj = IframeElement.objects.create(
        url=OTHER_FORM_URL, title="P", width=640, height=360
    )
    form = IframeElementForm(
        data={"url": "https://player.vimeo.com/video/999", "title": "P"}, instance=obj
    )
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()  # the :217 guard still scopes the LOOKUP to GeoGebra
    assert (saved.width, saved.height) == (None, None)


@pytest.mark.django_db
def test_form_geogebra_to_non_geogebra_url_change_clears_the_stale_pair():
    # B1. Was pinned as "A KNOWN, ACCEPTED gap"; this is the deliberate change that
    # comment invited. Keeping 880x660 rendered a 16:9 video in a 4:3 box with no
    # badge -- the same pillarbox defect #238 removed, through a different door.
    #
    # frame_ratio is the load-bearing assertion. A `size_unknown is False` check
    # would NOT discriminate: size_unknown is `is_geogebra_iframe_url(url) and ...`,
    # and the new url is Vimeo, so it is False whether or not the pair was cleared.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    form = IframeElementForm(
        data={"url": OTHER_FORM_URL, "title": "P"}, instance=obj
    )
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (None, None)
    assert saved.frame_ratio is None  # -> .embed-frame's 16:9 default


@pytest.mark.django_db
def test_form_non_geogebra_unchanged_url_keeps_its_pair():
    # B3. NEW. B1 and B2 are the only two form tests using a non-GeoGebra stored
    # pair and both now assert clearing, so without this nothing pins that such a
    # pair survives an UNCHANGED url. That is this change's highest-risk failure
    # mode: url_changed is `extract_embed_url(raw) != self.instance.url`, so a
    # future non-idempotent canonicalisation for a new provider would wipe every
    # such element's pair on every save, with no lookup to restore it and no badge.
    obj = IframeElement.objects.create(
        url=OTHER_FORM_URL, title="P", width=640, height=360
    )
    form = IframeElementForm(
        data={"url": OTHER_FORM_URL, "title": "renamed"}, instance=obj
    )
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (640, 360)
```

- [ ] **Step 2: Run to verify B1 and B2 fail**

Run: `uv run pytest tests/test_iframe_dimensions.py -k "same_provider or geogebra_to_non_geogebra or unchanged_url_keeps" --verbosity=0`
Expected: B1 and B2 FAIL (the pair is still `(880, 660)` / `(640, 360)`); B3 passes already. The filter deliberately avoids the substring `clears_the_stale_pair`, which would also select the pre-existing `test_form_url_change_clears_the_stale_pair_and_looks_up_afresh` (`:425`).

- [ ] **Step 3: Drop the conjunct and rewrite both comments**

In `courses/element_forms.py`, replace `:192-197` — the whole justification comment block and the guard it introduces, not just the `if` line:

```python
        # A stored pair describes the URL it was captured from, so any URL change
        # invalidates it: drop it and let the new URL take the normal path. Not
        # scoped to GeoGebra -- a provider swap (or a same-provider video swap)
        # leaves a pair that describes an unrelated embed, which frame_ratio would
        # render as a confident, badge-less wrong ratio. Cost, accepted: a URL edit
        # on a hand-pasted non-GeoGebra embed loses the pair, and the textarea holds
        # the stored canonical URL rather than the original snippet, so restoring it
        # means re-pasting the embed code from the provider.
        if url_changed and not usable_dimensions(width, height):
            self.instance.width = self.instance.height = None
```

And at `:189`, the hoist comment now over-claims — only the lookup guard uses `mid`:

```python
        mid = geogebra_material_id(url)  # hoisted: used by the lookup guard below
```

- [ ] **Step 3b: Re-word the now-ambiguous guard comment**

`test_form_non_geogebra_dimensionless_paste_never_looks_up` (`:376`) guards the `:217` conjunct you did **not** touch. Its comment at `tests/test_iframe_dimensions.py:377-382` opens "THE guard on the `and mid` conjunct" — which named the only such conjunct when it was written, and after this change names the wrong one. This is a spec requirement, not a nicety: an ambiguous mechanism comment is the same defect class as a false one.

Replace **lines 377–378 as a unit** — not just line 377. The sentence runs on: line 377 ends "Every other form test either uses a" and line 378 begins "GeoGebra URL (lookup fires anyway)…", so replacing only the first line would orphan that clause into a fragment with no subject. Use this verbatim (already wrapped, no Markdown emphasis — this is a Python comment):

```python
    # THE guard on the `and mid` conjunct of the LOOKUP guard (element_forms.py:217);
    # the stale-pair clear above it is deliberately provider-neutral and has no `mid`.
    # Every other form test either uses a GeoGebra URL (lookup fires anyway) or
```

Lines 379 onwards ("`# short-circuits on a usable pair BEFORE`…") are unchanged.

- [ ] **Step 4: Run — all three green**

Run: `uv run pytest tests/test_iframe_dimensions.py --verbosity=0`
Expected: all pass.

- [ ] **Step 5: Falsify B1 and B2**

Restore `and mid` on the `:196` clear.
Run: `uv run pytest tests/test_iframe_dimensions.py -k "same_provider or geogebra_to_non_geogebra" --verbosity=0`
Expected: both FAIL — this is the defect itself.
**Edit it back by hand.** Re-run: PASS.

- [ ] **Step 5b: Falsify B2 with its OWN mutant**

Step 5's `and mid` restore reddens B1 and B2 together, so it does not show that B2 earns its place. The spec names a different mutant for B2 — the **provider-change rule**, the alternative this design rejected. Apply it:

```python
        # MUTANT: clear only when the HOST changes, not on any URL change.
        from urllib.parse import urlsplit

        old_host = urlsplit(self.instance.url or "").hostname or ""
        new_host = urlsplit(url or "").hostname or ""
        if old_host != new_host and not usable_dimensions(width, height):
            self.instance.width = self.instance.height = None
```

Run: `uv run pytest tests/test_iframe_dimensions.py -k "same_provider or geogebra_to_non_geogebra" --verbosity=0`
Expected: **B2 FAILS, B1 stays green.** B1 is a cross-host swap (geogebra.org → player.vimeo.com) so the mutant still clears it; B2 is `player.vimeo.com` → `player.vimeo.com`, so the pair survives and B2 reddens. That asymmetry is the whole reason B2 exists: it is the test that distinguishes the chosen any-URL-change rule from the rejected provider-change one.

**Edit the mutant back by hand.** Re-run: PASS.

- [ ] **Step 6: Falsify B3**

Apply exactly this mutant — it also clears when the URL is unchanged but the element is not GeoGebra:

```python
        if (url_changed or not mid) and not usable_dimensions(width, height):
```

Run: `uv run pytest tests/test_iframe_dimensions.py --verbosity=0`
Expected: **only B3 fails.** B1, B2, `:293`, `:304`, `:376`, `:410`, `:425`, `:437` and `:468` all stay green — that is what makes B3 uniquely justified.

**Two look-alike mutants that are NOT this one**, and why:
- `if not usable_dimensions(...) and not mid` (drop `url_changed`, scope to non-GeoGebra) *also* reddens `:425`: `not mid` blocks the clear on a GeoGebra→GeoGebra change, the pair survives, `stored_usable` stays `True`, the `:217` guard never fires and `assert lookup.call_count == 1` fails.
- `if url_changed and not usable_dimensions(...) and not mid` (scoping inversion alone) leaves B3 **green**, because B3's URL is unchanged so the clear is never reached — running it would wrongly suggest B3 is vacuous.

**Edit the mutant back by hand.** Re-run: PASS.

- [ ] **Step 7: Format and lint the files this task touched**

```bash
uv run ruff format .
uv run ruff check --no-cache courses/element_forms.py tests/test_iframe_dimensions.py
```

Do this **before** the commit, not at Task 6. `ruff format` does not sort imports, and `ruff format --check` is a separate CI gate — discovering either at the end means re-touching files from several earlier commits.

- [ ] **Step 8: Commit**

```bash
git add courses/element_forms.py tests/test_iframe_dimensions.py
git commit -m "fix(iframe): clear a stored dimension pair on any URL change

The clear was gated on the NEW url being a GeoGebra material, so swapping a
GeoGebra element to a Vimeo or YouTube one kept the applet's 880x660 and
rendered a 16:9 video in a 4:3 box with no badge. Reverses a gap #238 pinned
as deliberate."
```

---

### Task 6: Whole-branch gate

The only wide sweep in this plan. Everything above ran narrowly.

**Files:** none modified (fix-forward only if something reddens).

- [ ] **Step 1: Confirm the database this worktree actually uses is up**

**Superseded in part by the Global Constraints:** since Task 1 this worktree runs against `test_libli_gg` on **55433** (`libli-test-db`) via the `TEST_DATABASE_URL` prefix, not the 5432 default — because a concurrent worktree occupies `test_libli` on 5432. So verify **`libli-test-db` (55433)** is healthy, and use the prefix for this step's full-suite run. The paragraph below describes the no-prefix default and is retained for the record.

With no `.env` in the worktree there is **no `TEST_DATABASE_URL`**, so the suite connects to the `base.py` default on **port 5432** — the `bonnot-postgres` container — *not* the tuned `libli-test-db` on 55433 that normal main-repo runs use. Checking the wrong container is worse than not checking: it reports "healthy", the gate says proceed, and the run hangs for ~4 minutes.

Run: `docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'`
Expected: a container publishing **5432** and healthy (`bonnot-postgres` at the time of writing).

If you would rather run against the tuned server for parity with normal runs, copy `.env` into the worktree first — `cp ../../libli/.env .` from the worktree root — and then verify `libli-test-db` instead. Either is fine; what is not fine is verifying one and running against the other.

- [ ] **Step 2: Full unit suite**

Run: `uv run pytest --verbosity=0`
Expected: all pass, with **9 more tests than the branch point** (8 in `test_geogebra.py`, 1 in `test_iframe_dimensions.py`; B1 and B2 are rewritten in place and do not change the count).

Compare against the figure captured in **Task 1 Step 0**. Both sides must be the same measurement — a *selected-collection* count, taken the same way:

```bash
uv run pytest --collect-only --verbosity=0 | tail -1
```

That prints e.g. `5974/6886 tests collected (912 deselected) in 72.76s`. **Read the LEFT-hand number** (5974): the right-hand one includes the 912 deselected e2e tests. Do **not** compare it against the `N passed` line from Step 2's run — that excludes deselected tests *and* runtime skips (`tests/test_db_quiesce.py:153` skips conditionally), so the delta would not be 9 for two independent reasons.

Do **not** background this run — a backgrounded pytest that is reaped mid-run orphans the test database and the next run dies with `DuplicateDatabase`.

- [ ] **Step 3: Lint and format**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
```

Expected: both clean. `--no-cache` is required: a cached run reports "All checks passed" for a file that warned on a previous run. `ruff format --check` is a separate CI gate from `ruff check`.

- [ ] **Step 4: Confirm no migration was implied**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected". This change touches no model field.

- [ ] **Step 5: Draft the PR body from the spec's accepted gaps**

The spec has a section headed "Accepted gaps, to be recorded in the PR body" and names the PR body as their delivery surface. The commit messages carry only a fraction. Write the PR body to `docs/superpowers/plans/pr-body-geogebra-lookup-followups.md` in the worktree so it survives a session boundary, covering **all** of:

- the lock is **still held** during the lookup, now for up to `_DEADLINE_SECONDS`; de-locking is the named follow-up PR and is out of scope here
- the orphan bound is **conditional** — ~8s once response headers have arrived; a peer dribbling the handshake or headers parks the worker inside `_open`, bounded only by `http.client`'s `_MAXLINE`/`_MAXHEADERS`
- no cap on concurrent lookup threads, deliberately; the ceiling is distinct dimensionless materials pasted within one orphan lifetime, and nothing makes it observable
- a late-arriving body is discarded (cache writes are main-thread only)
- the negative cache is **per-process** — no `CACHES` outside `config/settings/test.py:19`, so `LocMemCache` applies; hypothetical, since there is no deployment
- a deadline appears **once per material per 60s**: the cache-hit short-circuit is unlogged, so the symptom of the sticky suppression is silence, not repetition
- `daemon=True` and the `isinstance(bytes)` guard are deliberately untested, per the file's existing "cannot be driven, cannot be falsified" convention
- Component B **reverses a decision #238 pinned as deliberate** (`tests/test_iframe_dimensions.py:498`'s "A KNOWN, ACCEPTED gap … pinned so a future change to it is deliberate") — say so plainly rather than presenting it as a fresh bug fix
- Component B's known cost: a URL edit on a hand-pasted non-GeoGebra embed loses the pair, with no badge and no lookup to restore it, and the textarea holds the canonical URL rather than the original snippet
- finding 3 from the original review (the ws-level `settings` block) is **dropped as unverified** — the fixture cited as evidence pins the opposite, and `wseg.json` shows the top-level read is load-bearing
- **thread creation and thread abandonment are different rates** — one thread is created per lookup that reaches the network, but a thread is only *abandoned* when the deadline actually fires; the common case leaves nothing parked
- **prior design docs are left as historical record** — #238's spec and plan document the GeoGebra-scoped clear and its accepted gap; they are not annotated or amended, and this spec supersedes them
- `docs/development/architecture.md:106` gets its one-line update (done in Task 3 Step 9) — note it here so the PR body reflects the full change surface

- [ ] **Step 6: Commit any gate fixes**

Step 5 always produces a **new, untracked** file, so this commit is unconditional and `git add -u` alone is not enough (it stages only tracked paths):

```bash
git add docs/superpowers/plans/pr-body-geogebra-lookup-followups.md
git add -u
git commit -m "chore(geogebra): branch gate fixes and PR body"
```

---

## Self-Review

**Spec coverage.** Component A: `_CHUNK_BYTES`/`_DEADLINE_SECONDS`/`monotonic` import → Task 2 Step 3; `_BudgetExceeded` + `_fetch_body` read1 loop → Task 2 Step 4; `_run` handler order, store-then-close, deadline placement, `dict(box)` snapshot, `isinstance` guard, named daemon thread → Task 3 Step 3; four comment rewrites → Task 2 Step 3 (`:46-53`) and Task 3 Step 8 (the other three); `architecture.md` → Task 3 Step 9. Component B: conjunct + two comments → Task 5 Step 3. Tests: 1–4 → Task 3; 5a/5b → Task 2; 5c + constant relationship → Task 4; B1/B2/B3 → Task 5; existing-fetch-test regression gate → Task 3 Step 4; `_Resp` hoist → Task 1.

**Deliberately not implemented, per the spec:** `daemon=True` is untested (no test can distinguish it from `daemon=False` without asserting on the `Thread` object); the `isinstance(bytes)` guard is untested (unreachable by construction). Both are recorded as such in the code comments the plan mandates, matching the file's existing `_API_PREFIX` convention. De-locking the fetch is **out of scope** — it is a named follow-up PR.

**Type consistency.** `_fetch_body(request, deadline)` takes two arguments everywhere it appears (Task 2 Steps 1/4/5, Task 3 Step 3 and Step 5's mutant). `_Resp(body)` takes the body positionally in Tasks 1, 2, 3 and 4. `monotonic` is the bare module-local name in production and in every patch target.

**Placeholders:** none. Every code step carries the code; every test step carries the assertion and the mutant, including the two that require restructuring rather than a one-line edit (Task 3 Step 6, Task 5 Step 5b) and the replacement text for all four comment rewrites.

**PR body:** the spec's **eleven** accepted-gap bullets, plus three notes cross-referenced from other spec sections (the once-per-60s silence, the deliberately-untested `daemon=True`/`isinstance` pair, and the #238-reversal framing), are delivered by Task 6 Step 5 and written to a file in the worktree so they survive a session boundary. Cross-check against the spec's section before committing — three were missed across the first two passes.
