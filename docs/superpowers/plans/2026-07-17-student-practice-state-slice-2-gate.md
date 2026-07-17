# Student practice state — slice 2 (the reveal gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the plain "Show more" reveal gate the first lesson element whose state survives a page reload — it saves `{"open": true}` on click and re-cascades on load.

**Architecture:** A per-type validator (`courses/state.py`) normalizes the gate's blob; the render seam (`ElementBase._state_context`) serializes each leaf's blob to a `data-state` attribute; the gate template emits it on its existing `<button>`; and `reveal.js` grows a document-order, per-scope, prefix-closed restore pass plus a fire-and-forget save. The server save endpoint, the `element_state` field, and `build_lesson_context`'s read are untouched — slice 1 (PR #139) built them generically.

**Tech Stack:** Django (server-rendered templates, no JSON template filter), vanilla ES5 IIFE JS (no module system, no JS test runner), pytest + Playwright e2e. Package manager: `uv` (bash `ruff`/`pytest`/`python` are NOT on PATH — always `uv run`).

## Global Constraints

- **No migration.** The `element_state` field exists (slice 1). `uv run python manage.py makemigrations --check` must stay clean.
- **No new element type.** `ELEMENT_MODELS` does not change (keeps the `len(ELEMENT_MODELS)` count-asserts untriggered).
- **No new user-visible strings** → no `makemessages`, no `.po` work.
- **Registry key space is the content-type `model` string** — `"revealgateelement"`, NOT the form key `revealgate` and NOT the transfer key `reveal_gate`. The gate is one of seven nestable types whose form and transfer keys diverge (`builder.py:58-66`); only the `model` string belongs in `VALIDATORS`.
- **Per-worktree test DB:** run pytest with `DATABASE_URL` pointing at a worktree-unique database (e.g. `.../libli_slice2gate`; the role has CREATEDB) — concurrent worktrees collide on `test_libli`.
- **Heavy suite: `-n auto`.** Serial exceeds a subagent's 600s watchdog.
- **e2e needs explicit `-m e2e`** or `addopts = -q -m 'not e2e'` deselects the file and pytest exits 5 **looking like success**. Run focused e2e **foreground only, never backgrounded** (a backgrounded `-m e2e` leaves runaway browsers).
- **DoD (final gate):** full non-e2e suite green; `uv run ruff check` **and** `uv run ruff format --check`; `makemigrations --check`; `uv run python manage.py check`; and the three e2e files that cover `cascadeFrom` (`test_e2e_reveal_gate.py`, `test_e2e_fillgate.py`, `test_e2e_switchgate.py`) green.

Spec: `docs/superpowers/specs/2026-07-17-student-practice-state-slice-2-gate-design.md`.

---

## File structure

| File | Change | Task |
|---|---|---|
| `courses/state.py` | add `_val_revealgate`, register `"revealgateelement"` | 1 |
| `courses/tests/test_state_module.py` (**EXISTS — append**, the `_val_markdone` test home) | reveal-gate validator cases | 1 |
| `courses/tests/test_element_state_endpoint.py` (**EXISTS — append**) | endpoint round-trip test | 1 |
| `courses/views.py:402` | `"state"` → `"element_state"` | 2 |
| `courses/templatetags/courses_extras.py:67` | `context.get("state")` → `context.get("element_state")` | 2 |
| `courses/models.py:1157`, `:1265` | container re-inject key rename | 2 |
| `courses/tests/test_markdone_render.py:169,177` | context-key read rename | 2 |
| `courses/tests/test_markdone_render.py` | NEW two-column mark-done state guard test | 2 |
| `courses/models.py` (`_state_context`, `:340-361`) | `import json`, add `mine_json`, docstring | 3 |
| `templates/courses/elements/revealgateelement.html` | three attributes on the `<button>` + `{% url %}` | 3 |
| `courses/tests/test_reveal_gate_render.py` (**EXISTS — append, never overwrite**) | data-state round-trip, `{}` unseeded, chain, eid | 3 |
| `courses/static/courses/js/reveal.js` | `focus` option, `storedOpen`, `restoreGates`, `BARRIER`/`RESTORABLE`, `save`, wire; comment fix `:7-8` | 4 |
| `templates/courses/manage/editor/editor.html:139-143` | correct the false preview-inertness comment | 5 |
| `tests/test_e2e_reveal_gate.py` | feature e2e (Task 4); walk / fail-safe / editor-preview e2e + fixtures (Task 5) | 4, 5 |

---

## Task 1: Reveal-gate validator

**Files:**
- Modify: `courses/state.py` (append `_val_revealgate`; add one key to `VALIDATORS`)
- Test: `courses/tests/test_state_module.py` (append the reveal-gate validator tests beside `_val_markdone`'s) and `courses/tests/test_element_state_endpoint.py` (endpoint round-trip)

**Interfaces:**
- Consumes: `EMPTY`, `REJECT` sentinels and the `VALIDATORS` dict (slice 1, `courses/state.py`); the `element_state_save` endpoint (slice 1, `courses/views.py`).
- Produces: `VALIDATORS["revealgateelement"]` — a `validate(element, obj, payload) -> {"open": True} | EMPTY | REJECT`. Consumed by the endpoint's `validate_state` dispatch; no other task imports it directly.

- [ ] **Step 1: Write the failing validator tests**

**Append to `courses/tests/test_state_module.py` — the EXISTING validator-test home** (it holds the `_val_markdone` tests, imported as `from courses import state`; it does NOT import `pytest` as `state_svc`). `courses/tests/test_element_state.py` does **not** exist and must **not** be created — that would fragment the validator suite. Reuse the module's `from courses import state` alias.

The reveal validator ignores `element`/`obj` (it only shape-checks the payload), so calling it directly with `None, None` is correct and simpler than the DB-object style the mark-done tests use:

```python
import pytest


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"open": True}, {"open": True}),
        ({"open": True, "x": 1}, {"open": True}),   # extra keys normalized away
    ],
)
def test_val_revealgate_stores_open(payload, expected):
    assert state._val_revealgate(None, None, payload) == expected


@pytest.mark.parametrize("payload", [{"open": False}, {}, {"other": 1}])
def test_val_revealgate_empty(payload):
    # A well-formed "nothing to restore" DROPS the key -- EMPTY, never REJECT.
    assert state._val_revealgate(None, None, payload) is state.EMPTY


@pytest.mark.parametrize("payload", ["nope", 3, None, ["open"]])
def test_val_revealgate_rejects_non_dict(payload):
    assert state._val_revealgate(None, None, payload) is state.REJECT


def test_revealgate_registered_under_model_key():
    assert state.VALIDATORS["revealgateelement"] is state._val_revealgate
```

(`import pytest` is likely already at the top of the module — check before adding a duplicate.)

- [ ] **Step 2: Run to verify failure**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/test_state_module.py -q`
Expected: FAIL — `AttributeError: module 'courses.state' has no attribute '_val_revealgate'` (and the registry KeyError).

- [ ] **Step 3: Implement the validator and register it**

In `courses/state.py`, add above the `VALIDATORS` dict:

```python
def _val_revealgate(element, obj, payload):
    """{"open": True} -- monotone.

    A false/absent `open` is a well-formed "nothing to restore" -> EMPTY (drop the key),
    never REJECT (which would preserve a stale key on a well-formed request).
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"open": True} if payload.get("open") else EMPTY
```

Then add the one new key to the existing `VALIDATORS` dict — **keep the namespace comment above it**:

```python
# Keyed by content_type.model (the ELEMENT_MODELS namespace) -- NOT the form key
# ("markdone") and NOT the transfer key ("mark_done"). Those three namespaces have
# been a recurring trap; the registry does not add a fourth.
VALIDATORS = {
    "markdoneelement": _val_markdone,
    "revealgateelement": _val_revealgate,   # NEW -- the only line this slice adds here
}
```

- [ ] **Step 4: Run validator tests to verify pass**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/test_state_module.py -q`
Expected: PASS.

- [ ] **Step 5: Add and run the endpoint round-trip test**

Add to `courses/tests/test_element_state_endpoint.py`. The module's `_setup()` returns a **MarkDone** row, so it cannot be reused for a gate — add a gate-specific setup mirroring its shape (it already imports `_post`, `add_element`, `Enrollment`/`make_course_with_unit`, and force-login; follow whatever the file uses):

```python
def _setup_gate():
    from courses.models import RevealGateElement
    # mirror _setup(): enrolled student + lesson unit + a RevealGateElement join row
    course, unit = make_course_with_unit()
    student = make_verified_user()                       # the helper _setup() actually uses
    Enrollment.objects.create(student=student, course=course)
    gate = RevealGateElement.objects.create(label="Show more")
    row = add_element(unit, gate)
    return course, unit, row, student


def test_revealgate_state_round_trips(client):
    course, unit, row, student = _setup_gate()
    client.force_login(student)

    r = _post(client, course, unit, {"element": row.pk, "state": {"open": True}})
    assert r.status_code == 200
    assert r.json() == {"element": row.pk, "state": {"open": True}}

    # {"open": False} drops the key -> echoes {}
    r = _post(client, course, unit, {"element": row.pk, "state": {"open": False}})
    assert r.status_code == 200 and r.json()["state"] == {}
```

Read the module's actual `_setup()` first and match its login/enrollment idiom exactly — the shape above is the contract, not the verbatim helper names.

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/test_element_state_endpoint.py -q`
Expected: PASS (the endpoint already dispatches on `content_type.model`; registration is the whole wiring).

- [ ] **Step 6: Commit**

```bash
git add courses/state.py courses/tests/test_state_module.py courses/tests/test_element_state_endpoint.py
git commit -m "feat(state): register reveal-gate validator (open -> {open: true})"
```

---

## Task 2: Ambient context-key rename `state` → `element_state`

**Files:**
- Modify: `courses/views.py:402`, `courses/templatetags/courses_extras.py:67`, `courses/models.py:1157`, `courses/models.py:1265`
- Modify (tests): `courses/tests/test_markdone_render.py:169,177`
- Test: `courses/tests/test_markdone_render.py` (new two-column guard test)

**Interfaces:**
- Consumes: `build_lesson_context` (slice 1), `render_element` (slice 1), `TabsElement.render` / `TwoColumnElement.render` (slice 1).
- Produces: the lesson context key `element_state` (was `state`); `render_element` reads `context.get("element_state")`. Task 3's `_state_context` receives it via the unchanged `render(state=…)` **kwarg** (the kwarg name does NOT change).

**Why:** `render_element` reads the practice-state map off the ambient template context under the generic key `state`, which already collides with `views_review.py:98`'s `submission_review_state` binding. Inert today (that page renders no elements) but silent. `slug`/`node_pk` are deliberately NOT renamed — they have no demonstrated collision (see spec §3).

- [ ] **Step 1: Add the failing two-column guard test**

The Tabs re-inject (`models.py:1157`) is already guarded by `test_nested_in_tabs_checklist_resolves_checked`. The TwoColumn re-inject (`models.py:1265`) has **no** guard, and `mark_done` is nestable in a column, so a missed rename silently renders saved ticks unticked. Add to `courses/tests/test_markdone_render.py` (mirror `test_nested_in_tabs_checklist_resolves_checked`, but **read the minted column id back — never hardcode it**, because `TwoColumnElement.default_data()` mints ids with `secrets`):

```python
def test_nested_in_two_column_checklist_resolves_checked(client):
    # Guards models.py:1265 (TwoColumnElement.render's element_state re-inject).
    from courses.models import TwoColumnElement

    student = make_login(client, "stu2c")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    cid = col.data["columns"][0]["id"]          # minted by secrets -- never hardcode
    parent = Element.objects.create(unit=unit, content_object=col)
    el, (i1, i2) = _markdone()
    row = Element.objects.create(
        unit=unit, content_object=el, parent=parent, tab_id=cid
    )
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )

    body = client.get(_lesson_url(course, unit)).content.decode()

    assert f'name="element" value="{row.pk}"' in body
    assert "checked" in body
    assert "markdone__item on" in body
```

- [ ] **Step 2: Run the new test — it should PASS today** (the code still binds `state`, and the re-inject still works). This is a **guard-first** test: verify it is not vacuous by temporarily changing `models.py:1265`'s `"state": state` to `"state": {}` and confirming it goes RED, then revert.

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/test_markdone_render.py::test_nested_in_two_column_checklist_resolves_checked -q`
Expected: PASS (with the guard intact); RED (with `models.py:1265` sabotaged). Revert the sabotage before continuing.

- [ ] **Step 3: Rename the four production sites**

`courses/views.py:402`: `"state": state,` → `"element_state": state,`
`courses/templatetags/courses_extras.py:67`: `state=context.get("state"),` → `state=context.get("element_state"),`
`courses/models.py:1157` (inside `TabsElement.render`'s `render_to_string` dict): `"state": state,` → `"element_state": state,`
`courses/models.py:1265` (inside `TwoColumnElement.render`'s dict): `"state": state,` → `"element_state": state,`

- [ ] **Step 4: Rename the two context-key test reads**

`courses/tests/test_markdone_render.py:169` and `:177`: `build_lesson_context(unit, student)["state"]` → `build_lesson_context(unit, student)["element_state"]`. **Do NOT** touch `test_element_state_endpoint.py`'s `r.json()["state"]` reads — that is the wire format, unchanged.

- [ ] **Step 5: Run the markdone render suite**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/test_markdone_render.py courses/tests/test_render_seam.py -q`
Expected: PASS — including the existing tabs guard and the new two-column guard, which now prove both re-injects survived the rename.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/templatetags/courses_extras.py courses/models.py courses/tests/test_markdone_render.py
git commit -m "refactor(courses): rename ambient render context key state -> element_state"
```

---

## Task 3: Render seam `mine_json` + reveal-gate template attributes

**Files:**
- Modify: `courses/models.py` (`_state_context`, `:340-361`) — `import json`, docstring, `mine_json`
- Modify: `templates/courses/elements/revealgateelement.html`
- Test: `courses/tests/test_reveal_gate_render.py` (new module, or add to an existing reveal-gate render test file)

**Interfaces:**
- Consumes: `_state_context` (slice 1), the `element_state` context key (Task 2), `courses:element_state_save` URL (slice 1).
- Produces: every base-rendered leaf's context now carries `mine_json = json.dumps(mine)`; `revealgateelement.html` emits `data-element-pk`, `data-state`, `data-state-url` on its `<button>`. Task 4's `reveal.js` reads all three (`btn.dataset.elementPk`, `btn.dataset.state`, `btn.dataset.stateUrl`).

- [ ] **Step 1: Write the failing render tests**

**`courses/tests/test_reveal_gate_render.py` ALREADY EXISTS — APPEND, do not Create/overwrite.** It holds three pre-existing tests (`test_render_button_hidden_with_marker`, `test_render_custom_label`, `test_no_reveal_armed_no_hidden_blocks` — the last a fail-open guard) that MUST still pass after Task 3. They do: `.render()` with no args yields `save_url=""` and `mine_json="{}"`, so the button still ships `hidden` with an inert `data-state`. Never open this file with the Write tool.

**Reuse the file's OWN existing helpers — it already defines `lesson_url(unit)` (single-arg, derives `unit.course`) and imports `make_student` from `tests.factories`.** Do NOT introduce `make_login`/`_lesson_url` here (those are `test_markdone_render.py`'s names; mixing them makes two divergent login/URL helpers in one module). In each new test below, the enrolled-student + unit setup is:

```python
    from tests.factories import make_student
    student = make_student(client, "rg_render")
    course, unit = make_course_with_unit()          # or the file's existing unit helper
    Enrollment.objects.create(student=student, course=course)
```

and read the body with the file's `lesson_url(unit)` (single-arg), NOT `_lesson_url(course, unit)`. Confirm `make_course_with_unit` is imported in this module (it is used by the sibling render tests); if not, import it or reuse the unit-construction the file already does.

```python
import json
import re

import pytest

from courses.models import Element, RevealGateElement, UnitProgress
# plus the module's course/unit/enrollment helpers


def _seed_gate(unit, student, blob):
    gate = RevealGateElement.objects.create(label="Show more")
    row = Element.objects.create(unit=unit, content_object=gate)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row


def test_data_state_round_trips_as_json(client, ...):
    # Seed a NON-EMPTY blob, or the |safe / repr falsifications below stay green.
    student, course, unit = ...  # enrolled student + lesson unit
    row = _seed_gate(unit, student, {"open": True})
    body = client.get(lesson_url(unit)).content.decode()
    m = re.search(r'data-state="([^"]*)"', body)
    assert m, "no data-state attribute rendered"
    import html
    assert json.loads(html.unescape(m.group(1))) == {"open": True}


def test_data_state_renders_empty_when_unseeded(client, ...):
    student, course, unit = ...
    row = _seed_gate(unit, student, None)
    body = client.get(lesson_url(unit)).content.decode()
    assert 'data-state="{}"' in body


def test_gate_attributes_on_the_button_no_wrapper(client, ...):
    # The CSS + isGateWrapper require the button as a DIRECT child of .lesson-block__body.
    student, course, unit = ...
    row = _seed_gate(unit, student, {"open": True})
    body = client.get(lesson_url(unit)).content.decode()
    assert re.search(r'<div class="lesson-block__body">\s*<button[^>]*data-reveal-gate', body)


def test_eid_provenance(client, ...):
    student, course, unit = ...
    row = _seed_gate(unit, student, {"open": True})
    body = client.get(lesson_url(unit)).content.decode()
    assert f'data-element-pk="{row.pk}"' in body
```

- [ ] **Step 2: Run to verify failure**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/test_reveal_gate_render.py -q`
Expected: FAIL — no `data-state` / `data-element-pk` attribute in the rendered gate.

- [ ] **Step 3: Add `mine_json` to `_state_context`**

In `courses/models.py`, add `import json` to the import block (there is none today). **The stdlib imports are alphabetized (`import re`, `import secrets`, …), so `import json` goes ABOVE `import re`** — misplacing it fails `uv run ruff check` at the DoD. Then edit `_state_context` (`:340-361`). Replace the docstring and add `mine_json` to the returned dict:

```python
    def _state_context(self, element, state, slug, node_pk):
        """{el, eid, mine, mine_json, slug, node_pk} -- the leaf contract.

        `mine_json` is json.dumps(mine), for a leaf to emit as data-state. Serialized
        HERE, in Python: there is no JSON filter in this project, and `{{ mine }}` would
        render Python's repr ({'open': True}), which JSON.parse rejects.

        Every leaf gets it whether or not it reads one -- the gate is the only consumer
        today. A leaf that hand-builds its own render_to_string context instead of
        splatting this (the Table/Gallery pattern) forfeits it silently.

        NOT `checked`: mark-done-only, added by ElementBase.render below.

        `eid == 0` means "a content object with no join row" (transient/mid-create),
        NOT "editor preview" -- the preview passes REAL join rows and is made inert
        by its context lacking slug/node_pk (so `{% url ... as save_url %}` -> "").
        """
        eid = element.pk if element is not None else 0
        mine = (state or {}).get(eid)
        if not isinstance(mine, dict):
            mine = {}  # read-side fail-open: drifted blob -> render fresh, never 500
        return {
            "el": self,
            "eid": eid,
            "mine": mine,
            "mine_json": json.dumps(mine),
            "slug": slug,
            "node_pk": node_pk,
        }
```

- [ ] **Step 4: Add the three attributes to the gate template**

Edit `templates/courses/elements/revealgateelement.html` — the `{% url … as save_url %}` on line 2 and three attributes on the **existing** `<button>` (NO wrapper element):

```django
{% load i18n %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
<button type="button" class="reveal-gate" data-reveal-gate hidden
        data-element-pk="{{ eid }}" data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
  <span>{% if el.label %}{{ el.label }}{% else %}{% trans "Show more" %}{% endif %}</span>
  <svg class="reveal-gate__chevron" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
    <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6"
          stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
</button>
```

Do NOT add `|safe` — Django's autoescape of `"` → `&quot;` round-trips correctly through `dataset.state`.

- [ ] **Step 5: Run the render tests to verify pass**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/test_reveal_gate_render.py -q`
Expected: PASS.

- [ ] **Step 6: Verify no other leaf broke** (all six base-rendered leaves now carry `mine_json`):

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest courses/tests/ -q -k "render or markdone"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/models.py templates/courses/elements/revealgateelement.html courses/tests/test_reveal_gate_render.py
git commit -m "feat(courses): render gate state as data-state; _state_context gains mine_json"
```

---

## Task 4: `reveal.js` client restore + save + the feature e2e

**Files:**
- Modify: `courses/static/courses/js/reveal.js` (the whole client change; comment fix `:7-8`)
- Test: `tests/test_e2e_reveal_gate.py` (new feature e2e)

**Interfaces:**
- Consumes: `data-element-pk` / `data-state` / `data-state-url` from Task 3; the endpoint from Task 1; existing `scopeOf`, `ownWrapper`, `isGateWrapper`, `initRevealGates`, `cascadeFrom` (`reveal.js`).
- Produces: `restoreGates(root)` (un-exported), `storedOpen(btn)`, `save(btn)`, and `cascadeFrom(el, {focus: false})` restore mode. No later task imports these — Task 5 only adds e2e against them.

**Note on TDD here:** this project has **no JS test runner**, so the failing test that drives this task is the **feature e2e**. Write it, watch it fail (no restore/save yet), implement `reveal.js`, watch it pass.

- [ ] **Step 1: Write the failing feature e2e**

Add to `tests/test_e2e_reveal_gate.py` (uses existing `_new_unit`, `_gate`, `_text`, `add_element`, `_login`, `_unit_url`). The click and reload MUST be separated by an awaited response, or the test is flaky (`save()` is fire-and-forget):

```python
@pytest.mark.django_db(transaction=True)
def test_gate_state_survives_reload(page, live_server):
    """Click the real gate -> state POST -> reload -> content still revealed AND the
    gate button is gone (the only coverage of the restore call's {hideWrapper: true})."""
    student, unit = _new_unit("rg_persist")
    add_element(unit, _text("<p>intro</p>"))
    add_element(unit, _gate("Reveal"))
    add_element(unit, _text("<p>secret block</p>"))
    _login(page, live_server, "rg_persist")
    page.goto(_unit_url(live_server, unit))

    # REAL click; await the /state/ POST before reloading.
    with page.expect_response(lambda r: "/state/" in r.url and r.request.method == "POST"):
        page.get_by_role("button", name="Reveal").click()

    page.reload()

    # After reload: the secret block is revealed, and the gate button is consumed.
    assert page.get_by_text("secret block").is_visible()
    assert page.get_by_role("button", name="Reveal").count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest tests/test_e2e_reveal_gate.py::test_gate_state_survives_reload -m e2e -q`
Expected: FAIL — after reload the block is hidden again (no restore) and/or no POST fires (no save). Run FOREGROUND only.

- [ ] **Step 3: Add the `focus` option to `cascadeFrom`**

In `reveal.js`, edit `cascadeFrom` (`:70`). Add `var focus = opts.focus !== false;` near the top, and an early `return` placed AFTER the `hideWrapper` block and BEFORE the focus-target resolution:

```javascript
  function cascadeFrom(triggerEl, opts) {
    opts = opts || {};
    var hideWrapper = opts.hideWrapper !== false;
    var focus = opts.focus !== false;   // NEW
    var scope = scopeOf(triggerEl);
    if (!scope) return;
    var gateWrap = ownWrapper(triggerEl, scope);
    if (!gateWrap) return;

    var node = gateWrap.nextElementSibling;
    var lastRevealed = null;
    while (node) {
      node.classList.add("reveal-shown");
      node.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      lastRevealed = node;
      if (isGateWrapper(node, scope)) break;
      node = node.nextElementSibling;
    }

    if (hideWrapper) {
      gateWrap.classList.remove("reveal-shown");
      gateWrap.hidden = true;
    }

    if (!focus) return;   // NEW: restore skips focus-target resolution ENTIRELY
    // ... existing focus block unchanged ...
```

A real click passes no `focus`, so `opts.focus !== false` is `true` and today's behaviour is byte-for-byte unchanged.

- [ ] **Step 4: Add `csrf`, `storedOpen`, and `save`**

Add near the top of the IIFE (duplicate `markdone.js:5-8`'s 4-line `csrf`; each JS file is a self-contained IIFE):

```javascript
  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function storedOpen(btn) {
    try {
      var raw = btn.dataset.state;
      if (!raw) return false;
      var blob = JSON.parse(raw);
      return !!(blob && blob.open === true);   // strict shape, not truthiness
    } catch (e) {
      return false;   // drifted blob -> this gate simply stays live
    }
  }

  function save(btn) {
    var url = btn.dataset.stateUrl;
    if (!url) return;                       // editor preview: "" -> no-op
    var eid = parseInt(btn.dataset.elementPk, 10);
    if (!eid) return;                       // pk 0 == content object with no join row
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ element: eid, state: { open: true } }),
      keepalive: true,                      // survives unload
    }).catch(function () {});               // monotone: keep the DOM, ignore the body
  }
```

- [ ] **Step 5: Wire `save` into the click handler**

Edit `initOne` (`:124`): the click handler both cascades and saves:

```javascript
    btn.addEventListener("click", function () { reveal(btn); save(btn); });
```

- [ ] **Step 6: Add `BARRIER`/`RESTORABLE` constants and `restoreGates`, and fix the `:7-8` comment**

Fix `reveal.js:7-8` first — replace `"Setting this eagerly, at parse time, is what lets that fallback see the engine is alive."` with: the IIFE runs after parsing and before `DOMContentLoaded`, which is what lets the watchdog see the engine is alive.

Declare the constants **above** `initRevealGates`'s definition (hoisting hazard: they are read by a function invoked at parse-end). In `initRevealGates` (`:139`), change `var sel = "button.reveal-gate[data-reveal-gate]";` to **`var sel = RESTORABLE;`** — keep the local `sel` so both usages at `:140` (`scope.matches(sel)`) and `:141` (`querySelectorAll(sel)`) stay bound; only the literal moves to the shared constant. Then add `restoreGates`:

```javascript
  // RESTORABLE replaces initRevealGates's inline `sel`: ONE definition of "a plain gate",
  // read by both init and restore. MUST be assigned above initRevealGates and its call.
  var BARRIER    = "[data-reveal-gate]";                   // all three gate families
  var RESTORABLE = "button.reveal-gate[data-reveal-gate]"; // the plain gate only

  function restoreGates(root) {
    // `ctx`, NOT `scope`: in this file "scope" means scopeOf()'s return. NO self-match
    // branch, deliberately -- restore is document-only and never exported, so `root`
    // can never itself be a gate.
    var ctx = root || document;
    var gates = Array.prototype.slice.call(ctx.querySelectorAll(BARRIER));

    // GROUP by scopeOf. Null-scope gates are dropped here and never bucketed.
    var scopes = [], buckets = [];
    gates.forEach(function (gate) {
      var scope = scopeOf(gate);
      if (!scope) return;                                  // (b) null-scope: never walked
      var i = scopes.indexOf(scope);
      if (i === -1) { scopes.push(scope); buckets.push([gate]); }
      else { buckets[i].push(gate); }
    });

    // WALK each bucket in document order; `break` ends ONLY this bucket.
    buckets.forEach(function (bucket, bi) {
      var scope = scopes[bi];
      for (var j = 0; j < bucket.length; j++) {
        var gate = bucket[j];
        try {
          if (!isGateWrapper(ownWrapper(gate, scope), scope)) continue;  // (a) mis-scoped
          if (!gate.matches(RESTORABLE)) break;            // fill/switch gate: a barrier
          if (!storedOpen(gate)) break;                    // closed gate: prefix-closure
          cascadeFrom(gate, { hideWrapper: true, focus: false });
        } catch (e) {
          break;                                           // unknown state: stop THIS scope
        }
      }
    });
  }
```

- [ ] **Step 7: Call `restoreGates` after `initRevealGates`, with the verbatim ordering comment**

At the tail of the IIFE, keep the two `window.*` exports, and change the bottom to:

```javascript
  window.libliInitRevealGates = initRevealGates;
  window.libliRevealCascade = cascadeFrom;
  // ORDER IS LOAD-BEARING, and it is the only thing guarding this: init MUST run first
  // so that even an uncaught throw inside restore leaves every gate un-hidden and
  // click-bound -- the student re-earns the content instead of being locked out of it.
  // There is no test for this (nothing in restore can throw once the null-scope discard
  // is in place); this comment is the guard. Do not reorder these two lines.
  initRevealGates(document);
  restoreGates(document);   // NEW -- restoreGates is NOT exported (editor.js:77 must not reach it)
```

- [ ] **Step 8: Run the feature e2e to verify pass**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest tests/test_e2e_reveal_gate.py::test_gate_state_survives_reload -m e2e -q`
Expected: PASS. Foreground only.

- [ ] **Step 9: Confirm the seven pre-existing reveal e2e still pass** (this task edits the shared cascade engine):

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest tests/test_e2e_reveal_gate.py -m e2e -q`
Expected: PASS — all pre-existing tests + the new one. Foreground only.

- [ ] **Step 10: Commit**

```bash
git add courses/static/courses/js/reveal.js tests/test_e2e_reveal_gate.py
git commit -m "feat(reveal): client restore + fire-and-forget save for the show-more gate"
```

---

## Task 5: Walk edge-case, fail-safe, and editor-preview e2e coverage

**Files:**
- Modify: `templates/courses/manage/editor/editor.html:139-143` (correct the false comment)
- Test: `tests/test_e2e_reveal_gate.py` (four new fixture helpers + the falsification-heavy e2e)

**Interfaces:**
- Consumes: everything from Task 4 (`restoreGates`, the walk, `save`, `cascadeFrom` focus mode); existing helpers `_gate`, `_text`, `_seed_tab1_gate`.
- Produces: no production code (comment fix aside) — pure test coverage. Four new fixture helpers: `_fillgate(author_stem)`, an editor harness, a per-tab tabs seeder, a two-column seeder.

**All e2e drive the REAL gesture — never `page.evaluate` for the gesture under test.** Seeding `UnitProgress.element_state` directly in the DB is setup, not a bypassed gesture (the gesture under test is the reload). Each test is falsified on the way in per the spec's falsifiability table (delete the guard → confirm RED → restore).

- [ ] **Step 1: Add the four fixture helpers**

`_fillgate` — mirror `tests/test_e2e_fillgate.py:98-105`:

```python
def _fillgate(author_stem):
    from courses.fillblank import parse
    from courses.models import FillGateElement

    token_stem, blanks = parse(author_stem)
    return FillGateElement.objects.create(stem=token_stem, answers=blanks)
```

Editor harness — mirror `tests/test_e2e_editor_view_toggle.py:24-56` (`seed_roles()` + PLATFORM_ADMIN, `CourseFactory(slug=…, owner=pa)`, an `_editor_url`). Per-tab tabs seeder — mirror `tests/test_e2e_tabs.py:93`'s `_seed_tabs_element(unit, tabs, children)`. Two-column seeder — **read the minted id back**:

```python
def _seed_two_column_gate(unit, col_children):
    from courses.models import Element, TwoColumnElement

    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    cid = col.data["columns"][0]["id"]          # minted by secrets -- never hardcode
    parent = Element.objects.create(unit=unit, content_object=col)
    for child in col_children:
        Element.objects.create(unit=unit, content_object=child, parent=parent, tab_id=cid)
    return parent, cid
```

- [ ] **Step 2: Write the walk / fail-safe e2e**

Add these tests (seed `element_state = {str(join_pk): {"open": True}}` for "stored-open" gates). Each asserts on `.reveal-shown` class presence/absence, NOT `to_be_visible()` (inactive tab panels carry the `hidden` attribute → false RED):

- **Barrier enumeration:** a TOP-LEVEL unanswered fill-gate above a stored-open plain gate → no block past the plain gate carries `.reveal-shown`. Falsify: change `querySelectorAll(BARRIER)` → `RESTORABLE` → RED.
- **Prefix-closure:** gate2 stored open behind a closed gate1 → gate1 is a live gate, no block past gate2 carries `.reveal-shown`. Falsify: `break` → `continue` in the `storedOpen` line → RED.
- **Across scopes:** gate closed in tab panel 1, gate stored open in panel 2 → panel 2's `.tabs__child` carries `.reveal-shown`. Falsify: flatten the bucketing into one `for` with one `break` → RED. (Uses the per-tab tabs seeder.)
- **Two-column:** a stored-open gate inside a column → the two-column element is NOT hidden, and a top-level stored-open gate later in the slide still restores. Falsify: remove the `isGateWrapper` `continue` → RED.
- **Column-nested fill-gate does not veto** a later top-level stored-open gate. Falsify: change the `isGateWrapper` `continue` → `break` → RED.
- **Boot-restore moves neither focus nor scroll:** after a restore-only load, `expect(page.locator("body")).to_be_focused()` and `page.evaluate("window.scrollY") == 0`. **Seed the gate below the fold** (enough preceding blocks) so the scroll assertion can fail. Falsify: default `opts.focus` to `false` → RED.
- **Drifted `data-state`:** seed `element_state = {str(join_pk): {"open": "yes"}}` (the only reachable drift) → the gate button is visible and clickable, no following block carries `.reveal-shown`, clicking it then reveals. Falsify: relax `blob.open === true` to truthiness → RED. (Do NOT assert "content visible" — that is RED on correct code.)
- **JS blocked → content visible:** confirm `test_watchdog_unhides_when_reveal_js_blocked` still passes (pre-existing; regression only).

- [ ] **Step 3: Write the two editor-preview e2e**

- **Tab-nested preview gate:** non-null scope, `data-state="{}"` → does not cascade. Falsify: default `mine_json` to a stored-open blob → RED.
- **Preview gate CLICK sends no request:** click a real gate in the preview, assert NO request to `.../state/` AND none to the editor's own URL (`save_url == ""`; without the guard `fetch("")` hits the current page). Falsify: delete `if (!url) return;` → RED.

- [ ] **Step 4: Correct the editor.html comment**

Edit `templates/courses/manage/editor/editor.html:139-143` — the `{% comment %}` block wrongly says *"the cascade is inert here (no .slide/[data-tab-panel] scope in the preview)."* A tabs element in the preview DOES emit `[data-tab-panel]`. Rewrite the parenthetical to say the preview's inertness rests on `data-state="{}"` — and, for top-level gates only, the absent scope.

- [ ] **Step 5: Run the new e2e (foreground) and falsify each**

Run: `DATABASE_URL=postgres:///libli_slice2gate uv run pytest tests/test_e2e_reveal_gate.py -m e2e -q`
Expected: PASS. Then, for each new walk/preview test, delete the guard named in its bullet, confirm RED, restore. A test that stays green with its guard deleted is deleted.

- [ ] **Step 6: Run the full DoD**

```bash
# non-e2e suite
DATABASE_URL=postgres:///libli_slice2gate uv run pytest -n auto -q
# the three e2e files that cover cascadeFrom (foreground)
DATABASE_URL=postgres:///libli_slice2gate uv run pytest tests/test_e2e_reveal_gate.py tests/test_e2e_fillgate.py tests/test_e2e_switchgate.py -m e2e -q
uv run ruff check
uv run ruff format --check
uv run python manage.py makemigrations --check
uv run python manage.py check
```

Expected: all green; `makemigrations --check` reports no changes.

- [ ] **Step 7: Commit**

```bash
git add tests/test_e2e_reveal_gate.py templates/courses/manage/editor/editor.html
git commit -m "test(reveal): walk, fail-safe, and editor-preview e2e for gate restore"
```

---

## Notes for the executor

- **The falsifiability discipline is not optional.** For every walk/preview e2e in Task 5, delete the single guard it names, confirm RED, restore. Six distinct "test that cannot fail" traps were caught in spec review; the discipline is what prevents a seventh.
- **Exempt guards get no test** (spec's falsifiability table): the null-scope discard, `storedOpen`'s `try`/`catch`, the `matches(RESTORABLE)` barrier line, the per-gate `catch`, `restoreGates`'s non-export, `save()`'s `if (!eid) return;`, `keepalive: true`, and `libli:reveal` firing. Do not write a test that pretends to cover any of them.
- **Never hardcode a two-column column id** — `default_data()` mints them with `secrets`. Read `col.data["columns"][0]["id"]` back after `save()`. A hardcoded id orphans the child and makes both column tests pass vacuously.
- **e2e foreground only**, `-m e2e`, per-worktree `DATABASE_URL`.
