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
- **Falsify, don't just run.** Every task names a mutant. Apply it, watch the named test go RED, then **edit the mutant out by hand** — never `git checkout` the file, which destroys the task's real work.
- **`git add` every file the task created or modified**, then commit with the task number in the subject.

### Two repo idioms this plan depends on

**Making a quiz unit.** Use the existing helper — do **not** hand-roll a `ContentNodeFactory` call:

```python
from tests.factories import make_course_with_unit, make_quiz_unit

course, lesson = make_course_with_unit()
quiz = make_quiz_unit(course=course)
```

`make_quiz_unit(course=None, **kw)` (`tests/factories.py:240`) already sets `kind="unit"`, `unit_type="quiz"` and inherits `ContentNodeFactory`'s `parent=None`; it is the established idiom in ~10 files. **`make_course_with_unit(unit_type="quiz")` does NOT work** — it splats `**kw` into **`CourseFactory`** and hard-codes the unit as `unit_type="lesson"`, so it raises, and would give you a lesson even if it didn't.

**Database access.** `courses/tests/test_beforeafter_nesting.py`, `tests/test_twocolumn_registry.py` and `tests/lal_import/*` have **no module-level `pytestmark`** — every test carries its own `@pytest.mark.django_db`. Copying a function into those files without the decorator fails with "Database access not allowed".

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/templatetags/courses_extras.py` | Builds the `page` dict, gates it on `CONTAINER_MODELS`, resolves the six page values from context |
| `courses/models.py` | Five container `render()`s accept and splat `page`; spoiler also gains `eid`; `resolved_children()` cost comment |
| `courses/builder.py` | `CONTAINER_MODELS`, `NESTABLE_QUESTION_KEYS`, `ancestor_pks()`, `unit_has_nested_question()`, the three builder clauses |
| `courses/views.py` | `check_answer` seeds `feedback_ancestor_pks`; prefetch-block cost comment |
| `courses/views_manage.py` | `element_try` action_url, `PASTE_REFUSAL_MESSAGES` entry |
| `courses/transfer/{payloads,schema}.py` | Archive-side quiz refusal, `FORMAT_VERSION` bump |
| `courses/lal_loader/builders.py` | One nested-question-in-quiz guard at the top of `build_element` |
| `templates/courses/elements/spoilerelement.html` | Re-opens on the no-JS re-render |
| `templates/courses/manage/editor/_add_menu.html` | Nested `Questions` group |
| `templates/courses/manage/editor/_preview.html` | `editor_preview=True` |

**New test files** (named here so every task's `git add` is unambiguous):

| File | Owner task |
|---|---|
| `courses/tests/test_ancestor_pks.py` | Task 2 |
| `courses/tests/test_nested_question_add.py` | Task 4 |
| `courses/tests/test_nested_question_gates.py` | Task 5 |
| `courses/tests/test_nested_question_transfer.py` | Task 6 |
| `tests/lal_import/test_loader_question_in_quiz.py` | Task 7 |
| `courses/tests/test_nested_question_preview.py` | Task 8 |
| `tests/test_e2e_nested_question.py` | Task 10 |
| `tests/capture_nested_question_screenshots.py` | Task 10 |

---

### Task 1: The `page` dict render seam

The core fix. Ends with the five container seam tests green and `test_render_seam.py` proving no leaf broke.

**Files:**
- Modify: `courses/builder.py` (add `CONTAINER_MODELS` after `_CONTAINER_REGISTRY`)
- Modify: `courses/templatetags/courses_extras.py:25-109`
- Modify: `courses/models.py` — `SpoilerElement.render:454`, `CalloutElement.render:522`, `BeforeAfterElement.render:591`, `TabsElement.render:1780`, `TwoColumnElement.render:1892`
- Modify: `courses/views.py` (comment only, Step 8)
- Create: `courses/tests/test_nested_question_nojs_feedback.py` (cherry-picked)

**Interfaces:**
- Produces: `builder.CONTAINER_MODELS: frozenset[type]` — the five container model classes.
- Produces: container `render(*, element=None, state=None, slug=None, node_pk=None, page=None)`.
- Produces: the `page` dict keys `feedback_for_pk`, `selected_ids`, `submitted_values`, `mark_result`, `editor_preview`, `feedback_ancestor_pks`. Task 2 supplies the last one's value; Task 8 the fifth's.

- [ ] **Step 1: Bring the pinning tests onto the branch**

```bash
git checkout test/nested-question-nojs-feedback -- courses/tests/test_nested_question_nojs_feedback.py
```

- [ ] **Step 2: Invert the absence assertion and rename the function**

Rename `test_nested_blank_answer_shows_no_feedback` → `test_nested_blank_answer_shows_feedback`, and change its last assertion:

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
Expected: the 5 `test_nested_blank_answer_shows_feedback` cases FAIL. The 6 controls PASS.

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

Add `editor_preview=None` as the last parameter, then insert after the `if obj is None: return ""` guard:

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
    # `None`, NOT `False`: a False default can never satisfy `is None`, which would
    # make this fallback dead code and silently no-op the editor-preview fix.
    #
    # NOT the same thing as `previewing` (views.py:1394), which means "a
    # NON-ENROLLED STUDENT is viewing this quiz" -- the opposite audience. This one
    # routes forms at a MANAGE-GATED endpoint and must never be set for a student.
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

For `CalloutElement.render` and `SpoilerElement.render`:

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

- [ ] **Step 8: Record the two accepted costs as comments (spec §8) — SIX comment sites**

Two *costs*, six *insertion points*: one in `views.py`, plus the same comment repeated at each of the five `models.py` child-queryset methods.

In `courses/views.py::build_lesson_context`, beneath the whole markdone prefetch block (i.e. after `prefetch_related_objects(markdone_els, "items")`) — **not** wedged between the existing "ACCEPTED LIMITATION" note and the `markdone_els` list it describes:

```python
    # SECOND ACCEPTED LIMITATION, same shape: `choice_qs`/`fill_qs` are built from
    # `elements` (parent__isnull=True), so a NESTED choice question re-queries
    # choices.all() per render. Bounded (per-unit question counts are small) and
    # pre-existing for nested fill_blank's `blanks`. Closing it would cost an extra
    # flat query on EVERY lesson render, including the vast majority with no nesting.
```

At **five** sites in `courses/models.py` — Spoiler `resolved_children()` (`:441`), Callout `resolved_children()` (`:509`), BeforeAfter `resolved_slots()` (`:565`), Tabs `resolved_tabs()` (`:1760`), TwoColumn `resolved_columns()` (`:1874`); note spoiler and callout share the *method name* but are separate methods — one comment each:

```python
        # NOTE: no select_related("unit__course") here. QuestionElement.render
        # reverses courses:check_answer from element.unit.course.slug whenever
        # action_url is None -- exactly the nested case -- so each nested question
        # costs up to two extra queries ON THE STUDENT PAGE, not only in the editor
        # preview. Pre-existing for nested fill_blank; accepted rather than fixed,
        # because widening this select_related touches five methods on the student
        # path and should be measured first.
```

- [ ] **Step 9: Run the seam tests and the render-seam gate — expect PASS**

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py courses/tests/test_render_seam.py -v
```
Expected: all PASS. `test_render_seam.py` is 13 concretes × 6 placements and is the test that catches an unconditional `page=`.

- [ ] **Step 10: Falsify — the container gate**

Delete the `if type(obj) in CONTAINER_MODELS:` line from Step 6 and dedent, so `page=` goes to everything. Run:

```bash
uv run pytest courses/tests/test_render_seam.py -v
```
Expected: FAIL with `TypeError: render() got an unexpected keyword argument 'page'`. **Edit the condition back in by hand.**

- [ ] **Step 11: Falsify — per-container isolation**

Delete `**(page or {}),` from `TabsElement.render` only. Run the seam tests. Expected: exactly the `tabs` case FAILs; the other four stay green. Edit it back in.

(Blast radius is deliberately uneven — tabs, two_column and before_after give one-test isolation; callout and spoiler carry more once Task 3 lands.)

- [ ] **Step 12: Lint and commit**

```bash
uv run ruff check --no-cache courses/ && uv run ruff format --check courses/
git add courses/builder.py courses/templatetags/courses_extras.py courses/models.py courses/views.py courses/tests/test_nested_question_nojs_feedback.py
git commit -m "fix(nesting): forward page-level question values across the container barrier

Task 1. render_element builds one \`page\` dict and passes it ONLY to the five
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
- Modify: `courses/views.py` — `check_answer`'s no-JS `ctx.update(...)`
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
        # `reads` is PER NODE. The correct walk performs six .parent reads on a
        # cycle in total (one initializer + five iterations, since `hops <= 4`
        # admits 0,1,2,3,4), and a two-node cycle splits those 3/3 -- so any one
        # instance sees at most 3. The tripwire at MAX_NEST_DEPTH * 3 == 12 leaves
        # a 4x margin, which a correct implementation can never reach.
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

Directly after `element_depth`:

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

After the `**(page or {})` splat:

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

Add a `{% comment %}` above recording: the no-JS path is a full page re-render, so without this the verdict renders inside a closed disclosure; and the `feedback_ancestor_pks and` guard is required because on a direct `render()` with no `page` the key is absent from context entirely — a bare membership test would work only because Django's `smartif` swallows the `TypeError`.

- [ ] **Step 8: Assert `open` in the spoiler seam test**

In the parametrized blank-answer test:

```python
    if child_class == "spoiler__child":
        # The no-JS path re-renders the whole page; a closed <details> would hide
        # the verdict we just asserted is present.
        assert '<details class="spoiler" open>' in body
```

- [ ] **Step 9: Run and verify**

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py courses/tests/test_ancestor_pks.py -v
```
Expected: all PASS.

- [ ] **Step 10: Falsify — both halves**

(a) Delete ` open` from the template's `{% if %}` → the spoiler case FAILs, the plain `VERDICT in body` half stays green. Restore.
(b) Remove `feedback_ancestor_pks=ancestor_pks(element)` from `check_answer` → the same assertion FAILs. Restore.

An implementer who plumbs the template but forgets the view must have something to catch it.

- [ ] **Step 11: Lint and commit**

```bash
uv run ruff check --no-cache courses/ && uv run ruff format --check courses/
git add courses/builder.py courses/views.py courses/models.py templates/courses/elements/spoilerelement.html courses/tests/test_ancestor_pks.py courses/tests/test_nested_question_nojs_feedback.py
git commit -m "fix(nesting): re-open a spoiler holding the checked question on the no-JS re-render

Task 2. The no-JS path re-renders the whole page and <details> has no \`open\`, so
the verdict landed inside a closed disclosure -- the fix was invisible in the one
container the capability was built for.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The type axis, depth-2, and the seven claim tests

Needs no production change — nested rows are created directly, bypassing `resolve_scope`, so this runs before the widening.

**Files:**
- Modify: `courses/tests/test_nested_question_nojs_feedback.py`

- [ ] **Step 1: Extend the `scene` fixture to place a non-fill-blank child**

The cherry-picked fixture's `build(make_container)` hard-codes `_fill_blank()`. Give it an optional factory, defaulting to `_fill_blank` so the five existing container cases are untouched:

```python
    def build(make_container, make_question=_fill_blank):
        concrete, slot_id = make_container()
        container_row = add_element(unit, concrete)
        nested_row = Element.objects.create(
            unit=unit,
            content_object=make_question(),
            parent=container_row,
            tab_id=slot_id,
        )
        return nested_row
```

Add the slice helper in the same step:

```python
def _child_slice(body, wrapper_class, index=0):
    """The markup inside ONE container child wrapper, tag-depth matched.

    `index` selects WHICH wrapper: 0 (the default, and the plan's original
    behaviour) for every seam test, 1 for the invariant-B claim test, which needs
    the UNCHECKED sibling inside the same container.

    The three widened types render byte-identical markup
    (`<div class="el el--question" data-question>`) -- only fill_blank has a type
    class -- so the nested render is identified by POSITION, not by class.

    A naive `body.index("</div>", start)` is WRONG and silently guts every
    assertion built on it: each question template opens
    `<div class="el el--question" data-question>` and then
    `<div class="question__stem">`, so the first closing tag belongs to the STEM.
    The slice would end mid-question, containing no <form>, no inputs and no
    verdict -- and every `... in slice_` assertion would fail against a CORRECT
    implementation.
    """
    open_tag = f'<div class="{wrapper_class}">'
    start = body.index(open_tag)
    i, depth = start + len(open_tag), 1
    while depth:
        nxt_open = body.find("<div", i)
        nxt_close = body.index("</div>", i)
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            i = nxt_open + len("<div")
        else:
            depth -= 1
            i = nxt_close + len("</div>")
    return body[start:i]
```

- [ ] **Step 2: Add the type-axis fixtures with their per-type discriminators**

**First add the imports** — the cherry-picked file imports only
`BeforeAfterElement, Blank, CalloutElement, Element, Enrollment,
FillBlankQuestionElement, SpoilerElement, TabsElement, TwoColumnElement`, so all
four models below are unbound and the block would `NameError` on first run. Ruff's
isort is `force-single-line`, so one per line:

```python
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
```

```python
def _choice(feedback=""):
    """`feedback` defaults to "" so this stays a zero-arg callable for TYPES.

    The invariant-B claim test MUST pass a real string. choice_marks' lesson
    branch marks only options in mark_result.annotated, and mark() annotates only
    options that HAVE feedback -- so with feedback="" that test would assert zero
    markers on the sibling AND zero on the checked question, i.e. vacuously.
    """
    q = ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False)
    right = Choice.objects.create(
        question=q, text="right", is_correct=True, feedback=feedback
    )
    Choice.objects.create(
        question=q, text="wrong", is_correct=False, feedback=feedback
    )
    q._correct_pk = right.pk  # read by the type-axis discriminator below
    return q


def _short_text():
    return ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")


def _short_numeric():
    return ShortNumericQuestionElement.objects.create(
        stem="2+2?", value="4", tolerance="0"
    )


# (factory, blank POST, present-substrings, absent-substrings).
#
# The blank POST must be EXACT or answer_is_empty never fires and the test proves
# nothing:  choice -> post.getlist("choice"), so NO "choice" key at all;
# short_text/short_numeric -> post.get("answer", ""), so {"answer": ""}.
#
# The discriminators prove the right WIDGET rendered -- without them the three
# parametrized cases are indistinguishable from one another.
TYPES = [
    # `name="choice"` ALONE is satisfied by any choice question on the page, so the
    # correct option's pk is what makes the assertion non-vacuous once the slice is
    # right. `_choice()` must therefore expose it -- have it stash the correct
    # Choice pk on the returned question (e.g. `q._correct_pk = c.pk`) and build the
    # `present` list per-test rather than at module import.
    pytest.param(_choice, {}, ['name="choice"', "VALUE_PK"], [], id="choice"),
    pytest.param(
        _short_text, {"answer": ""}, ['name="answer"'], ["inputmode"], id="short_text"
    ),
    pytest.param(
        _short_numeric,
        {"answer": ""},
        ['name="answer"', 'inputmode="text"'],
        [],
        id="short_numeric",
    ),
]
```

(`shortnumericquestionelement.html:8` renders `inputmode="text"`; `shorttextquestionelement.html:8` renders no `inputmode` at all — hence one present-assertion and one absent-assertion.)

- [ ] **Step 3: Add seam tests 6–8 (type axis, in a callout)**

```python
@pytest.mark.parametrize(("make_question", "blank_post", "present", "absent"), TYPES)
def test_nested_blank_answer_shows_feedback_by_type(
    scene, client, make_question, blank_post, present, absent
):
    """Three NEW types, not four: fill_blank x callout is already the container axis."""
    _student, unit, _top, build = scene
    nested_row = build(_callout, make_question)

    resp = client.post(_check_url(unit, nested_row.pk), blank_post)
    assert resp.status_code == 200
    body = resp.content.decode()
    slice_ = _child_slice(body, "callout__child")
    # The FULL reversed URL, not a bare pk substring: the action carries BOTH
    # node_pk and element_pk, and Element/ContentNode draw from independent
    # Postgres sequences, so `nested_row.pk == unit.pk` is reachable and a bare
    # f"/{pk}/" would match the node segment. (Same trap test_render_seam.py:88
    # documents.)
    assert _check_url(unit, nested_row.pk) in slice_
    for needle in present:
        # "VALUE_PK" is the placeholder for the choice case's correct-option pk,
        # which is only known after the question is built.
        if needle == "VALUE_PK":
            needle = f'value="{nested_row.content_object._correct_pk}"'
        assert needle in slice_
    for needle in absent:
        assert needle not in slice_
    assert VERDICT in slice_
```

- [ ] **Step 4: Add seam tests 9 and 10**

The depth-2 case needs **three hand-built rows** — `build()` creates only one
container and one child, so it cannot express nesting-inside-nesting:

```python
def test_nested_blank_answer_shows_feedback_at_depth_2(scene, client):
    """A question in a callout in a spoiler. Pins that the recursion RE-EMITS
    rather than forwarding one level, AND that ancestry (not direct childhood)
    drives the spoiler's `open` -- seam test 2 nests directly in the spoiler, so a
    direct-parent implementation (`ancestors = {element.parent_id}`) would satisfy
    it and leave the rule unpinned. Spec section 9.3 names this test as that
    mutant's sole RED."""
    _student, unit, _top, _build = scene
    spoiler_row = add_element(unit, SpoilerElement.objects.create(label="s"))
    callout_row = Element.objects.create(
        unit=unit,
        content_object=CalloutElement.objects.create(kind="example"),
        parent=spoiler_row,
        tab_id=SpoilerElement.SLOT_ID,
    )
    nested_row = Element.objects.create(
        unit=unit,
        content_object=_fill_blank(),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    body = client.post(
        _check_url(unit, nested_row.pk), {"blank": [""]}
    ).content.decode()
    assert VERDICT in body
    assert '<details class="spoiler" open>' in body


def test_only_the_checked_question_shows_a_verdict(scene, client):
    """Invariant A. Without this, every flipped assertion would pass just as well
    if the fix leaked a verdict onto EVERY question on the page.

    Create the CHECKED question FIRST (lowest order/pk) inside the callout:
    _child_slice slices the FIRST `callout__child`, so checking the second child
    would fail this assertion against a correct implementation.
    """
    ...
    assert body.count(VERDICT) == 1
    assert VERDICT in _child_slice(body, "callout__child")
```

- [ ] **Step 5: Add the seven claim tests (spec §9.4)**

All in the same file:

1. **Invariant B** — two nested `choice` questions **in the same container**, one checked: the sibling renders **zero** `question__choice-marker` and `question__choice-feedback`, **and the checked child renders at least one of each**. Both halves are required: without the positive half the test passes vacuously, since `mark()` annotates only options that carry feedback. Build both questions with `_choice(feedback="...")`, and reach the sibling with `_child_slice(body, "callout__child", index=1)`. Seam test 10 cannot catch this — the marker path emits no verdict block to count.
2. **Quiz page still renders** — a quiz built with `make_quiz_unit(course=course)` (see Global Constraints) containing a container with a nested **choice** child returns 200, with no `question__verdict` and no `question__choice-marker`. Build it with a direct `Element.objects.create` — §6 forbids authoring it, and the point is that legacy content must not 500. Plus `"selected_ids" not in build_quiz_context(...)`, which needs `from courses.views import build_quiz_context`.
3. **Restore and live routes agree** — POST a whitespace-bearing answer (live route), then GET the lesson page (`feedback_for_pk` is `None`, so restore runs); assert the verdict text and refilled value match. **Compare extracted values, not whole slices**: every form carries a freshly masked `{% csrf_token %}`, so two renders of the same form are never byte-identical. Add `_form_slice(body, action_url)` — keyed on the **full reversed URL**, per §9.2's bare-pk trap — plus small regex extractors for the refilled input value and the verdict block. Claim 4 uses the same helpers.
4. **`None` and `""` refill identically** — a blank nested short-text answer and a blank top-level one produce the same empty input, pinning the `default_if_none:''` the `or None` coercion rests on.
5. **Shadowing is impossible**, `@pytest.mark.parametrize` over **all five container models**. An `el`-only hijack is NOT enough: `tabselement.html` never reads `el` at all and `twocolumnelement.html` reads it only through `columns`, so for two of the five cases it is a no-op. Poison **every container-owned key at once** — `el`, `children`, `tabs`, `columns`, `slots`, `eid`, `element_state`, `slug`, `node_pk`, `display`, `label_pos` — then assert both `"HIJACKED" not in html` **and** a per-container positive marker proving the real value won. Including `display`/`label_pos` is what exercises `TabsElement`'s second splat, the site §3.2 flags as the one an implementer copying the single-splat snippet gets wrong.
6. **Spoiler `eid` sentinel** — `SpoilerElement.render(element=None)` returns without raising. Nothing in `test_render_seam.py` covers this: its CONCRETES loop passes a real join row, and its only `element=None` case uses `FillGateElement`.
7. **`mode` is not forwarded**:

```python
def test_mode_is_not_forwarded_to_a_nested_child(monkeypatch, scene, client):
    captured = {}

    def capture(self, *, element=None, state=None, slug=None, node_pk=None, page=None):
        captured.update(page or {})
        return ""  # render_element mark_safe()s the result

    monkeypatch.setattr(CalloutElement, "render", capture)
    ...
    # The FULL key set, not just the absence: `"mode" not in captured` is green
    # when `page` never arrived at all.
    assert captured.keys() == {
        "feedback_for_pk", "selected_ids", "submitted_values",
        "mark_result", "editor_preview", "feedback_ancestor_pks",
    }
```

- [ ] **Step 6: Run the whole file**

```bash
uv run pytest courses/tests/test_nested_question_nojs_feedback.py -v
```
Expected: all PASS.

- [ ] **Step 7: Falsify — two mutants**

(a) Add `"mode": mode` to the `page` dict → the `mode` claim test FAILs. Remove it.
(b) Move `**(page or {})` from first to last in `CalloutElement.render` → the shadowing test FAILs for callout. Restore.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check --no-cache courses/tests/ && uv run ruff format --check courses/tests/
git add courses/tests/test_nested_question_nojs_feedback.py
git commit -m "test(nesting): pin the type axis, depth-2 recursion and the seven design claims

Task 3. Guards are POSITIONAL: choice/short_text/short_numeric render
byte-identical wrapper markup, so only fill_blank has a type class to assert on.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Widen the allowlist, aliases, add menu, and the drift test

**Files:**
- Modify: `courses/builder.py:85-132`
- Modify: `templates/courses/manage/editor/_add_menu.html`
- Modify: `courses/tests/test_beforeafter_nesting.py`, `courses/tests/test_spoiler_nesting.py`, `courses/tests/test_nesting_rule.py`, `tests/test_twocolumn_registry.py`, `tests/test_tabs_registry.py`
- Create: `courses/tests/test_nested_question_add.py`

- [ ] **Step 1: Widen the constants**

```python
NESTABLE_TYPE_KEYS = frozenset({..., "choice", "short_text", "short_numeric", ...})

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

**Three** aliases (`fillblankquestion` already exists):

```python
    "choicequestion": "choice",
    "shorttextquestion": "short_text",
    "shortnumericquestion": "short_numeric",
```

**The choice alias is `choicequestion`, never the card names.** `element_add` (`views_manage.py:2128-2134`) reads `choice-single`/`choice-multi` to set `multiple`, then sets `type_key="choicequestion"` before calling `resolve_scope` — so the card names never reach this map. Also update the prose comment at `:85-88` listing which types' form key differs from their transfer key.

- [ ] **Step 2: Add the nested `Questions` group**

A **sibling** of the `{% if not nested %}` block, never inside it — a `{% if nested %}` group nested in `{% if not nested %}` is unreachable and the failure is silent. Move the `{% if nested %}`-gated fill-blank card (line 54) out of `Interactive`; leave the top-level card at line 64 alone.

The five cards, with their exact `data-add-type` and icon ids (the icon id is **not** derivable from `data-add-type` — copy from the top-level `Questions` group, lines 59-69):

| `data-add-type` | `use href` | Label |
|---|---|---|
| `choice-single` | `#el-choice-single` | Single choice |
| `choice-multi` | `#el-choice-multi` | Multiple choice |
| `shorttextquestion` | `#el-shorttext` | Short text |
| `shortnumericquestion` | `#el-shortnumeric` | Short numeric |
| `fillblankquestion` | `#el-fillblank` | Fill in the blanks |

```html
    {% if nested and not unit_is_quiz %}
    {% comment %}
    Questions nested in a container -- LESSON UNITS ONLY. The server enforces this
    at five authorities regardless; hiding the group is courtesy.

    NO depth gate, unlike the container cards: questions are LEAVES, so from a menu
    at depth d they land at d+1, which resolve_scope clause 3 accepts up to
    MAX_NEST_DEPTH. Containers need `depth < max_nest_depth|add:-1` only because a
    container child must itself still have room for children.

    data-add-type carries the CARD names -- element_add reads choice-single /
    choice-multi to set `multiple`, THEN collapses both to "choicequestion" for the
    nesting check. Emitting "choicequestion" here would NOT error (it is in the
    allow-tuple) -- both cards would 200 and silently produce single-choice.
    {% endcomment %}
    <p class="typemenu__group-label">{% trans "Questions" %}</p>
    <div class="typemenu__group">
      ...five buttons per the table above...
    </div>
    {% endif %}
```

- [ ] **Step 3: Re-run the spec's three sweeps BEFORE trusting the table**

Spec §9.6 records that its enumeration came from three orthogonal greps and says the
plan should re-run them rather than trust the list. Do that — it is what surfaces the
files a single-angle grep misses:

```bash
grep -rn "choicequestion\|choice-single\|shorttextquestion\|shortnumericquestion" tests/ courses/tests/
grep -rn "NESTABLE_TYPE_KEYS" tests/ courses/tests/
grep -rn "FORMAT_VERSION == 11\|format_version\"\] == 11" tests/ courses/tests/
```

Reconcile every hit against the table below. **An un-listed hit is a defect in this
table, not a surprise** — add it before proceeding.

- [ ] **Step 4: Run the affected files and watch the expected REDs**

```bash
uv run pytest courses/tests/test_beforeafter_nesting.py courses/tests/test_spoiler_nesting.py tests/test_twocolumn_registry.py tests/test_tabs_registry.py tests/test_tabs_editor_partial.py tests/test_tabs_transfer.py -v
```
Expected FAILs — **all expected, none a regression**:

| Site | Why |
|---|---|
| `test_beforeafter_nesting.py:52` | `resolve_scope(…, "choice")` no longer raises. Its docstring names this change as its mutant. |
| `tests/test_twocolumn_registry.py:53` | Same, with the *form* key `"choicequestion"`. |
| `courses/tests/test_spoiler_nesting.py:157` | Same, key hidden in a `for bad in (…)` **loop variable**. |
| `tests/test_tabs_registry.py:74` | `test_nested_add_of_a_blocked_type_is_400`, **the `choicequestion` param only** |
| `test_spoiler_nesting.py:351-363, :389, :444-448` | Add-menu absence assertions |
| `tests/test_tabs_editor_partial.py:89-114` | `test_nested_add_menu_offers_only_nestable_types` renders `_add_menu.html` directly with `nested=True` and **no `unit_is_quiz`** (falsy ⇒ the new group renders), then asserts `"choice-single" not in html`. Bare substring, so it matches the card **and** its `#el-choice-single` icon href. |
| `tests/test_tabs_transfer.py:142` | `test_nesting_validation_rejects[elements2]` — `_child(type_="choice")` inside `pytest.raises(TransferError)`. It passes **no `unit_types`**, so the quiz clause is irrelevant: this breaks the moment `choice` joins `NESTABLE_TYPE_KEYS`, i.e. **here in Task 4**, not in Task 6. |

- [ ] **Step 5: Rewrite each refusal as a LESSON-ACCEPTANCE test**

⚠️ **Only the acceptance half lands here.** The quiz-refusal half depends on
`resolve_scope`'s quiz clause, which **Task 5 Step 3 adds** — `resolve_scope` today
reads `unit` only for `_parse_scope_ref` and inspects `unit.unit_type` nowhere. A
quiz-refusal assertion written now would be RED at this task's commit. Task 5 Step 6
adds each companion alongside the clause that makes it pass.

Note the `@pytest.mark.django_db` — these files have no module-level `pytestmark`.

```python
@pytest.mark.django_db
def test_a_graded_question_is_accepted_as_a_child_of_a_LESSON_before_after():
    """Was `test_a_graded_question_is_still_refused_as_a_child`, whose docstring
    named this very change as its mutant. The refusal is now conditional on
    unit.unit_type; its quiz companion lands in Task 5 Step 6."""
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    parent, tab = builder.resolve_scope(
        unit, str(join.pk), BeforeAfterElement.BEFORE_SLOT_ID, "choice"
    )
    assert parent == join
```

The same shape for `tests/test_twocolumn_registry.py:53` (form key `"choicequestion"`)
and `courses/tests/test_spoiler_nesting.py:157` (the `for bad in (…)` loop — drop
`choicequestion` from that tuple and add a positive assertion).

For **`tests/test_tabs_registry.py:71-86`**: split the parametrization so `slidebreak`
keeps its unconditional 400 (it is rejected at the allow-tuple and never reaches
`resolve_scope`), and add a **lesson-200** test for `choicequestion`. Its quiz-400
companion also belongs to Task 5 Step 6.

```python
@pytest.mark.parametrize("post", [{"type": "slidebreak"}])   # still always blocked
def test_nested_add_of_a_blocked_type_is_400(client, post):
    ...unchanged...


def test_nested_add_of_a_question_is_200_in_a_lesson(client):
    ...choicequestion into a tab on the LESSON unit: 200...
    # The quiz-400 companion lands in Task 5 Step 6.
```

For the add-menu assertions: drag/grid/extended keys stay banned nested; the four widened keys become expected-**present** in a lesson and expected-**absent** in a quiz.

For **`tests/test_tabs_editor_partial.py:89-114`**: `slidebreak` stays banned;
`choice-single` becomes expected-**present** in the existing lesson-style render, and
add a second render with `"unit_is_quiz": True` in the context asserting it is
absent. Keep the docstring's note that `depth`/`max_nest_depth` must be **integers**
(a string binds and `smartif` swallows the `str < int` TypeError, silently reading
every guard as False).

For **`tests/test_tabs_transfer.py:142`**, the rewrite happens **here**, since that
is where the break happens: swap the subject to `type_="extended_response"` (still
non-nestable) and add a positive case asserting `choice` is now accepted nested.
Task 6 then only has to bump that file's `FORMAT_VERSION` literal.

Also fix `test_spoiler_nesting.py:179-180`, which **stays green but becomes a lie** — `assert "choicequestion" not in NESTABLE_TYPE_KEYS` under the comment `# genuinely non-nestable`. Drop `choicequestion` from that tuple, or reword to "form keys never appear in the transfer-key set".

- [ ] **Step 6: Add the add-menu placement tests**

In `test_spoiler_nesting.py`: nested + lesson shows the five cards; nested + quiz shows none; top level unchanged. **Assert the five `data-add-type` strings, not a card count** — a count is blind to the `choicequestion` mix-up. (`tests/test_manage_editor_menu.py` pins 24 for its **quiz** fixture; a top-level lesson menu is 33.)

- [ ] **Step 7: Extend the drift test (spec §9.5)**

In `courses/tests/test_nesting_rule.py`:

```python
def test_nestable_question_keys_are_a_subset_of_nestable_type_keys():
    assert builder.NESTABLE_QUESTION_KEYS <= builder.NESTABLE_TYPE_KEYS


def test_every_nestable_question_key_is_a_serializer_key():
    from courses.transfer.export import SERIALIZERS

    assert builder.NESTABLE_QUESTION_KEYS <= set(SERIALIZERS)


def test_every_new_form_key_alias_resolves_into_nestable_type_keys():
    aliases = builder._NESTABLE_FORM_KEY_ALIASES
    for form_key in ("choicequestion", "shorttextquestion", "shortnumericquestion"):
        assert aliases[form_key] in builder.NESTABLE_TYPE_KEYS


def test_container_models_is_derived_from_the_registry():
    """The only incremental fact worth pinning: CONTAINER_MODELS is DERIVED, not a
    hand-written second list. test_container_keys_agree_by_key_not_by_count already
    covers the registry-vs-transfer-keys agreement."""
    assert builder.CONTAINER_MODELS == frozenset(builder._CONTAINER_REGISTRY)
```

- [ ] **Step 8: Add the `element_add` endpoint tests**

Create `courses/tests/test_nested_question_add.py`.

**`element_add` creates no `Element` row.** It validates the type, resolves the scope, and returns `_render_open_form(...)` — an empty editor form fragment (`views_manage.py:2186-2199`); the row is created later by `element_save`. So assert on the **returned fragment**, exactly as `tests/test_tabs_registry.py:55-69` does. Copy that file's `_managed(client)` helper into the new file (it is local to `test_tabs_registry.py`, not importable).

```python
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("add_type", "expect_multiple_checked"),
    [
        ("choice-single", False),
        ("choice-multi", True),
        ("shorttextquestion", None),
        ("shortnumericquestion", None),
    ],
)
def test_nested_add_of_a_widened_question_type_opens_its_form(
    client, add_type, expect_multiple_checked
):
    """These catch a wrong alias at the endpoint, where it actually bites.

    Note the drift test catches a REPLACED key too (it indexes the map by
    expected form key, so a missing "choicequestion" is a KeyError). What only
    these tests catch is an alias ADDED ALONGSIDE the correct one: `choice-single
    -> choice` is well-formed, satisfies the drift assertion, and is simply never
    consulted by resolve_scope.
    """
    course, unit = _managed(client)                       # a LESSON unit
    callout = CalloutElement.objects.create(kind="example")
    join = Element.objects.create(unit=unit, content_object=callout)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "type": add_type,
            "unit": unit.pk,
            "parent": join.pk,
            "tab": CalloutElement.SLOT_ID,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert f'name="parent" value="{join.pk}"' in html
    assert f'name="tab" value="{CalloutElement.SLOT_ID}"' in html
    if expect_multiple_checked is not None:
        # The ONLY thing distinguishing the two choice cards at this endpoint:
        # element_add passes initial={"multiple": ...} into the opened form.
        #
        # `multiple` is a HiddenInput (element_forms.py:671), rendered by
        # _edit_choicequestion.html:3 as {{ form.multiple }} -- so the markup is
        # <input type="hidden" name="multiple" value="True"> and there is NO
        # `checked` attribute anywhere. Render once and copy the exact substring
        # before pinning it; Django emits type/name/value contiguously.
        assert f'name="multiple" value="{expect_multiple_checked}"' in html
```

**The quiz-400 companion is NOT written here.** `element_add` 400s on nesting only when `resolve_scope` raises, and after this task `choicequestion → choice` is nestable, the callout is a registered container and depth is 2 — so the same POST against a quiz unit returns **200** until Task 5 Step 3 lands. It is Task 5 Step 6's.

- [ ] **Step 9: Run, falsify, lint, commit**

```bash
uv run pytest courses/tests/test_beforeafter_nesting.py courses/tests/test_spoiler_nesting.py courses/tests/test_nesting_rule.py courses/tests/test_nested_question_add.py tests/test_twocolumn_registry.py tests/test_tabs_registry.py tests/test_tabs_editor_partial.py tests/test_tabs_transfer.py tests/test_manage_editor_menu.py -v
```

Falsify: change the alias to `"choice-single": "choice"` → the **two choice** endpoint tests FAIL and the short-text/short-numeric ones stay **green** (they resolve through untouched aliases). Do not chase the greens. Restore.

```bash
uv run ruff check --no-cache courses/ tests/ && uv run ruff format --check courses/ tests/
git add courses/builder.py templates/courses/manage/editor/_add_menu.html courses/tests/test_beforeafter_nesting.py courses/tests/test_spoiler_nesting.py courses/tests/test_nesting_rule.py courses/tests/test_nested_question_add.py tests/test_twocolumn_registry.py tests/test_tabs_registry.py tests/test_tabs_editor_partial.py tests/test_tabs_transfer.py
git commit -m "feat(nesting): allow choice/short_text/short_numeric inside lesson containers

Task 4. Three transfer keys, three form-key aliases (choicequestion, not the
choice-single/choice-multi card names -- element_add collapses those before
resolve_scope sees them), a nested Questions group, and the drift assertions.

The lesson-only ENFORCEMENT lands in Task 5: until then the add menu hides the
cards in a quiz but the server does not yet refuse a crafted POST. Intermediate
branch state only -- Task 5 is the next commit and nothing ships between them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The lesson-only gates in `builder` and the paste endpoint

**Files:**
- Modify: `courses/builder.py` — `unit_has_nested_question`, `resolve_scope`, `paste_allowed`, `rename_node`
- Modify: `courses/views_manage.py:1558-1567` — `PASTE_REFUSAL_MESSAGES`
- Create: `courses/tests/test_nested_question_gates.py`
- Modify (the quiz-refusal companions Task 4 deferred): `courses/tests/test_beforeafter_nesting.py`, `courses/tests/test_spoiler_nesting.py`, `courses/tests/test_nested_question_add.py`, `tests/test_twocolumn_registry.py`, `tests/test_tabs_registry.py`

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

- [ ] **Step 2: Check the query-count exposure (concrete, not open-ended)**

`get_for_model` issues extra SELECTs on a cold cache, and `build_lesson_context` documents rejecting that exact pattern because it broke a query-count assertion. But `unit_has_nested_question` is called **only** from `rename_node`, which `tests/test_html_element.py` does not exercise — so run the grep, not a test that cannot fail for the stated reason:

```bash
grep -rn "assertNumQueries\|django_assert_num_queries" tests/ courses/tests/
```

Run any hit that touches `rename_node` / `manage_node_rename`. **Expected today: no such test exists**, so the `app_label` + `model__in=[...]` fallback (the shape `has_stateful_elements` uses) is optional. If a hit does appear, switch to that shape.

- [ ] **Step 3: `resolve_scope` clause**

Immediately after clause 1 (the `NESTABLE_TYPE_KEYS` check at `:284-285`):

```python
    if (
        child_key in NESTABLE_QUESTION_KEYS
        and unit.unit_type == ContentNode.UnitType.QUIZ
    ):
        raise NestingError("questions may not be nested in a quiz")
```

(Pre-wrapped: the single-line form is 91 columns and `ruff check` runs at the
default 88 with `E` selected, so pasting it verbatim fails this task's own lint gate.)

Left untranslated, matching every other `NestingError` in this file (`:248, :282, :286, :298, :302, :306`) — `element_add` discards the message and returns `HttpResponseBadRequest("bad nesting")`, so a msgid here would be dead.

- [ ] **Step 4: `paste_allowed` clause + message**

Immediately after the `type_not_nestable` clause (`:441-444`), **inside the `dest_parent is not None` branch** — pasting a question to top level in a quiz must stay legal:

```python
        if (
            model_to_key(type(marked_join.content_object)) in NESTABLE_QUESTION_KEYS
            and unit.unit_type == ContentNode.UnitType.QUIZ
        ):
            return False, "question_in_quiz"
```

Update the docstring's reason precedence to `…, type_not_nestable, question_in_quiz, too_deep, own_slot`, and put a short comment **at the new clause** recording its inherited narrowness (spec §6.3 requires this documented rather than closed): it checks the pasted subtree's **root only**, so pasting a *container* that already holds a question is not re-checked — sound because authority 3 stops a unit becoming a quiz while such content exists, and clause 0 (`wrong_unit`) makes cross-unit pastes impossible. Then in `views_manage.PASTE_REFUSAL_MESSAGES`:

```python
    "question_in_quiz": gettext_lazy(
        "Questions can only be placed inside a container in a lesson unit."
    ),
```

- [ ] **Step 5: `rename_node` flip guard**

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
                    gettext_lazy(
                        "This unit has a question inside a container. Move it out "
                        "of the container before turning the unit into a quiz."
                    )
                )
            node.unit_type = unit_type
            fields.append("unit_type")
```

**Translated, unlike the `NestingError` above** — this message is surfaced to the author verbatim, so it is a real msgid. Import `gettext_lazy` if the module does not already.

Quiz→lesson stays unconditionally allowed; a quiz→quiz no-op is accepted.

- [ ] **Step 6: Write the gate tests**

Create `courses/tests/test_nested_question_gates.py`:

**First, the five quiz-refusal companions Task 4 deferred** — each pairs with the lesson-acceptance test written there, and each is RED until this task's Step 3 clause lands:

- `courses/tests/test_beforeafter_nesting.py` — `resolve_scope(quiz, …, "choice")` raises `NestingError`.
- `tests/test_twocolumn_registry.py` — same with the form key `"choicequestion"`.
- `courses/tests/test_spoiler_nesting.py` — same, in the loop that previously banned it.
- `tests/test_tabs_registry.py` — `element_add` with `choicequestion` into a tab on a **quiz** unit returns 400.
- `courses/tests/test_nested_question_add.py` — the same POST against a quiz unit returns 400.

Then, in `courses/tests/test_nested_question_gates.py`:

- `resolve_scope` raises for a question into a quiz container; accepts into a lesson container.
- `paste_allowed` returns `question_in_quiz`; still permits a **top-level** paste into a quiz; and — asserted **on the paste endpoint**, not the function — surfaces its own message, not the generic fallback.
- **The `too_deep` precedence case needs a depth-4 destination, built through the ORM.** A question is a leaf, so `subtree_facts` gives `min_headroom = MAX_NEST_DEPTH = 4` and `too_deep` fires only when `dest_depth > 4` — i.e. the destination container must itself sit at depth **4**, which `resolve_scope` clause 4 makes unreachable through any authoring path. Build the chain with direct `Element.objects.create` calls, modelling `courses/tests/test_nesting_rule.py::_mk`. Assert **both directions**: with the quiz unit_type it returns `question_in_quiz`; with the same fixture on a **lesson** unit it returns `too_deep`. Without the second half the test stays green even if the clause were placed *after* `too_deep`.
- The `ast` completeness assertion (a source regex would sweep the docstring, which lists the reason names in prose; a hand-maintained constant just moves the drift):

```python
import ast
from pathlib import Path

from courses import builder
from courses.views_manage import PASTE_REFUSAL_MESSAGES


def test_every_paste_reason_has_a_message():
    tree = ast.parse(Path(builder.__file__).read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "paste_allowed"
    )
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

- `rename_node`: flip refused, `unit_type` unchanged, quiz→quiz no-op accepted, quiz→lesson allowed, **plus the wide-predicate case** — a nested `extended_response` created with a direct `Element.objects.create` must still block the flip.

  **Copy the call shape from `tests/test_manage_builder.py:96`**, the repo's only existing `builder.rename_node(...)` call site. Two traps: `token` must be a `parse_datetime`-able string matching `node.updated` **exactly** or `_check_token` (`builder.py:524-527`) raises `ConflictError` before the new guard ever runs; and `title` must be non-blank or `full_clean()` rejects it.

- [ ] **Step 7: Run and falsify — three mutants**

```bash
uv run pytest courses/tests/test_nested_question_gates.py courses/tests/test_beforeafter_nesting.py courses/tests/test_spoiler_nesting.py courses/tests/test_nested_question_add.py tests/test_twocolumn_registry.py tests/test_tabs_registry.py -v
```

| Mutant | Expected RED |
|---|---|
| Make `resolve_scope`'s new clause never fire (e.g. guard it with `if False and …`) | the `resolve_scope` quiz cases, plus their endpoint/registry companions — every lesson-acceptance, paste and rename case stays green. **Do NOT "drop the `unit_type` conjunct"**: that makes the clause fire for *lessons too*, reddening the acceptance tests instead, which is a different mutant with the opposite signature |
| Drop the `dest_parent is not None` scoping on `paste_allowed`'s clause (hoist it above the branch) | the top-level-paste-into-quiz case |
| Narrow `unit_has_nested_question` to `NESTABLE_QUESTION_KEYS` | the `extended_response` case only — the `fill_blank` case stays green, which is why the wide case must exist |

Edit each back out by hand.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check --no-cache courses/ && uv run ruff format --check courses/
git add courses/builder.py courses/views_manage.py courses/tests/test_nested_question_gates.py
git commit -m "feat(nesting): refuse a nested question in a quiz at three builder authorities

Task 5. resolve_scope, paste_allowed (inside the dest_parent branch, so a
top-level paste into a quiz stays legal) and rename_node's lesson->quiz flip,
which must read unit_type BEFORE the assignment or it is dead code.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Transfer — archive refusal and the `FORMAT_VERSION` bump

**Files:**
- Modify: `courses/transfer/payloads.py:858`, `courses/transfer/schema.py:14,358`
- Modify: 7 files asserting `FORMAT_VERSION == 11` (`tests/test_tabs_transfer.py`'s **nesting** case was already rewritten in Task 4 Step 5; only its version literal remains)
- Create: `courses/tests/test_nested_question_transfer.py`

- [ ] **Step 1: `validate_nesting` gains `unit_types=None`**

Keyword-with-default is **required**: **20** positional call sites across six test files pass `elements` alone (Task 4 Step 5 added one to the plan-time count of 19). Add the clause **immediately after** the existing `NESTABLE_TYPE_KEYS` clause (`:922`), so "not nestable at all" wins over "not nestable here":

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

`el["unit"]`, deliberately — **not** the parent's unit. `validate_nesting` never checks that a child and its parent share a unit, so the two can disagree; `el["unit"]` is the unit the row is actually created in, and `schema.py:344-349` has already validated it points at a unit node. `"quiz"` is the **raw string** — the archive's `unit_type` is validated at `schema.py:281` against the literal pair and never becomes a `ContentNode`.

- [ ] **Step 2: `schema.py` builds the map and bumps the version**

```python
FORMAT_VERSION = 12
```

```python
    unit_types = {
        nd["id"]: nd.get("unit_type") for nd in nodes if nd.get("kind") == "unit"
    }
    validate_nesting(elements, unit_types=unit_types)
```

- [ ] **Step 3: Write the clause's own tests**

Create `courses/tests/test_nested_question_transfer.py`. Without these, deleting Step 1's clause entirely would leave the whole task green.

(If executing strictly TDD, write this file and run it **before** Steps 1-2 — it fails with `TypeError: validate_nesting() got an unexpected keyword argument 'unit_types'`, a real RED. Task 2 Steps 1-4 model that order. Written after, it is green on creation, which is weaker but acceptable given Step 8's mutant.)

Imports first (isort is `force-single-line`; note `TransferError` lives in `schema`, **not** `payloads`):

```python
import pytest

from courses.transfer.payloads import validate_nesting
from courses.transfer.schema import TransferError
```

**Copy `_els` / `_tabs_el` / `_child` from `tests/test_tabs_transfer.py:109-125` — and ADD a `"unit"` key to both dicts.** Those helpers emit `{"id", "type", "data", "parent", "tab"}` with **no `"unit"`**, because every existing caller passes no `unit_types` and the clause short-circuits on `unit_types is not None` before ever reading it. A straight paste raises `KeyError: 'unit'` the moment `unit_types` is non-`None`:

```python
def _tabs_el(eid="e1", unit="n1"):
    return {"id": eid, "type": "tabs", "unit": unit,
            "data": {"tabs": [{"id": "taaaaaa", "label": "A"}]},
            "parent": None, "tab": ""}


def _child(eid="e2", parent="e1", tab="taaaaaa", type_="choice", unit="n1"):
    return {"id": eid, "type": type_, "unit": unit, "data": {},
            "parent": parent, "tab": tab}


def test_a_question_nested_in_a_quiz_unit_is_rejected():
    with pytest.raises(TransferError):
        validate_nesting([_tabs_el(), _child()], unit_types={"n1": "quiz"})


def test_the_same_nesting_in_a_lesson_unit_is_accepted():
    validate_nesting([_tabs_el(), _child()], unit_types={"n1": "lesson"})


def test_the_childs_own_unit_governs_not_the_parents():
    """el["unit"], deliberately -- validate_nesting never checks that a child and
    its parent share a unit, so a crafted archive can make them disagree."""
    els = [_tabs_el(unit="n_lesson"), _child(unit="n_quiz")]
    with pytest.raises(TransferError):
        validate_nesting(els, unit_types={"n_lesson": "lesson", "n_quiz": "quiz"})


def test_a_non_nestable_type_reports_the_existing_message_first():
    """Ordering: "not nestable at all" wins over "not nestable HERE".

    validate_nesting has no reason keys -- every clause raises through _err() with
    a translated message -- so this matches on the EXISTING msgid, not on a
    paste_allowed key.
    """
    with pytest.raises(TransferError, match="may not be nested"):
        validate_nesting(
            [_tabs_el(), _child(type_="drag_fill_blank")], unit_types={"n1": "quiz"}
        )
```

- [ ] **Step 4: Run and watch seven assertions go RED**

```bash
uv run pytest courses/tests/test_nested_question_transfer.py courses/tests/test_beforeafter_transfer.py courses/tests/test_image_size_transfer.py tests/test_link_transfer.py tests/test_table_transfer.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py -v
```
Expected: seven `assert FORMAT_VERSION == 11` (or `manifest["format_version"] == 11`) FAIL. **The tabs nesting case is NOT among them** — it broke in Task 4 and was rewritten there (Task 4 Step 5). Only that file's version literal remains.

- [ ] **Step 5: Fix them**

Bump each literal `11` → `12`. Nothing else in these seven files changes.

- [ ] **Step 6: Add the round-trip test**

`choice` is the only newly nestable type with child rows, and both `duplicate_element` and the paste flow go through the transfer serializers — so duplicating a callout is the first thing an author does after nesting a question.

**Model it on `tests/test_tabs_transfer.py:265`'s `_round_trip(client, course)`** — verified during execution as the only real export→validate→import shape in the suite: `write_archive` → `open_archive` → `validate_archive_document` → `import_course`. (`test_callout_transfer.py` has a *serializer-level* round trip plus export-only and `duplicate_*` tests but never calls `validate_document`; `test_twocolumn_transfer.py` calls none of the three. Do not model on either.)

Note `build_export(course, node=None, source_host="", *, drop_missing_media=True, …)` — its first three arguments are **positional**, not keyword-only; `validate_document(doc, *, kind, …)` is keyword-only after the first.

Assert the re-imported child's `parent`, `tab_id`, concrete type and its `Choice` rows (`is_correct`, `feedback`) all match.

**Mutant:** drop `"choice"` from `NESTABLE_TYPE_KEYS` → the round-trip goes RED at the `validate_document` step. Edit it back out.

- [ ] **Step 7: Verify the 20 positional call sites still pass**

```bash
uv run pytest courses/tests/test_beforeafter_transfer.py courses/tests/test_callout_transfer.py courses/tests/test_spoiler_transfer.py tests/test_tabs_transfer.py tests/test_transfer_nesting_depth.py tests/test_twocolumn_transfer.py -v
```
Expected: all PASS — that is exactly what the keyword-with-default protects.

- [ ] **Step 8: Falsify**

Change the clause's lookup from `unit_types.get(el["unit"])` to the **parent's** unit (`unit_types.get(by_id[el["parent"]]["unit"])`). Expected: `test_a_question_nested_in_a_quiz_unit_is_rejected` stays **green** (same-unit fixture) while `test_the_childs_own_unit_governs_not_the_parents` goes RED — which is exactly why that third test exists. Edit the mutant out by hand.

- [ ] **Step 9: Re-check for a competing bump, then commit**

```bash
gh pr list --state open
```
Two branches bumping `FORMAT_VERSION` to the **same** number produce no git conflict — identical lines merge silently and one capability ships under a version claiming the other. This was empty at spec time; confirm again.

```bash
git add courses/transfer/payloads.py courses/transfer/schema.py courses/tests/test_nested_question_transfer.py courses/tests/test_beforeafter_transfer.py courses/tests/test_image_size_transfer.py tests/test_link_transfer.py tests/test_table_transfer.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py
git commit -m "feat(transfer): refuse a nested question in a quiz archive, bump FORMAT_VERSION to 12

Task 6. The set of legal archive contents changed even though the shape did not,
so an unbumped archive would import into an older deployment and be rejected with
a message blaming the content rather than the version skew.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The LAL loader guard

**Files:**
- Modify: `courses/lal_loader/builders.py`
- Create: `tests/lal_import/test_loader_question_in_quiz.py`

- [ ] **Step 1: Add the guard at the TOP of `build_element`**

**Not at the container branches.** The loader has **two** recursive nesting sites: `if etype == "spoiler":` (`:114-163`) gates children against `LAL_SPOILER_CHILD_TYPES`, but `if etype == "tabs":` (`:201-224`) recurses with **no allowlist and no unit-type check at all** — and all six question branches are reachable from it: `choice_grid` (`:171`), `multi_grid` (`:184`), `fillblank` (`:237`), `choice` (`:378`), `numeric` (`:400`), `shorttext` (`:425`). A guard at the spoiler branch closes half the hole.

Add `from courses.models import ContentNode` at module level — **`builders.py` does not import it today** (only `guards.py` and `tree.py` do), so the snippet would `NameError` without this.

```python
# EVERY question etype this loader can build -- SIX branches, not four:
# choice_grid (:171) and multi_grid (:184) are QuestionElement subclasses too, and
# both are reachable from the ungated tabs recursion at :201. Deliberately as wide
# as unit_has_nested_question (which spans all ten concrete question models), NOT
# as narrow as NESTABLE_QUESTION_KEYS: a manifest creating tabs > choice_grid in a
# quiz would otherwise land content that no write authority refused, and that unit
# is then permanently barred from every unit_type flip.
#
# Spelled CANONICALLY because the guard canonicalises first: _PARSER_TO_CANONICAL
# maps "fillblank" -> "fill_blank" (builders.py:50), so a set holding the raw
# "fillblank" would never match and the spoiler case would silently pass.
LAL_QUESTION_TYPES = frozenset(
    {"choice", "numeric", "shorttext", "fill_blank", "choice_grid", "multi_grid"}
)
```

At the top of `build_element`, after the `flagged` handling — which either raises or
returns, so a flagged element can never reach the guard and **no `not
el.get("flagged")` clause belongs in the condition**. Adding one would be a
condition that cannot fail, the pattern this repo's reviews strip out:

```python
    # Nested question in a QUIZ unit: refused for every recursion site at once.
    # `parent is not None` means "this call is creating a nested row". Placed here,
    # not at the container branches: the tabs recursion is entirely ungated, and a
    # per-branch guard would have to be remembered a third time by the next slice.
    if (
        parent is not None
        and _PARSER_TO_CANONICAL.get(etype, etype) in LAL_QUESTION_TYPES
        and unit.unit_type == ContentNode.UnitType.QUIZ
    ):
        raise LoaderError(
            f"a question ({etype}) may not be nested in quiz unit {unit.pk}; "
            "questions nest in lesson units only"
        )
```

`LoaderError` is operator-facing and **not** translated.

**The tabs recursion's missing type allowlist stays out of scope** — a pre-existing `NESTABLE_TYPE_KEYS` bypass this task neither widens nor closes.

- [ ] **Step 2: Write the three loader tests**

Create `tests/lal_import/test_loader_question_in_quiz.py`, following the shape of `tests/lal_import/test_loader_spoiler_gate.py` — direct `build_element(course, unit, el_dict, ...)` calls, per-test `@pytest.mark.django_db`, and an assertion on the **message**, not just the exception class.

```python
@pytest.mark.django_db
def test_fillblank_in_a_spoiler_in_a_quiz_is_refused():
    """The spoiler path -- fill_blank is the only question type its allowlist admits."""
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    spoiler = {
        "type": "spoiler",
        "label": "s",
        "elements": [{"type": "fillblank", "stem": "Cap is {{paris}}."}],
    }
    with pytest.raises(LoaderError, match="may not be nested in quiz unit"):
        build_element(course, quiz, spoiler, source_root=None, source_dir=None,
                      allow_html=False, parent=None, tab_id="", missing=[])


@pytest.mark.django_db
def test_choice_in_a_tabs_element_in_a_quiz_is_refused():
    """The tabs path has NO allowlist at all, so a spoiler-only gate leaves this
    green. This is the case that proves the guard sits at build_element."""
    ...tabs dict with one tab whose "elements" holds a {"type": "choice", ...}...


@pytest.mark.django_db
def test_flipping_to_quiz_while_dropping_the_nested_question_is_accepted():
    """upsert_node runs BEFORE rebuild_unit_elements, which deletes every element
    first -- so a guard on the flip would stale-read the previous run and refuse a
    legal manifest revision. The child-creation guard sees the NEW unit_type and
    the NEW children, and transaction.atomic rolls the flip back on refusal."""
    ...build a quiz unit whose manifest has a tabs element with NO question child;
    assert it builds without raising...
```

Match the exact `build_element` keyword names against `tests/lal_import/test_loader_spoiler_gate.py` before running.

- [ ] **Step 3: Falsify**

Move the guard from the top of `build_element` into the `spoiler` branch only → the **tabs** test FAILs, the spoiler one stays green. Edit it back.

- [ ] **Step 4: Run, lint, commit**

```bash
uv run pytest tests/lal_import/ -v
uv run ruff check --no-cache courses/ tests/ && uv run ruff format --check courses/ tests/
git add courses/lal_loader/builders.py tests/lal_import/test_loader_question_in_quiz.py
git commit -m "feat(lal): refuse a nested question in a quiz unit at both loader recursion sites

Task 7. The loader nests under spoiler AND tabs; the tabs recursion has no
allowlist at all, so the guard goes at the top of build_element.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The editor preview

**Files:**
- Modify: `templates/courses/manage/editor/_preview.html:16`
- Modify: `courses/templatetags/courses_extras.py` — question branch
- Modify: `courses/views_manage.py:2363-2373`
- Create: `courses/tests/test_nested_question_preview.py`

- [ ] **Step 1: Flag the preview**

```html
<section class="prev-el" data-element-id="{{ el.pk }}">{% render_element el action_url=try_url editor_preview=True %}</section>
```

Add a comment naming `editor_preview` as **not** the existing `previewing` flag (`views.py:1394`), which means "a non-enrolled **student** is viewing this quiz" — the opposite audience, and one that must never route forms at a manage-gated endpoint.

- [ ] **Step 2: Reverse the child's own try URL**

In `render_element`'s question branch, before `obj.render(...)`:

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

Top-level preview elements keep their explicitly passed `try_url` — this fires only where `action_url` is absent, which today means exactly "nested".

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

**This fixes nothing observable.** `editor.js` fetches `tryForm.getAttribute("action")` from the **live** form node (`:250`) and swaps only `innerHTML` (`:272`), so the response's `action` is discarded. Kept because a manage-gated fragment should not carry a student endpoint in its markup — two lines. **If it costs more than that, drop it** (and drop Step 4's second assertion with it); that is the correct call, not a compromise. `reverse()` takes `kwargs=`, not loose keyword arguments.

(`element_try`'s quiz `INLINE_QUIZ_REVEAL` branch at `:2393-2405` is deliberately left alone: after Task 5 a nested question cannot exist in a quiz.)

- [ ] **Step 4: Preview tests**

Create `courses/tests/test_nested_question_preview.py`, with two tests:

1. A nested question's form `action` in the rendered preview is `manage_element_try` for **its own** pk — three distinct assertions, since two of them are the actual bug: **not** `check_answer`, **not** the parent's pk, and **equal to** the child's own try URL.

   **Drive the real editor page**, not `render_to_string` on the partial: a direct render would need `unit`, `preview_elements` and `editor_preview` seeded by hand and would never exercise `_preview.html:15`'s `{% url %}`. Log in as the course owner (the `_managed(client)` shape from `tests/test_tabs_registry.py:37-41`), put a `choice` question inside a callout in the lesson, then `GET reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})` and assert on the response body.
2. For Step 3: `element_try`'s choice re-render returns a fragment whose form action is `manage_element_try`, not `check_answer`. This is a **markup** assertion — `editor.js` discards the attribute — and it is dropped if Step 3 is dropped.

- [ ] **Step 5: Falsify, lint, commit**

Falsify: default `editor_preview` to `False` instead of `None` → preview test 1 FAILs (the fallback becomes dead code). Restore.

```bash
uv run pytest courses/tests/test_nested_question_preview.py -v
uv run ruff check --no-cache courses/ && uv run ruff format --check courses/
git add templates/courses/manage/editor/_preview.html courses/templatetags/courses_extras.py courses/views_manage.py courses/tests/test_nested_question_preview.py
git commit -m "fix(editor): post a nested question's preview Check to its own try endpoint

Task 8. A nested question rendered with action_url=None and fell back to the
STUDENT check_answer URL, persisting practice state against the author's account.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Translations, stale comments, and the content pre-flight

**Files:**
- Modify: `locale/{en,pl}/LC_MESSAGES/django.po` (+ `.mo`)
- Modify: `courses/views.py`, `courses/views_manage.py` (comments only)

- [ ] **Step 1: Run the pre-flight against the local dev database**

```bash
uv run python manage.py shell -c '
from django.contrib.contenttypes.models import ContentType
from courses.models import ContentNode, Element
from courses.richtext import CONCRETE_QUESTION_MODELS

ct_ids = {ContentType.objects.get_for_model(m).id for m in CONCRETE_QUESTION_MODELS}
print(Element.objects.filter(
    parent__isnull=False,
    content_type_id__in=ct_ids,
    unit__unit_type=ContentNode.UnitType.QUIZ,
).count())
'
```

All ten models, not the four widened ones — the point is to find anything at all. Expected: **0**. A non-zero count **halts the task and is reported**; do not auto-repair, the remedy is an editorial decision.

- [ ] **Step 2: Fix the two stale comments**

- `courses/views.py` (~`:416-419`): "Only fill_blank is nestable today, so this only newly fires for a nested fillblank" — now four types.
- `courses/views_manage.py:2179-2181`: states `"choicequestion"` "is not in `NESTABLE_TYPE_KEYS`, so clause 1 rejects it" — false after Task 4, and it sits directly above the call site.

- [ ] **Step 3: Regenerate translations**

**Exactly three new msgids**, not four — `NestingError` is the excluded fourth: it is discarded by the view (`element_add` returns `HttpResponseBadRequest("bad nesting")`) and left untranslated per Task 5 Step 3, matching every other `NestingError` in `builder.py`:

1. `_err(_("Element '%(el)s' is a question and may not be nested in a quiz."), …)` — Task 6
2. `PASTE_REFUSAL_MESSAGES["question_in_quiz"]` — Task 5
3. `rename_node`'s `ValidationError` — Task 5, wrapped in `gettext_lazy` because it *is* shown to the author verbatim

```bash
uv run python manage.py makemessages -l en -l pl
```

**Clear every fuzzy pre-fill.** `makemessages` fuzzy-fills a *wrong* Polish string from a similar msgid, and a fuzzy entry is not used at runtime — so it silently reads as "translation missing" in production. Removing one means deleting **both** the `#, fuzzy` marker and the wrong `msgstr`.

```bash
uv run python manage.py compilemessages
uv run pytest tests/test_i18n_po_health.py tests/test_i18n_questions.py tests/test_i18n_editor_rows.py -v
```

Named files, not `tests/ -k i18n` — that collects the whole tree, which the Global
Constraints reserve for the branch gate. `test_i18n_po_health.py` is the one that
asserts no obsolete (`#~`) and no fuzzy entries survive.

- [ ] **Step 4: Commit**

```bash
git add locale/ courses/views.py courses/views_manage.py
git commit -m "i18n(nesting): new refusal messages, EN+PL, fuzzy pre-fills cleared

Task 9. Also corrects two comments the widening falsified.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: e2e and visual verification

**Files:**
- Create: `tests/test_e2e_nested_question.py`, `tests/capture_nested_question_screenshots.py`

- [ ] **Step 1: e2e — a nested choice question with JS on**

Inside a **closed** `<details>` spoiler and inside an **inactive** tab panel, it must still check and show inline feedback. `question.js` binds to `[data-question]` document-wide with no depth assumption, so no JS change is expected — the e2e proves that rather than assuming it.

**Copy the scaffolding** (login, enrolment, page setup, the nest-inside-a-Tabs-panel fixture) from `tests/test_e2e_filltable.py:485` or `tests/test_e2e_switchgrid.py:288` — both already drive a `NESTABLE_TYPE_KEYS` member nested inside a Tabs panel, so only the element type and the assertions change.

Two traps:
- Playwright reports a `.visually-hidden` element as **visible** (1×1 + `clip` has a non-empty box) — assert on `bounding_box()`, not `is_visible()`.
- A closed `<details>` hides content via `content-visibility`, so use `checkVisibility()` rather than `is_visible()`.

```bash
uv run pytest tests/test_e2e_nested_question.py -m e2e -v
```

Run **foreground**. `-n 2` is faster than `-n 8` here — the bottleneck is TRUNCATE teardown, not CPU.

- [ ] **Step 2: Capture the screenshots**

Create `tests/capture_nested_question_screenshots.py`, modelled on the existing `tests/capture_*_screenshots.py` scripts. It renders a lesson holding a `choice` question inside each of the five containers and writes PNGs to `docs/superpowers/screenshots/nested-question-<container>-<theme>.png`.

For dark mode set **`user.theme`**, not the cookie.

```bash
uv run python tests/capture_nested_question_screenshots.py
```

**"Judged" means three specific facts per image**, checked by reading them: (a) the question's controls and verdict are inside the container's visual bounds, not overflowing; (b) vertical rhythm between the container's own body and the nested question matches a top-level question's; (c) in dark mode the verdict text and any per-option marker meet contrast against the container's background — judged on the dark image alone, not inferred from light.

- [ ] **Step 3: If any CSS proves necessary, A/B it**

Capture with and without the new rule. Measuring with the rule present proves nothing about whether the rule does anything.

- [ ] **Step 4: Branch gate — the full suite, once**

```bash
uv run pytest --verbosity=0
uv run pytest -m e2e --verbosity=0
uv run ruff check --no-cache . && uv run ruff format --check .
```

**Not `-q`.** `pyproject.toml` sets `addopts = "-q -m 'not e2e'"`, so an explicit
`-q` doubles to `-qq` and **suppresses the run summary** — losing the pass/fail line
on the one whole-repo verification step of the branch.

`scripts/e2e_chunks.sh` is stale — it covers 84 of 97 e2e files, so "I ran the full suite" through it is off by ~20%. Run the marker directly.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_nested_question.py tests/capture_nested_question_screenshots.py docs/superpowers/screenshots/
git commit -m "test(nesting): e2e a nested choice question in a closed spoiler and an inactive tab

Task 10. Plus light+dark capture across all five containers.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** — §3 render seam → T1; §4.1 spoiler → T2; §5/§5.1 preview → T8; §6.1–6.2 widening + menu → T4; §6.3 authorities 1–3 → T5, authority 4 → T6, authority 5 → T7; §6.4 pre-flight → T9; §6.5 FORMAT_VERSION → T6; §7 error handling → T1/T5/T7; §8 accepted costs → **T1 Step 8** (both comments); §9.1–9.4 → T1/T2/T3; §9.5 gates → T4 Step 6 (drift), T4 Step 7 (endpoint), T5 Step 6, T6 Step 3, T7 Step 2; §9.6 expected-RED → T4 Step 3, T6 Step 4; §9.7 preview → T8 Step 4 (**both** assertions); §9.8–9.9 → T10.

**Type consistency** — `page` dict keys identical in T1 (producer), T2 (`feedback_ancestor_pks`), T3 (key-set assertion), T8 (`editor_preview`). `ancestor_pks` / `unit_has_nested_question` / `CONTAINER_MODELS` / `NESTABLE_QUESTION_KEYS` / `LAL_QUESTION_TYPES` spelled identically at every site. `build(make_container, make_question=_fill_blank)` is defined in T3 Step 1 and used in T3 Steps 3–5.

**Every task names a mutant** — T1 (two), T2 (two), T3 (two), T4 (alias), T5 (three), T6 (parent-unit lookup), T7 (guard placement), T8 (`False` default). T9 and T10 are verification tasks with no production logic of their own.
