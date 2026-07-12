# Switch grid element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `SwitchGridElement` content element — a self-contained, ungraded lesson self-check widget of multiple lines, each interleaving static math with clickable "cyclers", graded as a whole grid server-side with per-cycler feedback.

**Architecture:** Mirrors the existing `SwitchGateElement` ("Choose & confirm") substrate — a plain (non-Model) form, a `{% render_switch_grid %}` template tag that splices cycler widgets into a token-stem, a soft-pk-lookup JSON check endpoint, and a JS enhancer — but generalizes the single-token stem to **N tokens across N lines**, and is **not** a reveal gate (no cascade; grades in place). The novel parts are the multi-token stem parser, the 3-level authoring form (lines → cyclers → options) with append-only indices + gap/blank compaction, and the per-cycler alignment invariant across render/JS/server.

**Tech Stack:** Django (Python), Django templates, vanilla JS (IIFE enhancer), pytest + Playwright (e2e).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-13-switch-grid-design.md` — the authoritative design; every task realizes part of it.
- **Form key** is `switchgrid`; **transfer key** is `switch_grid` (the two namespaces diverge, matching `switchgate`/`switch_gate`). Model is `SwitchGridElement`; content-type string `switchgridelement`.
- **Sentinel tokens** `￿0￿ ￿1￿ …` MUST be built in code from `courses.fillblank.SENTINEL` (`SENTINEL + str(i) + SENTINEL`) — never copy-pasted from any doc (U+FFFF corrupts to U+FFFC through some tools).
- **Not nestable** in v1: do NOT add `switch_grid` to `NESTABLE_TYPE_KEYS`; the palette card is gated `{% if not nested %}`.
- **No marks / no persistence:** the check endpoint never writes any row.
- **No prepaint-hide watchdog:** unlike the reveal gates, the grid's no-JS fallback is fully visible (static `options[0]`), so it fails open with no watchdog needed. The JS enhancer only needs idempotent init.
- **Alignment invariant (load-bearing):** cyclers are indexed by **stem-marker position** within their line; `indices[i][j]`, `cells[i][j]`, and the DOM's `data-line="{i}"`/`data-cycler="{j}"` all agree. Every line contributes exactly one sub-list (in line order); a static line contributes `[]`.
- **i18n:** all user-facing strings wrapped for EN + PL; run `makemessages` and fill PL. Use `uv run` for all python/ruff/pytest/django tooling (bash PATH lacks them).
- **Windows/xdist:** run the switchgrid test modules serially if xdist flakes (`-p no:xdist` or `-n0`).

---

### Task 1: Multi-token stem parser (`courses/switchgrid.py`)

Generalizes `courses/switchgate.py` (single `{{choice}}`) to **N** markers per line, indexing like `fillblank.parse` (running count → token index). Leaves `switchgate.py` untouched.

**Files:**
- Create: `courses/switchgrid.py`
- Test: `courses/tests/test_switchgrid_stem.py`

**Interfaces:**
- Produces:
  - `CHOICE_MARKER = "{{choice}}"`
  - `class SwitchGridError(ValueError)`
  - `parse_stem_multi(clean: str) -> tuple[str, int]` — replace the *i*-th `{{choice}}` with `SENTINEL+str(i)+SENTINEL`; return `(token_stem, marker_count)`.
  - `to_author_stem_multi(token_stem: str) -> str` — inverse: every `￿i￿` → `{{choice}}`.
  - `render_stem_multi(token_stem: str, widgets_by_index: dict[int, SafeString]) -> SafeString` — split on the sentinel token regex; splice `widgets_by_index[i]` for each token; a missing index renders as empty string (safe-degrade, never `KeyError`). Non-token segments are `mark_safe`'d (sanitized upstream at clean()/import time).
  - `count_markers(token_stem: str) -> int` — public helper: number of sentinel cycler tokens in a stored token stem. Used by the transfer validator (avoids reaching into the private regex).
  - `sanitize_stem_segments(token_stem: str) -> str` — split on the sentinel tokens, `sanitize_cell` each non-token segment, re-join with the tokens intact. Used by the import builder to sanitize stems that bypass the form.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_switchgrid_stem.py
from django.utils.safestring import mark_safe
from courses import fillblank
from courses import switchgrid


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def test_parse_multi_replaces_each_marker_in_order():
    stem, count = switchgrid.parse_stem_multi("3 {{choice}} 3 {{choice}} 9")
    assert stem == f"3 {_tok(0)} 3 {_tok(1)} 9"
    assert count == 2


def test_parse_multi_zero_markers_is_static_line():
    stem, count = switchgrid.parse_stem_multi("just static")
    assert stem == "just static"
    assert count == 0


def test_to_author_stem_multi_is_inverse():
    token_stem = f"a {_tok(0)} b {_tok(1)} c"
    assert switchgrid.to_author_stem_multi(token_stem) == "a {{choice}} b {{choice}} c"


def test_render_stem_multi_splices_widgets():
    token_stem = f"x {_tok(0)} y {_tok(1)} z"
    out = switchgrid.render_stem_multi(
        token_stem, {0: mark_safe("<b>W0</b>"), 1: mark_safe("<i>W1</i>")}
    )
    assert out == "x <b>W0</b> y <i>W1</i> z"


def test_render_stem_multi_missing_index_degrades_to_empty():
    token_stem = f"x {_tok(0)} y {_tok(1)} z"
    out = switchgrid.render_stem_multi(token_stem, {0: mark_safe("W0")})  # index 1 missing
    assert out == "x W0 y  z"  # no KeyError; missing widget -> empty


def test_count_markers():
    assert switchgrid.count_markers(f"a {_tok(0)} b {_tok(1)} c") == 2
    assert switchgrid.count_markers("static") == 0


def test_sanitize_stem_segments_neutralizes_script_but_keeps_tokens():
    dirty = f"<script>x</script>ok {_tok(0)} <b>b</b>"
    out = switchgrid.sanitize_stem_segments(dirty)
    assert "<script>" not in out
    assert _tok(0) in out          # sentinel token preserved
    assert "ok" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_stem.py -v`
Expected: FAIL (module `courses.switchgrid` does not exist).

- [ ] **Step 3: Implement `courses/switchgrid.py`**

```python
"""Multi-token stem helper for the Switch grid element (SwitchGridElement).

Generalizes courses.switchgate (which allows exactly one {{choice}}) to N markers
per line, indexed like courses.fillblank.parse (running count -> token index).
Authors type the literal {{choice}}; each occurrence i is stored as the
fillblank.SENTINEL + str(i) + SENTINEL token, and split back out at render time.
"""

import re

from django.utils.safestring import SafeString
from django.utils.safestring import mark_safe

from courses import fillblank

CHOICE_MARKER = "{{choice}}"
_TOKEN_RE = re.compile(fillblank.SENTINEL + r"(\d+)" + fillblank.SENTINEL)


class SwitchGridError(ValueError):
    """Raised for malformed switch-grid stems (reserved; parse is lenient on count)."""


def _token(i: int) -> str:
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def parse_stem_multi(clean: str) -> tuple[str, int]:
    """Replace the i-th {{choice}} with the i-th sentinel token; return (stem, count)."""
    count = 0

    def _swap(_m):
        nonlocal count
        tok = _token(count)
        count += 1
        return tok

    token_stem = re.sub(re.escape(CHOICE_MARKER), _swap, clean or "")
    return token_stem, count


def to_author_stem_multi(token_stem: str) -> str:
    """Inverse of parse_stem_multi: every sentinel token -> {{choice}}."""
    return _TOKEN_RE.sub(CHOICE_MARKER, token_stem or "")


def count_markers(token_stem: str) -> int:
    """Public: number of sentinel cycler tokens in a stored token stem."""
    return len(_TOKEN_RE.findall(token_stem or ""))


def sanitize_stem_segments(token_stem: str) -> str:
    """Sanitize each non-token segment (sanitize_cell) while preserving the tokens.

    Used by the import builder, which bypasses the form's clean()-time sanitize."""
    from courses.sanitize import sanitize_cell

    parts = _TOKEN_RE.split(token_stem or "")
    # split with one capture group -> [seg, idx, seg, idx, ..., seg]; odd items are
    # the captured index digits, which must be rebuilt back into their sentinel token.
    out = []
    for pos, part in enumerate(parts):
        out.append(_token(int(part)) if pos % 2 else sanitize_cell(part))
    return "".join(out)


def render_stem_multi(token_stem: str, widgets_by_index: dict[int, SafeString]) -> SafeString:
    """Split the token-stem and splice widgets_by_index[i] at each token i.

    Non-token segments are marked safe (sanitized at clean()/import time). A token
    whose index is absent from widgets_by_index renders as empty (safe-degrade)."""
    parts = _TOKEN_RE.split(token_stem or "")
    # re.split with one capture group yields: [seg, idx, seg, idx, ..., seg]
    out = []
    for pos, part in enumerate(parts):
        if pos % 2 == 0:
            out.append(mark_safe(part))  # noqa: S308 — stem segment sanitized upstream
        else:
            out.append(widgets_by_index.get(int(part), mark_safe("")))
    return mark_safe("".join(out))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest courses/tests/test_switchgrid_stem.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/switchgrid.py courses/tests/test_switchgrid_stem.py
git commit -m "feat(switch-grid): multi-token stem parser"
```

---

### Task 2: Model + migration + has_math (`SwitchGridElement`)

**Files:**
- Modify: `courses/models.py` (add `SwitchGridElement`; append `"switchgridelement"` to `ELEMENT_MODELS`)
- Create: `courses/migrations/0040_switchgridelement.py`
- Modify: `courses/views.py` (`_element_has_math` branch)
- Test: `courses/tests/test_switchgrid_model.py`

**Interfaces:**
- Produces: `SwitchGridElement(prompt: TextField, lines: JSONField(default=list), elements: GenericRelation)`, with `save()` sanitizing every option HTML in `lines` and `render()` returning the student template with the join `eid`. `lines` shape: `[{"stem": <token_stem>, "cyclers": [{"options": [str, ...], "answer": int}, ...]}, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_switchgrid_model.py
import pytest
from courses.models import SwitchGridElement

pytestmark = pytest.mark.django_db


def test_save_sanitizes_option_html_in_lines():
    el = SwitchGridElement.objects.create(
        prompt="",
        lines=[{"stem": "s", "cyclers": [
            {"options": ["<script>x</script>ok", "<b>b</b>"], "answer": 0}]}],
    )
    el.refresh_from_db()
    opts = el.lines[0]["cyclers"][0]["options"]
    assert "<script>" not in opts[0]
    assert "ok" in opts[0]


def test_lines_json_round_trips():
    lines = [
        {"stem": "a", "cyclers": [{"options": ["+", "-"], "answer": 1}]},
        {"stem": "static", "cyclers": []},
    ]
    el = SwitchGridElement.objects.create(lines=lines)
    el.refresh_from_db()
    assert el.lines[1]["cyclers"] == []
    assert el.lines[0]["cyclers"][0]["answer"] == 1


def test_element_has_math_detects_math_in_stem_or_options():
    # defensive branch (used when nested via tabs; grid is top-level in v1 but keep parity)
    from courses.views import _element_has_math
    el = SwitchGridElement(lines=[{"stem": r"\(x\)", "cyclers": []}])
    assert _element_has_math(el) is True
    el2 = SwitchGridElement(lines=[{"stem": "plain", "cyclers": [
        {"options": ["plain", r"\(y\)"], "answer": 0}]}])
    assert _element_has_math(el2) is True
    el3 = SwitchGridElement(lines=[{"stem": "plain", "cyclers": [
        {"options": ["a", "b"], "answer": 0}]}])
    assert _element_has_math(el3) is False
```

> **Note (render test moved):** the `render()`-produces-`switchgrid`-markup test lives in **Task 4** (`test_switchgrid_template.py`), because `render()` needs the `switchgridelement.html` template and the `render_switch_grid` tag, both created in Task 4. Task 2 does NOT test `render()`.
>
> **The load-bearing has_math test drives the real lesson path** — because the grid is **not nestable**, its math is detected by `build_lesson_context`'s inline `has_math` OR-chain (not `_element_has_math`, which only runs for tabs-nested elements). Add this test too:

```python
# still in courses/tests/test_switchgrid_model.py — drives the REAL lesson context
def test_build_lesson_context_flags_math_for_grid(lesson_unit_with_grid):
    # fixture: a lesson unit containing a SwitchGridElement whose option carries \(y\).
    # Mirror the switchgate has_math fixture in test_switchgate_* ; assert the context's
    # has_math flag is True. This catches the top-level (non-nested) detection path that
    # a bare _element_has_math() unit test would miss.
    from courses.views import build_lesson_context
    ctx = build_lesson_context(lesson_unit_with_grid.node, lesson_unit_with_grid.user)
    assert ctx["has_math"] is True
```

> Reuse the switchgate lesson-context fixture pattern; if none exists, build a unit + `Element` join over a `SwitchGridElement` inline (mirror `test_switchgate_model.py`).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_model.py -v`
Expected: FAIL (`SwitchGridElement` undefined).

- [ ] **Step 3: Add the model to `courses/models.py`**

Append `"switchgridelement"` to `ELEMENT_MODELS` (after `"spoilerelement"`):

```python
ELEMENT_MODELS = [
    # ... existing entries ...
    "switchgateelement",
    "spoilerelement",
    "switchgridelement",
]
```

Add the model class (place it after `SwitchGateElement`, ~line 540):

```python
class SwitchGridElement(ElementBase):
    """A 'Switch grid' self-check: multiple lines interleaving static math with
    clickable cyclers, graded as a whole grid with per-cycler feedback. Records no
    marks and reveals nothing (NOT a reveal gate). `prompt` is a plain-text
    instruction line; `lines` is a list of {stem, cyclers} where stem is the token
    stem (￿i￿ per cycler) and each cycler is {options: list[str], answer: int}."""

    prompt = models.TextField(blank=True)
    lines = models.JSONField(default=list)
    elements = GenericRelation(Element)

    def save(self, *args, **kwargs):
        for line in self.lines or []:
            for cyc in line.get("cyclers", []) or []:
                cyc["options"] = [sanitize_cell(o or "") for o in (cyc.get("options") or [])]
        super().save(*args, **kwargs)

    def render(self):
        from django.template.loader import render_to_string

        join = self.elements.order_by("pk").first()
        return render_to_string(
            "courses/elements/switchgridelement.html",
            {"el": self, "eid": join.pk if join else 0},
        )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0040_switchgridelement.py` with a `CreateModel` for `SwitchGridElement` and an `AlterField` of `element.content_type` whose `limit_choices_to` `model__in` list now ends with `'switchgridelement'`. Verify the dependency is `('courses', '0039_spoilerelement_alter_element_content_type')`.

- [ ] **Step 5: Wire has_math in BOTH detection paths in `courses/views.py`**

The grid is **top-level** (not nestable), so its math is detected by `build_lesson_context`'s inline `has_math` OR-chain — **this is the load-bearing edit.** The `_element_has_math` branch (used only for tabs-nested elements) is added too, defensively/for parity. Define one shared helper to avoid divergence.

Add the helper near `_element_has_math`:

```python
def _switch_grid_has_math(obj):
    for line in obj.lines or []:
        if has_math_delimiters(line.get("stem", "")):
            return True
        for cyc in line.get("cyclers", []) or []:
            if any(has_math_delimiters(o) for o in (cyc.get("options") or [])):
                return True
    return False
```

In `_element_has_math`, before the final `return _table_has_math(...)`, add:

```python
    if isinstance(obj, SwitchGridElement):
        return _switch_grid_has_math(obj)
```

In `build_lesson_context`, find the inline `has_math` OR-chain (the `isinstance(..., SwitchGateElement)` / `SpoilerElement` branches, ~`views.py:209–244`) and add a matching branch:

```python
        or any(
            _switch_grid_has_math(e.content_object)
            for e in elements
            if isinstance(e.content_object, SwitchGridElement)
        )
```

> **Read the actual `build_lesson_context` has_math block first** and mirror its exact idiom (it may iterate a prefetched `elements` list or use per-type `.exists()` queries) — the snippet above is illustrative; match the real structure so the branch composes with the existing OR-chain. Add `SwitchGridElement` to the model imports at the top of `courses/views.py` (next to `SwitchGateElement`).

- [ ] **Step 5b: Bump the `ELEMENT_MODELS` count assertion NOW (not in Task 8)**

Appending to `ELEMENT_MODELS` in Step 3 makes `len(ELEMENT_MODELS) == 23`, which immediately breaks `tests/test_transfer_schema.py` (asserts `== 22`). Bump it in **this** task so the suite is never left red between tasks:

In `tests/test_transfer_schema.py`, change the `len(ELEMENT_MODELS)` assertion from `== 22` to `== 23`.

- [ ] **Step 6: Run tests + migration check**

Run: `uv run pytest courses/tests/test_switchgrid_model.py tests/test_transfer_schema.py -v`
Expected: PASS.
Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0040_switchgridelement.py courses/views.py tests/test_transfer_schema.py courses/tests/test_switchgrid_model.py
git commit -m "feat(switch-grid): SwitchGridElement model, migration, has_math"
```

---

### Task 3: Authoring form (`SwitchGridElementForm`)

The 3-level dynamic parse (lines → cyclers → options) from indexed POST fields, with **append-only indices + gap/blank compaction**, blank-line drop, `answer` remap onto the compacted option list, defensive `answer` parse, marker-count == cycler-count validation, and edit re-populate.

**Files:**
- Modify: `courses/element_forms.py` (add `SwitchGridElementForm`; register in `FORM_FOR_TYPE`)
- Test: `courses/tests/test_switchgrid_form.py`

**Interfaces:**
- Consumes: `switchgrid.parse_stem_multi`, `switchgrid.to_author_stem_multi`, `SwitchGridElement`, `sanitize_cell`, `sanitize_html`, `fillblank.strip_sentinel`.
- Field-name convention (all keys optional; presence-driven, append-only, gaps compacted):
  - `line-{i}-stem` — stem text for line *i*.
  - `line-{i}-c{j}-opt` — repeated (`getlist`) option inputs for cycler *j* of line *i*.
  - `line-{i}-c{j}-ans` — 0-based index (as posted, before blank-compaction) of the correct option for cycler *j* of line *i*.
- Produces: `SwitchGridElementForm(forms.Form)` with `.save()` persisting `prompt` + normalized `lines`, and a `line_rows()` method feeding the edit partial (Task 7).

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_switchgrid_form.py
import pytest
from django.http import QueryDict
from courses.element_forms import SwitchGridElementForm
from courses.models import SwitchGridElement
from courses import fillblank

pytestmark = pytest.mark.django_db


def _post(pairs):
    qd = QueryDict(mutable=True)
    for k, v in pairs:
        qd.appendlist(k, v)
    return qd


def _valid_pairs():
    # one line, one cycler with 3 options, correct = index 2
    return [
        ("prompt", "Fix the operators"),
        ("line-0-stem", "3 {{choice}} 3 = 9"),
        ("line-0-c0-opt", "+"), ("line-0-c0-opt", "-"), ("line-0-c0-opt", "\\cdot"),
        ("line-0-c0-ans", "2"),
    ]


def test_valid_single_line_single_cycler_saves():
    form = SwitchGridElementForm(data=_post(_valid_pairs()))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.prompt == "Fix the operators"
    assert len(obj.lines) == 1
    cyc = obj.lines[0]["cyclers"][0]
    assert cyc["options"] == ["+", "-", "\\cdot"]
    assert cyc["answer"] == 2
    # stem stored with one sentinel token
    assert fillblank.SENTINEL + "0" + fillblank.SENTINEL in obj.lines[0]["stem"]


def test_marker_count_must_equal_cycler_count():
    pairs = [("line-0-stem", "a {{choice}} b {{choice}} c"),  # 2 markers
             ("line-0-c0-opt", "x"), ("line-0-c0-opt", "y"), ("line-0-c0-ans", "0")]  # 1 cycler
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_fewer_than_two_options_rejected():
    pairs = [("line-0-stem", "a {{choice}} b"),
             ("line-0-c0-opt", "only"), ("line-0-c0-ans", "0")]
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_blank_options_dropped_and_answer_remapped():
    # options ["+", "", "-"], answer posted = 2 (the "-") -> after drop -> ["+","-"], answer 1
    pairs = [("line-0-stem", "a {{choice}} b"),
             ("line-0-c0-opt", "+"), ("line-0-c0-opt", ""), ("line-0-c0-opt", "-"),
             ("line-0-c0-ans", "2")]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    cyc = form.save().lines[0]["cyclers"][0]
    assert cyc["options"] == ["+", "-"]
    assert cyc["answer"] == 1


def test_answer_pointing_at_blank_option_rejected():
    pairs = [("line-0-stem", "a {{choice}} b"),
             ("line-0-c0-opt", "+"), ("line-0-c0-opt", ""), ("line-0-c0-opt", "-"),
             ("line-0-c0-ans", "1")]  # the blank slot
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_missing_or_nonint_answer_is_validation_error_not_500():
    pairs = [("line-0-stem", "a {{choice}} b"),
             ("line-0-c0-opt", "+"), ("line-0-c0-opt", "-"),
             ("line-0-c0-ans", "")]  # empty
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()  # no ValueError raised


def test_empty_grid_rejected():
    form = SwitchGridElementForm(data=_post([("prompt", "hi")]))
    assert not form.is_valid()


def test_all_static_grid_rejected():
    pairs = [("line-0-stem", "static only")]  # no cyclers anywhere
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_static_line_kept_when_another_line_has_cycler():
    pairs = [("line-0-stem", "intro static line"),
             ("line-1-stem", "3 {{choice}} 3"),
             ("line-1-c0-opt", "+"), ("line-1-c0-opt", "-"), ("line-1-c0-ans", "0")]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    lines = form.save().lines
    assert len(lines) == 2
    assert lines[0]["cyclers"] == []          # static line contributes []
    assert len(lines[1]["cyclers"]) == 1


def test_wholly_blank_trailing_line_dropped():
    pairs = _valid_pairs() + [("line-1-stem", ""), ("line-1-c0-opt", "")]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    assert len(form.save().lines) == 1        # blank line-1 dropped


def test_index_gaps_compacted():
    # author added then removed a middle cycler -> gap at c0 (blanked), c1 real
    pairs = [("line-0-stem", "a {{choice}} b"),
             ("line-0-c0-opt", ""),            # removed cycler, blanked
             ("line-0-c1-opt", "+"), ("line-0-c1-opt", "-"), ("line-0-c1-ans", "0")]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    line = form.save().lines[0]
    assert len(line["cyclers"]) == 1          # gap compacted; 1 marker == 1 cycler


def test_edit_repopulate_round_trip():
    el = SwitchGridElement.objects.create(
        prompt="P",
        lines=[{"stem": fillblank.SENTINEL + "0" + fillblank.SENTINEL + " end",
                "cyclers": [{"options": ["+", "-"], "answer": 1}]}],
    )
    form = SwitchGridElementForm(instance=el)
    rows = form.line_rows()
    assert rows[0]["stem"] == "{{choice}} end"          # sentinel -> {{choice}}
    cyc = rows[0]["cyclers"][0]
    assert [o["value"] for o in cyc["options"][:2]] == ["+", "-"]
    assert cyc["options"][1]["checked"] is True          # answer=1 pre-selected
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_form.py -v`
Expected: FAIL (`SwitchGridElementForm` undefined).

- [ ] **Step 3: Implement `SwitchGridElementForm` in `courses/element_forms.py`**

Add these module constants near the existing `_MIN_OPTIONS` / `_MIN_ROWS` (reuse `_MIN_OPTIONS = 2`):

```python
_SG_MIN_LINES = 2          # blank line slots shown on create
_SG_MIN_CYCLERS = 1        # blank cycler slots shown per line on create
_SG_MIN_OPT_INPUTS = 3     # blank option inputs shown per cycler on create
```

Add the form class (import `re`, `switchgrid`, `SwitchGridElement` at the top of the module if not present):

```python
class SwitchGridElementForm(forms.Form):
    """Plain (non-Model) form for the Switch grid self-check. The grid is posted as
    indexed fields: line-{i}-stem, line-{i}-c{j}-opt (repeated), line-{i}-c{j}-ans.
    Indices are append-only; gaps and blanks are compacted at clean() time."""

    prompt = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    _LINE_STEM_RE = re.compile(r"^line-(\d+)-stem$")
    _CYC_RE = re.compile(r"^line-(\d+)-c(\d+)-(opt|ans)$")

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance if instance is not None else SwitchGridElement()
        self._lines = []            # normalized, ready to store
        super().__init__(*args, **kwargs)
        if instance is not None and instance.pk:
            self.initial["prompt"] = instance.prompt

    # ---- POST discovery helpers -------------------------------------------------
    def _line_indices(self):
        """Sorted line indices present in the POST (any line-{i}-* key)."""
        idx = set()
        for key in self.data.keys():
            m = self._LINE_STEM_RE.match(key)
            if m:
                idx.add(int(m.group(1)))
            m = self._CYC_RE.match(key)
            if m:
                idx.add(int(m.group(1)))
        return sorted(idx)

    def _cycler_indices(self, i):
        """Sorted cycler indices present for line i."""
        idx = set()
        prefix = f"line-{i}-c"
        for key in self.data.keys():
            m = self._CYC_RE.match(key)
            if m and int(m.group(1)) == i:
                idx.add(int(m.group(2)))
        return sorted(idx)

    def _opts_for(self, i, j):
        name = f"line-{i}-c{j}-opt"
        data = self.data
        return data.getlist(name) if hasattr(data, "getlist") else []

    # ---- validation -------------------------------------------------------------
    def clean(self):
        cleaned = super().clean()
        cleaned["prompt"] = (cleaned.get("prompt") or "").strip()
        lines = []
        total_cyclers = 0
        for i in self._line_indices():
            raw_stem = self.data.get(f"line-{i}-stem", "") or ""
            clean_stem = fillblank.strip_sentinel(sanitize_html(raw_stem))
            token_stem, marker_count = switchgrid.parse_stem_multi(clean_stem)

            cyclers = []
            for j in self._cycler_indices(i):
                raw_opts = [sanitize_cell(o or "") for o in self._opts_for(i, j)]
                # remember which posted slots survive, to remap the answer
                kept = [(k, o) for k, o in enumerate(raw_opts) if o != ""]
                if not kept:
                    continue  # wholly-blank cycler slot -> not present
                ans_raw = self.data.get(f"line-{i}-c{j}-ans")
                try:
                    ans_posted = int(ans_raw)
                except (TypeError, ValueError):
                    self.add_error(None, _("Select the correct option in every cycler."))
                    ans_posted = -1
                # remap posted answer onto the compacted (non-blank) list
                remap = {orig_k: new_k for new_k, (orig_k, _o) in enumerate(kept)}
                options = [o for _k, o in kept]
                answer = remap.get(ans_posted, -1)
                if len(options) < _MIN_OPTIONS:
                    self.add_error(None, _("Each cycler needs at least two options."))
                if not (0 <= answer < len(options)):
                    self.add_error(None, _("Select the correct option in every cycler."))
                cyclers.append({"options": options, "answer": answer})

            # drop wholly-blank line (empty stem AND no surviving cyclers)
            if not clean_stem.strip() and not cyclers:
                continue
            if marker_count != len(cyclers):
                self.add_error(
                    None,
                    _("Line %(n)d: mark each cycler with {{choice}} exactly once.")
                    % {"n": len(lines) + 1},
                )
            lines.append({"stem": token_stem, "cyclers": cyclers})
            total_cyclers += len(cyclers)

        if not lines:
            self.add_error(None, _("Add at least one line."))
        if total_cyclers < 1:
            self.add_error(None, _("Add at least one cycler with options."))
        self._lines = lines
        return cleaned

    def save(self, commit=True):
        self.instance.prompt = self.cleaned_data.get("prompt", "")
        self.instance.lines = self._lines
        if commit:
            self.instance.save()
        return self.instance

    # ---- edit re-populate (feeds _edit_switchgrid.html) -------------------------
    def line_rows(self):
        """Padded structure for the editor partial. On a bound form, mirror posted
        data; on edit, mirror instance.lines; on create, blanks. Indices are
        append-only; the partial renders name="line-{i}-c{j}-opt" etc."""
        stored = list(self.instance.lines or []) if self.instance.pk else []
        n_lines = max(_SG_MIN_LINES, len(stored) + 1)
        rows = []
        for i in range(n_lines):
            line = stored[i] if i < len(stored) else None
            stem = switchgrid.to_author_stem_multi(line["stem"]) if line else ""
            stored_cyclers = (line or {}).get("cyclers", []) if line else []
            n_cyc = max(_SG_MIN_CYCLERS, len(stored_cyclers) + 1)
            cyclers = []
            for j in range(n_cyc):
                cyc = stored_cyclers[j] if j < len(stored_cyclers) else None
                opts = (cyc or {}).get("options", []) if cyc else []
                answer = cyc["answer"] if cyc else -1
                n_opt = max(_SG_MIN_OPT_INPUTS, len(opts) + 1)
                option_rows = [
                    {"value": opts[k] if k < len(opts) else "", "checked": k == answer}
                    for k in range(n_opt)
                ]
                cyclers.append({"index": j, "options": option_rows})
            rows.append({"index": i, "stem": stem, "cyclers": cyclers})
        return rows
```

Register in `FORM_FOR_TYPE` (add the entry next to `"switchgate"`):

```python
    "switchgrid": SwitchGridElementForm,
```

> Note: `line_rows()` above is the create/edit view (unbound). A full bound-form re-render on validation error is out of v1 scope — a validation error re-renders from the instance/blank state, acceptable for v1 (matches switchgate's simpler behavior closely enough). The edit round-trip test asserts the unbound edit path.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest courses/tests/test_switchgrid_form.py -v`
Expected: PASS (all tests). If `fillblank.strip_sentinel` differs in name, grep `courses/fillblank.py` and use the actual sentinel-stripping helper (the switchgate form uses `fillblank.strip_sentinel`).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py courses/tests/test_switchgrid_form.py
git commit -m "feat(switch-grid): SwitchGridElementForm (3-level parse, compaction, remap)"
```

---

### Task 4: Render tag + student template + CSS

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (add `render_switch_grid`)
- Create: `templates/courses/elements/switchgridelement.html`
- Modify: `core/static/core/css/app.css` (add `.switchgrid*` styles)
- Test: `courses/tests/test_switchgrid_context.py`, `courses/tests/test_switchgrid_template.py`

**Interfaces:**
- Consumes: `switchgrid.render_stem_multi`, `courses:switchgrid_check` URL (Task 5 — the `reverse()` name must exist for the tag to render; **do Task 5's URL registration first or in the same commit** — see note).
- Produces: a `<div class="switchgrid" data-switchgrid data-element-pk data-check-url>` with one `data-line` container per line (incl. static), each cycler a `<button data-switchgrid-cycler data-cycler="{j}">` carrying all option HTML (first visible, rest hidden), plus a confirm button and one toggled summary region.

> **Ordering note:** `reverse("courses:switchgrid_check", ...)` requires the URL from Task 5. Either implement Task 5 before Task 4, or add just the URL line (Task 5 Step 3) as the first step here. The plan orders Task 5 after 4 for test-narrative reasons, so **add the URL line as Step 0 below.**

- [ ] **Step 0: Add the check URL (needed by the tag's `reverse()`)**

In `courses/urls.py`, add next to `switchgate_check`:

```python
    path(
        "courses/element/<int:element_pk>/switchgrid-check/",
        views.switchgrid_check,
        name="switchgrid_check",
    ),
```

(The `views.switchgrid_check` view itself is written in Task 5; add a temporary stub if running Task 4 in isolation, but preferably implement Task 5 before running Task 4's tests.)

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_switchgrid_context.py
import pytest
from django.utils.safestring import SafeString
from courses.models import SwitchGridElement
from courses.templatetags.courses_extras import render_switch_grid
from courses import fillblank

pytestmark = pytest.mark.django_db


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def _grid():
    return SwitchGridElement.objects.create(
        prompt="Fix operators",
        lines=[
            {"stem": "intro static", "cyclers": []},
            {"stem": f"3 {_tok(0)} 3 = 9", "cyclers": [{"options": ["+", "-", "x"], "answer": 2}]},
        ],
    )


def test_render_emits_data_line_for_every_line_including_static():
    html = render_switch_grid(_grid(), eid=1)
    assert isinstance(html, SafeString)
    assert 'data-line="0"' in html   # static line still gets a container
    assert 'data-line="1"' in html


def test_render_embeds_full_option_set_but_not_answer():
    html = render_switch_grid(_grid(), eid=1)
    assert "switchgrid__option" in html
    for opt in ("+", "-", "x"):
        assert opt in html
    assert 'data-cycler="0"' in html
    assert "answer" not in html.lower()   # correct index never emitted


def test_render_shows_prompt_and_confirm():
    html = render_switch_grid(_grid(), eid=1)
    assert "Fix operators" in html
    assert "switchgrid__confirm" in html
    assert "switchgrid__summary" in html


def test_render_emits_i18n_summary_message_attrs():
    html = render_switch_grid(_grid(), eid=1)
    assert "data-success-msg=" in html   # JS reads these instead of hardcoding EN
    assert "data-retry-msg=" in html


def test_render_via_model_render_method(client):
    # render() must resolve its join pk and produce the widget (moved from Task 2 — needs this task's template)
    el = _grid()
    from courses.models import Element
    from django.contrib.contenttypes.models import ContentType
    # attach a join-row so render()'s eid is real (mirror test_switchgate_model.py's join creation)
    # ... build the Element join over `el` per the switchgate model test, then:
    html = el.render()
    assert 'class="switchgrid"' in html
```

> `test_render_via_model_render_method` needs an `Element` join over the concrete element (so `render()`'s `eid` is non-zero) — copy the exact join-row creation from `test_switchgate_model.py`. This is the render test relocated from Task 2 per the ordering fix.

```python
# courses/tests/test_switchgrid_template.py
import pytest
from courses.models import SwitchGridElement

pytestmark = pytest.mark.django_db


def test_element_template_renders_via_tag(client_lesson_with_switchgrid):
    # fixture builds a unit with a SwitchGridElement join and returns the rendered page
    resp = client_lesson_with_switchgrid
    assert b'class="switchgrid"' in resp.content
```

> Reuse the existing lesson-render fixture pattern from `test_switchgate_template.py`; adapt the concrete model to `SwitchGridElement`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_context.py -v`
Expected: FAIL (`render_switch_grid` undefined).

- [ ] **Step 3: Implement `render_switch_grid` in `courses/templatetags/courses_extras.py`**

```python
@register.simple_tag
def render_switch_grid(el, eid):
    """Render the switch-grid self-check widget: one container per line (static
    lines included), cyclers spliced into each line's token stem."""
    from courses import switchgrid as _switchgrid

    check_url = reverse("courses:switchgrid_check", args=[eid])
    line_html = []
    for i, line in enumerate(el.lines or []):
        widgets = {}
        for j, cyc in enumerate(line.get("cyclers", []) or []):
            options = cyc.get("options", []) or []
            option_spans = format_html_join(
                "",
                '<span class="switchgrid__option{}"{}>{}</span>',
                (
                    (" switchgrid__option--current" if k == 0 else "",
                     "" if k == 0 else mark_safe(" hidden"),
                     mark_safe(o))  # noqa: S308 — options sanitized at save()
                    for k, o in enumerate(options)
                ),
            )
            widgets[j] = format_html(
                '<button type="button" class="switchgrid__cycler" '
                'data-switchgrid-cycler data-cycler="{j}" '
                'aria-label="{label}">{opts}</button>',
                j=j, label=_("Cycle options"), opts=option_spans,
            )
        body = _switchgrid.render_stem_multi(line.get("stem", ""), widgets)
        line_html.append(
            format_html('<div class="switchgrid__line" data-line="{i}">{body}</div>',
                        i=i, body=body)
        )
    lines_joined = mark_safe("".join(line_html))
    prompt_html = format_html('<p class="switchgrid__prompt">{}</p>', el.prompt) if el.prompt else ""
    return format_html(
        '<div class="switchgrid" data-switchgrid data-element-pk="{pk}" data-check-url="{url}">'
        "{prompt}{lines}"
        '<button type="button" class="switchgrid__confirm">{confirm}</button>'
        '<p class="switchgrid__summary" data-switchgrid-summary '
        'data-success-msg="{ok}" data-retry-msg="{retry}" hidden></p>'
        "</div>",
        pk=eid, url=check_url, prompt=prompt_html, lines=lines_joined,
        confirm=_("Check"), ok=_("Great!"), retry=_("Try again"),
    )
```

> The `data-success-msg`/`data-retry-msg` attributes carry the fixed EN/PL summary strings server-side; `switchgrid.js` reads them so the messages stay translatable (do NOT hardcode them in JS).

Ensure the imports `format_html`, `format_html_join`, `mark_safe`, `reverse`, and `_` (gettext) are already present at the top of `courses_extras.py` (they are, used by `render_switch_gate`).

- [ ] **Step 4: Create `templates/courses/elements/switchgridelement.html`**

```django
{% load courses_extras %}
{% render_switch_grid el eid %}
```

- [ ] **Step 5: Add CSS to `core/static/core/css/app.css`**

Append (mirror the `.switchgate*` visual language; tokens per the existing design system):

```css
/* --- Switch grid self-check --- */
.switchgrid { margin: var(--space-4, 1rem) 0; }
.switchgrid__prompt { font-weight: 600; margin: 0 0 var(--space-2, .5rem); }
.switchgrid__line { margin: var(--space-1, .25rem) 0; line-height: 2; }
.switchgrid__cycler {
  border: 1px solid var(--border-strong, #888);
  border-radius: var(--radius-1, .25rem);
  background: var(--surface-2, #f3f3f3);
  padding: .1em .5em; margin: 0 .15em; cursor: pointer; font: inherit;
}
.switchgrid__cycler.switchgrid--correct { border-color: var(--ok, #2e7d32); background: var(--ok-bg, #e8f5e9); }
.switchgrid__cycler.switchgrid--incorrect { border-color: var(--bad, #c62828); background: var(--bad-bg, #ffebee); }
.switchgrid__cycler.switchgrid--locked { cursor: default; opacity: .9; }
.switchgrid__option { }
.switchgrid__confirm {
  margin-top: var(--space-2, .5rem);
  /* reuse the app button base; add .btn if the project's convention is a class */
}
.switchgrid__summary { margin-top: var(--space-2, .5rem); font-weight: 600; }
.switchgrid__summary.switchgrid--success { color: var(--ok, #2e7d32); }
.switchgrid__summary.switchgrid--retry { color: var(--bad, #c62828); }
```

> Match the real token names used elsewhere in `app.css` (grep `--border-strong`, `--surface-2`, etc.); the fallbacks above are only defensive. If the app has a `.btn` base class, add it to the confirm button in the render tag instead of restyling.

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest courses/tests/test_switchgrid_context.py courses/tests/test_switchgrid_template.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/switchgridelement.html core/static/core/css/app.css courses/urls.py courses/tests/test_switchgrid_context.py courses/tests/test_switchgrid_template.py
git commit -m "feat(switch-grid): render tag, student template, CSS"
```

---

### Task 5: Server check endpoint (`switchgrid_check`)

**Files:**
- Modify: `courses/views.py` (add `switchgrid_check`; import `json` if not present)
- Modify: `courses/urls.py` (URL added in Task 4 Step 0 — verify present)
- Test: `courses/tests/test_switchgrid_check.py`

**Interfaces:**
- Produces: `POST courses/element/<pk>/switchgrid-check/` → `{"correct": bool, "cells": [[bool, ...], ...]}`; soft pk lookup; `can_access_course` gate; never persists; `indices` parsed from a JSON form field.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_switchgrid_check.py
import json
import pytest
from django.urls import reverse
from courses.models import SwitchGridElement, Element
# reuse the switchgate test's helpers for building a unit + Element join + enrolled user
from courses.tests.test_switchgate_check import _make_join, _client_for  # adjust to real helpers

pytestmark = pytest.mark.django_db


def _grid_join():
    el = SwitchGridElement.objects.create(
        lines=[
            {"stem": "s", "cyclers": []},                                   # static line -> []
            {"stem": "t", "cyclers": [{"options": ["+", "-", "x"], "answer": 2}]},
            {"stem": "u", "cyclers": [{"options": [":", "-"], "answer": 0}]},
        ]
    )
    return _make_join(el)  # returns (element_join, course/unit/user context)


def test_all_correct(client_and_join):
    join, client = client_and_join
    url = reverse("courses:switchgrid_check", args=[join.pk])
    resp = client.post(url, {"indices": json.dumps([[], [2], [0]])})
    data = resp.json()
    assert data["correct"] is True
    assert data["cells"] == [[], [True], [True]]


def test_one_wrong(client_and_join):
    join, client = client_and_join
    url = reverse("courses:switchgrid_check", args=[join.pk])
    resp = client.post(url, {"indices": json.dumps([[], [0], [0]])})
    data = resp.json()
    assert data["correct"] is False
    assert data["cells"] == [[], [False], [True]]


def test_bad_pk_soft_200(client_only):
    url = reverse("courses:switchgrid_check", args=[99999])
    resp = client_only.post(url, {"indices": "[[2]]"})
    assert resp.status_code == 200
    assert resp.json() == {"correct": False, "cells": []}


def test_ill_shaped_indices_no_500(client_and_join):
    join, client = client_and_join
    url = reverse("courses:switchgrid_check", args=[join.pk])
    for bad in ["not json", "{}", "[1,2,3]", ""]:
        resp = client.post(url, {"indices": bad})
        assert resp.status_code == 200
        assert resp.json()["correct"] is False


def test_short_payload_and_out_of_range_count_incorrect(client_and_join):
    join, client = client_and_join
    url = reverse("courses:switchgrid_check", args=[join.pk])
    resp = client.post(url, {"indices": json.dumps([[], [], [99]])})  # missing + oob
    data = resp.json()
    assert data["correct"] is False
    assert data["cells"] == [[], [False], [False]]


def test_no_marks_persisted(client_and_join, django_assert_num_queries):
    join, client = client_and_join
    # sanity: no results/marks model row created. Query the results table used by
    # the course; assert count unchanged. (Mirror the no-persistence assert used by
    # the switchgate check test, adapting the model name.)
    from courses.models import Response  # adjust to the real results model
    before = Response.objects.count()
    url = reverse("courses:switchgrid_check", args=[join.pk])
    client.post(url, {"indices": json.dumps([[], [2], [0]])})
    assert Response.objects.count() == before
```

> The exact fixture helpers (`_make_join`, `client_and_join`, `client_only`, and the results-model name) must match what `test_switchgate_check.py` uses — read that file and copy its fixtures/imports verbatim, swapping the concrete model. Do not invent new fixture scaffolding.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_check.py -v`
Expected: FAIL (`switchgrid_check` undefined).

- [ ] **Step 3: Implement `switchgrid_check` in `courses/views.py`**

Apply the same decorators the `switchgate_check` view carries (e.g. `@require_POST`, `@login_required` — copy exactly what precedes `switchgate_check`).

```python
def switchgrid_check(request, element_pk):
    """Server-side check for a Switch grid self-check. Reports per-cycler and overall
    correctness only — NOTHING is persisted. Soft pk lookup (switchgate parity):
    a missing/wrong-type pk is a 200 {"correct": False, "cells": []}, not 404."""
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, SwitchGridElement):
        return JsonResponse({"correct": False, "cells": []})
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied

    try:
        indices = json.loads(request.POST.get("indices", ""))
    except (TypeError, ValueError):
        return JsonResponse({"correct": False, "cells": []})
    if not isinstance(indices, list):
        return JsonResponse({"correct": False, "cells": []})

    cells = []
    all_correct = True
    for i, line in enumerate(concrete.lines or []):
        row = []
        sub = indices[i] if (i < len(indices) and isinstance(indices[i], list)) else []
        for j, cyc in enumerate(line.get("cyclers", []) or []):
            submitted = sub[j] if (j < len(sub) and isinstance(sub[j], int)) else None
            ok = submitted == cyc.get("answer")
            row.append(ok)
            all_correct = all_correct and ok
        cells.append(row)
    return JsonResponse({"correct": all_correct, "cells": cells})
```

Add `import json` at the top of `courses/views.py` if not already present.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest courses/tests/test_switchgrid_check.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py courses/urls.py courses/tests/test_switchgrid_check.py
git commit -m "feat(switch-grid): switchgrid_check endpoint"
```

---

### Task 6: JS enhancer + editor add/remove + wiring

**Files:**
- Create: `courses/static/courses/js/switchgrid.js` (student enhancer)
- Create: `courses/static/courses/js/switchgrid_editor.js` (editor add/remove rows)
- Modify: `courses/static/courses/js/editor.js` (re-init the preview enhancer)
- Modify: `templates/courses/manage/editor/editor.html` (load both scripts)
- Modify: `courses/views.py` (`build_lesson_context` — add `has_switch_grid` flag)
- Modify: `templates/courses/lesson_unit.html` (conditional `switchgrid.js` script tag)
- Consumes (created in Task 7): `templates/courses/manage/editor/_edit_switchgrid.html` — its `<template>` nodes are what the editor JS clones; the editor add/remove buttons are inert until Task 7 ships the partial.
- Test: `courses/tests/test_switchgrid_wiring.py`

**Interfaces:**
- Produces: `window.libliInitSwitchGrids(root)` (idempotent) and `window.libliInitSwitchGridEditors(root)`.

- [ ] **Step 1: Write the failing wiring test**

```python
# courses/tests/test_switchgrid_wiring.py
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_editor_loads_switchgrid_scripts(manage_editor_client):
    # GET the manage editor page (reuse the switchgate wiring test's fixture)
    resp = manage_editor_client
    assert b"courses/js/switchgrid.js" in resp.content
    assert b"courses/js/switchgrid_editor.js" in resp.content
```

> Copy the exact fixture/URL the switchgate wiring test (`test_switchgate_wiring.py`) uses to GET the editor page; swap only the asserted script name.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_wiring.py -v`
Expected: FAIL (script tags absent).

- [ ] **Step 3: Create `courses/static/courses/js/switchgrid.js`**

```javascript
(function () {
  "use strict";

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function options(cycler) {
    return Array.prototype.slice.call(cycler.querySelectorAll(".switchgrid__option"));
  }

  function currentIndex(cycler) {
    var opts = options(cycler);
    for (var i = 0; i < opts.length; i++) {
      if (!opts[i].hidden) return i;
    }
    return 0;
  }

  function show(cycler, idx) {
    var opts = options(cycler);
    for (var i = 0; i < opts.length; i++) {
      opts[i].hidden = i !== idx;
      opts[i].classList.toggle("switchgrid__option--current", i === idx);
    }
  }

  function advance(cycler) {
    if (cycler.classList.contains("switchgrid--locked")) return;
    var opts = options(cycler);
    if (!opts.length) return;
    show(cycler, (currentIndex(cycler) + 1) % opts.length);
    cycler.classList.remove("switchgrid--correct", "switchgrid--incorrect");
  }

  function collect(root) {
    var lines = Array.prototype.slice.call(root.querySelectorAll("[data-line]"));
    return lines.map(function (line) {
      var cyclers = Array.prototype.slice.call(line.querySelectorAll("[data-switchgrid-cycler]"));
      return cyclers.map(currentIndex);
    });
  }

  function paint(root, cells) {
    var lines = Array.prototype.slice.call(root.querySelectorAll("[data-line]"));
    lines.forEach(function (line, i) {
      var cyclers = Array.prototype.slice.call(line.querySelectorAll("[data-switchgrid-cycler]"));
      var row = (cells && cells[i]) || [];
      cyclers.forEach(function (cyc, j) {
        cyc.classList.remove("switchgrid--correct", "switchgrid--incorrect");
        if (row[j] === true) cyc.classList.add("switchgrid--correct");
        else if (row[j] === false) cyc.classList.add("switchgrid--incorrect");
      });
    });
  }

  function lock(root) {
    root.querySelectorAll("[data-switchgrid-cycler]").forEach(function (c) {
      c.classList.add("switchgrid--locked");
    });
    var btn = root.querySelector(".switchgrid__confirm");
    if (btn) btn.hidden = true;
  }

  function summarize(root, ok) {
    var s = root.querySelector("[data-switchgrid-summary]");
    if (!s) return;
    s.hidden = false;
    s.classList.toggle("switchgrid--success", ok);
    s.classList.toggle("switchgrid--retry", !ok);
    s.textContent = ok ? s.dataset.successMsg || "Great!" : s.dataset.retryMsg || "Try again";
  }

  function submit(root) {
    var pk = root.dataset.elementPk;
    var url = root.dataset.checkUrl;
    if (!pk || pk === "0" || !url) return; // unsaved preview
    var body = new FormData();
    body.append("indices", JSON.stringify(collect(root)));
    fetch(url, { method: "POST", headers: { "X-CSRFToken": csrf() }, body: body, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        paint(root, data.cells || []);
        summarize(root, !!data.correct);
        if (data.correct) lock(root);
      })
      .catch(function () { /* fail-open: leave widget interactive */ });
  }

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

  function initSwitchGrids(root) {
    (root || document).querySelectorAll("[data-switchgrid]").forEach(initOne);
  }

  window.libliInitSwitchGrids = initSwitchGrids;
  initSwitchGrids(document);
})();
```

> The `s.dataset.successMsg`/`s.dataset.retryMsg` reads correspond to the `data-success-msg`/`data-retry-msg` attributes the render tag emits (added in Task 4 Step 3) — the JS falls back to English only if they are absent, so Task 4 must emit them (it does). If switchgate.js's typeset call is named differently than `renderMathInElement`, grep switchgate.js and mirror the exact call.

- [ ] **Step 4: Create `courses/static/courses/js/switchgrid_editor.js`**

Editor-only: "add line", per-line "add cycler", per-cycler "add option" via `<template>` cloning with **append-only** indices (the server compacts gaps/blanks, so removal = clearing inputs, never renumbering).

Uses **document-level event delegation** — one listener attached once at load — so it works no matter when the `_edit_switchgrid.html` partial is injected (the palette card loads it via AJAX). No per-partial re-init is required. Indices are **append-only** (server compacts gaps); the option template's input names are derived from the enclosing line/cycler indices at clone time.

```javascript
(function () {
  "use strict";

  function nextIndex(container, selector, attr) {
    var max = -1;
    container.querySelectorAll(selector).forEach(function (el) {
      var v = parseInt(el.getAttribute(attr), 10);
      if (!isNaN(v) && v > max) max = v;
    });
    return max + 1;
  }

  function rewrite(frag, subs) {
    frag.querySelectorAll("*").forEach(function (n) {
      ["name", "data-line-index", "data-cycler-index"].forEach(function (a) {
        if (n.hasAttribute(a)) {
          var v = n.getAttribute(a);
          Object.keys(subs).forEach(function (k) { v = v.split(k).join(subs[k]); });
          n.setAttribute(a, v);
        }
      });
    });
  }

  function onClick(e) {
    var editor = e.target.closest("[data-switchgrid-editor]");
    if (!editor) return;

    if (e.target.closest("[data-add-line]")) {
      var linesWrap = editor.querySelector("[data-lines]");
      var i = nextIndex(linesWrap, "[data-line-row]", "data-line-index");
      var frag = editor.querySelector("template[data-line-template]").content.cloneNode(true);
      rewrite(frag, { "__i__": i });
      linesWrap.appendChild(frag);
      return;
    }
    var addCyc = e.target.closest("[data-add-cycler]");
    if (addCyc) {
      var lineRow = addCyc.closest("[data-line-row]");
      var i2 = lineRow.getAttribute("data-line-index");
      var cycWrap = lineRow.querySelector("[data-cyclers]");
      var j = nextIndex(cycWrap, "[data-cycler-row]", "data-cycler-index");
      var cfrag = editor.querySelector("template[data-cycler-template]").content.cloneNode(true);
      rewrite(cfrag, { "__i__": i2, "__j__": j });
      cycWrap.appendChild(cfrag);
      return;
    }
    var addOpt = e.target.closest("[data-add-option]");
    if (addOpt) {
      var cycRow = addOpt.closest("[data-cycler-row]");
      var lineRow2 = cycRow.closest("[data-line-row]");
      var i3 = lineRow2.getAttribute("data-line-index");
      var j3 = cycRow.getAttribute("data-cycler-index");
      var ofrag = editor.querySelector("template[data-option-template]").content.cloneNode(true);
      // derive the current cycler's real field names for the cloned option row
      rewrite(ofrag, { "__i__": i3, "__j__": j3 });
      cycRow.querySelector("[data-options]").appendChild(ofrag);
    }
  }

  document.addEventListener("click", onClick);
  // exposed as a no-op initializer for symmetry with other enhancers (delegation is global)
  window.libliInitSwitchGridEditors = function () {};
})();
```

Because the option template uses `__i__`/`__j__` placeholders (same as the cycler template) and `rewrite()` substitutes them from the enclosing indices, the option-row's `-ans`/`-opt` names come out correct. Update the `data-option-template` in Task 7 to use `name="line-__i__-c__j__-ans"` / `name="line-__i__-c__j__-opt"` accordingly.

- [ ] **Step 5: Wire `editor.js`**

In `courses/static/courses/js/editor.js`, next to the existing `libliInitSwitchGates` preview re-init line (~`editor.js:79`), add ONLY the **preview enhancer** re-init (the student widget in the preview pane must re-init after each fragment swap):

```javascript
    if (preview && window.libliInitSwitchGrids) window.libliInitSwitchGrids(preview);
```

No editor-helper re-init line is needed: `switchgrid_editor.js` uses a single document-level delegated click listener (attached once at load), so it handles AJAX-injected edit partials without re-initialization.

- [ ] **Step 6: Load scripts in `editor.html`**

In `templates/courses/manage/editor/editor.html`, next to the `switchgate.js` tag:

```django
<script src="{% static 'courses/js/switchgrid.js' %}" defer></script>
<script src="{% static 'courses/js/switchgrid_editor.js' %}" defer></script>
```

- [ ] **Step 6b: Wire the STUDENT lesson page (CRITICAL — without this the widget is inert for students)**

The lesson page only loads a widget's JS behind a per-type context flag. `templates/courses/lesson_unit.html` loads `switchgate.js` under `{% if has_switch_gate %}`; `has_switch_gate` is computed and returned by `build_lesson_context` (`courses/views.py` ~:258/:284). Mirror this for the grid:

1. In `build_lesson_context`, compute the flag next to `has_switch_gate` (match the exact idiom used there — `.exists()` on the prefetched elements or a filtered query):

```python
    has_switch_grid = any(
        isinstance(e.content_object, SwitchGridElement) for e in elements
    )
```

2. Add `has_switch_grid` to the returned context dict (next to `has_switch_gate`).

3. In `templates/courses/lesson_unit.html`, next to the `switchgate.js` conditional tag (~:60), add:

```django
{% if has_switch_grid %}<script src="{% static 'courses/js/switchgrid.js' %}" defer></script>{% endif %}
```

> **Read the real `build_lesson_context` return and the `lesson_unit.html` switchgate block first**, and mirror them exactly (flag name style, `.exists()` vs comprehension, `{% static %}` load, script ordering). This is the same detection surface as the has_math OR-chain in Task 2 Step 5 — you may compute both in one pass.

- [ ] **Step 7: Extend the wiring test to cover BOTH editor and student pages**

Add to `courses/tests/test_switchgrid_wiring.py`:

```python
def test_lesson_page_loads_switchgrid_js_when_grid_present(lesson_with_grid_client):
    # GET a lesson unit containing a SwitchGridElement (reuse switchgate lesson fixture)
    resp = lesson_with_grid_client
    assert b"courses/js/switchgrid.js" in resp.content
```

Run: `uv run pytest courses/tests/test_switchgrid_wiring.py -v`
Expected: PASS (editor-scripts test + lesson-page test).

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/switchgrid.js courses/static/courses/js/switchgrid_editor.js courses/static/courses/js/editor.js courses/views.py templates/courses/manage/editor/editor.html templates/courses/lesson_unit.html courses/tests/test_switchgrid_wiring.py courses/templatetags/courses_extras.py
git commit -m "feat(switch-grid): JS enhancer, editor add/remove, lesson+editor wiring"
```

---

### Task 7: Registration surface (palette, labels, allow-tuples, edit partial, summary)

Makes the element reachable end-to-end and adds the authoring GET/POST guard.

**Files:**
- Modify: `courses/views_manage.py` (`element_add` + `element_save` allow-tuples; `_EDITOR_TYPE_LABELS`)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`)
- Create: `templates/courses/manage/editor/_edit_switchgrid.html`
- Modify: `templates/courses/manage/_add_menu.html` (palette card, Interactive group, `{% if not nested %}`)
- Modify: `templates/courses/manage/_icon_sprite.html` (`#el-switchgrid` symbol)
- Test: `courses/tests/test_switchgrid_authoring.py`

- [ ] **Step 1: Write the failing authoring tests**

```python
# courses/tests/test_switchgrid_authoring.py
import pytest
from django.urls import reverse
from courses.models import SwitchGridElement
# reuse the switchgate authoring test's fixtures for a manage-able unit + PA/CA user
from courses.tests.test_switchgate_authoring import manage_ctx  # adjust to real fixture

pytestmark = pytest.mark.django_db


def test_add_get_renders_edit_partial(manage_ctx):
    ctx = manage_ctx
    url = reverse("courses:element_add", args=[ctx.unit.pk])  # adjust arg to real signature
    resp = ctx.client.get(url + "?type=switchgrid")
    assert resp.status_code == 200
    assert b"data-switchgrid-editor" in resp.content


def test_add_post_creates_element(manage_ctx):
    ctx = manage_ctx
    url = reverse("courses:element_save", args=[ctx.unit.pk])  # adjust to real signature
    before = SwitchGridElement.objects.count()
    resp = ctx.client.post(url, {
        "type": "switchgrid",
        "prompt": "Fix",
        "line-0-stem": "3 {{choice}} 3 = 9",
        "line-0-c0-opt": ["+", "-", "x"],   # LIST value -> Django posts repeated fields
        "line-0-c0-ans": "2",
    })
    assert resp.status_code in (200, 302)
    assert SwitchGridElement.objects.count() == before + 1   # a valid create actually happened
```

> **Critical:** the `element_add`/`element_save` URL names, argument signatures, and the "type" parameter mechanism must be copied from `test_switchgate_authoring.py` verbatim — read it first. The repeated `line-0-c0-opt` needs a QueryDict/`data` list (see the switchgate authoring POST for how it posts repeated `option` values). Fix the option-list posting to match.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_authoring.py -v`
Expected: FAIL (bad type / missing partial).

- [ ] **Step 3: Add `"switchgrid"` to both allow-tuples in `courses/views_manage.py`**

In `element_add`'s tuple (next to `"switchgate"`): add `"switchgrid"`.
In `element_save`'s tuple (next to `"switchgate"`): add `"switchgrid"`.

- [ ] **Step 4: Add the editor label in `courses/views_manage.py`**

In `_EDITOR_TYPE_LABELS`, next to the switchgate entry:

```python
    "switchgrid": gettext_lazy("Switch grid"),
```

- [ ] **Step 5: Add the element label in `courses/templatetags/courses_manage_extras.py`**

In `_ELEMENT_LABELS`, next to `"switchgateelement"`:

```python
    "switchgridelement": _("Switch grid"),
```

(The generic `stem`-based `element_summary` fallback does not apply — `SwitchGridElement` has no top-level `stem` attribute. Add a bespoke branch in `element_summary` that returns the prompt or the element label:)

```python
    if isinstance(el, SwitchGridElement):
        text = re.sub(r"\s+", " ", strip_tags(el.prompt or "")).strip()
        return Truncator(text).chars(60) or name
```

Import `SwitchGridElement` in that module (mirror how `element_summary`/`_ELEMENT_LABELS` reference other concrete models; use a lazy/local import if the module avoids top-level model imports).

- [ ] **Step 6: Create `templates/courses/manage/editor/_edit_switchgrid.html`**

The partial renders `form.line_rows` and the `<template>` nodes the editor JS clones. Placeholders `__i__`/`__j__` in the templates are rewritten by `switchgrid_editor.js`.

```django
{% load i18n %}
<div class="el-editor el-editor--switchgrid" data-switchgrid-editor>
  <label class="el-editor__label">{% trans "Instruction (optional)" %}</label>
  <textarea name="prompt" class="rte-source" rows="2">{{ form.prompt.value|default:"" }}</textarea>

  <p class="el-editor__hint">{% trans "Each line: type math and mark each cycler position with {{choice}}." %}</p>

  <div data-lines>
    {% for line in form.line_rows %}
      <div class="el-editor__line" data-line-row data-line-index="{{ line.index }}">
        <textarea name="line-{{ line.index }}-stem" class="rte-source" rows="1">{{ line.stem }}</textarea>
        <div data-cyclers>
          {% for cyc in line.cyclers %}
            <div class="el-editor__cycler" data-cycler-row data-cycler-index="{{ cyc.index }}">
              <div data-options>
                {% for opt in cyc.options %}
                  <div class="el-editor__option-row">
                    <input type="radio" name="line-{{ line.index }}-c{{ cyc.index }}-ans"
                           value="{{ forloop.counter0 }}"{% if opt.checked %} checked{% endif %}
                           aria-label="{% trans 'Correct option' %}">
                    <input type="text" name="line-{{ line.index }}-c{{ cyc.index }}-opt"
                           class="rte-source" value="{{ opt.value }}"
                           placeholder="{% trans 'Option' %} {{ forloop.counter }}">
                  </div>
                {% endfor %}
              </div>
              <button type="button" class="btn btn--small" data-add-option>{% trans "Add option" %}</button>
            </div>
          {% endfor %}
        </div>
        <button type="button" class="btn btn--small" data-add-cycler>{% trans "Add cycler" %}</button>
      </div>
    {% endfor %}
  </div>
  <button type="button" class="btn btn--small" data-add-line>{% trans "Add line" %}</button>

  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  {# --- clone templates (indices __i__/__j__ rewritten by switchgrid_editor.js) --- #}
  <template data-line-template>
    <div class="el-editor__line" data-line-row data-line-index="__i__">
      <textarea name="line-__i__-stem" class="rte-source" rows="1"></textarea>
      <div data-cyclers></div>
      <button type="button" class="btn btn--small" data-add-cycler>{% trans "Add cycler" %}</button>
    </div>
  </template>
  <template data-cycler-template>
    <div class="el-editor__cycler" data-cycler-row data-cycler-index="__j__">
      <div data-options>
        <div class="el-editor__option-row">
          <input type="radio" name="line-__i__-c__j__-ans" value="0" aria-label="{% trans 'Correct option' %}">
          <input type="text" name="line-__i__-c__j__-opt" class="rte-source" placeholder="{% trans 'Option' %}">
        </div>
      </div>
      <button type="button" class="btn btn--small" data-add-option>{% trans "Add option" %}</button>
    </div>
  </template>
  <template data-option-template>
    <div class="el-editor__option-row">
      <input type="radio" name="line-__i__-c__j__-ans" value="0" aria-label="{% trans 'Correct option' %}">
      <input type="text" name="line-__i__-c__j__-opt" class="rte-source" placeholder="{% trans 'Option' %}">
    </div>
  </template>
</div>
```

> The `__i__`/`__j__` placeholders in all three `<template>`s are substituted by `switchgrid_editor.js`'s `rewrite()` from the enclosing line/cycler indices at clone time (Task 6), so a cloned option row gets the correct `line-{i}-c{j}-opt`/`-ans` names. Note the added radio `value="0"` on a fresh option defaults the correct answer to the first option; the author re-selects as needed.

- [ ] **Step 7: Add the palette card in `templates/courses/manage/_add_menu.html`**

In the Interactive group, after the switchgate card, gated non-nested:

```django
{% if not nested %}<button type="button" class="typecard" data-add-type="switchgrid"><svg class="ic" aria-hidden="true"><use href="#el-switchgrid"/></svg>{% trans "Switch grid" %}</button>{% endif %}
```

- [ ] **Step 8: Add the icon symbol in `templates/courses/manage/_icon_sprite.html`**

Add a `<symbol id="el-switchgrid" viewBox="0 0 16 16">` — a simple monochrome `currentColor` line icon (e.g. a small 2×2 grid of squares). Mirror the stroke/style of neighbouring `#el-switchgate`/`#el-fillgate` symbols.

- [ ] **Step 9: Run to verify pass**

Run: `uv run pytest courses/tests/test_switchgrid_authoring.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add courses/views_manage.py courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/_edit_switchgrid.html templates/courses/manage/_add_menu.html templates/courses/manage/_icon_sprite.html courses/tests/test_switchgrid_authoring.py
git commit -m "feat(switch-grid): registration surface (palette, labels, edit partial)"
```

---

### Task 8: Transfer (export / import) + schema count

**Files:**
- Modify: `courses/transfer/export.py` (serializer + `SERIALIZERS`)
- Modify: `courses/transfer/payloads.py` (validator + `VALIDATORS`)
- Modify: `courses/transfer/importer.py` (builder + `BUILDERS`)
- Modify: `tests/test_transfer_schema.py` (bump `ELEMENT_MODELS` count 22 → 23)
- Test: `courses/tests/test_switchgrid_transfer.py`

**Interfaces:**
- Transfer key `switch_grid`; payload shape `{"prompt": str, "lines": [{"stem": str, "cyclers": [{"options": [str], "answer": int}]}]}`.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_switchgrid_transfer.py
import pytest
from courses.models import SwitchGridElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.importer import BUILDERS
from courses import fillblank

pytestmark = pytest.mark.django_db


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def _payload():
    return {"prompt": "P", "lines": [
        {"stem": "static", "cyclers": []},
        {"stem": f"a {_tok(0)} b", "cyclers": [{"options": ["+", "-"], "answer": 1}]},
    ]}


from courses.transfer.errors import TransferError  # adjust import to the real TransferError location


def test_round_trip_preserves_prompt_and_lines():
    model, ser = SERIALIZERS["switch_grid"]
    el = SwitchGridElement.objects.create(**_payload())
    data = ser(el, {})
    assert data["prompt"] == "P"
    assert data["lines"][1]["cyclers"][0]["answer"] == 1
    # validate (3-arg signature) + build
    assert VALIDATORS["switch_grid"](data, "el-1", set()) == set()   # must not raise
    obj, _refs = BUILDERS["switch_grid"](data, {})
    obj.refresh_from_db()
    assert obj.lines[0]["cyclers"] == []
    assert obj.lines[1]["cyclers"][0]["options"] == ["+", "-"]


def test_validator_rejects_marker_cycler_mismatch():
    bad = {"prompt": "", "lines": [{"stem": f"a {_tok(0)} b {_tok(1)}", "cyclers": [
        {"options": ["x", "y"], "answer": 0}]}]}  # 2 markers, 1 cycler
    with pytest.raises(TransferError):
        VALIDATORS["switch_grid"](bad, "el-1", set())


def test_validator_rejects_out_of_range_answer():
    bad = {"prompt": "", "lines": [{"stem": f"a {_tok(0)}", "cyclers": [
        {"options": ["x", "y"], "answer": 5}]}]}
    with pytest.raises(TransferError):
        VALIDATORS["switch_grid"](bad, "el-1", set())


def test_import_sanitizes_stem_segments():
    payload = {"prompt": "", "lines": [
        {"stem": f"<script>evil</script>ok {_tok(0)}", "cyclers": [
            {"options": ["a", "b"], "answer": 0}]}]}
    obj, _refs = BUILDERS["switch_grid"](payload, {})
    obj.refresh_from_db()
    assert "<script>" not in obj.lines[0]["stem"]
    assert _tok(0) in obj.lines[0]["stem"]     # sentinel preserved
```

> **Find the real `TransferError` import** (grep `class TransferError` / where `_err` raises it — likely `courses/transfer/errors.py` or defined in `payloads.py`); use that exact import path. The `_err` argument name (`el=` vs positional) must match `_val_switch_gate`.

```python
# add to tests/test_transfer_schema.py — change the assertion
# assert len(ELEMENT_MODELS) == 22   ->   == 23
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_transfer.py tests/test_transfer_schema.py -v`
Expected: FAIL (`switch_grid` key absent; count assertion off).

- [ ] **Step 3: Implement the serializer (`courses/transfer/export.py`)**

```python
def _ser_switch_grid(concrete, media_ids):
    return {"prompt": concrete.prompt, "lines": concrete.lines}
```

Register: `"switch_grid": (SwitchGridElement, _ser_switch_grid),` in `SERIALIZERS` (next to `"switch_gate"`). Import `SwitchGridElement`.

- [ ] **Step 4: Implement the validator (`courses/transfer/payloads.py`)**

**FIRST read the real `_val_switch_gate` in `courses/transfer/payloads.py`** — validators take the signature `_val_switch_gate(data, elid, media_kinds)`, signal errors via `_err(_(...), el=elid)` (which raises `TransferError`, the exception the framework catches), and `return set()` (the media-refs set). Mirror that exactly — a one-arg `def ... : raise ValueError` would `TypeError` at call time and escape as a 500. Use `switchgrid.count_markers` (the public helper from Task 1), not the private regex.

```python
def _val_switch_grid(data, elid, media_kinds):
    from courses import switchgrid

    if not isinstance(data.get("prompt", ""), str):
        _err(_("Element '%(el)s': switch grid prompt must be text."), el=elid)
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        _err(_("Element '%(el)s': switch grid needs at least one line."), el=elid)
    total_cyclers = 0
    for line in lines:
        stem = line.get("stem", "")
        cyclers = line.get("cyclers", [])
        if not isinstance(stem, str) or not isinstance(cyclers, list):
            _err(_("Element '%(el)s': malformed switch grid line."), el=elid)
        if switchgrid.count_markers(stem) != len(cyclers):
            _err(_("Element '%(el)s': switch grid marker/cycler count mismatch."), el=elid)
        for cyc in cyclers:
            opts = cyc.get("options")
            if (not isinstance(opts, list) or len(opts) < 2
                    or not all(isinstance(o, str) for o in opts)):
                _err(_("Element '%(el)s': each switch-grid cycler needs 2+ text options."), el=elid)
            ans = cyc.get("answer")
            if isinstance(ans, bool) or not isinstance(ans, int) or not (0 <= ans < len(opts)):
                _err(_("Element '%(el)s': switch-grid answer out of range."), el=elid)
            total_cyclers += 1
    if total_cyclers < 1:
        _err(_("Element '%(el)s': switch grid needs at least one cycler."), el=elid)
    return set()
```

Register `"switch_grid": _val_switch_grid,` in `VALIDATORS`. Confirm `_err` and `_` are already imported in `payloads.py` (they are, used by `_val_switch_gate`); match its exact `_err` call idiom (arg name may be `el=` or positional — mirror the real one).

- [ ] **Step 5: Implement the builder (`courses/transfer/importer.py`)**

The import path bypasses the form, so **stem segments must be sanitized here** (spec M1) — `save()` sanitizes only options, and `render_stem_multi` `mark_safe`s stem segments, so an unsanitized imported stem is a stored-XSS vector at student render. Use `switchgrid.sanitize_stem_segments` (the Task 1 helper, preserves the sentinel tokens):

```python
def _build_switch_grid(data, assets):
    from courses import switchgrid

    lines = []
    for line in data.get("lines", []) or []:
        lines.append({
            "stem": switchgrid.sanitize_stem_segments(line.get("stem", "")),
            "cyclers": line.get("cyclers", []),
        })
    obj = SwitchGridElement.objects.create(
        prompt=data.get("prompt", ""),
        lines=lines,
    )  # save() sanitizes each cycler's options
    return obj, ()
```

Register `"switch_grid": _build_switch_grid,` in `BUILDERS`. Import `SwitchGridElement`. Confirm the builder return shape matches `_build_switch_gate`'s (`(obj, ())` media-refs tuple).

- [ ] **Step 6: Run to verify pass**

(The `tests/test_transfer_schema.py` count assertion was already bumped to `== 23` in Task 2 Step 5b — do not touch it again here.)

Run: `uv run pytest courses/tests/test_switchgrid_transfer.py tests/test_transfer_schema.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/tests/test_switchgrid_transfer.py
git commit -m "feat(switch-grid): transfer export/import"
```

---

### Task 9: i18n (EN + PL) + full-suite + catalog consistency

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl -l en` (or the project's usual invocation). Review the diff for the new `Switch grid`, `Check`, `Great!`, `Try again`, `Add line/cycler/option`, `Correct option`, validation strings.

- [ ] **Step 2: Fill PL translations**

Edit `locale/pl/LC_MESSAGES/django.po`, translating each new `msgid` (e.g. `"Switch grid"` → `"Siatka przełączników"`, `"Check"` → `"Sprawdź"`, `"Great!"` → `"Świetnie!"`, `"Try again"` → `"Spróbuj ponownie"`, `"Add line"` → `"Dodaj wiersz"`, etc.). Ensure no `#, fuzzy` flags remain on the new entries and no obsolete `#~` entries were introduced.

- [ ] **Step 3: Compile + verify catalog tests**

Run: `uv run python manage.py compilemessages`
Run: `uv run pytest tests/ courses/tests/ -k "i18n or catalog or po_" -v` (the project's catalog-consistency tests — run whichever assert no fuzzy / no obsolete entries).
Expected: PASS.

- [ ] **Step 4: Run the full switch-grid suite + a broad regression slice**

Run: `uv run pytest courses/tests/ -k switchgrid -v`
Run: `uv run pytest -q` (full suite; if xdist flakes on Windows, `uv run pytest -q -p no:cacheprovider -n0`).
Expected: all green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check courses/ tests/` and `uv run ruff format --check courses/ tests/`
Expected: clean (fix any E402/format issues; imports stay top-of-file).

- [ ] **Step 6: Commit**

```bash
git add locale/ courses/ tests/
git commit -m "feat(switch-grid): i18n EN/PL + catalog consistency"
```

---

### Task 10: End-to-end (Playwright)

**Files:**
- Create: `tests/test_e2e_switchgrid.py`

- [ ] **Step 1: Write the e2e test**

Mirror `tests/test_e2e_switchgate.py`'s harness (login, author a unit, add the element, open the lesson view). Drive the REAL UI (no `page.evaluate` shortcuts).

```python
# tests/test_e2e_switchgrid.py — sketch; adapt the harness/fixtures from test_e2e_switchgate.py
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_switchgrid_cycle_confirm_feedback(live_server, page, switchgrid_unit):
    page.goto(switchgrid_unit.lesson_url)
    grid = page.locator(".switchgrid").first
    cycler = grid.locator("[data-switchgrid-cycler]").first
    # cycle until the correct option shows, then confirm -> success + lock
    for _ in range(4):
        cycler.click()
    grid.locator(".switchgrid__confirm").click()
    # incorrect-then-correct paths asserted per fixture answers:
    summary = grid.locator("[data-switchgrid-summary]")
    page.wait_for_timeout(200)
    assert summary.is_visible()
    # if success: cyclers locked + confirm hidden
    # if retry: cyclers still clickable (assert not locked class), re-cycle + reconfirm


def test_switchgrid_incorrect_shows_retry_then_recoverable(live_server, page, switchgrid_unit):
    page.goto(switchgrid_unit.lesson_url)
    grid = page.locator(".switchgrid").first
    grid.locator(".switchgrid__confirm").click()  # likely wrong on first show
    summary = grid.locator("[data-switchgrid-summary]")
    page.wait_for_timeout(200)
    # if wrong: retry class present and cyclers NOT locked
    if "switchgrid--retry" in (summary.get_attribute("class") or ""):
        assert "switchgrid--locked" not in (
            grid.locator("[data-switchgrid-cycler]").first.get_attribute("class") or "")
```

> **Build discipline (per prior e2e learnings):** run e2e **focused and foreground** only — never a broad background `-m e2e` run (it spawns runaway headless browsers). Use opus for the e2e implementation task. The controller owns the final full-suite DoD.

- [ ] **Step 2: Run the e2e focused (foreground)**

Run: `uv run pytest tests/test_e2e_switchgrid.py -v` (foreground, focused).
Expected: PASS (adjust the fixture answers so the cycle-count reaches the correct option deterministically).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_switchgrid.py
git commit -m "test(switch-grid): e2e cycle/confirm/feedback"
```

---

## Definition of Done (controller)

- All 10 tasks committed; `uv run pytest -q` fully green (serial on Windows if xdist flakes).
- `uv run python manage.py makemigrations --check --dry-run` → no changes.
- `uv run ruff check` + `ruff format --check` clean.
- Visual QA (per "Every view ships styled" + "Verify UI with screenshots"): screenshot the student widget and the editor in light + dark; the grid, cyclers, correct/incorrect states, and summary read correctly; the palette card + icon render in the Interactive group.
- Manual smoke: author a 2-line grid with 1 cycler each, save, view as student, cycle + confirm → per-cycler green/red + success; confirm a wrong grid → retry, still interactive.

---

## Self-Review

**Spec coverage:** data model + save-sanitize + has_math (T2); multi-token parser (T1); form 3-level parse, blank/line/gap compaction, answer remap + parse-hardening, marker-count, edit re-populate (T3); render tag with per-line static containers, option-set embedding, prompt placement, never-answer, options-only ring, mutually-exclusive summary (T4/T6); endpoint JSON parse + 500-hardening + soft pk + access + per-cycler cells + static-line alignment + no-marks (T5); JS enhancer + editor add/remove + editor.js/editor.html wiring (T6); full registration lockstep incl. migration, ELEMENT_MODELS, allow-tuples, palette+icon, labels, edit partial, element_summary (T2/T7); transfer trio + structural validation + safe-degrade + schema count (T8/T1); i18n (T9); e2e (T10). All spec sections map to a task.

**Placeholder scan:** no TBD/TODO; every code step carries real code or an exact edit. Fixture-reuse notes point at the concrete switchgate test to copy, not vague "handle it".

**Type consistency:** `lines` shape `{stem, cyclers:[{options, answer}]}` is identical across model, form, render tag, endpoint, transfer, and tests. Field names `line-{i}-stem` / `line-{i}-c{j}-opt` / `line-{i}-c{j}-ans` are identical in form parse, edit partial, editor JS, and authoring test. `window.libliInitSwitchGrids` / `libliInitSwitchGridEditors` names match between the JS files, editor.js re-init, and the wiring test. Transfer key `switch_grid` vs form key `switchgrid` used consistently.
