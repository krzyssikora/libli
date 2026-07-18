# Step-by-step Stepper Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and restore how far a student has walked the Step-by-step stepper, so a reload restores the revealed depth instead of snapping back to step 0.

**Architecture:** Ride the merged practice-state substrate (PR #140/#150). A new count-valued validator `_val_stepper` normalizes `{"shown": N}` on save; the stepper template emits the three practice-state data-attributes the base render already provides; `stepper.js` reads the count at boot and reveals the first N steps, and saves the new count on each "Show next" click via the shared `window.libliState.saveFlag`. One template gate fix loads `state.js` for stepper-only lessons.

**Tech Stack:** Django 5, server-rendered templates, vanilla JS (no build step), pytest + pytest-django, Playwright (e2e), `uv` for all tooling.

## Global Constraints

- **Tooling is only reachable via `uv run`** — `ruff`/`pytest`/`python` are not on PATH. Prefix every command with `uv run`.
- **Non-e2e suite runs with xdist:** `uv run pytest -m "not e2e" -n auto` (serial exceeds the stream watchdog). e2e is deselected by default `addopts`.
- **e2e runs foreground, single file, explicit marker:** `uv run pytest tests/test_e2e_stepper.py -m e2e` — NEVER a background or whole-suite `-m e2e` run (runaway browsers).
- **No new user-facing strings.** `_val_stepper` returns sentinels/dicts with no `gettext`; the template reuses the existing `{% trans "Show next" %}`. Do not run `makemessages`; if it is run, it must introduce zero `#, fuzzy` entries (the project-wide `test_po_catalog_clean` fails on any fuzzy).
- **Falsifiability doctrine:** every guard test must be shown to go RED when its guard is removed, not merely pass. Do this for each new test before moving on.
- **No migration.** `UnitProgress.element_state` already stores an opaque per-element blob keyed by the `Element` join-row pk; `element_state_save` and the reset flow are unchanged.
- **Clean gates at DoD:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run python manage.py makemigrations --check --dry-run`, `uv run python manage.py check` all clean.

---

### Task 1: `_val_stepper` validator + registration

**Files:**
- Modify: `courses/state.py` (add `_val_stepper`; add `"stepperelement"` to `VALIDATORS`)
- Test: `courses/tests/test_state_module.py` (append stepper cases)

**Interfaces:**
- Consumes: `courses.state.EMPTY`, `courses.state.REJECT`, `courses.state._int_or_none`, `courses.state.validate_state` (existing); `StepperElement`/`StepperStep` models; `obj.steps.count()` (`related_name="steps"`).
- Produces: `courses.state._val_stepper(element, obj, payload) -> dict | EMPTY | REJECT`; registry entry `VALIDATORS["stepperelement"] = _val_stepper`. Blob shape `{"shown": int}` where `2 <= shown <= obj.steps.count()`.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_state_module.py` (module already imports `pytest`, `state`, `add_element`, `make_course_with_unit`; add the two model imports at the top with the others):

```python
from courses.models import StepperElement
from courses.models import StepperStep


def _mk_stepper(n):
    _course, unit = make_course_with_unit()
    obj = StepperElement.objects.create(prompt="P")
    for i in range(n):
        StepperStep.objects.create(stepper=obj, content=f"s{i}")
    el = add_element(unit, obj)
    return el, obj


def test_val_stepper_stores_clamped_count():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 2}) == {"shown": 2}


def test_val_stepper_clamps_to_step_count():
    # A stored value above the count stores the count, not the input (self-heal).
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 9}) == {"shown": 3}


def test_val_stepper_below_two_is_EMPTY():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 1}) is state.EMPTY
    assert state.validate_state(el, obj, {"shown": 0}) is state.EMPTY


def test_val_stepper_non_dict_is_REJECT():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, ["nope"]) is state.REJECT


def test_val_stepper_absent_or_non_numeric_shown_is_REJECT():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {}) is state.REJECT
    assert state.validate_state(el, obj, {"shown": "abc"}) is state.REJECT


def test_val_stepper_float_shown_is_floored_not_rejected():
    # int() floors 2.9 -> 2 (consistent with _val_markdone); NOT REJECT.
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 2.9}) == {"shown": 2}


def test_val_stepper_single_step_never_restores():
    el, obj = _mk_stepper(1)
    assert state.validate_state(el, obj, {"shown": 5}) is state.EMPTY


def test_stepper_registered():
    assert state.VALIDATORS["stepperelement"] is state._val_stepper
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_state_module.py -k stepper -q`
Expected: FAIL — `AttributeError: module 'courses.state' has no attribute '_val_stepper'` and `KeyError: 'stepperelement'`.

- [ ] **Step 3: Implement the validator + registration**

In `courses/state.py`, add after `_val_done` (before the `VALIDATORS` dict):

```python
def _val_stepper(element, obj, payload):
    """{"shown": N} -- how many steps the student has walked open (step 0 is always
    visible, so a fresh stepper is N=1). The FIRST count-valued blob in the registry.

    Clamped to obj.steps.count() so a later author edit that removes steps self-heals
    (a too-large stored N -> all steps shown). N<2 is a well-formed "nothing to restore"
    (only step 0, which is the default render) -> EMPTY, never REJECT. Writes are
    order-sensitive (a count, not the gates' idempotent flag); the race is accepted at
    human click cadence -- see the spec.
    """
    if not isinstance(payload, dict):
        return REJECT
    n = _int_or_none(payload.get("shown"))
    if n is None:
        return REJECT
    n = min(n, obj.steps.count())
    return {"shown": n} if n >= 2 else EMPTY
```

Then add the registry entry inside `VALIDATORS`, after `"guessnumberelement": _val_done,`:

```python
    "stepperelement": _val_stepper,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_state_module.py -k stepper -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Falsify the clamp guard**

Temporarily change `n = min(n, obj.steps.count())` to `n = n`. Run the same command; `test_val_stepper_clamps_to_step_count` and `test_val_stepper_single_step_never_restores` must FAIL. Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/state.py courses/tests/test_state_module.py
git commit -m "feat(stepper-restore): _val_stepper count validator + registration"
```

---

### Task 2: Template data-attributes + lesson-page `state.js` load gate

**Files:**
- Modify: `templates/courses/elements/stepperelement.html` (emit the three data-attrs on `.stepper`)
- Modify: `templates/courses/lesson_unit.html:76` (add `has_stepper` to the `state.js` load condition)
- Test: create `tests/test_stepper_restore.py` (lesson-view render tests)
- Test: `tests/test_lesson_stepper_wiring.py` (append a `state.js`-inclusion test)

**Interfaces:**
- Consumes: the base `ElementBase.render` context (`eid`, `mine_json`, `slug`, `node_pk`) already splatted into `stepperelement.html`; the `courses:element_state_save` url; the `has_stepper` lesson-context flag. (The read/restore path passes a stored `{"shown": N}` blob through `_state_context` **unchanged** — it does NOT invoke `_val_stepper`; the validator is exercised only by the Task 3 save round-trip, so these render tests do not depend on Task 1.)
- Produces: `.stepper` wrapper carrying `data-element-pk`, `data-state` (the `{"shown": N}` JSON, or `{}`), `data-state-url` — the attributes `stepper.js` reads in Task 3.

- [ ] **Step 1: Write the failing render tests**

Create `tests/test_stepper_restore.py`:

```python
"""Stepper restore render tests (student-practice-state). Behavioural assertions
go through the LESSON VIEW (str-keyed UnitProgress seed), never obj.render() with a
str key -- the int/str-key seam. See courses.state._val_stepper."""

import html
import json
import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import StepperElement
from courses.models import StepperStep
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_stepper(unit, student, n_steps, blob):
    obj = StepperElement.objects.create(prompt="P")
    for i in range(n_steps):
        StepperStep.objects.create(stepper=obj, content=f"s{i}")
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


def test_stored_shown_renders_data_state(client):
    student = make_student(client, "stp_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_stepper(unit, student, 4, {"shown": 3})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'class="stepper"[^>]*data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"shown": 3}
    assert "data-element-pk=" in body
    assert "data-state-url=" in body


def test_unseeded_stepper_renders_empty_state(client):
    student = make_student(client, "stp_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_stepper(unit, student, 3, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert re.search(r'class="stepper"[^>]*data-state="\{\}"', body)
```

- [ ] **Step 2: Write the failing `state.js`-inclusion test**

Append to `tests/test_lesson_stepper_wiring.py` (the module's `_body` helper already builds a stepper-only lesson):

```python
def test_lesson_loads_state_js_for_stepper():
    # A stepper-only lesson must load state.js (window.libliState.saveFlag), not
    # only stepper.js. Guards the has_stepper addition to the state.js load gate.
    assert "courses/js/state.js" in _body(pytest.importorskip("django.test").Client())
```

- [ ] **Step 3: Run both to verify they fail**

Run: `uv run pytest tests/test_stepper_restore.py tests/test_lesson_stepper_wiring.py::test_lesson_loads_state_js_for_stepper -q`
Expected: FAIL — the render tests find no `data-state` on `.stepper`; the wiring test finds no `state.js` (a stepper-only lesson is not in the current gate).

- [ ] **Step 4: Add the data-attributes to the stepper template**

Replace the first **two** lines of `templates/courses/elements/stepperelement.html` — the `{% load i18n %}` line and the `<div class="stepper" data-stepper>` open-tag line — with these three lines (the `{% load i18n %}`, the new `{% url ... as save_url %}` line, and the widened `<div>` open tag). The existing prompt line and everything below it stay put:

```django
{% load i18n %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
<div class="stepper" data-stepper data-element-pk="{{ eid }}" data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
```

Leave the rest of the file (prompt, `stepper__line`, steps loop, `stepper__next` button, closing `</div>`) unchanged. Note `mine_json` is emitted WITHOUT `|safe` (it is already JSON from Python); in the editor preview `slug`/`node_pk` are absent so `save_url` resolves to `""` (inertness).

- [ ] **Step 5: Add `has_stepper` to the `state.js` load gate**

In `templates/courses/lesson_unit.html`, line 76, change the condition from:

```django
{% if has_reveal_gate or has_fill_gate or has_switch_gate or has_switch_grid or has_fill_table or has_guess_number %}<script src="{% static 'courses/js/state.js' %}" defer></script>{% endif %}
```

to append `or has_stepper`:

```django
{% if has_reveal_gate or has_fill_gate or has_switch_gate or has_switch_grid or has_fill_table or has_guess_number or has_stepper %}<script src="{% static 'courses/js/state.js' %}" defer></script>{% endif %}
```

- [ ] **Step 6: Run both to verify they pass**

Run: `uv run pytest tests/test_stepper_restore.py tests/test_lesson_stepper_wiring.py -q`
Expected: PASS (render tests + all wiring tests).

- [ ] **Step 7: Falsify the gate guard**

Temporarily remove `or has_stepper` from line 76. Run `uv run pytest tests/test_lesson_stepper_wiring.py::test_lesson_loads_state_js_for_stepper -q`; it must FAIL. Revert.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/elements/stepperelement.html templates/courses/lesson_unit.html tests/test_stepper_restore.py tests/test_lesson_stepper_wiring.py
git commit -m "feat(stepper-restore): emit practice-state attrs + load state.js for steppers"
```

---

### Task 3: `stepper.js` restore-on-boot + save-on-click, proven by e2e

**Files:**
- Modify: `courses/static/courses/js/stepper.js` (read the count at boot; save on click)
- Test: `tests/test_e2e_stepper.py` (append a restore e2e and an editor-preview inertness e2e)

**Interfaces:**
- Consumes: the `.stepper` data-attributes from Task 2 (`data-state`, `data-state-url`, `data-element-pk`); `window.libliState.saveFlag(container, stateObj)` from `state.js` (generic: POSTs `{element, state}` to `container.dataset.stateUrl`, no-ops on empty url/pk); the Task 1 validator (so the click-save round-trips).
- Produces: no new JS globals; preserves `window.__stepperBooted` and `window.libliInitStepper`. Boot reveals the first `min(shown, total)` steps; click reveals the next step, focuses it, and saves the new count. Note: the old explicit `steps.length < 2` early-out is intentionally **folded** into the `if (shown >= steps.length) { btn.hidden = true; return; }` check (a 1-step stepper yields `shown=1 >= 1` → button hidden) — do not look for a literal `steps.length < 2` guard in the rewritten code.

- [ ] **Step 1: Write the failing restore e2e**

Append to `tests/test_e2e_stepper.py`. First add a step-count-parametrized seed helper (the existing `_seed_stepper` hardcodes 3 steps):

```python
def _seed_stepper_n(username, slug, n):
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import StepperElement
    from courses.models import StepperStep
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    el = StepperElement.objects.create(prompt="")
    for i in range(n):
        StepperStep.objects.create(stepper=el, content=f"s{i}")
    Element.objects.create(unit=unit, content_object=el)
    return course, unit


@pytest.mark.django_db(transaction=True)
def test_stepper_state_survives_reload(live_server, page):
    """Walk two steps -> state POST -> reload -> first 3 steps restored, 4th still
    hidden, button still visible (the mid-walk restore branch)."""

    def _is_state_post(r):
        return "/state/" in r.url and r.request.method == "POST"

    course, unit = _seed_stepper_n("stpreload", "stepper-reload", 5)
    _login(page, live_server, "stpreload")
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{url}")
    steps = page.locator(".stepper__step")
    btn = page.locator(".stepper__next")
    # Await EACH click's fire-and-forget /state/ POST before the next action.
    # Awaiting only the second click races the first ({shown:2}) write, which under
    # threaded LiveServerThread can commit last and leave stored=2 -> flaky RED.
    with page.expect_response(_is_state_post):
        btn.click()  # reveal step 1 (shown=2); await its POST
    with page.expect_response(_is_state_post):
        btn.click()  # reveal step 2 (shown=3); await its POST before reloading
    page.reload()
    # After reload: first three steps visible, 4th hidden, button still visible.
    assert steps.nth(0).is_visible()
    assert steps.nth(1).is_visible()
    assert steps.nth(2).is_visible()
    assert not steps.nth(3).is_visible()
    assert btn.is_visible()
```

- [ ] **Step 2: Write the failing editor-preview inertness e2e**

Also append to `tests/test_e2e_stepper.py` (imports for the PA helpers):

```python
def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    from tests.factories import make_verified_user

    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


@pytest.mark.django_db(transaction=True)
def test_editor_preview_stepper_click_sends_no_post(live_server, page):
    """In the editor preview save_url is "" -> a Show-next click POSTs nothing and
    raises no pageerror (saveFlag no-ops on empty stateUrl)."""
    from courses.models import Element
    from courses.models import StepperElement
    from courses.models import StepperStep
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    pa = _make_pa_user("stp_ed")
    course = CourseFactory(slug="stepper-ed", owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    el = StepperElement.objects.create(prompt="")
    for c in ("a", "b", "c"):
        StepperStep.objects.create(stepper=el, content=c)
    Element.objects.create(unit=unit, content_object=el)

    posts = []
    errors = []
    page.on(
        "request",
        lambda r: posts.append(r.url)
        if "/state/" in r.url and r.method == "POST"
        else None,
    )
    page.on("pageerror", lambda e: errors.append(str(e)))

    _login(page, live_server, "stp_ed")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/")
    preview_btn = page.locator('[data-scope="preview"] .stepper__next')
    preview_btn.wait_for(state="visible")
    preview_btn.click()

    assert errors == [], f"unexpected pageerror(s): {errors}"
    assert posts == [], f"editor preview must not POST state: {posts}"
```

- [ ] **Step 3: Run both e2e to verify they fail**

Run: `uv run pytest tests/test_e2e_stepper.py -m e2e -k "survives_reload or sends_no_post" -q`
Expected: FAIL — with current `stepper.js` no click fires a `/state/` POST (save not implemented), so the first `expect_response` times out; and even past that, after reload only step 0 is shown.

- [ ] **Step 4: Implement restore + save in `stepper.js`**

Replace the entire body of `courses/static/courses/js/stepper.js` with:

```javascript
(function () {
  "use strict";
  // Eager boot flag read by lesson_unit.html's DOMContentLoaded watchdog: if this
  // script never boots (blocked/404) the watchdog removes `stepper-armed` so the
  // full chain shows (fail-open). Set at parse time, like reveal.js.
  window.__stepperBooted = true;

  function shownCount(steps) {
    var n = 0;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].classList.contains("stepper-shown")) n++;
    }
    return n;
  }

  function restoreCount(root, total) {
    // Inline read of the {shown:N} blob -- storedFlag can't read a count. A missing
    // or non-integer `shown` (the fresh `{}` case) stays 1: never NaN, never 0 steps.
    var n = 1;
    try {
      var blob = JSON.parse(root.dataset.state || "{}");
      var parsed = parseInt(blob.shown, 10);
      if (parsed > 1) n = Math.min(parsed, total);
    } catch (e) {}
    return n;
  }

  function initOne(root) {
    // Idempotent: the editor preview re-runs this after each fragment swap.
    if (root.dataset.stepperReady === "1") return;
    root.dataset.stepperReady = "1";
    var steps = Array.prototype.slice.call(
      root.querySelectorAll("[data-stepper-step]")
    );
    if (!steps.length) return;
    // Restore: reveal the first N steps (N>=1). Boot only toggles classes -- it must
    // NOT call .focus()/scroll (that stays exclusive to user clicks below).
    var shown = restoreCount(root, steps.length);
    for (var i = 0; i < shown; i++) steps[i].classList.add("stepper-shown");
    root.classList.add("is-stepping");
    var btn = root.querySelector("[data-stepper-next]");
    if (!btn) return;
    if (shown >= steps.length) {
      btn.hidden = true; // nothing left to reveal
      return;
    }
    btn.hidden = false;
    btn.addEventListener("click", function () {
      var next = null;
      for (var i = 0; i < steps.length; i++) {
        if (!steps[i].classList.contains("stepper-shown")) {
          next = steps[i];
          break;
        }
      }
      if (!next) return;
      next.classList.add("stepper-shown");
      if (!next.hasAttribute("tabindex")) next.setAttribute("tabindex", "-1");
      next.focus();
      var count = shownCount(steps);
      // Fire-and-forget; no-ops in the editor preview (empty data-state-url).
      window.libliState.saveFlag(root, { shown: count });
      if (count >= steps.length) btn.hidden = true;
    });
  }

  function initStepper(root) {
    var scope = root || document;
    var sel = "[data-stepper]";
    if (scope.matches && scope.matches(sel)) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(sel), initOne);
  }

  window.libliInitStepper = initStepper;
  initStepper(document); // self-boot (lesson page + editor initial load)
})();
```

- [ ] **Step 5: Run both e2e to verify they pass**

Run: `uv run pytest tests/test_e2e_stepper.py -m e2e -k "survives_reload or sends_no_post" -q`
Expected: PASS.

- [ ] **Step 6: Run the full stepper e2e file (no regression to the existing reveal test)**

Run: `uv run pytest tests/test_e2e_stepper.py -m e2e -q`
Expected: PASS — including the pre-existing `test_stepper_reveals_one_at_a_time` (fresh stepper still shows step 0 + walks).

- [ ] **Step 7: Falsify the restore**

Temporarily change `var shown = restoreCount(root, steps.length);` to `var shown = 1;`. Run `uv run pytest tests/test_e2e_stepper.py -m e2e -k survives_reload -q`; it must FAIL (only step 0 restored). Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/stepper.js tests/test_e2e_stepper.py
git commit -m "feat(stepper-restore): restore revealed steps on boot, save count on click"
```

---

## Definition of Done

Run from the worktree root with `uv run`:

- [ ] Non-e2e suite green: `uv run pytest -m "not e2e" -n auto` (exit 0, 0 failed).
- [ ] Stepper e2e green (foreground, single file): `uv run pytest tests/test_e2e_stepper.py -m e2e`.
- [ ] `uv run ruff check .` clean.
- [ ] `uv run ruff format --check .` clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` reports no changes.
- [ ] `uv run python manage.py check` clean.
- [ ] PO catalogs fuzzy-free (no new strings were added): `uv run pytest -k po_catalog -q` green.
