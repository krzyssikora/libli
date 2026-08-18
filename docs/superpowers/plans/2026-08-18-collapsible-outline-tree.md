# Collapsible Course Outline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the student course-outline page render its container nodes as collapsible native `<details>` groups, so a long course opens as a short skimmable list instead of a thousand-row wall.

**Architecture:** `build_outline` gains an additive `depth` key; `_outline_node.html`'s container branch splits into a `<details>`/`<summary>` disclosure (with the per-container *Start fresh* link hoisted out of the summary to a grid-placed sibling) and today's plain head for the unreachable childless case; a new `outline_tree.js` persists the fold state per course in `localStorage` as an open/closed partition, drives an *Expand all / Collapse all* header button, and force-opens groups while a tag filter is active without ever persisting that forced state; `tags.js` gains one event dispatch so the two files stay decoupled.

**Tech Stack:** Django templates, vanilla ES5-style IIFE JS (no framework), token-driven CSS in `core/static/core/css/app.css`, pytest + pytest-django, Playwright (`-m e2e`).

**Spec:** `docs/superpowers/specs/2026-08-18-collapsible-outline-tree-design.md`

## Global Constraints

- **Worktree:** all work happens in `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/collapsible-outline-tree` on branch `pipeline/collapsible-outline-tree`. Never operate on the main checkout.
- **Test DB:** the `libli-test-db` container must be running before any pytest invocation, or the run looks hung for ~4 minutes.
- **Tooling:** ruff/pytest/python are not on PATH — always `uv run <tool>`. e2e tests are deselected by default; `-m e2e` is mandatory for them.
- **Never run two pytest processes at once** (shared test DB), and never background a pytest run.
- **All embedded Python must be `ruff format`-clean before it is pasted in** (88-col
  limit; no f-strings without placeholders). Task 5 and Task 11 both run the lint gate,
  and a plan snippet that fails it wastes a cycle.
- **Falsification is mandatory.** Every test in this plan names a mutant. Apply the mutant, watch the test go RED, then remove the mutant **by hand** — never `git checkout`, which discards surrounding work. A test that cannot be shown RED is not evidence.
- **Storage ids are strings.** `String()` normalisation on both read and write (`details.dataset.node` yields a string; `[12].includes("12")` is `false`).
- **`checkVisibility()` is the only sanctioned probe for folded content.** `to_be_hidden()` is a bounding-box test and a closed `<details>` keeps a stale non-zero rect. `to_be_hidden()` remains correct for the tag filter's `[hidden]` → `display: none` rows.
- **i18n:** *Expand all* / *Collapse all* / *Start fresh* must be spelled exactly as existing msgids. All three already exist translated; no new strings.
- **No new msgids means no fuzzy cleanup** — `makemessages` only appends `#:` reference lines.

---

### Task 1: `depth` on the outline dicts

**Files:**
- Modify: `courses/rollups.py` (the fold loop inside `build_outline`, ~line 258)
- Test: `tests/test_outline_collapsible.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: every dict returned by `build_outline` carries `"depth"` — `0` for a root, parent's depth `+ 1` otherwise. Task 2's template reads it as `{{ item.depth }}`; Task 5's JS reads it back off `data-depth`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_outline_collapsible.py`. Three of the imports (`reverse`,
`Enrollment`, `make_login`) are used by the `_outline_html` helper that Task 2 Step 1
appends — they are placed here so the file's import block is written once. A local
`ruff check` at this point will flag them F401 until Task 2 lands:

```python
"""Render-tier tests for the collapsible course outline (spec T1-T5)."""

import pytest
from django.urls import reverse

from courses.models import Enrollment
from courses.rollups import build_outline
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _three_level_course():
    """part > chapter > unit. Every container holds a visible unit, or
    build_outline's pruning drops it before the template ever sees it."""
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U1"
    )
    return course, part, chapter, unit


def test_build_outline_sets_depth(django_user_model):
    course, part, chapter, unit = _three_level_course()
    user = django_user_model.objects.create_user(username="d1", password="x")
    tree = build_outline(course, user)

    assert tree[0]["depth"] == 0, "a root container is depth 0"
    assert tree[0]["children"][0]["depth"] == 1
    assert tree[0]["children"][0]["children"][0]["depth"] == 2
```

- [ ] **Step 2: Run it and watch it fail**

```
uv run pytest tests/test_outline_collapsible.py::test_build_outline_sets_depth -v
```

Expected: FAIL with `KeyError: 'depth'`.

- [ ] **Step 3: Add the key**

In `courses/rollups.py`, inside `build_outline`'s fold loop, add `"depth"` to the dict literal. The parent dict is guaranteed to exist already (the loop is pre-order, and the line below it already assumes this with `by_pk[node.parent_id]["children"]`):

```python
        d = {
            "node": node,
            "children": [],
            "required_total": 0,
            "required_done": 0,
            "additional_done": 0,
            "is_unit": is_unit,
            "completed": is_unit and node.pk in completed,
            # Additive only: build_outline also feeds build_unit_nav (the rail),
            # build_student_breakdown (the teacher tree) and outline_with_tags,
            # all of which ignore this key. Pre-order guarantees the parent dict
            # exists; pruning runs after the fold and never re-parents, so a depth
            # assigned here stays correct.
            "depth": 0
            if node.parent_id is None
            else by_pk[node.parent_id]["depth"] + 1,
        }
```

- [ ] **Step 4: Run it and watch it pass**

```
uv run pytest tests/test_outline_collapsible.py::test_build_outline_sets_depth -v
```

Expected: PASS.

- [ ] **Step 5: Falsify it**

By hand, change `by_pk[node.parent_id]["depth"] + 1` to `by_pk[node.parent_id]["depth"]`. Re-run — it must FAIL on the `== 1` assertion. Remove the mutant by hand.

- [ ] **Step 6: Prove the other three consumers still work**

```
uv run pytest tests/test_courses_rollups.py tests/test_unit_nav_render.py tests/test_analytics_rollups.py tests/test_tags_outline.py tests/test_publish_outline.py -q
```

Expected: all pass (the key is additive; `test_analytics_rollups.py::test_progress_overall_parity_with_build_outline` calls `build_outline` directly).

- [ ] **Step 7: Commit**

```bash
git add courses/rollups.py tests/test_outline_collapsible.py
git commit -m "feat(outline): add additive depth key to build_outline dicts"
```

---

### Task 2: The disclosure markup and its CSS

This task is deliberately atomic: the moment the markup changes, five CSS selectors stop matching and one existing e2e locator resolves to nothing. Splitting them would land a task that is green but visibly broken.

**Files:**
- Modify: `templates/courses/_outline_node.html:20-31` (the `{% else %}` container branch)
- Modify: `core/static/core/css/app.css` (the `.outline-*` block, ~lines 503-594)
- Modify: `tests/test_outline_anchors.py` (add the twin assertion)
- Modify: `tests/test_e2e_link_dialog.py` (re-point the `:target` locator)
- Test: `tests/test_outline_collapsible.py` (append)

**Interfaces:**
- Consumes: `item.depth` from Task 1.
- Produces: `details.outline-node__group[data-node][data-depth]` inside every container `<li>` that has children; `summary.outline-node__head` carrying chevron + title + rollups; `a.outline-node__reset` as a **sibling** of the `<details>`. Task 5's JS selects on exactly these.

- [ ] **Step 1: Write the failing render tests**

Append to `tests/test_outline_collapsible.py`:

```python
def _outline_html(client, course, username):
    user = make_login(client, username)
    Enrollment.objects.create(student=user, course=course)
    return client.get(
        reverse("courses:course_outline", kwargs={"slug": course.slug})
    ).content.decode()


def test_depth0_open_deeper_closed(client):
    """T1. Mutant: emit `open` unconditionally."""
    course, part, chapter, unit = _three_level_course()
    html = _outline_html(client, course, "t1")

    assert f'data-node="{part.pk}"' in html
    assert 'data-depth="0"' in html
    assert 'data-depth="1"' in html

    part_tag = html.split(f'data-node="{part.pk}"')[1].split(">")[0]
    chapter_tag = html.split(f'data-node="{chapter.pk}"')[1].split(">")[0]
    assert "open" in part_tag, "a depth-0 container ships open (D1)"
    assert "open" not in chapter_tag, "a depth-1 container ships folded (D1)"


def test_reset_link_is_a_sibling_of_details_not_inside_the_summary(client):
    """T3. Mutant: move the link back inside the <summary>.

    Structural assertion. The motivation is that a <summary> is one button-role
    control whose accessible name concatenates its contents, and that a folded
    group hides everything except its summary — but this tier observes the
    structure, not those consequences.
    """
    course, part, chapter, unit = _three_level_course()
    html = _outline_html(client, course, "t3")

    summary = html.split('<summary class="outline-node__head">')[1].split(
        "</summary>"
    )[0]
    assert "outline-node__chevron" in summary
    assert "outline-node__title" in summary
    assert "outline-node__reset" not in summary, "D9: the reset link is a sibling"
    assert "outline-node__reset" in html, "...but it is still rendered"
```

- [ ] **Step 2: Run them and watch them fail**

```
uv run pytest tests/test_outline_collapsible.py -q
```

Expected: both new tests FAIL (no `data-node`, no `<summary>` in the output yet).

- [ ] **Step 3: Rewrite the container branch**

Replace `templates/courses/_outline_node.html` lines 20-31 (the `{% else %}` arm) with:

```django
  {% else %}
    {% comment %}Two arms. A container WITH children renders a native <details>:
       folding works with JS off, and keyboard + AT semantics come free. A
       childless one keeps the plain head — an empty disclosure is a dead
       control. The childless arm is unreachable on the student path (build_outline
       prunes zero-child containers under both "hide" and "keep"), so it is a
       correct fallback, not a live shape; do not assert it is reachable.

       `open` has two arms. depth == 0 is D1. The second is D8: under a tag
       filter, outline_with_tags has already set tag_hidden False on exactly the
       containers still holding a visible unit, so opening them is a read of an
       existing value. active_tag_ids reaches here because neither {% include %}
       uses `only` — if that ever changes, a no-JS filtered outline silently shows
       nothing.{% endcomment %}
    {% if item.children %}
      <details class="outline-node__group" data-node="{{ item.node.pk }}" data-depth="{{ item.depth }}"{% if item.depth == 0 or active_tag_ids and not item.tag_hidden %} open{% endif %}>
        <summary class="outline-node__head">
          <svg class="icon outline-node__chevron" aria-hidden="true" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>
          <span class="outline-node__title" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
          {% if item.required_total %}<span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>{% endif %}
          {% if item.additional_done %}<span class="rollup rollup--additional">+{{ item.additional_done }} {% trans "additional" %}</span>{% endif %}
        </summary>
        <ul>{% for child in item.children %}{% include "courses/_outline_node.html" with item=child course=course note_counts=note_counts %}{% endfor %}</ul>
      </details>
      {% comment %}D9: a SIBLING of the <details>, not a child of the <summary> —
         nesting a focusable link inside a button-role control both corrupts the
         disclosure's accessible name and is exposed inconsistently by screen
         readers. app.css grid-places it back onto the head row.{% endcomment %}
      <a class="outline-node__reset" title="{% trans 'Start fresh' %}" aria-label="{% trans 'Start fresh' %}"
         href="{% url 'courses:progress_reset' slug=course.slug node_pk=item.node.pk %}?next={% url 'courses:course_outline' slug=course.slug %}">{% trans "Start fresh" %}</a>
    {% else %}
      <div class="outline-node__head">
        <span class="outline-node__title" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
        {% if item.required_total %}<span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>{% endif %}
        {% if item.additional_done %}<span class="rollup rollup--additional">+{{ item.additional_done }} {% trans "additional" %}</span>{% endif %}
        <a class="outline-node__reset" title="{% trans 'Start fresh' %}" aria-label="{% trans 'Start fresh' %}"
           href="{% url 'courses:progress_reset' slug=course.slug node_pk=item.node.pk %}?next={% url 'courses:course_outline' slug=course.slug %}">{% trans "Start fresh" %}</a>
      </div>
    {% endif %}
  {% endif %}
```

- [ ] **Step 4: Run the render tests and watch them pass**

```
uv run pytest tests/test_outline_collapsible.py -q
```

Expected: PASS.

- [ ] **Step 5: Falsify both**

For T1: by hand, change the `open` condition to a bare `open`. Re-run — `test_depth0_open_deeper_closed` must FAIL on the chapter assertion. Remove by hand.
For T3: by hand, move the `<a class="outline-node__reset">` inside the `</summary>`. Re-run — `test_reset_link_is_a_sibling_of_details_not_inside_the_summary` must FAIL. Remove by hand.

- [ ] **Step 6: Re-point the five CSS selectors**

In `core/static/core/css/app.css`, apply these edits inside the `.outline-*` block. The rail hit every one of these first and fixed them by **doubling** the selector; `courses.css:707-710` carries the precedent and the comment explaining why a descendant combinator would destroy the level distinction.

Replace the nested-guide rule:

```css
/* nested levels get a hairline guide rule. Re-pointed, not doubled: the <ul>
   now lives inside the <details>, and neither surviving branch renders a <ul>
   as a child of the <li> (the childless arm has no children by definition, and
   a unit row has no nested list), so the old form would be dead. */
.outline-node__group > ul { margin-top: var(--space-2); padding-left: var(--space-4);
  border-left: 1px solid var(--border-subtle); }
```

Double the three type-scale rules — losing these leaves a structurally correct but visually flat tree, with nothing red:

```css
.outline-node--part > .outline-node__head .outline-node__title,
.outline-node--part > .outline-node__group > .outline-node__head .outline-node__title { font-size: 1.35rem; }
.outline-node--chapter > .outline-node__head .outline-node__title,
.outline-node--chapter > .outline-node__group > .outline-node__head .outline-node__title { font-size: 1.1rem; }
.outline-node--section > .outline-node__head .outline-node__title,
.outline-node--section > .outline-node__group > .outline-node__head .outline-node__title {
  font-size: .75rem; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  color: var(--text-tertiary);
}
```

Double the `:target` highlight (the old form survives as inert cover for the childless arm; the twin is the live one):

```css
.outline-node:target > .outline-node__head,
.outline-node:target > .outline-node__group > .outline-node__head,
.outline-node:target > .outline-unit {
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  box-shadow: 0 0 0 2px var(--primary);
}
```

- [ ] **Step 7: Add the new disclosure rules**

Append to the same block:

```css
/* Container rows become a two-column grid so D9's reset link sits back on the
   head row. The <details> MUST span 1 / -1: it contains the entire descendant
   subtree, so confining it to column 1 would narrow every nested row and the
   loss would COMPOUND per level (~220px at depth 3 on mat-pp). Grid, not
   position: absolute — an absolutely positioned link overlaps a wrapped title.
   Specificity is capped at (0,1,0) on purpose: `.outline-node[hidden]` is
   (0,2,0) and MUST keep winning, or a filtered-out container stops hiding.
   Do not scope these selectors more tightly. */
.outline-node--part,
.outline-node--chapter,
.outline-node--section {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline;
}
.outline-node__group { grid-column: 1 / -1; grid-row: 1; }

/* Group summary. display:flex (inherited from .outline-node__head) already drops
   the list-item box, so list-style + ::-webkit-details-marker are belt-and-braces
   against a future display change — neither is independently falsifiable, so do
   NOT write a test against them. padding-inline-end reserves the overlaid reset
   link's space; see the measured value recorded at the declaration. */
summary.outline-node__head { cursor: pointer; list-style: none; }
summary.outline-node__head::-webkit-details-marker { display: none; }
summary.outline-node__head:hover { background: var(--surface-raised); }
summary.outline-node__head:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }

/* Explicit size: the type scale lives on .outline-node__title, not on the head,
   so the head is 1rem at every level and .icon's 1em would render an identical
   16px chevron beside a .75rem uppercase section title. Constant across levels
   by choice — the disclosure is chrome. align-self: center because the head is
   align-items: baseline and a replaced element's baseline is its bottom margin
   edge, which would sit the chevron visibly high. Explicit colour because the
   rail's currentColor reasoning does NOT transfer: the rail's micro-type rule
   targets its head, ours targets the title span. */
.outline-node__head > .outline-node__chevron {
  width: .8rem; height: .8rem; align-self: center; color: var(--text-tertiary);
}
/* Full direct-child chain, NOT `[open] .outline-node__chevron`: the tree is
   recursive, so a CLOSED section sits inside an OPEN chapter and a descendant
   selector would paint it open too. */
.outline-node__group[open] > .outline-node__head > .outline-node__chevron { transform: rotate(90deg); }
/* Gated, not cancelled. A media query adds no specificity, so a `reduce` override
   at the same selector merely TIES and source order decides; at a lower
   specificity it loses outright — which is why the rail's chevron
   (courses.css:746-753) animates for reduced-motion users today. Do not
   "harmonise" back to that form. */
@media (prefers-reduced-motion: no-preference) {
  .outline-node__head > .outline-node__chevron { transition: transform 120ms ease; }
}
```

Extend the existing `.outline-node__reset` rule (do not duplicate it) so it becomes a grid item in the disclosure arm. In the childless arm it is a flex child inside the head and these two properties are inert:

```css
.outline-node__reset {
  grid-column: 2;
  grid-row: 1;
  justify-self: end;
  align-self: baseline;
  margin-left: var(--space-2);
  font-size: .8rem;
  color: var(--text-secondary);
  text-decoration: underline;
}
```

- [ ] **Step 8: Measure and set `padding-inline-end`**

The reset link now *overlays* row 1 rather than reserving a track, so a long wrapped title would run underneath it. Size the reservation against the **Polish** label — `Start fresh` → `Zacznij od nowa` — because pl is this project's primary UI locale and an English-tuned constant reproduces the collision where most users would see it.

Render the outline in **both** locales. The project resolves the active language from
the user's profile/session — set it through the app's own language control (Settings), or
for a throwaway measurement force it in a shell:

```
uv run python manage.py shell -c "from django.utils import translation; translation.activate('pl'); from django.template.loader import render_to_string; print(len('Zacznij od nowa'))"
```

then measure the rendered element with the app running (`uv run python manage.py runserver`), in the browser console on a course outline page, once per locale:

```js
document.querySelector(".outline-node__reset").getBoundingClientRect().width
```

Record the larger of the en/pl widths, add `var(--space-4)` of clearance, round **up** to the next `.5rem`, and write it with the measurement in the comment:

```css
/* MEASURED <YYYY-MM-DD>: "Zacznij od nowa" renders <N>px at .8rem (en
   "Start fresh" <M>px). Rounded up with clearance. Re-measure if either
   translation changes. */
summary.outline-node__head { padding-inline-end: <value>rem; }
```

- [ ] **Step 9: Update `tests/test_outline_anchors.py`**

The existing `test_target_highlight_is_scoped_to_the_row_not_the_li` asserts the literal old selector, which Step 6 kept — so it still passes and proves nothing about real containers. Add the twin assertion, which is the load-bearing half:

```python
    assert ".outline-node:target > .outline-node__head" in css
    # After the collapsible change the selector above is inert cover for the
    # unreachable childless branch; every REAL container renders its head as the
    # <summary> of a <details>, so this twin is the live rule. Without it the
    # permalink highlight silently never lands.
    assert ".outline-node:target > .outline-node__group > .outline-node__head" in css
    assert ".outline-node:target > .outline-unit" in css
```

- [ ] **Step 10: Re-point the `test_e2e_link_dialog.py` locator**

Its `#node-{chapter.pk} > .outline-node__head` now resolves to nothing (the head is a grandchild). Preserve the direct-child scoping the test's own comment says is the point — do not loosen to a descendant selector:

```python
    row = page.locator(f"#node-{chapter.pk} > .outline-node__group > .outline-node__head")
```

- [ ] **Step 11: Run the affected suites**

```
uv run pytest tests/test_outline_collapsible.py tests/test_outline_anchors.py tests/test_link_styling.py -q
uv run pytest tests/test_e2e_link_dialog.py -m e2e -q
```

Expected: all pass.

- [ ] **Step 12: Falsify the CSS re-points**

By hand, delete the `> .outline-node__group >` twin from the `:target` rule. `uv run pytest tests/test_outline_anchors.py -q` must FAIL. Remove the mutant by hand. (The type-scale and guide-rule twins are falsified by T17 in Task 10 — they have no render-tier assertion.)

- [ ] **Step 13: Commit**

```bash
git add templates/courses/_outline_node.html core/static/core/css/app.css tests/test_outline_collapsible.py tests/test_outline_anchors.py tests/test_e2e_link_dialog.py
git commit -m "feat(outline): render container nodes as collapsible details groups"
```

---

### Task 3: The no-JS filter guard (D8)

**Files:**
- Test: `tests/test_outline_collapsible.py` (append)

**Interfaces:**
- Consumes: the `open` condition's second arm, already written in Task 2.
- Produces: nothing new — this task exists to pin the arm with a test, because it is the *only* thing keeping the tag filter working with JS off and nothing else covers it.

- [ ] **Step 1: Write the guard test** (it passes immediately — Task 2 already wrote
the arm; Step 3's mutant is what proves it is not vacuous)

Append to `tests/test_outline_collapsible.py`:

```python
def test_filter_opens_the_ancestors_of_a_match(client):
    """T5 / D8. The tag filter is NOT JS-only: _tags_filter_bar.html renders real
    <a href="?tags=N"> links and outline_with_tags sets tag_hidden server-side.
    Without the second `open` arm, a no-JS student clicking a filter chip sees an
    outline of nothing — a regression on a currently-working path.

    Mutant: drop the `or active_tag_ids and not item.tag_hidden` arm.
    """
    from tags.models import Tag
    from tags.models import UnitTag

    course = CourseFactory()
    root_a = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    root_b = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    chap_a = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=root_a
    )
    chap_b = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=root_b
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a
    )
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap_b)

    user = make_login(client, "t5")
    Enrollment.objects.create(student=user, course=course)
    # The tag MUST be authored by the student issuing the GET: course_outline
    # filters active_tag_ids down to tags_for_outline(request.user, course), which
    # is tag__author-scoped. A tag owned by anyone else leaves active_tag_ids
    # empty, the D8 arm never fires, and this test fails on a CORRECT build.
    tag = Tag.objects.create(author=user, name="exam")
    UnitTag.objects.create(tag=tag, unit=hit)

    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    html = client.get(f"{url}?tags={tag.pk}").content.decode()

    chap_a_tag = html.split(f'data-node="{chap_a.pk}"')[1].split(">")[0]
    chap_b_tag = html.split(f'data-node="{chap_b.pk}"')[1].split(">")[0]
    assert "open" in chap_a_tag, "the match's depth-1 ancestor is opened"
    # Negative side must target depth >= 1: depth-0 containers render open
    # unconditionally under D1's arm, so a depth-0 negative fails on a correct build.
    assert "open" not in chap_b_tag, "a depth-1 container with no match stays folded"
```

- [ ] **Step 2: Run it**

```
uv run pytest tests/test_outline_collapsible.py::test_filter_opens_the_ancestors_of_a_match -v
```

Expected: PASS (Task 2 already wrote the arm). If it fails, check the `Tag`/`UnitTag` import paths against `tags/models.py` and the authorship note above before touching the template.

- [ ] **Step 3: Falsify it**

By hand, reduce the template's condition to `{% if item.depth == 0 %} open{% endif %}`. Re-run — it must FAIL on the `chap_a` assertion. Remove the mutant by hand.

- [ ] **Step 4: Commit**

```bash
git add tests/test_outline_collapsible.py
git commit -m "test(outline): pin the no-JS tag-filter ancestor-open guard"
```

---

### Task 4: Header control, nav attributes and script wiring

**Files:**
- Modify: `templates/courses/outline.html` (lines 7-12, 14, 20)
- Modify: `core/static/core/css/app.css` (append)
- Test: `tests/test_outline_collapsible.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `nav.outline-tree.outline-tree--booting[data-course-slug]`, `button.outline__toggle-all[data-outline-toggle-all][data-label-expand][data-label-collapse][hidden]`, and `outline_tree.js` loaded immediately **before** `tags.js`. Task 5's JS selects on all of these.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outline_collapsible.py`:

```python
def test_header_button_and_nav_attributes(client):
    """T4. Mutant: drop data-course-slug from the nav — without it the storage key
    becomes `libli_outline_open:undefined`, i.e. one fold state shared across every
    course, which nothing else would notice."""
    course, part, chapter, unit = _three_level_course()
    html = _outline_html(client, course, "t4")

    assert f'data-course-slug="{course.slug}"' in html
    assert "outline-tree--booting" in html, (
        "server-rendered: a JS-added class arrives after the first paint, which is "
        "the very paint it exists to cover"
    )
    button = html.split("data-outline-toggle-all")[0].rsplit("<button", 1)[1]
    assert "hidden" in button, "ships hidden; JS reveals it (dead control with JS off)"
    assert 'data-label-expand="Expand all"' in html
    assert 'data-label-collapse="Collapse all"' in html
```

- [ ] **Step 2: Run it and watch it fail**

```
uv run pytest tests/test_outline_collapsible.py::test_header_button_and_nav_attributes -v
```

Expected: FAIL.

- [ ] **Step 3: Edit `templates/courses/outline.html`**

Insert the button **before** the *My results* link (line 9). That places it in the left group beside the `<h1>`, because `.outline__results` carries `margin-left: auto` and pushes everything from there rightwards — deliberate: the tree control sits with the thing it controls, and the three page actions stay grouped:

```django
    <button type="button" class="btn btn--ghost btn--small outline__toggle-all" hidden
            data-outline-toggle-all
            data-label-expand="{% trans 'Expand all' %}"
            data-label-collapse="{% trans 'Collapse all' %}"></button>
```

Both labels reuse msgids that already exist (from `templates/courses/manage/builder.html`) with Polish translations — spell them exactly, or you fork a new untranslated string.

Change the nav (line 14):

```django
  <nav class="outline-tree outline-tree--booting" data-course-slug="{{ course.slug }}"
       aria-label="{% trans 'Course outline' %}">
```

Add the script **immediately before** `tags.js` (line 20). Both `defer`, and `defer` preserves document order — so `outline_tree.js` has registered its `libli:tagfilter` listener before `tags.js` runs its initial `applyFilter()`:

```django
<script src="{% static 'courses/js/outline_tree.js' %}" defer></script>
<script src="{% static 'tags/js/tags.js' %}" defer></script>
```

- [ ] **Step 4: Add the disabled-button CSS**

Append to `app.css`. There is **no** reduced-opacity `:disabled` precedent in this codebase to copy — the only `:disabled` rules are the two cyclers, and `.switchgate__cycler:disabled` is a *success tint* which on a disabled *Collapse all* would read as "something succeeded":

```css
/* Disabled while a tag filter is active (§5): Collapse all would hide every
   match. .btn sets cursor:pointer and .btn--ghost:hover sets a fill, neither
   reset by the UA and neither guarded with :not(:disabled) — without these two
   rules the disabled control looks and behaves like a live one, which is the
   "visibly does nothing" affordance the disable was chosen to avoid. */
.outline__toggle-all:disabled { opacity: .5; cursor: default; }
.outline__toggle-all:disabled:hover { background: transparent; }
```

- [ ] **Step 5: Run it and watch it pass**

```
uv run pytest tests/test_outline_collapsible.py -q
```

Expected: all pass.

- [ ] **Step 6: Falsify it**

By hand, remove `data-course-slug="{{ course.slug }}"` from the nav. Re-run — `test_header_button_and_nav_attributes` must FAIL. Remove the mutant by hand.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/outline.html core/static/core/css/app.css tests/test_outline_collapsible.py
git commit -m "feat(outline): add expand/collapse-all control and fold-state wiring points"
```

---

### Task 5: `outline_tree.js` — init, storage, persistence, label

**Files:**
- Create: `courses/static/courses/js/outline_tree.js`
- Modify: `core/static/core/css/app.css` (the booting suppression rule)

**Interfaces:**
- Consumes: the DOM contract from Tasks 2 and 4.
- Produces: `localStorage["libli_outline_open:<slug>"]` holding `{"v":1,"open":["12"],"closed":["88"]}`; a `libli:tagfilter` **listener** on `document` (Task 6 adds the dispatcher).

- [ ] **Step 1: Write the file**

Create `courses/static/courses/js/outline_tree.js`:

```js
(function () {
  "use strict";

  var tree = document.querySelector(".outline-tree");
  if (!tree) return;

  var KEY = "libli_outline_open:" + (tree.dataset.courseSlug || "");
  var groups = Array.prototype.slice.call(
    tree.querySelectorAll(".outline-node__group")
  );
  var button = document.querySelector("[data-outline-toggle-all]");
  var filterActive = false;

  // ── storage ──────────────────────────────────────────────────────────────
  // The value is a PARTITION, not an open-list. With an open-only list "not
  // listed" is ambiguous between "the student closed this" and "this container
  // did not exist last visit", and those need opposite treatments.
  // Ids are strings on BOTH sides: dataset.node yields a string and
  // [12].indexOf("12") is -1, so a numeric writer + dataset reader is a silent
  // no-op that still passes any test seeding storage the writer's own way.
  function read() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || parsed.v !== 1) return null;
      return {
        open: (parsed.open || []).map(String),
        closed: (parsed.closed || []).map(String)
      };
    } catch (e) {
      return null; // unparseable, or Safari private mode. Never throw.
    }
  }

  // Full replacement, never a merge: ids of containers deleted since the last
  // visit self-prune on the next gesture. Last-write-wins across tabs is
  // accepted for a cosmetic preference — do NOT add a `storage` listener.
  function write() {
    if (filterActive) return; // D5 — the filtered view is transient by definition
    var open = [];
    var closed = [];
    groups.forEach(function (g) {
      (g.open ? open : closed).push(String(g.dataset.node));
    });
    try {
      localStorage.setItem(KEY, JSON.stringify({ v: 1, open: open, closed: closed }));
    } catch (e) {}
  }

  // A group in neither array is NEW since the last write: fall back to its own
  // data-depth default, so a newly authored top-level part behaves like a first
  // visit for that node instead of silently arriving folded.
  function applyPartition(state) {
    groups.forEach(function (g) {
      var id = String(g.dataset.node);
      if (state && state.open.indexOf(id) !== -1) g.open = true;
      else if (state && state.closed.indexOf(id) !== -1) g.open = false;
      else g.open = g.dataset.depth === "0";
    });
  }

  // ── label ────────────────────────────────────────────────────────────────
  // Names the ACTION OFFERED, not the current state. One shared function,
  // called at init and from the capture-phase toggle listener — never from the
  // toggle-all click handler, or the capture listener could be missing entirely
  // and no test would notice.
  function syncLabel() {
    if (!button) return;
    var anyClosed = groups.some(function (g) { return !g.open; });
    button.textContent = button.getAttribute(
      anyClosed ? "data-label-expand" : "data-label-collapse"
    );
  }

  // ── deep links ───────────────────────────────────────────────────────────
  function openHashTarget() {
    var m = /^#node-(\d+)$/.exec(location.hash);
    if (!m) return;
    var li = document.getElementById("node-" + m[1]);
    if (!li) return; // a draft the student cannot see, or a deleted node

    // The target's OWN group, if it has one. Every generated permalink names a
    // container (views.py sends units to lesson_unit/quiz_unit instead), so
    // ancestors-only would land the student on a highlighted head with its
    // contents folded. But id="node-N" is on EVERY <li>, units included, so a
    // bookmarked #node-<unit-pk> owns no <details> — this must not throw.
    var own = li.querySelector(":scope > .outline-node__group");
    if (own) own.open = true;

    var el = li.parentElement;
    while (el && tree.contains(el)) {
      if (el.tagName === "DETAILS") el.open = true;
      el = el.parentElement;
    }
    li.scrollIntoView({ block: "center" });
    write(); // D6 — a deliberate navigation. No-op while filterActive.
  }

  // ── init, in this order (§4.0) ───────────────────────────────────────────
  // 1. Seed filterActive FROM THE PAGE, before anything reads or writes. It must
  //    not wait for the libli:tagfilter event: that arrives after the steps
  //    below have run, so a ?tags=N#node-M URL would write the server's
  //    force-opened tree straight into storage.
  filterActive = !!document.querySelector("[data-tags-filter] a.tag-chip.is-active");

  // 2. Reveal the button — but not on a course with zero groups, where "every
  //    group is open" is vacuously true and the control would do nothing.
  if (button && groups.length) {
    button.hidden = false;
    button.disabled = filterActive;
  }

  // 3. Apply stored state — SKIPPED under a filter, where the server's D8 render
  //    is already correct. Key absent: do nothing at all, leaving the server's
  //    D1/D8 render. (The filter-clear restore below has the opposite rule.)
  if (!filterActive) {
    var stored = read();
    if (stored) applyPartition(stored);
  }

  // 4. Deep link.
  openHashTarget();
  window.addEventListener("hashchange", openHashTarget);

  // Spec §4.0 puts syncLabel() in step 2; it is called here instead, AFTER the
  // stored state and the deep link have changed the tree, so the very first label
  // describes the tree the student actually sees. Deliberate deviation from a
  // section the spec marks normative — the end state is identical because the
  // capture-phase listener below would correct it anyway, but this avoids a
  // one-frame stale label.
  syncLabel();

  // 5. Force a style recalculation BEFORE dropping the class. Whether a
  //    transition starts is decided from the after-change style, and the
  //    mutations above plus this removal happen in one synchronous task — so
  //    without the forced read the chevrons would have both the new rotation and
  //    a live transition at the next recalc, and the wave animates anyway. The
  //    class would be silently inert.
  void tree.offsetHeight;
  // Unconditionally, however the branches above went. Conditioning this on
  //    step 3 would leave the transition dead for the whole session on a
  //    filtered or first-time load.
  tree.classList.remove("outline-tree--booting");

  // ── persistence: on user gesture, never on `toggle` ──────────────────────
  // `toggle` fires ASYNCHRONOUSLY, so the obvious "set a programmatic flag,
  // mutate, clear the flag" approach clears the flag long before the queued
  // events run and persists every programmatic open — exactly the D5 failure,
  // invisible until a student clears a filter. So the gesture is the trigger.
  tree.addEventListener("click", function (e) {
    // closest(), not matches(): the summary contains an <svg>, the title span
    // and the rollup chips, so e.target is almost never the summary itself — a
    // matches() build fires only in the gaps between children and looks like it
    // works. closest() also resolves from inside the SVG. A click on the sibling
    // reset link yields null here and is ignored with no special-casing.
    if (!e.target.closest("summary.outline-node__head")) return;
    // The timeout is required, not decoration: <summary>'s activation behaviour
    // runs AFTER click dispatch, so reading .open in this handler reads the
    // pre-click state. Keyboard activation dispatches a real click too, so this
    // covers Enter/Space with no extra keydown handling.
    setTimeout(write, 0);
  });

  if (button) {
    button.addEventListener("click", function () {
      var expand = groups.some(function (g) { return !g.open; });
      groups.forEach(function (g) { g.open = expand; });
      write();
      // Deliberately NOT syncLabel() — spec §4.3 forbids the click handler
      // setting the label itself, because then the capture listener below could
      // be missing entirely and T9 would still pass. The programmatic `g.open`
      // mutations above fire `toggle`, which the listener handles.
    });
  }

  // CAPTURE phase: `toggle` does not bubble, so a plain delegated listener
  // silently never fires and the label just stops updating.
  tree.addEventListener("toggle", syncLabel, true);

  // ── tag filter (dispatcher lives in tags.js) ─────────────────────────────
  document.addEventListener("libli:tagfilter", function (e) {
    var count = e.detail ? e.detail.count : 0;
    if (count > 0) {
      filterActive = true;
      if (button) button.disabled = true;
      groups.forEach(function (g) {
        if (g.querySelector("li[data-unit]:not([hidden])")) g.open = true;
      });
    } else {
      // No-op unless a filter was actually active. tags.js ends setupFilter with
      // an unconditional applyFilter, so an UNFILTERED load that renders a filter
      // bar dispatches count:0 right after openHashTarget() ran — without this
      // guard that would slam the just-opened ancestors shut.
      if (!filterActive) return;
      filterActive = false;
      if (button) button.disabled = false;
      // Restore path: an absent key is an EMPTY PARTITION here, so every group
      // falls back to its data-depth default. (The load path leaves the DOM
      // alone instead — otherwise a first-visit student who filters and clears
      // is left with a fully force-opened tree.)
      applyPartition(read());
    }
    // No syncLabel() here either: the force-open / restore mutations above fire
    // `toggle`, and the capture listener owns the label. See §4.3.
  });
})();
```

- [ ] **Step 2: Add the booting suppression rule**

Append to `app.css`. Written at (0,3,0) so it wins outright — the shorter `.outline-tree--booting .outline-node__chevron` is (0,2,0) and merely ties the base chevron rule, leaving source order to decide:

```css
/* Suppresses the chevron animation until outline_tree.js finishes restoring the
   stored fold state, so the restore is an instant state change rather than a
   wave of animating chevrons. This rule is the ONLY thing the class does: with
   JS off it is never removed, so it must never hide or reposition anything. */
.outline-tree--booting .outline-node__head > .outline-node__chevron { transition: none; }
```

- [ ] **Step 3: Lint**

```
uv run ruff check --no-cache .
uv run ruff format --check .
```

Expected: clean (ruff does not lint JS; this catches any stray Python edit).

- [ ] **Step 4: Smoke it by hand**

Start the app, open a course outline, and confirm: depth-0 groups open, deeper folded; clicking a summary folds/unfolds; the *Expand all* button appears and flips its label; reloading preserves what you folded. The e2e suite in Tasks 7-10 is what actually proves these — this step is only to catch a gross wiring error before writing ten tests against it.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/outline_tree.js core/static/core/css/app.css
git commit -m "feat(outline): persist fold state and drive the expand/collapse-all control"
```

---

### Task 6: The `tags.js` bridge

**Files:**
- Modify: `tags/static/tags/js/tags.js` (end of `applyFilter`)

**Interfaces:**
- Consumes: nothing.
- Produces: a `libli:tagfilter` `CustomEvent` on `document` carrying `{detail: {count}}`, which Task 5's listener already handles.

- [ ] **Step 1: Add the dispatch**

At the very end of `applyFilter` in `tags/static/tags/js/tags.js`, after the container-bubbling loop:

```js
    // The outline's fold controller (outline_tree.js) needs to force-open groups
    // holding a visible match — a matching unit inside a folded <details> is
    // invisible, so filtering would appear to find nothing. Dispatched on
    // `document` so the two files stay decoupled and tags.js keeps working
    // unchanged on pages with no outline.
    document.dispatchEvent(
      new CustomEvent("libli:tagfilter", { detail: { count: active.size } })
    );
```

Nothing else in `tags.js` changes.

- [ ] **Step 2: Confirm the existing tag e2e still passes**

```
uv run pytest tests/test_e2e_tags.py -m e2e -q
```

Expected: PASS. Its fixture puts units at depth 1 under a single depth-0 part, so they stay visible under D1 — **verify, do not pre-emptively edit**. If it needs a change, that is a signal the default is wrong, not that the test is wrong.

- [ ] **Step 3: Confirm the other outline-driving e2e still passes**

```
uv run pytest tests/test_e2e_publish_toggle.py -m e2e -q
```

Expected: PASS. It clicks `[data-unit="…"] a.outline-unit` on the outline with the same single-part shape; a Playwright `click()` on a folded row would time out, so this is not optional to check.

- [ ] **Step 4: Commit**

```bash
git add tags/static/tags/js/tags.js
git commit -m "feat(tags): announce filter changes so the outline can unfold matches"
```

---

### Task 7: e2e — the default, persistence and expand-all (T6-T9)

**Files:**
- Create: `tests/test_e2e_outline_tree.py`

**Interfaces:**
- Consumes: everything from Tasks 2-6.
- Produces: `_login`, `_course_with_two_chapters`, `_title_sel`, `_visible`, `_is_open`, `_has_open_attr`, `_stored` and `_wait_for_write` helpers, reused by Tasks 8-10.

- [ ] **Step 1: Write the file with T6-T9**

```python
"""Playwright e2e for the collapsible course outline (spec T6-T19).

Real browser gestures only. Marked `e2e` (run with -m e2e).

FOLD ASSERTIONS USE checkVisibility(), NEVER to_be_hidden(): Playwright's
visibility contract is "non-empty bounding box and not visibility:hidden", and a
closed <details> keeps a STALE non-zero rect — this repo measured exactly that in
tests/test_e2e_unit_nav.py. Worse, it is state-dependent: content never laid out
may report 0x0 and pass, while the same assertion after a real fold gesture
fails. to_be_hidden() IS correct for the tag filter's [hidden] rows, which are
display:none, and is used for exactly those.
"""

import json
import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _course_with_two_chapters(username="outliner"):
    """part > (chapter A > unit A1) + (chapter B > unit B1), plus a depth-0 unit.

    Every container holds a visible unit, or build_outline's pruning drops it
    before the template ever sees it. The depth-0 unit pins the mixed shape:
    units and containers coexist at the same depth, so "top level open" cannot
    mean "show only containers".
    """
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username=username,
        email=f"{username}@test.example.com",
        password=TEST_PASSWORD,
    )
    course = CourseFactory(title="Algebra")
    Enrollment.objects.create(student=user, course=course)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    chap_a = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Chapter A"
    )
    chap_b = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Chapter B"
    )
    unit_a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a, title="Unit A1"
    )
    unit_b = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_b, title="Unit B1"
    )
    root_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Root Unit"
    )
    return {
        "user": user,
        "course": course,
        "part": part,
        "chap_a": chap_a,
        "chap_b": chap_b,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "root_unit": root_unit,
    }


def _title_sel(node_pk):
    """The clickable title span of ONE group.

    `[data-node='N'] .outline-node__title` is a descendant selector, and a
    container's <details> contains every descendant group's title too — on a part
    it resolves to three spans and .click() raises a strict-mode violation.
    Scoping through `> summary` keeps it to exactly one, at any depth.
    """
    return f"[data-node='{node_pk}'] > summary .outline-node__title"


def _visible(page, selector):
    """checkVisibility() — see the module docstring for why not to_be_hidden()."""
    return page.evaluate(
        "sel => { const el = document.querySelector(sel);"
        "         return !!el && el.checkVisibility(); }",
        selector,
    )


def _is_open(page, node_pk):
    return page.evaluate(
        "pk => document.querySelector(`[data-node='${pk}']`).open", str(node_pk)
    )


def _has_open_attr(page, node_pk):
    """Attribute read, for contexts where page.evaluate is unavailable (JS off)."""
    return page.locator(f"[data-node='{node_pk}']").get_attribute("open") is not None


def _stored(page):
    return page.evaluate(
        "() => { const k = Object.keys(localStorage)"
        ".find(x => x.startsWith('libli_outline_open:'));"
        "        return k ? localStorage.getItem(k) : null; }"
    )


def _wait_for_write(page):
    """Persistence runs inside setTimeout(write, 0) because <summary> activation
    is post-dispatch. Any reload that races it fails intermittently on a CORRECT
    build — the worst thing to debug a mutant against."""
    page.wait_for_function(
        "() => Object.keys(localStorage).some("
        "  k => k.startsWith('libli_outline_open:'))"
    )


@pytest.mark.django_db(transaction=True)
def test_first_visit_opens_depth0_only(page, live_server):
    """T6 + T7. Mutant: render every <details> open."""
    f = _course_with_two_chapters("t7")
    _login(page, live_server, "t7")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # The attribute half is what actually pins D1; a visibility-only assertion
    # also passes under a stray display:none.
    assert _is_open(page, f["part"].pk) is True
    assert _is_open(page, f["chap_a"].pk) is False

    assert _visible(page, f"[data-node='{f['chap_a'].pk}'] > summary")
    assert not _visible(page, f"#node-{f['unit_a'].pk}")
    # Mixed shape: a depth-0 unit row is an ordinary row, always visible.
    assert _visible(page, f"#node-{f['root_unit'].pk}")

    # T6: the computed ACCESSIBLE NAME, not DOM text — a text assertion would
    # merely duplicate the render-tier T3. Do NOT use get_by_role("button", ...):
    # <summary> has no entry in Playwright's implicit-role table, so that locator
    # resolves to ZERO elements and fails on a correct build. Nor
    # page.accessibility.snapshot(), which no longer exists in this version.
    summary = page.locator(f"[data-node='{f['chap_a'].pk}'] > summary")
    expect(summary).to_have_accessible_name(re.compile(r"^Chapter A"))
    expect(summary).not_to_have_accessible_name(re.compile("Start fresh"))


@pytest.mark.django_db(transaction=True)
def test_fold_state_survives_a_round_trip(page, live_server):
    """T8. Mutant: take the snapshot SYNCHRONOUSLY inside the click handler
    instead of inside setTimeout(..., 0) — it reads the pre-click state, so the
    newly-opened chapter is absent from the stored `open` array."""
    f = _course_with_two_chapters("t8")
    _login(page, live_server, "t8")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # Click the TITLE SPAN, not the summary's padding: that click target is what
    # falsifies an e.target.matches() implementation.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    _wait_for_write(page)

    # Assert on the "open" ARRAY, not on the raw JSON string: under the mutant
    # chap_a's pk lands in "closed", so its digits are still in the blob and a
    # substring test passes. (It is pk-fragile too — "4" is in '["14"]'.)
    # The round
    # trip below can be served from Chromium's back/forward cache — nothing in
    # this project sends Cache-Control: no-store — which restores the live DOM
    # WITHOUT re-running outline_tree.js, leaving the chapter open regardless of
    # what was persisted and turning the mutant green.
    assert str(f["chap_a"].pk) in json.loads(_stored(page))["open"]

    page.locator(f"#node-{f['unit_a'].pk} a.outline-unit").click()
    page.wait_for_url(f"**/u/{f['unit_a'].pk}/")
    page.go_back()
    page.reload()  # defeats bfcache: forces a real re-run of the restore path

    assert _is_open(page, f["chap_a"].pk) is True
    assert _is_open(page, f["chap_b"].pk) is False


@pytest.mark.django_db(transaction=True)
def test_expand_all_then_collapse_all(page, live_server):
    """T9. Mutant: make write() a no-op in the toggle-all click handler — the
    reload assertion below goes red. (The separate "label set inline in the click
    handler instead of via syncLabel" mutant belongs to T14, not here.)"""
    f = _course_with_two_chapters("t9")
    _login(page, live_server, "t9")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    button = page.locator("[data-outline-toggle-all]")
    expect(button).to_be_visible()
    expect(button).to_have_text("Expand all")

    button.click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    expect(button).to_have_text("Collapse all")

    _wait_for_write(page)
    page.reload()
    assert _is_open(page, f["chap_a"].pk) is True

    page.locator("[data-outline-toggle-all]").click()
    # Collapse all folds depth 0 too.
    assert _is_open(page, f["part"].pk) is False
```

- [ ] **Step 2: Run them**

```
uv run pytest tests/test_e2e_outline_tree.py -m e2e -q
```

Expected: PASS.

- [ ] **Step 3: Falsify each**

- T7: by hand, make the template emit a bare `open`. `test_first_visit_opens_depth0_only` must FAIL. Remove by hand.
- T8: by hand, in `outline_tree.js`, replace `setTimeout(write, 0)` with `write()`. `test_fold_state_survives_a_round_trip` must FAIL on the `json.loads(...)["open"]` assertion. Remove by hand.
- T9: by hand, make the toggle-all handler skip its `write()`. The test must fail in `_wait_for_write` — the key is never written at all, so it times out there rather than at the reload assertion. That is the same evidence. Remove by hand.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_outline_tree.py
git commit -m "test(outline): e2e for the fold default, persistence and expand-all"
```

---

### Task 8: e2e — the filter interplay and deep links (T10-T13)

**Files:**
- Modify: `tests/test_e2e_outline_tree.py` (append)

**Interfaces:**
- Consumes: Task 7's helpers.
- Produces: `_tag_a_unit`, used by Task 10's T19.

- [ ] **Step 1: Add the tag helper and T10-T13**

```python
def _tag_a_unit(user, unit, name="exam"):
    """The tag MUST be authored by the logged-in student: tags_for_outline filters
    on tag__author=request.user, so a tag owned by anyone else leaves filter_chips
    empty, _tags_filter_bar.html renders nothing, tags.js runs setupFilter only
    `if (bar)` — and every filter assertion below becomes vacuous."""
    from tags.models import Tag
    from tags.models import UnitTag

    tag = Tag.objects.create(author=user, name=name)
    UnitTag.objects.create(tag=tag, unit=unit)
    return tag


@pytest.mark.django_db(transaction=True)
def test_filter_unfolds_matches_and_clearing_restores_the_fold_state(page, live_server):
    """T10 — the R1 guard, the single most damaging thing this feature could get
    wrong: a student's fold state silently destroyed by using the tag filter, with
    the damage only visible after they clear it.

    MUTANT MUST BE TWO-PART: persist inside a `toggle` handler AND remove the
    filterActive write guard. Moving persistence onto `toggle` alone does NOT
    redden this — the suppression still blocks writes during the filtered phase,
    and the post-clear programmatic toggles merely re-write the restored state.
    """
    f = _course_with_two_chapters("t10")
    tag = _tag_a_unit(f["user"], f["unit_b"])
    _login(page, live_server, "t10")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # Open chapter A, leave B folded — this is the state that must survive.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    _wait_for_write(page)
    before = _stored(page)

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    # The match lives inside folded chapter B: it must become visible.
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    expect(page.locator("[data-outline-toggle-all]")).to_be_disabled()
    # A tag_hidden CONTAINER row must compute hidden. This is the guard against
    # §6.2's `display: grid` out-specifying `.outline-node[hidden] {display:none}`
    # (0,2,0) — today's e2e proves that only for a unit row. to_be_hidden() is
    # correct here: these rows are display:none, not folded content.
    expect(page.locator(f"#node-{f['chap_a'].pk}")).to_be_hidden()

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    assert _is_open(page, f["chap_a"].pk) is True
    assert _is_open(page, f["chap_b"].pk) is False, "the pre-filter fold state returns"
    assert _stored(page) == before, "the forced-open state was never persisted"
    expect(page.locator("[data-outline-toggle-all]")).to_be_enabled()


@pytest.mark.django_db(transaction=True)
def test_clearing_a_filter_with_no_stored_key_returns_to_the_default(page, live_server):
    """T11. The load path and the filter-clear restore have OPPOSITE rules for a
    missing key: load leaves the DOM alone, restore treats it as an empty
    partition and drives every group from data-depth. Sharing one rule leaves a
    first-visit student with a fully force-opened tree.

    Mutant: make the restore a no-op when the key is absent."""
    f = _course_with_two_chapters("t11")
    tag = _tag_a_unit(f["user"], f["unit_b"])
    _login(page, live_server, "t11")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    assert _stored(page) is None, "never written — this is the whole point"

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()

    page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']").click()
    assert _is_open(page, f["chap_b"].pk) is False, "back to the D1 default"


@pytest.mark.django_db(transaction=True)
def test_a_filtered_deep_link_load_never_writes_storage(page, live_server):
    """T12. filterActive must be seeded from the PAGE at init, not from the
    libli:tagfilter event — that event arrives after the deep-link handler has
    already run and written.

    Mutant: seed filterActive only from the libli:tagfilter event instead of at
    init — the storage assertion reddens.

    NOT a mutant: dropping `button.disabled = filterActive` from init step 2. On
    a ?tags=N load tags.js's setupFilter ends with an unconditional
    applyFilter(active), dispatching count:1, and §5's count>0 branch sets
    disabled anyway — so the end state is identical and to_be_disabled() (which
    retries) can never see the difference. The init assignment is
    defence-in-depth with no independent e2e observable; do not go looking for
    one.
    """
    f = _course_with_two_chapters("t12")
    tag = _tag_a_unit(f["user"], f["unit_b"])
    _login(page, live_server, "t12")
    page.goto(
        f"{live_server.url}/courses/{f['course'].slug}/"
        f"?tags={tag.pk}#node-{f['chap_b'].pk}"
    )

    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    expect(page.locator("[data-outline-toggle-all]")).to_be_disabled()
    assert _stored(page) is None, "the server's force-opened tree must not persist"


@pytest.mark.django_db(transaction=True)
def test_deep_link_opens_the_target_and_its_ancestors(page, live_server):
    """T13 cases (a) and (b). Case (c) lives in its own test below, because its
    precondition is an EMPTY store that these cases would have populated.

    (a) THREE container levels deep, which the fixture must be extended to
        provide. With only part > chapter, the target's sole ancestor is the
        depth-0 part that D1 already renders open — so "drop the ancestor loop"
        leaves every assertion green. The section below is server-FOLDED, so
        opening it is evidence the loop ran.
        Three mutants, each must redden: drop the ancestor loop; open the
        ancestors but not the target itself; drop the `:target` twin from app.css.
    (b) A #node-<unit-pk> owns no <details> — id="node-N" is on EVERY <li>.
        Mutant: unconditional li.querySelector(":scope > details").open = true.

    Scroll-into-view is deliberately NOT asserted: this fixture renders ~6 rows
    in a 1280x720 viewport, so nothing scrolls and a getBoundingClientRect check
    would pass whether or not scrollIntoView ran. §4.4's scroll is covered by the
    screenshot gate instead.
    """
    from tests.factories import ContentNodeFactory

    f = _course_with_two_chapters("t13")
    section = ContentNodeFactory(
        course=f["course"],
        kind="section",
        unit_type=None,
        parent=f["chap_b"],
        title="Deep Section",
    )
    ContentNodeFactory(
        course=f["course"],
        kind="unit",
        unit_type="lesson",
        parent=section,
        title="Deep Unit",
    )
    _login(page, live_server, "t13")

    page.goto(f"{live_server.url}/courses/{f['course'].slug}/#node-{section.pk}")
    assert _is_open(page, f["part"].pk) is True
    # chap_b is depth 1, so the server rendered it FOLDED. Only the ancestor loop
    # can have opened it — this is the assertion the loop's mutant reddens.
    assert _is_open(page, f["chap_b"].pk) is True, "a folded ancestor was opened"
    assert _is_open(page, section.pk) is True, "the target's OWN details opens"

    # The :target highlight must land on a container reached through
    # outline_tree.js's own deep-link path — the string assertion in
    # test_outline_anchors.py cannot prove that. Mirrors test_e2e_link_dialog.py.
    bg = page.locator(f"[data-node='{section.pk}'] > summary").evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent")

    # (b) a unit-pk hash must scroll and must not throw
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/#node-{f['root_unit'].pk}")
    expect(page.locator(f"#node-{f['root_unit'].pk}")).to_be_visible()
    assert errors == [], f"deep link to a unit row threw: {errors}"


@pytest.mark.django_db(transaction=True)
def test_deep_link_survives_a_failing_storage_write(page, live_server):
    """T13(c) — the count===0 guard, in its OWN test because the spec's
    precondition is "no stored key". Run inside the test above, cases (a)/(b)
    would already have written a partition; with the guard removed the handler
    would then re-open the target FROM STORAGE and pass on the broken build.
    Stubbing setItem blocks new writes but does not clear an existing key, so
    getItem is stubbed too.

    Mutant: remove the `if (!filterActive) return;` guard in the count===0 branch.
    """
    f = _course_with_two_chapters("t13c")
    # Renders the filter bar, without which tags.js never calls setupFilter and
    # no libli:tagfilter event fires at all — the case would be vacuous.
    _tag_a_unit(f["user"], f["unit_b"], name="rev")
    _login(page, live_server, "t13c")
    page.add_init_script(
        "Object.defineProperty(Storage.prototype, 'setItem', "
        "{value: () => { throw new Error('denied'); }});"
        "Object.defineProperty(Storage.prototype, 'getItem', {value: () => null});"
    )
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/#node-{f['chap_b'].pk}")

    assert _is_open(page, f["chap_b"].pk) is True, (
        "tags.js dispatches count:0 on every unfiltered load that renders a filter "
        "bar; without the guard it slams the just-opened ancestors shut"
    )
```

- [ ] **Step 2: Run them**

```
uv run pytest tests/test_e2e_outline_tree.py -m e2e -q
```

Expected: PASS.

- [ ] **Step 3: Falsify each**

Apply each mutant named in the docstrings by hand, one at a time, confirm the matching test goes RED, and remove it by hand. For T10 apply **both** halves of the two-part mutant together, and confirm the one-part version leaves the test green — that is the point of the note.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_outline_tree.py
git commit -m "test(outline): e2e for the tag-filter interplay and deep links"
```

---

### Task 9: e2e — label sync, the storage partition and the reset link (T14-T16)

**Files:**
- Modify: `tests/test_e2e_outline_tree.py` (append)

**Interfaces:**
- Consumes: Task 7's and Task 8's helpers.
- Produces: nothing.

- [ ] **Step 1: Add T14-T16**

```python
@pytest.mark.django_db(transaction=True)
def test_label_tracks_a_single_summary_toggle(page, live_server):
    """T14 — the R3 guard. Mutant: register the toggle listener without
    capture:true. `toggle` does not bubble, so a plain delegated listener never
    fires and the label silently stops updating.

    T9 alone cannot catch this: an implementation that sets the label inline in
    the button handler passes T9 with no toggle listener at all."""
    f = _course_with_two_chapters("t14")
    _login(page, live_server, "t14")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    button = page.locator("[data-outline-toggle-all]")
    button.click()  # expand all
    expect(button).to_have_text("Collapse all")

    # A single summary gesture, not the button, is what exercises the listener.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    expect(button).to_have_text("Expand all")


@pytest.mark.django_db(transaction=True)
def test_storage_partition_semantics(page, live_server):
    """T15, four cases."""
    from tests.factories import ContentNodeFactory

    f = _course_with_two_chapters("t15")
    # A second depth-0 root, holding a visible unit so pruning keeps it.
    root_b = ContentNodeFactory(
        course=f["course"], kind="part", unit_type=None, parent=None, title="Part Two"
    )
    ContentNodeFactory(
        course=f["course"], kind="unit", unit_type="lesson", parent=root_b, title="P2U"
    )
    _login(page, live_server, "t15")
    url = f"{live_server.url}/courses/{f['course'].slug}/"
    key = f"libli_outline_open:{f['course'].slug}"

    # (a) a deliberately collapsed depth-0 root stays collapsed.
    # Mutant: union the stored set with the server default.
    page.goto(url)
    page.locator(_title_sel(f["part"].pk)).click()
    _wait_for_write(page)  # the write is deferred; reloading before it races it
    page.reload()
    assert _is_open(page, f["part"].pk) is False

    # (b) a group in NEITHER array is new since the last write: it falls back to
    # its data-depth default rather than to "closed".
    page.evaluate(
        "([k, pk]) => localStorage.setItem(k, JSON.stringify("
        "{v: 1, open: [], closed: [String(pk)]}))",
        [key, f["part"].pk],
    )
    # Mutant: treat an id in neither array as closed.
    page.reload()
    assert _is_open(page, root_b.pk) is True, "omitted depth-0 root uses data-depth"

    # (c) numeric ids must still apply. The seed CONTRADICTS the default (a
    # depth-1 chapter stored open, default closed), or the case is vacuous.
    # Mutant: drop String() on the read side only.
    page.evaluate(
        "([k, pk]) => localStorage.setItem(k, JSON.stringify("
        "{v: 1, open: [Number(pk)], closed: []}))",
        [key, f["chap_a"].pk],
    )
    page.reload()
    assert _is_open(page, f["chap_a"].pk) is True, "numeric ids normalise via String()"

    # (d) unparseable -> treat as absent, render the server default, never throw.
    # Mutant: drop the try/catch around JSON.parse in read().
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.evaluate("k => localStorage.setItem(k, 'not json')", key)
    page.reload()
    assert _is_open(page, f["part"].pk) is True
    assert errors == []


@pytest.mark.django_db(transaction=True)
def test_start_fresh_link_does_not_disturb_the_fold_state(page, live_server):
    """T16. Fold first, so the baseline is a real non-empty partition — without
    that, "before" and "after" are both None and the assertion compares absence
    to absence.

    The reset navigation is ABORTED by a route handler rather than followed. That
    is what makes the mutant deterministic: §4.2's write is scheduled in
    setTimeout(..., 0) and would otherwise race the browser committing the <a
    href>, so a navigating version reddens only intermittently. With the
    navigation blocked, the mutant (link back inside the <summary>) toggles the
    group and schedules a write on the same page — both observable here.
    """
    f = _course_with_two_chapters("t16")
    _login(page, live_server, "t16")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    page.locator(_title_sel(f["chap_a"].pk)).click()
    _wait_for_write(page)
    before = _stored(page)
    assert before is not None

    page.route("**/reset/**", lambda route: route.abort())
    # NOT `> a.outline-node__reset`: under the mutant the link moves inside the
    # <summary> and a direct-child locator would fail to resolve, reddening this
    # test on T3's structural point instead of on the storage invariant it exists
    # to prove.
    link = page.locator(f"#node-{f['chap_a'].pk} a.outline-node__reset")
    expect(link).to_be_visible()
    link.click()

    page.wait_for_timeout(200)  # let any scheduled write land before asserting
    assert _is_open(page, f["chap_a"].pk) is True, "the group must not have toggled"
    assert _stored(page) == before, "and nothing must have been persisted"
    page.unroute("**/reset/**")

    # The link really does navigate (the route abort is a test device, not the
    # product behaviour). courses/urls.py registers progress_reset at
    # courses/<slug>/reset/<node_pk>/ — there is no "progress/" segment.
    reset_url = f"/courses/{f['course'].slug}/reset/{f['chap_a'].pk}/"
    expect(link).to_have_attribute("href", re.compile(re.escape(reset_url)))

    # Keyboard reachability. Collapse chapter A first: with the group OPEN the
    # next tab stop after the summary is the unit link INSIDE the disclosure, not
    # the sibling reset link — D9 puts that link after </details> in DOM order.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    page.locator(f"[data-node='{f['chap_a'].pk}'] > summary").focus()
    page.keyboard.press("Tab")
    assert page.evaluate(
        "() => document.activeElement.classList.contains('outline-node__reset')"
    )
```

- [ ] **Step 2: Run them**

```
uv run pytest tests/test_e2e_outline_tree.py -m e2e -q
```

Expected: PASS.

- [ ] **Step 3: Falsify each**

Apply each named mutant by hand, confirm RED, remove by hand. For T16 the mutant is "move the reset link back inside the `<summary>`", and it must redden on the fold-state or stored-value assertion — **not** on `expect(link).to_be_visible()`, which would only re-prove T3's structure. The locator is deliberately a descendant selector so the mutant reaches the real assertions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_outline_tree.py
git commit -m "test(outline): e2e for label sync, storage partition and the reset link"
```

---

### Task 10: e2e — the silent CSS regressions and the no-JS path (T17-T19)

**Files:**
- Modify: `tests/test_e2e_outline_tree.py` (append)

**Interfaces:**
- Consumes: Task 7's helpers **and Task 8's `_tag_a_unit`** (T19 filters). If these tasks are ever reordered or split across agents, Task 10 does not run without Task 8.
- Produces: nothing.

- [ ] **Step 1: Add T17-T19**

```python
@pytest.mark.django_db(transaction=True)
def test_nested_type_scale_and_guide_rule_survive_the_details_nesting(
    page, live_server
):
    """T17 — the R6 guard. Both halves are pure-CSS regressions that leave a
    correct DOM and a worse page, with nothing red.

    Mutants, applied separately: (1) omit the `> .outline-node__group >`
    type-scale twins; (2) leave `.outline-node > ul` un-re-pointed.
    """
    from tests.factories import ContentNodeFactory

    f = _course_with_two_chapters("t17")
    section = ContentNodeFactory(
        course=f["course"],
        kind="section",
        unit_type=None,
        parent=f["chap_a"],
        title="A Section",
    )
    ContentNodeFactory(
        course=f["course"], kind="unit", unit_type="lesson", parent=section, title="SU"
    )
    _login(page, live_server, "t17")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")
    page.locator("[data-outline-toggle-all]").click()  # expand all

    chapter_size = page.evaluate(
        "pk => getComputedStyle(document.querySelector("
        "`[data-node='${pk}'] > summary .outline-node__title`)).fontSize",
        str(f["chap_a"].pk),
    )
    assert chapter_size == "17.6px", "1.1rem — the nested chapter type scale"

    section_style = page.evaluate(
        "pk => { const el = document.querySelector("
        "  `[data-node='${pk}'] > summary .outline-node__title`);"
        "  const s = getComputedStyle(el);"
        "  return {size: s.fontSize, transform: s.textTransform}; }",
        str(section.pk),
    )
    assert section_style["size"] == "12px", ".75rem — the section micro-type"
    assert section_style["transform"] == "uppercase"

    guide = page.evaluate(
        "pk => { const ul = document.querySelector(`[data-node='${pk}'] > ul`);"
        "  const s = getComputedStyle(ul);"
        "  return {border: s.borderLeftWidth, pad: s.paddingLeft}; }",
        str(f["chap_a"].pk),
    )
    assert guide["border"] == "1px", "the nested hairline guide rule still applies"
    assert guide["pad"] != "0px"


@pytest.mark.django_db(transaction=True)
def test_toggle_all_stays_hidden_when_there_are_no_groups(page, live_server):
    """T18. "Every group is open" is vacuously true on a container-free course, so
    an un-hidden button would read Collapse all and do nothing.

    Mutant: drop the `&& groups.length` guard from init step 2 so the button is
    un-hidden unconditionally."""
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="t18", email="t18@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Flat")
    Enrollment.objects.create(student=user, course=course)
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Only"
    )
    _login(page, live_server, "t18")
    page.goto(f"{live_server.url}/courses/{course.slug}/")

    button = page.locator("[data-outline-toggle-all]")
    # to_be_hidden() is satisfied by ZERO matching elements, so a build that
    # stopped rendering the button entirely would pass without this count check.
    expect(button).to_have_count(1)
    expect(button).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_folding_and_filtering_work_with_js_off(browser, live_server):
    """T19 — guards D3 and D8 together.

    The outline view is @login_required, so a bare
    new_context(java_script_enabled=False) lands on the login page and the
    assertions pass or fail for the wrong reason. Follow the existing precedent
    in tests/test_e2e_before_after.py: log in with JS on, capture storage_state,
    then open the no-JS context with it.

    Every state read here uses _has_open_attr, NOT _is_open: page.evaluate does
    not work in a JS-disabled context.

    Two mutants: emit a bare `open` in the template (the default half reddens);
    drop the D8 `or active_tag_ids and not item.tag_hidden` arm (the filtered
    half reddens).
    """
    f = _course_with_two_chapters("t19")
    tag = _tag_a_unit(f["user"], f["unit_b"])

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "t19")
    # _login's submit click does not await the navigation, and storage_state()
    # does not serialise against it — every other test happens to, via its next
    # goto(). Without this the no-JS context can start cookie-less and land on
    # the login page, failing for the wrong reason, intermittently.
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")
    storage_state = ctx.storage_state()
    ctx.close()

    nojs = browser.new_context(java_script_enabled=False, storage_state=storage_state)
    page = nojs.new_page()
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    assert _has_open_attr(page, f["part"].pk) is True
    assert _has_open_attr(page, f["chap_a"].pk) is False

    # Native <details> still folds with no JS at all.
    page.locator(f"[data-node='{f['chap_a'].pk}'] > summary").click()
    assert _has_open_attr(page, f["chap_a"].pk) is True

    # D8: the server opens the ancestors of a match, so a no-JS filtered outline
    # is not empty.
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/?tags={tag.pk}")
    assert _has_open_attr(page, f["chap_b"].pk) is True
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    nojs.close()
```

- [ ] **Step 2: Run the whole e2e file**

```
uv run pytest tests/test_e2e_outline_tree.py -m e2e -q
```

Expected: PASS. Use `-n 2` if you parallelise — `-n 8` is slower here because TRUNCATE teardown dominates.

- [ ] **Step 3: Falsify each**

Apply each named mutant by hand (for T17, run both mutants separately — each must redden its own half), confirm RED, remove by hand.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_outline_tree.py
git commit -m "test(outline): e2e for the CSS regressions, empty tree and no-JS path"
```

---

### Task 11: Citation sweep, i18n and the full gate

**Files:**
- Modify: `tests/capture_unit_marker_screenshots.py`, `tests/test_editor_row_css_guards.py`, `tests/test_e2e_filltable_gate.py`, `tests/test_outline_anchors.py` (comment citations only)
- Modify: `locale/*/LC_MESSAGES/django.po` and `.mo`

**Interfaces:**
- Consumes: everything.
- Produces: a branch ready for review.

- [ ] **Step 1: Sweep the rotted `app.css` line citations**

Inserting rules into `app.css`'s `.outline-*` block shifts every line below it, and these citations live in files this branch otherwise never touches — no per-task review can see them. Grep each named file in full rather than trusting the list:

```bash
grep -rn "app\.css:[0-9]" --include=*.py --include=*.css . | grep -v "\.venv"
grep -rn "_outline_node\.html:[0-9]" --include=*.py . | grep -v "\.venv"
```

**The second grep matters and the first must not be narrowed.** Scoping the sweep to
`tests/` misses the second test root and both sibling stylesheets entirely — verified
hits below the insertion point live in `courses/tests/test_beforeafter_css.py`,
`courses/tests/test_filltable_gate_print.py`,
`courses/tests/test_filltable_gate_static.py`,
`courses/tests/test_reveal_scope_agreement.py`,
`courses/static/courses/css/courses.css` (7 citations) and
`courses/static/courses/css/builder.css` (7 citations). And
`tests/test_title_math_assets.py` cites `_outline_node.html:21` — the head `<div>` line
that Task 2 rewrites — which no `app.css:` pattern can find.

Convert `_outline_node.html:21` to a selector-name reference ("the
`.outline-node__head` branch"); `tests/test_courses_progress.py` cites `:3`/`:5`, above
the change and safe.

Fix the `app.css` hits, preferring **selector-name citations over line numbers** so they
cannot rot again:
- `tests/capture_unit_marker_screenshots.py` — cites `app.css:533` (`.outline-unit:hover`) and `:554-556` (`.outline-node:target`), both inside the edited block.
- `tests/test_editor_row_css_guards.py` — cites `:546, :1009, :1192` and `:1452-1478`; all but `:546` sit below the insertion.
- `tests/test_e2e_filltable_gate.py` — cites `:1010`.
- `tests/test_outline_anchors.py` — cites `app.css:488`, which was **already stale** before this branch (the rule it names sits at 504). Do not assume the existing numbers were right.

Unaffected, listed so they are not chased: `tests/test_e2e_media_manager.py` (`:34`), `tests/test_builder_styles.py` (`:136`), and `tests/test_stale_rationale_comments.py` (which asserts on the *string* `app.css:150`) all sit above the insertion.

- [ ] **Step 2: Regenerate the catalogs**

```
uv run python manage.py makemessages -a
uv run python manage.py compilemessages
git diff --stat locale/
```

Expected: **reference-comment churn only**. There are no new msgids — *Expand all*, *Collapse all* and *Start fresh* all already exist with Polish translations. If you see a new `#, fuzzy` entry or an empty `msgstr` for any of the three, a label was misspelled: fix the template rather than the catalog.

- [ ] **Step 3: Guard against an unfilled measurement**

```bash
grep -n "<value>\|<N>\|<M>px\|<YYYY-MM-DD>" core/static/core/css/app.css
```

Expected: **no output**. Task 2 Step 8's placeholders are invalid CSS; if any survived,
the padding was never measured.

- [ ] **Step 4: Run the lint gates**

```
uv run ruff check --no-cache .
uv run ruff format --check .
```

Expected: clean. `--no-cache` matters: the noqa/unused warnings are cached away otherwise, and `ruff format --check` is a separate gate from `ruff check`.

- [ ] **Step 5: Run the non-e2e suite**

```
uv run pytest -q
```

Expected: pass. **Grep the summary line** rather than trusting the exit code.

- [ ] **Step 6: Run the e2e suite**

```
uv run pytest -m e2e -q -n 2
```

Expected: pass. If something fails, A/B it against `master` before blaming this branch — e2e flakes under parallel load.

- [ ] **Step 7: Walk the screenshot gate**

Capture light **and** dark, judging dark separately rather than assuming it follows. Every item below was settled by reasoning rather than by a test, which is why it is here:

1. The chevron's optical fit **and colour** against both a 1.35rem part title and a .75rem uppercase section title.
2. The summary hover fill against the `.rollup` chip — the chip fills with `--surface-sunken`, which is why the hover uses `--surface-raised`.
3. The *Start fresh* link's baseline against a part title.
4. The disabled toggle-all button, **at rest and under `:hover`** (the ghost fill survives `:disabled`; a rest-only capture misses it).
5. The header row's two-group layout.
6. A `:target`ed row — its highlight band must span the **full row**. If it stops short of the reset link, the `<details>` has been confined to column 1 and the compounding-width regression is live.
7. A long-title container row at mobile width (390px).
8. The same long-title row with the **`pl`** catalog active, confirming the measured `padding-inline-end` clears *Zacznij od nowa*.
9. The first paint of a returning student's page: the D1 default is **expected** to show briefly before the stored state applies — that flash is accepted (D2 rules out the server-side fix), not a defect to report.

- [ ] **Step 8: Commit**

Stage the sweep's actual output, not a fixed path list — the citations live in
`courses/` as well as `tests/`, and a `tests/ locale/` add would silently drop them:

```bash
git add -u
git status --short   # confirm ONLY citation comments and locale files are staged
git commit -m "chore(outline): refresh rotted css citations and message catalogs"
```

---

## Self-Review

**Spec coverage.** §1 → Task 1. §2 → Task 2. §3 → Task 4. §4.0/§4.1/§4.2/§4.3 → Task 5. §4.4 → Task 5 (`openHashTarget`) + T13. §4.5 → Task 4 step 3. §5 → Task 5's listener + Task 6's dispatcher. §6.1 → Task 2 steps 6-8. §6.2 → Task 2 step 7, Task 4 step 4, Task 5 step 2. §7 → T6 (accessible name), T19 (no-JS). §8 → Task 2 steps 9-10, Task 6 steps 2-3, Task 11 step 1. §9 R1-R7 → T10/T12, T8, T14, the `checkVisibility` constraint, Task 11 step 2, T17, Task 1 step 6. §10 T1-T19 → Tasks 1-10. §11 out-of-scope items are not implemented anywhere.

**Placeholders.** The only deliberately unfilled value is `padding-inline-end` in Task 2 step 8, which carries a measurement procedure and a recording format rather than a number — a guess there is the documented failure mode.

**Type consistency.** `data-node`/`data-depth`/`.outline-node__group`/`summary.outline-node__head`/`a.outline-node__reset`/`[data-outline-toggle-all]`/`data-course-slug`/`outline-tree--booting`/`libli:tagfilter` are spelled identically in Tasks 2, 4, 5, 6 and every test. `_is_open` (JS-on) and `_has_open_attr` (JS-off) are distinct on purpose.
