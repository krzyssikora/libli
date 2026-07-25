# Show "Start fresh" only on units that can hold practice state — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide the lesson-unit **Start fresh** link on units that contain no element type capable of persisting practice state, so the link is never a guaranteed no-op.

**Architecture:** A new pure helper in `courses/state.py` derives the set of state-bearing `content_type.model` names by unioning the two existing registries (`state.VALIDATORS` and the question types with `RESTORABLE_IN_LESSON`). `build_lesson_context` turns that into one `.exists()` query producing a `has_stateful_elements` context flag, and `_lesson_article.html` wraps the existing anchor in `{% if %}`. No migration, no new strings, no CSS.

**Tech Stack:** Django 5.2, pytest + pytest-django, Playwright (e2e), `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-07-25-start-fresh-only-on-stateful-units-design.md` (8 review rounds, 86 catches applied). Read §Testing before writing any test — it names each test's falsification.

## Global Constraints

- **All tooling runs through `uv run`.** `pytest`, `ruff`, `python` are not on PATH.
- **Test DB:** this worktree's `.env` pins `DATABASE_URL=…/libli_freshbtn`. Never change it — a parallel worktree is live and shares the Postgres server.
- **`pytest` excludes e2e by default** (`pyproject.toml:49` = `addopts = "-q -m 'not e2e'"`). Any e2e run needs an explicit `-m e2e` or it silently collects zero tests and exits 0.
- **pytest verdict lines do not survive a Bash pipe on this box.** Rely on the exit code, or `grep FAILED`, or read the tail of a redirected file.
- **Two symbols are named `VALIDATORS`.** `courses.state.VALIDATORS` is the one this plan means; `courses.transfer.payloads.VALIDATORS` is a different namespace that ~20 test modules import bare. Always write `state.VALIDATORS`.
- **Falsify every guard.** A passing test proves nothing here. For each test, apply its named mutation, observe RED, revert, and report the observed RED in the task's completion notes. Never report "passes" alone.
- **No migration, no new or changed translatable strings, no CSS change.** If a step seems to need one, stop — the spec is wrong and needs revisiting.
- **Never assert line numbers** in source-text guards; this change moves them.
- **`courses/views.py` line numbers in this plan are pre-Task-2.** Task 2 inserts ~11 lines into
  `build_lesson_context`, so from Task 3 onward every anchor below `:370` has shifted down by roughly
  that much (`:373`→~`:384`, `:404-428`→~`:415-439`, `:559`→~`:570`, `:828`→~`:839`). Navigate by the
  quoted symbol or code text given alongside each anchor, never by the number alone.
- **Run `uv run ruff check --fix` before each task's lint gate.** `pyproject.toml` selects `I` with
  `force-single-line = true`, so new imports must land in sorted position; appending them in a block
  yields `I001`. The merged import blocks below are already sorted, but `--fix` is the safety net.
- **After every falsification: revert, re-run the test, and confirm it is GREEN again** before applying
  the next mutation. Record the RED→GREEN pair. A partially-reverted mutation surfacing in Task 6 is
  much harder to attribute.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `courses/state.py` | Modify (add one function after `validate_state`) | Derives the 18 state-bearing model names from the two registries |
| `courses/views.py` | Modify (`build_lesson_context`, + a comment at `progress_reset`) | Turns those names into the `has_stateful_elements` flag |
| `courses/models.py` | Modify (one comment at `UnitProgress.element_state`) | The lockstep contract note at the storage surface |
| `templates/courses/_lesson_article.html` | Modify (lines 24-27) | Gates the anchor |
| `courses/tests/test_state_module.py` | Modify (add 2 tests) | Tests 8-9: the derivation and its intersection |
| `courses/tests/test_reset_controls.py` | Modify (1 test) + add 6 | Tests 1-7: rendered-link behaviour |
| `tests/test_element_state_write_routes.py` | Create | Test 10: the write-route source guard |
| `tests/test_e2e_unit_head_layout.py` | Modify | Keeps the three-child head row measured |

---

### Task 1: The derivation helper (spec C1) + tests 8-9

**Files:**
- Modify: `courses/state.py` (append after `validate_state`, which ends at `:131`)
- Test: `courses/tests/test_state_module.py` (append)

**Interfaces:**
- Consumes: `courses.state.VALIDATORS` (existing, 8 keys); `courses.models.ELEMENT_MODELS` (existing, 31 names).
- Produces: `courses.state.stateful_element_model_names() -> tuple[str, ...]` — a **sorted tuple** of 18 `content_type.model` names. Task 2 calls it as `state_svc.stateful_element_model_names()`; Task 3's test 6 monkeypatches it by that dotted path.

- [ ] **Step 1: Write the two failing tests**

Append to `courses/tests/test_state_module.py`. Note the module already has `pytestmark = pytest.mark.django_db` and `from courses import state` at the top — do not re-import.

```python
# The 18 element types that can persist practice state, written out literally.
# DELIBERATELY hard-coded rather than re-derived: re-implementing state.py's
# comprehension here would be green by construction and could never go RED
# (spec §Testing, test 8). Derive in production, pin literally in the test.
STATEFUL_MODEL_NAMES = {
    # the state.VALIDATORS half -- self-checks and gates
    "markdoneelement",
    "revealgateelement",
    "fillgateelement",
    "switchgateelement",
    "switchgridelement",
    "filltableelement",
    "guessnumberelement",
    "stepperelement",
    # the RESTORABLE_IN_LESSON half -- lesson-mode question answers
    "choicequestionelement",
    "shorttextquestionelement",
    "extendedresponsequestionelement",
    "shortnumericquestionelement",
    "fillblankquestionelement",
    "dragfillblankquestionelement",
    "matchpairquestionelement",
    "dragtoimagequestionelement",
    "choicegridquestionelement",
    "multigridquestionelement",
}


def test_stateful_element_model_names_is_the_expected_18():
    from courses.models import ELEMENT_MODELS

    names = state.stateful_element_model_names()

    assert set(names) == STATEFUL_MODEL_NAMES
    # Sortedness: compare against a TUPLE, not a list. `list(names) == sorted(names)`
    # would let a raw set pass whenever its hash order happened to be sorted, making
    # the RED hash-seed dependent; a set never equals a tuple (spec §Testing, test 8).
    assert names == tuple(sorted(names))
    # Known-inert types stay out (shares the equality guard's falsification).
    assert "textelement" not in names
    assert "videoelement" not in names
    # The registry contract the `& known` intersection relies on. Falsified TEST-SIDE
    # only (monkeypatching in a bogus key) -- no production edit fires this one.
    assert set(state.VALIDATORS) <= set(ELEMENT_MODELS)


def test_a_bogus_validator_key_is_dropped_from_the_derived_names(monkeypatch):
    """The `& known` intersection itself, which nothing else can falsify.

    The real VALIDATORS is clean by construction, so deleting `& known` from
    state.py leaves the whole suite green. Only a bogus key surfaces it.
    """
    monkeypatch.setitem(state.VALIDATORS, "nosuchelement", lambda *a: None)

    # Equality, not `"nosuchelement" not in ...`: a widened result must be caught as
    # a value change, since the names feed a content_type__model__in filter.
    assert set(state.stateful_element_model_names()) == STATEFUL_MODEL_NAMES
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest courses/tests/test_state_module.py -k stateful_element_model_names -v
uv run pytest courses/tests/test_state_module.py -k bogus_validator_key -v
```

Expected: both FAIL with `AttributeError: module 'courses.state' has no attribute 'stateful_element_model_names'`.

- [ ] **Step 3: Implement the helper**

Append to `courses/state.py`, immediately after `validate_state` (so the module reads `VALIDATORS` → `validate_state` → this, keeping the registry beside both consumers). Add no module-level imports — the two imports are deliberately function-local.

```python
def stateful_element_model_names():
    """content_type.model NAMES of every element type that can persist practice state:
    the validator registry UNION the question types that opt into RESTORABLE_IN_LESSON.
    Returns a sorted tuple of strings, fed straight to a content_type__model__in filter.

    DERIVED, never hand-listed. A literal list here would be a second hand-maintained
    copy of two registries that live elsewhere, in the same namespace they already use --
    and it would drift silently: a new state-bearing type would keep its state but lose
    its reset affordance.

    Sorted so the generated SQL parameter list is stable run to run. NOT cached: the
    suite monkeypatches VALIDATORS (see test_state_module.py), and a cache would make
    the result order-dependent -- 31 registry lookups is nothing beside the query this
    feeds.

    The `& known` intersection keeps a bogus/stale VALIDATORS key out of the RETURNED
    tuple. It does NOT guard the get_model call below -- that loop only ever iterates
    ELEMENT_MODELS, so a bad registry key could never reach it either way.

    CONTRACT (restated at the UnitProgress.element_state field declaration): these two
    routes are the only LIVE APPLICATION write routes into element_state -- migration
    0050's historical re-key and progress_reset's bulk clear aside, neither of which
    introduces a new state-bearing type. A third such route must extend this function in
    lockstep, or whatever it persists becomes unresettable from the unit page.
    """
    from django.apps import apps  # lazy: keeps this module import-time model-free

    from courses.models import ELEMENT_MODELS

    known = set(ELEMENT_MODELS)
    return tuple(
        sorted(
            (set(VALIDATORS) & known)
            | {
                name
                for name in ELEMENT_MODELS
                if getattr(apps.get_model("courses", name), "RESTORABLE_IN_LESSON", False)
            }
        )
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest courses/tests/test_state_module.py -v
```

Expected: PASS, including the module's pre-existing tests.

- [ ] **Step 5: Falsify each guard and record the observed RED**

Apply each mutation, run the named test, confirm RED, then **revert before the next one**.

| Guard | Mutation in `courses/state.py` | Must go RED |
|---|---|---|
| 18-name equality (+ inert-type absence — same mutation) | `(set(VALIDATORS) & known) - {"stepperelement"}` | `test_stateful_element_model_names_is_the_expected_18` |
| Sortedness | `return set(...)` instead of `tuple(sorted(...))` | same test |
| `& known` intersection | delete `& known` | `test_a_bogus_validator_key_is_dropped_from_the_derived_names` |
| `VALIDATORS <= ELEMENT_MODELS` | **test-side only** — temporarily change the first test's signature to `def test_stateful_element_model_names_is_the_expected_18(monkeypatch):` and add `monkeypatch.setitem(state.VALIDATORS, "nosuchelement", lambda *a: None)` as its first line. Without the signature change you get `NameError: monkeypatch`, which is not the RED you are looking for. | first test |

Record all four observed REDs in the completion notes.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check courses/state.py courses/tests/test_state_module.py
uv run ruff format --check courses/state.py courses/tests/test_state_module.py
git add courses/state.py courses/tests/test_state_module.py
git commit -m "feat(state): derive the set of element types that can persist practice state"
```

---

### Task 2: The flag, the template gate, and the render-level tests (spec C2, C3; tests 1-4)

**Files:**
- Modify: `courses/views.py` (`build_lesson_context`, after `has_guess_number` at `:367-369`)
- Modify: `templates/courses/_lesson_article.html:24-27`
- Test: `courses/tests/test_reset_controls.py`

**Interfaces:**
- Consumes: `state_svc.stateful_element_model_names()` from Task 1. `state_svc` is already imported at `views.py:27` as `from courses import state as state_svc`.
- Produces: context key `has_stateful_elements` (bool), consumed by `_lesson_article.html` and by Task 3's tests.

- [ ] **Step 1: Watch the existing test go RED first**

`test_lesson_page_links_to_the_reset_interstitial` (`test_reset_controls.py:19-26`) seeds `make_course_with_unit()` with **no elements at all** — exactly the case this feature hides. It will break once Step 4 lands, and that is the signal, not a regression. Record its current state now:

```bash
uv run pytest courses/tests/test_reset_controls.py::test_lesson_page_links_to_the_reset_interstitial -v
```

Expected: PASS (pre-change baseline).

- [ ] **Step 2: Write the failing tests**

In `courses/tests/test_reset_controls.py`, **replace** `test_lesson_page_links_to_the_reset_interstitial` (lines 19-26) with the version below, and append the three new tests.

**Replace the file's whole import block** with this merged, already-sorted version (isort is enforced with `force-single-line = true`, so appending a block would fail `I001`):

```python
import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Element
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import ShortTextQuestionElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user
```

```python
def _reset_url(course, unit):
    return reverse("courses:progress_reset", args=[course.slug, unit.pk])


def test_lesson_page_links_to_the_reset_interstitial(client):
    # Now seeds a state-bearing element: the link is gated on the unit CONTAINING a
    # type that can persist practice state (spec D1). No MarkDoneItem rows needed --
    # the flag is type-based, not content-based.
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_lesson_page_hides_the_reset_link_on_a_unit_with_no_stateful_element(client):
    # A text/video-only unit can hold nothing element_state ever stores, so reset is a
    # guaranteed no-op there and the link is not offered (spec §Purpose).
    course, unit = make_course_with_unit()
    add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    body = r.content.decode()
    # The positive anchor matters: "URL absent" is also satisfied by a 302 to login, a
    # 403, a 404 or a 500 -- i.e. by every failure mode of the FIXTURE rather than of
    # the condition under test.
    assert r.status_code == 200
    assert reverse("courses:complete", args=[course.slug, unit.pk]) in body
    assert _reset_url(course, unit) not in body


def test_lesson_page_shows_the_reset_link_for_an_element_nested_in_a_tab(client):
    # Children of a Tabs join row keep their own `unit` FK, so the flag's query is FLAT
    # (not parent__isnull=True). Scoping it to top level would hide the link on a unit
    # whose only interactive content lives inside a tab.
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=MarkDoneElement.objects.create(prompt="P"),
        parent=join,
        tab_id=tab_id,
    )
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_lesson_page_shows_the_reset_link_on_a_question_only_unit(client):
    # Covers the RESTORABLE_IN_LESSON half of the union. Every other render-level test
    # uses the validator half, so without this a bad implementation could drop questions
    # entirely and stay green. Seed NOTHING else -- the question must be the only
    # interactive element for this test's falsification to bite.
    course, unit = make_course_with_unit()
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q", accepted="x"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest courses/tests/test_reset_controls.py -v
```

Expected: `test_lesson_page_hides_the_reset_link_on_a_unit_with_no_stateful_element` FAILS (the link is still rendered unconditionally). The other three PASS — they assert presence, which is the current unconditional behaviour. That asymmetry is expected: the gate does not exist yet.

- [ ] **Step 4: Add the flag to `build_lesson_context`**

In `courses/views.py`, insert immediately after the `has_guess_number` assignment (`:367-369`) and **before** the `progress = None` block at `:371`:

```python
    # Capability, NOT stored state: true iff this unit CONTAINS a state-bearing element
    # type, regardless of whether this student has stored anything (spec D1). Flat over
    # node.elements (NOT parent__isnull=True) so a gate or question nested in a tab,
    # column or spoiler still counts -- children keep their own `unit` FK.
    # app_label pins the join the way Element.content_type's own limit_choices_to does;
    # get_for_model ct-ids were rejected because cold-cache CT SELECTs break
    # tests/test_html_element.py's query-count assertion.
    # Called through the module attribute so test 6's monkeypatch can bind.
    has_stateful_elements = node.elements.filter(
        content_type__app_label="courses",
        content_type__model__in=state_svc.stateful_element_model_names(),
    ).exists()
```

Then add it to the returned dict, beside its `has_*` neighbours (after `"has_guess_number": has_guess_number,` at `:420`):

```python
        "has_stateful_elements": has_stateful_elements,
```

- [ ] **Step 5: Gate the anchor**

In `templates/courses/_lesson_article.html`, replace lines 24-27 with:

```html
    {% if has_stateful_elements %}
      <a class="btn btn--ghost btn--small lesson-unit__reset"
         href="{% url 'courses:progress_reset' slug=course.slug node_pk=unit.pk %}?next={% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">
        {% trans "Start fresh" %}
      </a>
    {% endif %}
```

No CSS change: `.lesson-unit__head` is `display:flex; justify-content:space-between` with the title at `flex:1` and both actions at `flex:none`, so dropping the third child leaves title + pill correctly placed at both viewports.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest courses/tests/test_reset_controls.py -v
```

Expected: all 7 PASS (4 above + the 3 pre-existing outline/editor tests, which are untouched by this change).

- [ ] **Step 7: Falsify each guard and record the observed RED**

Revert each mutation before the next.

| Test | Mutation (literal) | Notes |
|---|---|---|
| `..._hides_the_reset_link_...` | `content_type__model__in=state_svc.stateful_element_model_names() + ("textelement",)` | Fires this test alone. **Widen at C2's call site, not C1's union** — widening C1 would co-fire Task 1's derivation test. |
| `..._for_an_element_nested_in_a_tab` | add `parent__isnull=True,` to C2's `.filter(...)` | Fires alone |
| `..._links_to_the_reset_interstitial` | none needed | Its Step-1 pass → Step-3 behaviour change IS the signal |

The fourth test in this task, `..._on_a_question_only_unit`, is falsified in **Task 3 Step 4** — its
mutation co-fires a test that does not exist until then, so it cannot be honestly performed here.

- [ ] **Step 8: Lint and commit**

This task changes what **every** lesson unit page renders, so it gets a full-suite gate before its
commit rather than deferring to Task 6 — a red surfacing three commits later is far harder to attribute.

```bash
uv run pytest -n auto
uv run ruff check --fix courses/views.py courses/tests/test_reset_controls.py
uv run ruff check courses/views.py courses/tests/test_reset_controls.py
uv run ruff format --check courses/views.py courses/tests/test_reset_controls.py
uv run python manage.py check
git add courses/views.py templates/courses/_lesson_article.html courses/tests/test_reset_controls.py
git commit -m "feat(courses): show Start fresh only on units that can hold practice state"
```

Expected: `pytest` exits 0. If any test outside `test_reset_controls.py` reds on a lesson render, this
commit is the cause — fix it here rather than carrying it forward.

---

### Task 3: The subtle render-path guards (tests 5-7)

**Files:**
- Test: `courses/tests/test_reset_controls.py` (append three more tests)

**Interfaces:**
- Consumes: `has_stateful_elements` from Task 2; `state.stateful_element_model_names` from Task 1 (monkeypatched by path).
- Produces: nothing consumed downstream.

These three are separated from Task 2 because each has a fixture requirement that, if missed, makes its falsification silently GREEN — they deserve their own review gate.

- [ ] **Step 1: Write the three failing tests**

Append to `courses/tests/test_reset_controls.py`. **Replace the import block again** with this merged, sorted version (three names added to Task 2's block):

```python
import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Element
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import ShortTextQuestionElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import UnitProgress
from courses.models import VideoElement
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user
```

```python
def test_reset_link_survives_the_no_js_check_answer_rerender(client):
    """The flag must reach the POST re-render path, not just the GET.

    A missing context variable renders as FALSE in Django with no error, so a future
    render site built with a hand-assembled context would drop the link silently. Only
    a test catches that.
    """
    course, unit = make_course_with_unit()
    q = ShortTextQuestionElement.objects.create(stem="Q", accepted="x")
    q_row = add_element(unit, q)
    # A MarkDoneElement beside the question so Task 2's question-only falsification
    # (restricting the filter to the validator half) does NOT co-fire this test.
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)

    # No X-Requested-With header -> _wants_fragment is False -> the full-page re-render
    # branch. The answer must be NON-EMPTY: an empty one takes the clear branch instead
    # of the store branch, exercising a different path while still returning 200.
    r = client.post(
        reverse("courses:check_answer", args=[course.slug, unit.pk, q_row.pk]),
        {"answer": "x"},
    )
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_views_calls_the_state_helper_rather_than_an_inlined_list(client, monkeypatch):
    """Proves the C1 -> C2 seam is live.

    Every other test here stays green if build_lesson_context hand-inlines the 18
    names, because the inlined list would be correct today. The drift shows up only
    when a 19th type ships: the derivation test goes RED, the author updates both it
    and state.py, and a stale list in views.py silently keeps the new type hidden.
    """
    from courses import state

    monkeypatch.setattr(
        state, "stateful_element_model_names", lambda: ("textelement",)
    )
    course, unit = make_course_with_unit()
    add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    _login(client, course)

    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    # A text-only unit now matches, because the helper says textelement is stateful.
    assert _reset_url(course, unit) in r.content.decode()


def test_an_orphaned_blob_does_not_bring_the_reset_link_back(client):
    """Pins the accepted cost of D1, in BOTH directions.

    Deleting a unit's last state-bearing element strands the student's stored blob:
    the unit page no longer offers to clear it (the outline's container/course resets
    still do). That is deliberate -- capability, not stored state. The union rule
    (`has_stateful_elements or bool(element_state)`) would cover this case at zero
    query cost and is the documented first thing to reach for if it ever matters; this
    test exists so adopting it is a decision rather than an accident.
    """
    course, unit = make_course_with_unit()
    # The SURVIVOR is a VideoElement, not a TextElement: the spec's scenario is an
    # author deleting the last STATEFUL element from a unit that still holds content,
    # and a video keeps Task 2's "textelement" falsification from firing this test.
    add_element(unit, VideoElement.objects.create(url="https://example.com/embed/x"))
    md = MarkDoneElement.objects.create(prompt="P")
    md_row = add_element(unit, md)
    item = MarkDoneItem.objects.create(element=md, content="a")

    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    # STR key, DICT value, and an ENROLLED student: build_lesson_context drops every
    # non-dict value and every non-int-coercible key, and never populates state at all
    # without a UnitProgress row. Get any of that wrong and the falsification below
    # silently passes without ever having fired.
    UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={str(md_row.pk): {"items": [item.pk]}},
    )
    md.delete()  # cascades the join row; the blob survives
    client.force_login(student)

    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert UnitProgress.objects.get(student=student, unit=unit).element_state != {}
    assert _reset_url(course, unit) not in r.content.decode()
```

- [ ] **Step 2: Run the tests — expect PASS, not RED**

```bash
uv run pytest courses/tests/test_reset_controls.py -v
```

Expected: all 10 PASS.

**This task has no RED phase, deliberately.** Task 2 already shipped the flag, the template gate and
the `state_svc` call, so all three of these tests describe behaviour that is already correct: the no-JS
re-render already carries `has_stateful_elements` (it goes through `full_lesson_render_context`), the
monkeypatch already binds because C2 calls through the module attribute, and the orphaned-blob unit
already renders no link. They are **characterization guards** over shipped behaviour — their entire
proof of worth is the falsification in Step 3. A test that passes here has demonstrated nothing yet.

- [ ] **Step 3: Falsify each guard and record the observed RED→GREEN**

Navigate by the quoted code, not the line number — Task 2 shifted every `views.py` anchor down by ~11
lines. After each mutation: observe RED, revert, **re-run and confirm GREEN**, then move on.

| Test | Mutation | Must go RED |
|---|---|---|
| `..._no_js_check_answer_rerender` | in `check_answer`'s no-JS branch, at the line `ctx = full_lesson_render_context(node, request.user)`, add `ctx.pop("has_stateful_elements")` immediately after it. **Do not** substitute a sparse hand-built dict — that also breaks `tests/test_questions_consumption.py` and `tests/test_unit_nav_render.py`. | this test alone |
| `..._calls_the_state_helper_...` | replace C2's `state_svc.stateful_element_model_names()` with a literal tuple of the 18 names | this test alone |
| `..._orphaned_blob_...` | in `build_lesson_context`'s returned dict, change the entry to `"has_stateful_elements": has_stateful_elements or bool(state),`. The local is named **`state`**, not `element_state`, and it is assigned *after* C2's line — so applying the OR at C2 itself raises `UnboundLocalError` on every lesson render and reds the whole suite instead of this test. | this test alone |
| **`..._on_a_question_only_unit`** (deferred from Task 2) | intersect C2's name list with `state.VALIDATORS`, e.g. `content_type__model__in=tuple(n for n in state_svc.stateful_element_model_names() if n in state.VALIDATORS)` | **two** tests: the question-only test **and** `..._calls_the_state_helper_...`. The co-fire is unavoidable and expected — that test monkeypatches the helper to return `"textelement"`, which any validator-half intersection filters straight back out. Record both REDs. |

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check --fix courses/tests/test_reset_controls.py
uv run ruff check courses/tests/test_reset_controls.py
uv run ruff format --check courses/tests/test_reset_controls.py
git add courses/tests/test_reset_controls.py
git commit -m "test(courses): pin the render path, the state-helper seam, and the orphaned-blob decision"
```

---

### Task 4: The write-route contract (spec C4) + test 10

**Files:**
- Modify: `courses/models.py` (comment at `UnitProgress.element_state`, `:2340`)
- Modify: `courses/views.py` (comment beside `progress_reset`'s `rows.update`, `:559`)
- Create: `tests/test_element_state_write_routes.py`

**Interfaces:**
- Consumes: `courses.state.stateful_element_model_names` (named in the comments only).
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing test**

Create `tests/test_element_state_write_routes.py`:

```python
"""Guard: the set of code paths that WRITE UnitProgress.element_state.

courses.state.stateful_element_model_names() enumerates the element types whose
practice state can be cleared from the unit page, and it is derived from exactly two
write routes (state.VALIDATORS and QuestionElement.RESTORABLE_IN_LESSON). A THIRD
route would ship a state-bearing type with no reset affordance -- silently.

This counts WRITES, not save_element_state() calls, because a direct write is the
house style here: progress_reset does `rows.update(element_state={})`, and migration
0050 did `up.element_state = ...`. A third route of that shape would never touch the
helper.
"""

import re
from pathlib import Path

from django.apps import apps

ROOT = Path(__file__).resolve().parent.parent

# Keyed on the surrounding OPERATION, because the confounders are textually adjacent:
# `rows.update(element_state={})` is a write but `rows.exclude(element_state={})` is a
# read, and any token keyed on `element_state=` alone matches both.
WRITE = re.compile(
    r"\.update\(\s*element_state=|element_state\.pop\(|element_state\[[^\]]*\]\s*="
    r"|\.element_state\s*=(?!=)"
)

# BLIND SPOTS, stated honestly: this catches .update(), .pop(), subscript assignment
# and attribute assignment. It does NOT catch setattr(), .bulk_update(), an
# F-expression, or a write spelled through a local alias. A tripwire, not a proof.

EXPECTED_WRITE_FILES = {"courses/views.py"}
EXPECTED_WRITE_COUNT = 3  # views.py: progress_reset's update, and the helper's pop + subscript assign


def _first_party_roots():
    """Every in-tree Python root: the 9 first-party apps, plus config/, scripts/, manage.py.

    Filters app configs by `path.parent == ROOT` -- NOT "path is under ROOT". The
    virtualenv lives INSIDE the checkout (.venv/), so "under ROOT" keeps every
    third-party app config and drags site-packages into the walk.
    """
    roots = []
    for cfg in apps.get_app_configs():
        path = Path(cfg.path).resolve()
        if path.parent != ROOT:
            continue
        if any(p in {".venv", "site-packages", "node_modules"} for p in path.parts):
            continue
        roots.append(path)
    return roots


def _source_files():
    for root in _first_party_roots() + [ROOT / "config", ROOT / "scripts"]:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if "migrations" in parts or "tests" in parts:
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            yield path
    yield ROOT / "manage.py"


def test_the_first_party_app_set_is_what_we_think_it_is():
    # If a tenth app ships, this guard must be re-read rather than silently skipping it.
    assert {p.name for p in _first_party_roots()} == {
        "core",
        "accounts",
        "institution",
        "courses",
        "grouping",
        "notes",
        "notifications",
        "tags",
        "integrations",
    }


def test_element_state_write_routes_are_unchanged():
    hits = []
    for path in _source_files():
        for _ in WRITE.finditer(path.read_text(encoding="utf-8")):
            # as_posix(): this is a Windows box, so str() yields backslashes and the
            # comparison would fail for a reason unrelated to the invariant.
            hits.append(path.relative_to(ROOT).as_posix())

    assert len(hits) == EXPECTED_WRITE_COUNT and set(hits) == EXPECTED_WRITE_FILES, (
        f"element_state write routes changed: found {len(hits)} in {sorted(set(hits))}, "
        f"expected {EXPECTED_WRITE_COUNT} in {sorted(EXPECTED_WRITE_FILES)}. "
        "A NEW WRITE ROUTE into UnitProgress.element_state must extend "
        "courses.state.stateful_element_model_names() in lockstep -- otherwise whatever "
        "it persists becomes unresettable from the unit page. Read that contract before "
        "bumping this number."
    )
```

- [ ] **Step 2: Run the test to verify it passes, then falsify it**

This guard describes the tree as it already is, so it should be GREEN immediately — which means running it proves nothing until it is falsified.

```bash
uv run pytest tests/test_element_state_write_routes.py -v
```

Expected: PASS (2 tests).

Now falsify. Add a fourth write to `courses/views.py`, at **function-level indentation (four spaces)
immediately above `progress_reset`'s final `return render(request, "courses/progress_reset_confirm.html", …)`**
— not above the earlier `return redirect(safe_next or fallback)`, which sits inside the
`if request.method == "POST":` block at eight spaces and would make this snippet an `IndentationError`
rather than a clean RED:

```python
    _throwaway = UnitProgress.objects.first()
    if _throwaway:
        _throwaway.element_state = {}
```

```bash
uv run pytest tests/test_element_state_write_routes.py -v
```

Expected: FAIL, message naming 4 hits. **Revert the mutation.** Also falsify the app-set guard by adding a bogus name to the expected set and confirming RED, then revert.

- [ ] **Step 3: Add the lockstep comments**

In `courses/models.py`, `UnitProgress.element_state` **already carries a three-line comment**
("Per-student practice state, keyed by Element (join-row) pk… Reset (progress_reset) clears this and
nothing else."). **Keep it** and append the contract note beneath it, so the field reads:

```python
    # Per-student practice state, keyed by Element (join-row) pk:
    # {"<Element.pk>": {...per-type blob}}. Personal, ungraded, invisible to
    # analytics. Reset (progress_reset) clears this and nothing else.
    # WRITE ROUTES INTO THIS FIELD ARE A CONTRACT. courses.state.stateful_element_model_names()
    # enumerates the element types whose state the unit page offers to clear, derived from
    # state.VALIDATORS + QuestionElement.RESTORABLE_IN_LESSON. A new write route here must
    # extend that function in lockstep, or whatever it stores becomes unresettable from the
    # unit page. Guarded by tests/test_element_state_write_routes.py.
    element_state = models.JSONField(default=dict)
```

In `courses/views.py`, above `rows.update(element_state={})` in `progress_reset` (`:559`), add:

```python
        # A DIRECT write, bypassing save_element_state -- the house style, and the
        # reason the lockstep contract lives on the field itself (see models.py).
```

**Neither comment may contain the literal `.element_state =`** — that string is one of the matcher's four alternations and would move the expected count in this very commit.

- [ ] **Step 4: Re-run the guard**

```bash
uv run pytest tests/test_element_state_write_routes.py -v
```

Expected: PASS, still 3 hits — confirming the comments did not trip the matcher.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tests/test_element_state_write_routes.py courses/models.py courses/views.py
uv run ruff format --check tests/test_element_state_write_routes.py courses/models.py courses/views.py
uv run python manage.py makemigrations --check
git add tests/test_element_state_write_routes.py courses/models.py courses/views.py
git commit -m "test: pin the element_state write routes; document the lockstep contract"
```

`makemigrations --check` must report no changes — a comment above a field is not a schema change.

---

### Task 5: Keep the e2e head-layout module honest

**Files:**
- Modify: `tests/test_e2e_unit_head_layout.py` (`_seed` at `:42-60`, `MEASURE` at `:63-78`, both tests)

**Interfaces:**
- Consumes: `has_stateful_elements` from Task 2.
- Produces: nothing.

`_seed` creates a unit with a single `TextElement`, so after Task 2 the reset link disappears from that page. Both tests would still pass — silently — while no longer guarding the three-item row the module exists for.

- [ ] **Step 1: Add a stateful element to `_seed`**

In `tests/test_e2e_unit_head_layout.py`, add to the imports inside `_seed`:

```python
    from courses.models import MarkDoneElement
```

and after the existing `Element.objects.create(...)` for the `TextElement` (`:57-59`), add:

```python
    # KEEPS THE "Start fresh" LINK RENDERED. The link is gated on the unit containing a
    # state-bearing element type; without this row the head row drops to two children and
    # this module silently stops guarding the crowded three-item case it exists for.
    # MarkDone over a question: no child rows, no answer setup, and markdone.js's boot
    # pass is read-only (it POSTs only on click), so it adds no traffic to a layout test.
    Element.objects.create(
        unit=unit, content_object=MarkDoneElement.objects.create(prompt="P")
    )
```

Keep the existing `TextElement` row — both tests share `_seed`, and the text body is what gives the page realistic height.

- [ ] **Step 2: Measure the third child**

Replace the `MEASURE` body's `return` block so it also reports the reset link:

```javascript
() => {
  const head = document.querySelector('.lesson-unit__head');
  const title = head.querySelector('.lesson-unit__title');
  const done = head.querySelector('.unit-done');
  const reset = head.querySelector('.lesson-unit__reset');
  const t = title.getBoundingClientRect();
  const d = done.getBoundingClientRect();
  const r = reset ? reset.getBoundingClientRect() : null;
  return {
    text_overflow: title.scrollWidth - title.clientWidth,
    title_bottom: Math.round(t.bottom),
    title_width: Math.round(t.width),
    done_top: Math.round(d.top),
    done_left: Math.round(d.left),
    has_reset: !!reset,
    reset_top: r ? Math.round(r.top) : null,
    reset_left: r ? Math.round(r.left) : null,
  };
}
```

Each test gets its **own** assertion, mirroring the `done_top` comparison it already makes — the two
tests guard opposite layouts, so one shared assertion cannot serve both.

In `test_long_title_does_not_overflow_under_the_action_buttons` (phone), after the existing
`assert m["done_top"] >= m["title_bottom"] - 1` block:

```python
    assert m["has_reset"], "the reset link vanished — _seed's MarkDoneElement is what keeps it"
    assert m["reset_top"] >= m["title_bottom"] - 1, (
        f"the reset link still shares the title's line at {PHONE['width']}px "
        f"(title bottom {m['title_bottom']}, reset top {m['reset_top']})"
    )
```

In `test_desktop_keeps_the_actions_beside_the_title`, after the existing
`assert m["done_top"] < m["title_bottom"]` block:

```python
    assert m["has_reset"], "the reset link vanished — _seed's MarkDoneElement is what keeps it"
    assert m["reset_top"] < m["title_bottom"], (
        "on desktop the reset link should still sit on the title's line"
    )
```

Do **not** compare `reset_left` against `title_width`: one is a viewport-absolute x-coordinate and the
other a width, so the comparison is a category error that happens to be true whenever the page has any
left padding — it would pass unconditionally on desktop while asserting nothing.

- [ ] **Step 3: Run the e2e in the foreground**

```bash
uv run pytest -m e2e tests/test_e2e_unit_head_layout.py -v
```

**The `-m e2e` is mandatory** — `addopts` is `-q -m 'not e2e'`, so without it pytest deselects both tests and exits 0, a green run that executed nothing. Expected: **2 passed**. Report the collected/passed count, not "green". Run in the foreground: backgrounded `-m e2e` runs have spawned runaway browsers here.

- [ ] **Step 4: Commit**

```bash
uv run ruff check tests/test_e2e_unit_head_layout.py
uv run ruff format --check tests/test_e2e_unit_head_layout.py
git add tests/test_e2e_unit_head_layout.py
git commit -m "test(e2e): keep the three-item unit head row measured after the reset gate"
```

---

### Task 6: Full verification (spec Definition of done)

**Files:** none modified.

- [ ] **Step 1: Full non-e2e suite**

```bash
uv run pytest -n auto
```

Expected: exit code 0. The verdict line does not survive a pipe here — check `$?` or grep for `FAILED`.

- [ ] **Step 2: The query-count test, in isolation as well**

```bash
uv run pytest tests/test_html_element.py::test_lesson_html_render_query_count_invariant -v
```

Expected: **1 passed**. Report the count — the point of the node id is that a mis-selection shows up as
`0 selected` rather than a green run of the wrong tests. (`-k has_html` looks right and is **wrong**: it
selects `test_course_form_has_html_css_js_fields`, `test_lesson_sets_has_html` and
`test_lesson_loads_html_js_only_when_has_html` — three tests, none of them this invariant.)

This is the test C2's rejected `get_for_model` alternative would have broken via cold-cache ContentType
SELECTs, and it only reds in isolated runs — `-n auto` alone would not surface it.

- [ ] **Step 3: e2e**

```bash
uv run pytest -m e2e tests/test_e2e_unit_head_layout.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Lint, migrations, checks**

```bash
uv run ruff check
uv run ruff format --check
uv run python manage.py makemigrations --check
uv run python manage.py check
```

Expected: all clean, no migrations generated.

- [ ] **Step 5: Look at the two-child head row**

This feature's entire visible output is a head row with its third child removed, and nothing above ever renders it — the e2e deliberately restores the three-child row, and the unit tests only grep HTML for a URL string.

Create a **throwaway** e2e module at `tests/test_tmp_head_shot.py` (deleted in Step 6 — it must never be
committed):

```python
import pytest

from tests.factories import add_element
from tests.test_e2e_unit_head_layout import _login

pytestmark = pytest.mark.e2e

SHOTS = "C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/e2e68207-43a4-4129-a443-c225117f2d91/scratchpad"


@pytest.mark.django_db(transaction=True)
def test_capture_two_child_head_row(page, live_server):
    from courses.models import Enrollment
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.test_e2e_unit_head_layout import LONG_TITLE
    from tests.factories import make_verified_user
    from tests.factories import TEST_PASSWORD

    student = make_verified_user(
        username="shot", email="shot@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug="shot-course", owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title=LONG_TITLE
    )
    # NO stateful element: this is the two-child head row the feature ships.
    add_element(unit, TextElement.objects.create(body="<p>Treść.</p>"))

    _login(page, live_server, "shot")
    for w, h, label in [(1280, 900, "desktop"), (390, 780, "phone")]:
        page.set_viewport_size({"width": w, "height": h})
        for theme in ["light", "dark"]:
            page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
            page.wait_for_selector(".lesson-unit__head")
            # The app's theme toggle stamps data-theme on <html>; setting the
            # attribute is what actually flips the token set.
            page.evaluate(
                "t => document.documentElement.setAttribute('data-theme', t)", theme
            )
            page.wait_for_timeout(150)
            assert page.locator(".lesson-unit__reset").count() == 0
            page.locator(".lesson-unit__head").screenshot(
                path=f"{SHOTS}/head-{label}-{theme}.png"
            )
```

Check `_login`'s signature and `LONG_TITLE`/`TEST_PASSWORD`'s import locations against
`tests/test_e2e_unit_head_layout.py` before running, and adjust if they differ.

Run it in the **foreground**, with the mandatory marker:

```bash
uv run pytest -m e2e tests/test_tmp_head_shot.py -v
```

Expected: 1 passed, and four PNGs in the scratchpad. Then **read all four** with the Read tool and
confirm:

- desktop: the "Mark as done" pill sits hard right, the title fills the remaining width;
- phone: the title takes its own row and the pill sits below it, left-aligned;
- neither theme shows a stray gap, a stretched pill, or a title colliding with the pill.

If any of that reads as broken rather than merely different, C3's "no CSS change is required" claim is wrong and must be revisited before merge. Attach the four screenshots to the completion notes.

- [ ] **Step 6: Delete the throwaway module and report**

```bash
rm tests/test_tmp_head_shot.py
git status --porcelain
```

Expected: `git status` shows no untracked `tests/test_tmp_head_shot.py`. The screenshots stay in the
scratchpad; they are never committed either.

Summarize: the full-suite result, the query-count test's `1 passed`, the e2e collected/passed count (2),
the screenshot verdict, and a falsification table covering **tests 2-10** — each with its observed
RED→GREEN pair. Test 1 has no falsification by design; report instead that it passed before Task 2 and
required a stateful fixture afterwards, which is its signal. Do not claim completion without that table.

---

## Self-Review

**Spec coverage.** C1 → Task 1. C2 → Task 2 Step 4. C3 → Task 2 Step 5. C4 → Task 4 Step 3. Tests 1-4 → Task 2. Tests 5-7 → Task 3. Tests 8-9 → Task 1. Test 10 → Task 4. e2e `_seed`/`MEASURE` → Task 5. DoD incl. the screenshot item and the isolated query-count run → Task 6. The non-goals (outline links, `lesson_unit.html:77`, `progress_reset`, quiz units, migrations/strings/CSS) are carried as Global Constraints and are touched by no task.

**Placeholders.** None: every code step carries the literal code, every command its expected output, every guard its named mutation.

**Type consistency.** `stateful_element_model_names()` returns `tuple[str, ...]` in Task 1 and is called with no arguments in Task 2 (production) and Task 3 (monkeypatched to `lambda: ("textelement",)`). The context key is `has_stateful_elements` in Tasks 2, 3 and 5. The helper `_reset_url(course, unit)` is defined once in Task 2 and reused in Task 3.
