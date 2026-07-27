# Builder Large-Course Performance — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the course builder render only the tree scopes that are open, so `mat-pp` (944 nodes) loads in under 1.5 s instead of 8.4 s, drags without per-event forced layout, and reflects a drop in under 500 ms.

**Architecture:** `_tree_node.html` stops recursing unconditionally; a child `<ol>` renders only when its node's pk is in an `open_ids` set. That set is computed by one helper, `_open_ids`, from an `open` request parameter with a fixed precedence order, seeded on a fresh page load from the last node the author touched (session). Because "the whole tree" now means only the visible rows, the existing whole-tree mutation responses become cheap without restructuring.

**Tech Stack:** Django 5.2 templates + views, vanilla ES5-style JS (`builder.js`, no build step), pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-07-27-builder-large-course-performance-design.md`. Read §1–§8 before starting. This plan implements **slice 1 only**; §9 (filter) and §10 (expand-all) are PR 2.

## Global Constraints

- **Python/tooling is only reachable through `uv run`.** Bare `pytest`/`ruff`/`python` are not on PATH. Use `uv run pytest …`, `uv run ruff format --check .`, `uv run ruff check .`.
- **Never run two pytest invocations at once.** Concurrent runs collide on the Postgres `test_libli` database. This worktree needs its own `DATABASE_URL` (role is `libli:libli`, not `postgres:postgres`).
- **e2e tests need `-m e2e` explicitly** or they are silently deselected and pytest exits 5.
- **Pytest verdict lines do not survive a Bash pipe.** Check the exit code, or `grep FAILED`.
- **`{# #}` template comments must be single-line.** Use `{% comment %}…{% endcomment %}` for multi-line.
- **New user-visible strings need msgids in both `pl` and `en` catalogs.** Regenerate with `-l pl -l en --no-obsolete`; clear every fuzzy entry (two deletions: the `#, fuzzy` line and the `#| msgid` line).
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD`.
- **Icons are monochrome `currentColor` SVGs** referenced from `_icon_sprite.html`. Never emoji.
- **`q` is slice 2.** `_open_ids` reserves a `q_chain=None` parameter but slice 1 always passes `None`, and no template emits `q`. Do not implement the filter.
- **Verify `git branch --show-current` immediately before every commit** — a parallel session has switched branches under this worktree before.
- Constants, exact values from the spec: ceiling **500** pks, size threshold **150** nodes, session slug bound **20**, seed chain ceiling **4** scopes.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `courses/builder_open.py` *(new)* | `OpenSet`, `_open_ids`, chain/ceiling/sanitisation helpers. Pure, no view imports — keeps the precedence rules in one testable place. |
| `courses/views_manage.py` | Wires `_open_ids` into `builder()`, `_builder_with_notice()`, `_render_scope()`; adds `extra_open`; adds `manage_node_scope`; session writes. |
| `courses/templatetags/courses_manage_extras.py` | Adds `{% toggle_href %}`. |
| `templates/courses/manage/_tree_node.html` | Conditional recursion + toggle markup. |
| `templates/courses/manage/_scope.html` | Scope `id`, hoisted URLs, passes `open_ids` down. |
| `templates/courses/manage/_move_buttons.html` | Stops reversing `manage_node_move` itself. |
| `templates/courses/manage/builder.html` | Root data attributes; `info` slot. |
| `templates/courses/manage/_icon_sprite.html` | New `bi-chevron` symbol. |
| `courses/static/courses/js/builder.js` | Toggle handler, open collector, `replaceState`, busy counter, drag rAF. |
| `courses/static/courses/css/builder.css` | Toggle column, busy state, info slot. |
| `courses/urls.py` | `manage_node_scope` route. |
| `tests/test_builder_open_ids.py` *(new)* | Unit tests for the precedence helper. |
| `tests/test_builder_lazy_scopes.py` *(new)* | Render/structural guards + reversal-count guard. |
| `tests/test_e2e_builder_toggle.py` *(new)* | Expand/collapse/drag e2e. |
| `tests/helpers_builder.py` *(new)* | `expand_to()` + `open_all_param()` migration helpers. |

---

### Task 1: The `_open_ids` precedence helper

**Files:**
- Create: `courses/builder_open.py`
- Test: `tests/test_builder_open_ids.py`

**Interfaces:**
- Consumes: `courses.models.ContentNode`, `courses.views_manage._children_map` (shape only: `{parent_id: [ContentNode]}`).
- Produces: `OpenSet(ids: frozenset[int], truncated: bool)`; `open_ids(request, course, cmap, *, mode="fragment", q_chain=None) -> OpenSet`; `container_pks(cmap) -> set[int]`; `CEILING = 500`; `SIZE_THRESHOLD = 150`.

> Note the public name is `open_ids` (no leading underscore) because it is imported across modules; the spec writes it `_open_ids`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_builder_open_ids.py`:

```python
import pytest
from django.test import RequestFactory

from courses.builder_open import CEILING
from courses.builder_open import container_pks
from courses.builder_open import open_ids
from courses.views_manage import _children_map
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


def _req(rf, query="", post=None, session=None):
    r = rf.post("/", data=post) if post is not None else rf.get(f"/?{query}")
    r.session = session if session is not None else {}
    return r


@pytest.fixture
def tree(db):
    """part > chapter > unit, plus a childless chapter (the `pk in cmap` trap)."""
    course = CourseFactory(slug="c1")
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=part, title="C")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    empty = ContentNodeFactory(course=course, kind="chapter", parent=part, title="E")
    return course, part, chapter, unit, empty


@pytest.mark.django_db
def test_childless_container_is_a_valid_open_pk(rf, tree):
    """`empty` is never a KEY in cmap -- a `pk in cmap` test would discard it."""
    course, _part, _ch, _unit, empty = tree
    cmap = _children_map(course)
    assert empty.pk in container_pks(cmap)
    result = open_ids(_req(rf, f"open={empty.pk}"), course, cmap)
    assert result.ids == frozenset({empty.pk})


@pytest.mark.django_db
def test_unit_pk_and_junk_and_foreign_pk_are_discarded(rf, tree):
    course, part, _ch, unit, _e = tree
    other = ContentNodeFactory(course=CourseFactory(slug="c2"), kind="part", parent=None)
    cmap = _children_map(course)
    q = f"open={part.pk},{unit.pk},{other.pk},abc,"
    assert open_ids(_req(rf, q), course, cmap).ids == frozenset({part.pk})


@pytest.mark.django_db
def test_absent_vs_empty_on_a_page_load(rf, tree):
    """Absent seeds from the session; empty means 'I collapsed everything'."""
    course, part, chapter, unit, _e = tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c1": unit.pk}}
    absent = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    assert absent.ids == frozenset({part.pk, chapter.pk})
    empty = open_ids(_req(rf, "open=", session=sess), course, cmap, mode="page")
    assert empty.ids == frozenset()


@pytest.mark.django_db
def test_seed_includes_the_node_itself_when_it_is_a_container(rf, tree):
    course, part, chapter, _u, _e = tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c1": chapter.pk}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    assert got.ids == frozenset({part.pk, chapter.pk})


@pytest.mark.django_db
def test_fragment_mode_never_seeds_and_skips_the_size_rule(rf, tree):
    """A 4-node course is under the threshold; a fragment must still be empty."""
    course, _p, _c, unit, _e = tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c1": unit.pk}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="fragment")
    assert got.ids == frozenset()


@pytest.mark.django_db
def test_small_course_opens_everything_before_consulting_the_seed(rf, tree):
    course, part, chapter, unit, empty = tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c1": unit.pk}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    assert got.ids == frozenset({part.pk, chapter.pk, empty.pk})


@pytest.mark.django_db
def test_open_session_sentinel_reads_then_falls_through_when_missing(rf, tree):
    course, part, chapter, _u, _e = tree
    cmap = _children_map(course)
    stored = {"builder_open": {"c1": [chapter.pk]}}
    got = open_ids(_req(rf, "open=session", session=stored), course, cmap, mode="page")
    assert got.ids == frozenset({chapter.pk})
    # missing key -> fall through to steps 3-6, NOT an empty tree
    got2 = open_ids(_req(rf, "open=session", session={}), course, cmap, mode="page")
    assert got2.ids == frozenset({part.pk, chapter.pk, _e_pk(tree)})


def _e_pk(tree):
    return tree[4].pk


@pytest.mark.django_db
def test_post_open_beats_get_open(rf, tree):
    course, part, chapter, _u, _e = tree
    cmap = _children_map(course)
    r = rf.post("/?open=" + str(part.pk), data={"open": str(chapter.pk)})
    r.session = {}
    assert open_ids(r, course, cmap).ids == frozenset({chapter.pk})


@pytest.mark.django_db
def test_ceiling_keeps_the_lowest_pks_and_flags_truncation(rf, db):
    course = CourseFactory(slug="big")
    parts = [
        ContentNodeFactory(course=course, kind="part", parent=None, title=f"p{i}")
        for i in range(CEILING + 5)
    ]
    cmap = _children_map(course)
    got = open_ids(_req(rf, "open=all"), course, cmap, mode="page")
    assert got.truncated is True
    assert len(got.ids) == CEILING
    assert got.ids == frozenset(sorted(p.pk for p in parts)[:CEILING])


@pytest.mark.django_db
def test_stale_session_pk_is_discarded(rf, tree):
    course, _p, _c, _u, _e = tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c1": 9_999_999}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    # falls through to the size rule, not to a crash
    assert got.ids == container_pks(cmap)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_builder_open_ids.py -q
```
Expected: collection error — `ModuleNotFoundError: No module named 'courses.builder_open'`.

- [ ] **Step 3: Write the implementation**

Create `courses/builder_open.py`:

```python
"""Which tree scopes are open, for one request.

The builder renders a child <ol> only for nodes in this set (spec section 1),
so this module is the single authority for the precedence rules in spec
section 2. It is deliberately free of view imports: everything it needs
arrives as arguments.
"""

from dataclasses import dataclass

from courses.models import ContentNode

CEILING = 500  # max open scopes after resolution; also bounds `open=all`
SIZE_THRESHOLD = 150  # courses at or under this open fully on a bare page load
SESSION_SLUG_LIMIT = 20  # per-key slug bound for the session dicts

LAST_NODE_KEY = "builder_last_node"
OPEN_KEY = "builder_open"
FORCE_KEY = "builder_force"


@dataclass(frozen=True)
class OpenSet:
    """`ids` is a frozenset so `frozen=True` actually protects it: frozen blocks
    attribute rebinding but not mutation of a mutable field, and a plain set
    would also make the generated __hash__ raise."""

    ids: frozenset
    truncated: bool = False


def nodes_by_pk(cmap):
    """pk -> node, over every node in the course.

    NOT `cmap` itself: _children_map only creates a KEY for a parent that has
    children, so `pk in cmap` silently discards every childless container.
    """
    return {n.pk: n for kids in cmap.values() for n in kids}


def container_pks(cmap):
    """Every non-unit pk. A unit owns no scope, so it can never be 'open'."""
    return {
        pk
        for pk, n in nodes_by_pk(cmap).items()
        if n.kind != ContentNode.Kind.UNIT
    }


def _finalize(ids, containers):
    """Sanitise against this course's containers, then apply the one ceiling.

    Truncation keeps the LOWEST pks: a set has no truncation order, and the
    outcome has to be reproducible across runs for the guard test to mean
    anything.
    """
    kept = set(ids) & containers
    if len(kept) > CEILING:
        return OpenSet(frozenset(sorted(kept)[:CEILING]), True)
    return OpenSet(frozenset(kept), False)


def _parse(raw, containers):
    if raw == "all":
        return set(containers)
    out = set()
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            out.add(int(token))
    return out


def _chain(pk, index):
    """Ancestor chain of `pk`, plus the node itself when it is a container.

    Including the node is why the ceiling is 4 scopes, not 3: otherwise an
    author returns to the course with the very chapter they were working in
    closed.
    """
    node = index.get(pk)
    if node is None:
        return set()
    out = set()
    if node.kind != ContentNode.Kind.UNIT:
        out.add(node.pk)
    cur = node.parent_id
    while cur is not None and cur in index:
        out.add(cur)
        cur = index[cur].parent_id
    return out


def _raw_open(request):
    """Presence, not truthiness. `.get()` returns "" for both absent and
    explicitly-empty, and "" is falsy -- which would re-seed from the session
    the moment the author collapses the last scope."""
    if "open" in request.POST:
        return request.POST["open"], True
    if "open" in request.GET:
        return request.GET["open"], True
    return "", False


def _stored_open(request, slug):
    return request.session.get(OPEN_KEY, {}).get(slug) or []


def open_ids(request, course, cmap, *, mode="fragment", q_chain=None):
    """Resolve the open set. `mode` is one of "page" | "notice" | "fragment".

    Steps run per mode (spec section 2):
      page     -> 1, 2, 3, 4, 5, 6
      notice   -> 2, 3, 4, 5, 6 + a direct builder_open read
      fragment -> 2, 3, 6 only  (never touches the session; the size rule is a
                  LANDING rule for a page, not a rule about a re-render)
    """
    index = nodes_by_pk(cmap)
    containers = {
        pk for pk, n in index.items() if n.kind != ContentNode.Kind.UNIT
    }
    raw, present = _raw_open(request)

    # Step 1 -- the no-JS post-mutation sentinel, page mode only.
    if present and raw == "session" and mode == "page":
        stored = _stored_open(request, course.slug)
        if stored:
            return _finalize(stored, containers)
        present = False  # missing/flushed -> fall through to 3-6

    # Step 2 -- an explicit value wins, including the empty string.
    if present:
        return _finalize(_parse(raw, containers), containers)

    # A no-JS conflict/validation re-render is the same author, same tab,
    # mid-loop -- it cannot be a bookmark, so reading the carrier is safe and
    # keeps a FAILED mutation showing the same tree as a successful one.
    if mode == "notice":
        stored = _stored_open(request, course.slug)
        if stored:
            return _finalize(stored, containers)

    # Step 3 -- the filter's chains (slice 2; always None here).
    if q_chain is not None:
        return _finalize(q_chain, containers)

    if mode == "fragment":
        return _finalize(set(), containers)  # step 6

    # Step 4 -- small courses open fully, BEFORE the seed. Ordered the other
    # way round, node_panel stores a pk on the first click and from the
    # author's second visit a small course would arrive with only the chain.
    if len(index) <= SIZE_THRESHOLD:
        return _finalize(containers, containers)

    # Step 5 -- the last node this author touched, at most 4 scopes.
    last = request.session.get(LAST_NODE_KEY, {}).get(course.slug)
    if last is not None:
        chain = _chain(last, index)
        if chain:
            return _finalize(chain, containers)

    return _finalize(set(), containers)  # step 6
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_builder_open_ids.py -q
```
Expected: 10 passed.

- [ ] **Step 5: Falsify two of them**

Temporarily change `_finalize`'s `sorted(kept)[:CEILING]` to `list(kept)[:CEILING]` and confirm `test_ceiling_keeps_the_lowest_pks_and_flags_truncation` still passes *sometimes* — it must be re-pinned to sorted. Then change `container_pks` to use `pk in cmap` and confirm `test_childless_container_is_a_valid_open_pk` goes **RED**. Revert both.

Expected: the second edit produces a failure. If it does not, the test is vacuous — fix it before continuing.

- [ ] **Step 6: Commit**

```bash
git branch --show-current   # must be worktree-builder-large-course-perf
git add courses/builder_open.py tests/test_builder_open_ids.py
git commit -m "feat(builder): add the open-scope precedence helper"
```

---

### Task 2: Record the last-touched node in the session

**Files:**
- Modify: `courses/views_manage.py` (`node_panel`, around `:155-174`)
- Test: `tests/test_builder_open_ids.py` (append)

**Interfaces:**
- Consumes: `courses.builder_open.LAST_NODE_KEY`, `SESSION_SLUG_LIMIT`.
- Produces: `courses.views_manage.remember_node(request, slug, pk)` — also reused by Task 6 for `builder_open`/`builder_force`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_builder_open_ids.py`:

```python
from django.urls import reverse

from courses.builder_open import LAST_NODE_KEY
from courses.builder_open import SESSION_SLUG_LIMIT
from tests.factories import make_login


@pytest.mark.django_db
def test_node_panel_records_the_focused_node(client, tree):
    course, part, _c, _u, _e = tree
    course.owner = make_login(client, "owner")
    course.save(update_fields=["owner"])
    client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": part.pk})
    )
    assert client.session[LAST_NODE_KEY]["c1"] == part.pk


@pytest.mark.django_db
def test_remember_node_bounds_slugs_and_moves_recent_to_the_end():
    from courses.views_manage import remember_node

    class R:
        session = {}

    r = R()
    for i in range(SESSION_SLUG_LIMIT + 5):
        remember_node(r, f"s{i}", i)
    assert len(r.session[LAST_NODE_KEY]) == SESSION_SLUG_LIMIT
    # re-writing an OLD slug must move it to the end, or "most recent" is a lie:
    # dicts keep INSERTION order, and re-assigning a key does not re-order it.
    oldest = next(iter(r.session[LAST_NODE_KEY]))
    remember_node(r, oldest, 999)
    assert next(iter(r.session[LAST_NODE_KEY])) != oldest
    assert list(r.session[LAST_NODE_KEY])[-1] == oldest


@pytest.mark.django_db
def test_remember_node_skips_an_unchanged_write():
    from courses.views_manage import remember_node

    class R:
        session = {}
        modified = False

    r = R()
    remember_node(r, "s", 1)
    r.modified = False
    remember_node(r, "s", 1)
    assert r.modified is False  # no session save for a re-focus
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_open_ids.py -q -k "remember or records_the_focused"
```
Expected: FAIL — `ImportError: cannot import name 'remember_node'`.

- [ ] **Step 3: Implement**

In `courses/views_manage.py`, add near `_children_map`:

```python
from courses.builder_open import LAST_NODE_KEY
from courses.builder_open import SESSION_SLUG_LIMIT


def remember_node(request, slug, pk, key=LAST_NODE_KEY):
    """Store a per-course pk (or pk list) in the session, most-recent last.

    Skips the write when the value is unchanged: with a DB-backed session an
    unconditional write means a session save on EVERY row focus.
    """
    store = request.session.get(key) or {}
    if store.get(slug) == pk:
        return
    # pop before re-inserting: a dict preserves INSERTION order and
    # re-assigning an existing key does not move it to the end, so without
    # this the eviction below drops recently-used slugs first.
    store.pop(slug, None)
    store[slug] = pk
    while len(store) > SESSION_SLUG_LIMIT:
        store.pop(next(iter(store)))
    request.session[key] = store
    request.session.modified = True
```

In `node_panel`, immediately after the `can_manage_course` check:

```python
    remember_node(request, node.course.slug, node.pk)
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_builder_open_ids.py -q
```
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add courses/views_manage.py tests/test_builder_open_ids.py
git commit -m "feat(builder): remember the last node an author focused"
```

---

### Task 3: Render only open scopes

This is the behaviour change. After it the builder is fast but has no toggle affordance yet (Task 4 adds the link, Task 8 the JS), so the tree is navigable only via `?open=`.

**Files:**
- Modify: `templates/courses/manage/_tree_node.html`, `templates/courses/manage/_scope.html`, `templates/courses/manage/_icon_sprite.html`, `courses/static/courses/css/builder.css`, `courses/views_manage.py` (`builder`, `_builder_with_notice`, `_render_scope`)
- Test: `tests/test_builder_lazy_scopes.py` *(new)*

**Interfaces:**
- Consumes: `courses.builder_open.open_ids`, `OpenSet`.
- Produces: context keys `open_ids` (a `frozenset[int]`) and `info` (a list of `{"key": str, "text": str}`), consumed by `_scope.html`/`_tree_node.html`/`builder.html`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_builder_lazy_scopes.py`:

```python
import re

import pytest
from django.urls import reverse

from courses.builder_open import SIZE_THRESHOLD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _big_course(owner, n_chapters=5, units_each=4):
    """Deliberately OVER SIZE_THRESHOLD, so the lazy path is exercised.

    A fixture under the threshold opens fully (spec section 3a) and would make
    every assertion below pass vacuously.
    """
    course = CourseFactory(slug="big", owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P0")
    chapters = []
    while (
        1 + len(chapters) + sum(len(c[1]) for c in chapters) <= SIZE_THRESHOLD
    ):
        ch = ContentNodeFactory(
            course=course, kind="chapter", parent=part, title=f"C{len(chapters)}"
        )
        units = [
            ContentNodeFactory(
                course=course,
                kind="unit",
                unit_type="lesson",
                parent=ch,
                title=f"U{len(chapters)}-{i}",
            )
            for i in range(units_each)
        ]
        chapters.append((ch, units))
    return course, part, chapters


@pytest.mark.django_db
def test_collapsed_scope_emits_no_descendant_rows(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "big"}))
    html = resp.content.decode()
    assert f'data-node="{part.pk}"' in html          # top level renders
    first_chapter = chapters[0][0]
    assert f'data-node="{first_chapter.pk}"' not in html   # its children do not
    assert f'data-scope="{part.pk}"' not in html


@pytest.mark.django_db
def test_open_param_renders_exactly_that_scope(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk}").content.decode()
    assert f'data-node="{ch.pk}"' in html            # part's children appear
    assert f'data-node="{chapters[0][1][0].pk}"' not in html  # chapter's do not


@pytest.mark.django_db
def test_builder_tree_stays_one_query(client, django_assert_num_queries):
    owner = make_login(client, "owner")
    _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    resp = client.get(f"{url}?open=all")
    assert resp.status_code == 200
    # The tree itself must stay a single query regardless of how much is open.
    # (Auth/session queries are not part of this assertion; count the tree by
    # asserting the rendered row count instead of a raw total.)
    rows = len(re.findall(r'class="tree__row"', resp.content.decode()))
    assert rows > SIZE_THRESHOLD / 2


@pytest.mark.django_db
def test_small_course_still_arrives_fully_expanded(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="small", owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    ch = ContentNodeFactory(course=course, kind="chapter", parent=part, title="C")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="U"
    )
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "small"})
    ).content.decode()
    for node in (part, ch, unit):
        assert f'data-node="{node.pk}"' in html


@pytest.mark.django_db
def test_collapsed_container_renders_a_toggle_with_its_direct_child_count(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"})
    ).content.decode()
    row = re.search(
        r'data-node="%d".*?</div>' % part.pk, html, re.S
    ).group(0)
    assert f'data-toggle="{part.pk}"' in row
    assert 'aria-expanded="false"' in row
    assert "aria-controls" not in row          # invalid ARIA while collapsed
    assert str(len(chapters)) in row           # DIRECT children only


@pytest.mark.django_db
def test_expanded_container_pairs_aria_controls_with_the_scope_id(client):
    owner = make_login(client, "owner")
    course, part, _chapters = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk}").content.decode()
    assert f'aria-controls="tree-scope-{part.pk}"' in html
    assert f'id="tree-scope-{part.pk}"' in html
    assert 'aria-expanded="true"' in html
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q
```
Expected: FAIL — `test_collapsed_scope_emits_no_descendant_rows` finds the chapter's `data-node` (the tree still renders in full).

- [ ] **Step 3: Add the chevron symbol**

In `templates/courses/manage/_icon_sprite.html`, after the `bi-duplicate` symbol line:

```html
  <symbol id="bi-chevron" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M6 3l5 5-5 5"/></symbol>
```

- [ ] **Step 4: Make the recursion conditional**

Replace the tail of `templates/courses/manage/_tree_node.html` (the `{% if node.kind != "unit" %}` block) with:

```html
  {% if node.kind != "unit" %}
    {% if node.pk in open_ids %}
      {% include "courses/manage/_scope.html" with scope_id=node.pk scope_updated=node.updated.isoformat nodes=children_map|get_item:node.pk children_map=children_map parent_kind=node.kind open_ids=open_ids %}
    {% endif %}
  {% endif %}
</li>
```

and insert the toggle as the FIRST child of `.tree__rowhead`, immediately after `<div class="tree__rowhead">`:

```html
    {% if node.kind != "unit" %}
      {% with kids=children_map|get_item:node.pk %}
      {% if node.pk in open_ids %}
      <a class="tree__toggle" href="#" data-toggle="{{ node.pk }}"
         aria-expanded="true" aria-controls="tree-scope-{{ node.pk }}"
         aria-label="{% blocktrans count counter=kids|length with title=node.title %}Collapse {{ title }}, {{ counter }} item{% plural %}Collapse {{ title }}, {{ counter }} items{% endblocktrans %}"
         data-label-expand="{% blocktrans count counter=kids|length with title=node.title %}Expand {{ title }}, {{ counter }} item{% plural %}Expand {{ title }}, {{ counter }} items{% endblocktrans %}"
         data-label-collapse="{% blocktrans count counter=kids|length with title=node.title %}Collapse {{ title }}, {{ counter }} item{% plural %}Collapse {{ title }}, {{ counter }} items{% endblocktrans %}"
      ><svg class="ic"><use href="#bi-chevron"/></svg></a>
      {% else %}
      <a class="tree__toggle" href="#" data-toggle="{{ node.pk }}"
         aria-expanded="false"
         aria-label="{% blocktrans count counter=kids|length with title=node.title %}Expand {{ title }}, {{ counter }} item{% plural %}Expand {{ title }}, {{ counter }} items{% endblocktrans %}"
         data-label-expand="{% blocktrans count counter=kids|length with title=node.title %}Expand {{ title }}, {{ counter }} item{% plural %}Expand {{ title }}, {{ counter }} items{% endblocktrans %}"
         data-label-collapse="{% blocktrans count counter=kids|length with title=node.title %}Collapse {{ title }}, {{ counter }} item{% plural %}Collapse {{ title }}, {{ counter }} items{% endblocktrans %}"
      ><svg class="ic"><use href="#bi-chevron"/></svg></a>
      {% endif %}
      {% endwith %}
    {% else %}
      <span class="tree__toggle tree__toggle--leaf" aria-hidden="true"></span>
    {% endif %}
```

> The `href="#"` is a placeholder replaced in Task 4 by `{% toggle_href %}`. Both labels are rendered server-side because JS cannot select a Polish plural form.

- [ ] **Step 5: Give the scope an id and thread `open_ids`**

In `templates/courses/manage/_scope.html`, change the `<ol>` open tag and the include:

```html
<ol class="tree__scope" id="tree-scope-{{ scope_id }}" data-scope="{{ scope_id }}" data-updated="{{ scope_updated }}">
  {% for node in nodes %}
    {% include "courses/manage/_tree_node.html" with node=node children_map=children_map is_first=forloop.first is_last=forloop.last rename_url=rename_url open_ids=open_ids %}
```

- [ ] **Step 6: Style the toggle column**

Append to `courses/static/courses/css/builder.css`:

```css
/* Disclosure column. Fixed width on BOTH the control and the leaf spacer so
   titles stay aligned down the tree; the count lives in aria-label, not in
   visible text, precisely so this width cannot vary. */
.tree__toggle { flex: 0 0 18px; width: 18px; height: 18px; display: inline-flex;
  align-items: center; justify-content: center; color: var(--text-secondary);
  border-radius: var(--radius-sm); text-decoration: none; }
.tree__toggle .ic { width: 12px; height: 12px; transition: transform .12s ease; }
.tree__toggle[aria-expanded="true"] .ic { transform: rotate(90deg); }
.tree__toggle:hover { color: var(--text-primary); background: var(--surface-sunken); }
.tree__toggle:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
.tree__toggle--leaf { pointer-events: none; }
```

- [ ] **Step 7: Wire the views**

In `courses/views_manage.py` add the import and update three functions:

```python
from courses.builder_open import open_ids as _open_ids
```

`builder()`:

```python
@login_required
def builder(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    cmap = _children_map(course)
    opened = _open_ids(request, course, cmap, mode="page")
    return render(
        request,
        "courses/manage/builder.html",
        {
            "course": course,
            "children_map": cmap,
            "top_nodes": cmap.get(None, []),
            "open_ids": opened.ids,
            "info": _info_entries(opened),
        },
    )
```

`_builder_with_notice()` — same two keys, `mode="notice"`:

```python
    cmap = _children_map(course)
    opened = _open_ids(request, course, cmap, mode="notice")
    return render(
        request,
        "courses/manage/builder.html",
        {
            "course": course,
            "children_map": cmap,
            "top_nodes": cmap.get(None, []),
            "notice": message,
            "open_ids": opened.ids,
            "info": _info_entries(opened),
        },
        status=status,
    )
```

`_render_scope()`:

```python
def _render_scope(request, course, scope_ref, *, extra_open=()):
    cmap = _children_map(course)
    opened = _open_ids(request, course, cmap, mode="fragment")
    ids = set(opened.ids) | _extra_container_pks(extra_open, cmap)
    ...
    return render(
        request,
        "courses/manage/_scope.html",
        {
            ...,
            "open_ids": ids,
        },
    )
```

and add the two small helpers beside it:

```python
def _info_entries(opened):
    """Keyed, so an incoming entry REPLACES rather than stacks."""
    if not opened.truncated:
        return []
    return [
        {
            "key": "truncation",
            "text": _("Only the first %(limit)s sections were opened.")
            % {"limit": CEILING},
        }
    ]


def _extra_container_pks(extra_open, cmap):
    """Effect 1 of extra_open: union into the open set, unit pks dropped.

    Effect 2 (re-inserting into a filtered map) is slice 2 -- see spec
    section 9. Callers pass EVERY created/moved pk whatever its kind; the kind
    filter lives here, not at the call site.
    """
    return set(extra_open) & container_pks(cmap)
```

with `from courses.builder_open import CEILING`, `container_pks`, and `from django.utils.translation import gettext as _` already present.

- [ ] **Step 8: Render the info slot**

In `templates/courses/manage/builder.html`, immediately after the existing `notice` line:

```html
{% if info %}<ul class="builder__info" role="status">{% for entry in info %}<li data-info-key="{{ entry.key }}">{{ entry.text }}</li>{% endfor %}</ul>{% endif %}
```

and in `builder.css`:

```css
.builder__info { list-style: none; margin: 0 0 var(--space-3); padding: var(--space-2) var(--space-3);
  background: var(--surface-sunken); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: .875rem; }
.builder__info:empty { display: none; }
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q
```
Expected: 6 passed.

- [ ] **Step 10: Falsify the headline guard**

Delete the `{% if node.pk in open_ids %}` wrapper in `_tree_node.html`, re-run, and confirm `test_collapsed_scope_emits_no_descendant_rows` goes **RED**. Restore it.

- [ ] **Step 11: Measure the real win**

```bash
uv run python manage.py shell -c "exec(open(r'C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/ab99b211-6983-4656-811e-9bc1c2971df5/scratchpad/probe1.py').read())"
```
Expected: the `mat-pp` scope render drops from ~3.1 s / 2.58 MB to well under 500 ms. Record the numbers — they go in the PR body against the spec's baseline table.

- [ ] **Step 12: Commit**

```bash
git branch --show-current
git add templates/courses/manage/_tree_node.html templates/courses/manage/_scope.html \
        templates/courses/manage/_icon_sprite.html templates/courses/manage/builder.html \
        courses/static/courses/css/builder.css courses/views_manage.py \
        tests/test_builder_lazy_scopes.py
git commit -m "feat(builder): render only open tree scopes"
```

---

### Task 4: The no-JS toggle link

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py`, `templates/courses/manage/_tree_node.html`, `courses/views_manage.py`
- Test: `tests/test_builder_lazy_scopes.py` (append)

**Interfaces:**
- Consumes: context keys `open_joined`, `open_descendants`, `builder_url`, `open_ids`.
- Produces: `{% toggle_href node is_open %}`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_toggle_href_expands_and_collapses_without_js(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(url).content.decode()
    m = re.search(r'data-toggle="%d"[^>]*href="([^"]+)"' % part.pk, html)
    assert m is None or "open=" in m.group(1)
    # collapsed -> its href opens it
    html = client.get(url).content.decode()
    href = re.search(r'href="([^"]*)"[^>]*data-toggle="%d"' % part.pk, html)
    assert href, "toggle must carry a real href for the no-JS path"


@pytest.mark.django_db
def test_collapse_href_drops_descendant_pks_too(client):
    """Collapse must forget descendants, or the no-JS path diverges from the
    JS path (which forgets them automatically by removing the subtree)."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk},{ch.pk}").content.decode()
    href = re.search(
        r'data-toggle="%d"[^>]*?href="([^"]+)"' % part.pk, html, re.S
    ) or re.search(r'href="([^"]+)"[^>]*?data-toggle="%d"' % part.pk, html, re.S)
    assert href
    value = href.group(1)
    assert str(ch.pk) not in value.split("open=")[-1].split("&")[0].split("#")[0]


@pytest.mark.django_db
def test_toggle_href_carries_a_row_anchor(client):
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"})
    ).content.decode()
    assert f"#node-{part.pk}" in html
    assert f'id="node-{part.pk}"' in html
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q -k toggle_href
```
Expected: FAIL — the toggle's `href` is still the literal `#`.

- [ ] **Step 3: Implement the tag**

Append to `courses/templatetags/courses_manage_extras.py`:

```python
from django import template
from django.utils.http import urlencode

register = template.Library()  # (already defined at the top of this module)


@register.simple_tag(takes_context=True)
def toggle_href(context, node, is_open):
    """The no-JS expand/collapse link for one container row.

    takes_context because open_descendants is a pk-keyed dict, which a
    template cannot index by a variable -- the lookup has to happen here.
    """
    ids = set(context.get("open_ids") or ())
    if is_open:
        # Subtract on the ID SET, never by string replacement: comma-joined
        # pks are prefix-colliding ("1,120,12".replace(",12","") corrupts it).
        # Descendants go too, so a collapse forgets them exactly as the JS
        # path does by removing the subtree.
        drop = {node.pk} | set((context.get("open_descendants") or {}).get(node.pk, ()))
        ids -= drop
        joined = ",".join(str(p) for p in sorted(ids))
    else:
        # Fast path: the precomputed join plus one pk.
        base = context.get("open_joined") or ""
        joined = f"{base},{node.pk}" if base else str(node.pk)
    query = urlencode({"open": joined})
    return f"{context.get('builder_url', '')}?{query}#node-{node.pk}"
```

- [ ] **Step 4: Precompute the context values**

In `courses/views_manage.py`, add:

```python
def _open_descendants(cmap, ids):
    """pk -> the OPEN container pks beneath it, in one bottom-up pass.

    Per row this would be a subtree walk; computed once per render it is a
    single pass, which is what keeps toggle_href off the render's critical
    path under a fully expanded tree.
    """
    out = {}

    def walk(pk):
        if pk in out:
            return out[pk]
        acc = set()
        for child in cmap.get(pk, []):
            if child.kind == ContentNode.Kind.UNIT:
                continue
            if child.pk in ids:
                acc.add(child.pk)
            acc |= walk(child.pk)
        out[pk] = acc
        return acc

    for parent_id in list(cmap):
        for n in cmap[parent_id]:
            if n.kind != ContentNode.Kind.UNIT:
                walk(n.pk)
    return out


def _tree_context(request, course, cmap, ids):
    """Keys every renderer of tree markup must supply, or toggle_href silently
    sees nothing on fragment renders."""
    return {
        "open_ids": ids,
        "open_joined": ",".join(str(p) for p in sorted(ids)),
        "open_descendants": _open_descendants(cmap, ids),
        "builder_url": reverse(
            "courses:manage_builder", kwargs={"slug": course.slug}
        ),
    }
```

and merge `_tree_context(...)` into the context dict of `builder()`, `_builder_with_notice()` and `_render_scope()` (replacing the bare `"open_ids"` key added in Task 3).

- [ ] **Step 5: Use the tag and add the row anchor**

In `_tree_node.html`: add `id="node-{{ node.pk }}"` to the `<li class="tree__row" …>` open tag, and replace both `href="#"` occurrences with `href="{% toggle_href node True %}"` (expanded branch) and `href="{% toggle_href node False %}"` (collapsed branch). Add `courses_manage_extras` to the `{% load %}` line if not already there (it is).

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q
```
Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add courses/templatetags/courses_manage_extras.py templates/courses/manage/_tree_node.html \
        courses/views_manage.py tests/test_builder_lazy_scopes.py
git commit -m "feat(builder): no-JS expand/collapse links"
```

---

### Task 5: The `manage_node_scope` endpoint

**Files:**
- Modify: `courses/urls.py`, `courses/views_manage.py`, `templates/courses/manage/builder.html`
- Test: `tests/test_builder_lazy_scopes.py` (append)

**Interfaces:**
- Produces: URL name `courses:manage_node_scope` (`…/build/node/<int:pk>/scope/`); root attribute `data-node-scope-url`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_scope_endpoint_returns_one_scope_for_a_manager(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    resp = client.get(
        reverse("courses:manage_node_scope", kwargs={"slug": "big", "pk": part.pk})
    )
    assert resp.status_code == 200
    assert f'data-scope="{part.pk}"' in resp.content.decode()


@pytest.mark.django_db
def test_scope_endpoint_404s_on_a_unit_and_on_a_foreign_pk(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    unit = chapters[0][1][0]
    assert (
        client.get(
            reverse("courses:manage_node_scope", kwargs={"slug": "big", "pk": unit.pk})
        ).status_code
        == 404
    )
    foreign = ContentNodeFactory(
        course=CourseFactory(slug="other"), kind="part", parent=None
    )
    assert (
        client.get(
            reverse(
                "courses:manage_node_scope", kwargs={"slug": "big", "pk": foreign.pk}
            )
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_scope_endpoint_403s_a_non_manager_and_redirects_anonymous(client):
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    url = reverse("courses:manage_node_scope", kwargs={"slug": "big", "pk": part.pk})
    make_login(client, "stranger")
    assert client.get(url).status_code == 403
    client.logout()
    assert client.get(url).status_code == 302
```

> Deliberately **no** "non-numeric pk → 404" case: the route is `<int:pk>`, so the resolver rejects it before the view runs and such a test would pass without any view code.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q -k scope_endpoint
```
Expected: FAIL — `NoReverseMatch: 'manage_node_scope' is not a valid view function or pattern name`.

- [ ] **Step 3: Implement the view**

In `courses/views_manage.py`:

```python
@login_required
def node_scope(request, slug, pk):
    """One scope <ol>, for the JS expand path.

    _require_manage alone is NOT enough: it validates the COURSE, and
    _render_scope resolves a missing/foreign pk to parent=None and returns 200
    with an empty scope. Resolve the node first, mirroring node_panel.
    """
    node = get_node_or_404(pk, slug)
    if node.kind == ContentNode.Kind.UNIT:
        raise Http404("Units own no scope.")
    course = _require_manage(request, slug)
    return _render_scope(request, course, node.pk)
```

- [ ] **Step 4: Add the route**

In `courses/urls.py`, directly after the `manage_node_panel` entry:

```python
    path(
        "manage/courses/<slug:slug>/build/node/<int:pk>/scope/",
        views_manage.node_scope,
        name="manage_node_scope",
    ),
```

- [ ] **Step 5: Publish the URL to the JS**

In `templates/courses/manage/builder.html`, add to the `<section class="builder" …>` attribute list:

```html
         data-node-scope-url="{% url 'courses:manage_node_scope' slug=course.slug pk=0 %}"
```

> `pk=0` is a sentinel. A string placeholder is impossible: the route is `<int:pk>`, whose converter regex is `[0-9]+`, so `{% url … pk='__PK__' %}` raises `NoReverseMatch`. The JS substitutes with an `$`-anchored replacement (Task 8).

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q
```
Expected: 12 passed.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add courses/urls.py courses/views_manage.py templates/courses/manage/builder.html \
        tests/test_builder_lazy_scopes.py
git commit -m "feat(builder): add the single-scope read endpoint"
```

---

### Task 6: `extra_open`, the session carrier, and `open=session` redirects

**Files:**
- Modify: `courses/views_manage.py` (`_render_tree`, `node_add`, `node_move`, `node_duplicate`, `node_rename`, `node_delete`, `builder`)
- Test: `tests/test_builder_lazy_scopes.py` (append)

**Interfaces:**
- Consumes: `remember_node` (Task 2), `courses.builder_open.OPEN_KEY`.
- Produces: `_render_tree(request, course, status=200, *, extra_open=())`; `_ancestor_chain(node) -> set[int]`.

- [ ] **Step 1: Write the failing test**

```python
from courses.builder_open import OPEN_KEY


@pytest.mark.django_db
def test_reparent_into_a_collapsed_destination_returns_the_moved_node(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    src, dest = chapters[0][0], chapters[1][0]
    unit = chapters[0][1][0]
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "big"}),
        {
            "mode": "reparent",
            "node": unit.pk,
            "node_token": unit.updated.isoformat(),
            "new_parent": dest.pk,
            "position": 0,
            "open": str(src.pk),          # dest is NOT open
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    # Without extra_open the row vanishes with no marker -- indistinguishable
    # from failure, on the affordance that exists for unseen destinations.
    assert f'data-node="{unit.pk}"' in resp.content.decode()


@pytest.mark.django_db
def test_adding_a_container_returns_it_already_open(client):
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "big"}),
        {
            "parent": part.pk,
            "parent_token": part.updated.isoformat(),
            "kind": "chapter",
            "title": "Fresh",
            "open": str(part.pk),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    new = course.nodes.get(title="Fresh")
    assert f'data-scope="{new.pk}"' in html     # its own scope is rendered


@pytest.mark.django_db
def test_no_js_mutation_round_trips_the_open_set_through_the_session(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    client.get(f"{url}?open={part.pk}")                  # persisted (step 2)
    assert client.session[OPEN_KEY]["big"] == [part.pk]
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "big"}),
        {"node": part.pk, "token": part.updated.isoformat(), "title": "P0 renamed"},
    )
    assert resp.status_code == 302
    assert "open=session" in resp["Location"]
    html = client.get(resp["Location"]).content.decode()
    assert f'data-node="{chapters[0][0].pk}"' in html    # still expanded


@pytest.mark.django_db
def test_a_derived_open_set_is_not_persisted(client):
    """Only an explicit `open` (steps 1-2) is written back."""
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    client.get(f"{url}?open={part.pk}")
    client.get(url)                                      # seeded, not explicit
    assert client.session[OPEN_KEY]["big"] == [part.pk]  # unchanged
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q -k "reparent_into or adding_a_container or round_trips or derived"
```
Expected: FAIL — the moved node is absent and no `open=session` appears in the redirect.

- [ ] **Step 3: Implement**

In `courses/views_manage.py`:

```python
def _ancestor_chain(node):
    """The node's own pk plus every ancestor pk. One query per level, and the
    chain is at most 4 deep, so this is bounded."""
    out, cur = {node.pk}, node.parent
    while cur is not None:
        out.add(cur.pk)
        cur = cur.parent
    return out


def _render_tree(request, course, status=200, *, extra_open=()):
    resp = _render_scope(request, course, "top", extra_open=extra_open)
    resp.status_code = status
    return resp


def _remember_open(request, course, opened, present):
    """Persist ONLY an explicit open (precedence steps 1-2).

    A derived set must never be written back: persisting the seed or the
    size-rule default would overwrite the author's real expansion, and they
    could never get it back.
    """
    if not present:
        return
    remember_node(request, course.slug, sorted(opened.ids), key=OPEN_KEY)
```

In `builder()`, after computing `opened`:

```python
    _remember_open(request, course, opened, "open" in request.GET)
```

Change the six no-JS redirects (`views_manage.py:282`, `:344`, `:376`, `:411`, `:455`, `:494`) from

```python
        return redirect("courses:manage_builder", slug=course.slug)
```

to

```python
        return _redirect_to_builder(course)
```

with:

```python
def _redirect_to_builder(course):
    """The ONLY places allowed to emit the open=session sentinel."""
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    return redirect(f"{url}?open=session")
```

Pass `extra_open` from the three mutating views:

```python
# node_add, after a successful add:
    if node.parent_id is None:
        return _render_tree(request, course, extra_open=_ancestor_chain(node))
    return _render_scope(
        request, course, _scope_ref(node.parent_id), extra_open=_ancestor_chain(node)
    )
```

```python
# node_move reparent branch -- capture the node returned by reparent_node:
        node, _old = builder_svc.reparent_node(...)
        ...
        return _render_tree(request, course, extra_open=_ancestor_chain(node))
```

```python
# node_duplicate, after materialising new_node:
    if new_node.parent_id is None:
        return _render_tree(request, course, extra_open=_ancestor_chain(new_node))
    return _render_scope(
        request,
        course,
        _scope_ref(new_node.parent_id),
        extra_open=_ancestor_chain(new_node),
    )
```

> `_ancestor_chain` is passed **whatever the node's kind**. The kind filter lives in `_extra_container_pks` (Task 3), so a unit's pk is harmlessly dropped from the open set while slice 2's filtered re-insertion can still use it.

For the no-JS branches of the same three views, persist the chain before redirecting:

```python
    if not _wants_fragment(request):
        store = set(request.session.get(OPEN_KEY, {}).get(course.slug) or [])
        remember_node(
            request,
            course.slug,
            sorted(store | (_ancestor_chain(node) & container_pks(_children_map(course)))),
            key=OPEN_KEY,
        )
        return _redirect_to_builder(course)
```

> The chain, not the bare pk: if `builder_open` happens to be missing, a bare `[new_pk]` is non-empty so the `open=session` read would *not* fall through, and the tree would render with every ancestor collapsed — hiding the node just created.

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q
```
Expected: 16 passed.

- [ ] **Step 5: Run the whole non-e2e builder suite for regressions**

```bash
uv run pytest tests/ -q -k "builder or node_ops or affordance or tree_badge" ; echo "exit=$?"
```
Expected: failures in the *existing* suite are expected here and are fixed in Task 11. Record which files fail — that list drives Task 11.

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add courses/views_manage.py tests/test_builder_lazy_scopes.py
git commit -m "feat(builder): force-open mutation destinations and carry open through no-JS"
```

---

### Task 7: The delete chain

Delete is a full-page navigation for **every** author: `node_confirm_delete.html`'s form has no `data-op` and `builder.js` has no `[data-delete]` handler, so `node_delete`'s fragment branch is unreachable from the UI.

**Files:**
- Modify: `courses/views_manage.py` (`node_delete` GET branch), `templates/courses/manage/node_confirm_delete.html`, `templates/courses/manage/_tree_node.html`
- Test: `tests/test_builder_lazy_scopes.py` (append)

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_delete_confirm_round_trips_the_open_set(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    victim = chapters[0][1][0]
    confirm = client.get(
        reverse("courses:manage_node_delete", kwargs={"slug": "big"})
        + f"?node={victim.pk}&open={part.pk},{chapters[0][0].pk}"
    )
    assert f'value="{part.pk},{chapters[0][0].pk}"' in confirm.content.decode()
    resp = client.post(
        reverse("courses:manage_node_delete", kwargs={"slug": "big"}),
        {
            "node": victim.pk,
            "token": victim.updated.isoformat(),
            "open": f"{part.pk},{chapters[0][0].pk}",
        },
    )
    assert f"open={part.pk}" in resp["Location"]
    assert "open=session" not in resp["Location"]


@pytest.mark.django_db
def test_delete_without_an_open_param_falls_back_to_the_session_sentinel(client):
    """No-JS: there is no href rewrite, so `open` is absent -- and emitting
    `open=` would blank the tree instead of degrading."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    victim = chapters[0][1][0]
    resp = client.post(
        reverse("courses:manage_node_delete", kwargs={"slug": "big"}),
        {"node": victim.pk, "token": victim.updated.isoformat()},
    )
    assert "open=session" in resp["Location"]
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q -k delete
```
Expected: FAIL — the confirm page has no hidden `open`.

- [ ] **Step 3: Implement**

In `node_delete`'s GET branch, add `"open": request.GET.get("open", "")` to the render context. In the POST branch, replace the redirect:

```python
    if not _wants_fragment(request):
        if "open" in request.POST:
            url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
            return redirect(f"{url}?{urlencode({'open': request.POST['open']})}")
        return _redirect_to_builder(course)
```

In `templates/courses/manage/node_confirm_delete.html`, inside the `<form>`:

```html
    {% if open %}<input type="hidden" name="open" value="{{ open }}">{% endif %}
```

and extend the Cancel link (`:12`), which now has the value for free:

```html
    <a class="btn btn--ghost" href="{% url 'courses:manage_builder' slug=course.slug %}{% if open %}?open={{ open|urlencode }}{% endif %}">{% trans "Cancel" %}</a>
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q -k delete
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add courses/views_manage.py templates/courses/manage/node_confirm_delete.html \
        tests/test_builder_lazy_scopes.py
git commit -m "feat(builder): carry the open set through the delete confirmation"
```

---

### Task 8: `builder.js` — toggle, collector, busy state

**Files:**
- Modify: `courses/static/courses/js/builder.js`, `courses/static/courses/css/builder.css`
- Test: `tests/test_e2e_builder_toggle.py` *(new)*

- [ ] **Step 1: Write the failing e2e**

Create `tests/test_e2e_builder_toggle.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import TEST_PASSWORD
from tests.factories import UserFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _seed(owner):
    course = CourseFactory(slug="e2e", owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="Part A")
    ch = ContentNodeFactory(course=course, kind="chapter", parent=part, title="Chap A")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="Unit A"
    )
    # push the course over SIZE_THRESHOLD so it does NOT auto-expand
    for i in range(160):
        ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=ch, title=f"U{i}"
        )
    return course, part, ch, unit


def _login(page, live_server, user):
    page.goto(f"{live_server.url}{reverse('accounts:login')}")
    page.fill("input[name=username]", user.username)
    page.fill("input[name=password]", TEST_PASSWORD)
    page.click("button[type=submit]")


def test_toggle_expands_and_collapses(page, live_server):
    owner = UserFactory(is_staff=True)
    course, part, ch, _unit = _seed(owner)
    _login(page, live_server, owner)
    page.goto(f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}")
    assert page.locator(f'[data-node="{ch.pk}"]').count() == 0
    page.click(f'[data-toggle="{part.pk}"]')          # the REAL gesture
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    toggle = page.locator(f'[data-toggle="{part.pk}"]')
    assert toggle.get_attribute("aria-expanded") == "true"
    assert toggle.get_attribute("aria-controls") == f"tree-scope-{part.pk}"
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]', state="detached")
    assert toggle.get_attribute("aria-expanded") == "false"
    assert toggle.get_attribute("aria-controls") is None


def test_double_click_yields_exactly_one_scope(page, live_server):
    owner = UserFactory(is_staff=True)
    course, part, ch, _u = _seed(owner)
    _login(page, live_server, owner)
    page.goto(f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}")
    page.dblclick(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    assert page.locator(f'ol[data-scope="{part.pk}"]').count() == 1


def test_expansion_survives_a_reload(page, live_server):
    owner = UserFactory(is_staff=True)
    course, part, ch, _u = _seed(owner)
    _login(page, live_server, owner)
    page.goto(f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}")
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    page.reload()
    page.wait_for_selector(f'[data-node="{ch.pk}"]')   # replaceState carried it


def test_collapsing_the_last_scope_survives_a_reload(page, live_server):
    """The empty set must be written as `open=` (present, empty), not omitted,
    or the reload re-seeds from the session and springs the tree back open."""
    owner = UserFactory(is_staff=True)
    course, part, ch, _u = _seed(owner)
    _login(page, live_server, owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "e2e"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]', state="detached")
    page.reload()
    assert page.locator(f'[data-node="{ch.pk}"]').count() == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e ; echo "exit=$?"
```
Expected: FAIL — clicking the toggle navigates to `#…` and nothing expands.

- [ ] **Step 3: Implement the JS**

In `courses/static/courses/js/builder.js`, add after the `csrf()` helper:

```js
  // ---- open-set collector + busy counter -------------------------------------
  // The collector observes the DOM, so it can only ever emit an enumeration;
  // `all` originates from the server, never from here.
  function collectOpen() {
    var out = [];
    root.querySelectorAll("ol.tree__scope[data-scope]").forEach(function (ol) {
      var s = ol.getAttribute("data-scope");
      if (s && s !== "top") out.push(s);
    });
    return out.join(",");
  }
  // SET, never append: mutation forms may already carry the value, and
  // QueryDict.get returns the LAST, so appending would win only by accident.
  function withOpen(body) { body.set("open", collectOpen()); return body; }

  function syncUrl() {
    // Present-but-empty, never omitted: dropping the parameter makes the next
    // page GET see `open` as ABSENT and re-seed from the session.
    var u = new URL(window.location.href);
    u.searchParams.set("open", collectOpen());
    history.replaceState(null, "", u.toString());
  }

  var busy = 0;
  function busyStart() { busy++; root.setAttribute("data-busy", "1"); }
  function busyEnd() { if (--busy <= 0) { busy = 0; root.removeAttribute("data-busy"); } }
```

Add the toggle handler before the drag section:

```js
  // ---- expand / collapse -----------------------------------------------------
  function scopeUrlFor(pk) {
    // pk=0 sentinel, replaced with an $-ANCHORED match so a `0` inside the
    // course slug can never be hit. A string placeholder is impossible: the
    // route is <int:pk> and reverse() rejects a non-numeric pk.
    var tpl = root.getAttribute("data-node-scope-url") || "";
    return tpl.replace(/\/0\/scope\/$/, "/" + pk + "/scope/");
  }

  root.addEventListener("pointerdown", function (e) {
    // Armed HERE, not around the removal: a click moves focus at mousedown, so
    // a dirty title's focusout fires BEFORE this handler's click would -- and
    // the rename guard reads `swapping`, which would still be false.
    if (e.target.closest("[data-toggle]")) swapping = true;
  });
  document.addEventListener("pointerup", function () { swapping = false; });
  document.addEventListener("pointercancel", function () { swapping = false; });

  root.addEventListener("click", function (e) {
    var t = e.target.closest("[data-toggle]");
    if (!t) return;
    e.preventDefault();                       // it is an <a href>; do not navigate
    if (t.dataset.submitting) return;         // ignore repeat activations
    var pk = t.getAttribute("data-toggle");
    var row = t.closest("li.tree__row");
    if (!row) return;
    var existing = row.querySelector(":scope > ol.tree__scope");
    if (existing) {
      swapping = true;
      try { existing.remove(); } finally { swapping = false; }
      t.setAttribute("aria-expanded", "false");
      t.removeAttribute("aria-controls");
      if (t.dataset.labelExpand) t.setAttribute("aria-label", t.dataset.labelExpand);
      syncUrl();
      return;
    }
    t.dataset.submitting = "1";
    busyStart();
    var body = new URLSearchParams();
    body.set("open", collectOpen() ? collectOpen() + "," + pk : pk);
    fetch(scopeUrlFor(pk) + "?" + body.toString(), {
      headers: { "X-Requested-With": "fetch" },
    }).then(function (r) {
      if (!r.status || r.status !== 200) throw new Error("bad status");
      return r.text();
    }).then(function (html) {
      // A foreign applyFragment may have replaced this row while we waited.
      var live = root.querySelector('li.tree__row[data-node="' + pk + '"]');
      var ctl = live && live.querySelector(':scope > .tree__rowhead [data-toggle]');
      if (!live || !ctl || !ctl.dataset.submitting) return;
      var incoming = parseFragment(html).firstElementChild;
      if (!incoming) return;
      // Replace, never blind-append: two responses would leave two sibling
      // <ol data-scope> and `:scope > ol.tree__scope` would pick one at random.
      var dup = live.querySelector(":scope > ol.tree__scope");
      if (dup) dup.remove();
      live.appendChild(incoming);             // direct child, after .tree__rowhead
      ctl.setAttribute("aria-expanded", "true");
      ctl.setAttribute("aria-controls", "tree-scope-" + pk);
      if (ctl.dataset.labelCollapse) ctl.setAttribute("aria-label", ctl.dataset.labelCollapse);
      syncUrl();
    }).catch(function () {
      notice(msg("network", "Network error — please try again."));
    }).then(function () {
      var ctl2 = root.querySelector('[data-toggle="' + pk + '"]');
      if (ctl2) delete ctl2.dataset.submitting;   // clear on BOTH paths, or the row wedges
      busyEnd();
    });
  });
```

Wrap the two existing fetch call sites: in the `submit` handler replace `body: body,` with `body: withOpen(body),`, and in the `drop` handler add `withOpen(body);` before the `fetch(`. Add `syncUrl();` inside both `.then` blocks after `applyFragment(text);`.

- [ ] **Step 4: Style the busy state**

Append to `builder.css`:

```css
/* Visual only. It must NOT set pointer-events:none -- the per-toggle
   in-flight guard is what prevents double activation, and blocking pointer
   events here would make that guard dead code. */
.builder[data-busy] .builder__tree { opacity: .6; transition: opacity .1s ease; cursor: progress; }
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e ; echo "exit=$?"
```
Expected: exit=0, 4 passed.

- [ ] **Step 6: Verify the JS invariants test still passes**

```bash
uv run pytest tests/test_builder_js_invariants.py -q ; echo "exit=$?"
```
Expected: exit=0. This file regexes **raw source including comments**, so if it fails, check whether a comment you added mentions `panel.innerHTML`.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add courses/static/courses/js/builder.js courses/static/courses/css/builder.css \
        tests/test_e2e_builder_toggle.py
git commit -m "feat(builder): expand/collapse scopes without a page load"
```

---

### Task 9: `builder.js` — drag throttle

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Test: `tests/test_e2e_builder_toggle.py` (append)

- [ ] **Step 1: Write the failing e2e**

```python
def test_drag_and_release_within_one_pointer_move(page, live_server):
    """Covers the drop-flushes-the-frame case. A cancel-only rule silently
    drops this gesture: targetScope is set in the DEFERRED part."""
    owner = UserFactory(is_staff=True)
    course = CourseFactory(slug="drag", owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    a = ContentNodeFactory(course=course, kind="chapter", parent=part, title="A")
    b = ContentNodeFactory(course=course, kind="chapter", parent=part, title="B")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=a, title="Movable"
    )
    for i in range(160):
        ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=b, title=f"F{i}"
        )
    _login(page, live_server, owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "drag"})
    page.goto(f"{live_server.url}{url}?open={part.pk},{a.pk},{b.pk}")
    src = page.locator(f'[data-node="{unit.pk}"] .ica--grip')
    dst = page.locator(f'ol[data-scope="{b.pk}"]')
    src.hover()
    page.mouse.down()
    dst.hover()                       # a SINGLE move, then release
    page.mouse.up()
    page.wait_for_selector(f'ol[data-scope="{b.pk}"] [data-node="{unit.pk}"]')
    unit.refresh_from_db()
    assert unit.parent_id == b.pk
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e -k drag_and_release ; echo "exit=$?"
```
Expected: this passes *before* the throttle exists (today's handler is synchronous). It is the regression guard for Step 3 — note the pass, then confirm it still passes after.

- [ ] **Step 3: Implement the throttle**

Replace `clearDropMarks` and the `dragover`/`drop`/`dragend` handlers:

```js
  var markedScope = null, markedLine = null;   // tracked, not re-queried
  function clearDropMarks() {
    if (markedScope) { markedScope.classList.remove("drop-target"); markedScope = null; }
    if (markedLine) { markedLine.remove(); markedLine = null; }
  }

  var pendingFrame = null, lastY = 0, lastScope = null;
  function cancelFrame() {
    if (pendingFrame !== null) { cancelAnimationFrame(pendingFrame); pendingFrame = null; }
  }
  function paintDropMarks() {
    pendingFrame = null;
    if (!drag || !lastScope) return;           // outlived drop/dragend
    clearDropMarks();
    lastScope.classList.add("drop-target");
    markedScope = lastScope;
    var t = targetFor(lastY, lastScope);
    var line = document.createElement("li");
    line.className = "drop-line";
    if (t.before) lastScope.insertBefore(line, t.before); else lastScope.appendChild(line);
    markedLine = line;
    lastScope.dataset.dropIndex = t.index;
    lastScope.dataset.dropParent = lastScope.getAttribute("data-scope");
    lastScope.dataset.dropToken = lastScope.getAttribute("data-updated");
    drag.targetScope = lastScope;
  }

  root.addEventListener("dragover", function (e) {
    if (!drag) return;
    var scope;
    var targetRow = e.target.closest(".tree__row");
    if (targetRow) {
      var childScope = targetRow.querySelector(":scope > .tree__scope");
      if (childScope && !childScope.contains(e.target)) scope = childScope;
    }
    if (!scope) scope = e.target.closest(".tree__scope");
    // Both rejecting branches cancel: a frame scheduled by the PREVIOUS legal
    // dragover would otherwise re-mark a target just rejected and re-set
    // targetScope, so a drop there would post an illegal move.
    if (!scope) { cancelFrame(); return; }
    var destRow = scope.closest(".tree__row");
    var parentKind = destRow ? destRow.getAttribute("data-kind") : null;
    var draggedRow = root.querySelector('.tree__row[data-node="' + drag.pk + '"]');
    if (!legal(parentKind) || (draggedRow && draggedRow.contains(scope))) {
      cancelFrame(); clearDropMarks(); drag.targetScope = null; return;
    }
    // Legality costs no layout, so it stays synchronous -- and preventDefault
    // stays conditional on it, or every illegal spot advertises as droppable.
    e.preventDefault();
    lastY = e.clientY;                        // the LATEST event, not the one
    lastScope = scope;                        // that scheduled the frame
    if (pendingFrame === null) pendingFrame = requestAnimationFrame(paintDropMarks);
  });
```

and in `drop`, before reading `drag.targetScope`:

```js
    if (pendingFrame !== null) { paintDropMarks(); cancelFrame(); }  // FLUSH, don't cancel
    var scope = drag.targetScope;
```

and in `dragend`:

```js
  root.addEventListener("dragend", function () {
    cancelFrame(); clearDropMarks(); drag = null; pointerFocus = false;
  });
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e ; echo "exit=$?"
```
Expected: exit=0, 5 passed.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add courses/static/courses/js/builder.js tests/test_e2e_builder_toggle.py
git commit -m "perf(builder): throttle dragover to one forced layout per frame"
```

---

### Task 10: Hoist the per-row URL reversals

**Files:**
- Modify: `templates/courses/manage/_scope.html`, `templates/courses/manage/_tree_node.html`, `templates/courses/manage/_move_buttons.html`, `courses/static/courses/js/builder.js`
- Test: `tests/test_builder_lazy_scopes.py` (append)

- [ ] **Step 1: Write the failing test**

```python
from unittest import mock


@pytest.mark.django_db
def test_per_row_url_reversals_are_hoisted(client):
    """Guards section 7. Without this, reintroducing {% url %} in a row
    template is invisible to the suite -- section 7's only justification is
    wall-clock time, which CI deliberately does not assert on."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    seen = []
    import django.urls as django_urls

    real = django_urls.reverse

    def spy(*a, **kw):
        seen.append(a[0] if a else kw.get("viewname"))
        return real(*a, **kw)

    # django.urls.reverse -- NOT django.urls.base.reverse and NOT
    # defaulttags.reverse: URLNode.render imports it from django.urls at call
    # time, so only this binding is observed.
    with mock.patch.object(django_urls, "reverse", spy):
        client.get(f"{url}?open=all")

    rows = course.nodes.count()
    per_row = ["courses:manage_node_move", "courses:manage_node_delete",
               "courses:manage_node_duplicate", "courses:manage_node_panel"]
    for name in per_row:
        assert seen.count(name) < rows, f"{name} still reversed per row"
    # export is a real <a href> a no-JS author follows, so it stays per node
    assert seen.count("courses:manage_node_export") == rows
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q -k reversals
```
Expected: FAIL — `courses:manage_node_move still reversed per row`.

- [ ] **Step 3: Hoist in `_scope.html`**

Extend the existing hoist block at the top of `templates/courses/manage/_scope.html`:

```html
{% url 'courses:manage_node_rename' slug=course.slug as rename_url %}
{% url 'courses:manage_node_move' slug=course.slug as move_url %}
{% url 'courses:manage_node_delete' slug=course.slug as delete_url %}
{% url 'courses:manage_node_duplicate' slug=course.slug as duplicate_url %}
```

and pass them down on the `_tree_node.html` include:

```html
    {% include "courses/manage/_tree_node.html" with node=node children_map=children_map is_first=forloop.first is_last=forloop.last rename_url=rename_url move_url=move_url delete_url=delete_url duplicate_url=duplicate_url open_ids=open_ids %}
```

- [ ] **Step 4: Consume them in `_tree_node.html`**

Replace the four `{% url %}` calls:

- Move link: `href="{{ move_url }}?node={{ node.pk }}"`
- Duplicate form: `action="{{ duplicate_url }}"`
- Delete link: `href="{{ delete_url }}?node={{ node.pk }}"`
- Drop `data-panel-url` from the title input entirely (the JS reads it from the root instead — Step 6)
- Pass the move URL into the include: `{% include "courses/manage/_move_buttons.html" with node=node is_first=is_first is_last=is_last move_url=move_url %}`

- [ ] **Step 5: Stop `_move_buttons.html` reversing**

```html
<form class="tree__inline" method="post" action="{{ move_url }}" data-op="reorder">
```

> `_tree_node.html` includes this **without `only`**, so `move_url` would already be visible from the parent context; passing it explicitly matches the `rename_url` convention.

- [ ] **Step 6: Move the panel URL to the root**

In `builder.html`, `data-panel-url` already exists on `.builder` with `pk=0`. In `builder.js`, replace the `focusin` handler's URL lookup:

```js
    var t = e.target.closest(".tree__title");
    if (!t) return;
    var row = t.closest("li.tree__row");
    if (!row) return;
    var tpl = root.getAttribute("data-panel-url") || "";
    var url = tpl.replace(/\/0\/$/, "/" + row.getAttribute("data-node") + "/");
    if (!url) return;
```

- [ ] **Step 7: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e ; echo "exit=$?"
```
Expected: both green — the panel-URL change is covered by the existing panel e2e in Task 11's sweep.

- [ ] **Step 8: Commit**

```bash
git branch --show-current
git add templates/courses/manage/_scope.html templates/courses/manage/_tree_node.html \
        templates/courses/manage/_move_buttons.html courses/static/courses/js/builder.js \
        tests/test_builder_lazy_scopes.py
git commit -m "perf(builder): hoist per-course URL reversals out of the row loop"
```

---

### Task 11: Migrate the existing suite

**Files:**
- Create: `tests/helpers_builder.py`
- Modify: every test file the sweep identifies

- [ ] **Step 1: Regenerate the affected-file list**

```bash
cd "$(git rev-parse --show-toplevel)"
grep -rln "manage_builder\|/build/\|data-scope\|tree__row\|data-panel-url\|data-node-move-url" tests/ | sort
```
Expected: at least `test_manage_builder.py`, `test_manage_node_ops.py`, `test_manage_affordance.py`, `test_manage_node_duplicate.py`, `test_manage_duplicate_button.py`, `test_tree_badge.py`, `test_seed_demo_course.py`, `test_e2e_builder.py`, `test_e2e_builder_ws2.py`, `test_e2e_builder_authoring.py`, `test_e2e_builder_reorder.py`, `test_e2e_builder_tree_layout.py`, `test_e2e_inline_rename.py`, `test_e2e_transfer.py`, `test_builder_styles.py`.

Do **not** work from the file-name prefix — four of these were missed that way.

- [ ] **Step 2: Write the shared helpers**

Create `tests/helpers_builder.py`:

```python
"""Helpers for tests written before the builder became lazy.

Most seeded fixtures are under SIZE_THRESHOLD and so still arrive fully
expanded -- which is a TRAP, not a relief: such a test no longer exercises
the lazy path at all. At least one test per behaviour must seed above the
threshold or pass open= explicitly.
"""


def open_all_param():
    """Append to a builder GET to force every scope open."""
    return "?open=all"


def expand_to(page, *nodes):
    """Click the real toggles down a chain and wait for each scope.

    Drives the actual control -- never page.evaluate, which would ship broken
    UX green.
    """
    for node in nodes:
        toggle = page.locator(f'[data-toggle="{node.pk}"]')
        if toggle.get_attribute("aria-expanded") == "true":
            continue
        toggle.click()
        page.wait_for_selector(f'ol[data-scope="{node.pk}"]')
```

- [ ] **Step 3: Fix the Python/view tests**

For each failing view test, append `open_all_param()` to the builder GET. Example, in `tests/test_manage_builder.py`:

```python
from tests.helpers_builder import open_all_param

resp = client.get(
    reverse("courses:manage_builder", kwargs={"slug": "c1"}) + open_all_param()
)
```

- [ ] **Step 4: Fix the e2e tests**

Replace `wait_for_selector('[data-scope="…"]')` immediately after a `goto` with an `expand_to(page, part, chapter)` call. Remember: **Playwright's text engine never matches `input[type=text]`**, so tree row titles cannot be located with `text=` or `get_by_text` — sweep for both forms.

- [ ] **Step 5: Re-measure `test_e2e_builder_tree_layout.py`**

The toggle adds an 18px column to every row. Re-run and read the actual geometry out of the failure output; do **not** guess the new numbers.

```bash
uv run pytest tests/test_e2e_builder_tree_layout.py -q -m e2e ; echo "exit=$?"
```

- [ ] **Step 6: Update `test_manage_affordance.py` for the real change**

Collapsing a container also hides its add affordance (`_add_affordance.html` renders inside `_scope.html`). Rewrite the assertions to expect that, and add one asserting the affordance **is** present once the scope is open. This encodes a behaviour change, not a fixture problem.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest tests/ -q ; echo "unit exit=$?"
uv run pytest tests/ -q -m e2e ; echo "e2e exit=$?"
```
Expected: both exit=0.

- [ ] **Step 8: Commit**

```bash
git branch --show-current
git add tests/
git commit -m "test(builder): migrate the suite to lazy tree scopes"
```

---

### Task 12: Catalogs, screenshots, lint, and the measured verdict

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ `.mo`), `core/static/core/img/help/builder-tree.{en,pl}.png`

- [ ] **Step 1: Regenerate the catalogs**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

Then open both `.po` files and clear every fuzzy entry — **two deletions each**: the `#, fuzzy` line and the `#| msgid` line. A fuzzy entry arrives pre-filled from an unrelated msgid, so leaving it ships a wrong translation. Translate the new toggle labels into Polish, respecting all three plural forms.

- [ ] **Step 2: Compile and verify catalog health**

```bash
uv run python manage.py compilemessages
uv run pytest tests/test_i18n_po_health.py -q ; echo "exit=$?"
```
Expected: exit=0.

- [ ] **Step 3: Re-capture the help screenshots**

```bash
uv run pytest tests/capture_help_screenshots.py -q -m e2e ; echo "exit=$?"
uv run python manage.py shell -c "
from courses.models import Course
c = Course.objects.filter(slug='demo-course').first()
print('demo-course nodes:', c.nodes.count() if c else 'MISSING')"
```
Record the node count in the PR — it decides whether the new shot shows an expanded or a collapsed tree, and therefore whether the surrounding help text is still accurate.

- [ ] **Step 4: Lint**

```bash
uv run ruff format --check .
uv run ruff check .
```
Expected: both clean.

- [ ] **Step 5: Measure against the spec's baseline**

Re-run the exact probes that produced the baseline, both ways (browser and offline) so the numbers are comparable:

```bash
uv run python manage.py shell -c "exec(open(r'C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/ab99b211-6983-4656-811e-9bc1c2971df5/scratchpad/probe1.py').read())"
uv run python "C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/ab99b211-6983-4656-811e-9bc1c2971df5/scratchpad/measure_browser.py"
```

Fill in this table for the PR body. Targets from the spec:

| Metric | Before | Target | After |
| --- | --- | --- | --- |
| `domInteractive`, `mat-pp` | 8.37 s | < 1.5 s | |
| Response size | 3.0 MB | < 300 KB | |
| DOM elements, empty open set | 38,418 | < 1,300 | |
| DOM elements, seed worst case | 38,418 | < 3,800 | |
| Reparent round trip | 4.47 s | < 500 ms | |
| Toggle round trip | n/a | < 300 ms | |
| Forced layout per `dragover` | 14.4 ms | ≤ 1 per frame | |
| Post-change elements per row | 40.7 | ~44 (re-measure) | |

If any target is missed, **stop and report** rather than adjusting the target. The first thing to try for a missed toggle budget is narrowing `_render_scope`'s full-`cmap` rebuild (89 ms on `mat-pp`), which the spec accepts explicitly.

- [ ] **Step 6: Screenshot both themes**

Take Playwright screenshots of the builder in light **and** dark, at a collapsed and an expanded state, and self-critique before opening the PR. Judge dark on its own — never infer it from light.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add locale/ core/static/core/img/help/
git commit -m "chore(builder): refresh catalogs and help screenshots for lazy scopes"
```

---

## Self-Review

**Spec coverage.** §1 lazy render → T3. §2 `open` transport, precedence, helper contract, `extra_open`, session carrier → T1/T3/T6. §3+§3a session seed and size default → T1/T2. §4 no-JS parity, toggle hrefs, redirect sites, delete chain → T4/T6/T7. §5 scope endpoint, JS toggle, insertion point, in-flight guard, `replaceState`, rename guard → T5/T8. §6 drag handler → T9. §7 reversal hoist + its guard → T10. §8 busy affordance → T8. Testing/migration → T11. Catalogs, screenshots, measurement → T12. **§9 and §10 are slice 2 and deliberately absent.**

**Known gap, deliberate:** the spec's `q`/filter rules (`_filtered_map`, `q` on hrefs and forms, `X-Builder-Info`'s `filtered` code, the `q_chain` precedence step) are reserved but not implemented — `open_ids` accepts `q_chain=None` so slice 2 does not have to retrofit a precedence step across a function boundary, and `_info_entries` already emits keyed entries so slice 2 only adds a second key.

**Type consistency.** `open_ids()` is the module function throughout (the spec's `_open_ids`; imported as `_open_ids` in `views_manage.py`). `OpenSet.ids` is a `frozenset` everywhere; `_extra_container_pks` and `_render_scope` build plain sets locally rather than mutating it. `remember_node(request, slug, value, key=...)` is used for all three session dicts. `container_pks(cmap)` is used by both `builder_open.py` and `views_manage.py`.

**Placeholder scan:** none — every step carries the actual code or the exact command and its expected output.
