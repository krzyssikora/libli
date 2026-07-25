# Student Unit-Page Breadcrumbs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a quiet, one-line breadcrumb (`Course › Part › Chapter › Section`) above the unit title on the student lesson and quiz pages.

**Architecture:** The ancestor chain is harvested from the outline tree `build_unit_nav` already stamps, so it costs zero extra queries. A new template partial renders it, included inside both article partials. All truncation is pure CSS — no JavaScript, no runtime measurement.

**Tech Stack:** Django 5.2 templates, plain CSS with design tokens, pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-07-25-student-unit-breadcrumbs-design.md` — 12 review rounds, 121 applied catches. It is **authoritative**: do not relitigate its decisions. Where this plan and the spec disagree, the spec wins and the plan is the bug.

## Global Constraints

- **Tooling:** `ruff`, `pytest` and `python` are **not** on PATH. Every command runs under `uv run`. `uv run ruff format --check .` and `uv run ruff check .` are part of the gate.
- **Worktree database:** this runs in a git worktree and needs a unique `DATABASE_URL`, or it collides with a concurrent session on the Postgres `test_libli` database. It is configured **durably, via a `.env` file** (Task 1 Step 1) — *not* by exporting a shell variable. A shell `export` would be wrong twice over: agent tool calls do not share shell state between invocations, and `export` is bash syntax on a PowerShell-primary host. `config/settings/base.py` calls `env.read_env()` on a worktree-root `.env`, and `.env` is already in `.gitignore`, so the file is picked up automatically by every `uv run` command and never committed.
- **Zero new JavaScript.** No JS file, no inline script, no resize observer.
- **Zero additional queries.** `tests/test_unit_nav_render.py::test_build_unit_nav_adds_no_queries` asserts 2 queries and must keep passing untouched.
- **Falsification is mandatory.** Every test below names its falsifying mutation. Apply the mutation, confirm **RED**, revert, confirm **GREEN**, and only then commit. A test that cannot be made to fail is not a test.
- **Separator glyph:** `›`, authored **only** in `templates/courses/_unit_crumbs.html`. Never in Python, never in `hidden_path`.
- **Spoken separator:** `HIDDEN_PATH_SEP = ", "` in `courses/rollups.py`.
- **Collapse breakpoint:** `832px`, authored in `px`, strictly within `(640, 1280)`.
- **Minimum supported viewport:** 360px.
- **CSS source order is load-bearing:** base rules → modifier rules → `@media screen and (max-width: 832px)` → `@media print`. Equal specificity throughout; order alone decides.

## File Structure

| File | Responsibility |
|---|---|
| `courses/rollups.py` (modify) | `HIDDEN_PATH_SEP`, `_current_ancestors(tree)`, two new keys on `build_unit_nav`'s return |
| `templates/courses/_unit_crumbs.html` (create) | The entire crumb markup — the only place the `›` glyph is authored |
| `templates/courses/_lesson_article.html` (modify) | One `{% include %}` line |
| `templates/courses/_quiz_article.html` (modify) | One `{% include %}` line |
| `courses/static/courses/css/courses.css` (modify) | `.unit-crumbs` block + collapse query + print query, appended near `.lesson-unit__head` |
| `courses/views_manage.py` (modify) | One comment on `_unit_ancestors` pointing at the rollups twin |
| `tests/test_unit_nav_render.py` (modify) | Tests 1–19 except the e2e ones; owns `COLLAPSE_BREAKPOINT_PX` |
| `tests/test_e2e_unit_crumbs.py` (create) | Playwright e2e; imports `COLLAPSE_BREAKPOINT_PX` from the above |
| `locale/{en,pl}/LC_MESSAGES/django.po` (modify) | The one new msgid, `Breadcrumb` |

**Dependency direction:** exactly one *permanent* cross-module test import, `test_e2e_unit_crumbs` → `test_unit_nav_render`. Never the reverse — the reverse closes a cycle and raises `ImportError` at collection. (Task 7's throwaway QA harness adds two more imports, both pointing the same way; they are deleted with it.)

---

### Task 1: Ancestor chain in `courses/rollups.py`

**Files:**
- Modify: `courses/rollups.py`
- Modify: `courses/views_manage.py` (one comment)
- Test: `tests/test_unit_nav_render.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `courses.rollups.HIDDEN_PATH_SEP: str` — `", "`
  - `courses.rollups._current_ancestors(tree: list[dict]) -> list[ContentNode]`
  - `build_unit_nav(...)` return dict gains `"ancestors": list[ContentNode]` and `"hidden_path": str`

- [ ] **Step 1: Give the worktree its own database, durably**

Write a `.env` at the **worktree root** (next to `manage.py`). `config/settings/base.py` reads it via `env.read_env()`, so every `uv run` command picks it up with no shell state involved:

```bash
cd "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/student-unit-breadcrumbs"
printf 'DATABASE_URL=postgres://libli:libli@localhost:5432/libli_crumbs\n' > .env
```

Do **not** `export` it instead: agent tool calls do not share shell state, so the variable would be gone by the next step and pytest would silently fall back to the default `libli` database — recreating the exact cross-worktree collision this avoids.

Verify it took effect (the printed name must be `libli_crumbs`, not `libli`):

```bash
uv run python -c "from django.conf import settings; import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test'); django.setup(); print(settings.DATABASES['default']['NAME'])"
uv run pytest tests/test_unit_nav_render.py --collect-only -q
```

Expected: `libli_crumbs`, then a clean collection (~14 tests, no errors).

`.env` is gitignored — never stage it.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_unit_nav_render.py`. Add `from courses.rollups import HIDDEN_PATH_SEP` and `from courses.rollups import _current_ancestors` and `from courses.rollups import _stamp_current_chain` to the imports at the top.

```python
def _chain_course(depth):
    """A course with `depth` group ancestors above one lesson unit.

    depth 0 -> unit is a root; 1 -> part; 2 -> part/chapter; 3 -> part/chapter/section.
    Returns (course, groups, unit) with groups root-first.
    """
    course = CourseFactory()
    kinds = ["part", "chapter", "section"][:depth]
    groups, parent = [], None
    for kind in kinds:
        parent = ContentNodeFactory(
            course=course,
            kind=kind,
            parent=parent,
            unit_type=None,
            title=f"{kind.title()} title",
        )
        groups.append(parent)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=parent, title="The Unit"
    )
    return course, groups, unit


@pytest.mark.django_db
@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_current_ancestors_returns_the_chain_root_first(depth):
    student = _make_student(f"anc{depth}")
    course, groups, unit = _chain_course(depth)

    nav = build_unit_nav(course, student, unit)

    assert [n.pk for n in nav["ancestors"]] == [g.pk for g in groups]


@pytest.mark.django_db
def test_current_ancestors_excludes_the_current_unit():
    student = _make_student("anc_excl")
    course, groups, unit = _chain_course(3)

    nav = build_unit_nav(course, student, unit)

    assert unit.pk not in [n.pk for n in nav["ancestors"]]
    assert all(n.kind != "unit" for n in nav["ancestors"])


@pytest.mark.django_db
def test_current_ancestors_returns_empty_for_a_stamped_tree_with_no_match():
    """Stamped-but-unmatched is a legitimate empty result, not an error."""
    student = _make_student("anc_nomatch")
    course, _groups, _unit = _chain_course(2)
    tree = build_outline(course, student)
    _stamp_current_chain(tree, -1)  # a pk that is certainly not in the tree

    assert _current_ancestors(tree) == []


@pytest.mark.django_db
def test_current_ancestors_raises_on_an_unstamped_tree():
    """Distinct from the empty case: forgetting to stamp must fail loudly."""
    student = _make_student("anc_unstamped")
    course, _groups, _unit = _chain_course(2)
    tree = build_outline(course, student)

    with pytest.raises(KeyError):
        _current_ancestors(tree)


@pytest.mark.django_db
def test_current_ancestors_handles_a_skipped_level():
    """A 'Full' course may still hold a unit whose only ancestor is a part."""
    student = _make_student("anc_skip")
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Only Part"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )

    nav = build_unit_nav(course, student, unit)

    assert [n.pk for n in nav["ancestors"]] == [part.pk]


@pytest.mark.django_db
@pytest.mark.parametrize("depth,expected", [(0, ""), (1, ""), (2, "Part title")])
def test_hidden_path_joins_all_but_the_deepest(depth, expected):
    student = _make_student(f"hp{depth}")
    course, _groups, unit = _chain_course(depth)

    assert build_unit_nav(course, student, unit)["hidden_path"] == expected


@pytest.mark.django_db
def test_hidden_path_joins_with_the_spoken_separator_and_never_the_glyph():
    """The visible '›' is aria-hidden; hidden_path is read aloud, so it must not
    contain the glyph or a screen reader announces its Unicode name per crumb."""
    student = _make_student("hp_sep")
    course, groups, unit = _chain_course(3)

    hidden_path = build_unit_nav(course, student, unit)["hidden_path"]

    assert hidden_path == HIDDEN_PATH_SEP.join(g.title for g in groups[:-1])
    assert "›" not in hidden_path
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest tests/test_unit_nav_render.py -k "ancestors or hidden_path" -q
```

Expected: collection error — `ImportError: cannot import name 'HIDDEN_PATH_SEP' from 'courses.rollups'`.

- [ ] **Step 4: Implement `HIDDEN_PATH_SEP` and `_current_ancestors`**

In `courses/rollups.py`, add the constant near the top of the module (with the other module-level names) and the helper immediately after `_top_level_part`:

```python
# The separator used in hidden_path, which is READ ALOUD (it is the ellipsis crumb's
# accessible name). Deliberately NOT the visible "›": the visible separators are
# aria-hidden precisely so AT never announces the glyph's Unicode name, and joining
# hidden_path with it would put the glyph straight back into the accessibility tree.
# The visible glyph is authored only in templates/courses/_unit_crumbs.html.
HIDDEN_PATH_SEP = ", "


def _current_ancestors(tree):
    """Root→parent ContentNodes on the stamped current chain, excluding the unit.

    REQUIRES a tree already stamped by _stamp_current_chain, and reads
    contains_current directly (not via .get()) so an unstamped tree raises KeyError
    loudly — the same contract _top_level_part uses. That is distinct from a stamped
    tree with no match, which legitimately returns [] (build_unit_nav already handles
    the no-match case defensively for prev/next).

    Pure dict traversal over an already-materialised tree — no queries.

    NOTE: courses/views_manage.py::_unit_ancestors does the same job for the BUILDER
    breadcrumb by walking node.parent. The duplication is deliberate: the builder side
    has no materialised tree to read from, so a parent walk is right there, whereas
    here a walk would cost up to 3 extra queries per page load.
    """
    ancestors = []
    level = tree
    while True:
        match = next((d for d in level if d["contains_current"]), None)
        if match is None:
            return ancestors
        if not match["is_unit"]:
            ancestors.append(match["node"])
        level = match["children"]
```

- [ ] **Step 5: Wire the two new keys into `build_unit_nav`**

In `build_unit_nav`, after the existing `_stamp_current_chain(tree, current_node.pk)` call and the `part_progress` block, add:

```python
    ancestors = _current_ancestors(tree)
```

and extend the returned dict with:

```python
        "ancestors": ancestors,
        "hidden_path": HIDDEN_PATH_SEP.join(a.title for a in ancestors[:-1]),
```

Update the docstring's return line. **Careful — the sentence continues on the same line.** The existing text is:

```
    Returns {tree, current_pk, prev, next, part_progress, course_progress}. Prev/Next
    are the immediate neighbours of current_node among the is_unit leaves of the
```

Replace **only the first sentence**, keeping the "Prev/Next are the immediate neighbours…" sentence intact. The result:

```
    Returns {tree, current_pk, prev, next, part_progress, course_progress, ancestors,
    hidden_path}. ancestors is the root→parent chain of the current unit (0–3 nodes,
    unit excluded); hidden_path joins all but the deepest with HIDDEN_PATH_SEP and is
    the collapsed "…" crumb's tooltip and accessible name. Prev/Next
    are the immediate neighbours of current_node among the is_unit leaves of the
    already-computed build_outline tree, located by pk (the walk builds its own node
    instances, distinct from the view's current_node). No queries beyond
    build_outline's.
```

- [ ] **Step 6: Add the reciprocal comment in `views_manage.py`**

Above `_unit_ancestors`, add:

```python
# Twin of courses.rollups._current_ancestors, which serves the STUDENT breadcrumb.
# Deliberately separate: that one reads an already-materialised outline tree for free,
# this one walks node.parent because the builder has no such tree. Keep both.
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/test_unit_nav_render.py tests/test_courses_rollups.py -q
```

`test_courses_rollups.py` is included because it is the module that owns `courses/rollups.py`'s coverage — five of its tests exercise `build_unit_nav` directly — and this is the first task to touch production Python.

Expected: all pass, including the pre-existing `test_build_unit_nav_adds_no_queries` — the new work is pure dict traversal and must not move the query count off 2.

- [ ] **Step 8: Falsify each new test**

Apply each mutation, confirm RED, revert, confirm GREEN:

| Test | Mutation |
|---|---|
| `test_current_ancestors_returns_the_chain_root_first` | `return ancestors[::-1]` |
| `test_current_ancestors_excludes_the_current_unit` | drop the `if not match["is_unit"]:` guard |
| `..._empty_for_a_stamped_tree_with_no_match` | `raise KeyError` when `match is None` |
| `..._raises_on_an_unstamped_tree` | `d.get("contains_current")` instead of `d["contains_current"]` |
| `..._handles_a_skipped_level` | filter ancestors to `kind == "chapter"` |
| `test_hidden_path_joins_all_but_the_deepest` | join over `ancestors` instead of `ancestors[:-1]` |
| `..._never_the_glyph` | set `HIDDEN_PATH_SEP = " › "` |

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff format . && uv run ruff check . --fix
git add courses/rollups.py courses/views_manage.py tests/test_unit_nav_render.py
git commit -m "feat(courses): expose the current unit's ancestor chain on unit_nav"
```

---

### Task 2: The crumb partial and its placement

**Files:**
- Create: `templates/courses/_unit_crumbs.html`
- Modify: `templates/courses/_lesson_article.html`
- Modify: `templates/courses/_quiz_article.html`
- Test: `tests/test_unit_nav_render.py`

**Interfaces:**
- Consumes: `unit_nav.ancestors`, `unit_nav.hidden_path` (Task 1); `course.title`, `course.slug`, `course.language` from the existing context.
- Produces: the DOM contract every later task asserts against — `nav.unit-crumbs` > `ol.unit-crumbs__list` > `li.unit-crumbs__item.unit-crumbs__item--{course,ellipsis,mid,leaf}`, each non-first item containing `span.unit-crumbs__sep` then `span.unit-crumbs__label` (the course item's label is the `<a>`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_unit_nav_render.py`:

```python
@pytest.mark.django_db
def test_crumb_renders_the_full_chain_with_one_leading_separator_each(client):
    student = _make_student("crumb_chain")
    course, groups, unit = _chain_course(3)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    soup = _crumb_nav(html)
    items = soup.select("li.unit-crumbs__item")
    # course + ellipsis + 3 ancestors
    assert len(items) == 5
    # The course crumb has NO separator; every later crumb has exactly one.
    assert items[0].select("span.unit-crumbs__sep") == []
    for item in items[1:]:
        assert len(item.select("span.unit-crumbs__sep")) == 1
    assert {s.get_text(strip=True) for s in soup.select("span.unit-crumbs__sep")} == {
        "›"
    }
    assert all(
        s.get("aria-hidden") == "true" for s in soup.select("span.unit-crumbs__sep")
    )


@pytest.mark.django_db
def test_course_crumb_links_to_the_outline_and_carries_its_title(client):
    student = _make_student("crumb_course")
    course, _groups, unit = _chain_course(2)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode())

    li = soup.select_one("li.unit-crumbs__item--course")
    assert li["title"] == course.title
    assert li.select_one("a.unit-crumbs__label")["href"] == f"/courses/{course.slug}/"


@pytest.mark.django_db
def test_group_crumbs_are_plain_text_never_links(client):
    student = _make_student("crumb_plain")
    course, _groups, unit = _chain_course(3)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode())

    for cls in ("--mid", "--leaf", "--ellipsis"):
        for li in soup.select(f"li.unit-crumbs__item{cls}"):
            assert li.select("a") == [], f"{cls} crumb must not be a link"


@pytest.mark.django_db
def test_flat_course_renders_the_course_crumb_and_no_ellipsis(client):
    student = _make_student("crumb_flat")
    course, _groups, unit = _chain_course(0)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode())

    assert soup.select_one("li.unit-crumbs__item--course") is not None
    assert soup.select("li.unit-crumbs__item--ellipsis") == []
    assert soup.select("li.unit-crumbs__item--mid") == []


@pytest.mark.django_db
def test_ellipsis_carries_hidden_path_as_title_and_visually_hidden_text(client):
    """The visually-hidden span is the SOLE accessibility carrier for the collapsed
    crumbs — at the collapse breakpoint the mids are display:none and gone from the
    accessibility tree. Without this test, deleting the span ships green."""
    student = _make_student("crumb_ellipsis")
    course, groups, unit = _chain_course(3)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode())

    expected = HIDDEN_PATH_SEP.join(g.title for g in groups[:-1])
    li = soup.select_one("li.unit-crumbs__item--ellipsis")
    assert li is not None
    assert li["title"] == expected
    assert li.select_one("span.visually-hidden").get_text(strip=True) == expected
    assert li.get("aria-hidden") is None


@pytest.mark.django_db
def test_ellipsis_is_gated_on_ancestor_count_not_on_hidden_path_being_truthy(client):
    """Two ancestors whose mid has a blank title yields hidden_path == "" while the
    CSS still hides one crumb. Gating on the string would drop the ellipsis and
    silently break invariant 5."""
    student = _make_student("crumb_blank")
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title=""
    )
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part, unit_type=None, title="Chapter"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter
    )
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode())

    assert soup.select_one("li.unit-crumbs__item--ellipsis") is not None


@pytest.mark.django_db
def test_crumb_lives_inside_the_lesson_article(client):
    """The two-file include is justified entirely by padding and lang inheritance from
    the <article>. A later 'de-duplicate into _unit_shell.html' refactor would keep
    every other test green while breaking both."""
    student = _make_student("crumb_place")
    course, _groups, unit = _chain_course(2)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    soup = BeautifulSoup(html, "html.parser")

    assert soup.select_one("article.lesson nav.unit-crumbs") is not None


@pytest.mark.django_db
def test_crumb_sets_ui_language_on_the_nav_and_course_language_on_each_item(client):
    """Author titles are course-language; the aria-label is UI-language. Both live
    inside <article lang="{{ course.language }}">, so the nav must override.

    UI = pl, course = en — deliberately INVERTED from the defaults. settings
    .LANGUAGE_CODE is "en" and conftest's autouse fixture pins the active language to
    it, so a UI-language assertion of "en" would also pass against a hardcoded
    lang="en" on the nav. Driving the UI to pl makes the two values distinguishable.
    The session key is how this repo switches UI language for a client request
    (SessionLocaleMiddleware); see tests/test_catalog_views.py for the precedent.
    """
    from core.middleware import LANGUAGE_SESSION_KEY

    student = _make_student("crumb_lang")
    course = CourseFactory(language="en")
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part One"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)
    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()

    soup = _crumb_nav(client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode())

    assert soup.select_one("nav.unit-crumbs")["lang"] == "pl"  # UI language
    items = soup.select("li.unit-crumbs__item")
    assert items and all(li["lang"] == "en" for li in items)  # course language


@pytest.mark.django_db
def test_crumb_carries_the_aria_scaffolding(client):
    """WebKit drops list semantics under list-style:none, and changing an <li>'s
    display away from list-item is a second trigger — hence both roles."""
    student = _make_student("crumb_aria")
    course, _groups, unit = _chain_course(2)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode())

    assert soup.select_one("nav.unit-crumbs")["aria-label"].strip()
    assert soup.select_one("ol.unit-crumbs__list")["role"] == "list"
    items = soup.select("li.unit-crumbs__item")
    assert items and all(li["role"] == "listitem" for li in items)
```

Add these imports at the top of the file:

```python
from bs4 import BeautifulSoup
```

and this helper next to `_course_with_part`:

```python
def _crumb_nav(html):
    """The crumb <nav> as soup. The unit page renders the tree twice (rail + drawer)
    but the crumb exactly once, so select_one is unambiguous."""
    return BeautifulSoup(html, "html.parser").select_one("nav.unit-crumbs")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_unit_nav_render.py -k crumb -q
```

Expected: all nine fail. Eight raise `AttributeError: 'NoneType' object has no attribute 'select'` — the partial does not exist, so `_crumb_nav` returns `None`. `test_crumb_lives_inside_the_lesson_article` builds its own soup instead and fails with a plain `AssertionError`; that is correct, not a symptom of something else being wrong.

- [ ] **Step 3: Create the partial**

Create `templates/courses/_unit_crumbs.html`:

```django
{% load i18n %}{% get_current_language as LANGUAGE_CODE %}
{% comment %}Student breadcrumb: the path TO this unit. The current unit is deliberately
NOT a crumb — the <h1> immediately below already names it. Only the course crumb is a
link; part/chapter/section have no student-facing page.

Every separator lives INSIDE the <li> it introduces. Two reasons: an <ol>'s content
model permits only <li> children (sibling <span>s would also undermine role="list"),
and it makes the hide-the-separator-with-its-crumb rule structural instead of a
hand-maintained pairing convention.

lang is split on purpose: the nav takes the UI language so the aria-label is announced
correctly, and each <li> takes the course language back for the author-written titles —
which the surrounding <article lang="{{ course.language }}"> would otherwise have
supplied for both. On the <li> rather than the label so it also covers the title
attribute, which holds the same author content.{% endcomment %}
<nav class="unit-crumbs" aria-label="{% trans 'Breadcrumb' %}" lang="{{ LANGUAGE_CODE }}">
  <ol class="unit-crumbs__list" role="list">
    <li class="unit-crumbs__item unit-crumbs__item--course" role="listitem"
        lang="{{ course.language }}" title="{{ course.title }}">
      <a class="unit-crumbs__label" href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
    </li>
    {% if unit_nav.ancestors|length > 1 %}
      {% comment %}Gated on ancestor COUNT, not on hidden_path being truthy: the CSS hides
      mids structurally, so a blank mid title would empty the string while a crumb was
      still hidden. Rendered at every width; CSS reveals it below the breakpoint.{% endcomment %}
      <li class="unit-crumbs__item unit-crumbs__item--ellipsis" role="listitem"
          lang="{{ course.language }}" title="{{ unit_nav.hidden_path }}">
        <span class="unit-crumbs__sep" aria-hidden="true">›</span>
        <span class="unit-crumbs__label">…<span class="visually-hidden">{{ unit_nav.hidden_path }}</span></span>
      </li>
    {% endif %}
    {% for a in unit_nav.ancestors %}
      <li class="unit-crumbs__item unit-crumbs__item--{% if forloop.last %}leaf{% else %}mid{% endif %}"
          role="listitem" lang="{{ course.language }}" title="{{ a.title }}">
        <span class="unit-crumbs__sep" aria-hidden="true">›</span>
        <span class="unit-crumbs__label">{{ a.title }}</span>
      </li>
    {% endfor %}
  </ol>
</nav>
```

- [ ] **Step 4: Include it in both article partials**

In `templates/courses/_lesson_article.html`, immediately above `<div class="lesson-unit__head">`:

```django
  {% include "courses/_unit_crumbs.html" %}
```

In `templates/courses/_quiz_article.html`, immediately above `<h1 class="lesson-unit__title">`:

```django
  {% include "courses/_unit_crumbs.html" %}
```

- [ ] **Step 5: Run the tests, then the whole suite**

```bash
uv run pytest tests/test_unit_nav_render.py -q
uv run pytest -q
```

Expected: both green. **The full-suite run is not optional here.** This task inserts a `<nav>`, an `<ol>` and an `<a href="/courses/<slug>/">` as the first child of `article.lesson` and `article.quiz`, which every existing test that parses a unit page can see. Catching collateral breakage now costs one fix; catching it in Task 7 means bisecting across five commits and a design pass.

- [ ] **Step 6: Falsify each new test**

| Test | Mutation |
|---|---|
| `..._one_leading_separator_each` | move the `<span class="unit-crumbs__sep">` out of the `<li>`, before it |
| `..._links_to_the_outline_and_carries_its_title` | delete `title="{{ course.title }}"` |
| `..._plain_text_never_links` | wrap `{{ a.title }}` in an `<a href="#">` |
| `..._flat_course_..._no_ellipsis` | change the gate to `{% if True %}` |
| `..._hidden_path_as_title_and_visually_hidden_text` | delete the `<span class="visually-hidden">` |
| `..._gated_on_ancestor_count_...` | change the gate to `{% if unit_nav.hidden_path %}` |
| `..._inside_the_lesson_article` | move the include into `_unit_shell.html` |
| `..._ui_language_on_the_nav_...` | delete `lang="{{ LANGUAGE_CODE }}"` (then, separately, the `<li>`'s `lang`) |
| `..._aria_scaffolding` | delete `role="list"` (then, separately, `role="listitem"`) |

- [ ] **Step 7: Commit**

```bash
uv run ruff format . && uv run ruff check .
git add templates/courses/_unit_crumbs.html templates/courses/_lesson_article.html templates/courses/_quiz_article.html tests/test_unit_nav_render.py
git commit -m "feat(courses): render student breadcrumbs above the unit title"
```

---

### Task 3: Coverage at every render site, and the quiz-results non-goal

**Files:**
- Test: `tests/test_unit_nav_render.py`

**Interfaces:**
- Consumes: the DOM contract from Task 2.
- Produces: nothing consumed downstream. Pure coverage.

**Why this is its own task:** the quiz side is *not* single-sourced — `build_quiz_context` does not call `build_unit_nav`; `quiz_unit` and `_quiz_render_feedback` each set `ctx["unit_nav"]` themselves. Those sites need fixture states that are easy to get wrong, and they are exactly the paths most likely to lose the crumb in a refactor.

- [ ] **Step 1: Write the failing tests**

Add these imports at the top of the file:

```python
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import QuizSubmission
from tests.factories import add_element
from tests.factories import make_quiz_unit
```

```python
def _quiz_course():
    """A course whose single unit is a quiz with one answerable question.

    Uses the repo's real element API: a ChoiceQuestionElement plus Choice rows,
    attached to the unit through an Element join-row via add_element().
    """
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Quiz Part"
    )
    unit = make_quiz_unit(course=course, parent=part, title="The Quiz")
    question = ChoiceQuestionElement.objects.create(stem="<p>2+2?</p>", multiple=False)
    right = Choice.objects.create(question=question, text="4", is_correct=True, order=0)
    Choice.objects.create(question=question, text="5", is_correct=False, order=1)
    element = add_element(unit, question)
    return course, part, unit, element, right


@pytest.mark.django_db
def test_crumb_renders_on_the_quiz_page(client):
    """quiz_unit redirects a SUBMITTED quiz away, so the student must have no
    submission for this GET to reach _quiz_article.html at all."""
    student = _make_student("crumb_quiz")
    course, part, unit, _element, _right = _quiz_course()
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    # Go straight to quiz_unit. The lesson_unit URL 302s a quiz node here, so a GET
    # without follow=True would return an empty 302 body and fail regardless of the
    # implementation — see the same trap documented in this file's existing
    # test_unit_shell_part_chip_hidden_for_root_unit.
    url = reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    soup = BeautifulSoup(client.get(url).content.decode(), "html.parser")

    assert soup.select_one("article.quiz nav.unit-crumbs") is not None
    assert part.title in soup.select_one("nav.unit-crumbs").get_text()


@pytest.mark.django_db
def test_crumb_survives_the_no_js_check_answer_re_render(client):
    """Omitting the fragment header makes check_answer re-render the whole page."""
    student = _make_student("crumb_check")
    course, groups, unit = _chain_course(2)
    question = ChoiceQuestionElement.objects.create(stem="<p>2+2?</p>", multiple=False)
    right = Choice.objects.create(
        question=question, text="4", is_correct=True, order=0
    )
    element = add_element(unit, question)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": element.pk},
    )
    soup = BeautifulSoup(
        client.post(url, {"choice": str(right.pk)}).content.decode(), "html.parser"
    )

    nav = soup.select_one("nav.unit-crumbs")
    assert nav is not None
    assert groups[-1].title in nav.get_text()


@pytest.mark.django_db
def test_crumb_survives_the_no_js_quiz_answer_re_render(client):
    """quiz_answer needs an ENROLLED student (a previewer gets PermissionDenied), an
    unlocked response with attempts left, and a NON-EMPTY answer — an empty POST
    takes the validation branch instead."""
    student = _make_student("crumb_qa")
    course, part, unit, element, right = _quiz_course()
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    url = reverse(
        "courses:quiz_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": element.pk},
    )
    soup = BeautifulSoup(
        client.post(url, {"choice": str(right.pk)}, follow=True).content.decode(),
        "html.parser",
    )

    nav = soup.select_one("nav.unit-crumbs")
    assert nav is not None
    assert part.title in nav.get_text()


@pytest.mark.django_db
def test_submitted_quiz_results_page_has_no_crumb(client):
    """Stated non-goal: quiz_results.html is outside _unit_shell.html, has no
    unit_nav, and is deliberately not covered. Also guards the redirect the quiz-GET
    fixture above depends on."""
    student = _make_student("crumb_results")
    course, _part, unit, _element, _right = _quiz_course()
    EnrollmentFactory(student=student, course=course)
    QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    client.force_login(student)

    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/", follow=True)

    assert resp.redirect_chain, "a SUBMITTED quiz must redirect to the results page"
    assert "unit-crumbs" not in resp.content.decode()
```

> **Verified against the worktree:** `ChoiceQuestionElement(stem=…, multiple=…)` + `Choice(question=…, text=…, is_correct=…, order=…)` + `add_element(unit, question)` is the repo's real element API (see `tests/test_choice_inline_feedback.py`); `QuizSubmission.Status.SUBMITTED` exists; the two URL names are `courses:check_answer` (`…/u/<node_pk>/q/<element_pk>/check/`) and `courses:quiz_answer` (`…/u/<node_pk>/quiz/q/<element_pk>/answer/`) — use `reverse()`, not literal paths. `QuizSubmission` may carry additional required fields; if `create()` complains, supply them, but do not change the assertions.

- [ ] **Step 2: Run to verify they fail**

Temporarily comment out both include lines. Use the **single-line** `{# … #}` form — this repo has a recorded lesson that `{# #}` must stay on one line, and an HTML comment would not work at all because Django still evaluates tags inside `<!-- -->`, leaving the include rendering and the RED check vacuous:

```django
{# {% include "courses/_unit_crumbs.html" %} #}
```

Then:

```bash
uv run pytest tests/test_unit_nav_render.py -k "crumb_quiz or crumb_check or crumb_qa or crumb_results" -q
```

Expected: **4 collected** — the three positive tests FAIL (`nav is None`), and `test_submitted_quiz_results_page_has_no_crumb` passes either way, since it is falsified differently in Step 4. (The narrow `-k` names matter: a broader filter like `-k quiz` also sweeps in the pre-existing `test_all_quiz_group_renders_no_counter_and_no_check`, which passes regardless and makes the expected output harder to read.)

**Restore both includes** and re-run to confirm GREEN before moving on. Step 4 re-applies a similar mutation per-test; that overlap is deliberate — this step proves the three positives are wired to the include at all, Step 4 proves each one is wired to the *specific* thing it names.

- [ ] **Step 3: Run to verify they pass**

```bash
uv run pytest tests/test_unit_nav_render.py -q
```

Expected: all pass.

- [ ] **Step 4: Falsify**

| Test | Mutation |
|---|---|
| `..._on_the_quiz_page` | remove the include from `_quiz_article.html` |
| `..._check_answer_re_render` | same, from `_lesson_article.html` |
| `..._quiz_answer_re_render` | delete `ctx["unit_nav"] = ...` in `_quiz_render_feedback` |
| `..._results_page_has_no_crumb` | add the include to `templates/courses/quiz_results.html` |

- [ ] **Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check .
git add tests/test_unit_nav_render.py
git commit -m "test(courses): cover the crumb at every unit render site"
```

---

### Task 4: CSS — the one-line collapse mechanic

**Files:**
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_unit_nav_render.py`

**Interfaces:**
- Consumes: the class names from Task 2.
- Produces: `tests.test_unit_nav_render.COLLAPSE_BREAKPOINT_PX: int = 832`, imported by Task 6's e2e module.

- [ ] **Step 1: Write the failing drift-guard test**

```python
COLLAPSE_BREAKPOINT_PX = 832


def _media_block(css, query):
    """The body of the @media block introduced by `query`, by brace matching."""
    start = css.index(query) + len(query)
    depth, i = 0, start
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start : i + 1]
        i += 1
    raise AssertionError(f"unterminated @media block for {query!r}")


def test_collapse_breakpoint_is_in_bounds_and_matches_the_stylesheet():
    """Invariant 7 plus the CSS<->constant coupling.

    The range check is not redundant with the string check: because the expected
    query is DERIVED from the constant, a retune updates constant, CSS and expected
    string in lockstep and every other assertion stays green — while the e2e's third
    viewport (BREAKPOINT + 1) silently slides below 640 into the rail-less regime and
    stops sampling the four-crumb worst case. This bare range check is the only thing
    standing between that retune and a vacuous e2e.
    """
    assert 640 < COLLAPSE_BREAKPOINT_PX < 1280

    css = (
        Path(__file__).resolve().parent.parent
        / "courses/static/courses/css/courses.css"
    ).read_text(encoding="utf-8")

    query = f"@media screen and (max-width: {COLLAPSE_BREAKPOINT_PX}px)"
    assert query in css, f"stylesheet does not contain {query!r}"
    # Assert the crumb rule is INSIDE that block: a bare "max-width: NNNpx" substring
    # could be satisfied by an unrelated pre-existing query at some values.
    assert ".unit-crumbs__item--mid" in _media_block(css, query)
```

Placement: define `COLLAPSE_BREAKPOINT_PX` immediately after the imports (Task 6 imports it, so it must be module-level and easy to find), and append `_media_block` plus the test at the end of the file. Add `from pathlib import Path` to the imports.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_unit_nav_render.py -k collapse_breakpoint -q
```

Expected: FAIL — `stylesheet does not contain '@media screen and (max-width: 832px)'`.

- [ ] **Step 3: Add the CSS**

**Insert** into `courses/static/courses/css/courses.css` — not append. The block goes immediately after the last `.unit-done` rule (`.unit-done.is-complete .unit-done__pill { … }`, currently ~line 687) and **before** the `/* Mobile drawer … */` comment, so it sits adjacent to the `.lesson-unit__head` rules it belongs with, as the spec asks. Appending at end-of-file would put it after the `.el--tabs` `@media print` block instead, producing a different diff and orphaning it from its neighbours.

**The order of the four groups below is load-bearing** — base, then modifiers, then the screen query, then print. All four target the same elements at identical specificity and media queries add no specificity, so source order alone decides. Authoring the collapse query above the modifiers leaves the `…` permanently hidden; authoring print above the base stops the printout wrapping.

```css
/* ── Student breadcrumbs (path TO the unit; the <h1> below is the unit itself) ──
   "Pinned ends, squeezed middle": the course crumb and the deepest crumb survive,
   the middle absorbs the squeeze and then collapses to "…" below the breakpoint.
   One line always, zero JS. The four rule groups below MUST stay in this order —
   base, modifiers, screen query, print — because every collision between them is at
   equal specificity and is resolved by source order alone. */
.unit-crumbs { --crumb-gap: var(--space-2); margin-bottom: var(--space-3); }

/* padding/margin here are the focus-ring allowance, NOT a reset. The list is the one
   ancestor that clips the course link's focus ring (overflow:hidden clips on all four
   sides); 5px = the repo's 4px ring plus 1px of slack so the containment check does
   not sit on a zero-margin equality. The negative margin cancels it so the strip stays
   flush with the <h1>. Do not "tidy" either to 0. */
.unit-crumbs__list {
  display: flex; flex-wrap: nowrap; align-items: center; overflow: hidden;
  list-style: none; gap: var(--crumb-gap); padding: 5px; margin: -5px;
  font-size: .85rem; color: var(--text-tertiary);
}
/* align-items:center, not baseline: a flex item with overflow:hidden is a scroll
   container and exposes no text baseline, so the UA synthesises one from its border
   box and the label sits a few pixels off its own separator. */
.unit-crumbs__item {
  display: flex; align-items: center; min-width: 0; gap: var(--crumb-gap);
}
/* Clipping lives on the LABEL, never on the <li>. No min-width of any kind here:
   overflow:hidden already zeroes this element's automatic minimum size, and a floor
   here would be a floor on a descendant that flexbox does not consult when sizing the
   <li> — the label would then overflow its own crumb and paint over its neighbour. */
.unit-crumbs__label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unit-crumbs__sep { flex: 0 0 auto; }
a.unit-crumbs__label { color: inherit; text-decoration: none; }
a.unit-crumbs__label:hover { text-decoration: underline; }
a.unit-crumbs__label:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

/* Modifiers — AFTER the base rule, or min-width:0 wins and the floors never apply.
   Floors are on the <li> (the flex item the list actually shrinks) and sized to cover
   the separator's advance plus the internal gap. --course has no separator, so it
   takes the bare 6ch: carrying the extra term there would be dead width that shifts
   the shrink balance against the leaf at the narrowest widths. */
.unit-crumbs__item--mid { flex-shrink: 200; min-width: calc(4ch + 1em + var(--crumb-gap)); }
.unit-crumbs__item--course { flex-shrink: 3; min-width: 6ch; }
.unit-crumbs__item--leaf { flex-shrink: 1; min-width: calc(6ch + 1em + var(--crumb-gap)); }
.unit-crumbs__item--ellipsis { display: none; flex: 0 0 auto; }

/* Collapse — AFTER the modifiers (the --ellipsis display pair is decided by order).
   Scoped to `screen` so print never collapses. 832px, not the shell's 640px: the
   narrowest column that must hold four UNCOLLAPSED crumbs is just above the shell
   breakpoint (~369px at 641px, where the 14rem rail is still present). */
@media screen and (max-width: 832px) {
  .unit-crumbs__item--mid { display: none; }
  .unit-crumbs__item--ellipsis { display: flex; }
}

/* Print — LAST. Resetting the LIST's overflow matters as much as the label's: leaving
   it hidden means a single unbreakable 200-char title escapes the now-visible label
   and is clipped by the list, losing printed text silently. Cf. the .el--tabs print
   block below, which exists because a screen-only rule once did exactly that. */
@media print {
  .unit-crumbs__list { flex-wrap: wrap; overflow: visible; }
  .unit-crumbs__label {
    overflow: visible; white-space: normal; text-overflow: clip; overflow-wrap: anywhere;
  }
}
```

- [ ] **Step 4: Run to verify it passes, then the whole suite**

```bash
uv run pytest tests/test_unit_nav_render.py -q
uv run pytest -q
```

Expected: both green. The full-suite gate repeats here because the CSS is the last change before the browser tests, and a stylesheet edit can break existing render or e2e assertions that match on markup near `.lesson-unit__head`.

- [ ] **Step 5: Falsify**

| Assertion | Mutation |
|---|---|
| range check | set `COLLAPSE_BREAKPOINT_PX = 600` (expect RED on the range line, **not** the string line — the string is derived, so it would still match if you also edited the CSS; that is the point of the range check) |
| query-present | change the CSS query to `@media (max-width: 832px)` (drop `screen and`) |
| rule-inside-block | move `.unit-crumbs__item--mid { display: none; }` outside the query |

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check .
git add courses/static/courses/css/courses.css tests/test_unit_nav_render.py
git commit -m "feat(ui): one-line breadcrumb collapse, pure CSS"
```

---

### Task 5: i18n catalogue

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

**Interfaces:** consumes the `{% trans 'Breadcrumb' %}` from Task 2. Produces nothing.

- [ ] **Step 1: Extract**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

- [ ] **Step 2: Inspect for fuzzy damage**

```bash
grep -n -B2 -A4 'msgid "Breadcrumb"' locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
grep -c "#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
```

Expected: `0` for both files. `tests/test_i18n_po_health.py` asserts zero fuzzy entries across both catalogues, so any non-zero count must be cleared — two deletions each — before Step 4.

A fuzzy entry can arrive **pre-filled from an unrelated msgid**; clearing the flag without replacing the text promotes a wrong translation. Clearing a fuzzy is **two** deletions — the `#, fuzzy` line *and* the `#| msgid` line above it.

- [ ] **Step 3: Set the Polish translation**

In `locale/pl/LC_MESSAGES/django.po`:

```po
msgid "Breadcrumb"
msgstr "Ścieżka nawigacji"
```

Leave the `en` msgstr empty (gettext falls back to the source string), matching the file's existing convention.

- [ ] **Step 4: Compile and verify**

```bash
uv run python manage.py compilemessages
uv run pytest tests/test_i18n_po_health.py -q
```

Expected: PASS. That module forbids `#~` obsolete entries and `#, fuzzy` flags across the whole catalogue, so it is the real gate here.

- [ ] **Step 5: Commit**

```bash
git add locale/
git commit -m "i18n: add the Breadcrumb aria-label (en, pl)"
```

---

### Task 6: Playwright e2e

**Files:**
- Create: `tests/test_e2e_unit_crumbs.py`

**Interfaces:**
- Consumes: `tests.test_unit_nav_render.COLLAPSE_BREAKPOINT_PX`; `courses.rollups.HIDDEN_PATH_SEP`; the DOM contract from Task 2; the CSS from Task 4.
- Produces: nothing.

**Import direction:** this module imports from `test_unit_nav_render`, never the reverse. The reverse closes a cycle that raises `ImportError` at collection depending on which module pytest imports first.

- [ ] **Step 1: Write the file**

```python
"""Playwright e2e for the student unit-page breadcrumbs.

The CSS *is* the feature here, so these are the tests that actually protect it.
Three viewports, because 360px and 1280px alone never exercise the state where mids
are visible but squeezed: at 360px they are hidden and at 1280px there is room to
spare. The worst case sits just above the collapse breakpoint, where the 14rem rail
is still present and the column is at its narrowest for four uncollapsed crumbs.

Marked e2e (excluded from the default run). Run focused and in the FOREGROUND — a
background `-m e2e` sweep spawns runaway browsers.
"""

import os

import pytest

from courses.rollups import HIDDEN_PATH_SEP
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_verified_user
from tests.test_unit_nav_render import COLLAPSE_BREAKPOINT_PX

pytestmark = pytest.mark.e2e

NARROW = 360
SQUEEZED = COLLAPSE_BREAKPOINT_PX + 1
WIDE = 1280
ALL_WIDTHS = (NARROW, SQUEEZED, WIDE)


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py — it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_crumb_course(username):
    """course → part → chapter → section → unit, ~60-char titles at every level.

    A new helper rather than an extension of test_e2e_unit_nav._seed_nav_course:
    that one builds a single part with unit children, so it can never yield three
    ancestors. CourseFactory's default title is a factory.Sequence, hence the
    explicit title=.

    Long titles are not decoration — both falsifying mutations below are only
    detectable when the content actually exceeds the column.
    """
    student = _make_student(username)
    long_ = "Sequences Series And Their Convergence Criteria In Depth"  # 56 chars
    course = CourseFactory(title=f"Advanced {long_}", owner=student)
    EnrollmentFactory(student=student, course=course)
    parent = None
    for kind in ("part", "chapter", "section"):
        parent = ContentNodeFactory(
            course=course,
            kind=kind,
            parent=parent,
            unit_type=None,
            title=f"{kind.title()} {long_}",
        )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=parent, title="Unit One"
    )
    return course, unit


def _open(browser, live_server, username, width):
    course, unit = _seed_crumb_course(username)
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector("nav.unit-crumbs")
    return ctx, page


CONTENT_HEIGHT_JS = """() => {
  const list = document.querySelector('.unit-crumbs__list');
  const cs = getComputedStyle(list);
  return list.clientHeight
       - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
}"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", ALL_WIDTHS)
def test_strip_never_overflows_and_stays_one_line(browser, live_server, width):
    """THE guard on the whole design.

    Falsifying mutation: change the three modifier floors (--course, --mid, --leaf)
    to `min-width: auto`. That restores each <li>'s content-based minimum — the full
    nowrap width of sep + label — the row refuses to shrink, and this goes red at 360
    and at BREAKPOINT+1.

    Two mutations that do NOT work, recorded so nobody mistakes a wrong mutation for
    a vacuous test: deleting `min-width: 0` from the base .unit-crumbs__item rule
    (every emitted <li> carries a modifier whose floor already overrides it), and
    deleting a `min-width: 0` from .unit-crumbs__label (overflow:hidden already zeroes
    its automatic minimum, and the label carries no min-width at all).
    """
    ctx, page = _open(browser, live_server, f"crumb_fit_{width}", width)
    try:
        overflow = page.evaluate(
            """() => {
              const l = document.querySelector('.unit-crumbs__list');
              return l.scrollWidth - l.clientWidth;
            }"""
        )
        assert overflow <= 0, f"crumb strip overflows its own box by {overflow}px"

        # Page-level tripwire. Deliberately EXEMPT from the falsification requirement:
        # the list's overflow:hidden clips any crumb overflow before it can reach the
        # document, so no single crumb-CSS mutation can turn this red. Kept as a cheap
        # standing guard on invariant 2 against future layout changes elsewhere.
        page_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
        assert page_overflow <= 0, f"page scrolls horizontally by {page_overflow}px"

        # One line. Reference the COURSE crumb specifically: it is the only crumb that
        # renders at every width (--mid is display:none at 360, --ellipsis at 1280), so
        # "any item" would compare against offsetHeight == 0 and could never pass. The
        # list's block padding is subtracted because the focus-ring fix adds it in both
        # axes and would otherwise eat the tolerance.
        content_h = page.evaluate(CONTENT_HEIGHT_JS)
        item_h = page.locator(".unit-crumbs__item--course").evaluate(
            "el => el.offsetHeight"
        )
        assert content_h <= 1.5 * item_h, f"strip wrapped: {content_h} vs item {item_h}"
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [NARROW, SQUEEZED])
def test_labels_stay_inside_their_crumbs_and_never_overlap(browser, live_server, width):
    """Catches a floor declared in the wrong place.

    Overlap is asserted on the LABELS, not the <li> boxes: sibling flex items in a
    single-line row never overlap without negative margins, so an <li>-level check
    could not go red under any mutation. It is the labels that spill.

    Falsifying mutation: move the three floors off the <li>s onto
    .unit-crumbs__label and put `min-width: 0` back on the items.
    """
    ctx, page = _open(browser, live_server, f"crumb_fit2_{width}", width)
    try:
        boxes = page.evaluate(
            """() => [...document.querySelectorAll('.unit-crumbs__item')]
                 .filter(li => li.getClientRects().length)
                 .map(li => {
                   const label = li.querySelector('.unit-crumbs__label');
                   const r = label.getBoundingClientRect();
                   return {cls: li.className,
                           fits: label.clientWidth <= li.clientWidth,
                           left: r.left, right: r.right,
                           w: label.clientWidth};
                 })"""
        )
        for b in boxes:
            assert b["fits"], f"label overflows its own crumb: {b['cls']}"
        for a, b in zip(boxes, boxes[1:]):
            assert a["right"] <= b["left"] + 0.5, f"labels overlap: {a['cls']} / {b['cls']}"

        # The pinned ends must still have *something* to show. This is what makes
        # Task 6's floor-retune criterion 2 real: without it, a retune that starves
        # the leaf to zero width at 360px passes every other assertion here —
        # `fits` and non-overlap are both trivially true for a zero-width label.
        for b in boxes:
            if "--course" in b["cls"] or "--leaf" in b["cls"]:
                assert b["w"] > 0, f"pinned crumb squeezed to zero width: {b['cls']}"

        if width == SQUEEZED:
            mids = [b for b in boxes if "--mid" in b["cls"]]
            assert mids, "mids must be visible just above the breakpoint"
            assert all(b["w"] > 0 for b in mids)
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_narrow_collapses_mids_behind_the_ellipsis(browser, live_server):
    """Falsifying mutation: delete the `--mid { display: none }` rule from the
    collapse query."""
    ctx, page = _open(browser, live_server, "crumb_narrow", NARROW)
    try:
        assert page.locator(".unit-crumbs__item--mid").count() > 0  # present in DOM
        assert not page.locator(".unit-crumbs__item--mid").first.is_visible()
        assert page.locator(".unit-crumbs__item--ellipsis").is_visible()

        # An orphaned separator is what this catches — a hidden crumb must take its
        # separator with it. Structural in the markup, asserted anyway.
        visible_items = page.evaluate(
            "() => [...document.querySelectorAll('.unit-crumbs__item')]"
            ".filter(e => e.getClientRects().length).length"
        )
        visible_seps = page.evaluate(
            "() => [...document.querySelectorAll('.unit-crumbs__sep')]"
            ".filter(e => e.getClientRects().length).length"
        )
        assert visible_seps == visible_items - 1
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_ellipsis_tooltip_names_exactly_the_hidden_crumbs(browser, live_server):
    """The guard on the invariant coupling hidden_path to the collapse query.

    Reads li.unit-crumbs__item--mid only — separators and the leaf must not be swept
    in — and joins with the imported HIDDEN_PATH_SEP rather than a ", " literal.

    Falsifying mutation: join hidden_path over `ancestors` instead of `ancestors[:-1]`.
    """
    ctx, page = _open(browser, live_server, "crumb_tooltip", NARROW)
    try:
        mids = page.eval_on_selector_all(
            "li.unit-crumbs__item--mid", "els => els.map(e => e.getAttribute('title'))"
        )
        ellipsis_title = page.locator(".unit-crumbs__item--ellipsis").get_attribute(
            "title"
        )
        assert mids
        assert HIDDEN_PATH_SEP.join(mids) == ellipsis_title
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_wide_shows_every_crumb_and_no_ellipsis(browser, live_server):
    """Falsifying mutation: delete `display: none` from the `--ellipsis` modifier —
    the "…" then renders at 1280 alongside the mids it is meant to replace.

    NOT "drop the `screen and`": that yields `@media (max-width: 832px)`, which does
    not match a 1280px viewport under any media type, so every assertion here would
    stay green. (That mutation is the right one for the print test below, which is
    what makes it look plausible here.)
    """
    ctx, page = _open(browser, live_server, "crumb_wide", WIDE)
    try:
        assert page.locator(".unit-crumbs__item--ellipsis").count() == 1
        assert not page.locator(".unit-crumbs__item--ellipsis").is_visible()
        for sel in (".unit-crumbs__item--mid", ".unit-crumbs__item--leaf"):
            for i in range(page.locator(sel).count()):
                w = page.locator(sel).nth(i).evaluate(
                    "el => el.querySelector('.unit-crumbs__label').clientWidth"
                )
                assert w > 0, f"{sel} label has zero width at {WIDE}px"
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_print_shows_the_whole_path_wrapped(browser, live_server):
    """A screen-only hiding rule once silently destroyed printed content in this
    stylesheet (see the .el--tabs print block). Not shipping that risk untested.

    Falsifying mutation: remove `screen and` from the collapse query — the mids then
    vanish from the printout and the first assertion goes red.
    """
    ctx, page = _open(browser, live_server, "crumb_print", NARROW)
    try:
        page.emulate_media(media="print")
        assert page.locator(".unit-crumbs__item--mid").first.is_visible()
        assert not page.locator(".unit-crumbs__item--ellipsis").is_visible()

        overflow = page.evaluate(
            """() => {
              const l = document.querySelector('.unit-crumbs__list');
              return l.scrollWidth - l.clientWidth;
            }"""
        )
        assert overflow <= 0

        # Wrapped, not clipped: the whole point of the print block.
        content_h = page.evaluate(CONTENT_HEIGHT_JS)
        item_h = page.locator(".unit-crumbs__item--course").evaluate(
            "el => el.offsetHeight"
        )
        assert content_h > 1.5 * item_h, "print output did not wrap"
    finally:
        ctx.close()
```

- [ ] **Step 2: Run them, focused and in the foreground**

```bash
uv run pytest tests/test_e2e_unit_crumbs.py -q -m e2e
```

Expected: all pass.

**If a floor needs retuning** — the spec calls the `ch`/`em` values starting points to verify by measurement — the acceptance criterion is not "looks right". It is:

1. The summed floors plus gaps stay **below the measured 360px content column** (~328px), so nothing is ever clipped at the minimum supported width; and
2. at 360px, both `--course` and `--leaf` labels have `clientWidth > 0`; and
3. at `COLLAPSE_BREAKPOINT_PX + 1`, every `--mid` label has `clientWidth > 0`.

Each maps to a specific assertion — worth knowing so a failure is located rather than hunted. **Criterion 1** → `test_strip_never_overflows_and_stays_one_line`'s `scrollWidth <= clientWidth`; when the floors over-run the column, each `<li>` still sits at its floor with its label fitting inside it, so `fits` stays *green* and only the overflow check goes red. **Criteria 2 and 3** → `test_labels_stay_inside_their_crumbs_and_never_overlap`, via the pinned-crumb `w > 0` loop and the `SQUEEZED` branch respectively. So the check is: **after any retune, re-run the whole of `tests/test_e2e_unit_crumbs.py` plus `uv run pytest -q`, and re-confirm the primary falsifying mutation still goes red.** That last part matters — the floors *are* the subject of that mutation, so a retune in the wrong direction can quietly turn the primary guard into a test that is always green (floors so loose nothing shrinks) or always red (floors so tight the row cannot fit), and neither shows up as a failure at the time.

- [ ] **Step 2b: Sweep the existing unit-page e2e modules — now, not in Task 8**

The browser harness exists as of this task, so run the modules most exposed to a new first child and a new focusable link **here**, while a regression is still attributable to one commit rather than to six commits and a design pass:

```bash
uv run pytest -q -m e2e -n 2 \
  tests/test_e2e_unit_nav.py \
  tests/test_e2e_unit_head_layout.py \
  tests/test_e2e_scroll_affordance.py \
  tests/test_e2e_practice_state.py \
  tests/test_e2e_notes.py
```

Expected: green. Task 8 still runs the whole browser suite at the end; this is the early, cheap half of that sweep. Foreground only.

**If one goes red**, triage it exactly as Task 8 Step 2 does: a hard-coded y-coordinate or element index that the new first child shifted, or a tab-order assertion that now meets the crumb link first. Fix the **test** if it was over-specified about geometry it never meant to pin; fix the **crumb** if the breadcrumb genuinely broke something. Then re-run the repaired module *and* `uv run pytest -q`, and **commit the repair here**, in its own commit:

```bash
git add -- <the module(s) you repaired>
git commit -m "test(e2e): adjust for the new breadcrumb first child"
```

Committing it here rather than leaving it for Task 8 matters: Task 8's Step 1 would then pass, its Step 3 says "if nothing needed repair, skip the commit entirely", and the repair would never be committed at all — leaving a dirty tree the Definition of Done forbids.

- [ ] **Step 3: Falsify**

Apply each mutation named in the docstrings above, confirm RED, revert, confirm GREEN. The page-level tripwire in the first test is the one documented exemption.

- [ ] **Step 4: Commit**

```bash
uv run ruff format . && uv run ruff check .
git add tests/test_e2e_unit_crumbs.py courses/static/courses/css/courses.css
git commit -m "test(e2e): guard the breadcrumb one-line collapse at three viewports"
```

The stylesheet is staged too because Step 2 explicitly authorises retuning the floor values. If you did retune them, commit that as its own change first — `fix(ui): tune breadcrumb min-width floors against measured widths` — so it does not get swept into Task 7's `style(ui): design pass` commit under a misleading message.

---

### Task 7: Frontend-design pass and screenshot QA

**Files:**
- Modify: `courses/static/courses/css/courses.css` (visual treatment only)

**Interfaces:** consumes everything above. Produces the shipped look.

**This task is a required deliverable, explicitly requested by the user — not optional polish.** A previous pipeline run on this repo shipped unpolished UI precisely by treating a design pass as skippable.

- [ ] **Step 1: Run the frontend-design skill**

Invoke the `frontend-design` skill against the breadcrumb strip. Give it the constraint list below verbatim.

**The design pass may freely change** colour, size, weight, spacing, and the breakpoint value.

**It may not break the seven invariants in §4 of the spec:**
1. One line at every screen width ≥ 360px (print deliberately wraps).
2. Never causes page-level horizontal scroll.
3. No orphaned separators (for non-blank titles).
4. At 360px every label is contained in its `<li>` and no two labels overlap.
5. The crumbs the collapse query hides are exactly the ones `hidden_path` names.
6. The `›` glyph stays pinned, and stays authored only in `_unit_crumbs.html`.
7. The breakpoint stays strictly within (640px, 1280px) — retuning means updating `COLLAPSE_BREAKPOINT_PX` **and** the CSS together.

Also unavailable to the pass: adding JavaScript; making `title` conditional (CSS cannot express "is this clipped"); removing any `title`; changing `align-items` to `baseline` without measuring sep/label alignment at both viewports; and **zeroing or "tidying" `.unit-crumbs__list`'s `padding: 5px` / `margin: -5px`** — "spacing is free" does not extend to those two, which are the focus-ring allowance and its compensation. The `ring` measurement catches a removed padding; nothing catches a removed negative margin, which would silently inset the strip 5px from the `<h1>` in both axes.

- [ ] **Step 2: Re-run the full gate**

```bash
uv run ruff format --check . && uv run ruff check .
uv run pytest -q
uv run pytest tests/test_e2e_unit_crumbs.py -q -m e2e
```

Expected: all green. If the pass retuned the breakpoint, `COLLAPSE_BREAKPOINT_PX` must have moved with it.

- [ ] **Step 3: Screenshot QA, focus check and accessible-name measurement — one script**

Steps 3–5 all need a live browser on the same seeded page, so drive them from one throwaway Playwright test rather than three hand-waves. Write it to `tests/test_e2e_crumbs_qa.py`, run it, then **delete it** — it is a capture harness, not a guard.

```python
"""THROWAWAY design-QA harness — delete after Task 7. Captures the six screenshots,
measures focus-ring containment, and reads the crumb accessible name."""

import json
import os
import pathlib

import pytest

from tests.test_e2e_unit_crumbs import _login
from tests.test_e2e_unit_crumbs import _seed_crumb_course
from tests.test_unit_nav_render import COLLAPSE_BREAKPOINT_PX

pytestmark = pytest.mark.e2e
OUT = pathlib.Path("crumbs-qa")


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_capture_design_qa(browser, live_server):
    OUT.mkdir(exist_ok=True)
    course, unit = _seed_crumb_course("crumb_qa_shots")
    findings = {}

    for width in (360, COLLAPSE_BREAKPOINT_PX + 1, 1280):
        for theme in ("light", "dark"):
            ctx = browser.new_context(viewport={"width": width, "height": 900})
            page = ctx.new_page()
            _login(page, live_server, "crumb_qa_shots")
            page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
            page.wait_for_selector("nav.unit-crumbs")
            page.evaluate(
                "t => document.documentElement.setAttribute('data-theme', t)", theme
            )

            # Region shot, not an element shot: the self-critique below asks whether
            # the strip competes with the <h1> and whether the muted colour holds
            # contrast — both are judgements about the crumb IN CONTEXT, and a
            # locator screenshot of the nav alone is a ~330x20px sliver that shows
            # neither the heading nor the page background.
            page.locator("article.lesson, article.quiz").first.screenshot(
                path=str(OUT / f"crumbs-{width}-{theme}.png")
            )

            if width == 360 and theme == "light":
                # Focus ring containment, exactly as the spec pins it: the link's rect
                # expanded by the 4px ring must lie inside the list's rect, compared
                # NON-STRICTLY with the 1px of padding slack. A strict comparison
                # flaps on sub-pixel item heights; an eyeball cannot verify the 1px.
                page.keyboard.press("Tab")
                for _ in range(25):
                    if page.evaluate(
                        "() => document.activeElement"
                        ".classList.contains('unit-crumbs__label')"
                    ):
                        break
                    page.keyboard.press("Tab")
                else:
                    pytest.fail("never reached the crumb link by tabbing")

                findings["ring"] = page.evaluate(
                    """() => {
                      // Derive both from computed style rather than hardcoding 4/1:
                      // the design pass may retune the outline or the list padding,
                      // and stale constants would make this silently false-pass.
                      const el = document.activeElement;
                      const list = document.querySelector('.unit-crumbs__list');
                      const ecs = getComputedStyle(el), lcs = getComputedStyle(list);
                      const RING = parseFloat(ecs.outlineWidth)
                                 + parseFloat(ecs.outlineOffset);
                      // A zero RING makes every comparison below degenerate to
                      // "edge >= edge - padding", which is true even with the padding
                      // removed — the check would report all-clear on a genuinely
                      // clipped ring. Report it so Step 4 can reject the reading.
                      const SLACK = parseFloat(lcs.paddingLeft) - RING;
                      const a = el.getBoundingClientRect();
                      const l = list.getBoundingClientRect();
                      return {
                        ring: RING, slack: SLACK,
                        left:   (a.left   - RING) >= (l.left   - SLACK),
                        right:  (a.right  + RING) <= (l.right  + SLACK),
                        top:    (a.top    - RING) >= (l.top    - SLACK),
                        bottom: (a.bottom + RING) <= (l.bottom + SLACK),
                      };
                    }"""
                )
                # NO mouse-click ring measurement here, deliberately. An earlier draft
                # clicked the link and read outlineStyle; that was wrong twice over —
                # the click navigates to the outline page, so the follow-up evaluate
                # reads a detached document and throws, losing every screenshot; and
                # a mousedown on an ALREADY keyboard-focused element does not re-fire
                # focus in Chromium, so the retained :focus-visible state would report
                # a ring even on a correct implementation. More fundamentally there is
                # nothing here to test: the ring comes from the GLOBAL
                # `:focus-visible` rule in core/static/core/css/reset.css, not from a
                # crumb-specific rule, so there is no bare-`:focus` mistake this
                # change could make. What this harness must verify is our own padding
                # allowance — which is exactly what findings["ring"] above measures.

                # Accessible name of a crumb <li>. The sync Python API has no
                # accessible_name getter and page.accessibility.snapshot() is
                # deprecated; axe is NOT a dependency of this repo, so the axe half of
                # the spec's suggestion is unavailable. aria_snapshot() is the cheap
                # read, but whether it emits a name for a listitem named only by title
                # is EXACTLY the uncertainty being measured — a snapshot with no name
                # is indistinguishable from "no name exists". So take a CDP reading
                # too, which reports the computed name and its source directly.
                findings["aria"] = page.locator(
                    "li.unit-crumbs__item--leaf"
                ).aria_snapshot()
                cdp = ctx.new_cdp_session(page)
                cdp.send("Accessibility.enable")
                doc = cdp.send("DOM.getDocument")
                node = cdp.send(
                    "DOM.querySelector",
                    {
                        "nodeId": doc["root"]["nodeId"],
                        "selector": "li.unit-crumbs__item--leaf",
                    },
                )
                findings["ax"] = cdp.send(
                    "Accessibility.getPartialAXTree",
                    {"nodeId": node["nodeId"], "fetchRelatives": False},
                )["nodes"]
            ctx.close()

    (OUT / "findings.json").write_text(json.dumps(findings, indent=2))
```

Run it in the **foreground**:

```bash
uv run pytest tests/test_e2e_crumbs_qa.py -q -m e2e
```

- [ ] **Step 4: Read the output and self-critique**

Open all six PNGs in `crumbs-qa/` and judge them per `verify-ui-with-screenshots`: is the strip quiet enough not to compete with the `<h1>`? Is the separator optically centred between its neighbours? Is the `…` legible? Does the muted colour hold contrast in dark mode?

Then check `crumbs-qa/findings.json`:

- **`ring`** — read the numbers **before** the booleans.
  - **`ring` must be non-zero** (expect 4: a 2px outline at a 2px offset). A `ring` of 0 means the focused link computes no outline at all — for instance if the design pass swapped it for a `box-shadow`, which `overflow: hidden` *does* clip. With `ring == 0` every comparison degenerates to `edge >= edge - padding` and all four booleans come out `true` **even with the padding removed**, so a zero here means the measurement did not happen and the booleans must not be believed. Fix the CSS and re-measure.
  - **`slack`** should be ~1px (the list's `padding` minus the ring). Zero or negative means the padding no longer covers the ring.
  - Only then: `left`/`right`/`top`/`bottom` must all be `true`. A `false` on any side means the list's `padding: 5px` is missing or was reduced in that axis and the ring is being clipped.
- **`aria` / `ax`** — informational; read them in Step 5.

There is deliberately **no mouse-click measurement**. This change *does* author `a.unit-crumbs__label:focus-visible`, but that rule is a verbatim duplicate of the global `:focus-visible` rule already in `core/static/core/css/reset.css`, so the ring's click behaviour is the platform's and the reset's, not this diff's — there is nothing a click test could catch here that the keyboard test does not. (See the comment in the harness for why the earlier attempt at one was doubly broken.)

**If `ring` fails on any side, fix `courses/static/courses/css/courses.css` — do not relax the check — then re-run Step 3's harness and re-read `findings.json`.** This loop is mandatory: Step 2's gate ran *before* these measurements, so a CSS edit made here has been validated by nothing at the point Step 6 commits it. Keep looping until all four sides are `true`.

- [ ] **Step 5: Record the accessible-name finding**

Create `docs/superpowers/plans/crumbs-qa-findings.md` (it does not exist yet) with exactly these two sections — the PR body quotes both, so the shape matters:

```markdown
# Breadcrumb QA findings

## Accessible-name measurement

Measured on <engine/version> at 360px, on `li.unit-crumbs__item--leaf`.

- `aria_snapshot()`: <paste>
- CDP computed name: <the `name.value` from the `ax` node, or "none emitted">
- Reading: <one line — either "title contributes an accessible name duplicating the
  label text" or "no accessible name is computed from title on a listitem">

No change was made either way: the spec rules the remedy out of bounds because that
`title` is load-bearing for render test 12, for the 360px e2e coupling assertion, and
for the documented hover affordance.

## Follow-up: no breadcrumb on quiz_results.html

A student who has submitted a quiz is redirected to `quiz_results.html`, which renders
outside `_unit_shell.html` with no sidebar tree, no drawer and no `unit_nav` — so it is
the page with the *least* orientation and it deliberately gets no crumb in this change.
Covering it needs a `build_unit_nav` call on that view plus its own alignment work.
```

Interpreting the two readings: if the CDP node reports a `name` whose value equals the crumb's title text, `title` **does** contribute an accessible name and the duplication the spec predicted is real. If no `name` is emitted, it does not. `aria_snapshot()` alone cannot settle this — a snapshot without a name is ambiguous between the two — which is why the CDP reading is taken.

The spec predicts `title` on a `listitem` may produce an accessible name duplicating the label text. **Change nothing either way.** The remedy was considered and ruled explicitly out of bounds: that `title` is load-bearing for two tests and for the documented hover affordance.

- [ ] **Step 6: Delete the harness and commit**

```bash
rm -rf tests/test_e2e_crumbs_qa.py crumbs-qa/
uv run ruff format . && uv run ruff check .
uv run pytest -q
uv run pytest tests/test_e2e_unit_crumbs.py -q -m e2e
git add courses/static/courses/css/courses.css tests/test_unit_nav_render.py docs/superpowers/plans/crumbs-qa-findings.md
git commit -m "style(ui): design pass on the student breadcrumbs"
```

The e2e re-run is not redundant with Step 2: `pytest -q` inherits `addopts = "-q -m 'not e2e'"` and therefore **excludes** the browser suite, so without this line any CSS the design pass or the Step-4 loop changed would be committed without the tests that actually guard the layout ever seeing it.

`tests/test_unit_nav_render.py` is staged because the pass is allowed to retune the breakpoint, and retuning means moving `COLLAPSE_BREAKPOINT_PX` in lockstep with the CSS. Committing one without the other leaves a tree that is green locally and red in CI on `test_collapse_breakpoint_is_in_bounds_and_matches_the_stylesheet`. If the pass touched any other file, stage that too.

---

### Task 8: Regression sweep over the existing browser suite, and the PR body

**Files:** none for the sweep — verification only; plus `docs/superpowers/plans/crumbs-qa-findings.md` for the PR-body assembly.

**Why:** this change inserts a `<nav>` and an `<ol>` as the **first child** of both `article.lesson` and `article.quiz`, and a new **focusable `<a>` ahead of all page content**. That shifts vertical geometry and tab order on every unit page. The plan gates twice on the non-e2e suite for exactly this collateral-breakage reason; the browser suite is the one most likely to be disturbed and `addopts = "-m 'not e2e'"` means none of the earlier gates ever ran it.

> **Note — the focused half of this sweep runs earlier.** Task 6 Step 2b runs the five
> unit-page e2e modules as soon as the browser harness exists, so a regression there is
> attributable to a single commit rather than to six commits and a design pass. What
> remains here is the whole-suite confirmation.

- [ ] **Step 1: Run the whole browser suite, chunked and parallel**

There are 69 `tests/test_e2e_*.py` modules. Serially they will not finish inside a single foreground tool invocation, and a killed run leaves exactly the orphaned browsers this plan warns about. Use xdist (already a dev dependency; CI runs `-m e2e -n 2`) and split into chunks so each invocation returns:

```bash
uv run pytest -q -m e2e -n 2 tests/test_e2e_[a-g]*.py
uv run pytest -q -m e2e -n 2 tests/test_e2e_[h-q]*.py
uv run pytest -q -m e2e -n 2 tests/test_e2e_[r-z]*.py
```

Character classes, not `a*.py b*.py c*.py …`: an unmatched literal glob is passed through verbatim and pytest aborts the whole invocation with `ERROR: file or directory not found`, exit 4, having collected **nothing**. There is no `tests/test_e2e_d*.py` in this repo — exactly how an earlier draft of this step would have silently skipped 25 modules. The three classes cover all 69 files.

`-n 2` matches CI (`.github/workflows/ci.yml` runs the browser suite at `-n 2`). Do **not** use `-n auto`: one browser process and one test database per core invites resource-contention flakes, which Step 2 would then misdiagnose as a breadcrumb regression.

Each chunk should return in a few minutes. Two outcomes that are **not** test failures and must not be recorded as one: an invocation timeout (a harness limit — split the chunk further) and `ERROR: file or directory not found` (a command bug — fix the glob and re-run). And a failure that does not reproduce at `-n 0` is a contention flake, not a regression.

- [ ] **Step 2: Triage any failure**

A failure is almost certainly one of two things: a hard-coded y-coordinate or element index that the new first child shifted, or a tab-order assertion that now meets the crumb link first.

- Fix the **test** if it was over-specified about geometry it never meant to pin.
- Fix the **crumb** if the breadcrumb genuinely broke something.

- [ ] **Step 3: Re-gate, then commit**

If you changed anything in Step 2 — **including** a template or CSS repair — re-run **both** suites before committing. A crumb repair can satisfy an e2e assertion while reddening one of the 21 render tests that own the DOM contract, and this is the last task: nothing after it would catch that.

```bash
uv run ruff format . && uv run ruff check .
uv run pytest -q
uv run pytest -q -m e2e -n 2 tests/test_e2e_unit_crumbs.py tests/test_e2e_unit_nav.py <every module you touched or that failed in Step 1>
git add -- <only the files you actually repaired>
```

Then commit with the message that matches what you repaired:

```bash
# test-only repair:
git commit -m "test(e2e): adjust for the new breadcrumb first child"
# crumb repair (production code):
git commit -m "fix(ui): <what the breadcrumb broke and how>"
```

If nothing needed repair, skip the commit entirely.

- [ ] **Step 4: Assemble the PR body**

Three things must reach the PR description, and no earlier step owns it:

1. The accessible-name measurement — quote the two sections of `docs/superpowers/plans/crumbs-qa-findings.md` verbatim.
2. The `quiz_results.html` follow-up, from the same file.
3. The result of this sweep — either "existing e2e suite green, no changes" or a one-line description of each repair and which category it fell into.

Append (3) to `crumbs-qa-findings.md` under a `## Existing e2e suite` heading so the whole PR body has one source. **This step always runs**, whether or not Step 3 committed — on the "nothing needed repair" path it is the task's only commit, and the Definition of Done's clean-tree requirement depends on it:

```bash
uv run ruff format --check . && uv run ruff check .
git add docs/superpowers/plans/crumbs-qa-findings.md
git commit -m "docs: record the existing-e2e sweep result for the PR body"
```

---

## Definition of done

- [ ] The **21 new test functions** in Tasks 1–4 (which implement spec tests 1–18 — several spec items map to more than one function) and the 6 e2e tests in Task 6 are implemented, and **each has been falsified** — mutation applied, RED confirmed, reverted, GREEN confirmed. Two documented exceptions: the e2e page-level scroll tripwire (structurally unfalsifiable, exemption argued in the spec), and spec test 19 (`test_build_unit_nav_adds_no_queries`), which is pre-existing, must stay unmodified, and is verified by running it rather than by mutation.
- [ ] `uv run pytest -q` green; `uv run pytest -q -m e2e` green — the **whole** browser suite, not just the new file (Task 8), since `addopts` excludes e2e from every other gate.
- [ ] `uv run ruff format --check .` and `uv run ruff check .` clean.
- [ ] `test_build_unit_nav_adds_no_queries` still passes, unmodified.
- [ ] `tests/test_i18n_po_health.py` passes; zero `#, fuzzy`, zero `#~`.
- [ ] Six screenshots reviewed; `findings.json` shows the focus ring contained on all four sides at 360px, with a non-zero `ring` value proving the measurement actually ran.
- [ ] `docs/superpowers/plans/crumbs-qa-findings.md` exists and holds the accessible-name measurement plus the `quiz_results.html` follow-up; the PR body quotes both from it.
- [ ] The throwaway QA harness (`tests/test_e2e_crumbs_qa.py`) and `crumbs-qa/` are deleted, and `git status` reports a clean tree. `.env` is gitignored and must **not** appear — if it does, it was staged by mistake.
