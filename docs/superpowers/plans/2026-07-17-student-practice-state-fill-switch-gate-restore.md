# Fill-in-&-confirm and Choose-&-confirm restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a student's correctly-answered *Fill in & confirm* and *Choose & confirm* gates survive a page reload — the revealed content **and** the answered-and-locked widget — by bringing both onto slice 2's client-restore substrate.

**Architecture:** The blob stays the monotone `{"open": true}` the plain gate already uses. `reveal.js`'s restore walk (built in slice 2) cascades the following content; the locked *appearance* is rendered server-side from the element's own known answer (gated on the stored open flag), so no answer or verdict is stored. Each widget's JS gains a one-shot save-on-correct and a boot-time "skip arming" branch.

**Tech Stack:** Django (server-rendered templates + template tags), vanilla ES5 IIFE JS (no module system, no JS test runner — behavioural JS coverage is Playwright e2e), pytest, Playwright.

## Global Constraints

- **No new migration.** The `UnitProgress.element_state` field exists (slice 1). `uv run python manage.py makemigrations --check` must stay clean.
- **No new element type.** `ELEMENT_MODELS` does not change — the `len(ELEMENT_MODELS)` / `ELEMENT_MODELS[-1]` count-asserts in `tests/test_transfer_schema.py` and `tests/test_models_multigrid.py` must not be touched.
- **No new user-visible strings** — no `makemessages` pass. `test_po_catalog_clean` must stay green.
- **The blob is monotone `{"open": true}` only.** No free-text, no verdict, no answer stored in the blob.
- **Tooling runs via `uv run`** (`ruff`, `pytest`, `python` are NOT on PATH in bash). DoD requires `uv run ruff check`, `uv run ruff format --check`, and `uv run python manage.py check`.
- **Heavy suite: `uv run pytest -n auto`** (serial exceeds a subagent's 600s watchdog).
- **e2e needs `-m e2e`** — otherwise `addopts = -q -m 'not e2e'` deselects the file and pytest exits **5, looking like success**. Run focused e2e **foreground only, never backgrounded** (a backgrounded `-m e2e` leaves runaway browsers).
- **Isolate the test DB per worktree:** set `DATABASE_URL=…/libli_<slug>` in the worktree `.env` (the role has CREATEDB). Concurrent worktrees collide on `test_libli`; the symptom is *errors, not failures*.
- **Verify the main checkout with `git status`** before claiming it is untouched — subagents can write outside their stated cwd.

## File map

- `courses/state.py` — rename `_val_revealgate` → `_val_open_gate`; register `fillgateelement` + `switchgateelement`. (Task 1)
- `courses/tests/test_state_module.py` — rename 4 references; add a family-registration test. (Task 1)
- `courses/models.py` — add `FillGateElement.canonical_answers` property. (Task 2)
- `courses/fillblank.py` — `render_inputs` gains a `locked` mode. (Task 3)
- `courses/templatetags/courses_extras.py` — `render_fill_blanks` forwards `locked`; `render_switch_gate` gains `mine`/`mine_json`/`save_url`, emits `data-state`/`data-state-url`, renders the locked (bounds-safe) appearance. (Tasks 3, 5)
- `templates/courses/elements/fillgateelement.html` — `data-state`/`data-state-url` on the barrier `<div>`; locked render when open. (Task 4)
- `templates/courses/elements/switchgateelement.html` — pass `mine mine_json save_url` to the tag. (Task 5)
- `courses/static/courses/js/reveal.js` — walk restores all three families (`hideWrapper` per family). (Task 6)
- `courses/static/courses/js/fillgate.js` — save-on-correct + boot skip-arm + `preventDefault`-only handler. (Task 7)
- `courses/static/courses/js/switchgate.js` — save-on-correct + boot skip-arm + `typesetMath`. (Task 8)
- New tests: `courses/tests/test_fillblank_locked.py` (Task 3), `courses/tests/test_fillgate_restore.py` (Tasks 2, 4), `courses/tests/test_switchgate_restore.py` (Task 5). e2e added to `tests/test_e2e_fillgate.py` (Tasks 6, 7) and `tests/test_e2e_switchgate.py` (Task 8).

---

### Task 1: Register both gate families under the monotone validator

**Files:**
- Modify: `courses/state.py:61-78`
- Modify (test): `courses/tests/test_state_module.py:76-99`

**Interfaces:**
- Produces: `state._val_open_gate(element, obj, payload) -> {"open": True} | EMPTY | REJECT` (renamed from `_val_revealgate`, same behaviour). `state.VALIDATORS` keys `"revealgateelement"`, `"fillgateelement"`, `"switchgateelement"` all map to it.

- [ ] **Step 1: Update the tests first (rename refs + add registration test)**

**Replace `courses/tests/test_state_module.py` lines 76-99 in full** — the whole block from the `@pytest.mark.parametrize` above `test_val_revealgate_stores_open` through the final `test_revealgate_registered_under_model_key` — with the block below (which carries its own `@pytest.mark.parametrize` decorators). This renames all four `state._val_revealgate` references to `state._val_open_gate`, renames the three `test_val_revealgate_*` functions to `test_val_open_gate_*`, and broadens the registration test to all three families. Do not leave the old decorators or function names behind.

```python
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"open": True}, {"open": True}),
        ({"open": True, "x": 1}, {"open": True}),  # extra keys normalized away
    ],
)
def test_val_open_gate_stores_open(payload, expected):
    assert state._val_open_gate(None, None, payload) == expected


@pytest.mark.parametrize("payload", [{"open": False}, {}, {"other": 1}])
def test_val_open_gate_empty(payload):
    # A well-formed "nothing to restore" DROPS the key -- EMPTY, never REJECT.
    assert state._val_open_gate(None, None, payload) is state.EMPTY


@pytest.mark.parametrize("payload", ["nope", 3, None, ["open"]])
def test_val_open_gate_rejects_non_dict(payload):
    assert state._val_open_gate(None, None, payload) is state.REJECT


def test_open_gate_registered_for_all_three_families():
    for key in ("revealgateelement", "fillgateelement", "switchgateelement"):
        assert state.VALIDATORS[key] is state._val_open_gate
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_state_module.py -q`
Expected: FAIL — `AttributeError: module 'courses.state' has no attribute '_val_open_gate'`.

- [ ] **Step 3: Rename the function and register the two new keys**

In `courses/state.py`, rename `_val_revealgate` to `_val_open_gate`, broaden its docstring, and add the two keys:

```python
def _val_open_gate(element, obj, payload):
    """{"open": True} -- monotone. Shared by every answered/clicked reveal gate
    (plain, fill, switch): a correct answer or a click is the whole gesture, and
    the blob has exactly one reachable value.

    A false/absent `open` is a well-formed "nothing to restore" -> EMPTY (drop the key),
    never REJECT (which would preserve a stale key on a well-formed request).
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"open": True} if payload.get("open") else EMPTY


# Keyed by content_type.model (the ELEMENT_MODELS namespace) -- NOT the form key
# and NOT the transfer key. Those three namespaces have been a recurring trap; the
# registry does not add a fourth.
VALIDATORS = {
    "markdoneelement": _val_markdone,
    "revealgateelement": _val_open_gate,
    "fillgateelement": _val_open_gate,
    "switchgateelement": _val_open_gate,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_state_module.py -q`
Expected: PASS (all, including `test_open_gate_registered_for_all_three_families`).

- [ ] **Step 5: Commit**

```bash
git add courses/state.py courses/tests/test_state_module.py
git commit -m "feat(state): register fill/switch gates under the monotone open-gate validator"
```

---

### Task 2: `FillGateElement.canonical_answers` property

**Files:**
- Modify: `courses/models.py` (inside `class FillGateElement`, near `:658-672`)
- Create (test): `courses/tests/test_fillgate_restore.py`

**Interfaces:**
- Produces: `FillGateElement.canonical_answers -> list[str]` — the first accepted alternative per blank (`[a[0] if a else "" for a in answers]`). Consumed by the fillgate template (Task 4).

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_fillgate_restore.py`:

```python
import html
import json
import re

import pytest

from courses.fillblank import parse
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillGateElement
from courses.models import UnitProgress

pytestmark = pytest.mark.django_db


def test_canonical_answers_first_alternative_per_blank():
    el = FillGateElement(answers=[["color", "colour"], ["x"]])
    assert el.canonical_answers == ["color", "x"]


def test_canonical_answers_handles_empty_shapes():
    assert FillGateElement(answers=[]).canonical_answers == []
    assert FillGateElement(answers=[[]]).canonical_answers == [""]
    assert FillGateElement(answers=None).canonical_answers == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_restore.py -q`
Expected: FAIL — `AttributeError: 'FillGateElement' object has no attribute 'canonical_answers'`.

- [ ] **Step 3: Add the property**

In `courses/models.py`, inside `class FillGateElement`, after the `answers`/`elements` field declarations and before `def render`:

```python
    @property
    def canonical_answers(self):
        """First accepted alternative per blank -- the canonical spelling shown,
        locked, on restore of a correctly-answered gate. `answers` is
        list[list[str]]; a blank with no alternatives renders empty."""
        return [(a[0] if a else "") for a in (self.answers or [])]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest courses/tests/test_fillgate_restore.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/models.py courses/tests/test_fillgate_restore.py
git commit -m "feat(fillgate): canonical_answers property (first alternative per blank)"
```

---

### Task 3: `render_inputs` / `render_fill_blanks` locked mode

**Files:**
- Modify: `courses/fillblank.py:90-112`
- Modify: `courses/templatetags/courses_extras.py:83-90`
- Create (test): `courses/tests/test_fillblank_locked.py`

**Interfaces:**
- Consumes: `courses.fillblank.parse(author_stem) -> (token_stem, answers)` (existing).
- Produces: `render_inputs(token_stem, submitted_values=None, locked=False) -> SafeString`. When `locked`, each `<input>` carries `readonly`, `class="question__blank-input is-correct"`, and `size="max(len(value), 2)"`. `render_fill_blanks(el, submitted_values=None, locked=False)` forwards `locked`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_fillblank_locked.py`:

```python
from courses.fillblank import parse
from courses.fillblank import render_inputs


def test_render_inputs_locked_emits_readonly_is_correct_and_size():
    token_stem, _answers = parse("City: {{Constantinople}}")
    out = str(render_inputs(token_stem, ["Constantinople"], locked=True))
    assert "readonly" in out
    assert "is-correct" in out
    assert 'value="Constantinople"' in out
    assert 'size="14"' in out  # len("Constantinople") == 14


def test_render_inputs_locked_size_floor_is_two():
    token_stem, _answers = parse("Letter: {{a}}")
    out = str(render_inputs(token_stem, ["a"], locked=True))
    assert 'size="2"' in out  # max(len("a"), 2) == 2


def test_render_inputs_unlocked_default_is_unchanged():
    token_stem, _answers = parse("City: {{Paris}}")
    out = str(render_inputs(token_stem, ["Paris"]))
    assert "readonly" not in out
    assert "is-correct" not in out
    assert 'size="' not in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_fillblank_locked.py -q`
Expected: FAIL — `render_inputs() got an unexpected keyword argument 'locked'`.

- [ ] **Step 3: Add the `locked` branch to `render_inputs`**

Replace `render_inputs` in `courses/fillblank.py`:

```python
def render_inputs(token_stem, submitted_values=None, locked=False):
    """Split a stored token-stem and safe-join server-built <input>s. The text
    segments are already-sanitized HTML (trusted); only the <input>s are inserted,
    with the repopulation value HTML-escaped.

    `locked=True` renders each input read-only + .is-correct with a `size` that
    fits its value -- the server-side answered appearance for a restored gate
    (the width-release CSS `.is-correct:read-only` needs the `size` to fit; without
    it `width:auto` defaults to ~20ch and clips long answers)."""
    vals = list(submitted_values or [])
    parts = _TOKEN_RE.split(token_stem or "")
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)  # trusted sanitized HTML
        else:
            n = int(part)
            v = vals[n] if 0 <= n < len(vals) else ""
            if locked:
                out.append(
                    str(
                        format_html(
                            '<input type="text" name="blank" value="{}" '
                            'class="question__blank-input is-correct" size="{}" '
                            "readonly autocomplete=\"off\">",
                            v,
                            max(len(v), 2),
                        )
                    )
                )
            else:
                out.append(
                    str(
                        format_html(
                            '<input type="text" name="blank" value="{}" '
                            'class="question__blank-input" autocomplete="off">',
                            v,
                        )
                    )
                )
    return mark_safe("".join(out))  # noqa: S308 — segments sanitized; inputs escaped
```

- [ ] **Step 4: Forward `locked` through the template tag**

In `courses/templatetags/courses_extras.py`, replace `render_fill_blanks`:

```python
@register.simple_tag
def render_fill_blanks(el, submitted_values=None, locked=False):
    """Render a fill-blank stem: text segments (sanitized HTML) interleaved with
    server-built <input name="blank"> elements (escaped values). `locked=True`
    renders the read-only answered state (restore path). See courses.fillblank."""
    from courses import fillblank

    return fillblank.render_inputs(el.stem, submitted_values, locked=locked)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillblank_locked.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/fillblank.py courses/templatetags/courses_extras.py courses/tests/test_fillblank_locked.py
git commit -m "feat(fillblank): render_inputs locked mode (readonly + is-correct + fitted size)"
```

---

### Task 4: `fillgateelement.html` — data-state + server-rendered locked answer

**Files:**
- Modify: `templates/courses/elements/fillgateelement.html`
- Modify (test): `courses/tests/test_fillgate_restore.py`

**Interfaces:**
- Consumes: leaf context `{el, eid, mine, mine_json, slug, node_pk}` from `_state_context`; `el.canonical_answers` (Task 2); `render_fill_blanks(el, values, locked=True)` (Task 3).
- Produces: a `<div class="fillgate" data-reveal-gate data-fillgate data-element-pk data-state data-state-url>` barrier; when `mine.open`, `fillgate--done`, canonical blanks locked, no Confirm.

- [ ] **Step 1: Write the failing tests (via the lesson view, str-keyed seed)**

Append to `courses/tests/test_fillgate_restore.py`. These mirror `courses/tests/test_reveal_gate_render.py` — render through the real lesson view so the str-keyed `UnitProgress.element_state` is int-coerced by `build_lesson_context` (do NOT call `obj.render()` with a str key; that misses the int `element.pk` lookup and renders the unanswered branch).

```python
from django.urls import reverse

from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_student


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_fillgate(unit, student, author, blob):
    """Attach a FillGateElement (built from author {{answer}} markup) and, if `blob`
    is given, seed the student's UnitProgress.element_state for its join-row pk."""
    stem, answers = parse(author)
    obj = FillGateElement.objects.create(stem=stem, answers=answers)
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row


def test_fillgate_stored_open_renders_locked_with_data_state(client):
    student = make_student(client, "fg_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    row = _seed_fillgate(unit, student, "City: {{Constantinople}}", {"open": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"open": True}
    assert "fillgate--done" in body
    assert 'value="Constantinople"' in body
    assert "readonly" in body and "is-correct" in body
    assert 'size="14"' in body
    assert "fillgate__confirm" not in body  # Confirm suppressed when open
    assert f'data-element-pk="{row.pk}"' in body


def test_fillgate_unanswered_renders_editable(client):
    student = make_student(client, "fg_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_fillgate(unit, student, "City: {{Paris}}", None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "fillgate--done" not in body
    assert "readonly" not in body
    assert "fillgate__confirm" in body


def test_fillgate_barrier_div_is_direct_child_of_body(client):
    student = make_student(client, "fg_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_fillgate(unit, student, "City: {{Paris}}", {"open": True})

    body = client.get(_lesson_url(unit)).content.decode()

    # isGateWrapper + the prepaint CSS require the barrier as a DIRECT child of
    # .lesson-block__body -- no wrapper element. Falsify by wrapping the div.
    assert re.search(
        r'<div class="lesson-block__body">\s*<div[^>]*data-reveal-gate', body
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_fillgate_restore.py -q`
Expected: FAIL — no `data-state` attribute yet, `fillgate--done`/`readonly` absent.

- [ ] **Step 3: Rewrite the template**

Replace `templates/courses/elements/fillgateelement.html` with:

```django
{% load i18n courses_extras %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
<div class="fillgate{% if mine.open %} fillgate--done{% endif %}" data-reveal-gate data-fillgate
     data-element-pk="{{ eid }}" data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
  {% comment %}The check URL lives in data-check-url (NOT the form action), so a no-JS
  Enter/submit cannot navigate to the JSON endpoint. fillgate.js reads data-check-url /
  data-element-pk and treats pk 0 (unsaved preview) as a no-op.{% endcomment %}
  <form class="fillgate__form"
        data-check-url="{% url 'courses:fillgate_check' eid %}"
        data-element-pk="{{ eid }}">
    <div class="fillgate__body">{% if mine.open %}{% render_fill_blanks el el.canonical_answers locked=True %}{% else %}{% render_fill_blanks el %}{% endif %}</div>
    {% if not mine.open %}<button type="submit" class="fillgate__confirm" hidden>{% trans "Confirm" %}</button>{% endif %}
    <p class="fillgate__feedback" data-fillgate-feedback hidden></p>
    {% comment %}Persistent, pre-translated message source; fillgate.js copies its text
    into the feedback slot on a wrong answer and hides it on reset — never destroys it.{% endcomment %}
    <span class="fillgate__msg" data-fillgate-message hidden>{% trans "Not quite — try again" %}</span>
  </form>
</div>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_restore.py -q`
Expected: PASS (all Task 2 + Task 4 tests).

- [ ] **Step 5: Falsify the `data-state` autoescape guard**

Temporarily add `|safe` to `data-state="{{ mine_json|safe }}"` and re-run `test_fillgate_stored_open_renders_locked_with_data_state`. Expected: the `[^"]*` capture truncates at the first raw `"` → `json.loads` RED. Revert `|safe`.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/elements/fillgateelement.html courses/tests/test_fillgate_restore.py
git commit -m "feat(fillgate): data-state + server-rendered locked answer on restore"
```

---

### Task 5: `render_switch_gate` — data-state + bounds-safe locked answer

**Files:**
- Modify: `courses/templatetags/courses_extras.py:236-270`
- Modify: `templates/courses/elements/switchgateelement.html`
- Create (test): `courses/tests/test_switchgate_restore.py`

**Interfaces:**
- Consumes: leaf context `{el, eid, mine, mine_json, slug, node_pk}`; `el.options` (list[str]), `el.answer` (int index), `el.stem`.
- Produces: `render_switch_gate(el, eid, mine=None, mine_json="{}", save_url="")`. Emits `data-state`/`data-state-url` on the `.switchgate` `<div>`; when `mine.open`, `switchgate--done`, `options[answer]` visible + placeholder hidden + cycler `disabled`, no Confirm. Bounds-safe (per-index compare, no `options[answer]` indexing).

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_switchgate_restore.py`:

```python
import html
import json
import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import SwitchGateElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_switchgate(unit, student, stem, options, answer, blob):
    obj = SwitchGateElement.objects.create(stem=stem, options=options, answer=answer)
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row


# The stem is a single-token stem (courses.switchgate.SENTINEL_TOKEN marks the
# cycler slot). Build it the way render_stem expects: text + sentinel + text.
def _stem():
    from courses.switchgate import SENTINEL_TOKEN

    return f"The answer is {SENTINEL_TOKEN}."


def test_switchgate_stored_open_shows_correct_option_locked(client):
    student = make_student(client, "sg_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(
        unit, student, _stem(), ["<b>alpha</b>", "<b>beta</b>", "<b>gamma</b>"], 2,
        {"open": True},
    )

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"open": True}
    assert "switchgate--done" in body
    assert "disabled" in body  # cycler disabled
    assert "switchgate__confirm" not in body  # Confirm omitted when open
    # options[2] ("gamma") is the visible one; placeholder + others hidden.
    assert re.search(r'<span class="switchgate__option">\s*<b>gamma</b>', body)
    assert re.search(
        r'<span class="switchgate__option" hidden>\s*<b>alpha</b>', body
    )


def test_switchgate_unanswered_hides_all_options(client):
    student = make_student(client, "sg_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(unit, student, _stem(), ["a", "b"], 1, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "switchgate--done" not in body
    assert "switchgate__confirm" in body
    # Every option hidden (today's behaviour), placeholder visible.
    assert not re.search(r'<span class="switchgate__option">', body)
    assert "switchgate__placeholder" in body


def test_switchgate_out_of_range_answer_shows_nothing_no_crash(client):
    # A transfer/import could persist an out-of-range answer; render must not 500.
    student = make_student(client, "sg_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(unit, student, _stem(), ["a", "b"], 5, {"open": True})

    resp = client.get(_lesson_url(unit))

    assert resp.status_code == 200
    body = resp.content.decode()
    assert not re.search(r'<span class="switchgate__option">', body)  # none un-hidden


def test_switchgate_barrier_div_is_direct_child_of_body(client):
    student = make_student(client, "sg_ro4")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(unit, student, _stem(), ["a", "b"], 0, {"open": True})

    body = client.get(_lesson_url(unit)).content.decode()

    assert re.search(
        r'<div class="lesson-block__body">\s*<div[^>]*data-reveal-gate', body
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_switchgate_restore.py -q`
Expected: FAIL — no `data-state`, no locked render (the tag ignores `mine`).

- [ ] **Step 3: Rewrite `render_switch_gate`**

Replace `render_switch_gate` in `courses/templatetags/courses_extras.py` (keep the surrounding imports; `_switchgate`, `reverse`, `format_html`, `format_html_join`, `mark_safe`, `_` are already imported at module top):

```python
@register.simple_tag
def render_switch_gate(el, eid, mine=None, mine_json="{}", save_url=""):
    """Render the "Choose & confirm" cycler. When mine.open (restore path), the
    correct option is shown, the cycler disabled, Confirm omitted, and
    switchgate--done added -- the server half of the answered appearance
    (switchgate.js typesets its math on boot). mine_json is passed pre-serialized
    from the template (courses_extras.py has no json import). See courses.switchgate."""
    check_url = reverse("courses:switchgate_check", args=[eid])
    is_open = bool((mine or {}).get("open"))  # null-safe: mine may be None
    answer = el.answer
    # Bounds-safe: un-hide the option where k == answer; an out-of-range answer
    # (a transfer/import could persist one) leaves ALL options hidden, never an
    # IndexError. NEVER index options[answer].
    option_spans = format_html_join(
        "",
        '<span class="switchgate__option"{}>{}</span>',
        (
            (
                "" if (is_open and k == answer) else mark_safe(" hidden"),
                mark_safe(o),  # noqa: S308 — options sanitized at save()
            )
            for k, o in enumerate(el.options or [])
        ),
    )
    hint_id = f"sg-hint-{eid}"
    cycler_disabled = mark_safe(" disabled") if is_open else ""
    ph_hidden = mark_safe(" hidden") if is_open else ""
    confirm_html = (
        ""
        if is_open
        else format_html(
            '<button type="button" class="switchgate__confirm" hidden>{}</button>',
            _("Confirm"),
        )
    )
    widget = format_html(
        '<button type="button" class="switchgate__cycler" data-switchgate-cycler '
        'aria-describedby="{hint}"{disabled}>'
        '<span class="switchgate__placeholder"{ph}>{placeholder}</span>{options}</button>'
        '<span id="{hint}" class="visually-hidden">{describe}</span>'
        "{confirm}"
        '<span class="switchgate__feedback" data-switchgate-feedback hidden>'
        "{tryagain}</span>",
        hint=hint_id,
        disabled=cycler_disabled,
        ph=ph_hidden,
        placeholder=_("Choose ▾"),
        options=option_spans,
        describe=_("Choose an option"),
        confirm=confirm_html,
        tryagain=_("Try again"),
    )
    body = _switchgate.render_stem(el.stem, widget)
    done = mark_safe(" switchgate--done") if is_open else ""
    return format_html(
        '<div class="switchgate{done}" data-reveal-gate data-switchgate '
        'data-element-pk="{pk}" data-check-url="{url}" '
        'data-state="{state}" data-state-url="{save_url}">{body}</div>',
        done=done,
        pk=eid,
        url=check_url,
        state=mine_json,
        save_url=save_url,
        body=body,
    )
```

- [ ] **Step 4: Update the passthrough template**

Replace `templates/courses/elements/switchgateelement.html`:

```django
{% load courses_extras %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
{% render_switch_gate el eid mine mine_json save_url %}
```

(Do NOT load `i18n` — every string comes from `_()` inside the tag.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_restore.py -q`
Expected: PASS.

- [ ] **Step 6: Falsify the bounds-safe render**

Temporarily change the generator's condition to un-hide `options[0]` unconditionally (drop the `k == answer` guard) and re-run `test_switchgate_stored_open_shows_correct_option_locked`. Expected: RED (alpha shown instead of gamma). Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/switchgateelement.html courses/tests/test_switchgate_restore.py
git commit -m "feat(switchgate): data-state + bounds-safe server-rendered locked answer"
```

---

### Task 6: `reveal.js` — the walk restores all three gate families

**Files:**
- Modify: `courses/static/courses/js/reveal.js:199-212`
- Modify (test): `tests/test_e2e_fillgate.py`

**Interfaces:**
- Consumes: fillgate/plain-gate DOM with `data-state` (Tasks 4, existing plain gate); `UnitProgress.element_state` seeded in the DB.
- Produces: after boot, a stored-open fill gate cascades its following content (keeping the widget); an unanswered fill gate stops its scope's walk (prefix-closure).

- [ ] **Step 1: Add a state-seeding helper to the e2e file**

In `tests/test_e2e_fillgate.py`, add a `_seed_state` helper (mirroring `tests/test_e2e_reveal_gate.py:182`) near the other seed helpers:

```python
def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- fixture SETUP (a
    precondition of the reload gesture under test), not a bypassed gesture."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save(update_fields=["element_state"])
```

- [ ] **Step 2: Write the failing e2e tests**

Append to `tests/test_e2e_fillgate.py`. These seed state directly and assert on `.reveal-shown` presence (not visibility — a correctly-restored block may sit in a not-yet-active context, and content hiding is CSS-driven).

```python
@pytest.mark.django_db(transaction=True)
def test_stored_open_fillgate_restores_content_on_load(page, live_server):
    """A previously-answered fill gate: seed {"open": true}, load, the following
    block is revealed (content restored) and the widget stays (locked, done)."""
    student, unit = _new_unit("fg_restore")
    add_element(unit, _text("<p>intro block</p>"))
    fg = add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _seed_state(student, unit, {str(fg.pk): {"open": True}})
    _login(page, live_server, "fg_restore")
    page.goto(_unit_url(live_server, unit))

    expect(page.get_by_text("reward block")).to_be_visible()
    expect(page.locator("[data-fillgate]")).to_have_class(
        re.compile(r"\bfillgate--done\b")
    )
    expect(_confirm(page)).to_have_count(0)  # server omitted Confirm when open


@pytest.mark.django_db(transaction=True)
def test_answered_fillgate_lets_a_later_plain_gate_restore(page, live_server):
    """The walk must CONTINUE past a restored fill gate: a stored-open fill gate
    followed by a stored-open plain gate -> BOTH restore. This is what falsifies
    keeping the old `!matches(RESTORABLE) break` (which stops the walk at the fill
    gate, so the later plain gate never restores)."""
    student, unit = _new_unit("fg_chain")
    fg = add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>between gates</p>"))
    plain = add_element(unit, _gate("Show more"))
    add_element(unit, _text("<p>past the plain gate</p>"))
    _seed_state(
        student, unit, {str(fg.pk): {"open": True}, str(plain.pk): {"open": True}}
    )
    _login(page, live_server, "fg_chain")
    page.goto(_unit_url(live_server, unit))

    expect(page.get_by_text("between gates")).to_be_visible()  # fill gate cascaded
    expect(page.get_by_text("past the plain gate")).to_be_visible()  # walk continued


@pytest.mark.django_db(transaction=True)
def test_unanswered_fillgate_stops_the_walk(page, live_server):
    """Prefix-closure across the new family: a stored-open PLAIN gate placed AFTER
    an unanswered fill gate must NOT restore -- the fill gate is a barrier."""
    student, unit = _new_unit("fg_prefix")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))  # unanswered
    plain = add_element(unit, _gate("Show more"))
    add_element(unit, _text("<p>past the plain gate</p>"))
    _seed_state(student, unit, {str(plain.pk): {"open": True}})
    _login(page, live_server, "fg_prefix")
    page.goto(_unit_url(live_server, unit))

    # The block past the (stored-open) plain gate stays hidden, because the
    # unanswered fill gate stops the walk before the plain gate is reached.
    expect(page.get_by_text("past the plain gate")).to_be_hidden()
```

- [ ] **Step 3: Run the e2e to verify it fails**

Run (foreground): `uv run pytest tests/test_e2e_fillgate.py -m e2e -k "restores_content_on_load or lets_a_later_plain_gate or stops_the_walk" -q`
Expected: a **mix** — `test_stored_open_fillgate_restores_content_on_load` and `test_answered_fillgate_lets_a_later_plain_gate_restore` are **RED** (the current walk `break`s on the fill gate via `!gate.matches(RESTORABLE)`, so it never cascades and never continues to the later plain gate), while `test_unanswered_fillgate_stops_the_walk` is already **GREEN** (the old `break` already stops at the unanswered fill gate — its falsification is Step 6).

- [ ] **Step 4: Change the walk**

In `courses/static/courses/js/reveal.js`, inside `restoreGates`'s inner `for` loop, replace:

```js
        try {
          if (!isGateWrapper(ownWrapper(gate, scope), scope)) continue; // (a) mis-scoped
          if (!gate.matches(RESTORABLE)) break;   // fill/switch gate: a barrier
          if (!storedOpen(gate)) break;           // closed gate: prefix-closure
          cascadeFrom(gate, { hideWrapper: true, focus: false });
        } catch (e) {
          break; // unknown state: stop THIS scope
        }
```

with:

```js
        try {
          if (!isGateWrapper(ownWrapper(gate, scope), scope)) continue; // (a) mis-scoped
          if (!storedOpen(gate)) break;           // closed OR unanswered gate: prefix-closure
          // Plain gate self-consumes (hideWrapper:true); fill/switch keep their answered
          // Q&A visible (false), matching each family's click path. RESTORABLE still means
          // "the plain gate button" -- initRevealGates uses it to bind clicks (plain only).
          cascadeFrom(gate, { hideWrapper: gate.matches(RESTORABLE), focus: false });
        } catch (e) {
          break; // unknown state: stop THIS scope
        }
```

- [ ] **Step 5: Run the e2e to verify it passes**

Run (foreground): `uv run pytest tests/test_e2e_fillgate.py -m e2e -k "restores_content_on_load or lets_a_later_plain_gate or stops_the_walk" -q`
Expected: PASS (all three — the fill gate restores, the walk continues to the later plain gate, and the unanswered fill gate still stops its scope).

- [ ] **Step 6: Falsify prefix-closure**

Temporarily narrow `restoreGates`'s enumeration from `ctx.querySelectorAll(BARRIER)` to `ctx.querySelectorAll(RESTORABLE)` and re-run `test_unanswered_fillgate_stops_the_walk`. Expected: RED (the fill gate is no longer enumerated, so it can't stop the walk, and the plain gate leaks). Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/reveal.js tests/test_e2e_fillgate.py
git commit -m "feat(reveal): restore fill/switch gates in the walk (hideWrapper per family)"
```

---

### Task 7: `fillgate.js` — save on correct, skip-arm on boot

**Files:**
- Modify: `courses/static/courses/js/fillgate.js`
- Modify (test): `tests/test_e2e_fillgate.py`

**Interfaces:**
- Consumes: `.fillgate` div with `data-state`, `data-state-url`, `data-element-pk` (Task 4); the walk that cascades on boot (Task 6); the `element_state_save` endpoint + `_val_open_gate` (Task 1).
- Produces: on a correct answer, a fire-and-forget `POST {"element": eid, "state": {"open": true}}`; on boot, a stored-open gate is not armed but binds a `preventDefault`-only submit handler.

- [ ] **Step 1: Write the failing e2e tests**

Append to `tests/test_e2e_fillgate.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_correct_answer_persists_across_reload(page, live_server):
    """Real gesture: answer correctly, await the state POST, reload -> content still
    revealed AND the blank shows the canonical answer locked, no Confirm."""
    _student, unit = _new_unit("fg_persist")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_persist")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _blank(page).fill("Paris")
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    expect(page.get_by_text("reward block")).to_be_visible()
    expect(_blank(page)).to_have_js_property("readOnly", True)
    expect(_blank(page)).to_have_value("Paris")
    expect(_confirm(page)).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_long_answer_not_clipped_after_reload(page, live_server):
    """Round-2 C1: the server must emit `size`, or width:auto clips a long answer
    to ~20ch on the restore path (the JS lock() that sets size never runs on boot)."""
    _student, unit = _new_unit("fg_persist_long")
    add_element(unit, _fillgate("Largest city on the Bosphorus? {{Constantinople}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_persist_long")
    page.goto(_unit_url(live_server, unit))

    _blank(page).fill("Constantinople")
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ):
        _confirm(page).click()

    page.reload()
    expect(_blank(page)).to_have_js_property("readOnly", True)
    assert page.evaluate(
        "() => { const i = document.querySelector("
        "'[data-fillgate] input[name=\"blank\"]');"
        " return i.scrollWidth <= i.clientWidth + 1; }"
    )


@pytest.mark.django_db(transaction=True)
def test_wrong_answer_persists_nothing(page, live_server):
    """A wrong answer makes NO state POST; reload -> fresh editable widget, hidden."""
    _student, unit = _new_unit("fg_wrong_nosave")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_wrong_nosave")
    page.goto(_unit_url(live_server, unit))

    saw_state_post = {"hit": False}
    page.on(
        "request",
        lambda r: saw_state_post.__setitem__("hit", saw_state_post["hit"] or "/state/" in r.url),
    )
    _blank(page).fill("London")
    _confirm(page).click()
    expect(page.locator("[data-fillgate-feedback]")).to_be_visible()
    assert saw_state_post["hit"] is False

    page.reload()
    expect(_blank(page)).to_have_js_property("readOnly", False)
    expect(page.get_by_text("reward block")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_restored_fillgate_does_not_navigate_on_enter(page, live_server):
    """Round-3 I2: a restored single-blank form must not implicitly submit (Enter)
    and navigate away. The boot preventDefault-only handler blocks it."""
    student, unit = _new_unit("fg_enter")
    fg = add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _seed_state(student, unit, {str(fg.pk): {"open": True}})
    _login(page, live_server, "fg_enter")
    url = _unit_url(live_server, unit)
    page.goto(url)

    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    _blank(page).focus()
    _blank(page).press("Enter")
    page.wait_for_timeout(150)  # allow any (wrongly) queued navigation / POST to start
    assert page.url == url  # no navigation / reload
    # The distinguishing assertion (spec §e2e): skip-arm binds a preventDefault-ONLY
    # handler, so NO check POST fires. The normal handler also preventDefaults (so
    # page.url alone can't tell them apart) but additionally POSTs to fillgate_check.
    assert posts == []
```

- [ ] **Step 2: Run the e2e to verify it fails**

Run (foreground): `uv run pytest tests/test_e2e_fillgate.py -m e2e -k "persists_across_reload or long_answer_not_clipped or wrong_answer_persists_nothing or does_not_navigate_on_enter" -q`
Expected: FAIL — `test_correct_answer_persists_across_reload` times out on `expect_response` (no state POST yet).

- [ ] **Step 3: Add `storedOpen` + `saveOpen` locals and wire them in**

In `courses/static/courses/js/fillgate.js`, add two helpers near `csrf` (top of the IIFE):

```js
  function storedOpen(el) {
    try {
      var raw = el && el.dataset.state;
      if (!raw) return false;
      var blob = JSON.parse(raw);
      return !!(blob && blob.open === true); // strict shape, not truthiness
    } catch (e) {
      return false;
    }
  }

  function saveOpen(container) {
    var url = container.dataset.stateUrl;
    if (!url) return; // editor preview: "" -> no-op
    var eid = parseInt(container.dataset.elementPk, 10);
    if (!eid) return; // pk 0 == content object with no join row
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ element: eid, state: { open: true } }),
      keepalive: true, // survives unload
    }).catch(function () {}); // monotone: keep the DOM, ignore the body
  }
```

Then in `submit`, inside the `if (data.correct)` branch, persist after the cascade:

```js
        if (data.correct) {
          var container = lock(form);
          if (window.libliRevealCascade && container) {
            window.libliRevealCascade(container, { hideWrapper: false });
          }
          if (container) saveOpen(container); // NEW: persist {"open": true}
        } else {
```

And in `initOne`, short-circuit for a stored-open gate AFTER latching the ready flag:

```js
  function initOne(form) {
    if (form.dataset.fillgateReady === "1") return;
    form.dataset.fillgateReady = "1";
    var container = form.closest("[data-fillgate]");
    if (storedOpen(container)) {
      // Server rendered it locked; do NOT arm Confirm/submit. But a single-blank
      // form with no submit button implicitly submits on Enter (GET nav -> reload);
      // bind a preventDefault-only handler so restore is not worse than the click path.
      form.addEventListener("submit", function (e) { e.preventDefault(); });
      return;
    }
    var btn = form.querySelector(".fillgate__confirm");
    if (btn) btn.hidden = false; // arm Confirm now that JS is live
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      submit(form);
    });
  }
```

- [ ] **Step 4: Run the e2e to verify it passes**

Run (foreground): `uv run pytest tests/test_e2e_fillgate.py -m e2e -k "persists_across_reload or long_answer_not_clipped or wrong_answer_persists_nothing or does_not_navigate_on_enter" -q`
Expected: PASS.

- [ ] **Step 5: Falsify the size + preventDefault guards**

- Temporarily drop `size="{}"` (and its arg) from `render_inputs`'s locked branch → re-run `test_long_answer_not_clipped_after_reload` → RED. Revert.
- Falsify the boot short-circuit two ways, both against `test_restored_fillgate_does_not_navigate_on_enter`: (a) replace its `form.addEventListener("submit", …preventDefault…)` with a bare `return;` → Enter implicitly submits → navigation → `page.url` RED; (b) delete the whole `if (storedOpen(container)) {…}` branch so a stored-open gate falls through to normal arming → Enter fires a `fillgate_check` POST → `assert posts == []` RED. Revert after each.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/fillgate.js tests/test_e2e_fillgate.py
git commit -m "feat(fillgate): persist {open:true} on correct; skip-arm + preventDefault on restore"
```

---

### Task 8: `switchgate.js` — save on correct, skip-arm + typeset on boot

**Files:**
- Modify: `courses/static/courses/js/switchgate.js`
- Modify (test): `tests/test_e2e_switchgate.py`

**Interfaces:**
- Consumes: `.switchgate` div with `data-state`, `data-state-url`, `data-element-pk` (Task 5); the walk (Task 6); the endpoint + validator (Task 1).
- Produces: on a correct choice, a fire-and-forget `POST {"open": true}`; on boot, a stored-open gate is not armed but typesets its shown option's math.

- [ ] **Step 1: Add a `_seed_state` helper, then write the failing e2e tests**

`tests/test_e2e_switchgate.py` has no `_seed_state` helper — add the one identical to Task 6 (near the other seed helpers):

```python
def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- fixture SETUP (a
    precondition of the reload gesture under test), not a bypassed gesture."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save(update_fields=["element_state"])
```

Then append the tests. The correct-choice gesture (from the shipped `test_wrong_then_correct_reveals_and_locks`): for `answer=1`, click the cycler twice (placeholder → opt0 → opt1) to reach the correct option, then Confirm.

```python
@pytest.mark.django_db(transaction=True)
def test_choice_persists_across_reload(page, live_server):
    """Real gesture: cycle to the correct option, Confirm, await the state POST,
    reload -> content revealed, the correct option shown disabled, done, no Confirm."""
    _student, unit = _new_unit("sg_persist")
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "sg_persist")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _cycler(page).click()  # -> opt0 "Alpha"
    _cycler(page).click()  # -> opt1 "Bravo" (correct; answer index 1)
    expect(_option(page, 1)).to_be_visible()
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    expect(page.get_by_text("reward block")).to_be_visible()
    expect(page.locator("[data-switchgate]")).to_have_class(
        re.compile(r"\bswitchgate--done\b")
    )
    expect(_confirm(page)).to_have_count(0)
    expect(_cycler(page)).to_have_js_property("disabled", True)
    expect(_option(page, 1)).to_be_visible()  # the correct option, server-shown


@pytest.mark.django_db(transaction=True)
def test_stored_open_switchgate_typesets_math_on_load(page, live_server):
    """Round-1 C1: switchgate math is typeset ONLY by its own initOne (math.js's
    global renderInlineText list excludes .switchgate). Seed {"open": true} for a
    gate whose correct option contains inline \\(...\\); on load the shown option is
    typeset (a .katex node), with no raw \\( left in the switchgate text."""
    student, unit = _new_unit("sg_math_restore")
    sg = add_element(
        unit, _switchgate("Operator: {{choice}}", [r"\(+\)", "minus"], answer=0)
    )
    _seed_state(student, unit, {str(sg.pk): {"open": True}})
    _login(page, live_server, "sg_math_restore")
    page.goto(_unit_url(live_server, unit))

    # The correct option (index 0, the math one) is server-shown; its LaTeX is
    # typeset by switchgate.js's boot short-circuit.
    math_node = page.locator(".switchgate__option .katex")
    expect(math_node).to_have_count(1)
    expect(math_node.first).to_be_visible()
    assert "\\(" not in page.locator(".switchgate").inner_text()
    expect(page.locator("[data-switchgate]")).to_have_class(
        re.compile(r"\bswitchgate--done\b")
    )
```

- [ ] **Step 2: Run the e2e to verify it fails**

Run (foreground): `uv run pytest tests/test_e2e_switchgate.py -m e2e -k "persists_across_reload or typesets_math_on_load" -q`
Expected: only `test_choice_persists_across_reload` is **RED** (there is no `saveOpen` yet, so `expect_response` on `/state/` times out). `test_stored_open_switchgate_typesets_math_on_load` is already **GREEN** here: Task 5 (done earlier) server-renders the open switchgate, and the *unmodified* `initOne` already calls `typesetMath` on its normal path — so the math is typeset even before this task's boot branch exists. That test's real job is Step 5 (it guards that the boot branch, once added, typesets *before* returning; a `return` that skipped the normal-path `typesetMath` would render raw LaTeX).

- [ ] **Step 3: Add `storedOpen` + `saveOpen`; wire save + boot typeset**

In `courses/static/courses/js/switchgate.js`, add the same `storedOpen` and `saveOpen` helpers as Task 7 (near `csrf`). In `submit`, inside `if (data.correct)`, after the cascade:

```js
        if (data.correct) {
          lock(container);
          if (window.libliRevealCascade) {
            window.libliRevealCascade(container, { hideWrapper: false });
          }
          saveOpen(container); // NEW -- container is submit()'s own arg
        } else {
```

In `initOne`, short-circuit for a stored-open gate AFTER latching the ready flag — **typeset before returning** (math.js's global list excludes `.switchgate`):

```js
  function initOne(container) {
    if (container.dataset.switchgateReady === "1") return;
    container.dataset.switchgateReady = "1";
    if (storedOpen(container)) {
      typesetMath(container); // C1: switchgate math is JS-only; typeset THEN return
      return;
    }
    var cycler = container.querySelector("[data-switchgate-cycler]");
    var confirm = container.querySelector(".switchgate__confirm");
    if (confirm) confirm.hidden = false;  // arm Confirm now that JS is live
    if (cycler) {
      cycler.addEventListener("click", function () { advance(container); });
    }
    if (confirm) {
      confirm.addEventListener("click", function () { submit(container); });
    }
    typesetMath(container);
  }
```

> **Falsifiability note:** unlike fillgate's boot short-circuit (whose `preventDefault`-only handler is *load-bearing* — the normal path would fire a spurious check POST on Enter), the switchgate `return` is **defense-in-depth**: the server renders the cycler `disabled` and omits Confirm, so the normal fall-through path is already harmless (a disabled button dispatches no click → `advance` never fires) and it *also* typesets. No test falsifies the `return` itself; what IS falsifiable (Step 5) is that `typesetMath` runs before it. Keep the `return` for symmetry and to stay correct if a future change re-enables the cycler.

- [ ] **Step 4: Run the e2e to verify it passes**

Run (foreground): `uv run pytest tests/test_e2e_switchgate.py -m e2e -k "persists_across_reload or typesets_math_on_load" -q`
Expected: PASS.

- [ ] **Step 5: Falsify the typeset guard**

Temporarily remove `typesetMath(container);` from the boot short-circuit → re-run `test_stored_open_switchgate_typesets_math_on_load` → RED (raw `\(...\)` remains, no `.katex` node). Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/switchgate.js tests/test_e2e_switchgate.py
git commit -m "feat(switchgate): persist {open:true} on correct; skip-arm + typeset on restore"
```

---

### Task 9: Definition of Done — full regression + visual check

**Files:** none (verification only).

- [ ] **Step 1: Full non-e2e suite**

Run: `uv run pytest -n auto -q`
Expected: PASS, no regressions. (Baseline should be green before this branch; compare counts.)

- [ ] **Step 2: The three e2e files (foreground, `-m e2e`)**

Run each foreground (never backgrounded):
```
uv run pytest tests/test_e2e_reveal_gate.py -m e2e -q
uv run pytest tests/test_e2e_fillgate.py -m e2e -q
uv run pytest tests/test_e2e_switchgate.py -m e2e -q
```
Expected: PASS. `test_e2e_reveal_gate.py`'s seven pre-existing tests guard the plain-gate cascade / `hideWrapper:true` / watchdog / quiz-inertness against the walk change; the fill/switch files' pre-existing click-path tests guard `focusTargetIn`'s `[data-fillgate]`/`[data-switchgate]` branches.

- [ ] **Step 3: Lint, format, migration & system checks**

Run:
```
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check
uv run python manage.py check
```
Expected: all clean; `makemigrations --check` reports no changes (this slice adds none).

- [ ] **Step 4: Visual no-flash check (per verify-ui-with-screenshots)**

Screenshot a stored-open fill gate on load (seed `{"open": true}` for a **>20-character** answer, e.g. "Constantinople"). Confirm the canonical answer shows in full (not clipped), reads as locked, with no flash of an editable/clipped input. This is a manual verification supplementing the automated `test_long_answer_not_clipped_after_reload`.

- [ ] **Step 5: Confirm the main checkout is clean**

If executing in an isolated worktree, run `git status --short` **from the primary (non-worktree) checkout** — the repo path the worktree branched from — to confirm no stray edits leaked outside the worktree (subagents can write outside their stated cwd). If executing directly on `master` (no worktree), run `git status --short` in the repo root and confirm only the intended files are modified.
Expected: only the intended files changed.

---

## Self-review notes (author)

- **Spec coverage:** §1 → Task 1; §2 (fillgate template + `canonical_answers` + `render_inputs` locked + `size`) → Tasks 2–4; §3 (`render_switch_gate` signature, data-state, bounds-safe locked) → Task 5; §5 (walk) → Task 6; §4 (save + boot skip-arm, preventDefault, typeset) → Tasks 7–8; Testing (validator, canonical, render, DOM-chain, e2e round-trips, prefix-closure, math-restore, no-nav) → distributed across tasks; Regression + Visual → Task 9. The required `test_state_module.py` rename (round-3 I1) is Task 1 Step 1.
- **Monotone-blob invariant** upheld: no task stores anything but `{"open": true}`; the answer is rendered server-side from `canonical_answers` / `el.answer`.
- **Int/str key seam** (round-2 I1) handled by rendering the server-side tests through the lesson view (`client.get`, str-keyed `UnitProgress` seed), never `obj.render()` with a str key.
- **Endpoint round-trip coverage:** the spec's fast "endpoint round-trip" item is covered end-to-end by the Task 7/8 e2e (a *real* `POST` to `element_state_save`, `assert resp.ok`, then a reload that shows restored state) plus the validator/dispatch unit tests in Task 1 and the generic slice-1 endpoint tests (`courses/tests/test_element_state_endpoint.py`, unchanged — the endpoint is type-agnostic). No duplicate fast endpoint test is added for the two new families.
