# Nested questions in lesson containers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a nested question's no-JS feedback reach the student, then allow four question types inside containers in lesson units only.

**Architecture:** `render_element` collects the page-level question values into one `page` dict and passes it **only to the five container models**, which splat it lowest-precedence into their child template context; `render_element` reads those names back from context, so recursion works at any depth. The widening adds three transfer keys plus three form-key aliases, and a lesson-only rule enforced at five write authorities.

**Tech Stack:** Django 5.2, Python 3.13, pytest + factory_boy against real PostgreSQL, `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-08-11-nested-questions-in-lesson-containers-design.md` — read it before starting. Section references below (§3.1, §6.3 …) point into it.

## Global Constraints

- **Working directory is the worktree**: `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/nested-questions-in-lesson-containers`. Every command runs there.
- **Start the test-DB container before the first pytest run.** If it is down the suite looks hung for ~4m21s.
- **All tooling goes through `uv run`** — `pytest`, `ruff`, `python` are not on PATH.
- **Never background a pytest run** — the harness reaps it mid-run and orphans the test DB, and the next run dies with `DuplicateDatabase`.
- **Scope every test run narrowly** to the files the task touches. A whole-repo sweep is a branch gate, run once at the end, never a task step.
- **e2e needs `-m e2e`** explicitly or it silently deselects and exits 5.
- **`ruff check` and `ruff format --check` are separate CI gates.** Run both. Use `--no-cache` for `ruff check` — a `# noqa` warning is cached away and a second run falsely reports clean.
- **Falsify, don't just run.** Every task names a mutant. Apply it, watch the named test go RED, then **edit the mutant back out** — never `git checkout` the file, which destroys the task's real work.
- **Commit at the end of every task**, with the task number in the subject.

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/templatetags/courses_extras.py` | Builds the `page` dict, gates it on `CONTAINER_MODELS`, resolves the six page values from context |
| `courses/models.py` | Five container `render()`s accept and splat `page`; spoiler also gains `eid` |
| `courses/builder.py` | `CONTAINER_MODELS`, `NESTABLE_QUESTION_KEYS`, `ancestor_pks()`, `unit_has_nested_question()`, the `resolve_scope`/`paste_allowed`/`rename_node` clauses |
| `courses/views.py` | `check_answer` seeds `feedback_ancestor_pks` |
| `courses/views_manage.py` | `element_try` action_url, `PASTE_REFUSAL_MESSAGES` entry |
| `courses/transfer/{payloads,schema}.py` | Archive-side quiz refusal, `FORMAT_VERSION` bump |
| `courses/lal_loader/builders.py` | One nested-question-in-quiz guard at the top of `build_element` |
| `templates/courses/elements/spoilerelement.html` | Re-opens on the no-JS re-render |
| `templates/courses/manage/editor/_add_menu.html` | Nested `Questions` group |
| `templates/courses/manage/editor/_preview.html` | `editor_preview=True` |

---

### Task 1: The `page` dict render seam

The core fix. Ends with the five container seam tests green and `test_render_seam.py` proving no leaf broke.

**Files:**
- Modify: `courses/builder.py` (add `CONTAINER_MODELS` after `_CONTAINER_REGISTRY`)
- Modify: `courses/templatetags/courses_extras.py:25-109`
- Modify: `courses/models.py` — `SpoilerElement.render:454`, `CalloutElement.render:522`, `BeforeAfterElement.render:591`, `TabsElement.render:1780`, `TwoColumnElement.render:1892`
- Create: `courses/tests/test_nested_question_nojs_feedback.py` (cherry-picked)

**Interfaces:**
- Produces: `builder.CONTAINER_MODELS: frozenset[type]` — the five container model classes.
- Produces: container `render(*, element=None, state=None, slug=None, node_pk=None, page=None)`.
- Produces: the `page` dict keys `feedback_for_pk`, `selected_ids`, `submitted_values`, `mark_result`, `editor_preview`, `feedback_ancestor_pks`. Task 2 adds the last one's producer; Task 8 the fifth's.

- [ ] **Step 1: Bring the pinning tests onto the branch**

```bash
git checkout test/nested-question-nojs-feedback -- courses/tests/test_nested_question_nojs_feedback.py
```

- [ ] **Step 2: Invert the absence assertion and rename the function**

In `courses/tests/test_nested_question_nojs_feedback.py`, rename `test_nested_blank_answer_shows_no_feedback` → `test_nested_blank_answer_shows_feedback`, and change its last assertion:

```python
    assert resp.status_code == 200
    body = resp.content.decode()
    # BOTH questions really are on the page -- the nested one rendered, and now it
    # renders WITH its result.
    assert body.count("el--fillblank") == 2
    assert child_class in body
    assert VERDICT in body          # was: assert VERDICT not in body
```

Rewrite the module docstring from "here is the divergence" to "here is the contract", keeping the falsification history (the `views.py:1060` mutant, and the `data-question` vacuity warning).

- [ ] **Step 3: Run the tests to verify they FAIL**

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py -v
```
Expected: the 5 `test_nested_blank_answer_shows_feedback` cases FAIL (`assert VERDICT in body`). The 6 controls PASS.

- [ ] **Step 4: Add `CONTAINER_MODELS` to `courses/builder.py`**

Immediately after the `_CONTAINER_REGISTRY` dict closes:

```python
# The five container model classes, DERIVED from _CONTAINER_REGISTRY so there is
# exactly one place that decides what a container is. Read by
# courses_extras.render_element to decide whether a render() accepts `page=` --
# the other eight render() signatures do not, and an unconditional `page=` would
# TypeError on every one of them (see test_render_seam.py).
CONTAINER_MODELS = frozenset(_CONTAINER_REGISTRY)
```

- [ ] **Step 5: Resolve the page values in `render_element`**

Add `editor_preview=None` as the last parameter of `render_element`, then insert immediately after the `if obj is None: return ""` guard:

```python
    # Page-level values a nested child needs. Six explicit statements, one per key
    # of the `page` dict below, so every name stays greppable. At TOP LEVEL these
    # are no-ops: _lesson_article.html passes exactly the page-context values the
    # fallback would read, so that render stays bit-identical.
    if feedback_for_pk is None:
        feedback_for_pk = context.get("feedback_for_pk")
    # `selected_ids` alone resolves by TRUTHINESS, not `is None`: its parameter
    # default is frozenset(), so `is None` could never fire, and an empty
    # selection renders identically to an unset one. See spec section 4.
    if not selected_ids:
        selected_ids = context.get("selected_ids") or frozenset()
    if submitted_values is None:
        submitted_values = context.get("submitted_values")
    if mark_result is None:
        mark_result = context.get("mark_result")
    # NOT `False`: a False default can never satisfy `is None`, which would make
    # this fallback dead code and silently no-op the editor-preview fix (Task 8).
    if editor_preview is None:
        editor_preview = bool(context.get("editor_preview"))
    # Context-only, never a tag argument -- page-level by nature (Task 2).
    feedback_ancestor_pks = context.get("feedback_ancestor_pks") or frozenset()
```

- [ ] **Step 6: Gate and pass the `page` dict**

Replace the non-question branch at the end of `render_element`:

```python
    # Function-local import, matching builder's own transfer-import convention:
    # a module-level import risks a cycle.
    from courses.builder import CONTAINER_MODELS

    extra = {}
    if type(obj) in CONTAINER_MODELS:
        # ONLY containers accept `page`. This branch is reached by every
        # non-question, non-HtmlElement type -- eight of the thirteen render()
        # signatures are leaves and would TypeError on an unconditional `page=`.
        extra["page"] = {
            "feedback_for_pk": feedback_for_pk,
            "selected_ids": selected_ids,
            # `or None` on both: an unresolvable template variable arrives as ''
            # (the quiz page's `st.mark_result` for a container row), and
            # ChoiceQuestionElement.choice_marks does `set(mark_result.reveal or ())`
            # before its per-choice mode branch -- ''.reveal is an AttributeError.
            "submitted_values": submitted_values or None,
            "mark_result": mark_result or None,
            "editor_preview": editor_preview,
            "feedback_ancestor_pks": feedback_ancestor_pks,
        }
    return mark_safe(  # noqa: S308 — each element template escapes its own fields
        obj.render(
            element=element,
            state=context.get("element_state"),
            slug=context.get("slug"),
            node_pk=context.get("node_pk"),
            **extra,
        )
    )
```

**`mode` is deliberately absent from that dict and must not be added** — see spec §6.6.

- [ ] **Step 7: Accept and splat `page` in all five containers**

For `CalloutElement.render` and `SpoilerElement.render`, the shape is:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None, page=None):
        from django.template.loader import render_to_string

        return render_to_string(
            "courses/elements/calloutelement.html",
            {
                # `page` FIRST -- it is the LOWEST-PRECEDENCE source, so this
                # container's own keys always win and the dict can never shadow
                # them however it later grows. Only containers take `page`: they
                # are the only element types that recursively render children.
                **(page or {}),
                "el": self,
                "children": self.resolved_children(),
                # `element_state`, NOT `state`: courses_extras.render_element reads
                # context.get("element_state") for the recursive child render.
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
            },
        )
```

`BeforeAfterElement.render` and `TwoColumnElement.render` take the same treatment, keeping their existing `eid` / `slots` / `columns` keys after the splat.

**`TabsElement.render` has TWO splats.** `page` goes first of all, `display_settings()` stays last:

```python
            {
                **(page or {}),
                "el": self,
                "tabs": self.resolved_tabs(),
                "eid": element.pk if element is not None else 0,
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
                # display_settings(), NOT normalized_data: resolved_tabs() already runs
                # normalize_data once, and running the DESTRUCTIVE normalizer twice per
                # response would re-mint ids on a damaged blob.
                **self.display_settings(),
            },
```

- [ ] **Step 8: Run the seam tests — expect PASS**

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py -v
```
Expected: all 11 PASS.

- [ ] **Step 9: Run the render-seam gate — expect PASS**

```bash
uv run pytest courses/tests/test_render_seam.py -v
```
Expected: all PASS (13 concretes × 6 placements). This is the test that catches an unconditional `page=`.

- [ ] **Step 10: Falsify — the container gate**

Temporarily change Step 6's `extra` block to pass `page=` unconditionally (delete the `if type(obj) in CONTAINER_MODELS:` line and dedent). Run:

```bash
uv run pytest courses/tests/test_render_seam.py -v
```
Expected: FAIL with `TypeError: render() got an unexpected keyword argument 'page'`. **Edit the condition back in by hand** — do not `git checkout` the file.

- [ ] **Step 11: Falsify — per-container isolation**

Delete `**(page or {}),` from `TabsElement.render` only. Run:

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py -v
```
Expected: exactly the `tabs` case FAILs; callout/spoiler/two_column/before_after stay green. Edit it back in.

(Blast radius is deliberately uneven — tabs, two_column and before_after give one-test isolation; callout and spoiler carry more once Task 3 lands.)

- [ ] **Step 12: Lint and commit**

```bash
uv run ruff check --no-cache courses/ && uv run ruff format --check courses/
git add courses/builder.py courses/templatetags/courses_extras.py courses/models.py courses/tests/test_nested_question_nojs_feedback.py
git commit -m "fix(nesting): forward page-level question values across the container barrier

Task 1. render_element builds one `page` dict and passes it ONLY to the five
container models, which splat it lowest-precedence into the child context.
Eight leaf render()s share the same generic branch and would TypeError on an
unconditional page=, so the call site gates on a new CONTAINER_MODELS derived
from _CONTAINER_REGISTRY.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The spoiler re-opens on the no-JS re-render

Without this the fix is invisible in the container it was built for: the no-JS path is a full page re-render and `<details>` has no `open`.

**Files:**
- Modify: `courses/builder.py` (add `ancestor_pks`, beside `element_depth`)
- Modify: `courses/views.py` — `check_answer`, the no-JS `ctx.update(...)`
- Modify: `courses/templatetags/courses_extras.py` (already reads the key — verify)
- Modify: `courses/models.py` — `SpoilerElement.render` gains `eid`
- Modify: `templates/courses/elements/spoilerelement.html:2`
- Create: `courses/tests/test_ancestor_pks.py`
- Modify: `courses/tests/test_nested_question_nojs_feedback.py`

**Interfaces:**
- Consumes: the `page` dict from Task 1.
- Produces: `builder.ancestor_pks(element) -> set[int]`.

- [ ] **Step 1: Write the failing helper test**

Create `courses/tests/test_ancestor_pks.py`:

```python
"""Unit tests for builder.ancestor_pks -- NO database.

The cycle case is a BOUND assertion, not a behavioural one. The mutant it guards
against (bounding the walk by len(ancestors) instead of a monotone hop counter)
does not fail, it HANGS: a set stops growing on a cycle, so the guard stays true
forever with a DB fetch per iteration. A hung pytest run also orphans the test DB
for the next run. So the fixture raises once the walk reads .parent too many
times, which is RED in milliseconds instead.
"""

import pytest

from courses.builder import MAX_NEST_DEPTH
from courses.builder import ancestor_pks


class _Node:
    """Anything with .pk and .parent satisfies ancestor_pks."""

    def __init__(self, pk):
        self.pk = pk
        self._parent = None
        self.reads = 0

    @property
    def parent(self):
        self.reads += 1
        # Correct code reads .parent exactly MAX_NEST_DEPTH + 2 == 6 times on a
        # cycle (one initializer + five iterations, since hops <= 4 admits
        # 0,1,2,3,4). The tripwire sits at 3x that so the margin is visible and a
        # correct implementation can never trip it.
        if self.reads > MAX_NEST_DEPTH * 3:
            raise AssertionError("ancestor_pks did not terminate on a cycle")
        return self._parent


def test_ancestor_pks_walks_the_whole_chain():
    a, b, c = _Node(1), _Node(2), _Node(3)
    c._parent = b
    b._parent = a
    assert ancestor_pks(c) == {1, 2}


def test_ancestor_pks_is_empty_for_a_top_level_element():
    assert ancestor_pks(_Node(1)) == set()


def test_ancestor_pks_terminates_on_a_cycle():
    a, b = _Node(1), _Node(2)
    a._parent = b
    b._parent = a
    ancestor_pks(a)  # must RETURN; the fixture raises if it loops
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest courses/tests/test_ancestor_pks.py -v
```
Expected: FAIL — `ImportError: cannot import name 'ancestor_pks'`.

- [ ] **Step 3: Implement `ancestor_pks` in `courses/builder.py`**

Place it directly after `element_depth`:

```python
def ancestor_pks(element):
    """Pks of every join row above `element` (its parent, grandparent, ...).

    `hops` is a SEPARATE MONOTONE COUNTER, never len(ancestors): a set stops
    growing on a parent cycle (A->B->A saturates at 2), so a size-bounded guard
    would stay true forever and loop with a DB fetch per iteration inside a
    student-facing POST. element_depth and payloads.validate_nesting both count
    hops for exactly this reason.

    MAX_NEST_DEPTH is 4 and a top-level element has depth 1, so well-formed
    content has at most three ancestors and the walk always terminates on
    `node is None`; the guard is purely a corruption backstop.
    """
    ancestors, node, hops = set(), element.parent, 0
    while node is not None and hops <= MAX_NEST_DEPTH:
        ancestors.add(node.pk)
        node = node.parent
        hops += 1
    return ancestors
```

- [ ] **Step 4: Run it to verify it passes**

```bash
uv run pytest courses/tests/test_ancestor_pks.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Seed the ancestor set in `check_answer`**

In `courses/views.py::check_answer`, the no-JS branch:

```python
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    from courses.builder import ancestor_pks

    ctx = full_lesson_render_context(node, request.user)
    selected = selected_ids(answer)
    submitted = None if isinstance(answer, (set, frozenset)) else answer
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=selected,
        submitted_values=submitted,
        mark_result=result,
        # A spoiler renders `open` when the checked element is anywhere in its
        # subtree. Ancestry, not direct childhood, so a question inside a callout
        # inside a spoiler opens the spoiler too.
        feedback_ancestor_pks=ancestor_pks(element),
    )
```

- [ ] **Step 6: Give `SpoilerElement.render` an `eid`**

Add to its context dict (after the `**(page or {})` splat):

```python
                # element.pk, NOT node_pk: node_pk is the UNIT's pk, the same for
                # every element on the page. `element` is None only in direct
                # render() calls, so the 0 sentinel cannot collide on a served page.
                "eid": element.pk if element is not None else 0,
```

- [ ] **Step 7: Re-open the disclosure in the template**

`templates/courses/elements/spoilerelement.html` line 2:

```html
<details class="spoiler"{% if feedback_ancestor_pks and eid in feedback_ancestor_pks %} open{% endif %}>
```

Add a `{% comment %}` above it recording: the no-JS path is a full page re-render, so without this the verdict renders inside a closed disclosure; and the `feedback_ancestor_pks and` guard is required because on a direct `render()` with no `page` the key is absent from context entirely — a bare membership test would only work because Django's `smartif` swallows the `TypeError`.

- [ ] **Step 8: Assert `open` in the spoiler seam test**

In `courses/tests/test_nested_question_nojs_feedback.py`, add to the parametrized blank-answer test, guarded to the spoiler case:

```python
    if child_class == "spoiler__child":
        # The no-JS path re-renders the whole page; a closed <details> would hide
        # the verdict we just asserted is present.
        assert "<details class=\"spoiler\" open>" in body
```

- [ ] **Step 9: Run and verify**

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py courses/tests/test_ancestor_pks.py -v
```
Expected: all PASS.

- [ ] **Step 10: Falsify — twice**

(a) Delete ` open` from the template's `{% if %}`. Run the seam tests → the spoiler case FAILs, the plain `VERDICT in body` half stays green. Restore.
(b) Remove `feedback_ancestor_pks=ancestor_pks(element)` from `check_answer`'s `ctx.update`. Run → the same assertion FAILs. Restore.

Both halves need their own RED — an implementer who plumbs the template but forgets the view must have something to catch it.

- [ ] **Step 11: Lint and commit**

```bash
uv run ruff check --no-cache courses/ && uv run ruff format --check courses/
git add courses/builder.py courses/views.py courses/models.py templates/courses/elements/spoilerelement.html courses/tests/
git commit -m "fix(nesting): re-open a spoiler holding the checked question on the no-JS re-render

Task 2. The no-JS path re-renders the whole page and <details> has no `open`,
so the verdict landed inside a closed disclosure -- the fix was invisible in the
one container the capability was built for. check_answer walks the ancestor
chain once (monotone hop counter, not set size: a cycle saturates a set and
would loop forever) and the spoiler opens when the checked element is in its
subtree.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The remaining seam and claim tests

Pins the type axis, depth-2 recursion, and the four design claims. Needs no production change — nested rows are created directly, bypassing `resolve_scope`, so this runs before the widening.

**Files:**
- Modify: `courses/tests/test_nested_question_nojs_feedback.py`

**Interfaces:**
- Consumes: Task 1's `page` dict, Task 2's `feedback_ancestor_pks`.

- [ ] **Step 1: Add the type-axis fixtures**

The three new types have **no per-type marker class** — `choicequestion.html`, `shorttextquestionelement.html` and `shortnumericquestionelement.html` all render the byte-identical `<div class="el el--question" data-question>`. Only `fill_blank` has `el--fillblank`. So guards are **positional**: slice the body to the `callout__child` wrapper and assert inside that slice.

```python
def _choice():
    q = ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False)
    Choice.objects.create(question=q, text="right", is_correct=True)
    Choice.objects.create(question=q, text="wrong", is_correct=False)
    return q


def _short_text():
    return ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")


def _short_numeric():
    return ShortNumericQuestionElement.objects.create(stem="2+2?", value="4", tolerance="0")


# (make_question, blank POST) -- what "blank" is ON THE WIRE per type. Exact,
# or answer_is_empty never fires and the test proves nothing:
#   choice        -> post.getlist("choice") -> NO "choice" key at all
#   short_text    -> post.get("answer", "") -> {"answer": ""}
#   short_numeric -> post.get("answer", "") -> {"answer": ""}
TYPES = [
    pytest.param(_choice, {}, id="choice"),
    pytest.param(_short_text, {"answer": ""}, id="short_text"),
    pytest.param(_short_numeric, {"answer": ""}, id="short_numeric"),
]
```

- [ ] **Step 2: Add seam tests 6–8 (type axis, in a callout)**

```python
@pytest.mark.parametrize(("make_question", "blank_post"), TYPES)
def test_nested_blank_answer_shows_feedback_by_type(scene, client, make_question, blank_post):
    """Three NEW types, not four: fill_blank x callout is already the container axis."""
    _student, unit, _top, build = scene
    nested_row = build_typed(unit, _callout, make_question)

    resp = client.post(_check_url(unit, nested_row.pk), blank_post)
    assert resp.status_code == 200
    body = resp.content.decode()
    slice_ = _child_slice(body, "callout__child")
    # Positional guard: these three types share identical wrapper markup, so the
    # nested render is identified by POSITION plus its own form action, which
    # carries the NESTED element's pk and cannot collide with the top-level twin.
    assert f"/{nested_row.pk}/" in slice_
    assert VERDICT in slice_
```

Add `_child_slice(body, cls)` — a small helper returning the substring from the wrapper `<div class="…__child">` to its close.

- [ ] **Step 3: Add seam test 9 (depth 2) and 10 (the §2.2 filter)**

```python
def test_nested_blank_answer_shows_feedback_at_depth_2(scene, client):
    """A question in a callout in a spoiler. Pins that the recursion RE-EMITS
    rather than forwarding one level, and that ancestry (not direct childhood)
    drives the spoiler's `open`."""
    ...
    assert VERDICT in body
    assert "<details class=\"spoiler\" open>" in body


def test_only_the_checked_question_shows_a_verdict(scene, client):
    """Invariant A. Without this, every flipped assertion would pass just as well
    if the fix leaked a verdict onto EVERY question on the page."""
    ...
    assert body.count(VERDICT) == 1
    assert VERDICT in _child_slice(body, "callout__child")
```

- [ ] **Step 4: Add the seven claim tests**

Per spec §9.4, in the same file:

1. **Invariant B** — two nested `choice` questions, one checked: the sibling renders **zero** `question__choice-marker` and `question__choice-feedback`. (Seam test 10 cannot catch this — the marker path emits no verdict block to count.)
2. **Quiz page still renders** — a quiz containing a container with a nested **choice** child returns 200 with no `question__verdict` / `question__choice-marker`. Build it with a direct `Element.objects.create` (§6 forbids authoring it — legacy content must not 500). Plus `"selected_ids" not in build_quiz_context(...)`.
3. **Restore and live routes agree** — POST a whitespace-bearing answer (live route), then GET the lesson page (`feedback_for_pk` is `None`, so restore runs) and assert the verdict text and refilled value are byte-identical.
4. **`None` and `""` refill identically** — a blank nested short-text answer and a blank top-level one produce the same empty input, pinning the `default_if_none:''` the `or None` coercion rests on.
5. **Shadowing is impossible** — **parametrized over all five container models**: `render(page={"el": "HIJACKED", ...})` still renders the container's own element.
6. **Spoiler `eid` sentinel** — `SpoilerElement.render(element=None)` returns without raising. Nothing in `test_render_seam.py` covers this: its CONCRETES loop passes a real join row, and its only `element=None` case uses `FillGateElement`.
7. **`mode` is not forwarded** —

```python
def test_mode_is_not_forwarded_to_a_nested_child(monkeypatch, scene, client):
    captured = {}

    def capture(self, *, element=None, state=None, slug=None, node_pk=None, page=None):
        captured.update(page or {})
        return ""  # render_element mark_safe()s the result

    monkeypatch.setattr(CalloutElement, "render", capture)
    ...
    # Assert the FULL key set, not just the absence: `"mode" not in captured` is
    # green when `page` never arrived at all.
    assert captured.keys() == {
        "feedback_for_pk", "selected_ids", "submitted_values",
        "mark_result", "editor_preview", "feedback_ancestor_pks",
    }
```

- [ ] **Step 5: Run the whole file**

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py -v
```
Expected: all PASS.

- [ ] **Step 6: Falsify — two mutants**

(a) Add `"mode": mode` to the `page` dict → the `mode` claim test FAILs. Remove it.
(b) Move `**(page or {})` from first to last in `CalloutElement.render` → the shadowing test FAILs for callout. Restore.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache courses/tests/ && uv run ruff format --check courses/tests/
git add courses/tests/test_nested_question_nojs_feedback.py
git commit -m "test(nesting): pin the type axis, depth-2 recursion and the four design claims

Task 3. Guards are POSITIONAL: choice/short_text/short_numeric render
byte-identical wrapper markup, so only fill_blank has a type class to assert on.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Widen the allowlist, aliases, and the add menu

**Files:**
- Modify: `courses/builder.py:85-132`
- Modify: `templates/courses/manage/editor/_add_menu.html`
- Modify: `courses/tests/test_beforeafter_nesting.py`, `courses/tests/test_spoiler_nesting.py`, `tests/test_twocolumn_registry.py`, `tests/test_tabs_registry.py`
- Create: endpoint tests for the four form keys

- [ ] **Step 1: Widen the constants**

```python
NESTABLE_TYPE_KEYS = frozenset(
    {
        ...
        "choice",
        "short_text",
        "short_numeric",
        ...
    }
)

# The nestable QUESTION keys, as transfer keys. Read by the three authorities that
# decide whether a NEW nesting may be created: resolve_scope, paste_allowed, and
# transfer.payloads.validate_nesting. The LAL loader keeps its own, narrower
# allowlist. The two authorities that decide whether an EXISTING nesting may be
# PRESERVED across a unit_type flip do NOT read this set -- they go through the
# deliberately WIDER unit_has_nested_question().
NESTABLE_QUESTION_KEYS = frozenset(
    {"choice", "short_text", "short_numeric", "fill_blank"}
)
```

Add **three** aliases (not four — `fillblankquestion` already exists):

```python
_NESTABLE_FORM_KEY_ALIASES = {
    ...
    "choicequestion": "choice",
    "shorttextquestion": "short_text",
    "shortnumericquestion": "short_numeric",
}
```

**The choice alias is `choicequestion`, never `choice-single`/`choice-multi`.** `element_add` (`views_manage.py:2128-2134`) reads the card name to decide `multiple` and *then* sets `type_key="choicequestion"` before calling `resolve_scope`, so the card names never reach this map. Also update the prose comment above `NESTABLE_TYPE_KEYS` (`:85-88`) listing which types' form key differs from their transfer key.

- [ ] **Step 2: Add the nested `Questions` group**

In `_add_menu.html`, as a **sibling** of the `{% if not nested %}` block (never inside it — a `{% if nested %}` group nested in `{% if not nested %}` is unreachable, and the failure is silent). Move the `{% if nested %}`-gated fill-blank card out of `Interactive`; leave the top-level card at line 64 alone.

```html
    {% if nested and not unit_is_quiz %}
    {% comment %}
    Questions nested in a container -- LESSON UNITS ONLY. The server enforces this
    at five authorities regardless; hiding the group is courtesy.

    NO depth gate, unlike the container cards: questions are LEAVES, so from a menu
    at depth d they land at d+1, which resolve_scope clause 3 accepts up to
    MAX_NEST_DEPTH. Containers need `depth < max_nest_depth|add:-1` only because a
    container child must itself still have room for children.

    data-add-type values are the CARD names -- element_add reads choice-single /
    choice-multi to set `multiple`, then collapses both to "choicequestion" for the
    nesting check. Emitting "choicequestion" here would NOT error (it is in the
    allow-tuple) -- both cards would 200 and silently produce single-choice.
    {% endcomment %}
    <p class="typemenu__group-label">{% trans "Questions" %}</p>
    <div class="typemenu__group">
      <button type="button" class="typecard" data-add-type="choice-single">…{% trans "Single choice" %}</button>
      <button type="button" class="typecard" data-add-type="choice-multi">…{% trans "Multiple choice" %}</button>
      <button type="button" class="typecard" data-add-type="shorttextquestion">…{% trans "Short text" %}</button>
      <button type="button" class="typecard" data-add-type="shortnumericquestion">…{% trans "Short numeric" %}</button>
      <button type="button" class="typecard" data-add-type="fillblankquestion">…{% trans "Fill in the blanks" %}</button>
    </div>
    {% endif %}
```

Copy each card's `<svg class="ic">…<use href="#el-…"/></svg>` markup from its top-level twin at `_add_menu.html:60-64`.

- [ ] **Step 3: Run the sweep for expected-RED tests**

```bash
uv run pytest courses/tests/test_beforeafter_nesting.py courses/tests/test_spoiler_nesting.py tests/test_twocolumn_registry.py tests/test_tabs_registry.py -v
```
Expected FAILs (all four are **expected**, not regressions):
- `test_beforeafter_nesting.py:52` — `resolve_scope(…, "choice")` no longer raises. Its docstring literally names this change as its mutant.
- `test_twocolumn_registry.py:53` — same, with the *form* key `"choicequestion"`.
- `test_spoiler_nesting.py:157` — same, key hidden in a `for bad in (…)` loop variable.
- `test_tabs_registry.py:74` — `element_add` with `choicequestion` into a tab now 200s instead of 400.
- `test_spoiler_nesting.py` add-menu absence assertions at `:351-363`, `:389`, `:444-448`.

- [ ] **Step 4: Rewrite each as quiz-conditional**

Each refusal becomes: **refused in a quiz unit, accepted in a lesson**. For example:

```python
def test_a_graded_question_is_refused_as_a_child_of_a_QUIZ_before_after():
    """The refusal is now conditional on unit.unit_type, not on the type alone.

    Mutant: drop resolve_scope's quiz clause -> accepted, this goes RED.
    """
    _course, unit = make_course_with_unit(unit_type="quiz")
    join = _ba(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(join.pk), BeforeAfterElement.BEFORE_SLOT_ID, "choice")


def test_a_graded_question_is_accepted_as_a_child_of_a_LESSON_before_after():
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    parent, tab = builder.resolve_scope(unit, str(join.pk), BeforeAfterElement.BEFORE_SLOT_ID, "choice")
    assert parent == join
```

For the add-menu assertions: drag/grid/extended keys stay banned nested; the four widened keys become expected-**present** in a lesson and expected-**absent** in a quiz.

Also fix `test_spoiler_nesting.py:179-180`, which **stays green but becomes a lie** — it asserts `"choicequestion" not in NESTABLE_TYPE_KEYS` under the comment `# genuinely non-nestable`. Drop `choicequestion` from that tuple or reword to "form keys never appear in the transfer-key set".

- [ ] **Step 5: Add the add-menu placement tests**

In `test_spoiler_nesting.py`: nested + lesson shows the five cards; nested + quiz shows none of them; top level unchanged. **Assert the five `data-add-type` strings, not a card count** — a count is blind to the `choicequestion` mix-up. Note `tests/test_manage_editor_menu.py` pins 24 for its **quiz** fixture; a top-level lesson menu is 33.

- [ ] **Step 6: Add four `element_add` endpoint tests**

These are what actually catch a wrong alias — the drift test cannot, because `choice-single → choice` is well-formed and simply never consulted.

```python
@pytest.mark.parametrize(
    ("add_type", "model", "multiple"),
    [
        ("choice-single", ChoiceQuestionElement, False),
        ("choice-multi", ChoiceQuestionElement, True),
        ("shorttextquestion", ShortTextQuestionElement, None),
        ("shortnumericquestion", ShortNumericQuestionElement, None),
    ],
)
def test_nested_add_of_a_widened_question_type(client, add_type, model, multiple):
    course, unit = _managed(client)          # a LESSON unit
    callout = CalloutElement.objects.create(kind="example")
    join = Element.objects.create(unit=unit, content_object=callout)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": add_type, "unit": unit.pk, "parent": join.pk, "tab": CalloutElement.SLOT_ID},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    row = Element.objects.get(parent=join)
    assert isinstance(row.content_object, model)
    assert row.tab_id == CalloutElement.SLOT_ID
    if multiple is not None:
        assert row.content_object.multiple is multiple
```

Plus a fifth asserting the same POST 400s on a **quiz** unit.

- [ ] **Step 7: Run, falsify, lint, commit**

Falsify: change the alias to `"choice-single": "choice"` → the **two choice** endpoint tests FAIL and the short-text/short-numeric ones stay **green** (they resolve through untouched aliases). Do not chase the greens.

```bash
uv run pytest courses/tests/test_beforeafter_nesting.py courses/tests/test_spoiler_nesting.py tests/test_twocolumn_registry.py tests/test_tabs_registry.py tests/test_manage_editor_menu.py -v
uv run ruff check --no-cache courses/ tests/ && uv run ruff format --check courses/ tests/
git commit -m "feat(nesting): allow choice/short_text/short_numeric inside lesson containers

Task 4. Three transfer keys, three form-key aliases (choicequestion, not the
choice-single/choice-multi card names -- element_add collapses those before
resolve_scope sees them), and a nested Questions group gated on
`nested and not unit_is_quiz`.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The lesson-only gates in `builder` and the paste endpoint

**Files:**
- Modify: `courses/builder.py` — `unit_has_nested_question`, `resolve_scope`, `paste_allowed`, `rename_node`
- Modify: `courses/views_manage.py:1558-1567` — `PASTE_REFUSAL_MESSAGES`
- Create/modify: gate tests

- [ ] **Step 1: Add `unit_has_nested_question`**

```python
def unit_has_nested_question(unit):
    """True iff `unit` holds a question inside a container (parent is not null).

    Scoped over ALL QuestionElement subclasses, deliberately WIDER than
    NESTABLE_QUESTION_KEYS: a nested extended_response or drag type can exist via a
    crafted POST or a hand-built archive, and such a unit must still be refused the
    flip to quiz. Narrowing this to NESTABLE_QUESTION_KEYS reopens that hole.
    """
    # CONCRETE_QUESTION_MODELS is the SAME source the pre-flight uses -- two lists
    # of ten would drift. Function-local, matching this module's import convention.
    from courses.richtext import CONCRETE_QUESTION_MODELS

    ct_ids = {ContentType.objects.get_for_model(m).id for m in CONCRETE_QUESTION_MODELS}
    return Element.objects.filter(
        unit=unit, parent__isnull=False, content_type_id__in=ct_ids
    ).exists()
```

Add `from django.contrib.contenttypes.models import ContentType` at module level.

**Check before moving on:** this runs inside `rename_node`'s `@transaction.atomic` + `select_for_update`, and `get_for_model` issues extra SELECTs on a cold cache. `build_lesson_context` documents rejecting exactly this pattern because it broke `tests/test_html_element.py`'s query-count assertion. Run `uv run pytest tests/test_html_element.py -v` and any `assertNumQueries` test touching the rename path; if one trips, switch to an `app_label` + `model__in=[...]` filter (the shape `has_stateful_elements` uses).

- [ ] **Step 2: `resolve_scope` clause**

Immediately after clause 1 (the `NESTABLE_TYPE_KEYS` membership check at `:284-285`):

```python
    if child_key in NESTABLE_QUESTION_KEYS and unit.unit_type == ContentNode.UnitType.QUIZ:
        raise NestingError("questions may not be nested in a quiz")
```

- [ ] **Step 3: `paste_allowed` clause + message**

Immediately after the `type_not_nestable` clause (`:441-444`), **inside the `dest_parent is not None` branch** — pasting a question to top level in a quiz must stay legal:

```python
        if (
            model_to_key(type(marked_join.content_object)) in NESTABLE_QUESTION_KEYS
            and unit.unit_type == ContentNode.UnitType.QUIZ
        ):
            return False, "question_in_quiz"
```

Update the docstring's reason precedence to `…, type_not_nestable, question_in_quiz, too_deep, own_slot`. Then add to `views_manage.PASTE_REFUSAL_MESSAGES`:

```python
    "question_in_quiz": gettext_lazy(
        "Questions can only be placed inside a container in a lesson unit."
    ),
```

- [ ] **Step 4: `rename_node` flip guard**

Inside the existing `if node.kind == ContentNode.Kind.UNIT:` block, **before** the `node.unit_type = unit_type` assignment at `:607`:

```python
        if unit_type is not _UNSET:
            # BEFORE the assignment: read after it and `!= unit_type` is permanently
            # False, making this dead code no static reading reveals. After
            # _check_token, so a stale-token request fails on the token.
            if (
                unit_type == ContentNode.UnitType.QUIZ
                and node.unit_type != unit_type
                and unit_has_nested_question(node)
            ):
                raise ValidationError(
                    "This unit has a question inside a container. Move it out of the "
                    "container before turning the unit into a quiz."
                )
            node.unit_type = unit_type
            fields.append("unit_type")
```

Quiz→lesson stays unconditionally allowed; a quiz→quiz no-op is accepted.

- [ ] **Step 5: Write the gate tests**

- `resolve_scope` raises for a question into a quiz container.
- `paste_allowed` returns `question_in_quiz`; returns it **ahead of `too_deep`** for a case that trips both; still permits a **top-level** paste into a quiz; and — asserted **on the endpoint** — surfaces its own message, not the generic fallback.
- A completeness assertion using **`ast`**, restricted to `Return` nodes inside `paste_allowed`'s body (a source regex would sweep the docstring, which lists the reason names in prose; a hand-maintained constant just moves the drift):

```python
def test_every_paste_reason_has_a_message():
    tree = ast.parse(Path(builder.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "paste_allowed")
    returned = {
        n.value.elts[1].value
        for n in ast.walk(fn)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Tuple)
        and len(n.value.elts) == 2
        and isinstance(n.value.elts[1], ast.Constant)
        and isinstance(n.value.elts[1].value, str)
    }
    # SUBSET, never equality: the map also holds `parent_gone`, which
    # paste_allowed never returns.
    assert returned <= set(PASTE_REFUSAL_MESSAGES)
```

- `rename_node`: flip refused, `unit_type` unchanged, quiz→quiz no-op accepted, quiz→lesson allowed, **plus the wide-predicate case** — a nested `extended_response` created with a direct `Element.objects.create` must still block the flip. Without that case, narrowing `unit_has_nested_question` to `NESTABLE_QUESTION_KEYS` stays green.

- [ ] **Step 6: Run, falsify, lint, commit**

Falsify: narrow `unit_has_nested_question` to `NESTABLE_QUESTION_KEYS` → the `extended_response` case FAILs, the `fill_blank` case stays green. Restore.

```bash
git commit -m "feat(nesting): refuse a nested question in a quiz at three builder authorities

Task 5. resolve_scope, paste_allowed (inside the dest_parent branch, so a
top-level paste into a quiz stays legal) and rename_node's lesson->quiz flip.
The flip guard reads unit_type BEFORE the assignment or it is dead code.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Transfer — archive refusal and the `FORMAT_VERSION` bump

**Files:**
- Modify: `courses/transfer/payloads.py:858`, `courses/transfer/schema.py:14,358`
- Modify: 7 files asserting `FORMAT_VERSION == 11`; `tests/test_tabs_transfer.py:142`

- [ ] **Step 1: `validate_nesting` gains `unit_types=None`**

Keyword-with-default is **required**, not a convenience: 19 positional call sites across six test files pass `elements` alone and must keep working. Add the clause **immediately after** the existing `NESTABLE_TYPE_KEYS` clause (`:922`), so "not nestable at all" still wins over "not nestable here":

```python
        if (
            unit_types is not None
            and el["type"] in NESTABLE_QUESTION_KEYS
            and unit_types.get(el["unit"]) == "quiz"
        ):
            _err(
                _("Element '%(el)s' is a question and may not be nested in a quiz."),
                el=el["id"],
            )
```

`el["unit"]`, deliberately — **not** the parent's unit. `validate_nesting` never checks that a child and its parent share a unit, so the two lookups can disagree; `el["unit"]` is the unit the row is actually created in, and `schema.py:344-349` has already validated it points at a unit node. `"quiz"` is the **raw string** — the archive's `unit_type` is validated at `schema.py:281` against the literal pair and never becomes a `ContentNode`.

- [ ] **Step 2: `schema.py` builds and passes the map, and bumps the version**

```python
FORMAT_VERSION = 12
```

```python
    unit_types = {
        nd["id"]: nd.get("unit_type")
        for nd in nodes
        if nd.get("kind") == "unit"
    }
    validate_nesting(elements, unit_types=unit_types)
```

- [ ] **Step 3: Run and watch eight assertions go RED**

```bash
uv run pytest courses/tests/test_beforeafter_transfer.py courses/tests/test_image_size_transfer.py tests/test_link_transfer.py tests/test_table_transfer.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py -v
```
Expected: seven `assert FORMAT_VERSION == 11` (or `manifest["format_version"] == 11`) FAIL, plus `test_tabs_transfer.py::test_nesting_validation_rejects[choice-child]`.

- [ ] **Step 4: Fix them**

Bump each literal `11` → `12`. For the tabs case, swap the subject to a still-non-nestable type and add a positive case:

```python
        _els(_tabs_el(), _child(type_="extended_response")),  # still non-nestable
```

```python
def test_nesting_validation_accepts_a_choice_child():
    validate_nesting(_els(_tabs_el(), _child(type_="choice")))  # must not raise
```

- [ ] **Step 5: Add the round-trip test**

`choice` is the only newly nestable type with child rows, and the paste flow and `duplicate_element` both go through the transfer serializers — so duplicating a callout is the first thing an author does after nesting a question. Assert `parent`, `tab_id`, concrete type and the `Choice` rows (`is_correct`, `feedback`) all survive `build_export` → `validate_document` → import.

- [ ] **Step 6: Verify the 19 positional call sites still pass**

```bash
uv run pytest courses/tests/test_beforeafter_transfer.py courses/tests/test_callout_transfer.py courses/tests/test_spoiler_transfer.py tests/test_tabs_transfer.py tests/test_transfer_nesting_depth.py tests/test_twocolumn_transfer.py -v
```
Expected: all PASS — that is exactly what the keyword-with-default protects.

- [ ] **Step 7: Re-check for a competing bump, then commit**

```bash
gh pr list --state open
```
Two branches bumping `FORMAT_VERSION` to the **same** number produce no git conflict — identical lines merge silently and one capability ships under a version claiming the other. This was empty at spec time; confirm again.

```bash
git commit -m "feat(transfer): refuse a nested question in a quiz archive, bump FORMAT_VERSION to 12

Task 6. The set of legal archive contents changed even though the shape did not,
so an unbumped archive would import into an older deployment and be rejected with
a message blaming the content rather than the version skew.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The LAL loader guard

**Files:**
- Modify: `courses/lal_loader/builders.py` — one guard at the top of `build_element`
- Create: `tests/lal_import/test_loader_question_in_quiz.py`

- [ ] **Step 1: Add the guard at the TOP of `build_element`**

**Not at the container branches.** The loader has **two** recursive nesting sites and they are not equally guarded: `if etype == "spoiler":` (`:114-163`) gates children against `LAL_SPOILER_CHILD_TYPES`, but `if etype == "tabs":` (`:201-224`) recurses with **no allowlist and no unit-type check at all** — and the file has `choice` (`:378`), `numeric` (`:400`), `shorttext` (`:425`) and `fillblank` (`:237`) branches all reachable from it. A guard at the spoiler branch would close half the hole.

```python
    # Nested question in a QUIZ unit: refused for every recursion site at once.
    # `parent is not None` means "this call is creating a nested row". Placed here,
    # not at the container branches: the tabs recursion is entirely ungated, and a
    # per-branch guard would have to be remembered a third time by the next slice.
    # AFTER the `flagged` exemption, which can only ever produce an HtmlElement.
    if (
        parent is not None
        and not el.get("flagged")
        and _PARSER_TO_CANONICAL.get(etype, etype) in LAL_QUESTION_TYPES
        and unit.unit_type == ContentNode.UnitType.QUIZ
    ):
        raise LoaderError(
            f"a question ({etype}) may not be nested in quiz unit {unit.pk}; "
            "questions nest in lesson units only"
        )
```

Define `LAL_QUESTION_TYPES = frozenset({"choice", "numeric", "shorttext", "fillblank"})` beside `LAL_SPOILER_CHILD_TYPES`, using this loader's own type names.

**The tabs recursion's missing type allowlist stays out of scope** — a pre-existing `NESTABLE_TYPE_KEYS` bypass this task neither widens nor closes.

- [ ] **Step 2: Two loader tests, one per recursion site**

```python
def test_fillblank_in_a_spoiler_in_a_quiz_is_refused():
    """The spoiler path -- fill_blank is the only question type its allowlist admits."""

def test_choice_in_a_tabs_element_in_a_quiz_is_refused():
    """The tabs path: NO allowlist at all, so a spoiler-only gate leaves this green.
    This is the case that proves the guard sits at build_element, not at a branch."""

def test_flipping_to_quiz_while_dropping_the_nested_question_is_accepted():
    """upsert_node runs BEFORE rebuild_unit_elements, which deletes every element
    first -- so a guard on the flip would stale-read the previous run and refuse a
    legal manifest revision. The child-creation guard sees the NEW unit_type and
    the NEW children, and transaction.atomic rolls the flip back on refusal."""
```

- [ ] **Step 3: Falsify, lint, commit**

Move the guard into the `spoiler` branch only → the **tabs** test FAILs, the spoiler one stays green. Restore.

```bash
git commit -m "feat(lal): refuse a nested question in a quiz unit at both loader recursion sites

Task 7. The loader nests under spoiler AND tabs; the tabs recursion has no
allowlist at all, so the guard goes at the top of build_element rather than at a
container branch.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The editor preview

**Files:**
- Modify: `templates/courses/manage/editor/_preview.html:16`
- Modify: `courses/templatetags/courses_extras.py` — question branch
- Modify: `courses/views_manage.py:2363-2373` — `element_try`'s choice branch

- [ ] **Step 1: Flag the preview**

```html
<section class="prev-el" data-element-id="{{ el.pk }}">{% render_element el action_url=try_url editor_preview=True %}</section>
```

Add a comment naming `editor_preview` as **not** the existing `previewing` flag (`views.py:1394`), which means "a non-enrolled **student** is viewing this quiz" — the opposite audience, and one that must never route forms at a manage-gated endpoint.

- [ ] **Step 2: Reverse the child's own try URL**

In `render_element`'s question branch, before calling `obj.render(...)`:

```python
        if action_url is None and editor_preview and element is not None:
            # A NESTED question in the preview: reverse the try URL for ITS OWN pk.
            # Forwarding the parent's action_url would post the child's answer to
            # the parent's endpoint; without this the render falls back to the
            # STUDENT check_answer URL and persists practice state for the author.
            action_url = reverse(
                "courses:manage_element_try",
                kwargs={"slug": element.unit.course.slug, "pk": element.pk},
            )
```

Top-level preview elements keep their explicitly passed `try_url` and are untouched — this fires only where `action_url` is absent, which today means exactly "nested".

- [ ] **Step 3: `element_try`'s choice branch (defence-in-depth only)**

```python
                question.render(
                    element=el,
                    mode="lesson",
                    selected_ids=selected,
                    mark_result=result,
                    feedback_for_pk=el.pk,
                    action_url=reverse(
                        "courses:manage_element_try",
                        kwargs={"slug": el.unit.course.slug, "pk": el.pk},
                    ),
                )
```

**This fixes nothing observable.** `editor.js` fetches `tryForm.getAttribute("action")` from the **live** form node (`:250`) and swaps only `innerHTML` (`:272`), so the response's `action` is discarded. It is kept because a manage-gated fragment should not carry a student endpoint in its markup — two lines. If it costs more than that, **drop it**; that is the correct call, not a compromise. `reverse()` takes `kwargs=`, not loose keyword arguments.

(`element_try`'s quiz `INLINE_QUIZ_REVEAL` branch at `:2393-2405` is deliberately left alone: after Task 5 a nested question cannot exist in a quiz.)

- [ ] **Step 4: Preview tests**

A nested question's form `action` is `manage_element_try` for **its own** pk — three distinct assertions, since two of them are the actual bug: not `check_answer`, not the parent's pk, equal to the child's own try URL.

- [ ] **Step 5: Falsify, lint, commit**

Falsify: default `editor_preview` to `False` instead of `None` → the preview test FAILs (the fallback becomes dead code). Restore.

```bash
git commit -m "fix(editor): post a nested question's preview Check to its own try endpoint

Task 8. A nested question rendered with action_url=None and fell back to the
STUDENT check_answer URL, persisting practice state against the author's own
account.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Translations, stale comments, and the content pre-flight

**Files:**
- Modify: `locale/{en,pl}/LC_MESSAGES/django.po` (+ `.mo`)
- Modify: `courses/views.py` (`has_questions` comment), `courses/views_manage.py:2179-2181`

- [ ] **Step 1: Run the pre-flight against the local dev database**

```python
from courses.richtext import CONCRETE_QUESTION_MODELS

question_ct_ids = {ContentType.objects.get_for_model(m).id for m in CONCRETE_QUESTION_MODELS}
Element.objects.filter(
    parent__isnull=False,
    content_type_id__in=question_ct_ids,
    unit__unit_type=ContentNode.UnitType.QUIZ,
).count()
```

All ten models, not the four widened ones — the point is to find anything at all. Expected: **0**. A non-zero count **halts the task and is reported**; do not auto-repair, the remedy (un-nest, delete, or convert the unit) is an editorial decision.

- [ ] **Step 2: Fix the two stale comments**

`courses/views.py` (~`:416-419`): "Only fill_blank is nestable today, so this only newly fires for a nested fillblank" — now four types. `courses/views_manage.py:2179-2181`: states `"choicequestion"` "is not in `NESTABLE_TYPE_KEYS`, so clause 1 rejects it" — false after Task 4, and it sits directly above the call site.

- [ ] **Step 3: Regenerate translations**

```bash
uv run python manage.py makemessages -l en -l pl
```

Fill in the new msgids (`NestingError`, `ValidationError`, `_err()`, `PASTE_REFUSAL_MESSAGES["question_in_quiz"]`). The loader's `LoaderError` is operator-facing and **not** translated.

**Clear every fuzzy pre-fill.** `makemessages` fuzzy-fills a *wrong* Polish string from a similar msgid, and a fuzzy entry is not used at runtime — so it silently reads as "translation missing" in production. Removing one means deleting **both** the `#, fuzzy` marker and the wrong `msgstr`.

```bash
uv run python manage.py compilemessages
uv run pytest tests/ -k i18n -v
```

- [ ] **Step 4: Commit**

```bash
git commit -m "i18n(nesting): new refusal messages, EN+PL, fuzzy pre-fills cleared

Task 9. Also corrects two comments the widening falsified.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: e2e and visual verification

**Files:**
- Create: `tests/test_e2e_nested_question.py`

- [ ] **Step 1: e2e — a nested choice question with JS on**

Inside a **closed** `<details>` spoiler and inside an **inactive** tab panel, it must still check and show inline feedback. `question.js` binds to `[data-question]` document-wide with no depth assumption, so no JS change is expected — the e2e proves that rather than assuming it.

Two traps to design around:
- Playwright reports a `.visually-hidden` element as **visible** (1×1 + `clip` has a non-empty box) — assert on `bounding_box()`, not `is_visible()`.
- A closed `<details>` hides content via `content-visibility`, so use `checkVisibility()` rather than `is_visible()`.

```bash
uv run pytest tests/test_e2e_nested_question.py -m e2e -v
```

Run it **foreground**; never background a pytest run. `-n 2` is faster than `-n 8` here — the bottleneck is TRUNCATE teardown, not CPU.

- [ ] **Step 2: Screenshot each container, light and dark**

A question inside each of the five containers. **Judge dark on its own**, not as "light but inverted". For dark mode set `user.theme`, not the cookie.

- [ ] **Step 3: If any CSS proves necessary, A/B it**

Measuring with the rule present proves nothing about whether the rule does anything — capture with and without.

- [ ] **Step 4: Branch gate — the full suite, once**

```bash
uv run pytest -q
uv run pytest -m e2e -q
uv run ruff check --no-cache . && uv run ruff format --check .
```

Note `scripts/e2e_chunks.sh` is stale — it covers 84 of 97 e2e files, so "I ran the full suite" through it is off by ~20%. Run the marker directly.

- [ ] **Step 5: Commit**

```bash
git commit -m "test(nesting): e2e a nested choice question in a closed spoiler and an inactive tab

Task 10. Plus light+dark verification across all five containers.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** — every section maps to a task: §3 render seam → T1; §4.1 spoiler → T2; §5 preview → T8; §6.1–6.2 widening + menu → T4; §6.3 authorities 1–3 → T5, authority 4 → T6, authority 5 → T7; §6.4 pre-flight → T9; §6.5 FORMAT_VERSION → T6; §7 error handling → T1/T5/T7; §8 accepted costs → comments in T1/T8; §9.1–9.4 → T1/T2/T3; §9.5 gates → T4/T5/T6/T7; §9.6 expected-RED → T4/T6; §9.7 preview → T8; §9.8–9.9 → T10; §10 files → all; §11 decisions → carried as code comments.

**Type consistency** — `page` dict keys are identical in T1 (producer), T2 (`feedback_ancestor_pks`), T3 (the key-set assertion) and T8 (`editor_preview`). `ancestor_pks` / `unit_has_nested_question` / `CONTAINER_MODELS` / `NESTABLE_QUESTION_KEYS` are spelled the same at every site.

**Known gap the executor must resolve, not guess:** T5 Step 1's `ContentType.get_for_model` cold-cache SELECTs may trip an existing `assertNumQueries`. The step says to run the check and gives the fallback query shape rather than assuming either outcome.
