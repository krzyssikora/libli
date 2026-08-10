# LaTeX in unit titles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `ContentNode.title` containing `\(...\)` or `\[...\]` typesets with KaTeX on every server-rendered display surface, and reads as clean plain text in `title=` attributes, `<title>` and screen-reader-only text.

**Architecture:** Three independent moving parts. (1) A `data-math-title` attribute marks every read-only display of a node title, and `math.js`'s `renderInlineText` selector list gains exactly one entry, `[data-math-title]`. (2) The existing server-side `has_math` gate is widened with two helpers — `titles_have_math(titles)` and `tree_titles_have_math(tree)` — and two shared asset partials replace the five duplicated KaTeX script blocks. (3) CSS neutralises KaTeX's `1.21em` sizing and its `.katex-display` block behaviour inside titles, with per-surface line-height clamps for compact chrome.

**Tech Stack:** Django 5 templates + views, KaTeX (vendored) + `auto-render.min.js`, plain CSS with design tokens, pytest / pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-10-latex-in-unit-titles-design.md`. Read it before starting — every section reference below (`§1`, `§2`, …) points into it.

---

## Global Constraints

- **Test DB container first.** `docker compose -f docker-compose.test.yml up -d` must be running before **any** pytest invocation in this repo. If it is down the suite looks hung for ~4m21s.
- **Tooling is behind `uv`.** `pytest`, `ruff` and `python` are not on PATH. Always `uv run pytest …`, `uv run ruff …`.
- **e2e needs `-m e2e`.** `addopts = "-q -m 'not e2e'"` in `pyproject.toml`, so an e2e file run without `-m e2e` silently deselects everything and exits 5.
- **Falsify every test before trusting it.** A test must be observed RED against a mutant chosen from the *failure mode*, not from the assertion. Every task below names its mutant explicitly. Revert the mutant before committing.
- **Scope test runs narrowly.** Run only the files a task touches. A whole-repo sweep is a branch gate (Task 11), never a per-task step.
- **Never `git add -A` / `git add .`.** Every commit lists explicit paths.
- **Delimiters are exactly four two-character sequences:** `\(`, `\)`, `\[`, `\]`. Never re-implement the test for them — always delegate to `courses.htmlsandbox.has_math_delimiters`.
- **Every KaTeX-family `<script>` carries `defer`.** Source order only guarantees execution order *among* `defer` scripts (`editor.html:173-175` records this). A non-deferred `math.js` runs during parsing and typesets nothing below its own tag — a failure that looks exactly like a missing marker.
- **Script order inside the JS partial is load-bearing and fixed:** `katex.min.js` → `contrib/auto-render.min.js` → `math_reflow.js` → `text_colour.js` → `math.js`. `math_reflow.js` pre-hooks `window.renderMathInElement` and `katex.render` with a single install attempt and no deferred retry; `text_colour.js` post-hooks the same two globals; `math.js` runs the document pass and must be last.
- **`ruff` config:** `force-single-line = true` for imports; `select = ["E", "F", "I", "UP", "B", "S"]`. Run `uv run ruff check --fix` and `uv run ruff format` on touched Python before each commit.
- **Course titles are out of scope.** `Course.title` is a different field on a different model. Never mark or filter it.
- **Path C (edit buffers) stays disjoint.** `manage/editor/_unit_settings.html:12`, `manage/_rename_result.html:7` and `manage/_tree_node.html:49` must receive the title with **no** marker and **no** filter — typesetting or stripping any of them corrupts what the author saves.
- **No builder templates change in this diff.** §5 defers every builder surface. Note this covers two *different* kinds of site in the same file: `_tree_node.html:49` is the Path-C edit buffer above (permanently unfiltered, even after the deferred work lands), while `:50`'s `title="{{ node.title }}"` is an ordinary plain-text tooltip that *would* take `|strip_math_delimiters` — it is untouched here only because the builder is out of scope, not because it is an edit buffer. The same distinction applies to `_tree_toggle.html:6,7`.

---

## File Structure

**New files**

| File | Responsibility |
| --- | --- |
| `templates/courses/_katex_css.html` | The `katex.min.css` `<link>`. Self-loads `static`. Unconditional — callers own the `{% if has_math %}`. |
| `templates/courses/_katex_js.html` | The five KaTeX-family `<script defer>` tags in fixed order. Self-loads `static`. |
| `tests/helpers_title_math.py` | Shared fixtures: the maths-title course builders and the bare-partial render helper. Not collected (no `test_` prefix). |
| `tests/test_title_math_filter.py` | `strip_math_delimiters` unit tests + the eleven per-(file, line) wiring assertions. |
| `tests/test_title_math_helpers.py` | `titles_have_math` / `tree_titles_have_math` unit tests, including the delegation pins. |
| `tests/test_title_math_assets.py` | Partial extraction, defect 3 (`math.js` presence + order), and the per-page gate assertions. |
| `tests/test_title_math_markers.py` | `data-math-title` marker coverage: present at every display site, absent at every excluded site. |
| `tests/test_title_math_css.py` | Source assertions on the CSS normalisation rules. |
| `tests/test_e2e_title_math.py` | Playwright: the next-unit-title-only case, plus the render-cost measurement. |

**Modified files**

| File | Change |
| --- | --- |
| `courses/templatetags/courses_extras.py` | `+ strip_math_delimiters` filter. |
| `courses/htmlsandbox.py` | `+ titles_have_math(titles)`, beside `has_math_delimiters`. |
| `courses/rollups.py` | `+ tree_titles_have_math(tree)`, beside `build_outline`. |
| `courses/static/courses/js/math.js` | `renderInlineText` selector gains `[data-math-title]`. |
| `courses/views.py` | `+ _widen_has_math_for_titles` helper; widen `has_math` at **six** render sites (four in Task 6, two in Task 7). |
| `courses/views_analytics.py` | `+ has_math` on the matrix and breakdown pages. |
| `courses/views_review.py` | Widen `_review_context`; `+ has_math` on the review queue. |
| `notes/views.py`, `tags/views.py` | `+ has_math` on the notes page, the tags hub (two sites) and the tags panel. |
| `core/static/core/css/app.css` | Global `[data-math-title]` normalisation + the analytics clamp. |
| `courses/static/courses/css/courses.css` | The unit-chrome clamp. |
| 22 templates | Markers, filter applications, `{% load %}` additions, partial includes, new `extra_css`/`extra_js` blocks. |

---

## Task 1: The `strip_math_delimiters` filter

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (append at end of file)
- Test: `tests/test_title_math_filter.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `strip_math_delimiters(value) -> str` — a Django template filter registered on the `courses_extras` library. Always returns a **new plain `str`**, never a `SafeString`. Coerces any input (`None`, lazy proxy, `int`) rather than raising.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_title_math_filter.py`:

```python
"""strip_math_delimiters: the plain-text half of LaTeX-in-titles (spec §4).

Unit tests here; the eleven per-(file, line) wiring assertions live in Task 2
of the same file.
"""

from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy

from courses.templatetags.courses_extras import strip_math_delimiters


def test_strips_an_inline_pair():
    assert strip_math_delimiters(r"\(x^2\)") == "x^2"


def test_strips_a_display_pair():
    assert strip_math_delimiters(r"\[a\]") == "a"


def test_strips_both_kinds_in_one_title():
    assert strip_math_delimiters(r"Solve \(x\) then \[y\]") == "Solve x then y"


def test_a_title_with_no_delimiters_keeps_its_content():
    assert strip_math_delimiters("Rozwiaz rownanie") == "Rozwiaz rownanie"


def test_an_unmatched_opener_is_removed_too():
    # Naive left-to-right replacement, REGARDLESS of pairing (spec §4).
    assert strip_math_delimiters(r"\(x") == "x"


def test_a_stray_closer_is_removed_too():
    assert strip_math_delimiters(r"x\)") == "x"


def test_none_renders_as_the_string_none():
    # Matches Django's own default rendering of None in a template. A filter
    # that raised would take down the whole page render (spec §Error handling).
    assert strip_math_delimiters(None) == "None"


def test_a_lazy_proxy_resolves_to_its_text():
    assert strip_math_delimiters(gettext_lazy("Review")) == "Review"


def test_an_int_renders_as_its_digits():
    assert strip_math_delimiters(7) == "7"


def test_returns_a_plain_str_not_safestring_when_delimiters_present():
    out = strip_math_delimiters(mark_safe(r"\(x\)"))
    assert type(out) is str


def test_returns_a_plain_str_not_safestring_on_the_no_delimiter_path():
    """The tempting optimisation -- return the input untouched when it holds no
    delimiter -- would pass a SafeString straight through and silently lose
    autoescaping in a title= attribute. SafeString.__str__ returns self, so even
    a str() coercion does not strip the safe marker."""
    out = strip_math_delimiters(mark_safe("Plain title"))
    assert out == "Plain title"
    assert type(out) is str
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_title_math_filter.py -v
```

Expected: collection error — `ImportError: cannot import name 'strip_math_delimiters'`.

- [ ] **Step 3: Write the filter**

Append to `courses/templatetags/courses_extras.py` (after `quiz_answer_url`, at end of file):

```python
# The four two-character maths delimiter sequences. Kept as a module constant so
# the filter's behaviour is readable at a glance; the DETECTION side of the same
# question lives in courses.htmlsandbox.has_math_delimiters and must never be
# re-implemented -- see titles_have_math.
_MATH_DELIMS = ("\\(", "\\)", "\\[", "\\]")


@register.filter
def strip_math_delimiters(value):
    """Remove the four maths delimiter sequences for plain-text contexts.

    `title=` attributes, <title>, and screen-reader-only text cannot contain
    markup, so they can never typeset; leaving `\\(x^2\\)` in a tooltip beside a
    rendered heading reads as a bug (spec §4).

    Naive left-to-right replacement, REGARDLESS of pairing: `\\(x` yields `x`
    and a stray `\\)` is removed too. A literal escaped backslash (`\\\\(`) is out
    of scope -- it is treated as `\\` followed by `\\(`.

    ALWAYS returns a plain `str`, never a SafeString, INCLUDING the no-delimiter
    path: this filter sits on `title=` attributes, where silently passing a
    marked-safe value through would lose autoescaping and open an injection seam.

    WHERE THAT GUARANTEE ACTUALLY COMES FROM -- measured, not assumed. It is NOT
    the `"%s"` coercion: `"%s" % (SafeString("x"),)` returns a **SafeString**, and
    so does `str(SafeString("x"))` (SafeString.__str__ returns self). What drops
    the marker is `str.replace`, which for a non-exact str subclass returns an
    exact `str` even when nothing matched. The `"%s"` line exists only to accept
    a non-string (None, a gettext_lazy proxy, an int) instead of raising -- a
    template filter that raises takes down the whole page render.

    Because that makes the guarantee INCIDENTAL to the loop, the final coercion
    below is explicit: a future "fast path, return early when there is no
    delimiter" would otherwise silently reintroduce the SafeString leak while
    every other line still looked correct.
    """
    text = "%s" % (value,)
    for delim in _MATH_DELIMS:
        text = text.replace(delim, "")
    if type(text) is not str:  # a str SUBCLASS check, deliberately
        text = str.__str__(text)  # copies a str subclass to an exact str
    return text
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_title_math_filter.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Falsify — observe RED against the failure-mode mutant**

The failure mode is *"the no-delimiter fast path leaks a SafeString"*. Temporarily insert as the first line of the filter body:

```python
    if not any(d in str(value) for d in _MATH_DELIMS):
        return value          # MUTANT
```

Run: `uv run pytest tests/test_title_math_filter.py -v`

Expected: **three** FAIL. `test_returns_a_plain_str_not_safestring_on_the_no_delimiter_path` (`type(out)` is `SafeString`) is the one the mutant targets; `test_none_renders_as_the_string_none` and `test_an_int_renders_as_its_digits` also go red, because the early return hands back the *original object* — `None` and `7`, not `"None"` and `"7"`. All three are expected.

Second mutant — the failure mode *"raises on a non-string"*: replace `text = "%s" % (value,)` with `text = value`. Expected: `test_none_renders_as_the_string_none` and `test_an_int_renders_as_its_digits` FAIL with `AttributeError`.

**`test_a_lazy_proxy_resolves_to_its_text` still PASSES under that mutant, and that is not a bug in the test** — Django's `lazy()` promotes every `str` method onto the `__proxy__` class, so `gettext_lazy("Review").replace("\\(", "")` returns the real `str` `'Review'`. Verified by running it. If you see that test green here, the mutant *was* applied; do not go hunting.

Third mutant, for the explicit coercion the docstring calls out: delete the `if type(text) is not str:` guard **and** add an early `if not any(d in text for d in _MATH_DELIMS): return text` immediately after the `"%s"` line. Expected: `test_returns_a_plain_str_not_safestring_on_the_no_delimiter_path` FAILS again — this is the exact "future fast path" regression the guard exists to stop.

Revert all three mutants.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --fix courses/templatetags/courses_extras.py tests/test_title_math_filter.py
uv run ruff format courses/templatetags/courses_extras.py tests/test_title_math_filter.py
uv run pytest tests/test_title_math_filter.py -v
git add courses/templatetags/courses_extras.py tests/test_title_math_filter.py
git commit -m "feat(courses): add strip_math_delimiters for plain-text title contexts"
```

---

## Task 2: Wire the filter into the eleven plain-text sites

**Files:**
- Modify: `templates/courses/_unit_tree_node.html:1,15,25`
- Modify: `templates/courses/_unit_crumbs.html:1,27,29,34`
- Modify: `templates/courses/_unit_footer.html:1,37`
- Modify: `templates/courses/lesson_unit.html:3`
- Modify: `templates/courses/quiz_unit.html:3`
- Modify: `templates/courses/quiz_results.html:3`
- Modify: `templates/courses/manage/editor/editor.html:2,3`
- Modify: `templates/courses/manage/review_submission.html:2,3`
- Create: `tests/helpers_title_math.py`
- Test: `tests/test_title_math_filter.py` (append)

**Interfaces:**
- Consumes: `strip_math_delimiters` from Task 1.
- Produces: `tests/helpers_title_math.py` exporting `MATHS_TITLE`, `MATHS_TITLE_STRIPPED`, `make_title_course(*, maths_on=...)`, `login_student(client, course, username=...)` — reused by Tasks 5–9 and 11.

**Why one assertion per (file, line) and not per spec-table row:** three rows cover several sites each. `_unit_tree_node.html:15` (unit label) and `:25` (group title) are independent interpolations, and the two "Browser tab" rows span five templates. A per-row test is satisfied by stripping at `:15` but not `:25`, or in `lesson_unit.html:3` but not `quiz_results.html:3` — exactly the wiring gap this task exists to close. Without it, an implementation that defines the filter, registers it, and wires it into **no** site at all passes Task 1 entirely green.

- [ ] **Step 1: Write the shared fixture helper**

Create `tests/helpers_title_math.py`:

```python
"""Shared fixtures for the LaTeX-in-titles tasks (spec 2026-08-10).

Not collected by pytest (no test_ prefix) -- imported by
test_title_math_filter / _markers / _assets and the e2e file.
"""

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login

# One inline pair and one display pair, plus prose around them, so a single
# fixture exercises both INLINE_DELIMS entries and the title-alone rule.
MATHS_TITLE = r"Rozwiaz \(x^2\) oraz \[y_3\]"
MATHS_TITLE_STRIPPED = "Rozwiaz x^2 oraz y_3"


def login_student(client, course, username="student"):
    """A verified, enrolled, logged-in student for `course`."""
    user = make_login(client, username)
    EnrollmentFactory(student=user, course=course)
    return user


def make_title_course(*, maths_on="none"):
    """A two-part course. Returns (course, viewed_unit, nodes) where `nodes` maps
    a name to its ContentNode.

    Shape (pre-order):
        part1  "Czesc pierwsza"
          unitA  <- the unit every view test opens
          unitB  <- unitA's `next`
        part2
          unitC

    `maths_on` places the ONLY maths title in the whole course:
      "none"   -- nothing carries maths (the negative-direction fixture)
      "unitA"  -- on the viewed unit itself
      "unitB"  -- on the viewed unit's `next` (the e2e / nav-button case)
      "far"    -- on unitC AND part2, i.e. several sections away from unitA,
                  with unitA, unitB, part1 and all their neighbours plain.
                  This is the TREE TRAP fixture: the whole course outline is in
                  unitA's DOM (build_unit_nav sets unit_nav["tree"] to it), so
                  unitA's page must still load KaTeX.
      "group"  -- on part2 only (a GROUP title, not a leaf) -- the analytics
                  expanded-group case, where a scan over matrix["columns"]
                  would silently miss it.
    """
    course = CourseFactory()
    part1 = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0,
        title="Czesc pierwsza",
    )
    part2 = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=1,
        title=MATHS_TITLE if maths_on in ("far", "group") else "Czesc druga",
    )
    unit_a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part1, order=0,
        obligatory=True,
        title=MATHS_TITLE if maths_on == "unitA" else "Lekcja pierwsza",
    )
    unit_b = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part1, order=1,
        obligatory=True,
        title=MATHS_TITLE if maths_on == "unitB" else "Lekcja druga",
    )
    unit_c = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part2, order=0,
        obligatory=True,
        title=MATHS_TITLE if maths_on == "far" else "Lekcja trzecia",
    )
    return course, unit_a, {
        "part1": part1, "part2": part2,
        "unitA": unit_a, "unitB": unit_b, "unitC": unit_c,
    }
```

- [ ] **Step 2: Write the failing wiring tests**

Append to `tests/test_title_math_filter.py`. **Everything this step adds — including the
imports the later code blocks use — goes into the file's single top-level import block**,
which means extending the one Task 1 wrote rather than starting a second block mid-file
(`ruff`'s `I` rule sorts per block and `force-single-line` is on, so a stray second block
invites churn, and the helpers below would transiently reference names imported further down).
**File layout, stated explicitly so the committed file matches this listing:** the imports and
`pytestmark` go **under the existing import block at the top**, and the helpers plus the new
tests are **appended at the end of the file**, after Task 1's eleven unit tests. The listing
below therefore shows them out of file order.

`pytestmark` is module-level and applies to every test in the file wherever it sits — including
Task 1's. That is harmless here and needs no per-test marking: `tests/conftest.py` already
declares an **autouse** `_enable_db_access(db)` fixture over the whole `tests/` subtree, so
every test in this directory has DB access and requires the running Postgres container
regardless. The mark is belt-and-braces, not a new cost.

The complete added import set, sorted as `ruff` will leave it:

```python
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.helpers_title_math import MATHS_TITLE
from tests.helpers_title_math import MATHS_TITLE_STRIPPED
from tests.helpers_title_math import login_student
from tests.helpers_title_math import make_title_course

pytestmark = pytest.mark.django_db


def _lesson_body(client, *, maths_on):
    course, unit, nodes = make_title_course(maths_on=maths_on)
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return client.get(url).content.decode(), course, unit, nodes


def _attr_values(html, selector, attr):
    return [
        el.get(attr, "")
        for el in BeautifulSoup(html, "html.parser").select(selector)
    ]


# --- (1) _unit_tree_node.html:15 -- the tree UNIT label tooltip ---------------
def test_tree_unit_label_tooltip_is_stripped(client):
    body, *_ = _lesson_body(client, maths_on="far")
    titles = _attr_values(body, "span.unit-tree__label", "title")
    assert MATHS_TITLE_STRIPPED in titles
    assert all("\\(" not in t for t in titles)


# --- (2) _unit_tree_node.html:25 -- the tree GROUP title tooltip --------------
def test_tree_group_title_tooltip_is_stripped(client):
    body, *_ = _lesson_body(client, maths_on="group")
    titles = _attr_values(body, "span.unit-tree__grouptitle", "title")
    assert MATHS_TITLE_STRIPPED in titles
    assert all("\\(" not in t for t in titles)


# --- (3) _unit_crumbs.html:34 -- the ancestor crumb <li title=> ---------------
def test_crumb_li_tooltip_is_stripped(client):
    course, unit, nodes = make_title_course(maths_on="none")
    nodes["part1"].title = MATHS_TITLE
    nodes["part1"].save(update_fields=["title"])
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    body = client.get(url).content.decode()
    titles = _attr_values(body, "li.unit-crumbs__item", "title")
    assert MATHS_TITLE_STRIPPED in titles
    assert all("\\(" not in t for t in titles)


# --- (4)+(5) _unit_crumbs.html:27 and :29 -- the collapsed crumb --------------
def _deep_course_with_maths_in_hidden_path():
    """>1 ancestor so the ellipsis crumb renders (it is gated on ancestor COUNT),
    with the maths title on an ancestor that hidden_path ACTUALLY CONTAINS.

    THE TRAP: `hidden_path` is `HIDDEN_PATH_SEP.join(a.title for a in
    ancestors[:-1])` (rollups.py:954) -- ALL BUT THE DEEPEST -- and `ancestors`
    already excludes the unit itself (_current_ancestors, rollups.py:878-879).
    For part1 -> chapter -> deep, `ancestors == [part1, chapter]` and
    `ancestors[:-1] == [part1]`. So the maths must go on **part1**; putting it on
    the chapter leaves hidden_path maths-free and both tests below fail no matter
    how correctly the filter is wired.
    """
    course, _unit, nodes = make_title_course(maths_on="none")
    part1 = nodes["part1"]
    part1.title = MATHS_TITLE          # ancestors[:-1] == [part1]
    part1.save(update_fields=["title"])
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part1, unit_type=None,
        order=0, title="Rozdzial zwykly",   # the DEEPEST ancestor: dropped by [:-1]
    )
    deep = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, order=0,
        obligatory=True, title="Lekcja gleboka",
    )
    return course, deep


def test_collapsed_crumb_tooltip_is_stripped(client):
    course, deep = _deep_course_with_maths_in_hidden_path()
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": deep.pk}
    )
    body = client.get(url).content.decode()
    titles = _attr_values(body, "li.unit-crumbs__item--ellipsis", "title")
    assert titles, "the collapsed crumb did not render"
    assert all("\\(" not in t for t in titles)
    assert any(MATHS_TITLE_STRIPPED in t for t in titles)


def test_collapsed_crumb_accessible_name_is_stripped(client):
    """The .visually-hidden span IS the collapsed crumb's accessible name. Without
    stripping, a maths ancestor is read aloud as "backslash paren x caret 2" on an
    otherwise fully typeset page."""
    course, deep = _deep_course_with_maths_in_hidden_path()
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": deep.pk}
    )
    body = client.get(url).content.decode()
    soup = BeautifulSoup(body, "html.parser")
    sr = soup.select("li.unit-crumbs__item--ellipsis span.visually-hidden")
    assert sr, "the collapsed crumb's SR-only name did not render"
    texts = [s.get_text() for s in sr]
    assert all("\\(" not in t for t in texts)
    assert any(MATHS_TITLE_STRIPPED in t for t in texts)


# --- (6) _unit_footer.html:37 -- the part-progress chip tooltip ---------------
def test_part_progress_chip_tooltip_is_stripped(client):
    course, _unit, nodes = make_title_course(maths_on="none")
    nodes["part1"].title = MATHS_TITLE
    nodes["part1"].save(update_fields=["title"])
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit",
        kwargs={"slug": course.slug, "node_pk": nodes["unitA"].pk},
    )
    body = client.get(url).content.decode()
    titles = _attr_values(body, "span.unit-foot__part", "title")
    assert titles, "the part chip did not render"
    assert all("\\(" not in t for t in titles)
    assert any(MATHS_TITLE_STRIPPED in t for t in titles)


# --- (7)-(11) the five <title> elements ---------------------------------------
def _head_title(html):
    return BeautifulSoup(html, "html.parser").select_one("title").get_text()


def test_lesson_unit_browser_tab_is_stripped(client):
    body, _c, _u, _n = _lesson_body(client, maths_on="unitA")
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)
```

Add the four remaining `<title>` assertions — `quiz_unit`, `quiz_results`, `editor`, `review_submission` — each driving its own view. Their imports are already in the consolidated block above; only the test bodies follow:

```python
def test_quiz_unit_browser_tab_is_stripped(client):
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    url = reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)


def _submitted_quiz(client, title):
    """A SUBMITTED quiz whose unit title is `title`, and its logged-in student."""
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=title,
    )
    student = login_student(client, course)
    QuizSubmission.objects.create(
        student=student, unit=quiz, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    return course, quiz


def test_quiz_results_browser_tab_is_stripped(client):
    course, quiz = _submitted_quiz(client, MATHS_TITLE)
    url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)


def test_editor_browser_tab_is_stripped(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=MATHS_TITLE,
    )
    url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)


def _review_url_with_unit_title(client, title):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem="<p>Explain plainly.</p>",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    return reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )


def test_review_submission_browser_tab_is_stripped(client):
    url = _review_url_with_unit_title(client, MATHS_TITLE)
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)
```

> **Two URL names, both verified against `courses/urls.py`:** the editor is
> `courses:manage_editor` and its node kwarg is **`pk`**, not `node_pk`
> (`courses/urls.py:245-249`). `courses:manage_review_submission` takes `slug` +
> `submission_pk` (`tests/test_review_views.py:144-147`). Do not invent
> `manage_unit_editor` — it does not exist.

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_filter.py -v
```

Expected: the eleven wiring tests FAIL (raw `\(` still present in every attribute and `<title>`); the eleven Task-1 unit tests still pass.

- [ ] **Step 4: Apply the filter at the eleven sites**

`templates/courses/_unit_tree_node.html` — line 1:

```
{% load i18n courses_extras %}
```

line 15 (`title=` only; the visible text keeps its raw delimiters for KaTeX):

```
      <span class="unit-tree__label" title="{{ item.node.title|strip_math_delimiters }}">{{ item.node.title }}</span>
```

line 25:

```
          <span class="unit-tree__grouptitle" lang="{{ course.language }}" title="{{ item.node.title|strip_math_delimiters }}">{{ item.node.title }}</span>
```

`templates/courses/_unit_crumbs.html` — line 1 becomes:

```
{% load i18n courses_extras %}{% get_current_language as LANGUAGE_CODE %}
```

line 27:

```
          lang="{{ course.language }}" title="{{ unit_nav.hidden_path|strip_math_delimiters }}">
```

line 29:

```
        <span class="unit-crumbs__label">…<span class="visually-hidden">{{ unit_nav.hidden_path|strip_math_delimiters }}</span></span>
```

line 34:

```
          role="listitem" lang="{{ course.language }}" title="{{ a.title|strip_math_delimiters }}">
```

`templates/courses/_unit_footer.html` — line 1:

```
{% load i18n courses_extras %}
```

line 37:

```
        <span class="unit-foot__part" title="{{ unit_nav.part_progress.title|strip_math_delimiters }}">
```

`templates/courses/lesson_unit.html:3`, `templates/courses/quiz_unit.html:3` — both already `{% load i18n static courses_extras %}` at line 2, so only line 3 changes:

```
{% block head_title %}{{ unit.title|strip_math_delimiters }} — libli{% endblock %}
```

`templates/courses/quiz_results.html:3`:

```
{% block head_title %}{{ unit.title|strip_math_delimiters }} — {% trans "results" %} — libli{% endblock %}
```

`templates/courses/manage/editor/editor.html` — line 2 gains the library, line 3 the filter:

```
{% load i18n static courses_extras %}
{% block head_title %}{{ unit.title|strip_math_delimiters }} — {% trans "Editor" %}{% endblock %}
```

`templates/courses/manage/review_submission.html` — line 2 and line 3:

```
{% load i18n static courses_extras %}
{% block head_title %}{% trans "Review" %} · {{ submission.unit.title|strip_math_delimiters }} · libli{% endblock %}
```

> **A missing `{% load %}` is a `TemplateSyntaxError` — a 500 on a student-facing page.** The three
> partials load `i18n` only today; `editor.html` and `review_submission.html` load `i18n static`.
> `lesson_unit`, `quiz_unit` and `quiz_results` already load `courses_extras`.

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_filter.py -v
```

Expected: all pass.

- [ ] **Step 6: Falsify — observe RED on the wiring, not the filter**

The failure mode is *"the filter exists and is registered, but is wired into some sites and not others."* Apply the mutant one site at a time and confirm exactly one assertion goes red each time:

1. Drop `|strip_math_delimiters` from `_unit_tree_node.html:25` only → `test_tree_group_title_tooltip_is_stripped` FAILS, `:15`'s test still passes.
2. Drop it from `quiz_results.html:3` only → `test_quiz_results_browser_tab_is_stripped` FAILS, the other four `<title>` tests still pass.
3. Drop it from `_unit_crumbs.html:29` only → `test_collapsed_crumb_accessible_name_is_stripped` FAILS, `:27`'s test still passes.

Revert each mutant before the next.

- [ ] **Step 7: Sanity-check the pages still render**

```bash
uv run pytest tests/test_unit_nav_render.py tests/test_consumption_pages.py tests/test_review_views.py -v
```

Expected: all pass — this is the `TemplateSyntaxError` guard for the five `{% load %}` edits.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check --fix tests/helpers_title_math.py tests/test_title_math_filter.py
uv run ruff format tests/helpers_title_math.py tests/test_title_math_filter.py
git add templates/courses/_unit_tree_node.html templates/courses/_unit_crumbs.html \
        templates/courses/_unit_footer.html templates/courses/lesson_unit.html \
        templates/courses/quiz_unit.html templates/courses/quiz_results.html \
        templates/courses/manage/editor/editor.html \
        templates/courses/manage/review_submission.html \
        tests/helpers_title_math.py tests/test_title_math_filter.py
git commit -m "feat(courses): strip maths delimiters in title attributes and browser tabs"
```

---

## Task 3: The two scan helpers

**Files:**
- Modify: `courses/htmlsandbox.py` (after `has_math_delimiters`, ~line 126)
- Modify: `courses/rollups.py` (after `build_outline`)
- Test: `tests/test_title_math_helpers.py` (create)

**Interfaces:**
- Consumes: `courses.htmlsandbox.has_math_delimiters(html) -> bool` (existing).
- Produces:
  - `courses.htmlsandbox.titles_have_math(titles: Iterable[str]) -> bool`
  - `courses.rollups.tree_titles_have_math(tree: list[dict]) -> bool` — `tree` is a `build_outline` node-dict list (`{"node": ContentNode, "children": [...], ...}`).

**Placement rationale (spec §2):** every consumer must import *downward*. `courses/views.py` already imports `has_math_delimiters` from `htmlsandbox` (`:33`) and five names from `rollups` (`:80-84`); `views_analytics.py` imports from `rollups` (`:20-22`); `views_review.py` imports from `htmlsandbox` (`:14`). Neither analytics nor review imports `courses.views`. `htmlsandbox` imports nothing from `courses`, so `rollups → htmlsandbox` introduces no cycle.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_title_math_helpers.py`:

```python
"""titles_have_math / tree_titles_have_math -- the scan half of the gate (spec §2).

No `import pytest`: this file has no pytestmark, no marks and no pytest.raises,
and `monkeypatch` is a fixture that needs no import -- ruff's F401 would strip
the line and leave the committed file differing from this listing.
"""

from courses import htmlsandbox
from courses import rollups
from courses.htmlsandbox import titles_have_math
from courses.rollups import tree_titles_have_math


def _node(title, children=None):
    """A build_outline-shaped node dict with only the keys the scan reads."""

    class _N:
        def __init__(self, t):
            self.title = t

    return {"node": _N(title), "children": children or []}


def test_titles_have_math_finds_an_inline_delimiter():
    assert titles_have_math(["plain", r"has \(x\)"]) is True


def test_titles_have_math_finds_a_display_delimiter():
    assert titles_have_math([r"has \[x\]"]) is True


def test_titles_have_math_is_false_when_nothing_carries_maths():
    assert titles_have_math(["plain", "also plain"]) is False


def test_titles_have_math_is_false_on_an_empty_iterable():
    assert titles_have_math([]) is False


def test_titles_have_math_accepts_a_generator():
    """Every call site in views.py passes a generator expression, not a list."""
    assert titles_have_math(t for t in ["plain", r"\(x\)"]) is True


def test_titles_have_math_tolerates_a_none_title():
    """Inherited free from has_math_delimiters' `html or ""` guard."""
    assert titles_have_math([None]) is False


def test_titles_have_math_delegates_to_has_math_delimiters(monkeypatch):
    """PIN: an independent copy of the "\\(" test satisfies every assertion above
    while forking the delimiter definition the moment has_math_delimiters changes.
    Patch the shared predicate to a sentinel and require the helper to follow it."""
    monkeypatch.setattr(
        htmlsandbox, "has_math_delimiters", lambda t: t == "SENTINEL"
    )
    assert htmlsandbox.titles_have_math(["SENTINEL"]) is True
    assert htmlsandbox.titles_have_math([r"\(x\)"]) is False


def test_tree_titles_have_math_finds_a_root_title():
    assert tree_titles_have_math([_node(r"\(x\)")]) is True


def test_tree_titles_have_math_recurses_into_grandchildren():
    """MUST RECURSE: the unit page renders the WHOLE course outline into the DOM,
    so a maths title three levels down is on screen. A one-level scan passes every
    other test in this file."""
    tree = [_node("part", [_node("chapter", [_node(r"deep \(x\)")])])]
    assert tree_titles_have_math(tree) is True


def test_tree_titles_have_math_is_false_on_a_maths_free_tree():
    tree = [_node("part", [_node("chapter", [_node("unit")])])]
    assert tree_titles_have_math(tree) is False


def test_tree_titles_have_math_is_false_on_an_empty_tree():
    assert tree_titles_have_math([]) is False


def test_tree_titles_have_math_tolerates_a_missing_children_key():
    """Cheap defensiveness, not a response to a known producer: build_outline
    unconditionally sets "children": [] and prunes by rebuilding the list."""
    assert tree_titles_have_math([{"node": _node("plain")["node"]}]) is False


def test_tree_titles_have_math_delegates_its_leaf_test(monkeypatch):
    """PIN, and with more force than the one above: this helper is written by hand
    against a tree walk, so it is the likeliest place for an inlined
    `"\\(" in title` copy to appear -- and nothing else here would go red."""
    monkeypatch.setattr(
        rollups, "titles_have_math", lambda ts: any(t == "SENTINEL" for t in ts)
    )
    assert rollups.tree_titles_have_math([_node("SENTINEL")]) is True
    assert rollups.tree_titles_have_math([_node(r"\(x\)")]) is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_helpers.py -v
```

Expected: collection error — `ImportError: cannot import name 'titles_have_math'`.

- [ ] **Step 3: Write `titles_have_math`**

In `courses/htmlsandbox.py`, immediately after `has_math_delimiters` (which ends at line 125):

```python
def titles_have_math(titles):
    """True iff any string in `titles` carries a maths delimiter (spec §2).

    Takes an iterable of STRINGS, not of nodes: the call sites hold four
    different shapes (a ContentNode, an analytics cell dict, a results row, a
    submission), so each does its own extraction.

    MUST delegate to has_math_delimiters, never re-implement the
    `"\\(" in t or "\\[" in t` test. An independent copy satisfies every test
    today, forks the delimiter definition the moment has_math_delimiters
    changes, and nothing would go red. Delegating also inherits its
    `html or ""` guard for a None title for free.
    """
    return any(has_math_delimiters(t) for t in titles)
```

- [ ] **Step 4: Write `tree_titles_have_math`**

In `courses/rollups.py`, add the import (isort places it with the other `from courses...` lines, `force-single-line`):

```python
from courses.htmlsandbox import titles_have_math
```

and add the function immediately after `build_outline`:

```python
def tree_titles_have_math(tree):
    """True iff any node title anywhere in a build_outline tree carries maths.

    COLLECT + MUST RECURSE, the same shape as _tabs_has_math (courses/views.py):
    on a unit page the contents tree is unit_nav["tree"], which build_unit_nav
    sets to the ENTIRE course outline, and _unit_tree_node.html renders all of
    it into the DOM whether collapsed or not. Scanning only the current unit and
    its prev/next therefore leaves a maths title three sections away rendering
    raw -- and it fails SILENTLY, since the page looks correct for the unit under
    test.

    Delegates its leaf test to titles_have_math (which delegates to
    has_math_delimiters); never inline a `"\\(" in title` check here.

    `item.get("children") or []` is cheap defensiveness, not a response to a
    known producer: build_outline unconditionally sets "children": [] on every
    node dict and prunes by rebuilding the list, never by deleting the key.
    """
    for item in tree or []:
        if titles_have_math([item["node"].title]):
            return True
        if tree_titles_have_math(item.get("children") or []):
            return True
    return False
```

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_helpers.py -v
```

Expected: 13 passed (7 `titles_have_math` + 6 `tree_titles_have_math`).

- [ ] **Step 6: Falsify — observe RED against the two failure-mode mutants**

Mutant A, the *silent narrowing* failure mode — make `tree_titles_have_math` non-recursive:

```python
    for item in tree or []:
        if titles_have_math([item["node"].title]):
            return True
    return False        # MUTANT: no recursion
```

Expected: `test_tree_titles_have_math_recurses_into_grandchildren` FAILS.

Mutant B, the *forked delimiter definition* failure mode — inline the test in `titles_have_math`:

```python
    return any(("\\(" in (t or "")) or ("\\[" in (t or "")) for t in titles)   # MUTANT
```

Expected: `test_titles_have_math_delegates_to_has_math_delimiters` FAILS. Apply the same mutant inside `tree_titles_have_math`'s loop body and confirm `test_tree_titles_have_math_delegates_its_leaf_test` FAILS.

Revert both.

- [ ] **Step 7: Guard against an import cycle**

`courses/rollups.py` imports `courses.models` at module level, so a bare `python -c` raises
`ImproperlyConfigured: Requested setting INSTALLED_APPS` **whether or not a cycle exists** —
the settings module has to be set and `django.setup()` called, or the check has no diagnostic
value at all:

**PowerShell is this repo's primary shell, and `VAR=value cmd` is a POSIX-only prefix that
PowerShell rejects as a parse error.** Use the form that matches the shell you are in:

PowerShell:

```powershell
$env:DJANGO_SETTINGS_MODULE = 'config.settings.test'
uv run python -c "import django; django.setup(); import courses.rollups, courses.views, courses.views_analytics, courses.views_review; print('ok')"
```

bash:

```bash
DJANGO_SETTINGS_MODULE=config.settings.test uv run python -c "import django; django.setup(); import courses.rollups, courses.views, courses.views_analytics, courses.views_review; print('ok')"
```

Then, in either shell:

```bash
uv run pytest tests/test_courses_rollups.py -v
```

Expected: `ok`, and the rollups suite green. A genuine cycle surfaces as `ImportError: cannot
import name ... (most likely due to a circular import)`, not as `ImproperlyConfigured`.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check --fix courses/htmlsandbox.py courses/rollups.py tests/test_title_math_helpers.py
uv run ruff format courses/htmlsandbox.py courses/rollups.py tests/test_title_math_helpers.py
uv run pytest tests/test_title_math_helpers.py -v
git add courses/htmlsandbox.py courses/rollups.py tests/test_title_math_helpers.py
git commit -m "feat(courses): add titles_have_math and tree_titles_have_math scan helpers"
```

---

## Task 4: Shared KaTeX partials, and defect 3

**Files:**
- Create: `templates/courses/_katex_css.html`
- Create: `templates/courses/_katex_js.html`
- Modify: `templates/courses/lesson_unit.html:37,72-76`
- Modify: `templates/courses/quiz_unit.html:10,28-32`
- Modify: `templates/courses/quiz_results.html:7,63-67`
- Modify: `templates/courses/manage/review_submission.html:6,135-139`
- Modify: `templates/courses/manage/editor/editor.html:20,182-186`
- Test: `tests/test_title_math_assets.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: two includable partials. `{% include "courses/_katex_css.html" %}` and `{% include "courses/_katex_js.html" %}`. Both emit **unconditionally**; every caller keeps its own `{% if has_math %}` guard (the editor deliberately has none).

**Defect 3 (spec §Purpose):** `quiz_results.html` and `review_submission.html` load four KaTeX files but **not** `math.js`, so `renderInlineText` has never run there. Switching them to `_katex_js.html` fixes that as a side effect. `question.js` is **retained**, stays **outside** the partial, and must be emitted **after** the include on both pages.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_title_math_assets.py`:

```python
"""Shared KaTeX partials, defect 3 (missing math.js), and the per-page gate."""

import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.helpers_title_math import login_student

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
JS_PARTIAL = ROOT / "templates/courses/_katex_js.html"
CSS_PARTIAL = ROOT / "templates/courses/_katex_css.html"

KATEX_JS = "courses/vendor/katex/katex.min.js"
KATEX_CSS = "courses/vendor/katex/katex.min.css"
MATH_JS = "courses/js/math.js"
QUESTION_JS = "courses/js/question.js"


# --- the partials themselves --------------------------------------------------
def test_js_partial_self_loads_static():
    """Template libraries are NOT inherited from the including template; omitting
    {% load static %} here is a TemplateSyntaxError."""
    assert "{% load static %}" in JS_PARTIAL.read_text(encoding="utf-8")


def test_css_partial_self_loads_static():
    assert "{% load static %}" in CSS_PARTIAL.read_text(encoding="utf-8")


def test_js_partial_keeps_the_load_bearing_script_order():
    """math_reflow.js pre-hooks renderMathInElement/katex.render with a SINGLE
    install attempt and no deferred retry, precisely because it is loaded after
    both vendor files. text_colour.js post-hooks the same two globals. math.js
    runs the document pass and must be last."""
    src = JS_PARTIAL.read_text(encoding="utf-8")
    order = [
        "courses/vendor/katex/katex.min.js",
        "courses/vendor/katex/contrib/auto-render.min.js",
        "courses/js/math_reflow.js",
        "courses/js/text_colour.js",
        "courses/js/math.js",
    ]
    positions = [src.index(name) for name in order]
    assert positions == sorted(positions), f"script order changed: {order}"


def test_every_script_in_the_js_partial_is_deferred():
    """A single non-deferred tag silently reorders execution -- source order only
    guarantees execution order AMONG defer scripts. Worse, a non-deferred math.js
    runs DURING parsing and typesets nothing below its own tag, a failure that
    looks exactly like a missing marker."""
    src = JS_PARTIAL.read_text(encoding="utf-8")
    # Match TAGS, not lines: a line-based count changes when a tag wraps across
    # two lines or a comment merely mentions "<script", and under-counts two tags
    # on one line -- brittle for exactly the edit (adding a KaTeX-family asset)
    # this assertion is meant to police. \b so "<scripting" cannot match.
    tags = re.findall(r"<script\b[^>]*>", src)
    assert len(tags) == 5, f"expected 5 script tags, found {len(tags)}: {tags}"
    assert all(re.search(r"\sdefer(\s|>)", t) for t in tags), tags


# --- defect 3 -----------------------------------------------------------------
def _submitted_quiz_results_url(client, *, unit_title, stem):
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=unit_title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem=stem, required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    Element.objects.create(unit=quiz, content_object=q)
    student = login_student(client, course)
    QuizSubmission.objects.create(
        student=student, unit=quiz, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    return reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )


def _review_url(client, *, unit_title, stem):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=unit_title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem=stem, required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    return reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )


def test_quiz_results_now_ships_math_js_before_question_js(client):
    """A gate test phrased as "contains the KaTeX <script>" is green on this page
    BOTH before and after the change -- it already emits four KaTeX tags today. So
    without this assertion the one thing defect 3 promises to fix is pinned by
    nothing, and the §2 ordering constraint is unpinned too."""
    url = _submitted_quiz_results_url(
        client, unit_title="Plain", stem=r"<p>Explain \(x^2\).</p>"
    )
    body = client.get(url).content.decode()
    assert MATH_JS in body
    assert QUESTION_JS in body
    assert body.index(MATH_JS) < body.index(QUESTION_JS)


def test_review_submission_now_ships_math_js_before_question_js(client):
    url = _review_url(client, unit_title="Plain", stem=r"<p>Explain \(x^2\).</p>")
    body = client.get(url).content.decode()
    assert MATH_JS in body
    assert QUESTION_JS in body
    assert body.index(MATH_JS) < body.index(QUESTION_JS)


def test_review_submission_still_ships_question_js(client):
    """PRESERVE the retained question.js: dropping it regresses maths rendering in
    the read-only stem/answer and breaks
    test_review_views.py::test_review_loads_katex_when_stem_has_math."""
    url = _review_url(client, unit_title="Plain", stem=r"<p>Explain \(x^2\).</p>")
    assert QUESTION_JS in client.get(url).content.decode()


# --- the editor stays unconditional ------------------------------------------
def test_editor_ships_katex_for_a_unit_with_no_maths_anywhere(client):
    """The editor has NO {% if has_math %} wrapper and computes no has_math: it
    ships KaTeX on every unit because MathLive and the live preview need it
    regardless of content. Pins the behaviour the shared partial must preserve."""
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title="Plain title",
    )
    url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    body = client.get(url).content.decode()
    assert KATEX_JS in body
    assert KATEX_CSS in body
    assert MATH_JS in body


def test_editor_still_ships_mathlive_outside_the_shared_partial(client):
    """mathlive.min.js + math_input.js are NOT part of _katex_js.html -- no other
    page has a MathLive authoring surface."""
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title="Plain title",
    )
    url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    body = client.get(url).content.decode()
    assert "courses/vendor/mathlive/mathlive.min.js" in body
    assert "courses/js/math_input.js" in body
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_assets.py -v
```

Expected: the four partial-source tests FAIL (`FileNotFoundError`), and both `math_js_before_question_js` tests FAIL (`math.js` absent).

- [ ] **Step 3: Create the two partials**

`templates/courses/_katex_css.html`:

```
{% load static %}
{% comment %}Shared KaTeX stylesheet link. Emitted UNCONDITIONALLY -- the
{% if has_math %} guard lives at each call site, never here, which is what lets
the editor include it unguarded. Self-loads `static`: template libraries are not
inherited from the including template, so omitting the load is a
TemplateSyntaxError.{% endcomment %}
<link rel="stylesheet" href="{% static 'courses/vendor/katex/katex.min.css' %}">
```

`templates/courses/_katex_js.html`:

```
{% load static %}
{% comment %}Shared KaTeX script block. ORDER IS LOAD-BEARING and must not be
reshuffled: math_reflow.js pre-hooks window.renderMathInElement and katex.render
with a SINGLE install attempt and no deferred retry, precisely because it is
loaded after both vendor files in document order; text_colour.js post-hooks the
same two globals; math.js runs the initial document pass and must be last.

EVERY tag carries `defer`. Source order only guarantees execution order AMONG
defer scripts, so one non-deferred tag silently reorders the rest -- and a
non-deferred math.js runs DURING parsing, so renderMath(document) and
renderInlineText(document) see a partial DOM and typeset nothing below their own
tag, a failure that looks exactly like a missing marker.

question.js is deliberately NOT here: only two pages need it, and it must come
AFTER this include on both.{% endcomment %}
<script src="{% static 'courses/vendor/katex/katex.min.js' %}" defer></script>
<script src="{% static 'courses/vendor/katex/contrib/auto-render.min.js' %}" defer></script>
<script src="{% static 'courses/js/math_reflow.js' %}" defer></script>
<script src="{% static 'courses/js/text_colour.js' %}" defer></script>
<script src="{% static 'courses/js/math.js' %}" defer></script>
```

- [ ] **Step 4: Convert the five call sites**

Every existing `{% if has_math %}` guard line stays exactly where it is; only the tag lines are replaced.

`templates/courses/lesson_unit.html` — line 37:

```
  {% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}
```

lines 72-76 → one line:

```
    {% include "courses/_katex_js.html" %}
```

`templates/courses/quiz_unit.html` — line 10:

```
  {% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}
```

lines 28-32 → `    {% include "courses/_katex_js.html" %}`

`templates/courses/quiz_results.html` — line 7:

```
  {% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}
```

lines 63-67 (the four KaTeX tags **plus** `question.js`) → the include followed by the retained `question.js`, keeping the existing `{% comment %}` at `:60-62` untouched:

```
    {% include "courses/_katex_js.html" %}
    <script src="{% static 'courses/js/question.js' %}" defer></script>
```

`templates/courses/manage/review_submission.html` — line 6:

```
  {% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}
```

lines 135-139 → the include plus the retained `question.js`, keeping the `{% comment %}` at `:131-134`:

```
    {% include "courses/_katex_js.html" %}
    <script src="{% static 'courses/js/question.js' %}" defer></script>
```

`templates/courses/manage/editor/editor.html` — line 20 (**no** `{% if %}` — the editor is unconditional):

```
  {% include "courses/_katex_css.html" %}
```

lines **182-186** → `  {% include "courses/_katex_js.html" %}`

> **The editor's JS range begins at 182, not 183.** Replacing only `183-186` strands a
> `katex.min.js` tag above the include. Lines `169-181` (mathlive + its inline bootstrap +
> `math_input.js`) stay exactly where they are.

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_assets.py -v
```

Expected: all pass.

- [ ] **Step 6: Falsify — observe RED against the ordering and defect-3 mutants**

1. *Defect 3 regressed*: delete the `math.js` line from `_katex_js.html` → **five** tests FAIL: both `math_js_before_question_js` tests, `test_js_partial_keeps_the_load_bearing_script_order` (`ValueError: substring not found`), `test_every_script_in_the_js_partial_is_deferred` (count 4 ≠ 5), and `test_editor_ships_katex_for_a_unit_with_no_maths_anywhere` — after Step 4 the shared partial is the editor's *only* source of `math.js`. All five are expected; none is a second, separate defect.
2. *Order reshuffled*: move `math_reflow.js` above `auto-render.min.js` in the partial → `test_js_partial_keeps_the_load_bearing_script_order` FAILS.
3. *A tag loses `defer`*: drop ` defer` from `text_colour.js` → `test_every_script_in_the_js_partial_is_deferred` FAILS.
4. *`question.js` folded into the partial*: move it inside `_katex_js.html` → `test_every_script_in_the_js_partial_is_deferred` FAILS on the count assertion (6 ≠ 5).
5. *`question.js` emitted before the include* on `quiz_results.html` → `test_quiz_results_now_ships_math_js_before_question_js` FAILS on the index comparison.

Revert each.

- [ ] **Step 7: Regression-check the pages that already had KaTeX**

`courses/tests/test_beforeafter_css.py:177-184` and `test_reveal_scope_agreement.py:65` read
`lesson_unit.html` / `quiz_unit.html` as **source**, which is precisely what this task's script-block
replacement rewrites — so that package belongs in this run too:

```bash
uv run pytest tests/test_review_views.py tests/test_consumption_pages.py \
              tests/test_choice_feedback_has_math.py courses/tests/ -v
```

Expected: all pass — in particular `test_review_loads_katex_when_stem_has_math` and `test_review_no_katex_without_math`.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix tests/test_title_math_assets.py
uv run ruff format tests/test_title_math_assets.py
git add templates/courses/_katex_css.html templates/courses/_katex_js.html \
        templates/courses/lesson_unit.html templates/courses/quiz_unit.html \
        templates/courses/quiz_results.html \
        templates/courses/manage/review_submission.html \
        templates/courses/manage/editor/editor.html \
        tests/test_title_math_assets.py
git commit -m "refactor(courses): extract shared KaTeX partials and ship math.js on results/review"
```

---

## Task 5: `data-math-title` markers and the `math.js` selector

**Files:**
- Modify: `courses/static/courses/js/math.js:31`
- Modify: `templates/courses/_lesson_article.html:7`
- Modify: `templates/courses/_quiz_article.html:5`
- Modify: `templates/courses/_unit_footer.html:14,48`
- Modify: `templates/courses/_unit_tree_node.html:15,25,60`
- Modify: `templates/courses/_unit_crumbs.html:36`
- Modify: `templates/courses/_outline_node.html:7,21`
- Modify: `templates/courses/quiz_results.html:12`
- Modify: `templates/courses/course_results.html:21`
- Modify: `notes/templates/notes/course_notes.html:16`
- Modify: `tags/templates/tags/panel_page.html:5`
- Modify: `tags/templates/tags/_tag_section.html:25`
- Modify: `templates/courses/manage/analytics_matrix.html:114,115,125`
- Modify: `templates/courses/manage/_breakdown_node.html:6,24,30`
- Modify: `templates/courses/manage/review_queue.html:15,30`
- Modify: `templates/courses/manage/review_submission.html:58`
- Modify: `templates/courses/manage/editor/editor.html:75,80`
- Modify: `templates/courses/manage/editor/_preview.html:6`
- Test: `tests/test_title_math_markers.py` (create)

**Interfaces:**
- Consumes: `tests/helpers_title_math.py` from Task 2.
- Produces: the `[data-math-title]` contract — `renderInlineText` typesets any element carrying it.

**Two rules that decide where the attribute goes:**

1. **The title-alone rule.** Where a template interpolates other content into the same element, the marker goes on a `<span>` wrapping the title **alone**, never on the shared parent — otherwise a student's display name or a translated word gets typeset too. Applies to `review_queue.html:15,30`, `review_submission.html:58`, `quiz_results.html:12`, `editor.html:75`, `tags/panel_page.html:5`.
2. **The rule's limit.** It bites only when the sibling content **could itself contain delimiters** (translated prose, a student name, another node's title). A static glyph does not qualify: `analytics_matrix.html:114-115` renders `{{ cell.title }} ▸` inside the leaf `<a>`, and the marker goes on that `<a>` with the `▸` inside its scope. Auto-render scans the glyph, finds no delimiters, and leaves it alone.

**Reading the line numbers:** they point at the **title interpolation**; the attribute goes on that title's nearest enclosing element, which for a multi-line opening tag is an earlier line. In `analytics_matrix.html` the leaf `<a class="analytics__expand">` opens at `:114`, the leaf `<span>` opens at the end of `:115`, and `<span class="analytics__group-title">` opens at `:125`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_title_math_markers.py`:

```python
"""data-math-title marker coverage (spec §1).

A regex over raw source is NOT acceptable -- per this repo's own experience
regexes match docstrings and comments. Every assertion here is over RENDERED
output: a view response, or render_to_string for the one branch no view reaches.
"""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.urls import reverse

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.helpers_title_math import MATHS_TITLE
from tests.helpers_title_math import login_student
from tests.helpers_title_math import make_title_course

pytestmark = pytest.mark.django_db


def _marked_texts(html):
    """Every [data-math-title] element's text, whitespace-normalised."""
    soup = BeautifulSoup(html, "html.parser")
    return [" ".join(el.get_text().split()) for el in soup.select("[data-math-title]")]


def _marked(html, selector):
    """Elements matching `selector` that carry the marker attribute.

    Attribute presence ONLY -- deliberately not a text check, because several
    fixtures below mark maths-free titles on purpose (the analytics leaf headers
    under maths_on="group" are the clearest case). The "visible text keeps its
    delimiters" property is pinned separately, by
    test_the_visible_title_keeps_its_raw_delimiters.
    """
    return BeautifulSoup(html, "html.parser").select(f"{selector}[data-math-title]")


# --- math.js's selector -------------------------------------------------------
def test_math_js_selector_includes_the_marker():
    """Anchored to the querySelectorAll ARGUMENT, not to the file.

    A bare `"[data-math-title]" in src` is satisfied by the COMMENT this same
    task writes above renderInlineText ("Inline \\(...\\) math typed into ... a
    node TITLE ([data-math-title], ...)"), so dropping the entry from the actual
    selector would leave it green -- the single most load-bearing line of the
    feature, undetected until the Task 11 e2e six tasks later. This file's own
    docstring says regexes match comments; that cuts both ways."""
    import re
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent
        / "courses/static/courses/js/math.js"
    ).read_text(encoding="utf-8")
    assert re.search(
        r'querySelectorAll\(\s*"[^"]*\[data-math-title\][^"]*"\s*\)', src
    ), "[data-math-title] is not in renderInlineText's querySelectorAll argument"


# --- the lesson page: heading, nav buttons, tree (x2), crumb ------------------
def _lesson_body(client, *, maths_on="far", node="unitA"):
    course, unit, nodes = make_title_course(maths_on=maths_on)
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit",
        kwargs={"slug": course.slug, "node_pk": nodes[node].pk},
    )
    return client.get(url).content.decode()


def test_lesson_heading_is_marked(client):
    assert _marked(_lesson_body(client, maths_on="unitA"), "h1.lesson-unit__title")


def test_nav_button_titles_are_marked(client):
    """View unitB, NOT unitA: unitA is the first unit in the course, so
    unit_nav.prev is None and _unit_footer.html:17-21 renders the DISABLED branch
    with no .unit-foot__navtitle at all. Only the `next` span would exist, and the
    prev marker at :14 could be dropped with this test still green.

    unitB has both a prev and a next, so the count assertion pins both sites."""
    body = _lesson_body(client, maths_on="unitB", node="unitB")
    assert len(_marked(body, "span.unit-foot__navtitle")) == 2


def test_tree_unit_labels_are_marked(client):
    assert _marked(_lesson_body(client), "span.unit-tree__label")


def test_tree_group_titles_are_marked(client):
    assert _marked(_lesson_body(client), "span.unit-tree__grouptitle")


def test_breadcrumb_labels_are_marked(client):
    body = _lesson_body(client)
    labels = _marked(body, "span.unit-crumbs__label")
    assert labels
    # The course crumb is an <a class="unit-crumbs__label"> and is OUT OF SCOPE
    # (Course.title is a different field on a different model).
    assert not _marked(body, "a.unit-crumbs__label")


def test_the_childless_container_branch_is_marked():
    """_unit_tree_node.html:60 is unreachable through any view: build_outline
    prunes every zero-child container under BOTH "hide" and "keep", pinned by
    test_unit_nav_render.py::test_a_genuinely_empty_group_is_pruned_not_rendered.
    Covered by a bare render only."""

    class _N:
        pk = 1
        kind = "chapter"
        title = MATHS_TITLE

    class _C:
        language = "pl"
        slug = "c"

    html = render_to_string(
        "courses/_unit_tree_node.html",
        {
            "item": {"node": _N(), "is_unit": False, "children": []},
            "course": _C(),
            "current_pk": None,
        },
    )
    assert _marked(html, "span.unit-tree__grouptitle")


def test_the_visible_title_keeps_its_raw_delimiters(client):
    """THE OVER-APPLICATION GUARD, and the only test that catches it.

    The most natural way to get this feature wrong is to pipe the VISIBLE
    interpolation through |strip_math_delimiters as well as the title=
    attribute. That silently disables typesetting on every marked surface while
    leaving the attribute in place -- so every other marker test here, which
    asserts attribute presence only, stays green. KaTeX needs the delimiters in
    the TEXT; the filter belongs on the attribute alone.

    Checks the four sites where the same title is interpolated twice in one tag
    (visible text + title= tooltip), which is exactly where the mistake is made.
    """
    body = _lesson_body(client, maths_on="unitA", node="unitA")
    soup = BeautifulSoup(body, "html.parser")

    for selector in ("span.unit-tree__label", "h1.lesson-unit__title"):
        els = soup.select(f"{selector}[data-math-title]")
        assert els, f"no marked {selector} rendered"
        assert any("\\(" in el.get_text() for el in els), (
            f"{selector}: the VISIBLE title lost its delimiters -- "
            "strip_math_delimiters was applied to the text, not just title="
        )

    # ...and the tooltip on the same element IS stripped. Both halves together
    # are what distinguish "correctly wired" from "filter applied everywhere".
    labels = soup.select("span.unit-tree__label[title]")
    assert labels
    assert all("\\(" not in el["title"] for el in labels)


# --- the quiz page ------------------------------------------------------------
def test_quiz_heading_is_marked(client):
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    url = reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    assert _marked(client.get(url).content.decode(), "h1.lesson-unit__title")


# --- the outline page ---------------------------------------------------------
def test_outline_unit_and_group_titles_are_marked(client):
    course, _unit, _nodes = make_title_course(maths_on="far")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert _marked(body, "span.outline-unit__title")
    assert _marked(body, "span.outline-node__title")


# --- quiz results: the TITLE-ALONE rule --------------------------------------
def test_quiz_results_heading_marks_the_title_alone(client):
    """`{{ unit.title }} — {% trans "results" %}`: marking the shared <h1> would
    typeset the translated word too."""
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=MATHS_TITLE,
    )
    student = login_student(client, course)
    QuizSubmission.objects.create(
        student=student, unit=quiz, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    body = client.get(url).content.decode()
    assert MATHS_TITLE in _marked_texts(body)
    assert not _marked(body, "h1.result__title")


# --- course results -----------------------------------------------------------
def test_course_results_row_titles_are_marked(client):
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    url = reverse("courses:course_results", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    # Precondition, stated rather than assumed: build_course_results appends a
    # "not_started" row for EVERY quiz unit (rollups.py:369-380), so a quiz with
    # no submission still renders. Without this the positive assertion below
    # could fail for fixture reasons and read as a wiring bug.
    assert MATHS_TITLE in body, "the results row did not render"
    assert _marked(body, "span.result-row__title")


# --- analytics ----------------------------------------------------------------
def _analytics_bodies(client, *, maths_on):
    """(matrix_body, breakdown_body) for a course seeded by make_title_course,
    viewed by the course owner. `expand` opens part2 so its GROUP header renders.

    Adds a QUIZ unit: make_title_course creates only unit_type="lesson", so
    _breakdown_node.html's `{% if item.node.unit_type == "quiz" %}` branch
    (:4-21, holding the :6 marker) would never render and the :24 lesson branch
    -- same class -- would satisfy the assertion on its own."""
    pa = make_pa(client)
    course, _unit, nodes = make_title_course(maths_on=maths_on)
    course.owner = pa
    course.save(update_fields=["owner"])
    ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=nodes["part2"],
        order=1, title=MATHS_TITLE if maths_on == "far" else "Quiz zwykly",
    )
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    matrix_url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    matrix = client.get(f"{matrix_url}?expand={nodes['part2'].pk}").content.decode()
    breakdown_url = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    breakdown = client.get(breakdown_url).content.decode()
    return matrix, breakdown


def test_analytics_matrix_group_header_is_marked(client):
    matrix, _b = _analytics_bodies(client, maths_on="group")
    assert _marked(matrix, "span.analytics__group-title")


def test_analytics_matrix_leaf_headers_are_marked(client):
    """BOTH leaf branches, with selectors that cannot be satisfied by the group
    cell. analytics_matrix.html:110 keeps `analytics__colhead` on the group <th>
    and only ADDS `analytics__group`, so a bare `th.analytics__colhead span`
    selector matches the group-title span the test above already asserted --
    leaving the expandable <a> (:114) and the non-expandable <span> (:115)
    unmarked with the suite still green.

    The `?expand=` fixture produces both: part2 is expanded (so its own children
    are leaves) while part1 is an unexpanded, child-bearing leaf -> expandable."""
    matrix, _b = _analytics_bodies(client, maths_on="group")
    leaf_th = "th.analytics__colhead:not(.analytics__group)"
    expandable = _marked(matrix, f"{leaf_th} a.analytics__expand")
    plain = _marked(matrix, f"{leaf_th} span")
    assert expandable, "expandable leaf header <a> is unmarked"
    assert plain, "non-expandable leaf header <span> is unmarked"


def test_analytics_breakdown_titles_are_marked(client):
    """BOTH unit branches plus the group branch, selected DISTINCTLY.

    The quiz branch (:6) and the lesson branch (:24) share the class
    `breakdown-unit__title`, so neither a truthiness check nor a `>= 2` count
    pins them: the fixture has THREE lesson units and one quiz, so dropping the
    quiz marker still leaves three marked spans and `3 >= 2` passes. What
    separates them structurally is the pill -- the quiz branch always emits one
    (`{% with p=item.pill %}`), the lesson branch never does."""
    _m, breakdown = _analytics_bodies(client, maths_on="far")
    quiz = _marked(
        breakdown, "div.breakdown-unit:has(.pill) > span.breakdown-unit__title"
    )
    lesson = _marked(
        breakdown,
        "div.breakdown-unit:not(:has(.pill)) > span.breakdown-unit__title",
    )
    assert quiz, "the quiz unit branch (_breakdown_node.html:6) is unmarked"
    assert lesson, "the lesson unit branch (:24) is unmarked"
    assert _marked(breakdown, "span.breakdown-node__title")


# --- review queue + review submission: the TITLE-ALONE rule ------------------
def _review_setup(client, unit_title):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=unit_title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem="<p>Explain plainly.</p>", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    # display_name MUST be set explicitly: UserFactory defaults it to
    # factory.Faker("name") (tests/factories.py:63), and review_queue.html:15
    # renders `display_name|default:username` -- so a test asserting on "anna"
    # while the factory renders a random Faker name CANNOT FAIL under any
    # implementation, including the mutant it exists to catch.
    student = UserFactory(username="anna", display_name="Anna Nowak")
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    # A SECOND submission, IN_PROGRESS, so review_queue.html:30 renders at all.
    # A SUBMITTED row lands in data["awaiting"] (courses/review.py:248-255) and
    # only exercises the :15 branch; :30 is inside {% if in_progress %}, which
    # stays empty without this -- the same duplicated-branch gap the analytics
    # leaf-header test closes with :not(.analytics__group).
    other = UserFactory(username="bogdan", display_name="Bogdan Lis")
    EnrollmentFactory(student=other, course=course)
    QuizSubmission.objects.create(
        student=other, unit=unit, status=QuizSubmission.Status.IN_PROGRESS,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    return course, sub


def test_review_queue_marks_the_title_alone_not_the_student_name(client):
    course, _sub = _review_setup(client, MATHS_TITLE)
    url = reverse("courses:manage_review_queue", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert "Anna Nowak" in body, "the student name did not render at all"
    assert "Bogdan Lis" in body, "the in-progress row did not render"
    marked = _marked_texts(body)
    # BOTH branches -- the awaiting row (:15) and the in-progress row (:30) --
    # carry the title, and neither carries a student name.
    assert marked.count(MATHS_TITLE) == 2
    assert all("Anna Nowak" not in t and "Bogdan Lis" not in t for t in marked)


def test_review_submission_marks_the_title_alone(client):
    course, sub = _review_setup(client, MATHS_TITLE)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    body = client.get(url).content.decode()
    marked = _marked_texts(body)
    assert MATHS_TITLE in marked
    assert not _marked(body, "h1.review-topbar__title")


# --- editor + preview ---------------------------------------------------------
# A title DISTINCT from MATHS_TITLE, so the crumb assertion cannot be satisfied
# by the <h1>: _editor_body gives the unit MATHS_TITLE, and editor.html:80 marks
# that h1 -- so asserting `MATHS_TITLE in _marked_texts(body)` would stay green
# with the per-ancestor crumb marker never added at all, which is precisely the
# "wired at some sites, not others" gap these tests exist to close.
MATHS_PART_TITLE = r"Czesc \(a_1\)"


def _editor_body(client, title=MATHS_TITLE):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0,
        title=MATHS_PART_TITLE,
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, order=0,
        title=title,
    )
    url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    return client.get(url).content.decode()


def test_editor_heading_and_preview_heading_are_marked(client):
    body = _editor_body(client)
    assert _marked(body, "h1.editor-head__title")
    assert _marked(body, "h2.prev-unit-title")


def test_editor_crumb_marks_each_ancestor_title_not_the_path(client):
    """.editor-crumb__path also holds course.title, which is out of scope.

    Asserts on MATHS_PART_TITLE, not MATHS_TITLE: only the ancestor's own title
    pins the :75 site independently of the :80 heading."""
    body = _editor_body(client)
    assert MATHS_PART_TITLE in body, "the ancestor crumb did not render"
    assert MATHS_PART_TITLE in _marked_texts(body)
    assert not _marked(body, "span.editor-crumb__path")


# --- notes + tags: three marked sites that nothing else pins ------------------
# Without these, dropping data-math-title from all three leaves Tasks 5 AND 9
# fully green -- Task 9 asserts only on KaTeX assets and on the title being
# present, neither of which sees the attribute.


def test_course_notes_unit_heading_is_marked(client):
    from notes.models import Note

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=MATHS_TITLE,
    )
    student = login_student(client, course)
    Note.objects.create(author=student, unit=unit, body="a note")
    body = client.get(
        reverse("notes:course_notes", kwargs={"slug": course.slug})
    ).content.decode()
    assert _marked(body, "h2.course-notes__unit-title")


def _tagged(client, title):
    from tags import services as tag_services

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=title,
    )
    student = login_student(client, course)
    tag_services.tag_unit(student, unit, "algebra")
    return course, unit


def test_tags_hub_unit_link_is_marked(client):
    _tagged(client, MATHS_TITLE)
    body = client.get(reverse("tags:my_tags")).content.decode()
    assert _marked(body, "div.tag-section__units li a")


def test_tags_panel_heading_marks_the_title_alone(client):
    """panel_page.html:5 is `<h1>{{ unit.title }} — {% trans "Tags" %}</h1>` --
    structurally identical to quiz_results.html:12, so the marker goes on an
    inner span and NOT on the shared <h1>. Reachable only via the invalid-tag
    no-JS POST (422)."""
    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    resp = client.post(
        reverse("tags:tag_add", kwargs={"slug": course.slug, "node_pk": unit.pk}),
        {"name": ""},
    )
    assert resp.status_code == 422
    body = resp.content.decode()
    assert MATHS_TITLE in _marked_texts(body)
    assert not _marked(body, "h1")


# --- the exclusions -----------------------------------------------------------
def test_the_editor_settings_title_input_is_neither_marked_nor_filtered(client):
    """Path C, the edit buffer: typesetting or stripping it corrupts what is saved.
    _unit_settings.html:12 is `<input type="text" name="title" value="{{ unit.title }}"
    required>`, and it is the only input[name="title"] on the editor page."""
    body = _editor_body(client)
    soup = BeautifulSoup(body, "html.parser")
    field = soup.select_one('input[name="title"]')
    assert field is not None
    assert field.get("value") == MATHS_TITLE
    assert "data-math-title" not in field.attrs


def test_the_rename_result_payload_is_neither_marked_nor_filtered(client):
    """<data value=> read by JS -- a fragment endpoint, so drive the rename POST.

    THE FRAGMENT PATH IS NARROW (views_manage.py:816-881): node_rename returns
    _rename_result.html only when _wants_fragment(request) is true AND the POST
    carries neither `has_settings` (which re-renders the unit panel) nor
    ctx="editor" (which redirects to the editor page). So: the fetch header, and
    `node` / `title` / `token` only."""
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title="Before",
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": course.slug}),
        {
            "node": unit.pk,
            "title": MATHS_TITLE,
            "token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200, resp.content.decode()[:400]
    payload = BeautifulSoup(resp.content.decode(), "html.parser").select_one(
        "data[value]"
    )
    assert payload is not None, "the rename fragment did not render _rename_result.html"
    assert payload["value"] == MATHS_TITLE
    assert "data-math-title" not in payload.attrs


def test_the_builder_rename_input_is_neither_marked_nor_filtered(client):
    """The THIRD Path-C edit buffer, and the only one not otherwise pinned.

    `_tree_node.html:49` is `<input class="tree__title" type="text" name="title"
    value="{{ node.title }}">`. The plan's own note stresses that :49 (permanent
    edit buffer) and :50 (deferred builder tooltip) are different kinds of site
    in the same tag -- exactly the confusion a later builder task could resolve
    wrongly with nothing red. Rendered via the builder page.
    """
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=MATHS_TITLE,
    )
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    field = BeautifulSoup(body, "html.parser").select_one("input.tree__title")
    assert field is not None, "the builder rename input did not render"
    assert field.get("value") == MATHS_TITLE      # unfiltered
    assert "data-math-title" not in field.attrs   # unmarked
```

> `courses:manage_builder` is verified in `courses/urls.py:161`. The unit is seeded at **top
> level** deliberately: the builder lazy-loads nested scopes (`tests/test_builder_lazy_scopes.py`),
> so a nested unit's row may not be in the first render and the selector would find nothing.

> The **token** idiom above — a real ISO `token` from `node.updated`, not a sentinel string —
> matches `tests/test_builder_lazy_scopes.py:698-707`. Note that call is **not** a model for
> the rest of this test: it sends no `X-Requested-With` header and follows `resp["Location"]`,
> i.e. it drives the redirect path, whereas this test needs the *fragment* branch. The header
> is what selects it: `_wants_fragment` reads `X-Requested-With: fetch` in both
> `courses/views_manage.py:1329` and `tags/views.py:20`. Omit it and you get a 302, not
> `_rename_result.html`.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_markers.py -v
```

Expected: every marker test FAILS (no element carries the attribute); the two exclusion tests already PASS (nothing is marked yet) — that is expected and they become meaningful once Step 3 lands.

- [ ] **Step 3: Add `[data-math-title]` to the `math.js` selector**

`courses/static/courses/js/math.js` — update the comment above `renderInlineText` and line 31:

```js
  function renderInlineText(root) {
    // Inline \(...\) math typed into a text element's PROSE, and into a node
    // TITLE ([data-math-title], added by the read-only display sites). Question
    // stems and choices are typeset by question.js/quiz.js, and math elements
    // use the [data-katex] path above; text elements, fill-gate stems and
    // titles are covered here. No-op if auto-render.min.js wasn't loaded.
    if (typeof window.renderMathInElement !== "function") return;
    (root || document).querySelectorAll(".el--text, .el--table, .el--gallery, .el--tabs, .fillgate, .stepper, .markdone, .guessnumber, .spoiler__toggle, .callout__heading, [data-math-title]").forEach(function (el) {
```

- [ ] **Step 4: Add the markers — student and results surfaces**

`_lesson_article.html:7`:

```
    <h1 class="lesson-unit__title" data-math-title>{{ unit.title }}</h1>
```

`_quiz_article.html:5`:

```
  <h1 class="lesson-unit__title" data-math-title>{{ unit.title }}</h1>
```

`_unit_footer.html:14` and `:48` — add the attribute to each `.unit-foot__navtitle`:

```
          <span class="unit-foot__navtitle" lang="{{ course.language }}" data-math-title>{{ unit_nav.prev.title }}</span>
```
```
          <span class="unit-foot__navtitle" lang="{{ course.language }}" data-math-title>{{ unit_nav.next.title }}</span>
```

`_unit_tree_node.html:15`, `:25`, `:60` (each already carries the Task-2 filter on `title=` at `:15`/`:25`):

```
      <span class="unit-tree__label" title="{{ item.node.title|strip_math_delimiters }}" data-math-title>{{ item.node.title }}</span>
```
```
          <span class="unit-tree__grouptitle" lang="{{ course.language }}" title="{{ item.node.title|strip_math_delimiters }}" data-math-title>{{ item.node.title }}</span>
```
```
        <span class="unit-tree__grouptitle" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
```

`_unit_crumbs.html:36` — the **ancestor** label only. Line 20's `<a class="unit-crumbs__label">` holds `course.title` and stays unmarked:

```
        <span class="unit-crumbs__label" data-math-title>{{ a.title }}</span>
```

`_outline_node.html:7` and `:21`:

```
      <span class="outline-unit__title" data-math-title>{{ item.node.title }}</span>
```
```
      <span class="outline-node__title" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
```

`quiz_results.html:12` — title-alone:

```
  <h1 class="result__title"><span data-math-title>{{ unit.title }}</span> — {% trans "results" %}</h1>
```

`course_results.html:21` — the row holds the title alone:

```
      <span class="result-row__title" data-math-title>{{ row.unit.title }}</span>
```

`notes/templates/notes/course_notes.html:16` — title alone:

```
        <h2 class="course-notes__unit-title" data-math-title>{{ row.unit.title }}</h2>
```

`tags/templates/tags/panel_page.html:5` — title-alone (structurally identical to `quiz_results.html:12`):

```
    <h1><span data-math-title>{{ unit.title }}</span> — {% trans "Tags" %}</h1>
```

`tags/templates/tags/_tag_section.html:25` — the `<a>` holds the title alone:

```
          <li><a href="{% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}" data-math-title>{{ unit.title }}</a></li>
```

- [ ] **Step 5: Add the markers — teacher / management surfaces**

`manage/analytics_matrix.html` — three sites. The leaf `<a>` opens at `:114`; the `▸` glyph stays **inside** its scope (the rule's limit — a static glyph carries no delimiters):

```
                      {% if cell.expandable %}<a class="analytics__expand" href="{{ cell.expand_url }}"
                         lang="{{ course.language }}" data-math-title>{{ cell.title }} ▸</a>{% else %}<span
                         lang="{{ course.language }}" data-math-title>{{ cell.title }}</span>{% endif %}
```

and the group cell, whose `<span>` opens at `:125`:

```
                    {% else %}<span class="analytics__group-title"
                         lang="{{ course.language }}" data-math-title>{{ cell.title }}</span><a
```

`manage/_breakdown_node.html:6`, `:24`, `:30`:

```
        <span class="breakdown-unit__title" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
```
```
        <span class="breakdown-unit__title{% if item.completed %} is-done{% endif %}" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
```
```
      <span class="breakdown-node__title" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
```

`manage/review_queue.html:15` and `:30` — title-alone: the student name shares the `<span>` today, so split the title out:

```
          <span>{{ sub.student.display_name|default:sub.student.username }} · <span data-math-title>{{ sub.unit.title }}</span></span>
```

(identical edit at `:30`).

`manage/review_submission.html:58` — title-alone:

```
      <h1 class="review-topbar__title">{% trans "Review" %}: {{ submission.student.display_name|default:submission.student.username }} — <span data-math-title>{{ submission.unit.title }}</span></h1>
```

`manage/editor/editor.html:75` — title-alone: the loop emits a separator and each ancestor title, and `.editor-crumb__path` also holds `course.title`:

```
      {{ course.title }}{% for a in ancestors %} <span class="editor-crumb__sep">/</span> <span data-math-title>{{ a.title }}</span>{% endfor %}
```

`manage/editor/editor.html:80`:

```
    <h1 class="editor-head__title" data-math-title>{{ unit.title }}</h1>
```

`manage/editor/_preview.html:6`:

```
      <h2 class="prev-unit-title" data-math-title>{{ unit.title }}</h2>
```

> **The preview heading already typesets today**, before this change: `editor.js`'s
> `renderPreviewMath(scope)` runs `renderMathInElement` over the whole preview pane on
> initial load and after every `[data-scope="preview"]` swap. The marker merely regularises
> it and is **not** a defect fix. Do not remove that call — it is this site's re-render path
> after the `replaceWith`. Expect the heading to be visited twice on initial load (once by
> `renderInlineText`, once by `renderPreviewMath`); the second visit is a no-op because the
> first replaced the delimiters with KaTeX markup whose `<annotation>` text carries none.
> This double visit is not new — the preview's `.el--text` prose is already visited twice.

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_markers.py -v
```

Expected: all pass.

> If a marker test still fails on a page that has no `has_math` yet (outline, analytics,
> review queue, notes, tags), that is **not** an asset problem — the marker is server-rendered
> markup and is present regardless of whether KaTeX loads. A failure here means the attribute
> is genuinely missing or the CSS selector in the test does not match the markup.

- [ ] **Step 7: Falsify — observe RED against the title-alone mutants**

The failure mode is *"the marker went on the shared parent, so a student name or a translated word gets typeset"*:

1. Move the marker in `review_queue.html:15` from the inner `<span>` to the outer one → `test_review_queue_marks_the_title_alone_not_the_student_name` FAILS (`anna` appears in a marked element's text).
2. Move it in `quiz_results.html:12` from the inner `<span>` to the `<h1>` → `test_quiz_results_heading_marks_the_title_alone` FAILS.
3. Move it in `editor.html:75` from the per-ancestor `<span>` to `.editor-crumb__path` → `test_editor_crumb_marks_each_ancestor_title_not_the_path` FAILS.
4. Add `data-math-title` to `_unit_settings.html:12`'s `<input>` → `test_the_editor_settings_title_input_is_neither_marked_nor_filtered` FAILS.
5. Drop `[data-math-title]` from the `math.js` **`querySelectorAll` argument** while leaving the comment above `renderInlineText` untouched → `test_math_js_selector_includes_the_marker` FAILS. If it passes, the assertion is matching the comment rather than the selector and the test is worthless — fix the test, not the mutant.
6. Drop the marker from `notes/course_notes.html:16`, `tags/_tag_section.html:25` and `tags/panel_page.html:5` — **all three at once** → exactly the three new notes/tags tests FAIL and nothing in Task 9 does. That asymmetry is the point: those three sites are the ones Task 9's asset assertions cannot see.
7. Move the `panel_page.html:5` marker from the inner `<span>` to the `<h1>` → `test_tags_panel_heading_marks_the_title_alone` FAILS on the `not _marked(body, "h1")` assertion.
8. Drop the marker from `_unit_footer.html:14` (prev) only, leaving `:48` → `test_nav_button_titles_are_marked` FAILS on the `== 2` count. With the old `node="unitA"` fixture this mutant was invisible.
9. Drop the marker from `_breakdown_node.html:6` (the quiz branch) only, leaving `:24` → `test_analytics_breakdown_titles_are_marked` FAILS on the `quiz` assertion. (A count-based assertion could **not** catch this — three lesson units keep the total above any small threshold — which is why the two branches are selected via `:has(.pill)`.)
10. Drop the marker from `review_queue.html:30` (the in-progress branch) only, leaving `:15` → `test_review_queue_marks_the_title_alone_not_the_student_name` FAILS on the `== 2` count.
11. **The over-application mutant**: add `|strip_math_delimiters` to the *visible* interpolation at `_unit_tree_node.html:15` (so the tag reads `title="{{ …|strip_math_delimiters }}" data-math-title>{{ item.node.title|strip_math_delimiters }}`) → `test_the_visible_title_keeps_its_raw_delimiters` FAILS, and **every other marker test stays green**. That asymmetry is the point: this is the one mistake that silently disables the whole feature while leaving all the attributes in place.

Revert each.

- [ ] **Step 7b: Regression-check the eighteen edited files (seventeen templates plus `math.js`)**

This is the largest template diff in the plan and several of these files are asserted on by
existing markup tests — `test_analytics_views.py` in particular pins literal header markup
(`">Sec ▸<"`), which the `analytics_matrix.html` edit sits directly on top of. Without this
step a regression here surfaces only at Task 11's whole-repo sweep, many commits later.

**`courses/tests/` is a SECOND, separately-rooted test package** — 106 files, collected by the
whole-repo run because `pyproject.toml` sets no `testpaths` — and a dozen of its files assert
on exactly the templates this task rewrites (`test_reveal_gate_palette.py`,
`test_callout_editor_row.py`, `test_spoiler_nesting.py` and others GET the editor page whose
`<h1>`, crumb and preview heading change here). It must be in this run for the same reason
`tests/` is:

```bash
uv run pytest tests/test_unit_nav_render.py tests/test_consumption_pages.py \
              tests/test_analytics_views.py tests/test_review_views.py \
              tests/test_tags_views.py tests/test_tags_outline.py \
              tests/test_notes_views.py tests/test_courses_views.py \
              courses/tests/ -v
```

Expected: all pass. A failure asserting on literal header markup means the marker changed a
string an existing test pins — update that test only if the change is genuinely intended
(adding an attribute should not move any text), otherwise fix the template edit.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix tests/test_title_math_markers.py
uv run ruff format tests/test_title_math_markers.py
uv run pytest tests/test_title_math_markers.py tests/test_title_math_filter.py -v
git add courses/static/courses/js/math.js \
        templates/courses/_lesson_article.html templates/courses/_quiz_article.html \
        templates/courses/_unit_footer.html templates/courses/_unit_tree_node.html \
        templates/courses/_unit_crumbs.html templates/courses/_outline_node.html \
        templates/courses/quiz_results.html templates/courses/course_results.html \
        templates/courses/manage/analytics_matrix.html \
        templates/courses/manage/_breakdown_node.html \
        templates/courses/manage/review_queue.html \
        templates/courses/manage/review_submission.html \
        templates/courses/manage/editor/editor.html \
        templates/courses/manage/editor/_preview.html \
        notes/templates/notes/course_notes.html \
        tags/templates/tags/panel_page.html tags/templates/tags/_tag_section.html \
        tests/test_title_math_markers.py
git commit -m "feat(courses): mark node-title display sites with data-math-title"
```

---

## Task 6: Widen `has_math` on the five render sites that already compute it

**Files:**
- Modify: `courses/views.py` — imports, `full_lesson_render_context` (`:529`, insert after `:556`), `quiz_unit` (`:1365`, after `:1385`), `_quiz_render_feedback` (`:1402`, after `:1418`), `quiz_results` (`:1572`, after `:1601`)
- Modify: `courses/views_review.py` — `_review_context` (`:93`)
- Test: `tests/test_title_math_assets.py` (append)

**Interfaces:**
- Consumes: `titles_have_math`, `tree_titles_have_math` (Task 3); the partials (Task 4).
- Produces: nothing new.

**`node`, not `unit`.** `full_lesson_render_context(node, …)`, `build_quiz_context(node, user)` and `quiz_results` all bind the node as **`node`**; `unit` exists only as a *context key*, never as a local. On the two quiz paths `has_math` and `unit_nav` are reachable only as `ctx["has_math"]` / `ctx["unit_nav"]`, and `ctx["unit_nav"]` is assigned on the very line cited — so the OR must come **after** that assignment.

**Why the lesson/quiz statement scans two things — redundant today, kept deliberately.** `unit_nav["tree"]` is `build_outline(...)` and already contains the ancestors, prev, next **and** the current unit, so the `[node.title]` scan is provably redundant at every present call site: `access.py:135-141` raises `Http404` for an unpublished unit whose viewer cannot see drafts, and both `lesson_unit` (`:717`) and `quiz_unit` (`:1366`) resolve through `get_node_or_404(..., viewer=request.user, ...)`; since `drafts == "hide"` is exactly `not can_see_drafts`, the on-screen unit is always `published`, so `unit_is_visible` is `True` and it is never pruned. Keep the second scan anyway, on the same footing as the `is_author` flag documented at `views.py:544-553` — defence-in-depth for a future render site that reaches these templates **without** the view-level `viewer=` gate. **There is deliberately no test for this branch** (the state is unreachable through the client), and that absence is a decision, not a gap.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_title_math_assets.py`. **Add these two imports to the file's top-level
block now** — Task 4 deliberately does not carry them, because nothing in Task 4 uses them and
its `ruff check --fix` step would strip them as F401 before the commit, leaving Task 6 with a
module-level `NameError` (a whole-file collection error, not the per-assertion failures Step 2
predicts):

```python
from tests.helpers_title_math import MATHS_TITLE
from tests.helpers_title_math import make_title_course
```

Then the tests:

```python
# =============================================================================
# The gate: pages that already compute has_math
# =============================================================================


def _assert_katex_present(body):
    assert KATEX_JS in body, "KaTeX script missing"
    assert KATEX_CSS in body, "KaTeX stylesheet missing"


def _assert_katex_absent(body):
    assert KATEX_JS not in body
    assert KATEX_CSS not in body


def _lesson_url(course, unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


def test_lesson_loads_katex_for_a_maths_title_on_the_unit_itself(client):
    course, unit, _n = make_title_course(maths_on="unitA")
    login_student(client, course)
    _assert_katex_present(client.get(_lesson_url(course, unit)).content.decode())


def test_lesson_loads_no_katex_when_nothing_carries_maths(client):
    course, unit, _n = make_title_course(maths_on="none")
    login_student(client, course)
    _assert_katex_absent(client.get(_lesson_url(course, unit)).content.decode())


def test_lesson_loads_katex_for_a_maths_title_sections_away(client):
    """THE TREE TRAP. On a unit page the contents tree is unit_nav["tree"], which
    build_unit_nav sets to the ENTIRE course outline, and _unit_tree_node.html
    renders all of it into the DOM whether collapsed or not. Scanning only unit /
    prev / next leaves a maths title three sections away rendering raw -- and it
    fails silently, because the page looks correct for the unit under test.

    This is the assertion that fails if the scan is narrowed. Without it the
    narrowing is invisible."""
    course, unit, nodes = make_title_course(maths_on="far")
    login_student(client, course)
    body = client.get(_lesson_url(course, unit)).content.decode()
    # Precondition: the viewed unit and BOTH its neighbours really are maths-free.
    assert "\\(" not in nodes["unitA"].title
    assert "\\(" not in nodes["unitB"].title
    assert "\\(" not in nodes["part1"].title
    _assert_katex_present(body)


def test_quiz_unit_with_zero_questions_loads_katex_for_a_maths_title(client):
    """The fixture MUST have zero questions: has_math = bool(questions) or ...
    (views.py:1318), so any quiz with a single question already loads KaTeX and
    the positive assertion would be vacuous."""
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    url = reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    _assert_katex_present(client.get(url).content.decode())


def test_quiz_unit_with_zero_questions_and_no_maths_loads_none(client):
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title="Plain quiz",
    )
    login_student(client, course)
    url = reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    _assert_katex_absent(client.get(url).content.decode())


def test_quiz_results_loads_katex_for_a_maths_title(client):
    url = _submitted_quiz_results_url(
        client, unit_title=MATHS_TITLE, stem="<p>Explain plainly.</p>"
    )
    _assert_katex_present(client.get(url).content.decode())


def test_quiz_results_loads_no_katex_without_maths(client):
    url = _submitted_quiz_results_url(
        client, unit_title="Plain", stem="<p>Explain plainly.</p>"
    )
    _assert_katex_absent(client.get(url).content.decode())


def test_review_submission_loads_katex_for_a_maths_title(client):
    url = _review_url(client, unit_title=MATHS_TITLE, stem="<p>Explain plainly.</p>")
    _assert_katex_present(client.get(url).content.decode())


def test_review_submission_loads_no_katex_without_maths(client):
    url = _review_url(client, unit_title="Plain", stem="<p>Explain plainly.</p>")
    _assert_katex_absent(client.get(url).content.decode())


def test_the_title_widening_is_applied_at_all_three_unit_render_sites():
    """The ONLY detector for the _quiz_render_feedback site.

    Two of the three sites are covered behaviourally by the tests above; the
    third cannot be -- its fixture necessarily has >=1 question, so
    has_math = bool(questions) is already True and a gate assertion is vacuous.
    Without this, an implementation that widens two of three ships fully green.

    Counts CALLS, not the statement body: the helper's own `def` line and its
    docstring do not match `_widen_has_math_for_titles(ctx, node)`, so this does
    not fall into the regexes-match-docstrings trap. It is a source assertion by
    necessity, not by preference."""
    import ast
    import inspect

    from courses import views

    src = inspect.getsource(views)
    tree = ast.parse(src)
    callers = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_widen_has_math_for_titles"
            for n in ast.walk(fn)
        )
    }
    assert callers == {
        "full_lesson_render_context",
        "quiz_unit",
        "_quiz_render_feedback",
    }, f"title widening applied at the wrong set of render sites: {sorted(callers)}"
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_assets.py -v -k "lesson or quiz or review or widening"
```

`or widening` is not optional: without it `test_the_title_widening_is_applied_at_all_three_unit_render_sites` — the **only** detector for the `_quiz_render_feedback` site — is silently deselected from the red run.

Expected: every **positive** assertion FAILS (no KaTeX for a title-only maths page), the call-site test FAILS (the helper does not exist yet), and every negative one passes. The filter also re-runs some Task-4 tests, which stay green.

- [ ] **Step 3: Add the imports**

`courses/views.py` — beside the existing `from courses.htmlsandbox import has_math_delimiters` (`:33`) and the `courses.rollups` block (`:80-84`), respecting `force-single-line` and isort order:

```python
from courses.htmlsandbox import titles_have_math
```
```python
from courses.rollups import tree_titles_have_math
```

`courses/views_review.py` — beside `from courses.htmlsandbox import has_math_delimiters` (`:14`):

```python
from courses.htmlsandbox import titles_have_math
```

- [ ] **Step 4: Widen the four `courses/views.py` sites**

**The shared helper.** The same widening lands at **three** render sites; two are covered by
the tests above and the third (`_quiz_render_feedback`) is not coverable behaviourally — its
fixture necessarily has ≥1 question, so `has_math = bool(questions)` is already `True` and any
gate assertion there is vacuous. Three hand-copied statements with one of them undetectable is
exactly how a two-of-three implementation ships fully green. Extract the statement once, so
"was it applied at every site?" becomes a countable question:

```python
def _widen_has_math_for_titles(ctx, node):
    """OR the node-title scan into ctx["has_math"] on a unit-page context.

    Call AFTER ctx["unit_nav"] is assigned -- the tree it scans is that value.

    The contents tree in the DOM is the WHOLE course outline (build_unit_nav sets
    unit_nav["tree"] to it), so one maths title anywhere in the course needs KaTeX
    on every unit page of that course.

    The second scan (`[node.title]`) is REDUNDANT TODAY and kept deliberately --
    the same reasoning as the is_author flag in full_lesson_render_context: every
    present caller resolves `node` through get_node_or_404(..., viewer=user, ...),
    which 404s an unpublished unit before this render is reached, so the on-screen
    unit is always in the tree already. It is defence-in-depth for a future render
    site that reaches these templates WITHOUT that view-level gate, which would
    otherwise silently lose the current unit's own title. Do not delete it as dead
    code without re-verifying that every caller still carries the gate.
    """
    ctx["has_math"] = (
        ctx["has_math"]
        or tree_titles_have_math(ctx["unit_nav"]["tree"])
        or titles_have_math([node.title])
    )
```

Place it beside `full_lesson_render_context` in `courses/views.py`, then call it at all three
sites, in each case on the line **immediately after** `ctx["unit_nav"] = build_unit_nav(...)`:

| Site | Function | Call line goes after |
| --- | --- | --- |
| Lesson | `full_lesson_render_context` (`:529`) | `:556` |
| Quiz | `quiz_unit` (`:1365`) | `:1385` |
| Quiz, no-JS feedback | `_quiz_render_feedback` (`:1402`) | `:1418` |

The call is identical at all three: `_widen_has_math_for_titles(ctx, node)`.

At the third site, add this above the call:

```python
    # The quiz page renders TWICE: this no-JS answer path re-renders
    # quiz_unit.html with its own context, so applying the widening only in
    # quiz_unit would leave this render on the un-widened flag. Masked today
    # because has_math = bool(questions) or ... and this path is reachable only
    # when the quiz HAS questions -- but that over-inclusiveness is an "accepted
    # tradeoff" the code comment says may be tightened later, at which point the
    # omission goes live. Knowingly uncovered BEHAVIOURALLY (a gate assertion
    # here would be vacuous); pinned instead by the call-site count test.
```

**Quiz results** — in `quiz_results`, after the `for el in node.elements...` loop's last line (`:1601`) and **before** `ctx = {` (`:1602`), at function-body indentation:

```python
    has_math = has_math or titles_have_math([node.title])
```

- [ ] **Step 5: Widen `_review_context`**

`courses/views_review.py` — the returned dict already carries `has_math`; OR into it:

```python
        # KaTeX is needed if the stem, the student's answer, or the UNIT TITLE
        # carries math.
        "has_math": any(
            has_math_delimiters(row["question"].stem)
            or has_math_delimiters(row["answer_text"] or "")
            for row in rows
        )
        or titles_have_math([submission.unit.title]),
```

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_assets.py -v
```

Expected: all pass.

- [ ] **Step 7: Falsify — observe RED against the narrowing mutant**

The failure mode is *"the scan was narrowed to the unit and its neighbours"*. Replace the lesson statement with:

```python
    nav = ctx["unit_nav"]
    near = [node.title]
    if nav["prev"] is not None:
        near.append(nav["prev"].title)
    if nav["next"] is not None:
        near.append(nav["next"].title)
    ctx["has_math"] = ctx["has_math"] or titles_have_math(near)   # MUTANT
```

Expected: `test_lesson_loads_katex_for_a_maths_title_sections_away` FAILS; `test_lesson_loads_katex_for_a_maths_title_on_the_unit_itself` still passes — which is exactly why the trap test has to exist.

Second mutant, the *quiz-results* site: delete the `has_math = has_math or titles_have_math([node.title])` line → `test_quiz_results_loads_katex_for_a_maths_title` FAILS.

Third mutant, `_review_context`: delete the `or titles_have_math(...)` clause → `test_review_submission_loads_katex_for_a_maths_title` FAILS.

Fourth mutant, the *undetectable* site — delete the `_widen_has_math_for_titles(ctx, node)` call from `_quiz_render_feedback` **only** → `test_the_title_widening_is_applied_at_all_three_unit_render_sites` FAILS and **every other test in the suite still passes**. That asymmetry is the entire reason the call-site test exists; if it does not hold, the test is not doing its job.

Revert each.

- [ ] **Step 8: Regression-check and commit**

```bash
uv run ruff check --fix courses/views.py courses/views_review.py tests/test_title_math_assets.py
uv run ruff format courses/views.py courses/views_review.py tests/test_title_math_assets.py
uv run pytest tests/test_title_math_assets.py tests/test_review_views.py \
              tests/test_consumption_pages.py tests/test_courses_views.py -v
git add courses/views.py courses/views_review.py tests/test_title_math_assets.py
git commit -m "feat(courses): widen has_math to node titles on the lesson, quiz and review pages"
```

---

## Task 7: Gate the outline and course-results pages

**Files:**
- Modify: `courses/views.py` — `course_outline` (`:576`), `course_results` (`:610`)
- Modify: `templates/courses/outline.html:4` (+ new `extra_js` block)
- Modify: `templates/courses/course_results.html:4` (+ new `extra_js` block)
- Test: `tests/test_title_math_assets.py` (append)

**Interfaces:**
- Consumes: `titles_have_math`, `tree_titles_have_math`, both partials.
- Produces: `has_math` in both templates' contexts.

**The negative assertion has no force on these pages.** Neither computes `has_math` today, and `{% if has_math %}` on a missing variable is silently false — so "no maths ⇒ no KaTeX" passes trivially even if the view change is omitted entirely and only the template change lands. **Only the positive assertion has force here, and its falsification mutant must remove the view's OR, not the template's guard.**

**Assert the stylesheet, not only the script.** An implementation that adds `_katex_js.html` but forgets `_katex_css.html` passes a script-only suite entirely green while KaTeX renders with no stylesheet — overlapping glyphs and fallback fonts, i.e. visibly broken rather than merely unstyled. Two blocks are added per template and only one is load-bearing for a script-only test.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_title_math_assets.py`:

```python
# =============================================================================
# The gate: pages that gain has_math (outline + course results)
# =============================================================================


def test_course_outline_loads_katex_for_a_maths_title(client):
    course, _unit, _n = make_title_course(maths_on="far")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    _assert_katex_present(client.get(url).content.decode())


def test_course_outline_loads_katex_for_a_maths_group_title(client):
    """The outline renders group titles too (_outline_node.html:21), and
    build_outline's tree is what the scan walks -- so a GROUP-only maths title
    must arm the gate."""
    course, _unit, _n = make_title_course(maths_on="group")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    _assert_katex_present(client.get(url).content.decode())


def test_course_outline_loads_no_katex_without_maths(client):
    course, _unit, _n = make_title_course(maths_on="none")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    _assert_katex_absent(client.get(url).content.decode())


def _course_results_url_with_quiz_title(client, title):
    course = CourseFactory()
    ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=title,
    )
    login_student(client, course)
    return reverse("courses:course_results", kwargs={"slug": course.slug})


def test_course_results_loads_katex_for_a_maths_row_title(client):
    url = _course_results_url_with_quiz_title(client, MATHS_TITLE)
    body = client.get(url).content.decode()
    # A quiz with no submission still renders: build_course_results appends a
    # "not_started" row for every quiz unit (rollups.py:369-380).
    assert MATHS_TITLE in body, "the results row did not render"
    _assert_katex_present(body)


def test_course_results_loads_no_katex_without_maths(client):
    url = _course_results_url_with_quiz_title(client, "Plain quiz")
    _assert_katex_absent(client.get(url).content.decode())
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_assets.py -v -k "outline or course_results"
```

Expected: the three positive assertions FAIL; the two negative ones pass trivially.

- [ ] **Step 3: Widen the two views**

`courses/views.py` — `course_outline` (`:576`), immediately before `return render(...)`:

```python
    # The whole outline is in the DOM, so scan the whole tree.
    has_math = tree_titles_have_math(outline)
```

and add `"has_math": has_math,` to the context dict.

`course_results` (`:610`), immediately before `return render(...)`:

```python
    # build_course_results builds "rows" with rows.append (rollups.py:369, :383,
    # :399), so it is a real list -- scanning it here and then passing it to
    # the template
    # iterates it twice safely. Were it a generator, the scan would exhaust it and
    # the page would render EMPTY, a silent severe failure no test here would
    # catch, which is why the return type is pinned rather than assumed.
    has_math = titles_have_math(r["unit"].title for r in summary["rows"])
```

and add `"has_math": has_math` to the context dict:

```python
        {"course": course, "summary": summary, "has_math": has_math},
```

- [ ] **Step 4: Add the guards and includes to both templates**

`templates/courses/outline.html` — line 4 gains the CSS include (keep the existing `{{ block.super }}`; it is pre-existing and **inert** — `base.html:49` is an empty block and base's own stylesheets are at `:44-46`, *outside* it — and it is preserved purely to keep the diff minimal):

```
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'notes/css/notes.css' %}"><link rel="stylesheet" href="{% static 'tags/css/tags.css' %}">{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
```

and a **new** `extra_js` block, appended after the existing `{% endblock %}` for `content`:

```
{% block extra_js %}{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

`templates/courses/course_results.html` — line 4 (no `{{ block.super }}` here; leave the asymmetry alone):

```
{% block extra_css %}<link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
```

plus a new `extra_js` block at the end of the file:

```
{% block extra_js %}{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

> Neither template needs `{% load static %}` added for the partials' sake — the partials
> self-load it, and a template that only `{% include %}`s them never evaluates `{% static %}`
> itself. (Both happen to load it already for their own links.)

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_assets.py -v
```

- [ ] **Step 6: Falsify — the mutant must be the view's OR, not the template's guard**

1. Delete `has_math = tree_titles_have_math(outline)` and its context key from `course_outline` → both outline positives FAIL. (Deleting the template's `{% if has_math %}` instead would make the *negative* fail — that is the wrong mutant here, because the negative has no force on this page.)
2. Delete only the `_katex_css.html` include from `outline.html` (leaving the JS one) → `test_course_outline_loads_katex_for_a_maths_title` FAILS on the stylesheet assertion. This is the "two blocks, only one load-bearing" wiring gap.
3. Change `course_results`'s scan to `titles_have_math([course.title])` → both course-results assertions behave wrongly (positive FAILS).

Revert each.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix courses/views.py tests/test_title_math_assets.py
uv run ruff format courses/views.py tests/test_title_math_assets.py
uv run pytest tests/test_title_math_assets.py tests/test_courses_views.py -v
git add courses/views.py templates/courses/outline.html \
        templates/courses/course_results.html tests/test_title_math_assets.py
git commit -m "feat(courses): load KaTeX for maths titles on the outline and results pages"
```

---

## Task 8: Gate the analytics matrix, breakdown and review queue

**Files:**
- Modify: `courses/views_analytics.py` — `analytics_matrix` (`:74`), `analytics_student` (`:224`)
- Modify: `courses/views_review.py` — `review_queue` (`:110`)
- Modify: `templates/courses/manage/analytics_matrix.html` (new `extra_css` block; existing `extra_js` at `:191`)
- Modify: `templates/courses/manage/analytics_student.html` (both blocks new)
- Modify: `templates/courses/manage/review_queue.html` (both blocks new)
- Test: `tests/test_title_math_assets.py` (append)

**Interfaces:**
- Consumes: `titles_have_math`, `tree_titles_have_math`, both partials.
- Produces: `has_math` in three more contexts.

**Three shapes that must be written against the real data, not guessed:**

> **On the analytics line numbers, which look like they contradict Task 5.** They do not, and
> nothing here needs "correcting": Task 5 cites the **enclosing opening tags** (`:114` the leaf
> `<a>`, the `<span>` opening at the end of `:115`, `:125` the group `<span>`) because that is
> where the *attribute* goes; this task cites the **title interpolations** (`:115`, `:116`,
> `:126`) because that is what the *scan* must reach. Both sets are the file's current numbers.

1. **Scan `header_rows`, never `columns`.** The titles at `analytics_matrix.html:115,116` (leaf) and `:126` (group) come from `matrix["header_rows"]` — a list of lists of cell dicts each with a `"title"` string, built in `frontier_columns` (`rollups.py:569,584,596`, assembled at `:615`). `matrix["columns"]` is `_public_columns(...)` (`:667`) and holds **leaf columns only**, so a scan over it silently misses every expanded group cell — exactly what line 126 renders.
2. **`build_student_breakdown` returns a dict wrapper, not a tree.** `build_student_breakdown` (`rollups.py:452`) returns `{"student": …, "tree": tree}` at `:472`; `analytics_student.html:12` iterates `breakdown.tree`. Passing `breakdown` itself iterates the dict's keys and raises `TypeError: string indices must be integers` — a 500 on the breakdown page.
3. **`review_queue` binds only `data`.** It unpacks `data["awaiting"]` / `data["in_progress"]` inline in the `render()` call (`:118-126`); there are no `awaiting` / `in_progress` locals, so referring to them is a `NameError`. `pending_reviews_for` materialises both with `list(... .select_related("student", "unit"))` (`review.py:242-246`) and returns two plain lists, so `data["awaiting"] + data["in_progress"]` is a valid list concatenation and the scan touches no database.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_title_math_assets.py`:

```python
# =============================================================================
# The gate: analytics + review queue
# =============================================================================


def _owned_course(client, *, maths_on):
    """A course owned by the logged-in PA, with one enrolled student."""
    pa = make_pa(client)
    course, _unit, nodes = make_title_course(maths_on=maths_on)
    course.owner = pa
    course.save(update_fields=["owner"])
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    return course, student, nodes


def test_analytics_matrix_loads_katex_for_a_maths_leaf_title(client):
    course, _s, _n = _owned_course(client, maths_on="far")
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    _assert_katex_present(client.get(url).content.decode())


def test_analytics_matrix_loads_katex_for_an_expanded_group_title(client):
    """THE GROUP CASE. A maths title on an EXPANDED group node, with every leaf
    column maths-free. This fails if the scan reads matrix["columns"] instead of
    matrix["header_rows"] -- columns holds leaf columns only, so the group cell
    line 126 renders would be silently missed."""
    course, _s, nodes = _owned_course(client, maths_on="group")
    base = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    body = client.get(f"{base}?expand={nodes['part2'].pk}").content.decode()
    # Precondition: every LEAF title is maths-free.
    for key in ("unitA", "unitB", "unitC", "part1"):
        assert "\\(" not in nodes[key].title
    _assert_katex_present(body)


def test_analytics_matrix_loads_no_katex_without_maths(client):
    course, _s, _n = _owned_course(client, maths_on="none")
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    _assert_katex_absent(client.get(url).content.decode())


def test_analytics_breakdown_returns_200_and_loads_katex(client):
    """THE SHAPE TEST. A bare smoke assertion suffices for the wrapper mistake:
    passing `breakdown` instead of `breakdown["tree"]` raises TypeError, so this
    catches it rather than shipping a 500."""
    course, student, _n = _owned_course(client, maths_on="far")
    url = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    resp = client.get(url)
    assert resp.status_code == 200
    _assert_katex_present(resp.content.decode())


def test_analytics_breakdown_loads_no_katex_without_maths(client):
    course, student, _n = _owned_course(client, maths_on="none")
    url = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    _assert_katex_absent(client.get(url).content.decode())


def _review_queue_url(client, unit_title):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, order=0,
        title=unit_title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem="<p>Explain plainly.</p>", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"), max_score=Decimal("0"),
    )
    return reverse("courses:manage_review_queue", kwargs={"slug": course.slug})


def test_review_queue_loads_katex_for_a_maths_title(client):
    url = _review_queue_url(client, MATHS_TITLE)
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # Precondition, inline rather than in prose: the submission must actually
    # land in data["awaiting"] (SUBMITTED + an unreviewed [R] question). An empty
    # queue would otherwise read as a scan bug rather than a fixture bug.
    assert MATHS_TITLE in body, "the review-queue row did not render"
    _assert_katex_present(body)


def test_review_queue_loads_no_katex_without_maths(client):
    url = _review_queue_url(client, "Plain quiz")
    _assert_katex_absent(client.get(url).content.decode())
```

> The three URL names are verified against `courses/urls.py`: `manage_review_queue` (`:301`),
> `manage_analytics` (`:322`), `manage_analytics_student` (`:333`, kwargs `slug` +
> `student_pk`).
>
> If `test_review_queue_loads_katex_for_a_maths_title`'s fixture does not actually land the
> submission in `data["awaiting"]` (it must be SUBMITTED **and** have an unreviewed `[R]`
> question), the queue renders empty and the scan finds nothing. Assert the row is present
> first — `assert MATHS_TITLE in resp.content.decode()` — and fix the fixture, not the scan,
> if it is not. `tests/factories.py::make_review_submission` is the reference shape.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_assets.py -v -k "analytics or review_queue"
```

Expected: the four positive assertions FAIL; the negatives pass trivially.

- [ ] **Step 3: Widen the three views**

`courses/views_analytics.py` — add the imports:

```python
from courses.htmlsandbox import titles_have_math
```
```python
from courses.rollups import tree_titles_have_math
```

In `analytics_matrix`, immediately before `return render(...)`:

```python
    # header_rows, NOT columns: `columns` is _public_columns(...) and holds LEAF
    # columns only, so a scan over it silently misses every expanded GROUP cell
    # -- which is exactly what analytics_matrix.html:126 renders.
    has_math = titles_have_math(
        c["title"] for row in matrix["header_rows"] for c in row
    )
```

and add `"has_math": has_math,` to the context dict.

In `analytics_student`, immediately before `return render(...)`:

```python
    # build_student_breakdown returns a DICT WRAPPER, {"student": …, "tree": …};
    # passing `breakdown` itself would iterate the dict's keys and raise
    # TypeError -- a 500 on this page.
    has_math = tree_titles_have_math(breakdown["tree"])
```

and add `"has_math": has_math,` to the context dict.

`courses/views_review.py` — in `review_queue`, immediately before `return render(...)`:

```python
    # `data` is the only local: awaiting/in_progress are unpacked inline in the
    # render() call below, so there are no locals of those names. Both are plain
    # lists (pending_reviews_for materialises them with list(...select_related)),
    # so the concatenation is valid and the scan touches no database.
    has_math = titles_have_math(
        s.unit.title for s in data["awaiting"] + data["in_progress"]
    )
```

and add `"has_math": has_math,` to the context dict.

- [ ] **Step 4: Add the blocks to the three templates**

`templates/courses/manage/analytics_matrix.html` — it has an `extra_js` block at `:191` but no `extra_css`. **Do the `extra_js` edit FIRST**, so the second edit's line number does not drift: inserting the `extra_css` block near the top pushes `{% block extra_js %}` from `:191` to `:192`, and this is a 196-line region dense with `<script>` tags where landing one line off is easy and quiet.

1. Add the include inside the existing `extra_js` block, as its first line after `{% block extra_js %}` (**`:191`, pre-edit**):

```
  {% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}
```

2. Then insert the new `extra_css` block immediately after line 3 (`{% block head_title %}…{% endblock %}`):

```
{% block extra_css %}{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
```

`templates/courses/manage/analytics_student.html` — **both** blocks are new. Insert after line 3:

```
{% block extra_css %}{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
```

and append at end of file:

```
{% block extra_js %}{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

`templates/courses/manage/review_queue.html` — **both** blocks are new; identical edits (after line 3, and at end of file).

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_assets.py -v
```

- [ ] **Step 6: Falsify — observe RED against the three shape mutants**

1. *Scan `columns` instead of `header_rows`*: `has_math = titles_have_math(c["title"] for c in matrix["columns"])` → `test_analytics_matrix_loads_katex_for_an_expanded_group_title` FAILS while `..._for_a_maths_leaf_title` still passes. That asymmetry is the whole point of the group fixture.
2. *Pass the wrapper*: `tree_titles_have_math(breakdown)` → `test_analytics_breakdown_returns_200_and_loads_katex` FAILS with a 500 / `TypeError`.
3. *Refer to a non-existent local*: `titles_have_math(s.unit.title for s in awaiting + in_progress)` → `test_review_queue_loads_katex_for_a_maths_title` FAILS with `NameError`.
4. *Forget the CSS block* on `analytics_student.html` → its positive test FAILS on the stylesheet assertion.

Revert each.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix courses/views_analytics.py courses/views_review.py tests/test_title_math_assets.py
uv run ruff format courses/views_analytics.py courses/views_review.py tests/test_title_math_assets.py
uv run pytest tests/test_title_math_assets.py tests/test_analytics_views.py tests/test_review_views.py -v
git add courses/views_analytics.py courses/views_review.py \
        templates/courses/manage/analytics_matrix.html \
        templates/courses/manage/analytics_student.html \
        templates/courses/manage/review_queue.html \
        tests/test_title_math_assets.py
git commit -m "feat(courses): load KaTeX for maths titles on the analytics and review-queue pages"
```

---

## Task 9: Gate the notes page, the tags hub and the tags panel

**Files:**
- Modify: `notes/views.py` — `course_notes` (`:54`)
- Modify: `tags/views.py` — `my_tags` (`:85`), `tag_recolor` (`:120`), `_add_error` (`:61`)
- Modify: `notes/templates/notes/course_notes.html:4,27`
- Modify: `tags/templates/tags/my_tags.html:4` (+ new `extra_js`)
- Modify: `tags/templates/tags/panel_page.html` (both blocks new)
- Test: `tests/test_title_math_assets.py` (append)

**Interfaces:**
- Consumes: `titles_have_math`, both partials.
- Produces: `has_math` in three more contexts (four render sites).

**Three traps specific to this task:**

1. **Bind a local first, at three sites.** `course_notes` passes `services.course_notes(...)` inline into the dict, and both tags-hub sites pass `services.units_by_tag(request.user)` inline — so `units` / `tags_by_tag` do **not** exist as locals. Bind, scan, then pass the same local into the context. Both services return real lists (`notes/services.py:98` a `list` of `{"unit": ContentNode, "groups": …}`; `tags/services.py:209` a `[(Tag, {Course: [unit]})]`), so iterating each twice is safe. **Were either a generator the scan would exhaust it and the page would render empty** — a silent, severe failure no test here would catch, which is why the return types are pinned rather than assumed.
2. **`tags_by_tag`'s shape, stated so it is not re-derived from the template.** `units_by_tag` returns `[(Tag, {Course: [unit, ...]})]`. The `{% for course, units in grouped.items %}` at `_tag_section.html:21` is the **inner** loop over one tag's `grouped` dict — translating it directly against `tags_by_tag` yields `for course, units in tags_by_tag`, which unpacks `(tag, grouped)` into `(course, units)` and then iterates a dict's keys, silently scanning `Course` objects instead of units. Use the literal generator below.
3. **The tags hub renders twice.** `tags/my_tags.html` is rendered by `my_tags` (`:88`) **and** inside `tag_recolor`'s `ValidationError` branch (`:127`), which rebuilds the context inline. Unlike the lesson and review pages there is no shared helper here, so the scan must be applied at **both** sites — otherwise a recolor validation error re-renders the hub with no `has_math` and shows raw delimiters. **That failure is live today, not masked by anything**, so its gate assertion is required, driven through the invalid-colour POST that reaches `tags/views.py:125`.

**The tags panel is unreachable by GET.** `tags/views.py:69` reaches `panel_page.html` only through `_add_error`, i.e. a **non-fragment POST that fails validation**, returning 422. Drive the invalid-tag no-JS POST (empty `name`, no `tag_pk`), which hits the `_("Enter a tag name or pick a tag.")` branch at `tags/views.py:53-55`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_title_math_assets.py`:

```python
# =============================================================================
# The gate: notes + tags (four render sites across three templates)
# =============================================================================


def _course_notes_url_with_unit_title(client, title):
    from notes.models import Note

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=title,
    )
    student = login_student(client, course)
    Note.objects.create(author=student, unit=unit, body="a note")
    return reverse("notes:course_notes", kwargs={"slug": course.slug})


def test_course_notes_loads_katex_for_a_maths_unit_title(client):
    url = _course_notes_url_with_unit_title(client, MATHS_TITLE)
    resp = client.get(url)
    assert resp.status_code == 200
    assert MATHS_TITLE in resp.content.decode(), "the notes row did not render"
    _assert_katex_present(resp.content.decode())


def test_course_notes_loads_no_katex_without_maths(client):
    url = _course_notes_url_with_unit_title(client, "Plain lesson")
    _assert_katex_absent(client.get(url).content.decode())


def _tagged_unit(client, title):
    from tags import services as tag_services

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=title,
    )
    student = login_student(client, course)
    tag_services.tag_unit(student, unit, "algebra")
    return course, unit, student


def test_tags_hub_loads_katex_for_a_maths_unit_title(client):
    _c, _u, _s = _tagged_unit(client, MATHS_TITLE)
    resp = client.get(reverse("tags:my_tags"))
    assert resp.status_code == 200
    assert MATHS_TITLE in resp.content.decode(), "the tagged unit did not render"
    _assert_katex_present(resp.content.decode())


def test_tags_hub_loads_no_katex_without_maths(client):
    _c, _u, _s = _tagged_unit(client, "Plain lesson")
    _assert_katex_absent(client.get(reverse("tags:my_tags")).content.decode())


def test_tags_hub_recolor_error_branch_also_loads_katex(client):
    """THE SECOND RENDER SITE. tag_recolor's ValidationError branch rebuilds the
    hub context inline, with no shared helper -- so "one test per gate-table row"
    is satisfiable by wiring only my_tags while this branch still ships raw
    delimiters. Unlike the no-JS quiz-feedback case, that failure is LIVE today.

    422, not 200: the branch renders with status=422 (tags/views.py:133) and that
    status must survive the refactor."""
    from tags.models import Tag

    _c, _u, student = _tagged_unit(client, MATHS_TITLE)
    tag = Tag.objects.filter(author=student).first()
    resp = client.post(
        reverse("tags:tag_recolor", kwargs={"tag_pk": tag.pk}),
        {"color": "not-a-real-colour"},
    )
    assert resp.status_code == 422
    body = resp.content.decode()
    assert MATHS_TITLE in body, "the error branch did not re-render the hub"
    _assert_katex_present(body)


def _tags_panel_response(client, title):
    """panel_page.html is reachable ONLY through _add_error: a NON-fragment POST
    that fails validation, returning 422. A plain client.get() cannot reach it."""
    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, order=0,
        title=title,
    )
    login_student(client, course)
    return client.post(
        reverse(
            "tags:tag_add", kwargs={"slug": course.slug, "node_pk": unit.pk}
        ),
        {"name": ""},          # neither a name nor a tag_pk -> ValidationError
    )


def test_tags_panel_error_page_loads_katex_for_a_maths_title(client):
    resp = _tags_panel_response(client, MATHS_TITLE)
    assert resp.status_code == 422
    _assert_katex_present(resp.content.decode())


def test_tags_panel_error_page_loads_no_katex_without_maths(client):
    resp = _tags_panel_response(client, "Plain lesson")
    assert resp.status_code == 422
    _assert_katex_absent(resp.content.decode())
```

> All three shapes are verified: `notes.models.Note` takes `author`, `unit`, `body`
> (`element` is nullable — an unanchored note is fine here);
> `tags.services.tag_unit(author, unit, name)` (`tags/services.py:108`); and
> `notes.services.course_notes` **omits units with no notes**, which is why the fixture
> creates one.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_assets.py -v -k "notes or tags"
```

Expected: the four positive assertions FAIL; the negatives pass trivially.

- [ ] **Step 3: Widen `notes/views.py`**

Add the import:

```python
from courses.htmlsandbox import titles_have_math
```

and rewrite `course_notes` (`:54`) so `units` is a local:

```python
@login_required
def course_notes(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    drafts = "keep" if can_see_drafts(request.user, course) else "hide"
    # Bound to a local first: the scan and the template both need it. Safe to
    # iterate twice -- services.course_notes returns a real list. Were it a
    # generator the scan would exhaust it and the page would render EMPTY.
    units = services.course_notes(request.user, course, drafts=drafts)
    has_math = titles_have_math(r["unit"].title for r in units)
    return render(
        request,
        "notes/course_notes.html",
        {"course": course, "units": units, "has_math": has_math},
    )
```

- [ ] **Step 4: Widen `tags/views.py` at three sites**

Add the import:

```python
from courses.htmlsandbox import titles_have_math
```

Add a module-level helper so the hub's two render sites cannot drift apart:

```python
def _hub_context(user):
    """The tags-hub context, shared by my_tags and tag_recolor's error branch.

    THE HUB RENDERS TWICE and there is no other shared seam, so without this the
    scan has to be applied at both sites or a recolor validation error
    re-renders the hub with no has_math and shows raw delimiters.

    tags_by_tag is [(Tag, {Course: [unit, ...]})] -- a real list, so scanning it
    here and passing it on iterates it twice safely. Note the nesting: a direct
    translation of _tag_section.html's `{% for course, units in grouped.items %}`
    would unpack (tag, grouped) into (course, units) and silently scan Course
    objects instead of units.
    """
    tags_by_tag = services.units_by_tag(user)
    return {
        "tags_by_tag": tags_by_tag,
        "palette": TAG_PALETTE,
        # Both current render sites pass the same value; it stays in the shared
        # context so neither can drift.
        "hub_tab": "manage_tags",
        "has_math": titles_have_math(
            u.title
            for _tag, grouped in tags_by_tag
            for units in grouped.values()
            for u in units
        ),
    }
```

`my_tags` (`:85`) becomes:

```python
@login_required
def my_tags(request):
    return render(request, "tags/my_tags.html", _hub_context(request.user))
```

`tag_recolor`'s `except ValidationError:` branch (`:124-134`) — replace the inline dict with the shared helper. **The `status=422` is load-bearing and must survive**; the branch's three existing keys (`tags_by_tag`, `palette`, `hub_tab`) are exactly what `_hub_context` now returns:

```python
    except ValidationError:
        return render(
            request, "tags/my_tags.html", _hub_context(request.user), status=422
        )
```

`_add_error` (`:61`), after `ctx.update(...)` and before `return render(...)` at `:69`:

```python
    ctx["has_math"] = titles_have_math([unit.title])
```

- [ ] **Step 5: Add the blocks and includes to the three templates**

`notes/templates/notes/course_notes.html` — **both blocks already exist**; only the includes are added. Line 4:

```
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'notes/css/notes.css' %}">{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
```

line 27:

```
{% block extra_js %}{{ block.super }}<script src="{% static 'notes/js/notes.js' %}" defer></script>{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

`tags/templates/tags/my_tags.html` — `extra_css` exists (line 4); `extra_js` is new:

```
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'tags/css/tags.css' %}">{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
```

and appended at end of file:

```
{% block extra_js %}{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

`tags/templates/tags/panel_page.html` — **both blocks new**. Insert after line 2 (`{% load i18n %}`):

```
{% block extra_css %}{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
```

and append at end of file:

```
{% block extra_js %}{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_assets.py -v
```

- [ ] **Step 7: Falsify — observe RED against the second-render-site and shape mutants**

1. *Wire only `my_tags`*: revert `tag_recolor`'s branch to its inline dict without `has_math` → `test_tags_hub_recolor_error_branch_also_loads_katex` FAILS while `test_tags_hub_loads_katex_for_a_maths_unit_title` still passes. That asymmetry is why the hub needs two assertions.
2. *Wrong nesting*: change the hub scan to `titles_have_math(u.title for _c, u in tags_by_tag)` → `AttributeError` / a false negative; the hub positive FAILS.
3. *Forget the local bind*: `has_math = titles_have_math(r["unit"].title for r in services.course_notes(...))` while still passing a **second** `services.course_notes(...)` call inline — this happens to work but doubles the query cost; instead apply the genuinely dangerous mutant: pass the *same generator* to both the scan and the template (wrap `units` in `(r for r in units)`) → `test_course_notes_loads_katex_for_a_maths_unit_title` FAILS on its `MATHS_TITLE in body` precondition, because the page renders empty.
4. *Forget `_add_error`* → both tags-panel assertions behave wrongly (positive FAILS).

Revert each.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix notes/views.py tags/views.py tests/test_title_math_assets.py
uv run ruff format notes/views.py tags/views.py tests/test_title_math_assets.py
uv run pytest tests/test_title_math_assets.py tests/test_tags_views.py \
              tests/test_tags_notes_hub.py tests/test_notes_views.py -v
git add notes/views.py tags/views.py notes/templates/notes/course_notes.html \
        tags/templates/tags/my_tags.html tags/templates/tags/panel_page.html \
        tests/test_title_math_assets.py
git commit -m "feat(tags,notes): load KaTeX for maths titles on the notes, hub and panel pages"
```

> Both regression files exist. Add `tests/test_tags_notes_hub.py` to that run too — it is the
> suite most likely to notice the `my_tags` / `tag_recolor` refactor (`hub_tab`, the 422).

---

## Task 10: CSS normalisation

**Files:**
- Modify: `core/static/core/css/app.css` (append at end of file)
- Modify: `courses/static/courses/css/courses.css` (append at end of file)
- Test: `tests/test_title_math_css.py` (create)

**Interfaces:**
- Consumes: the `[data-math-title]` contract from Task 5.
- Produces: nothing consumed by later tasks; Task 11 **measures** these values and may correct them.

**The overriding invariant — re-apply this check whenever a value changes.** `app.css` is at `base.html:46`; every `katex.min.css` link lands in `{% block extra_css %}` at `:49` or later. **The vendor stylesheet therefore always loads after ours on every page in this change.** At equal specificity KaTeX wins, so every rule below must be *strictly more specific* than the vendor rule it overrides. This is not a property that survives casual editing.

**Which stylesheet, and why not `courses.css`.** Of the twelve distinct templates in the gate table, only five link `courses.css`. The other seven — `outline.html`, `analytics_matrix.html`, `analytics_student.html`, `review_queue.html`, `notes/course_notes.html`, `tags/my_tags.html`, `tags/panel_page.html` — extend `base.html` and link no `courses.css` at all. Putting the global normalisation in `courses.css` would leave every one of those seven, all of which newly gain KaTeX rendering, at an unnormalised `1.21em`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_title_math_css.py`:

```python
"""The [data-math-title] CSS normalisation (spec §3).

Source assertions, not rendering: the MEASURED confirmation of these values is
Task 11's job (screenshots + devtools), and this file only pins that the rules
exist, live in the right stylesheet, and keep their specificity edge over the
vendor rules they override.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "core/static/core/css/app.css"
COURSES_CSS = ROOT / "courses/static/courses/css/courses.css"


def _app():
    return APP_CSS.read_text(encoding="utf-8")


def _courses():
    return COURSES_CSS.read_text(encoding="utf-8")


def test_the_global_normalisation_lives_in_app_css_not_courses_css():
    """Seven of the twelve gate-table templates link NO courses.css -- their rules
    live in app.css / notes.css / tags.css. A courses.css copy would leave all
    seven at an unnormalised 1.21em."""
    # Anchored to a RULE, not a mention: the courses.css block this task appends
    # is a long comment that cross-references the app.css block, and a bare
    # `not in` substring check would go red for a documentation edit with no
    # behavioural change.
    assert re.search(r"^\s*\[data-math-title\]\s+\.katex\s*\{", _app(), re.M)
    assert not re.search(r"^\s*\[data-math-title\]\s+\.katex", _courses(), re.M)


def test_font_size_weight_and_style_are_all_restored():
    """The vendored rule is `.katex{font:normal 1.21em KaTeX_Main,...}` -- a font
    SHORTHAND, which resets every unset font longhand, font-weight among them.
    Restoring only font-size leaves a maths run at `normal` weight inside a bold
    .lesson-unit__title / .result__title / .editor-head__title, visibly lighter
    than the prose beside it."""
    block = re.search(
        r"\[data-math-title\]\s+\.katex\s*\{([^}]*)\}", _app()
    )
    assert block, "the [data-math-title] .katex rule is missing"
    body = block.group(1)
    assert "font-size: inherit" in body
    assert "font-weight: inherit" in body
    assert "font-style: inherit" in body


def test_line_height_is_not_inherited_by_the_global_rule():
    """Deliberately NOT inherited here -- the compact-chrome clamps own it."""
    block = re.search(r"\[data-math-title\]\s+\.katex\s*\{([^}]*)\}", _app())
    assert "line-height" not in block.group(1)


def test_the_display_wrapper_is_neutralised():
    """`.katex-display{display:block;margin:1em 0;text-align:center}` would turn a
    \\[...\\] title into a centred block with 1em margins inside a nav button, a
    breadcrumb <li> or a tree row. Since \\[...\\] in titles is supported, this is
    required, not optional."""
    block = re.search(
        r"\[data-math-title\]\s+\.katex-display\s*\{([^}]*)\}", _app()
    )
    assert block, "the .katex-display wrapper override is missing"
    body = block.group(1)
    assert "display: inline-block" in body
    assert "margin: 0" in body
    assert "text-align: inherit" in body


def test_the_display_child_override_uses_the_child_combinator():
    """The vendor's `.katex-display>.katex` is (0,2,0) -- IDENTICAL to
    `[data-math-title] .katex`. Overriding it needs the child combinator to reach
    (0,3,0); at equal specificity KaTeX wins, because katex.min.css always loads
    AFTER app.css (base.html:46 vs the extra_css block at :49)."""
    assert re.search(
        r"\[data-math-title\]\s+\.katex-display\s*>\s*\.katex\s*\{", _app()
    ), "the child override is missing or lost its > combinator"


def test_both_display_rules_are_present_neither_alone_suffices():
    """Neutralising only the CHILD is wrong, and that is the half that matters: a
    display:block WRAPPER is still a block-level box -- inside
    `<h1>Rozwiaz \\[x^2\\] teraz</h1>` it splits the inline content into anonymous
    block boxes and renders on three lines. `margin: 0` removes the gaps but NOT
    the line break."""
    css = _app()
    assert re.search(r"\[data-math-title\]\s+\.katex-display\s*\{", css)
    assert re.search(r"\[data-math-title\]\s+\.katex-display\s*>\s*\.katex\s*\{", css)


def _rule_body(css, selector):
    """The declaration block of the (possibly grouped) rule `selector` heads.

    Returns None if `selector` never heads a rule. Matching up to the `{` --
    allowing a comma, i.e. the selector being one member of a grouped rule --
    means a documentation edit can never satisfy it: both stylesheets gain long
    comment blocks naming several of these class names, and they pass today only
    because those comments happen to omit the ` .katex` suffix, which is an
    incidental property rather than a designed one.
    """
    m = re.search(re.escape(selector) + r"\s*[,{][^{}]*\{([^}]*)\}", css)
    return m.group(1) if m else None


def test_the_analytics_clamp_lives_in_app_css_and_actually_clamps():
    """The analytics pages have no courses.css.

    Asserts the DECLARATIONS, not just the selector: a rule with an empty body --
    or one carrying line-height:1.2 -- would satisfy a selector-only check while
    clamping nothing, and the clamp's whole purpose is those two properties. The
    analytics sticky header is the most fragile surface in the change (a cell
    taller than --ahead-h desynchronises every sticky row beneath it)."""
    css = _app()
    for sel in (
        ".analytics__matrix thead th .katex",
        ".breakdown-unit__title .katex",
        ".breakdown-node__title .katex",
    ):
        body = _rule_body(css, sel)
        assert body is not None, f"missing analytics clamp rule: {sel}"
        assert "line-height: 1;" in body, f"{sel} does not clamp line-height"
        assert "vertical-align: baseline" in body, f"{sel} lacks baseline align"


def test_the_unit_chrome_clamp_lives_in_courses_css_and_actually_clamps():
    css = _courses()
    for sel in (
        ".unit-foot__navtitle .katex",
        ".unit-tree__label .katex",
        ".unit-tree__grouptitle .katex",
        ".unit-crumbs__label .katex",
    ):
        body = _rule_body(css, sel)
        assert body is not None, f"missing unit-chrome clamp rule: {sel}"
        assert "line-height: 1;" in body, f"{sel} does not clamp line-height"
        assert "vertical-align: baseline" in body, f"{sel} lacks baseline align"


def test_the_display_child_override_does_not_touch_white_space():
    """The vendor's `.katex-display>.katex{white-space:nowrap}` must SURVIVE.

    A formula must not break mid-formula, and an <h1> is white-space:normal, so
    `white-space: inherit` here would hand the formula back exactly the wrapping
    the vendor rule prevents. Spec §3's code block says `inherit` while its own
    prose says nowrap is "which we in fact want to keep for a formula" -- the
    prose is right, and this test is what pins it."""
    body = _rule_body(_app(), "[data-math-title] .katex-display > .katex")
    assert body is not None
    assert "white-space" not in body
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_title_math_css.py -v
```

Expected: every test FAILS — no rule exists yet.

- [ ] **Step 3: Add the global normalisation to `app.css`**

Append to `core/static/core/css/app.css`:

```css
/* --- Maths in node titles ([data-math-title], spec 2026-08-10) -------------- */
/* THE OVERRIDING INVARIANT: app.css is base.html:46; every katex.min.css link
   lands in {% block extra_css %} at :49 or later, so THE VENDOR STYLESHEET
   ALWAYS LOADS AFTER OURS on every page in this change. At equal specificity
   KaTeX wins, so each rule below is strictly MORE specific than the vendor rule
   it overrides -- the specificity comments are the check to re-apply whenever a
   value here is corrected.

   These live ONLY here, never in courses.css: seven of the twelve templates that
   newly gain KaTeX rendering link no courses.css at all, and a copy there could
   never match anything these do not already match. */

/* The vendored rule is `.katex{font:normal 1.21em KaTeX_Main,…;line-height:1.2}`
   -- a font SHORTHAND, so it resets every unset font longhand. Restoring only
   font-size leaves a maths run at `normal` weight inside a bold title, visibly
   lighter than the prose beside it. line-height is deliberately NOT inherited:
   the compact-chrome clamps below own that. */
[data-math-title] .katex {                              /* (0,2,0) > (0,1,0) */
  font-size: inherit; font-weight: inherit; font-style: inherit;
}
/* math.js's INLINE_DELIMS maps \[ to display:true, and the vendored
   `.katex-display{display:block;margin:1em 0;text-align:center}` would then turn
   a display-maths TITLE into a centred block with 1em margins inside a nav
   button, a breadcrumb <li> or a tree row.

   THE WRAPPER RULE IS THE LOAD-BEARING ONE: a display:block wrapper is still a
   block-level box, so inside an <h1> that also holds words it splits the inline
   content into anonymous block boxes and renders on three lines. `margin: 0`
   removes the gaps but NOT the line break -- an inline-block child cannot make a
   block parent join the surrounding line box. Once the wrapper is inline-block
   it establishes its own formatting context, so a display:block .katex inside it
   is harmless.

   Display maths is forced inline EVERYWHERE, including the <h1>s where nothing
   is clipped and a centred block would technically fit: a title is a single line
   of prose by definition, and an author writing \[…\] in one is reaching for
   emphasis, not a standalone equation block. One rule, one behaviour. */
[data-math-title] .katex-display {                      /* (0,2,0) > (0,1,0) */
  display: inline-block; margin: 0; text-align: inherit;
}
/* DEFENSIVE, not load-bearing -- see above. It neutralises the vendor's
   text-align:center (a no-op inside a shrink-to-fit box anyway).

   white-space is DELIBERATELY NOT OVERRIDDEN, so the vendor's
   `white-space: nowrap` survives. A formula must not break mid-formula, and an
   <h1> is white-space:normal -- so `white-space: inherit` here would hand the
   formula back exactly the wrapping the vendor rule exists to prevent.
   (KNOWING DEVIATION FROM THE SPEC: §3's code block lists
   `white-space: inherit` while its own prose says nowrap is "which we in fact
   want to keep for a formula". The prose is right and the declaration was
   wrong; the test below pins the prose. Record this in the PR body.)

   The child combinator is REQUIRED: the vendor's `.katex-display>.katex` is
   (0,2,0), identical to `[data-math-title] .katex`, so reaching (0,3,0) is the
   only way to win without relying on source order. */
[data-math-title] .katex-display > .katex {             /* (0,3,0) > (0,2,0) */
  display: inline-block; text-align: inherit;
}

/* The analytics clamp lives here, not in courses.css: neither analytics page
   links it. The matrix header is the most fragile surface in this change --
   .analytics{--ahead-h:2.4rem} and `thead th{position:sticky;height:var(--ahead-h);
   white-space:nowrap}`, with each header row positioned at
   top:calc(var(--ahead-h) * counter0). A title taller than 2.4rem DESYNCHRONISES
   every sticky row beneath it (a layout break, not a cosmetic one), and because
   the cell is nowrap a long maths title WIDENS the column instead of wrapping. */
.analytics__matrix thead th .katex,
.breakdown-unit__title .katex,
.breakdown-node__title .katex { line-height: 1; vertical-align: baseline; }
```

- [ ] **Step 4: Add the unit-chrome clamp to `courses.css`**

Append to `courses/static/courses/css/courses.css`:

```css
/* --- Maths in node titles: the unit-chrome clamp (spec 2026-08-10) ---------- */
/* The GLOBAL normalisation lives in app.css (see the block there); this file
   carries only the clamps for surfaces courses.css owns. KaTeX's line-height:1.2
   survives the global rules, and these four are all tight, single-line or
   line-clamped boxes.

   THE FOUR SURFACES BEHAVE DIFFERENTLY AND MUST NOT BE CONFLATED:
   - .unit-foot__navtitle (:778), .unit-tree__label (:755) and
     .unit-crumbs__label (:848) are single-line clips
     (overflow:hidden;text-overflow:ellipsis;white-space:nowrap). A long maths
     title HARD-CLIPS rather than showing an ellipsis -- text-overflow applies to
     inline text, not to KaTeX's inline-block box. Accepted; it is why the
     title= tooltips are kept useful by strip_math_delimiters.
   - .unit-tree__grouptitle (:702-704) is NOT a single-line clip: it is
     -webkit-box with -webkit-line-clamp:5 plus overflow-wrap:break-word and
     hyphens:auto. Intended behaviour is that the surrounding prose keeps
     wrapping and clamping as today while the formula stays intact on whichever
     line it lands on.
   - The MOBILE DRAWER is a fourth case, not covered here: courses.css:943
     overrides .unit-drawer__list .unit-tree__label to white-space:normal, so at
     <=640px titles WRAP rather than clip, in a title column squeezed to ~98px --
     and an unbreakable KaTeX inline-block is exactly what overflows it and
     paints under the action buttons. Needs its own measurement (see the plan's
     Task 11) before any rule is added for it.

   Also unaddressed on purpose: courses.css:903-907 re-opens .unit-crumbs__label
   under @media print with overflow-wrap:anywhere, which cannot break a KaTeX
   inline-block, so a long maths crumb can still overflow in print. Accepted --
   printing a breadcrumb is marginal and the text is not lost, only over-wide. */
.unit-foot__navtitle .katex,
.unit-tree__label .katex,
.unit-tree__grouptitle .katex,
.unit-crumbs__label .katex { line-height: 1; vertical-align: baseline; }
```

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_title_math_css.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Falsify — observe RED against the specificity and shorthand mutants**

1. *Collapse the child override into the base rule*: delete `[data-math-title] .katex-display > .katex { … }` and fold `display: inline-block` into `[data-math-title] .katex` instead. That selector is **(0,2,0)** — identical to the vendor's `.katex-display>.katex` — and since `katex.min.css` always loads after `app.css`, the vendor wins on source order and the override silently does nothing. Expected: `test_the_display_child_override_uses_the_child_combinator` and `test_both_display_rules_are_present_neither_alone_suffices` FAIL. This is the specificity trap the plan exists to prevent, and the reason the combinator is pinned rather than left to taste.
2. *Drop the wrapper rule*, keeping only the child override → `test_the_display_wrapper_is_neutralised` and `test_both_display_rules_are_present_neither_alone_suffices` FAIL. This is the half that matters visually: a `display:block` wrapper is still a block-level box, so an `<h1>` mixing words and `\[…\]` renders on three lines regardless of what the child does.
3. *Restore only `font-size`*: delete `font-weight: inherit; font-style: inherit;` → `test_font_size_weight_and_style_are_all_restored` FAILS.
4. *Put the global rules in `courses.css` instead* → `test_the_global_normalisation_lives_in_app_css_not_courses_css` FAILS on both assertions.
5. *Add `line-height: 1.2` to the global rule* → `test_line_height_is_not_inherited_by_the_global_rule` FAILS.
6. *Empty the clamp bodies*: keep both clamp selectors but delete their declarations (`… .katex { }`) → both `…_actually_clamps` tests FAIL. Repeat with `line-height: 1.2` in place of `line-height: 1` — same result. A selector-only assertion would have passed both variants while clamping nothing.
7. *Restore `white-space: inherit`* to `[data-math-title] .katex-display > .katex` → `test_the_display_child_override_does_not_touch_white_space` FAILS. This is the spec-deviation guard; if you "fix" the CSS back to the spec's literal code block, this test is what tells you.

Revert each.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix tests/test_title_math_css.py
uv run ruff format tests/test_title_math_css.py
uv run pytest tests/test_title_math_css.py tests/test_consumption_css.py -v
git add core/static/core/css/app.css courses/static/courses/css/courses.css \
        tests/test_title_math_css.py
git commit -m "feat(css): normalise KaTeX sizing and display math inside node titles"
```

---

## Task 11: End-to-end, render cost, and the measured clamp confirmation

**Files:**
- Create: `tests/test_e2e_title_math.py`
- Modify (only if measurement demands it): `core/static/core/css/app.css`, `courses/static/courses/css/courses.css`, `courses/static/courses/js/math.js`
- Modify (only if measurement demands it): `docs/superpowers/specs/2026-08-10-latex-in-unit-titles-design.md` §3, to record the confirmed or corrected values

**Interfaces:**
- Consumes: everything from Tasks 1–10.
- Produces: the measured confirmation the spec requires before the PR opens.

**Why an e2e is required here.** The defect this feature fixes is precisely one a template-level assertion cannot see: the template is correct and the **asset gate** is what fails. Only a real browser proves a `.katex` element actually appears.

- [ ] **Step 1: Write the e2e**

> **Unlike every earlier task, this file is expected GREEN on its first run.** All the
> implementation landed in Tasks 1–10, so there is no RED phase here — the RED evidence for
> these two tests is Step 3's mutant. Do not go hunting for a failure that should not exist.

Create `tests/test_e2e_title_math.py`:

```python
"""Playwright e2e for LaTeX-in-titles: the asset gate, measured in a real browser.

Marked e2e (excluded from the default run; run with -m e2e). Follows
tests/test_e2e_unit_nav.py's harness: _allow_async_unsafe, _login, and the
explicit `@pytest.mark.django_db(transaction=True)` + `browser.new_context()`
idiom rather than the bare `page` fixture -- the marker is what that file uses,
and owning the context is what makes the viewport controllable (this file does
not need a custom viewport today, but diverging from the house idiom for two
tests buys nothing and costs the next reader a double-take).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import EnrollmentFactory
from tests.factories import make_verified_user
from tests.helpers_title_math import make_title_course

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    """Log in via the allauth HTML form. Copied verbatim from
    tests/test_e2e_unit_nav.py:40-46 -- no `.first`, no networkidle wait; the
    subsequent page.goto is the synchronisation point."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_next_unit_title_typesets_in_the_nav_button(browser, live_server):
    """The ONLY maths in the entire course is in the NEXT unit's title. The
    template is correct either way; what fails without the widened gate is that
    the page ships no KaTeX at all -- which is exactly why this cannot be a
    template-level assertion."""
    course, unit_a, _nodes = make_title_course(maths_on="unitB")
    student = make_verified_user(
        username="e2estudent", email="e2estudent@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2estudent")
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit_a.pk}/")
        katex = page.locator(".unit-foot__navtitle .katex")
        katex.first.wait_for(state="attached", timeout=5000)
        assert katex.count() >= 1
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_render_inline_text_main_thread_cost_is_recorded(browser, live_server, capsys):
    """RENDER COST, MEASURED not predicted. renderInlineText calls
    renderMathInElement ONCE PER MATCHED ELEMENT, and a unit page holds the whole
    course outline TWICE (the rail plus the drawer copy at _unit_shell.html:40),
    with every group title marked as well as every unit row.

    MEASURE THE FIRST PASS, NOT A SECOND ONE. math.js is deferred but runs before
    this test's evaluate(), and it replaces the delimiters with KaTeX markup whose
    <annotation> text carries none -- so timing a re-run over the live DOM times a
    walk of a DELIMITER-FREE tree and reports a near-zero number on a fast AND on
    a pathologically slow build. The route below aborts math.js so KaTeX and
    auto-render still load (window.renderMathInElement exists) while the document
    pass never happens, leaving the markup pristine for one real, timed pass.

    Take the element count FROM THE PAGE, never derive it. If the measured time
    exceeds ~50 ms, switch renderInlineText to a single renderMathInElement over a
    common ancestor -- and note that the single-root alternative over document.body
    is NOT the default, because it would typeset every delimiter on the page
    including the edit buffers Path C must keep untouched."""
    course, unit_a, _nodes = make_title_course(maths_on="far")
    student = make_verified_user(
        username="e2eperf", email="e2eperf@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2eperf")
        page.route("**/courses/js/math.js", lambda route: route.abort())
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit_a.pk}/")
        page.wait_for_function(
            "() => typeof window.renderMathInElement === 'function'"
        )
        stats = page.evaluate(
            """() => {
                const els = document.querySelectorAll('[data-math-title]');
                let withMaths = 0;
                els.forEach(el => {
                    if (/\\\\[([]/.test(el.textContent)) withMaths++;
                });
                const t0 = performance.now();
                els.forEach(el => window.renderMathInElement(el, {
                    delimiters: [
                        { left: '\\\\(', right: '\\\\)', display: false },
                        { left: '\\\\[', right: '\\\\]', display: true },
                    ],
                    throwOnError: false,
                }));
                const ms = performance.now() - t0;
                return { count: els.length, withMaths: withMaths, ms: ms,
                         rendered: document.querySelectorAll('.katex').length };
            }"""
        )
    finally:
        ctx.close()
    with capsys.disabled():
        print(
            f"\n[render cost] {stats['count']} marked elements "
            f"({stats['withMaths']} carrying delimiters), first renderInlineText "
            f"pass: {stats['ms']:.1f} ms, produced {stats['rendered']} .katex nodes"
        )
    assert stats["count"] > 0, "no [data-math-title] elements on the page"
    # The pass must have done REAL work -- otherwise the number above is a walk of
    # an already-typeset tree and the whole measurement is vacuous.
    assert stats["withMaths"] > 0, "math.js not blocked; DOM already typeset"
    assert stats["rendered"] > 0, "the timed pass produced no KaTeX output"
```

- [ ] **Step 2: Run the e2e and verify the first test's premise**

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_title_math.py -m e2e -v
```

Expected: both pass. If `test_next_unit_title_typesets_in_the_nav_button` fails, the gate or the marker is wrong — fix the code, not the test.

> **Never background a pytest run in this repo.** The harness reaps backgrounded pytest
> mid-run, and a killed run orphans the test DB so the *next* run dies with
> `DuplicateDatabase`. Run e2e in the foreground; if it is long, use `Monitor persistent`
> and verify by process.

- [ ] **Step 3: Falsify the e2e**

Mutant: delete the `_widen_has_math_for_titles(ctx, node)` **call** from `full_lesson_render_context` only — leaving the helper itself intact, which is what keeps the mutant site-specific. (Do **not** gut the helper's `ctx["has_math"] = …` body: after Task 6 that statement lives *only* inside the helper, so removing it would neuter all three render sites at once and prove nothing about the lesson page.)

Expected: `test_next_unit_title_typesets_in_the_nav_button` FAILS on the `wait_for` timeout — the page ships no KaTeX, so no `.katex` element ever appears. Revert.

- [ ] **Step 4: Record the render-cost measurement**

Read the `[render cost]` line from the run above. Note the element count and the milliseconds.

- If the time is **≤ ~50 ms**: record it and change nothing.
- If it **exceeds ~50 ms**: add a **delimiter pre-filter** in `renderInlineText`, so the expensive call is skipped for the overwhelming majority of titles that carry no maths at all:

  ```js
      var text = el.textContent;
      if (text.indexOf("\\(") === -1 && text.indexOf("\\[") === -1) return;
  ```

  placed as the first statement inside the `forEach` callback, before the `try`. This is the
  cheap win the measurement itself already quantifies — the e2e prints `withMaths` beside
  `count` precisely so you know the ratio. Re-run and re-record.

  **There is deliberately no "one call over a common ancestor" branch.** On a unit page the
  marked set spans the `<h1>` and crumbs (`_lesson_article.html`), the rail tree *and* its
  drawer copy (`_unit_shell.html:21,40`) and the footer nav titles (`:24`) — their nearest
  common ancestor is the page shell, which also contains the lesson prose. So the only
  available "common ancestor" is exactly what must not be passed: a single call over it would
  typeset element prose the selector list deliberately scopes, and the edit buffers §Data-flow
  Path C must keep untouched. Per-element calls plus the pre-filter is the realisable fix.

Note the fixture above is a five-node course, not the matematyka worst case (21 parts / 793 units ≈ 1,600+ invocations). If the small-course number is anywhere near the threshold, re-measure against a larger seeded course before concluding.

- [ ] **Step 5a: Seed the visual-verification fixtures**

None of the surfaces below exist under the fixtures written so far — `MATHS_TITLE` is short,
`make_title_course` has no long-title or two-depth-analytics mode, and nothing seeds a
`\[…\]`-only title. Add a **capture script** (not a test) at
`tests/capture_title_math_screenshots.py`, modelled on the repo's existing
`tests/capture_help_screenshots.py` / `tests/capture_publish_screenshots.py`, that seeds this
course and drives it:

```python
TITLES = {
    # (key, title) -- each one exists to exercise a specific §3 claim
    "inline":   r"Rozwiaz \(x^2 + 2x + 1 = 0\) metoda delty",
    "display":  r"Rozwiaz \[\int_0^1 x^2\,dx\] i zapisz wynik",   # .katex-display
    # (long) -- wraps past the 5-line group clamp and every single-line clip
    "long": r"Bardzo dlugi tytul lekcji z formula \(\sum_{i=1}^{n} a_i b_i\) na koncu",
    # (mixed_h1) -- the forced-inline decision AND the font-weight restoration
    "mixed_h1": r"Policz \(a_1\) oraz \[\frac{p}{q}\] i porownaj",
    "plain":    "Lekcja bez matematyki",
}
```

Course shape: **part A** (title = `TITLES["long"]`, to exercise the 5-line group clamp)
containing chapter A1 (**title = `TITLES["long"]`** — `_unit_crumbs.html:33` marks
`forloop.last` of `unit_nav.ancestors` as the crumb **leaf**, and for any lesson under A1 that
leaf is A1 itself; giving A1 a short title makes row 4 unshootable, because the long title
would sit on part A, which renders as `--mid`) containing three lesson units titled
`TITLES["mixed_h1"]`, `TITLES["display"]` and `TITLES["long"]` in that order — so the middle
unit's page shows a display-maths **prev** and a long **next** in one shot; plus **part B**
(title = `TITLES["inline"]`) with one quiz unit titled `TITLES["long"]`, giving the analytics
matrix maths at two nesting depths once part B is expanded.

**The part-B quiz must carry an `[R]` question, or rows 9 and 13 are unshootable.**
`courses/review.py::_awaiting_review` requires `state["total"] > 0` — i.e. at least one element
whose `marking_mode` is `REVIEW` — and `pending_reviews_for` only appends to `awaiting` when
that holds. A quiz unit with a submission but no review-mode question leaves `data["awaiting"]`
empty, so `review_queue.html` renders "Nothing awaiting review." and `review_submission.html`
renders no rows. Seed it with an `ExtendedResponseQuestionElement(marking_mode=
QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"))` — the `_review_quiz` shape at
`tests/test_review_views.py:54-63` — and a `SUBMITTED` submission that has not been reviewed.

Then: enrol one student, submit that quiz (so the results/review rows exist), and tag one unit
(so the tags hub renders). Also seed **one lesson unit and one quiz unit under part B** so the
breakdown page (row 11) shows both `.breakdown-unit__title` branches.

**Two logins, not one.** Rows 6 (analytics matrix), 9 (review queue), 11 (breakdown) and the
review-submission half of row 13 are manage surfaces gated by `scoping.can_review_course`,
which passes only for a platform admin or `course.owner` — capture those as a `make_pa`-style
admin (or the owner). Every other row is captured as the enrolled student.

Follow `tests/capture_publish_screenshots.py` exactly — it already solved every mechanical
question here:

- **Filename is not `test_`-prefixed**, so `python_files = ["test_*.py"]` never auto-collects
  it; the `test_`-named function inside runs only when the path is passed explicitly.
- **Markers:** `pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]`.
- **Invocation:** `uv run pytest tests/capture_title_math_screenshots.py -m e2e`.
- **Dark is set through `User.theme`, never the `libli_theme` cookie** — that file's own
  docstring records why: for an authenticated user `_resolve_theme_pref` lets `User.theme` win
  outright, so a cookie is silently ignored and the "dark" shot comes back light.
- **Output:** `SHOT_DIR` (env) or `./.superpowers/shots/`, both gitignored. One file per row
  per theme, named `title-math-<row>-<theme>.png`.
- **Viewports:** desktop `1440×900` via `browser.new_context(viewport=…)`; mobile `390×780`
  for row 7 only — the exact viewport `test_e2e_unit_nav.py:311,355` uses for its drawer tests.
- **Row 7 needs an INTERACTION — it is the one row that is not a plain page load.** The drawer
  is not visible at load: `_unit_footer.html:29-33` ships
  `<button … data-unit-drawer-open … hidden>` and `unit_nav.js` un-hides it, and the drawer's
  contents only appear once the dialog is open. A script that merely sets a 390px viewport and
  shoots the page photographs the **footer bar**, not the drawer — and row 7 is precisely the
  surface Task 10's own CSS comment leaves unaddressed pending measurement. So: wait for
  `[data-unit-drawer-open]` to lose `hidden`, click it, wait for the drawer dialog to be open,
  then shoot. Mirror the drawer tests in `tests/test_e2e_unit_nav.py`
  (`test_mobile_drawer_open_close_scrim_and_esc`).

- [ ] **Step 5b: Visual verification — light and dark, judged separately**

Read every image and judge the dark one **on its own terms**, not as "the light one but darker".

| # | Surface | What is being judged |
| --- | --- | --- |
| 1 | Prev/next buttons, **inline** maths title | baseline `1.21em` normalisation |
| 2 | Prev/next buttons, **display** (`\[…\]`) maths title | the `.katex-display` case — must stay on one line, no 1em gaps |
| 3 | A **long** maths title in a contents-tree unit row | single-line clip; a hard clip is expected, not an ellipsis |
| 4 | A **long** maths title in the breadcrumb leaf | the second single-line clip |
| 5 | A contents-tree **group** title long enough to exercise the 5-line clamp | `-webkit-box` line counting with an inline-block child; prose keeps wrapping, the formula stays intact |
| 6 | Analytics matrix column header, maths at **two nesting depths** | the `--ahead-h` sticky-offset desync and the `nowrap` column-widening case — the most fragile of the six |
| 7 | **≤640px mobile drawer**, long maths title | wraps rather than clips; the title column is ~98px, and an unbreakable inline-block paints *under* the action buttons |
| 8 | A lesson **`<h1>`** carrying `\(…\)` **and** `\[…\]` alongside words | the forced-inline decision **and** the `font-weight` restoration |
| 9 | A **review-queue row** (`.card-list__row`) | a flex row §3 claims needs no clamp |
| 10 | A **course-results row** and an **outline row** | the other two surfaces §3 claims need no clamp |
| 11 | The **analytics breakdown** page, quiz + lesson rows | `.breakdown-unit__title .katex` and `.breakdown-node__title .katex` are **two of the three selectors in the `app.css` clamp** — without this row they ship on a hypothesis Task 11 never tests |
| 12 | **Notes page** (`h2.course-notes__unit-title`), **tags hub** (`_tag_section.html`'s `<li><a>`) and **tags panel** (`<h1>`) | three pages that newly gain KaTeX rendering and receive **no clamp at all**; §3 puts them in the "global rules only" bucket, and this row is what turns that from an assumption into a measurement |
| 13 | `h1.result__title` (quiz results) and `h1.review-topbar__title` (review submission) | the **same synthetic-bold risk as row 8** on two different pages — row 8 only judges the lesson `<h1>` |
| 14 | The **editor page**: the ancestor crumb, `h1.editor-head__title`, and the preview `h2.prev-unit-title` | the editor ships KaTeX **unconditionally**, so all three typeset on *every* editor load — and their rules live in a **third** stylesheet the rest of this task never touches: `.editor-crumb__path` is `font-size:.9rem` in a flex row (`editor.css:366`), `.editor-head__title` is `1.1rem` (`:370`), and `.prev-unit-title` is `font-weight:700` (`:513`). Both the line-height-growth risk and the synthetic-bold risk apply here, unmeasured |

**Pass criterion for #14:** if either editor surface needs a clamp, the selector goes in
**`courses/static/courses/css/editor.css`** — the editor links `courses.css` *and* `editor.css`,
and these three rules live in the latter, so that is where a correction belongs. This is a
**third** clamp target alongside `app.css` and `courses.css`; Task 10 does not pre-empt it
because no §3 surface lives there. Extend `tests/test_title_math_css.py` with an `EDITOR_CSS`
reader and a `_has_rule` assertion if you add one.

**Pass criterion for #8, stated explicitly:** the maths run must read at the same weight as the adjacent words **without synthetic smearing**. `KaTeX_Main` has no true bold face, so an inherited `bold` is browser-synthesised. **If it smears, drop `font-weight: inherit` and accept the weight mismatch as the lesser defect** — and update `tests/test_title_math_css.py::test_font_size_weight_and_style_are_all_restored` and the spec's §3 to match.

**Pass criterion for #9 and #10:** these are a *claim to be checked*, not a free pass. KaTeX's `line-height: 1.2` survives the global rules, and `.result-row`, `.outline-unit` and `.card-list__row` are flex rows that can still gain height from it. Measure the row height with and without a maths title; if it grows, add a clamp — **and put each selector in the stylesheet its own page actually links**, which is not the same file for all three:

| Selector | Goes in | Because |
| --- | --- | --- |
| `.result-row__title .katex` | `courses.css` | `course_results.html:4` links `courses.css`. |
| `.outline-unit__title .katex` | **`app.css`** | `outline.html:4` links only `notes.css` + `tags.css` (plus base's `app.css`) — **no `courses.css` at all**. A rule for it appended to `courses.css` is a silent no-op on the only page that renders the class, and `test_title_math_css.py` would stay green because it only asserts the rule exists *somewhere*. This is Task 10's own central argument, applied to a surface Task 10 did not pre-empt. |
| `.card-list__row` / review-queue | **`app.css`** | `review_queue.html` extends `base.html` and links no `courses.css` either. |

If you add any selector, extend `tests/test_title_math_css.py` with a `_has_rule` assertion **against the specific stylesheet**, so the placement is pinned and not just the existence.

**Pass criterion for #6:** measure the `thead th` height against `--ahead-h` (`2.4rem`). If any header cell exceeds it, every sticky row beneath desynchronises — that is a layout break, and the fix is more CSS in the same rules (a tighter clamp, or a `max-height` on the cell), not a change of approach.

**Pass criterion for #7:** the maths run must not paint over the drawer's action buttons. This surface cannot be inferred from the desktop rail and needs its own screenshot.

- [ ] **Step 6: Confirm or correct the §3 clamp values**

The values in Task 10 are a **starting hypothesis, not a result**. Having measured:

- If every surface is clean, record that in the spec's §3 closing paragraph: replace "All clamp values above are a **starting hypothesis, not a result**" with the measured confirmation and the date.
- If any surface needs a different value or an extra selector, change the CSS, re-run `tests/test_title_math_css.py` (extending it if you added selectors), update §3, and re-screenshot that surface.

Whenever you change a value, **re-apply the overriding invariant**: the vendor stylesheet always loads after ours, so any new rule must be strictly more specific than the vendor rule it overrides.

- [ ] **Step 7: Branch gate — the full suite**

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest -v
```

Expected: green. Then the e2e suite:

```bash
uv run pytest -m e2e -v
```

> This is the only whole-repo sweep in the plan; it belongs here, not in any earlier task.
> Wall-clock is the user's cost. Do not background it — see the note in Step 2.

- [ ] **Step 8: Commit**

The capture script is **tracked**, not scratch: `tests/capture_help_screenshots.py` and
`tests/capture_publish_screenshots.py` are both committed (and one of them has a dedicated
isolation test), and under this plan's "never `git add -A`" rule an unlisted new file would be
left untracked at PR time — making Step 5b's verification unreproducible.

```bash
uv run ruff check --fix tests/test_e2e_title_math.py tests/capture_title_math_screenshots.py
uv run ruff format tests/test_e2e_title_math.py tests/capture_title_math_screenshots.py
git add tests/test_e2e_title_math.py tests/capture_title_math_screenshots.py
# plus any CSS / math.js / spec files the measurement corrected:
# git add core/static/core/css/app.css courses/static/courses/css/courses.css \
#         courses/static/courses/js/math.js \
#         docs/superpowers/specs/2026-08-10-latex-in-unit-titles-design.md
git commit -m "test(e2e): drive a maths title through the real nav button and measure render cost"
```

---

## Accepted consequences (state these in the PR body, do not rediscover them)

- **The gate is coarse.** Because the contents tree is course-wide, a single maths title anywhere in a course loads ~275 KB of JavaScript and ~23 KB of CSS on **every** unit page of that course. This is correct — those titles really are in the DOM — but it makes the gate coarse in practice. The alternative, scanning only the expanded subtree, is wrong: collapsed nodes are present in the markup, not fetched on demand.
- **Behaviour change on two pages.** Giving `quiz_results.html` and `review_submission.html` `math.js` runs **both** of its passes there for the first time: `renderMath(document)` over `[data-katex]` as well as `renderInlineText(document)`. Any `MathElement` reachable on those pages goes from raw LaTeX to a full `displayMode: true` render, and the listed inline containers begin typesetting too. Intended, but a larger visible change than the title feature itself.
- **A second newly-executing script on those two pages.** `question.js` sits *inside* their `{% if has_math %}` block, so widening the flag for a maths **title** starts running it on responses where no question carries maths — a script that previously never executed there. Believed benign: both pages emit form-less `[data-question]` blocks, per the templates' own comments.
- **Partial coverage is visible to users.** A maths title typesets on the student and analytics surfaces but still shows raw delimiters in the builder panels, the move picker, the link picker, the two confirm prompts, the notification bodies, the gradebook print/export, and — the densest of them — `manage/_flag_strip_headline.html`, which carries **eleven** title interpolations (`:12,14,17,21,23,29,31,33,37,39,41`), every one inside a `{% blocktrans with title=node.title %}` whose msgid would have to be split and re-translated (spec §5). A teacher who uses the builder will see the inconsistency. Deliberate boundary, not an unknown.
- **Knowingly untested branches, each a decision:** the `[node.title]` defence-in-depth scan (Task 6) is unreachable through the client because `access.py` 404s first; the `_quiz_render_feedback` gate assertion would be vacuous because that path always has ≥1 question.
- **No authoring affordance is added.** Title inputs stay plain `<input type="text">` and authors type the delimiters by hand, exactly as for table cells and tab labels. A live preview or a MathLive field may follow as separate work.
- **Titles are not validated.** An unclosed `\(` renders as raw text and invalid TeX renders as a `.katex-error` span — KaTeX auto-render's existing behaviour everywhere else in the app.
