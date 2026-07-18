# Student practice state — graded self-checks restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a student's **fully-correct** Switch grid, Fill-in table, and Guess-the-number self-check survive a page reload — the locked, all-green completed appearance the widget shows the moment the last cell/cycler/guess lands correct — by bringing all three onto slice 2's client-restore substrate, the same way PR #147 brought the two answered reveal-gates onto it.

**Architecture:** The blob is monotone `{"done": true}` — one reachable value, no verdict, no answer stored. The completed answer is **rendered server-side** from each element's own answer fields (`SwitchGridElement.lines[].cyclers[].answer`, `FillTableElement.canonical_cells`, `GuessNumberElement.canonical_target`), gated on the stored flag. Two elements render via a **positional template tag** (`render_switch_grid`, `render_guess_number` in `courses/templatetags/courses_extras.py`) whose signature must widen to receive `mine`/`mine_json`/`save_url` (exactly as `render_switch_gate` was widened in PR #147); the third (`FillTableElement`) renders via a **real Django template** (`filltableelement.html`) that already receives the full state context and just needs to use it. A new shared JS global, `window.libliState` (`courses/static/courses/js/state.js`), replaces the duplicated `storedOpen`/`saveOpen` pairs in `fillgate.js`/`switchgate.js` and is reused by the three new widget scripts for save-on-complete + boot-time skip-arm.

**Tech Stack:** Django (server-rendered templates + template tags), vanilla ES5 IIFE JS (no module system, no JS test runner — behavioural JS coverage is Playwright e2e), pytest, Playwright.

## Global Constraints

- **No new migration.** `UnitProgress.element_state` already exists (slice 1, PR #139). `uv run python manage.py makemigrations --check` must stay clean.
- **No new element type.** `ELEMENT_MODELS` does not change (currently 31 entries) — the `len(ELEMENT_MODELS)` / `ELEMENT_MODELS[-1]` count-asserts in `tests/test_transfer_schema.py` and `tests/test_models_multigrid.py` must not be touched.
- **No new user-visible strings** — no `makemessages` pass. `test_po_catalog_clean` must stay green. Every label used (`Check`, `Confirm`, `Great!`, `Try again`, `Correct!`, `Your answer`, …) already exists in the codebase.
- **The blob is monotone `{"done": true}` only.** No free-text, no verdict, no answer stored in the blob. The completed answer is rendered server-side from the element's own answer fields on every request, gated on the flag — it self-heals if an author edits the accepted answer after a student completes the element.
- **Tooling runs via `uv run`** (`ruff`, `pytest`, `python` are NOT on PATH in bash). DoD requires `uv run ruff check`, `uv run ruff format --check`, and `uv run python manage.py check`.
- **Heavy suite: `uv run pytest -n auto`** (serial exceeds a subagent's 600s watchdog).
- **e2e needs `-m e2e`** — otherwise `addopts = -q -m 'not e2e'` deselects the file and pytest exits **5, looking like success**. Run focused e2e **foreground only, never backgrounded** (a backgrounded `-m e2e` leaves runaway browsers).
- **Isolate the test DB per worktree:** the worktree `.env` already sets `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_gradedselfchecks` (the role has CREATEDB). Concurrent worktrees collide on `test_libli`; the symptom is *errors, not failures*.
- **Verify the main checkout with `git status`** before claiming it is untouched — subagents can write outside their stated cwd.
- **No `reveal.js` change.** None of these three elements emit `[data-reveal-gate]` or join the `restoreGates` walk. Restore here is purely each widget restoring its own locked appearance.
- **No change to `switchgrid_check` / `filltable_check` / `guessnumber_check`.** They remain the sole grader of a live attempt; this slice only persists the *completed* outcome and re-renders it.
- **Step-by-step (`StepperElement`) is out of scope** — ungraded, ELEMENT_MODELS entry not touched, no restore logic added.

## File map

- `courses/state.py` — add `_val_done`; register `switchgridelement`, `filltableelement`, `guessnumberelement`. (Task 1)
- `courses/tests/test_state_module.py` — add `_val_done` tests + a registration test. (Task 1)
- `courses/models.py` — add `FillTableElement.canonical_cells` (Task 2); add `GuessNumberElement.canonical_target` (Task 3); rewrite `FillTableElement.render()` (Task 6).
- `tests/test_filltable_model.py` — `canonical_cells` unit tests. (Task 2)
- `tests/test_guessnumber_model.py` — `canonical_target` unit tests. (Task 3)
- `courses/templatetags/courses_extras.py` — widen `render_switch_grid` (Task 4) and `render_guess_number` (Task 5) to `(el, eid, mine=None, mine_json="{}", save_url="")`, bounds-safe locked render, `data-state`/`data-state-url`.
- `templates/courses/elements/switchgridelement.html` — pass `mine mine_json save_url`. (Task 4)
- `templates/courses/elements/guessnumberelement.html` — pass `mine mine_json save_url`. (Task 5)
- `templates/courses/elements/filltableelement.html`, `templates/courses/elements/_filltable_cell.html` — `data-state`/`data-state-url`, locked cell branch, summary un-hide. (Task 6)
- New tests: `courses/tests/test_switchgrid_restore.py` (Task 4), `tests/test_guessnumber_restore.py` (Task 5), `tests/test_filltable_restore.py` (Task 6), `courses/tests/test_libli_state_wiring.py` (Task 7).
- `courses/static/courses/js/state.js` — **new file**, `window.libliState.storedFlag`/`saveFlag`. (Task 7)
- `templates/courses/lesson_unit.html` — include `state.js`, gated on the OR of all six families, before every consuming widget script. (Task 7)
- `courses/static/courses/js/fillgate.js`, `courses/static/courses/js/switchgate.js` — refactored onto `libliState`, private `storedOpen`/`saveOpen` removed. (Task 7)
- `courses/static/courses/js/switchgrid.js` — save-on-complete + boot skip-arm (typeset-before-return). (Task 8)
- `courses/static/courses/js/filltable.js` — save-on-complete + boot skip-arm (typeset-before-return). (Task 9)
- `courses/static/courses/js/guessnumber.js` — save-on-complete + boot skip-arm (no typeset needed — `.guessnumber` is in math.js's global list). (Task 10)
- e2e additions: `tests/test_e2e_switchgrid.py` (Task 8), `tests/test_e2e_filltable.py` (Task 9), `tests/test_e2e_guessnumber.py` (Task 10).
- `courses/tests/test_progress_reset.py` — one new "Start fresh clears a done self-check" test. (Task 11)

---

### Task 1: `_val_done` validator + register the three graded self-check families

**Files:**
- Modify: `courses/state.py:74-82`
- Modify (test): `courses/tests/test_state_module.py` (append after the existing `_val_open_gate` tests)

**Interfaces:**
- Produces: `state._val_done(element, obj, payload) -> {"done": True} | EMPTY | REJECT`. `state.VALIDATORS` keys `"switchgridelement"`, `"filltableelement"`, `"guessnumberelement"` all map to it.

- [ ] **Step 1: Write the failing tests first**

Append to `courses/tests/test_state_module.py`:

```python
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"done": True}, {"done": True}),
        ({"done": True, "x": 1}, {"done": True}),  # extra keys normalized away
    ],
)
def test_val_done_stores_done(payload, expected):
    assert state._val_done(None, None, payload) == expected


@pytest.mark.parametrize("payload", [{"done": False}, {}, {"other": 1}])
def test_val_done_empty(payload):
    # A well-formed "nothing to restore" DROPS the key -- EMPTY, never REJECT.
    assert state._val_done(None, None, payload) is state.EMPTY


@pytest.mark.parametrize("payload", ["nope", 3, None, ["done"]])
def test_val_done_rejects_non_dict(payload):
    assert state._val_done(None, None, payload) is state.REJECT


def test_done_registered_for_all_three_graded_selfcheck_families():
    for key in ("switchgridelement", "filltableelement", "guessnumberelement"):
        assert state.VALIDATORS[key] is state._val_done
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_state_module.py -q`
Expected: FAIL — `AttributeError: module 'courses.state' has no attribute '_val_done'`.

- [ ] **Step 3: Add the validator and register the three keys**

In `courses/state.py`, insert `_val_done` after `_val_open_gate` (before the `VALIDATORS` dict):

```python
def _val_done(element, obj, payload):
    """{"done": True} -- monotone. A graded self-check (switch grid / fill-in table /
    guess-the-number) that has been answered fully correctly. The whole gesture has one
    reachable value; the completed answer is NOT stored -- it is rendered server-side
    from the element's own answers, gated on this flag.

    A false/absent `done` is a well-formed "nothing to restore" -> EMPTY (drop the key),
    never REJECT.
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"done": True} if payload.get("done") else EMPTY


# Keyed by content_type.model (the ELEMENT_MODELS namespace) -- NOT the form key
# and NOT the transfer key. Those three namespaces have been a recurring trap; the
# registry does not add a fourth.
VALIDATORS = {
    "markdoneelement": _val_markdone,
    "revealgateelement": _val_open_gate,
    "fillgateelement": _val_open_gate,
    "switchgateelement": _val_open_gate,
    "switchgridelement": _val_done,
    "filltableelement": _val_done,
    "guessnumberelement": _val_done,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_state_module.py -q`
Expected: PASS (all, including `test_done_registered_for_all_three_graded_selfcheck_families`).

- [ ] **Step 5: Falsify the registration**

Temporarily change the `"filltableelement"` entry to `_val_open_gate` and re-run `test_done_registered_for_all_three_graded_selfcheck_families`. Expected: RED (`state.VALIDATORS["filltableelement"] is state._val_done` fails). Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/state.py courses/tests/test_state_module.py
git commit -m "feat(state): register switch-grid/fill-table/guess-number under the monotone done validator"
```

---

### Task 2: `FillTableElement.canonical_cells` property

**Files:**
- Modify: `courses/models.py` (inside `class FillTableElement`, after `normalize_data` at `:884-909`, before `_sanitized_data`)
- Modify (test): `tests/test_filltable_model.py`

**Interfaces:**
- Produces: `FillTableElement.canonical_cells -> list[list[dict]]` — same shape as `normalize_data(self.data)["cells"]`; static cells pass through unchanged; each answer cell's `"answer"` is replaced by `courses.filltable.split_alternatives(cell["answer"])[0]` (or `""` if no alternatives).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_filltable_model.py`:

```python
def test_canonical_cells_uses_first_alternative_per_answer_cell():
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "x"},
                    {"kind": "answer", "answer": "4 | four | IV"},
                ]
            ]
        }
    )
    out = el.canonical_cells
    assert out[0][0] == {
        "kind": "static",
        "html": "x",
        "halign": "left",
        "valign": "top",
    }
    assert out[0][1]["kind"] == "answer"
    assert out[0][1]["answer"] == "4"


def test_canonical_cells_no_alternatives_renders_empty_string():
    el = FillTableElement(data={"cells": [[{"kind": "answer", "answer": ""}]]})
    assert el.canonical_cells[0][0]["answer"] == ""
    el2 = FillTableElement(data={"cells": [[{"kind": "answer", "answer": "|  |"}]]})
    assert el2.canonical_cells[0][0]["answer"] == ""  # pipe-only -> zero alternatives


def test_canonical_cells_shape_matches_normalize_data():
    el = FillTableElement(
        data={
            "cells": [
                [{"kind": "answer", "answer": "1"}],
                [{"kind": "static", "html": "b"}],
            ]
        }
    )
    normalized = FillTableElement.normalize_data(el.data)
    assert len(el.canonical_cells) == len(normalized["cells"])
    assert [len(r) for r in el.canonical_cells] == [len(r) for r in normalized["cells"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_filltable_model.py -q`
Expected: FAIL — `AttributeError: 'FillTableElement' object has no attribute 'canonical_cells'`.

- [ ] **Step 3: Add the property**

In `courses/models.py`, inside `class FillTableElement`, immediately after the `normalize_data` static method and before `_sanitized_data`:

```python
    @property
    def canonical_cells(self):
        """Grid shaped exactly like normalize_data(self.data)["cells"]: static
        cells pass through unchanged; each answer cell's `answer` is replaced by
        its FIRST pipe-delimited alternative (courses.filltable.split_alternatives
        ()[0]; no configured alternatives -> ""). Restore-only (mine.done); reads
        self.data via normalize_data() but NEVER mutates it -- normalize_data()
        already returns fresh cell dicts, not references into self.data."""
        from courses.filltable import split_alternatives

        cells = self.normalize_data(self.data)["cells"]
        out = []
        for row in cells:
            out_row = []
            for cell in row:
                if cell.get("kind") == self.ANSWER:
                    alts = split_alternatives(cell.get("answer", ""))
                    out_row.append({**cell, "answer": alts[0] if alts else ""})
                else:
                    out_row.append(cell)
            out.append(out_row)
        return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_filltable_model.py -q`
Expected: PASS.

- [ ] **Step 5: Falsify the first-alternative selection**

Temporarily change `alts[0] if alts else ""` to `cell.get("answer", "")` (i.e. leave the raw pipe-delimited string untouched) and re-run `test_canonical_cells_uses_first_alternative_per_answer_cell`. Expected: RED (`out[0][1]["answer"] == "4 | four | IV"`, not `"4"`). Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/models.py tests/test_filltable_model.py
git commit -m "feat(filltable): canonical_cells property (first alternative per answer cell)"
```

---

### Task 3: `GuessNumberElement.canonical_target` property

**Files:**
- Modify: `courses/models.py` (inside `class GuessNumberElement`, after the field declarations at `:713-719`, before `save`)
- Modify (test): `tests/test_guessnumber_model.py`

**Interfaces:**
- Produces: `GuessNumberElement.canonical_target -> str` — `courses.guessnumber.format_target(self.target)`, never a bare `Decimal.normalize()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_guessnumber_model.py`:

```python
def test_canonical_target_strips_trailing_zeros():
    el = GuessNumberElement(target=Decimal("42.50000000"))
    assert el.canonical_target == "42.5"


def test_canonical_target_avoids_e_notation_for_round_numbers():
    # normalize() ALONE yields '4.0401E+4' for 40401 and '1E+2' for 100 --
    # the exact defect format_target's docstring already fixed once.
    assert GuessNumberElement(target=Decimal("40401")).canonical_target == "40401"
    assert GuessNumberElement(target=Decimal("100")).canonical_target == "100"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_guessnumber_model.py -q`
Expected: FAIL — `AttributeError: 'GuessNumberElement' object has no attribute 'canonical_target'`.

- [ ] **Step 3: Add the property**

In `courses/models.py`, inside `class GuessNumberElement`, immediately after the field declarations and before `def save`:

```python
    @property
    def canonical_target(self):
        """Display-formatted target, reusing courses.guessnumber.format_target() --
        NEVER a fresh Decimal.normalize() (that alone yields E-notation for round
        numbers, e.g. 40401 -> '4.0401E+4', the exact defect format_target's own
        docstring records already fixing once). Shown, readonly, on restore of a
        correctly-answered guess: the student's exact within-tolerance guess is
        not stored (monotone blob), so the canonical target is what is shown."""
        from courses.guessnumber import format_target

        return format_target(self.target)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_guessnumber_model.py -q`
Expected: PASS.

- [ ] **Step 5: Falsify the format_target reuse**

Temporarily replace the property body with `return str(self.target.normalize())` (bare `Decimal.normalize()`, bypassing `format_target`) and re-run `test_canonical_target_avoids_e_notation_for_round_numbers`. Expected: RED (`"4.0401E+4"` / `"1E+2"` instead of `"40401"` / `"100"`). Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/models.py tests/test_guessnumber_model.py
git commit -m "feat(guessnumber): canonical_target property (reuses format_target, no E-notation)"
```

---

### Task 4: Switch grid — bounds-safe server-rendered locked appearance

**Files:**
- Modify: `courses/templatetags/courses_extras.py:338-401` (`render_switch_grid`)
- Modify: `templates/courses/elements/switchgridelement.html`
- Create (test): `courses/tests/test_switchgrid_restore.py`

**Interfaces:**
- Produces: `render_switch_grid(el, eid, mine=None, mine_json="{}", save_url="")`. When `mine.done`: each cycler's option at index `cyc["answer"]` is shown (bounds-safe — index-equality comparison, never `options[answer]`; an out-of-range `answer` un-hides nothing), the cycler carries `switchgrid--locked` + `disabled`, the Confirm button is omitted, and the summary `<p data-switchgrid-summary>` is un-hidden with `switchgrid--success` and the "Great!" text. Adds `data-state`/`data-state-url` on the root `.switchgrid` div unconditionally (autoescaped).

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_switchgrid_restore.py`:

```python
"""Switch grid restore tests (student-practice-state graded self-checks slice).
Server-rendered locked appearance is asserted via the LESSON VIEW (str-keyed
UnitProgress seed, never obj.render() with a str key -- that misses the int
element.pk lookup build_lesson_context performs and silently renders the
unanswered branch). See courses.state._val_done and
courses.templatetags.courses_extras.render_switch_grid."""

import html
import json
import re

import pytest
from django.urls import reverse

from courses import fillblank
from courses.models import Element
from courses.models import Enrollment
from courses.models import SwitchGridElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_grid(unit, student, lines, blob):
    obj = SwitchGridElement.objects.create(prompt="", lines=lines)
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


_ONE_CYCLER_LINE = [
    {
        "stem": f"3 {_tok(0)} 3 = 9",
        "cyclers": [{"options": ["+", "-", "x"], "answer": 2}],
    }
]


def test_switchgrid_stored_done_renders_locked_with_data_state(client):
    student = make_student(client, "sgrid_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_grid(unit, student, _ONE_CYCLER_LINE, {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"done": True}
    assert re.search(r"data-switchgrid-cycler[^>]*\bdisabled\b", body)
    assert "switchgrid--locked" in body
    assert "switchgrid__confirm" not in body  # Confirm omitted when done
    assert "switchgrid--success" in body
    assert "Great!" in body
    # options[2] ("x") is the visible one; option[0] ("+") is hidden.
    assert re.search(
        r'<span class="switchgrid__option switchgrid__option--current">x</span>', body
    )
    assert re.search(r'<span class="switchgrid__option" hidden>\+</span>', body)


def test_switchgrid_unanswered_renders_editable(client):
    student = make_student(client, "sgrid_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_grid(unit, student, _ONE_CYCLER_LINE, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "switchgrid--locked" not in body
    assert "switchgrid__confirm" in body
    assert not re.search(r"data-switchgrid-cycler[^>]*\bdisabled\b", body)
    assert re.search(
        r'<span class="switchgrid__option switchgrid__option--current">\+</span>', body
    )


def test_switchgrid_out_of_range_answer_shows_nothing_no_crash(client):
    # A transfer/import could persist an out-of-range answer; render must not 500.
    student = make_student(client, "sgrid_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    bad_line = [
        {"stem": f"pick {_tok(0)}", "cyclers": [{"options": ["a", "b"], "answer": 5}]}
    ]
    _seed_grid(unit, student, bad_line, {"done": True})

    resp = client.get(_lesson_url(unit))

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "switchgrid__option--current" not in body  # none un-hidden
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_switchgrid_restore.py -q`
Expected: FAIL — no `data-state` attribute yet, no locked render (the tag ignores `mine`).

- [ ] **Step 3: Rewrite `render_switch_grid`**

Replace `render_switch_grid` in `courses/templatetags/courses_extras.py`:

```python
@register.simple_tag
def render_switch_grid(el, eid, mine=None, mine_json="{}", save_url=""):
    """Render the switch-grid self-check widget: one container per line (static
    lines included), cyclers spliced into each line's token stem.

    mine_json is passed pre-serialized from the template (courses_extras.py has no
    json import). When mine.done (restore path), each cycler shows its correct
    option -- BOUNDS-SAFE: compared by index equality, never options[answer]
    indexing, so an out-of-range author-set answer (a stray transfer/import) un-
    hides nothing rather than 500ing -- carries switchgrid--locked + disabled;
    the Confirm button is omitted; and the summary <p> is un-hidden with
    switchgrid--success and the success text, reproducing lock()+summarize(root,
    true). See courses.switchgrid."""
    from courses import switchgrid as _switchgrid

    check_url = reverse("courses:switchgrid_check", args=[eid])
    is_done = bool((mine or {}).get("done"))
    line_html = []
    for i, line in enumerate(el.lines or []):
        widgets = {}
        for j, cyc in enumerate(line.get("cyclers", []) or []):
            options = cyc.get("options", []) or []
            answer = cyc.get("answer")
            valid_answer = (
                isinstance(answer, int)
                and not isinstance(answer, bool)
                and 0 <= answer < len(options)
            )
            shown = (answer if valid_answer else -1) if is_done else 0
            option_spans = format_html_join(
                "",
                '<span class="switchgrid__option{}"{}>{}</span>',
                (
                    (
                        " switchgrid__option--current" if k == shown else "",
                        "" if k == shown else mark_safe(" hidden"),
                        mark_safe(o),  # noqa: S308 — options sanitized at save()
                    )
                    for k, o in enumerate(options)
                ),
            )
            cyc_locked = " switchgrid--locked" if is_done else ""
            cyc_disabled = mark_safe(" disabled") if is_done else ""
            widgets[j] = format_html(
                '<button type="button" class="switchgrid__cycler{locked}" '
                'data-switchgrid-cycler data-cycler="{j}" '
                'aria-label="{label}"{disabled}>{opts}</button>',
                locked=cyc_locked,
                j=j,
                label=_("Cycle options"),
                disabled=cyc_disabled,
                opts=option_spans,
            )
        body = _switchgrid.render_stem_multi(line.get("stem", ""), widgets)
        line_html.append(
            format_html(
                '<div class="switchgrid__line" data-line="{i}">{body}</div>',
                i=i,
                body=body,
            )
        )
    lines_joined = mark_safe("".join(line_html))  # noqa: S308 — built from format_html above
    prompt_html = (
        format_html('<p class="switchgrid__prompt">{}</p>', el.prompt)
        if el.prompt
        else ""
    )
    confirm_html = (
        ""
        if is_done
        else format_html(
            '<button type="button" class="switchgrid__confirm">{}</button>',
            _("Check"),
        )
    )
    summary_class = mark_safe(" switchgrid--success") if is_done else ""
    summary_hidden = "" if is_done else mark_safe(" hidden")
    summary_text = _("Great!") if is_done else ""
    return format_html(
        '<div class="switchgrid" data-switchgrid data-element-pk="{pk}" '
        'data-check-url="{url}" data-state="{state}" data-state-url="{save_url}">'
        "{prompt}{lines}"
        "{confirm}"
        '<p class="switchgrid__summary{summary_class}" data-switchgrid-summary '
        'data-success-msg="{ok}" data-retry-msg="{retry}"{summary_hidden}>{summary_text}</p>'
        "</div>",
        pk=eid,
        url=check_url,
        state=mine_json,
        save_url=save_url,
        prompt=prompt_html,
        lines=lines_joined,
        confirm=confirm_html,
        summary_class=summary_class,
        ok=_("Great!"),
        retry=_("Try again"),
        summary_hidden=summary_hidden,
        summary_text=summary_text,
    )
```

- [ ] **Step 4: Update the passthrough template**

Replace `templates/courses/elements/switchgridelement.html`:

```django
{% load courses_extras %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
{% render_switch_grid el eid mine mine_json save_url %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgrid_restore.py courses/tests/test_switchgrid_template.py courses/tests/test_switchgrid_wiring.py -q`
Expected: PASS (new restore tests plus the pre-existing template/wiring tests unaffected — `el.render()` with no state still hits `mine={}`, so the unanswered branch is byte-identical modulo the two new attributes).

- [ ] **Step 6: Falsify the bounds-safe render**

Temporarily change `shown = (answer if valid_answer else -1) if is_done else 0` to `shown = (answer if is_done else 0)` (drop the `valid_answer` bounds check, trust `answer` even when out of range) and re-run `courses/tests/test_switchgrid_restore.py -q`. Expected: RED — `test_switchgrid_stored_done_renders_locked_with_data_state` still passes (that grid's `answer` is in range), but this is not the guard under test here; the equality comparison `k == shown` never indexes and so never crashes regardless of `shown`'s value, by construction. The bounds guard's real job is *correctness*, not crash-safety: temporarily change the comparison instead to `shown = 0` unconditionally whenever `is_done` (ignoring `answer` entirely) and re-run `test_switchgrid_stored_done_renders_locked_with_data_state`. Expected: RED (option "+", index 0, shown instead of the correct option "x", index 2). Revert.

- [ ] **Step 7: Falsify the `data-state` autoescape guard**

Temporarily wrap `state=mine_json` as `state=mark_safe(mine_json)` and re-run `test_switchgrid_stored_done_renders_locked_with_data_state`. Expected: the unescaped `"` inside the JSON blob breaks the attribute early, the `[^"]*` capture truncates, and `json.loads` raises → RED. Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/switchgridelement.html courses/tests/test_switchgrid_restore.py
git commit -m "feat(switchgrid): data-state + bounds-safe server-rendered locked answer"
```

---

### Task 5: Guess-the-number — server-rendered locked appearance

**Files:**
- Modify: `courses/templatetags/courses_extras.py:303-335` (`render_guess_number`)
- Modify: `templates/courses/elements/guessnumberelement.html`
- Create (test): `tests/test_guessnumber_restore.py`

**Interfaces:**
- Produces: `render_guess_number(el, eid, mine=None, mine_json="{}", save_url="")`. When `mine.done`: the input is pre-filled with `el.canonical_target`, `readonly`, carries `is-correct`; Check is omitted entirely (not just hidden); `guessnumber--done` is added to the root; the success block is un-hidden. Adds `data-state`/`data-state-url` on the root `.guessnumber` div unconditionally.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_guessnumber_restore.py`:

```python
"""Guess-the-number restore tests (student-practice-state graded self-checks
slice). Server-rendered locked appearance is asserted via the LESSON VIEW
(str-keyed UnitProgress seed, never obj.render() with a str key). See
courses.state._val_done, GuessNumberElement.canonical_target, and
courses.templatetags.courses_extras.render_guess_number."""

import html
import json
import re
from decimal import Decimal

import pytest
from django.urls import reverse

from courses import guessnumber
from courses.models import Element
from courses.models import Enrollment
from courses.models import GuessNumberElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_guessnumber(unit, student, author_stem, blob, success_message=""):
    token_stem, raw = guessnumber.parse_stem(author_stem)
    obj = GuessNumberElement.objects.create(
        stem=token_stem, target=Decimal(raw), success_message=success_message
    )
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


def test_guessnumber_stored_done_renders_locked_with_data_state(client):
    student = make_student(client, "gn_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_guessnumber(unit, student, "Guess: {{40401}}", {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"done": True}
    assert "guessnumber--done" in body
    assert 'value="40401"' in body  # canonical_target -- no E-notation
    assert "readonly" in body
    assert "is-correct" in body
    assert "data-guess-check" not in body  # Check omitted entirely when done
    assert "Correct!" in body  # blank success_message falls back
    assert "<div data-guess-success>" in body  # un-hidden


def test_guessnumber_unanswered_renders_editable(client):
    student = make_student(client, "gn_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_guessnumber(unit, student, "Guess: {{42}}", None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "guessnumber--done" not in body
    assert "data-guess-check" in body
    assert "readonly" not in body
    assert "<div data-guess-success hidden>" in body


def test_guessnumber_canonical_target_avoids_e_notation_end_to_end(client):
    student = make_student(client, "gn_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_guessnumber(unit, student, "Guess: {{40401.5}}", {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'value="40401.5"' in body
    assert "E+" not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_guessnumber_restore.py -q`
Expected: FAIL — no `data-state` attribute, no locked render (the tag ignores `mine`).

- [ ] **Step 3: Rewrite `render_guess_number`**

Replace `render_guess_number` in `courses/templatetags/courses_extras.py`:

```python
@register.simple_tag
def render_guess_number(el, eid, mine=None, mine_json="{}", save_url=""):
    """Render the numeric input spliced into the stem at its U+FFFF-delimited token.

    NO <form>: implicit submission cannot be suppressed without JS, and a stray
    Enter reload would wipe reveal.js's in-memory cascade state (it persists
    nothing), re-hiding a gated element. Enter comes from a keydown listener
    instead. The <div> WRAPS the stem; only inline markup is spliced, because
    the parser hoists block elements out of an enclosing <p>.

    mine_json is passed pre-serialized from the template (courses_extras.py has
    no json import). When mine.done (restore path), the input shows
    el.canonical_target readonly + is-correct, Check is omitted entirely, and
    the success block is un-hidden -- reproducing guessnumber.js's correct-
    branch appearance server-side (its boot skip-arm does not re-run this).
    See courses.guessnumber."""
    check_url = reverse("courses:guessnumber_check", args=[eid])
    is_done = bool((mine or {}).get("done"))
    if is_done:
        widget = format_html(
            '<input data-guess-input type="text" inputmode="decimal" '
            'aria-label="{}" value="{}" readonly class="is-correct">',
            _("Your answer"),
            el.canonical_target,
        )
    else:
        widget = format_html(
            '<input data-guess-input type="text" inputmode="decimal" '
            'aria-label="{}"><button data-guess-check type="button" hidden>{}</button>',
            _("Your answer"),
            _("Check"),
        )
    body = guessnumber.render_stem(el.stem, widget)
    msg = el.success_message or ""
    has_text = bool(strip_tags(msg).strip())
    success = mark_safe(msg) if has_text else format_html("{}", _("Correct!"))  # noqa: S308 — sanitized at save()
    done_class = mark_safe(" guessnumber--done") if is_done else ""
    success_hidden = "" if is_done else mark_safe(" hidden")
    return format_html(
        '<div class="guessnumber{}" data-guessnumber data-element-pk="{}" '
        'data-check-url="{}" data-msg-high="{}" data-msg-low="{}" '
        'data-state="{}" data-state-url="{}">{}'
        '<div data-guess-live aria-live="polite">'
        "<p data-guess-hint hidden></p>"
        '<div data-guess-success{}>{}</div></div></div>',
        done_class,
        eid,
        check_url,
        _("The number is too big, try again."),
        _("The number is too small, try again."),
        mine_json,
        save_url,
        body,
        success_hidden,
        success,
    )
```

- [ ] **Step 4: Update the passthrough template**

Replace `templates/courses/elements/guessnumberelement.html`:

```django
{% load courses_extras %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
{% render_guess_number el eid mine mine_json save_url %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_guessnumber_restore.py tests/test_guessnumber_render.py -q`
Expected: PASS (new restore tests plus the pre-existing render tests, including `assert "<form" not in html`, unaffected).

- [ ] **Step 6: Falsify the `data-state` autoescape guard**

Temporarily wrap `mine_json` as `mark_safe(mine_json)` in the call site and re-run `test_guessnumber_stored_done_renders_locked_with_data_state`. Expected: the unescaped `"` breaks the attribute, the capture truncates, `json.loads` raises → RED. Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/guessnumberelement.html tests/test_guessnumber_restore.py
git commit -m "feat(guessnumber): data-state + server-rendered locked answer (canonical_target, readonly, Check omitted)"
```

---

### Task 6: Fill-in table — server-rendered locked appearance, no `self.data` mutation

**Files:**
- Modify: `courses/models.py` (`FillTableElement.render` at `:937-942`)
- Modify: `templates/courses/elements/filltableelement.html`
- Modify: `templates/courses/elements/_filltable_cell.html`
- Create (test): `tests/test_filltable_restore.py`

**Interfaces:**
- Produces: `FillTableElement.render()` builds `ctx["data"] = {**normalize_data(self.data), "cells": self.canonical_cells}` when `mine.done`, else unchanged. Template gains `data-state`/`data-state-url` on `[data-filltable]`, omits Confirm when done, un-hides `.filltable__summary` with `filltable__summary--success` + text. `_filltable_cell.html` gains a `mine.done` branch: `readonly` + `filltable__input--correct` + the canonical value.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_restore.py`:

```python
"""Fill-in table restore tests (student-practice-state graded self-checks
slice). The locked-appearance behavioural assertions go through the LESSON
VIEW (str-keyed UnitProgress seed, never obj.render() with a str key). The
self.data no-mutation guard is a pure Python-level invariant and calls
obj.render() directly with an INT-keyed state dict -- render()'s own contract,
not the str/int UnitProgress.element_state seam. See courses.state._val_done,
FillTableElement.canonical_cells, and FillTableElement.render()."""

import json
import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import FillTableElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


_CELLS = [
    [{"kind": "static", "html": "czas"}, {"kind": "static", "html": "woda"}],
    [{"kind": "static", "html": "0"}, {"kind": "answer", "answer": "4 | four"}],
]


def _seed_filltable(unit, student, cells, blob):
    obj = FillTableElement(data={"cells": cells})
    obj.save()
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


def test_filltable_stored_done_renders_locked_with_data_state(client):
    student = make_student(client, "ftbl_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, _CELLS, {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(m.group(1)) == {"done": True}
    assert (
        '<input type="text" class="filltable__input filltable__input--correct" '
        'data-r="1" data-c="1" value="4" readonly' in body
    )
    assert "filltable__confirm" not in body  # Confirm omitted when done
    assert "filltable__summary--success" in body
    assert "Great!" in body


def test_filltable_unanswered_renders_editable(client):
    student = make_student(client, "ftbl_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, _CELLS, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "filltable__input--correct" not in body
    assert "filltable__confirm" in body
    assert (
        '<input type="text" class="filltable__input" data-r="1" data-c="1" '
        "aria-label=" in body
    )


def test_filltable_done_render_empty_alternatives_shows_empty_value(client):
    student = make_student(client, "ftbl_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, [[{"kind": "answer", "answer": ""}]], {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'value=""' in body
    assert "filltable__input--correct" in body


def test_filltable_render_does_not_mutate_self_data_on_done():
    course, unit = make_course_with_unit()
    obj = FillTableElement(
        data={"cells": [[{"kind": "answer", "answer": "4 | four"}]]}
    )
    obj.save()
    row = Element.objects.create(unit=unit, content_object=obj)
    before = json.dumps(obj.data, sort_keys=True)

    obj.render(
        element=row,
        state={row.pk: {"done": True}},
        slug=unit.course.slug,
        node_pk=unit.pk,
    )

    assert json.dumps(obj.data, sort_keys=True) == before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_filltable_restore.py -q`
Expected: FAIL — no `data-state` attribute, no locked cell branch.

- [ ] **Step 3: Rewrite `FillTableElement.render()`**

In `courses/models.py`, replace `FillTableElement.render`:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        if ctx["mine"].get("done"):
            # Shallow-copied dict, NEVER `self.data["cells"] = ...` -- mutating
            # self.data in place would silently overwrite the student's stored
            # pipe-delimited alternatives in-memory for the rest of the request.
            ctx["data"] = {
                **self.normalize_data(self.data),
                "cells": self.canonical_cells,
            }
        else:
            ctx["data"] = self.normalize_data(self.data)
        return render_to_string("courses/elements/filltableelement.html", ctx)
```

- [ ] **Step 4: Rewrite the templates**

Replace `templates/courses/elements/filltableelement.html`:

```django
{% load i18n %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
{% comment %}Student Fill-in table self-check. Static cells are pre-sanitised at
save() and emitted |safe (math typeset client-side over .el--filltable). Answer
cells emit an EMPTY input — the accepted answer is NEVER sent to the client,
UNLESS mine.done (restore path), when render() has already swapped data.cells for
FillTableElement.canonical_cells and _filltable_cell.html renders each answer
cell readonly + locked with its canonical value. data-r/data-c are 0-based
indices into normalize_data(data)["cells"].{% endcomment %}
<div class="filltable" data-filltable
     data-element-pk="{{ eid }}"
     data-check-url="{% url 'courses:filltable_check' eid %}"
     data-success-msg="{% trans 'Great!' %}"
     data-retry-msg="{% trans 'Try again' %}"
     data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
  {% if data.prompt %}<p class="filltable__prompt">{{ data.prompt }}</p>{% endif %}
  <div class="el el--filltable el--filltable--border-{{ data.border }}"
       {% if data.header_row %}data-header-row{% endif %}
       {% if data.header_col %}data-header-col{% endif %}>
    <div class="el--filltable__scroll">
      <table>
        {% for row in data.cells %}
        <tr>
          {% for cell in row %}
            {% if forloop.parentloop.first and data.header_row or forloop.first and data.header_col %}
              <th class="ta-{{ cell.halign }} va-{{ cell.valign }}"
                  {% if forloop.parentloop.first and data.header_row %}scope="col"{% elif forloop.first and data.header_col %}scope="row"{% endif %}>{% include "courses/elements/_filltable_cell.html" %}</th>
            {% else %}
              <td class="ta-{{ cell.halign }} va-{{ cell.valign }}">{% include "courses/elements/_filltable_cell.html" %}</td>
            {% endif %}
          {% endfor %}
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>
  {% if not mine.done %}<button type="button" class="filltable__confirm btn btn--small">{% trans "Check" %}</button>{% endif %}
  <p class="filltable__summary{% if mine.done %} filltable__summary--success{% endif %}" data-filltable-summary{% if not mine.done %} hidden{% endif %}>{% if mine.done %}{% trans "Great!" %}{% endif %}</p>
</div>
```

Replace `templates/courses/elements/_filltable_cell.html` (single line, matching the original file's style):

```django
{% load i18n %}{% if cell.kind == "answer" %}{% if mine.done %}<input type="text" class="filltable__input filltable__input--correct" data-r="{{ forloop.parentloop.counter0 }}" data-c="{{ forloop.counter0 }}" value="{{ cell.answer }}" readonly aria-label="{% blocktranslate with r=forloop.parentloop.counter c=forloop.counter %}Answer, row {{ r }}, column {{ c }}{% endblocktranslate %}">{% else %}<input type="text" class="filltable__input" data-r="{{ forloop.parentloop.counter0 }}" data-c="{{ forloop.counter0 }}" aria-label="{% blocktranslate with r=forloop.parentloop.counter c=forloop.counter %}Answer, row {{ r }}, column {{ c }}{% endblocktranslate %}">{% endif %}{% else %}{{ cell.html|safe }}{% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_filltable_restore.py tests/test_filltable_render.py tests/test_filltable_model.py -q`
Expected: PASS (new restore tests plus pre-existing render/model tests unaffected — `_render()` in `test_filltable_render.py` calls `el.render()` with no state, so `mine={}`, unchanged output modulo the two new attributes).

- [ ] **Step 6: Falsify the no-mutation guard**

Temporarily replace the `render()` branch with `self.data["cells"] = self.canonical_cells; ctx["data"] = self.data` (mutate in place instead of shallow-copying) and re-run `test_filltable_render_does_not_mutate_self_data_on_done`. Expected: RED (`self.data`'s `cells[0][0]["answer"]` becomes `"4"` in place, no longer matching the pre-render snapshot). Revert.

- [ ] **Step 7: Falsify the locked-cell branch**

Temporarily change `{% if mine.done %}` to `{% if False %}` inside `_filltable_cell.html`'s answer branch and re-run `test_filltable_stored_done_renders_locked_with_data_state`. Expected: RED (`filltable__input--correct` absent, empty unlocked input rendered instead). Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/models.py templates/courses/elements/filltableelement.html templates/courses/elements/_filltable_cell.html tests/test_filltable_restore.py
git commit -m "feat(filltable): data-state + server-rendered locked answer, no self.data mutation"
```

---

### Task 7: `window.libliState` shared helper — wiring + gate refactor

**Files:**
- Create: `courses/static/courses/js/state.js`
- Modify: `templates/courses/lesson_unit.html:76-83`
- Modify: `courses/static/courses/js/fillgate.js:14-36` and its two call sites
- Modify: `courses/static/courses/js/switchgate.js:14-36` and its two call sites
- Create (test): `courses/tests/test_libli_state_wiring.py`

**Interfaces:**
- Produces: `window.libliState.storedFlag(el, key) -> bool` (strict `blob[key] === true`, try/catch fail-open to `false`); `window.libliState.saveFlag(container, stateObj)` (fire-and-forget `POST` with `keepalive`, no-op on missing `data-state-url`/`data-element-pk`).
- `fillgate.js` / `switchgate.js` call `window.libliState.storedFlag(container, "open")` / `window.libliState.saveFlag(container, {open: true})` instead of their private `storedOpen`/`saveOpen`.

- [ ] **Step 1: Write the failing wiring test**

Create `courses/tests/test_libli_state_wiring.py`:

```python
"""Wiring for the shared `libliState` JS helper (student-practice-state graded
self-checks slice): state.js must load on a lesson page whenever ANY of the six
gate/self-check families is present, and it must load BEFORE every widget
script that depends on it (deferred scripts execute in document order). See
the design doc's "load order is a hard requirement" note."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element
from courses.models import SwitchGridElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_state_js_loads_before_switchgrid_js_in_isolation(client):
    # ONE new-family element present, no gate -- guards the six-flag OR gate in
    # isolation (a bug that gated state.js on only the three gate flags would
    # pass a page that ALSO has a gate but fail this one).
    course = CourseFactory()
    unit = _lesson_unit(course)
    grid = SwitchGridElement.objects.create(prompt="P", lines=[])
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(SwitchGridElement),
        object_id=grid.pk,
    )
    user = make_login(client, "liblistate-wiring-student")
    EnrollmentFactory(student=user, course=course)

    body = client.get(
        reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    ).content.decode()

    assert "courses/js/state.js" in body
    assert body.index("courses/js/state.js") < body.index("courses/js/switchgrid.js")


def test_state_js_absent_when_no_family_present(client):
    course = CourseFactory()
    unit = _lesson_unit(course)
    user = make_login(client, "liblistate-wiring-student2")
    EnrollmentFactory(student=user, course=course)

    body = client.get(
        reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    ).content.decode()

    assert "courses/js/state.js" not in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_libli_state_wiring.py -q`
Expected: FAIL — `state.js` never appears in `lesson_unit.html`'s output.

- [ ] **Step 3: Create `state.js`**

Create `courses/static/courses/js/state.js`:

```js
(function () {
  "use strict";

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  window.libliState = {
    storedFlag: function (el, key) {           // strict shape, not truthiness
      try {
        var raw = el && el.dataset.state;
        if (!raw) return false;
        var blob = JSON.parse(raw);
        return !!(blob && blob[key] === true);
      } catch (e) {
        return false;
      }
    },
    saveFlag: function (container, stateObj) {  // fire-and-forget, keepalive, swallow errors
      var url = container.dataset.stateUrl;
      if (!url) return;                          // editor preview "" -> no-op
      var eid = parseInt(container.dataset.elementPk, 10);
      if (!eid) return;                          // pk 0 -> no join row
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ element: eid, state: stateObj }),
        keepalive: true,
      }).catch(function () {});
    },
  };
})();
```

- [ ] **Step 4: Include `state.js` before every consuming widget script**

In `templates/courses/lesson_unit.html`, insert a new line immediately **before** the `reveal.js` include (the first of the six):

```django
  {% if has_reveal_gate or has_fill_gate or has_switch_gate or has_switch_grid or has_fill_table or has_guess_number %}<script src="{% static 'courses/js/state.js' %}" defer></script>{% endif %}
  {% if has_reveal_gate %}<script src="{% static 'courses/js/reveal.js' %}" defer></script>{% endif %}
  {% if has_fill_gate %}<script src="{% static 'courses/js/fillgate.js' %}" defer></script>{% endif %}
  {% if has_switch_gate %}<script src="{% static 'courses/js/switchgate.js' %}" defer></script>{% endif %}
  {% if has_switch_grid %}<script src="{% static 'courses/js/switchgrid.js' %}" defer></script>{% endif %}
  {% if has_fill_table %}<script src="{% static 'courses/js/filltable.js' %}" defer></script>{% endif %}
```

(The `has_guess_number`-gated `guessnumber.js` include further down the block is untouched by this step — `state.js`'s own `{% if %}` already covers it via the OR.)

- [ ] **Step 5: Run the wiring test to verify it passes**

Run: `uv run pytest courses/tests/test_libli_state_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Falsify the six-flag OR**

Temporarily narrow the new `{% if %}` to only `has_reveal_gate or has_fill_gate or has_switch_gate` (dropping the three new flags) and re-run `test_state_js_loads_before_switchgrid_js_in_isolation`. Expected: RED (`state.js` absent — the page has only `has_switch_grid`). Revert.

- [ ] **Step 7: Refactor `fillgate.js` onto `libliState`**

In `courses/static/courses/js/fillgate.js`, delete the private `storedOpen`/`saveOpen` functions (currently lines 14-36, immediately after `csrf()`):

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

Then replace the two call sites. In `submit`:

```js
          if (container) saveOpen(container); // NEW: persist {"open": true}
```
becomes
```js
          if (container) window.libliState.saveFlag(container, { open: true });
```

In `initOne`:

```js
    if (storedOpen(container)) {
```
becomes
```js
    if (window.libliState.storedFlag(container, "open")) {
```

`csrf()` itself is left in place — `submit`'s own `fillgate_check` `fetch` call still uses it.

- [ ] **Step 8: Refactor `switchgate.js` onto `libliState`**

In `courses/static/courses/js/switchgate.js`, delete the identical private `storedOpen`/`saveOpen` block (lines 14-36). Replace the two call sites. In `submit`:

```js
          saveOpen(container); // NEW -- container is submit()'s own arg
```
becomes
```js
          window.libliState.saveFlag(container, { open: true }); // NEW -- container is submit()'s own arg
```

In `initOne`:

```js
    if (storedOpen(container)) {
```
becomes
```js
    if (window.libliState.storedFlag(container, "open")) {
```

`csrf()` is left in place (used by `submit`'s own `switchgate_check` fetch).

- [ ] **Step 9: Regression — the two gate e2e files stay green (foreground)**

Run each foreground (never backgrounded):
```
uv run pytest tests/test_e2e_fillgate.py -m e2e -q
uv run pytest tests/test_e2e_switchgate.py -m e2e -q
```
Expected: PASS, unchanged from before the refactor (they exercise `storedOpen`/`saveOpen` behaviourally through `libliState` now, not through the removed private functions).

- [ ] **Step 10: Commit**

```bash
git add courses/static/courses/js/state.js templates/courses/lesson_unit.html courses/static/courses/js/fillgate.js courses/static/courses/js/switchgate.js courses/tests/test_libli_state_wiring.py
git commit -m "feat(state): shared window.libliState helper; refactor fillgate/switchgate JS onto it"
```

---

### Task 8: `switchgrid.js` — save on complete, skip-arm + typeset on boot

**Files:**
- Modify: `courses/static/courses/js/switchgrid.js`
- Modify (test): `tests/test_e2e_switchgrid.py`

**Interfaces:**
- Consumes: `.switchgrid` div with `data-state`, `data-state-url`, `data-element-pk` (Task 4); `window.libliState` (Task 7).
- Produces: on an all-correct Check, `window.libliState.saveFlag(root, {done: true})`; on boot, a stored-done grid is not armed but its math IS typeset first (`.switchgrid` is excluded from `math.js`'s global `renderInlineText` list — the exact gotcha PR #147 hit for `.switchgate`).

- [ ] **Step 1: Write the failing e2e tests**

Append to `tests/test_e2e_switchgrid.py` (after the existing `_seed_two_cycler_grid` helper, and change that helper to `return` its row):

```python
def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- fixture SETUP (a
    precondition of the reload gesture under test), not a bypassed gesture."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save(update_fields=["element_state"])


def _seed_tab1(unit, tab1_children):
    """One TabsElement on `unit` (tabs 'First'/'Second'); `tab1_children` is a
    list of concrete element objects placed, in order, nested under tab 1."""
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "First"},
                {"id": "t000002", "label": "Second"},
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=obj)
    for child in tab1_children:
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id="t000001"
        )
    return join


@pytest.mark.django_db(transaction=True)
def test_switchgrid_correct_choice_persists_across_reload(page, live_server):
    """Real gesture: cycle both cyclers to correct, Check, await the state POST,
    reload -> still locked/all-correct, Check gone, correct options shown."""
    _student, unit = _new_unit("sgrid_persist")
    _seed_two_cycler_grid(unit)
    _login(page, live_server, "sgrid_persist")
    page.goto(_unit_url(live_server, unit))

    c0, c1 = _cycler(page, 0), _cycler(page, 1)
    c0.click()
    c0.click()
    c1.click()
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    c0, c1 = _cycler(page, 0), _cycler(page, 1)
    expect(_confirm(page)).to_have_count(0)
    expect(c0).to_have_class(_LOCKED)
    expect(c1).to_have_class(_LOCKED)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_SUCCESS)
    expect(_option(c0, 2)).to_be_visible()
    expect(_option(c1, 1)).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_switchgrid_wrong_attempt_persists_nothing(page, live_server):
    """A wrong Check makes NO state POST; reload -> fresh, editable, unlocked."""
    _student, unit = _new_unit("sgrid_wrong_nosave")
    _seed_two_cycler_grid(unit)
    _login(page, live_server, "sgrid_wrong_nosave")
    page.goto(_unit_url(live_server, unit))

    saw_state_post = {"hit": False}
    page.on(
        "request",
        lambda r: saw_state_post.__setitem__(
            "hit", saw_state_post["hit"] or "/state/" in r.url
        ),
    )
    _confirm(page).click()  # both cyclers at default index 0 -> wrong
    expect(_summary(page)).to_have_class(_RETRY)
    assert saw_state_post["hit"] is False

    page.reload()
    expect(_confirm(page)).to_be_visible()
    expect(_cycler(page, 0)).not_to_have_class(_LOCKED)


@pytest.mark.django_db(transaction=True)
def test_switchgrid_isolation_no_pageerror_when_alone(page, live_server):
    """libliState presence/isolation guard: a page with EXACTLY ONE new-family
    element type -- no gate -- restores without a ReferenceError. Not alongside
    a gate, which could mask a missing six-flag-OR bug."""
    student, unit = _new_unit("sgrid_isolation")
    row = _seed_two_cycler_grid(unit)
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, "sgrid_isolation")
    page.goto(_unit_url(live_server, unit))

    assert errors == []
    expect(_confirm(page)).to_have_count(0)
    expect(_cycler(page, 0)).to_have_class(_LOCKED)


@pytest.mark.django_db(transaction=True)
def test_switchgrid_stored_done_typesets_math_on_load(page, live_server):
    """.switchgrid is excluded from math.js's global renderInlineText list (like
    .switchgate); on restore, switchgrid.js's OWN boot short-circuit must
    typeset the correct option's math before returning."""
    from courses import switchgrid
    from courses.models import SwitchGridElement

    student, unit = _new_unit("sgrid_math_restore")
    token_stem, _n = switchgrid.parse_stem_multi("Operator: {{choice}}")
    grid = SwitchGridElement.objects.create(
        prompt="",
        lines=[
            {
                "stem": token_stem,
                "cyclers": [{"options": [r"\(+\)", "minus"], "answer": 0}],
            }
        ],
    )
    row = add_element(unit, grid)
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    _login(page, live_server, "sgrid_math_restore")
    page.goto(_unit_url(live_server, unit))

    math_node = page.locator(".switchgrid__option .katex")
    expect(math_node).to_have_count(1)
    assert "\\(" not in page.locator(".switchgrid").inner_text()


@pytest.mark.django_db(transaction=True)
def test_switchgrid_nested_in_tab_restores_after_reload(page, live_server):
    """Switch grid is in NESTABLE_TYPE_KEYS -- nested inside a Tabs panel. The
    widget JS's root-scoped dataset lookups and the server render must restore
    correctly inside a tab panel exactly as at top level."""
    from courses import switchgrid
    from courses.models import Element
    from courses.models import SwitchGridElement

    student, unit = _new_unit("sgrid_tabs")
    token_stem, _n = switchgrid.parse_stem_multi("Pick {{choice}}")
    grid = SwitchGridElement.objects.create(
        prompt="",
        lines=[{"stem": token_stem, "cyclers": [{"options": ["a", "b"], "answer": 1}]}],
    )
    join = _seed_tab1(unit, [grid])
    row = Element.objects.get(parent=join, content_type__model="switchgridelement")
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    _login(page, live_server, "sgrid_tabs")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    c0 = _cycler(page, 0)
    expect(c0).to_have_class(_LOCKED)
    expect(_option(c0, 1)).to_be_visible()
```

Also change `_seed_two_cycler_grid` to return its row (used by the isolation test above):

```python
def _seed_two_cycler_grid(unit):
    return add_element(
        unit,
        _switchgrid(
            "Set both:",
            [
                (
                    "First {{choice}} then {{choice}}",
                    [(["A", "B", "C"], 2), (["X", "Y"], 1)],
                )
            ],
        ),
    )
```

- [ ] **Step 2: Run the e2e to verify it fails**

Run (foreground): `uv run pytest tests/test_e2e_switchgrid.py -m e2e -k "persists_across_reload or persists_nothing or isolation_no_pageerror or typesets_math_on_load or nested_in_tab" -q`
Expected: FAIL — `test_switchgrid_correct_choice_persists_across_reload` times out on `expect_response` (no state POST yet); the restore-dependent tests (`isolation`, `typesets_math_on_load`, `nested_in_tab`) fail because nothing ever locked on reload (no skip-arm exists yet, so a fresh unarmed grid shows unlocked).

- [ ] **Step 3: Wire save-on-complete and boot skip-arm**

In `courses/static/courses/js/switchgrid.js`, in `submit`'s `.then` callback, change:

```js
      .then(function (data) {
        paint(root, data.cells || []);
        summarize(root, !!data.correct);
        if (data.correct) lock(root);
      })
```
to
```js
      .then(function (data) {
        paint(root, data.cells || []);
        summarize(root, !!data.correct);
        if (data.correct) {
          lock(root);
          window.libliState.saveFlag(root, { done: true });
        }
      })
```

Replace `initOne`:

```js
  function initOne(root) {
    if (root.dataset.switchgridReady === "1") return;
    root.dataset.switchgridReady = "1";
    root.querySelectorAll("[data-switchgrid-cycler]").forEach(function (cyc) {
      cyc.addEventListener("click", function () { advance(cyc); });
    });
    var btn = root.querySelector(".switchgrid__confirm");
    if (btn) btn.addEventListener("click", function () { submit(root); });
    // KaTeX auto-render (mirror switchgate.js's typeset call exactly)
    if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
  }
```
with
```js
  function initOne(root) {
    if (root.dataset.switchgridReady === "1") return;
    root.dataset.switchgridReady = "1";
    if (window.libliState.storedFlag(root, "done")) {
      // Server rendered it locked; do NOT arm cyclers/Confirm. Typeset THEN
      // return -- .switchgrid is excluded from math.js's global
      // renderInlineText list, so this file's own call is the ONLY thing
      // that typesets its math (mirrors switchgate.js's boot short-circuit).
      if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
      return;
    }
    root.querySelectorAll("[data-switchgrid-cycler]").forEach(function (cyc) {
      cyc.addEventListener("click", function () { advance(cyc); });
    });
    var btn = root.querySelector(".switchgrid__confirm");
    if (btn) btn.addEventListener("click", function () { submit(root); });
    // KaTeX auto-render (mirror switchgate.js's typeset call exactly)
    if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
  }
```

- [ ] **Step 4: Run the e2e to verify it passes**

Run (foreground): `uv run pytest tests/test_e2e_switchgrid.py -m e2e -k "persists_across_reload or persists_nothing or isolation_no_pageerror or typesets_math_on_load or nested_in_tab" -q`
Expected: PASS (all five).

- [ ] **Step 5: Falsify the typeset-before-return guard**

Temporarily remove the `renderMathInElement` call from the skip-arm branch (leave the bare `return;`) and re-run `test_switchgrid_stored_done_typesets_math_on_load`. Expected: RED (raw `\(+\)` remains, no `.katex` node). Revert.

- [ ] **Step 6: Run the full existing switch-grid e2e file to confirm no regression**

Run (foreground): `uv run pytest tests/test_e2e_switchgrid.py -m e2e -q`
Expected: PASS (the two pre-existing correct/incorrect-path tests plus the editor-authoring tests, unaffected).

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/switchgrid.js tests/test_e2e_switchgrid.py
git commit -m "feat(switchgrid): persist {done:true} on all-correct; skip-arm + typeset on restore"
```

---

### Task 9: `filltable.js` — save on complete, skip-arm + typeset on boot

**Files:**
- Modify: `courses/static/courses/js/filltable.js`
- Modify (test): `tests/test_e2e_filltable.py`

**Interfaces:**
- Consumes: `.filltable` div with `data-state`, `data-state-url`, `data-element-pk` (Task 6); `window.libliState` (Task 7).
- Produces: on an all-correct Check, `window.libliState.saveFlag(root, {done: true})`; on boot, a stored-done table is not armed but its math IS typeset first (`.el--filltable` is excluded from `math.js`'s global list, same as `.switchgrid`/`.switchgate`).

- [ ] **Step 1: Write the failing e2e tests**

Append to `tests/test_e2e_filltable.py`:

```python
def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- fixture SETUP (a
    precondition of the reload gesture under test), not a bypassed gesture."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save(update_fields=["element_state"])


def _seed_tab1(unit, tab1_children):
    """One TabsElement on `unit` (tabs 'First'/'Second'); `tab1_children` is a
    list of concrete element objects placed, in order, nested under tab 1."""
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "First"},
                {"id": "t000002", "label": "Second"},
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=obj)
    for child in tab1_children:
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id="t000001"
        )
    return join


@pytest.mark.django_db(transaction=True)
def test_filltable_correct_value_persists_across_reload(page, live_server):
    """Real gesture: fill the correct value, Check, await the state POST,
    reload -> still locked/correct, Check gone, the value stays shown."""
    _student, unit = _new_unit("ftbl_persist")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_persist")
    page.goto(_unit_url(live_server, unit))

    inp = _answer_input(page)
    inp.fill("4")
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    inp = _answer_input(page)
    expect(_confirm(page)).to_have_count(0)
    expect(inp).to_be_disabled()
    expect(inp).to_have_value("4")
    expect(inp).to_have_class(_CORRECT)
    expect(_summary(page)).to_have_class(_SUCCESS)


@pytest.mark.django_db(transaction=True)
def test_filltable_wrong_value_persists_nothing(page, live_server):
    """A wrong Check makes NO state POST; reload -> fresh, editable, unlocked."""
    _student, unit = _new_unit("ftbl_wrong_nosave")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_wrong_nosave")
    page.goto(_unit_url(live_server, unit))

    saw_state_post = {"hit": False}
    page.on(
        "request",
        lambda r: saw_state_post.__setitem__(
            "hit", saw_state_post["hit"] or "/state/" in r.url
        ),
    )
    inp = _answer_input(page)
    inp.fill("9")
    _confirm(page).click()
    expect(_summary(page)).to_have_class(_RETRY)
    assert saw_state_post["hit"] is False

    page.reload()
    expect(_confirm(page)).to_be_visible()
    expect(_answer_input(page)).to_be_enabled()


@pytest.mark.django_db(transaction=True)
def test_filltable_stored_done_typesets_math_on_load(page, live_server):
    """.el--filltable is excluded from math.js's global renderInlineText list;
    on restore, filltable.js's OWN boot short-circuit must typeset the static
    cell's math before returning."""
    from courses.models import FillTableElement

    student, unit = _new_unit("ftbl_math_restore")
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": r"\(x<5\)"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    el.save()
    row = add_element(unit, el)
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    _login(page, live_server, "ftbl_math_restore")
    page.goto(_unit_url(live_server, unit))

    math_node = page.locator(".filltable .katex")
    expect(math_node).to_have_count(1)
    assert "\\(" not in page.locator(".filltable").inner_text()


@pytest.mark.django_db(transaction=True)
def test_filltable_nested_in_tab_restores_after_reload(page, live_server):
    """Fill-in table is in NESTABLE_TYPE_KEYS -- nested inside a Tabs panel. The
    widget JS's root-scoped lookups and the server render must restore
    correctly inside a tab panel exactly as at top level."""
    from courses.models import Element
    from courses.models import FillTableElement

    student, unit = _new_unit("ftbl_tabs")
    el = FillTableElement(
        data={
            "cells": [
                [{"kind": "static", "html": "a"}, {"kind": "answer", "answer": "4"}]
            ]
        }
    )
    el.save()
    join = _seed_tab1(unit, [el])
    row = Element.objects.get(parent=join, content_type__model="filltableelement")
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    _login(page, live_server, "ftbl_tabs")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    inp = page.locator('.filltable__input[data-r="0"][data-c="1"]')
    expect(inp).to_have_value("4")
    expect(inp).to_be_disabled()
```

- [ ] **Step 2: Run the e2e to verify it fails**

Run (foreground): `uv run pytest tests/test_e2e_filltable.py -m e2e -k "persists_across_reload or persists_nothing or typesets_math_on_load or nested_in_tab" -q`
Expected: FAIL — no state POST yet, no restore.

- [ ] **Step 3: Wire save-on-complete and boot skip-arm**

In `courses/static/courses/js/filltable.js`, in `submit`'s `.then` callback, change:

```js
      .then(function (data) {
        paint(root, data.cells || []);
        summarize(root, !!data.all_correct);
        if (data.all_correct === true && (data.cells || []).length > 0) lock(root);
      })
```
to
```js
      .then(function (data) {
        paint(root, data.cells || []);
        summarize(root, !!data.all_correct);
        if (data.all_correct === true && (data.cells || []).length > 0) {
          lock(root);
          window.libliState.saveFlag(root, { done: true });
        }
      })
```

Replace `initOne`:

```js
  function initOne(root) {
    if (root.dataset.filltableReady === "1") return;
    root.dataset.filltableReady = "1";
    var btn = root.querySelector(".filltable__confirm");
    if (btn) btn.addEventListener("click", function () { submit(root); });
    // KaTeX auto-render (mirror switchgrid.js's typeset call exactly)
    if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
  }
```
with
```js
  function initOne(root) {
    if (root.dataset.filltableReady === "1") return;
    root.dataset.filltableReady = "1";
    if (window.libliState.storedFlag(root, "done")) {
      // Server rendered it locked; do NOT arm Check. Typeset THEN return --
      // .el--filltable is excluded from math.js's global renderInlineText
      // list, so this file's own call is the ONLY thing that typesets its
      // static cells' math (mirrors switchgrid.js's boot short-circuit).
      if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
      return;
    }
    var btn = root.querySelector(".filltable__confirm");
    if (btn) btn.addEventListener("click", function () { submit(root); });
    // KaTeX auto-render (mirror switchgrid.js's typeset call exactly)
    if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
  }
```

- [ ] **Step 4: Run the e2e to verify it passes**

Run (foreground): `uv run pytest tests/test_e2e_filltable.py -m e2e -k "persists_across_reload or persists_nothing or typesets_math_on_load or nested_in_tab" -q`
Expected: PASS (all four).

- [ ] **Step 5: Falsify the typeset-before-return guard**

Temporarily remove the `renderMathInElement` call from the skip-arm branch and re-run `test_filltable_stored_done_typesets_math_on_load`. Expected: RED (raw `\(x<5\)` remains). Revert.

- [ ] **Step 6: Run the full existing fill-table e2e file to confirm no regression**

Run (foreground): `uv run pytest tests/test_e2e_filltable.py -m e2e -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/filltable.js tests/test_e2e_filltable.py
git commit -m "feat(filltable): persist {done:true} on all-correct; skip-arm + typeset on restore"
```

---

### Task 10: `guessnumber.js` — save on correct, skip-arm on boot

**Files:**
- Modify: `courses/static/courses/js/guessnumber.js`
- Modify (test): `tests/test_e2e_guessnumber.py`

**Interfaces:**
- Consumes: `.guessnumber` div with `data-state`, `data-state-url`, `data-element-pk` (Task 5); `window.libliState` (Task 7).
- Produces: on a correct guess, `window.libliState.saveFlag(root, {done: true})`; on boot, a stored-done element is not armed. **No typeset call needed** — `.guessnumber` IS in `math.js`'s global `renderInlineText` list (`courses/static/courses/js/math.js:31`), unlike `.switchgrid`/`.filltable`/`.switchgate`. **No `preventDefault` Enter guard needed** — `guessnumber.js` uses no `<form>` (a dependency check, not a code change).

- [ ] **Step 1: Dependency check — confirm `guessnumber.js` still has no `<form>`**

Run: `uv run pytest tests/test_guessnumber_render.py -q -k test_renders_contract_hooks`
Expected: PASS, including its `assert "<form" not in html` and `assert 'type="submit"' not in html` lines (unaffected by Task 5's tag widening — the un-done branch is byte-identical). This confirms the gate slice's `preventDefault`-only Enter guard is **not** required here: a restored `readonly` input with no `<form>` cannot implicitly submit/navigate on Enter.

- [ ] **Step 2: Write the failing e2e tests**

Append to `tests/test_e2e_guessnumber.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_correct_guess_persists_across_reload(page, live_server):
    """Real gesture: guess correctly, await the state POST, reload -> input
    still shows the canonical target, readonly, is-correct, done, Check gone."""
    _student, unit = _new_unit("gn_persist")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_persist")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()
    _input(page).fill("42")
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _check(page).click()
    assert resp_info.value.ok

    page.reload()
    expect(_input(page)).to_have_value("42")
    expect(_input(page)).to_have_js_property("readOnly", True)
    expect(_input(page)).to_have_class(re.compile(r"\bis-correct\b"))
    expect(_root(page)).to_have_class(re.compile(r"\bguessnumber--done\b"))
    expect(_check(page)).to_have_count(0)
    expect(_success(page)).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_wrong_guess_persists_nothing(page, live_server):
    """A wrong guess makes NO state POST; reload -> fresh, editable, unlocked."""
    _student, unit = _new_unit("gn_wrong_nosave")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_wrong_nosave")
    page.goto(_unit_url(live_server, unit))

    saw_state_post = {"hit": False}
    page.on(
        "request",
        lambda r: saw_state_post.__setitem__(
            "hit", saw_state_post["hit"] or "/state/" in r.url
        ),
    )
    _input(page).fill("43")
    _check(page).click()
    expect(_hint(page)).to_be_visible()
    assert saw_state_post["hit"] is False

    page.reload()
    expect(_check(page)).to_be_visible()
    expect(_input(page)).to_have_value("")
    expect(_input(page)).to_have_js_property("readOnly", False)


@pytest.mark.django_db(transaction=True)
def test_restored_guessnumber_does_not_repost_on_enter(page, live_server):
    """Skip-arm guard: a restored (already-done) element must not re-arm its
    keydown-Enter submit path. Without the skip-arm branch, initOne's `done`
    local starts false regardless of server state, so Enter would call submit()
    again and fire a redundant check POST against an already-locked element."""
    student, unit = _new_unit("gn_restore_enter")
    row = add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    _login(page, live_server, "gn_restore_enter")
    page.goto(_unit_url(live_server, unit))

    expect(_input(page)).to_have_js_property("readOnly", True)
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    _input(page).focus()
    _input(page).press("Enter")
    page.wait_for_timeout(150)  # allow any (wrongly) queued POST to start
    assert posts == []
```

Also add the `_seed_state` helper this new test uses (mirroring the pattern in `tests/test_e2e_fillgate.py`), near the other seed helpers:

```python
def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- fixture SETUP (a
    precondition of the reload gesture under test), not a bypassed gesture."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save(update_fields=["element_state"])
```

- [ ] **Step 3: Run the e2e to verify it fails**

Run (foreground): `uv run pytest tests/test_e2e_guessnumber.py -m e2e -k "persists_across_reload or persists_nothing or restored_guessnumber_does_not_repost" -q`
Expected: FAIL on two of the three. `test_correct_guess_persists_across_reload` times out on `expect_response` (no state POST yet). `test_restored_guessnumber_does_not_repost_on_enter` also fails: the server already renders the input `readonly` and omits `[data-guess-check]` (Task 5), but the OLD `initOne` unconditionally binds `input.addEventListener("keydown", ...)` regardless of whether `check` exists, so pressing Enter still calls `submit()` — `done` is a fresh local `false`, `input.value` is the server-filled "42", so it POSTs to the check endpoint and `assert posts == []` fails. `test_wrong_guess_persists_nothing` already passes (unaffected by this task).

- [ ] **Step 4: Wire save-on-correct and boot skip-arm**

In `courses/static/courses/js/guessnumber.js`, in `submit`'s correct branch, change:

```js
          if (d.correct) {
            done = true;
            hint.hidden = true;
            success.hidden = false;
            input.classList.remove("is-wrong");
            input.classList.add("is-correct");
            input.readOnly = true;
            if (check) check.remove(); // Check is spent (as fillgate/switchgate do)
            root.classList.add("guessnumber--done");
          } else {
```
to
```js
          if (d.correct) {
            done = true;
            hint.hidden = true;
            success.hidden = false;
            input.classList.remove("is-wrong");
            input.classList.add("is-correct");
            input.readOnly = true;
            if (check) check.remove(); // Check is spent (as fillgate/switchgate do)
            root.classList.add("guessnumber--done");
            window.libliState.saveFlag(root, { done: true });
          } else {
```

In `initOne`, add the skip-arm branch immediately after the existing preview no-op guard:

```js
    var pk = root.getAttribute("data-element-pk");
    var url = root.getAttribute("data-check-url");
    if (pk === "0" || !url) return; // unsaved editor preview: no-op
    if (check) check.hidden = false; // arm Check now that JS is live
```
becomes
```js
    var pk = root.getAttribute("data-element-pk");
    var url = root.getAttribute("data-check-url");
    if (pk === "0" || !url) return; // unsaved editor preview: no-op

    if (window.libliState.storedFlag(root, "done")) {
      // Server already rendered the locked/correct appearance (readonly
      // value, is-correct, success shown, Check omitted). No typeset call is
      // needed here -- unlike .switchgrid/.filltable/.switchgate, .guessnumber
      // IS in math.js's global renderInlineText list (math.js:31).
      return;
    }

    if (check) check.hidden = false; // arm Check now that JS is live
```

- [ ] **Step 5: Run the e2e to verify it passes**

Run (foreground): `uv run pytest tests/test_e2e_guessnumber.py -m e2e -k "persists_across_reload or persists_nothing or restored_guessnumber_does_not_repost" -q`
Expected: PASS (all three).

- [ ] **Step 6: Falsify the skip-arm guard**

Temporarily delete the `if (window.libliState.storedFlag(root, "done")) { return; }` branch entirely (letting `initOne` fall through to its normal arming path even on a restored element) and re-run `test_restored_guessnumber_does_not_repost_on_enter`. Expected: RED — the keydown-Enter listener is bound unconditionally again, so pressing Enter on the restored (readonly, already-done) input calls `submit()` and POSTs to the check endpoint, and `assert posts == []` fails. Revert.

- [ ] **Step 7: Run the full existing guess-number e2e file to confirm no regression**

Run (foreground): `uv run pytest tests/test_e2e_guessnumber.py -m e2e -q`
Expected: PASS (all ten pre-existing cases plus the three new ones).

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/guessnumber.js tests/test_e2e_guessnumber.py
git commit -m "feat(guessnumber): persist {done:true} on correct; skip-arm on restore"
```

---

### Task 11: Definition of Done — Start-fresh restore, full regression, visual check

**Files:**
- Modify (test): `courses/tests/test_progress_reset.py`

**Interfaces:**
- None new — verification + one regression test tying `progress_reset` to the new `{"done": true}` blob.

- [ ] **Step 1: Write the failing "Start fresh clears a done self-check" test**

Append to `courses/tests/test_progress_reset.py`:

```python
def test_post_clears_done_selfcheck_state_and_lesson_restores_fresh(client):
    """[[student-practice-state-graded-selfchecks-restore]] Start-fresh must clear
    a graded self-check's {"done": true} blob too -- mirrors the MarkDone
    coverage above, extended through the lesson view to prove the WIDGET, not
    just the row, comes back fresh."""
    from courses.models import SwitchGridElement

    course, unit = make_course_with_unit()
    grid = SwitchGridElement.objects.create(
        prompt="",
        lines=[{"stem": "pick", "cyclers": [{"options": ["a", "b"], "answer": 1}]}],
    )
    row = add_element(unit, grid)
    student = make_verified_user(username="gsc_reset", email="gsc_reset@school.edu")
    Enrollment.objects.create(student=student, course=course)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"done": True}}
    )
    client.force_login(student)

    r = client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 302
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {}

    body = client.get(
        reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    ).content.decode()
    assert 'data-state="{}"' in body
    assert "switchgrid--locked" not in body
    assert "switchgrid__confirm" in body
```

Run: `uv run pytest courses/tests/test_progress_reset.py -q -k done_selfcheck`
Expected: FAIL before Tasks 1/4 are applied (n/a at this point in the plan — this is the DoD, so it should already PASS given Tasks 1-10 are done; if it fails here, one of the earlier tasks has a regression — treat this as a genuine bug, not a step to "make pass" by weakening the assertion).

- [ ] **Step 2: Run it and confirm PASS**

Run: `uv run pytest courses/tests/test_progress_reset.py -q`
Expected: PASS, full file including the new test.

- [ ] **Step 3: Full non-e2e suite**

Run: `uv run pytest -n auto -q`
Expected: PASS, no regressions. (Baseline should be green before this branch; compare counts.)

- [ ] **Step 4: The five e2e files (foreground, `-m e2e`)**

Run each foreground (never backgrounded):
```
uv run pytest tests/test_e2e_switchgrid.py -m e2e -q
uv run pytest tests/test_e2e_filltable.py -m e2e -q
uv run pytest tests/test_e2e_guessnumber.py -m e2e -q
uv run pytest tests/test_e2e_fillgate.py -m e2e -q
uv run pytest tests/test_e2e_switchgate.py -m e2e -q
```
Expected: PASS. The last two guard the Task 7 `libliState` refactor against the two gates.

- [ ] **Step 5: Lint, format, migration & system checks**

Run:
```
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check
uv run python manage.py check
```
Expected: all clean; `makemigrations --check` reports no changes (this slice adds none).

- [ ] **Step 6: Visual no-flash check (per verify-ui-with-screenshots)**

Screenshot a stored-done Switch grid, Fill-in table, and Guess-the-number on load (light + dark theme), each seeded via `_seed_state`. Confirm each shows its fully-locked, all-green completed appearance immediately (correct option/cell/value visible, Confirm/Check gone, summary/success text shown) with no flash of an editable/unlocked widget.

- [ ] **Step 7: Confirm the main checkout is clean**

If executing in an isolated worktree, run `git status --short` **from the primary (non-worktree) checkout** — the repo path the worktree branched from — to confirm no stray edits leaked outside the worktree (subagents can write outside their stated cwd). If executing directly on `master` (no worktree), run `git status --short` in the repo root and confirm only the intended files are modified.
Expected: only the intended files changed.

---

## Self-review notes (author)

- **Spec coverage:** §1 (`_val_done`, three keys) → Task 1. §2 (`canonical_cells`, `canonical_target`) → Tasks 2, 3. §3 (render-path gap: `render_switch_grid`/`render_guess_number` widening, `filltableelement.html` locked branch, bounds-safety, no-self.data-mutation, unanswered-path byte-invariant) → Tasks 4, 5, 6. §4 (`window.libliState`, load-order gate, gate refactor) → Task 7. §5 (save-on-complete, boot skip-arm, typeset-before-return gotcha, no Enter-guard-needed dependency check) → Tasks 8, 9, 10. Testing section (validator/monotone tests, canonical-answer tests, lesson-view locked render, summarize/is-correct reproduction, bounds-safety, e2e round-trips, wrong/no-save, `libliState` isolation, gate regression, nested-in-tabs, Start-fresh, regression/visual DoD) → distributed across all eleven tasks, closing in Task 11.
- **Monotone-blob invariant** upheld throughout: no task stores anything but `{"done": true}`; every displayed answer (`SwitchGridElement.answer` index, `FillTableElement.canonical_cells`, `GuessNumberElement.canonical_target`) is rendered server-side from the element's own fields on every request.
- **Int/str key seam** handled per the sibling slice's precedent: all server-rendered-locked-appearance tests go through `client.get` on the real lesson view (str-keyed `UnitProgress` seed, int-coerced by `build_lesson_context`), never `obj.render()` with a str key. The one exception — Task 6's self-data-mutation guard — deliberately calls `obj.render()` directly with an **int**-keyed dict, which is `render()`'s own documented contract, not the JSON-serialization str/int seam; this is called out explicitly in that test file's docstring and Task 6's Interfaces line so a reviewer doesn't mistake it for the forbidden pattern.
- **Typeset-before-return gotcha** (PR #147's Round-1 catch for `.switchgate`) is explicitly re-derived here for `.switchgrid` and `.el--filltable` (both excluded from `math.js`'s global `renderInlineText` list, confirmed by reading `courses/static/courses/js/math.js:31`) and explicitly ruled OUT for `.guessnumber` (which IS in that list) — Task 10 Step 1 is a dependency check, not an assumption.
- **Falsifiability**: every new guard (validator registration, bounds-safety, autoescape, no-mutation, six-flag OR, typeset-before-return, skip-arm) has a named falsification step in the task that introduces it, per the doctrine — neutralize, confirm RED, revert.
- **Global Constraints re-verified**: no task touches `ELEMENT_MODELS`, adds a migration, or introduces a new user-visible string (every label used — `Check`, `Confirm`, `Great!`, `Try again`, `Correct!`, `Your answer` — already exists in the pre-slice codebase, confirmed by reading the current `render_switch_grid`/`render_guess_number`/`filltableelement.html`).
- **Type/name consistency**: `is_done` (Python tag-locals), `mine.done` (template/JS blob key), `window.libliState.storedFlag(el, "done")` / `saveFlag(el, {done: true})` (JS) are used consistently across Tasks 4/5/6/8/9/10 — no stray `mine.open` or `is_open` leaked from the gate-slice naming into this one.
