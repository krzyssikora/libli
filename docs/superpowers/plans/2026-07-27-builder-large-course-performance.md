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
- Constants, exact values from the spec: ceiling **500** pks, size threshold **150** nodes,
  session slug bound **20**. The "seed chain is at most 4 scopes" figure is **not** a
  constant to implement — it is an emergent property of `ContentNode.RANK` having four
  levels, so `_chain` walks the chain unbounded and the 4 follows.
- **Every code block in this plan is meant to be pasted verbatim, then formatted.** End each
  task by running `uv run ruff format .` and `uv run ruff check .` *before* the commit step;
  several snippets here are hand-wrapped and `ruff format` will re-flow them. Appended
  imports go at the **top** of the file with the existing import block — ruff selects `E`,
  so `E402` rejects a mid-file import, and isort is `force-single-line`.

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

### Task 0: Commit the measurement harness

The plan's only performance gate is a pair of probe scripts. They must live in the repo,
not in a session scratchpad, and one of them breaks the moment Task 3 lands.

**Files:**
- Create: `scripts/perf/probe_tree_render.py`, `scripts/perf/probe_browser.py`, `scripts/perf/README.md`

- [ ] **Step 1: Write the server-side probe**

Create `scripts/perf/probe_tree_render.py`:

```python
"""Time the builder tree render for one course. Usage:

    uv run python manage.py shell -c \
      "exec(open('scripts/perf/probe_tree_render.py').read())" -- mat-pp

Prints warm render time, byte size, element count and query count. `OPEN` may
be set to "all" (default), "" or a comma-separated pk list.
"""

import os
import re
import time
from collections import Counter

from django.conf import settings
from django.db import connection
from django.db import reset_queries
from django.template.loader import render_to_string

from courses.models import Course
from courses.models import ContentNode
from courses.views_manage import _children_map

SLUG = os.environ.get("SLUG", "mat-pp")
OPEN = os.environ.get("OPEN", "all")


def _containers(cmap):
    """Local copy, so this probe runs BEFORE courses.builder_open exists.

    Task 0 has to capture the baseline on today's code; importing helpers that
    Tasks 1 and 4 create would make the BEFORE run impossible.
    """
    return {
        n.pk
        for kids in cmap.values()
        for n in kids
        if n.kind != ContentNode.Kind.UNIT
    }


def _descendants(cmap, ids):
    """Local copy of _open_descendants, same reason."""
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

    for pk in ids:
        walk(pk)
    return out


def _run():
    settings.DEBUG = True
    reset_queries()
    course = Course.objects.get(slug=SLUG)
    cmap = _children_map(course)
    containers = _containers(cmap)
    ids = (
        containers
        if OPEN == "all"
        else {int(t) for t in OPEN.split(",") if t.strip().isdigit()}
    )
    # open_ids must be supplied: after Task 3 the template branches on it, and
    # Django's smartif swallows the resulting TypeError (verified: `{% if 5 in
    # nothing %}` renders the else-branch), so omitting it renders SILENTLY
    # COLLAPSED rather than failing loudly -- which would make every "after"
    # number look like a huge win for the wrong reason.
    ctx = {
        "scope_id": "top",
        "scope_updated": course.updated.isoformat(),
        "parent_kind": None,
        "nodes": cmap.get(None, []),
        "children_map": cmap,
        "course": course,
        "open_ids": ids,
        "open_joined": ",".join(str(p) for p in sorted(ids)),
        "open_descendants": _descendants(cmap, ids),
        "builder_url": f"/manage/courses/{course.slug}/build/",
    }
    render_to_string("courses/manage/_scope.html", ctx)  # warm the template
    t0 = time.perf_counter()
    html = render_to_string("courses/manage/_scope.html", ctx)
    dt = (time.perf_counter() - t0) * 1000
    tags = Counter(t.lower() for t in re.findall(r"<([a-zA-Z][a-zA-Z0-9-]*)", html))
    print(f"slug={SLUG} open={OPEN}")
    print(f"  nodes in course : {sum(len(v) for v in cmap.values())}")
    print(f"  open scopes     : {len(ids)}")
    print(f"  warm render     : {dt:.1f} ms")
    print(f"  bytes           : {len(html)} ({len(html) / 1048576:.2f} MB)")
    print(f"  open tags       : {sum(tags.values())}")
    print(f"  rows            : {tags.get('li', 0)}")
    print(f"  queries         : {len(connection.queries)}")


_run()
```

- [ ] **Step 2: Write the browser probe**

Create `scripts/perf/probe_browser.py`:

```python
"""Measure the real builder page in Chromium.

PREREQUISITES -- none of these are automatic:
  1. A dev database containing the course (default slug: mat-pp).
  2. `uv run python manage.py runserver` on 127.0.0.1:8000.
  3. A session cookie for a user who can manage that course. Mint one with:

       uv run python manage.py shell -c \
         "exec(open('scripts/perf/probe_browser.py').read())" -- --mint-session

Usage:
    SESSION=<key> uv run python scripts/perf/probe_browser.py
"""

import json
import os
import sys
import time

BASE = os.environ.get("BASE", "http://127.0.0.1:8000")
SLUG = os.environ.get("SLUG", "mat-pp")
SESSION = os.environ.get("SESSION", "")


def mint_session():
    """Run INSIDE `manage.py shell`. Prints a session key for the first
    superuser."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.contrib.sessions.backends.db import SessionStore

    user = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
    store = SessionStore()
    store["_auth_user_id"] = str(user.pk)
    store["_auth_user_backend"] = settings.AUTHENTICATION_BACKENDS[0]
    store["_auth_user_hash"] = user.get_session_auth_hash()
    store.create()
    print("SESSION", store.session_key)


def measure():
    from playwright.sync_api import sync_playwright

    if not SESSION:
        sys.exit("set SESSION=<key> (see --mint-session in this file's docstring)")
    url = f"{BASE}/manage/courses/{SLUG}/build/"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        ctx.add_cookies(
            [{"name": "sessionid", "value": SESSION, "domain": "127.0.0.1", "path": "/"}]
        )
        page = ctx.new_page()
        t0 = time.perf_counter()
        resp = page.goto(url, wait_until="load", timeout=180000)
        wall = time.perf_counter() - t0
        stats = page.evaluate(
            """() => {
              const nav = performance.getEntriesByType('navigation')[0] || {};
              const els = document.getElementsByTagName('*').length;
              const rows = document.querySelectorAll('.tree__row').length;
              return {elements: els, rows: rows,
                      per_row: rows ? +(els / rows).toFixed(1) : null,
                      ttfb_ms: Math.round(nav.responseStart - nav.requestStart),
                      domInteractive_ms: Math.round(nav.domInteractive),
                      transferKB: Math.round((nav.transferSize || 0) / 1024)};
            }"""
        )
        stats["http"] = resp.status
        stats["wall_s"] = round(wall, 2)
        print(json.dumps(stats, indent=2))
        browser.close()


if "--mint-session" in sys.argv:
    mint_session()
elif __name__ == "__main__":
    measure()
```

- [ ] **Step 3: Document the prerequisites**

Create `scripts/perf/README.md` recording: which database the probes expect, that `mat-pp`
must exist in it, that `probe_browser.py` needs `runserver` plus a minted session key, and
that the two probes report on **different bases** (the offline render has no CSRF inputs;
the browser count does) so post-change numbers must be compared like for like.

- [ ] **Step 4: Capture the BEFORE numbers**

```bash
SLUG=mat-pp OPEN=all uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
```
Expected (matching the spec's baseline): ~3.1 s warm, ~2.6 MB, and **1 query**
(`_children_map` runs after `reset_queries()`; `course.nodes.all()` populates
`_known_related_objects`, so `node.course.slug` in the row template costs nothing more). Record the
output — every later comparison is against this run, on this machine.

> The probe imports nothing this plan creates, so it runs on today's code. `open_ids` is in
> its context from the start: before Task 3 the template ignores the key, after it the key is
> load-bearing — and because smartif swallows the error, a missing key would show up as a
> spuriously fast render rather than a crash.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add scripts/perf/
git commit -m "chore(perf): commit the builder measurement probes"
```

---

### Task 0b: Enumerate the affected tests BEFORE changing behaviour

The spec calls the suite migration "a first-class work item, not cleanup" that must be
"enumerated file by file **before implementation starts**". Doing it after Task 3 means
Tasks 6–10 each commit against a knowingly red suite, where a real regression is
indistinguishable from expected fixture breakage.

**Files:**
- Create: `docs/superpowers/plans/affected-tests.md`

- [ ] **Step 1: Sweep**

```bash
grep -rln "manage_builder\|/build/\|data-scope\|tree__row\|data-panel-url\|data-node-move-url" tests/ | sort
```

A file-name prefix is not a reliable filter — four files were missed that way. Expect at
least: `test_manage_builder.py`, `test_manage_node_ops.py`, `test_manage_affordance.py`,
`test_manage_node_duplicate.py`, `test_manage_duplicate_button.py`, `test_tree_badge.py`,
`test_seed_demo_course.py`, `test_e2e_builder.py`, `test_e2e_builder_ws2.py`,
`test_e2e_builder_authoring.py`, `test_e2e_builder_reorder.py`,
`test_e2e_builder_tree_layout.py`, `test_e2e_inline_rename.py`, `test_e2e_transfer.py`,
`test_builder_styles.py`, `test_builder_js_invariants.py`.

- [ ] **Step 2: Record the baseline and classify each file**

```bash
uv run pytest tests/ -q ; echo "unit exit=$?"
uv run pytest tests/ -q -m e2e ; echo "e2e exit=$?"
```

Both must be **green now**. Write `affected-tests.md` with one row per file: its seeded node
count, whether that is above or below `SIZE_THRESHOLD` (150), and the expected treatment —
`open=all` param, `expand_to()`, re-measure, or *encodes a behaviour change*.

Flag every file under the threshold explicitly. Those keep passing untouched, which is a
**trap**: such a test no longer exercises the lazy path at all. At least one test per
behaviour must seed above the threshold.

- [ ] **Step 3: Commit**

```bash
git branch --show-current
git add docs/superpowers/plans/affected-tests.md
git commit -m "docs(builder): enumerate the tests the lazy-tree change will touch"
```

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
    """part > chapter > unit, plus a childless chapter (the `pk in cmap` trap).

    4 nodes, i.e. UNDER SIZE_THRESHOLD -- so on a page load this course takes
    precedence step 4 and opens fully. Use `big_tree` for anything that must
    reach step 5.
    """
    course = CourseFactory(slug="c1")
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=part, title="C")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    empty = ContentNodeFactory(course=course, kind="chapter", parent=part, title="E")
    return course, part, chapter, unit, empty


@pytest.fixture
def big_tree(db, monkeypatch):
    """The same shape, but forced OVER the threshold so steps 5/6 are reachable.

    Monkeypatching the constant beats seeding 151 rows: the rule under test is
    "len(index) <= SIZE_THRESHOLD", and a 4-node fixture with a threshold of 2
    exercises it identically at a fraction of the cost.
    """
    monkeypatch.setattr("courses.builder_open.SIZE_THRESHOLD", 2)
    course = CourseFactory(slug="c2big")
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
def test_absent_vs_empty_on_a_page_load(rf, big_tree):
    """Absent seeds from the session; empty means 'I collapsed everything'.

    big_tree, not tree: under the threshold step 4 fires first and this would
    assert the size rule while claiming to test the seed.
    """
    course, part, chapter, unit, _e = big_tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c2big": unit.pk}}
    absent = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    assert absent.ids == frozenset({part.pk, chapter.pk})
    empty = open_ids(_req(rf, "open=", session=sess), course, cmap, mode="page")
    assert empty.ids == frozenset()


@pytest.mark.django_db
def test_seed_includes_the_node_itself_when_it_is_a_container(rf, big_tree):
    course, part, chapter, _u, _e = big_tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c2big": chapter.pk}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    # the chapter ITSELF, not just its ancestors -- otherwise the author
    # returns with the very chapter they were working in closed
    assert got.ids == frozenset({part.pk, chapter.pk})


@pytest.mark.django_db
def test_fragment_mode_never_seeds_and_skips_the_size_rule(rf, tree):
    """`tree` deliberately: 4 nodes IS under the threshold, and a fragment
    must still come back empty -- step 4 is a landing rule for a page."""
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
    course, part, chapter, _u, empty = tree
    cmap = _children_map(course)
    stored = {"builder_open": {"c1": [chapter.pk]}}
    got = open_ids(_req(rf, "open=session", session=stored), course, cmap, mode="page")
    assert got.ids == frozenset({chapter.pk})
    # MISSING key -> fall through to steps 3-6 (here: the size rule)
    got2 = open_ids(_req(rf, "open=session", session={}), course, cmap, mode="page")
    assert got2.ids == frozenset({part.pk, chapter.pk, empty.pk})


@pytest.mark.django_db
def test_open_session_honours_a_stored_EMPTY_list(rf, tree):
    """Stored-empty is 'I collapsed everything' and must NOT fall through.

    `.get(slug) or []` conflates missing with empty: the author's collapsed
    state would spring back open on the next no-JS mutation, and the derived
    set would then be persisted over it -- permanently.
    """
    course, _p, _c, _u, _e = tree
    cmap = _children_map(course)
    stored = {"builder_open": {"c1": []}}
    got = open_ids(_req(rf, "open=session", session=stored), course, cmap, mode="page")
    assert got.ids == frozenset()


@pytest.mark.django_db
def test_post_open_beats_get_open(rf, tree):
    course, part, chapter, _u, _e = tree
    cmap = _children_map(course)
    r = rf.post("/?open=" + str(part.pk), data={"open": str(chapter.pk)})
    r.session = {}
    assert open_ids(r, course, cmap).ids == frozenset({chapter.pk})


@pytest.mark.django_db
def test_ceiling_keeps_the_lowest_pks_and_flags_truncation(rf, db, monkeypatch):
    """Monkeypatch the ceiling rather than seeding 505 rows: the rule under
    test is `len(kept) > CEILING`, and 6 rows exercise it identically."""
    monkeypatch.setattr("courses.builder_open.CEILING", 4)
    course = CourseFactory(slug="ceil")
    parts = [
        ContentNodeFactory(course=course, kind="part", parent=None, title=f"p{i}")
        for i in range(6)
    ]
    cmap = _children_map(course)
    got = open_ids(_req(rf, "open=all"), course, cmap, mode="page")
    assert got.truncated is True
    assert len(got.ids) == 4
    assert got.ids == frozenset(sorted(p.pk for p in parts)[:4])


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
uv run pytest tests/test_builder_open_ids.py -q ; echo "exit=$?"
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
    explicit: bool = False  # resolved by step 1 or 2 -> safe to persist


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


def _finalize(ids, containers, *, explicit=False):
    """Sanitise against this course's containers, then apply the one ceiling.

    Truncation keeps the LOWEST pks: a set has no truncation order, and the
    outcome has to be reproducible across runs for the guard test to mean
    anything.
    """
    kept = set(ids) & containers
    if len(kept) > CEILING:
        return OpenSet(frozenset(sorted(kept)[:CEILING]), True, explicit)
    return OpenSet(frozenset(kept), False, explicit)


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


_MISSING = object()


def _stored_open(request, slug):
    """Returns _MISSING when the key is absent, the (possibly EMPTY) list
    otherwise.

    `.get(slug) or []` would conflate the two, and stored-empty is meaningful:
    it is how "I collapsed everything" survives a no-JS mutation. Conflated,
    the tree springs back open and _remember_open then writes that derived set
    over the author's real one.
    """
    return request.session.get(OPEN_KEY, {}).get(slug, _MISSING)


def open_ids(request, course, cmap, *, mode="fragment", q_chain=None):
    """Resolve the open set. `mode` is one of "page" | "notice" | "fragment".

    Steps run per mode (spec section 2):
      page     -> 1, 2, 3, 4, 5, 6
      notice   -> 2, 3, 4, 5, 6 + a direct builder_open read
      fragment -> 2, 3, 6 only  (never touches the session; the size rule is a
                  LANDING rule for a page, not a rule about a re-render)

    `.explicit` on the result records whether step 1 or 2 resolved it, so
    _remember_open can persist ONLY author-chosen sets. Keying that off the
    raw presence of the parameter would persist the derived fall-through of
    `open=session`.
    """
    index = nodes_by_pk(cmap)
    containers = {pk for pk, n in index.items() if n.kind != ContentNode.Kind.UNIT}
    raw, present = _raw_open(request)

    # Step 1 -- the no-JS post-mutation sentinel, page mode only.
    if present and raw == "session" and mode == "page":
        stored = _stored_open(request, course.slug)
        if stored is not _MISSING:
            return _finalize(stored, containers, explicit=True)
        present = False  # missing/flushed -> fall through to 3-6

    # Step 2 -- an explicit value wins, including the empty string.
    if present:
        return _finalize(_parse(raw, containers), containers, explicit=True)

    # A no-JS conflict/validation re-render is the same author, same tab,
    # mid-loop -- it cannot be a bookmark, so reading the carrier is safe and
    # keeps a FAILED mutation showing the same tree as a successful one.
    if mode == "notice":
        stored = _stored_open(request, course.slug)
        if stored is not _MISSING:
            # explicit=False: safe to RENDER from, not safe to write back.
            # Marking it True would hand a future caller a wrong
            # "author chose this" signal.
            return _finalize(stored, containers, explicit=False)

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
uv run pytest tests/test_builder_open_ids.py -q ; echo "exit=$?"
```
Expected: exit=0. (Do not assert a test COUNT — every count in an
earlier draft was wrong, and a mismatched number invites 'fixing' it by deleting a test.)

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

Add the four imports **to the top of `tests/test_builder_open_ids.py`** with the existing
import block (ruff selects `E`, so `E402` rejects a mid-file import; isort here is
`force-single-line`, one per line):

```python
from django.urls import reverse

from courses.builder_open import LAST_NODE_KEY
from courses.builder_open import SESSION_SLUG_LIMIT
from courses.views_manage import remember_node
from tests.factories import make_login
```

Then append the tests:

```python
class FakeSession(dict):
    """A dict that also carries `modified`, like SessionBase.

    A plain dict cannot: `dict` forbids attribute assignment, so
    `request.session.modified = True` raises AttributeError.
    """

    modified = False


class FakeRequest:
    def __init__(self):
        self.session = FakeSession()


@pytest.mark.django_db
def test_node_panel_records_the_focused_node(client, tree):
    course, part, _c, _u, _e = tree
    course.owner = make_login(client, "owner")
    course.save(update_fields=["owner"])
    client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": part.pk})
    )
    assert client.session[LAST_NODE_KEY]["c1"] == part.pk


def test_remember_node_bounds_slugs_and_moves_recent_to_the_end():
    r = FakeRequest()
    for i in range(SESSION_SLUG_LIMIT + 5):
        remember_node(r, f"s{i}", i)
    assert len(r.session[LAST_NODE_KEY]) == SESSION_SLUG_LIMIT
    # Re-writing an OLD slug must move it to the end, or "most recent" is a
    # lie: dicts keep INSERTION order and re-assigning a key does not re-order.
    oldest = next(iter(r.session[LAST_NODE_KEY]))
    remember_node(r, oldest, 999)
    assert next(iter(r.session[LAST_NODE_KEY])) != oldest
    assert list(r.session[LAST_NODE_KEY])[-1] == oldest


def test_remember_node_skips_an_unchanged_write():
    r = FakeRequest()
    remember_node(r, "s", 1)
    assert r.session.modified is True
    r.session.modified = False
    remember_node(r, "s", 1)      # same value -> no write
    assert r.session.modified is False
    remember_node(r, "s", 2)      # changed -> writes
    assert r.session.modified is True
```

> The assertions are on `r.session.modified`, **not** `r.modified`: the implementation
> writes the flag on the session, so asserting on the request object would inspect
> something nothing under test touches and could never go red.

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
uv run pytest tests/test_builder_open_ids.py -q ; echo "exit=$?"
```
Expected: exit=0.

- [ ] **Step 5: Falsify the skip-when-unchanged rule**

Delete the `if store.get(slug) == pk: return` early exit and re-run.
Expected: `test_remember_node_skips_an_unchanged_write` goes **RED**. Restore it. If it
stays green, the assertion is inspecting the wrong object — fix that before continuing.

- [ ] **Step 6: Commit**

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
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from django.http import Http404
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
def test_builder_tree_query_count_does_not_grow_with_open_scopes(client):
    """The spec's query-count invariant. Compare the SAME page collapsed vs
    fully expanded: the tree path is one query either way, so any delta means
    an N+1 crept into _open_descendants, _extra_container_pks or the toggle."""
    from django.test.utils import CaptureQueriesContext
    from django.db import connection

    owner = make_login(client, "owner")
    _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    client.get(url)  # warm sessions/auth so the two counts are comparable
    with CaptureQueriesContext(connection) as collapsed:
        client.get(f"{url}?open=")
    with CaptureQueriesContext(connection) as expanded:
        client.get(f"{url}?open=all")
    assert len(expanded) == len(collapsed), (
        f"expanded={len(expanded)} collapsed={len(collapsed)}; "
        "an N+1 was introduced in the tree path"
    )


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
    row = re.search(r'data-node="%d".*?</div>' % part.pk, html, re.S).group(0)
    assert f'data-toggle="{part.pk}"' in row
    assert 'aria-expanded="false"' in row
    assert "aria-controls" not in row          # invalid ARIA while collapsed
    # Assert the WHOLE label. `str(len(chapters)) in row` is vacuous: with 30
    # chapters, "30" also appears inside data-updated timestamps, maxlength
    # and pks, so it can never fail.
    assert f'aria-label="Expand P0, {len(chapters)} items"' in row


@pytest.mark.django_db
def test_truncation_renders_a_keyed_info_entry(client, monkeypatch):
    """The ceiling is slice 1, so its user-visible consequence must be too."""
    monkeypatch.setattr("courses.builder_open.CEILING", 2)
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"}) + "?open=all"
    ).content.decode()
    assert 'data-info-key="truncation"' in html
    assert 'role="status"' in html


@pytest.mark.django_db
def test_a_collapsed_container_with_zero_children_still_toggles(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    empty = ContentNodeFactory(
        course=course, kind="chapter", parent=part, title="Empty"
    )
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk}").content.decode()
    assert f'data-toggle="{empty.pk}"' in html
    opened = client.get(f"{url}?open={part.pk},{empty.pk}").content.decode()
    assert f'data-scope="{empty.pk}"' in opened
    # the add affordance lives INSIDE the scope, so it appears only when open
    assert f'data-add-scope="{empty.pk}"' in opened


@pytest.mark.django_db
def test_adding_a_unit_does_not_change_the_open_set(client):
    """extra_open's effect 1 drops unit pks; effect 2 (slice 2) keeps them."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "big"}),
        {
            "parent": ch.pk,
            "parent_token": ch.updated.isoformat(),
            "unit_type": "lesson",
            "title": "New unit",
            "open": f"{part.pk},{ch.pk}",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    new = course.nodes.get(title="New unit")
    html = resp.content.decode()
    assert f'data-node="{new.pk}"' in html        # the row is there
    assert f'data-scope="{new.pk}"' not in html   # a unit owns no scope


@pytest.mark.django_db
def test_render_scope_rejects_a_non_numeric_scope_ref():
    """The real hazard the routing-level 404 test does NOT cover: <int:pk>
    stops a bad pk at the resolver, but _render_scope is also called
    internally, where int(scope_ref) would raise a 500."""
    from django.test import RequestFactory

    from courses.views_manage import _render_scope

    course = CourseFactory(slug="rs")
    r = RequestFactory().get("/")
    r.session = {}
    with pytest.raises((ValueError, Http404)):
        _render_scope(r, course, "not-a-pk")


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
uv run pytest tests/test_builder_lazy_scopes.py -q ; echo "exit=$?"
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

> The `href="#"` is a placeholder replaced in Task 4 by `{% toggle_href %}`. Both labels are
> rendered server-side because JS cannot select a Polish plural form.
>
> **Byte cost, accepted:** each container row now carries the title three extra times
> (`aria-label` plus both `data-label-*`), and on the expanded branch `data-label-collapse`
> duplicates `aria-label` exactly. On `mat-pp` that is 137 containers × up to ~200 chars ×
> 3 ≈ 80 KB *only when everything is open* — the collapsed default renders 21 rows, so the
> "< 300 KB" target is unaffected. Task 3 Step 11's `OPEN=all` run measures the real figure;
> if it is worse than this estimate, drop `aria-label` and have the JS set it from
> `data-label-*` on init instead.

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

In `courses/views_manage.py` add the imports (one per line — isort here is
`force-single-line`) and update three functions:

```python
from courses.builder_open import CEILING
from courses.builder_open import container_pks
from courses.builder_open import open_ids as _open_ids
```

`gettext as _` is already imported in this module; `CEILING` and `container_pks` are not.

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

- [ ] **Step 7b: Show the complete `_render_scope`**

`_render_scope` has a `top`-vs-pk branch, so paste the whole post-edit function rather than
patching around an ellipsis — and note it computes `cmap` **once**:

```python
def _render_scope(request, course, scope_ref, *, extra_open=()):
    """Re-render a single scope <ol> (root carries data-scope). scope_ref is a parent
    pk or 'top'. Used for 200 success and 409 fresh-fragment on single-scope ops."""
    cmap = _children_map(course)
    opened = _open_ids(request, course, cmap, mode="fragment")
    ids = set(opened.ids) | _extra_container_pks(extra_open, cmap)
    if scope_ref == "top":
        nodes, updated, parent_kind = (
            cmap.get(None, []),
            course.updated.isoformat(),
            None,
        )
    else:
        parent = ContentNode.objects.filter(pk=scope_ref, course=course).first()
        nodes = cmap.get(int(scope_ref), [])
        updated = parent.updated.isoformat() if parent else course.updated.isoformat()
        parent_kind = parent.kind if parent else None
    context = {
        "scope_id": scope_ref,
        "scope_updated": updated,
        "parent_kind": parent_kind,
        "nodes": nodes,
        "children_map": cmap,
        "course": course,
    }
    context.update(_tree_context(course, cmap, ids))   # added in Task 4
    return render(request, "courses/manage/_scope.html", context)
```

> Until Task 4 exists, use `context["open_ids"] = ids` in place of the `_tree_context` line.

- [ ] **Step 8: Render the info slot**

In `templates/courses/manage/builder.html`, **inside `.builder__tree`, immediately above the
`_scope.html` include** (line 22) — not next to `notice`, which sits *outside*
`<section class="builder">` and so outside the element `builder.js` binds as `root`. Slice 2
requires the JS to read this slot on init, and the BEM name already claims membership:

```html
{% if info %}<ul class="builder__info" role="status">{% for entry in info %}<li data-info-key="{{ entry.key }}">{{ entry.text }}</li>{% endfor %}</ul>{% endif %}
```

and in `builder.css`:

```css
.builder__info { list-style: none; margin: 0 0 var(--space-3); padding: var(--space-2) var(--space-3);
  background: var(--surface-sunken); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: .875rem; }
```

> No `:empty` rule: the `{% if info %}` means an empty `<ul>` is never emitted server-side,
> and slice 1 has no JS that empties the list. Slice 2's `info` renderer adds it.

- [ ] **Step 9: Run the tests to verify they pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q ; echo "exit=$?"
```
Expected: exit=0.

- [ ] **Step 10: Falsify the headline guard**

Delete the `{% if node.pk in open_ids %}` wrapper in `_tree_node.html`, re-run, and confirm `test_collapsed_scope_emits_no_descendant_rows` goes **RED**. Restore it.

- [ ] **Step 11: Measure the real win, and the cost of the new context work**

```bash
# The seeded worst case: top level plus one 4-deep chain.
SLUG=mat-pp OPEN="" uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
# And the fully-expanded case, to bound expand-all and price _open_descendants.
SLUG=mat-pp OPEN=all uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
```

Expected: with `OPEN=""` the render drops from ~3.1 s / 2.58 MB (Task 0 Step 4) to well
under 500 ms. Record **both** runs. The `OPEN=all` figure is the one that prices
`_open_descendants` + `open_joined` — if the gap between it and the Task 0 baseline is
larger than the reversal hoist will recover (~24%, Task 10), say so now rather than
discovering it at Task 12.

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

Add `from urllib.parse import parse_qs, urlparse` to the file's import block, then:

```python
def _toggle_open_pks(html, pk):
    """The `open` pks in the toggle href for `pk`, as a set of ints.

    Parses rather than substring-matching: comma-joined pks are
    prefix-colliding, so `str(31) not in "1,131"` is both wrong and the exact
    trap toggle_href itself is written to avoid. The regex is anchored on the
    emitted attribute ORDER (class, href, data-toggle) -- reversing it makes
    the match silently fail, and an `assert m is None or ...` would then pass
    on the miss.
    """
    m = re.search(r'<a class="tree__toggle" href="([^"]+)"[^>]*data-toggle="%d"' % pk, html)
    assert m, f"no toggle href found for pk={pk}"
    qs = parse_qs(urlparse(m.group(1)).query)
    raw = (qs.get("open") or [""])[0]
    return {int(t) for t in raw.split(",") if t.strip().isdigit()}


@pytest.mark.django_db
def test_expand_href_adds_this_pk_to_the_open_set(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"})
    ).content.decode()
    assert _toggle_open_pks(html, part.pk) == {part.pk}


@pytest.mark.django_db
def test_collapse_href_drops_this_pk_AND_its_open_descendants(client):
    """Collapse must forget descendants, or the no-JS path diverges from the
    JS path (which forgets them automatically by removing the subtree)."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk},{ch.pk}").content.decode()
    # the part is expanded, so its toggle is a COLLAPSE href
    assert _toggle_open_pks(html, part.pk) == set()
    # and the chapter's own toggle (also expanded) only drops itself
    assert _toggle_open_pks(html, ch.pk) == {part.pk}


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
uv run pytest tests/test_builder_lazy_scopes.py -q -k "href or anchor"
```
Expected: **all three FAIL**. `_toggle_open_pks` asserts the match is found and then parses
the query string, so `href="#"` fails on the empty `open` set rather than passing on a
missed regex; `test_toggle_href_carries_a_row_anchor` fails on the missing `id`.

- [ ] **Step 3: Implement the tag**

**Add only `from django.utils.http import urlencode`** to the file's existing top import
block. `django.template` is already imported and **`register` is already bound at
`courses_manage_extras.py:23`** — re-assigning it would create a *new, empty* `Library`, so
Django's `import_library` would read that one and every existing tag and filter
(`get_item`, `legal_child_kinds`, `primary_child_kind`, `kind_label`, …) would vanish.
`_tree_node.html` would then die with `Invalid filter: 'get_item'` and take the whole builder
with it. Do **not** paste a `register = template.Library()` line.

Then append the tag:

```python
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

    # Only OPEN containers need an entry: a collapsed row's toggle is an
    # EXPAND href, which uses the open_joined fast path and never consults
    # this map. Walking every container instead would add a full-cmap pass to
    # the toggle endpoint, whose budget is < 300 ms.
    for pk in ids:
        walk(pk)
    return out


def _tree_context(course, cmap, ids):
    """Keys every renderer of tree markup must supply, or toggle_href silently
    sees nothing on fragment renders. Takes no `request`: everything it needs
    is already resolved."""
    return {
        "open_ids": ids,
        "open_joined": ",".join(str(p) for p in sorted(ids)),
        "open_descendants": _open_descendants(cmap, ids),
        "builder_url": reverse(
            "courses:manage_builder", kwargs={"slug": course.slug}
        ),
    }
```

Merge it into all three context dicts, replacing the bare `"open_ids"` key added in Task 3.
**Each call site has a different local name for the set** — pasting one expression into all
three raises `NameError`, the same hazard Task 6 flags for `_persist_chain`:

```python
# builder()               -- the OpenSet is `opened`
    context.update(_tree_context(course, cmap, opened.ids))

# _builder_with_notice()  -- likewise
    context.update(_tree_context(course, cmap, opened.ids))

# _render_scope()         -- the post-extra_open local is `ids`
    context.update(_tree_context(course, cmap, ids))
```

**Then measure it.** `_open_descendants` runs on every fragment, including the toggle
endpoint whose budget is < 300 ms, on top of the `cmap` rebuild already priced at 89 ms. The
walk is restricted to open containers (above), so Task 3 Step 11's `OPEN=all` run is the
upper bound. If the delta against the Task 0 baseline exceeds what Task 10 recovers (~24%),
narrow `_render_scope`'s `cmap` rebuild — the mitigation the spec sanctions.

- [ ] **Step 5: Use the tag and add the row anchor**

In `_tree_node.html`: add `id="node-{{ node.pk }}"` to the `<li class="tree__row" …>` open tag, and replace both `href="#"` occurrences with `href="{% toggle_href node True %}"` (expanded branch) and `href="{% toggle_href node False %}"` (collapsed branch). Add `courses_manage_extras` to the `{% load %}` line if not already there (it is).

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q ; echo "exit=$?"
```
Expected: exit=0.

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
uv run pytest tests/test_builder_lazy_scopes.py -q ; echo "exit=$?"
```
Expected: exit=0.

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


@pytest.mark.django_db
def test_no_js_add_carries_the_ANCESTOR_CHAIN_not_a_bare_pk(client):
    """Falsifies _persist_chain's central rule.

    With the session cleared, a bare [new_pk] is non-empty -- so `open=session`
    would NOT fall through, and the tree would render with every ancestor
    collapsed, hiding the node just created. Replace _ancestor_chain(node) with
    {node.pk} and this must go RED.
    """
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    session = client.session
    session.pop(OPEN_KEY, None)
    session.save()
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "big"}),
        {
            "parent": ch.pk,
            "parent_token": ch.updated.isoformat(),
            "kind": "section",
            "title": "Deep",
        },
    )
    assert "open=session" in resp["Location"]
    html = client.get(resp["Location"]).content.decode()
    new = course.nodes.get(title="Deep")
    assert f'data-node="{new.pk}"' in html      # visible, so the chain came too
    assert f'data-scope="{ch.pk}"' in html      # its parent is open


@pytest.mark.django_db
def test_no_js_reparent_via_the_picker_persists_the_destination_chain(client):
    """The picker exists for destinations the author cannot see; the no-JS half
    is the one with the reparent-capture ordering hazard."""
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
        },
    )
    assert "open=session" in resp["Location"]
    assert dest.pk in client.session[OPEN_KEY]["big"]
    html = client.get(resp["Location"]).content.decode()
    assert f'data-node="{unit.pk}"' in html


@pytest.mark.django_db
def test_builder_response_stays_small_and_shallow(client):
    """The spec calls this 'the test that actually guards this regression from
    coming back'. Ceilings are derived from Task 3 Step 11's measurement; raise
    them only with a measurement that justifies it.
    """
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "big"}))
    html = resp.content.decode()
    assert html.count('class="tree__row"') <= 5      # top level only
    assert len(resp.content) < 120_000


@pytest.mark.django_db
def test_open_session_falling_through_does_not_persist_the_derived_set(client):
    """The case `"open" in request.GET` gets wrong.

    The parameter IS present, but the resolved set came from the size rule /
    seed. Gating on raw presence would overwrite the author's real set here.
    """
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    session = client.session
    session.pop(OPEN_KEY, None)
    session.save()
    client.get(f"{url}?open=session")
    assert OPEN_KEY not in client.session or "big" not in client.session.get(
        OPEN_KEY, {}
    )
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


def _remember_open(request, course, opened):
    """Persist ONLY an author-chosen open set (precedence steps 1-2).

    Gated on opened.explicit, NOT on `"open" in request.GET`. The two differ
    exactly where it matters: `?open=session` with the key missing or flushed
    sets `present` internally to False and falls through to steps 4-6, so the
    parameter IS in the querystring while the resolved set is derived. Keying
    off raw presence would write that derived set over the author's real one,
    permanently.
    """
    if not opened.explicit:
        return
    remember_node(request, course.slug, sorted(opened.ids), key=OPEN_KEY)
```

In `builder()`, after computing `opened`:

```python
    _remember_open(request, course, opened)
```

Change **five** of the six no-JS redirects — `views_manage.py:282`, `:344`, `:376`, `:411`,
`:494`. **Leave `:455` (`node_delete`) alone**: Task 7 rewrites that one into a branch that
round-trips an explicit `open`, and changing it here only to supersede it two tasks later
invites keeping the wrong version through a conflict. Change them from

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

For the no-JS branches, persist the chain **before** redirecting. Add `from
courses.builder_open import OPEN_KEY` to the import block, then one helper:

```python
def _persist_chain(request, course, node):
    """Union a created/moved node's chain into the no-JS carrier.

    The CHAIN, not the bare pk: if builder_open happens to be missing, a bare
    [new_pk] is non-empty, so the open=session read would NOT fall through and
    the tree would render with every ancestor collapsed -- hiding the node the
    author just created.
    """
    cmap = _children_map(course)
    stored = request.session.get(OPEN_KEY, {}).get(course.slug) or []
    merged = set(stored) | (_ancestor_chain(node) & container_pks(cmap))
    remember_node(request, course.slug, sorted(merged), key=OPEN_KEY)
```

Then call it with **each view's own local name** — they differ, and pasting one snippet
into all three either raises `NameError` or silently persists the wrong chain:

```python
# node_add            -- the created node is `node`
    if not _wants_fragment(request):
        _persist_chain(request, course, node)
        return _redirect_to_builder(course)

# node_duplicate      -- the created node is `new_node`; `node` is the SOURCE
    if not _wants_fragment(request):
        _persist_chain(request, course, new_node)
        return _redirect_to_builder(course)

# node_move, reparent -- requires the capture edit above; today this branch
#                        discards reparent_node's return entirely
    if not _wants_fragment(request):
        _persist_chain(request, course, node)
        return _redirect_to_builder(course)
```

> **Ordering:** in `node_move` the "capture the node returned by `reparent_node`" edit is a
> prerequisite of this one. Apply it first, or `node` is undefined in that branch.

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q ; echo "exit=$?"
```
Expected: exit=0.

- [ ] **Step 5: Check against the Task 0b enumeration — the gate is bounded**

```bash
uv run pytest tests/ -q ; echo "exit=$?"
```

Expected: **only files listed in `docs/superpowers/plans/affected-tests.md` (Task 0b) may
fail.** Anything else failing is a regression introduced by this task, not expected fixture
breakage — stop and fix it before committing. Without this bound, a real defect introduced
in Task 6, 8, 9 or 10 is indistinguishable from migration noise until Task 11.

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
- Modify: `courses/views_manage.py` (`node_delete`), `templates/courses/manage/node_confirm_delete.html`, `courses/static/courses/js/builder.js`
- Test: `tests/test_builder_lazy_scopes.py` (append), `tests/test_e2e_builder_toggle.py` (append)

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

- [ ] **Step 3: Add the missing import**

`courses/views_manage.py` imports nothing from `django.utils.http`. Add to its top import
block:

```python
from django.utils.http import urlencode
```

(Task 4's `urlencode` went into `courses_manage_extras.py`, a different module.)

- [ ] **Step 4: Implement the server half**

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

- [ ] **Step 5: Implement the JS half — without it, EVERY JS author still loses the tree**

The server half above only helps if `open` reaches the confirm GET, and the delete link
(`_tree_node.html:40`) carries none. Add to `builder.js`, near the `[data-move]` handler:

```js
  // The delete link is a plain navigation for everyone -- node_confirm_delete's
  // form has no data-op and there is no [data-delete] fetch handler. So stamp
  // the LIVE open set onto the href at click time and let the navigation
  // proceed: no preventDefault.
  root.addEventListener("click", function (e) {
    var del = e.target.closest("[data-delete]");
    if (!del) return;
    var u = new URL(del.getAttribute("href"), window.location.origin);
    u.searchParams.set("open", collectOpen());
    del.setAttribute("href", u.pathname + u.search);
  });
```

> No change to `_tree_node.html` is needed — the handler rewrites the existing href in
> place. (Task 7's Files list is corrected accordingly.)

- [ ] **Step 6: Test the JS half end to end**

Append to `tests/test_e2e_builder_toggle.py`:

```python
def test_deleting_a_node_preserves_the_expanded_tree(page, live_server):
    owner = _make_pa_user("pa")
    course, part, ch, unit = _seed(owner, slug="del")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "del"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    page.click(f'[data-toggle="{ch.pk}"]')            # expand a second level
    page.wait_for_selector(f'ol[data-scope="{ch.pk}"]')
    page.click(f'[data-node="{unit.pk}"] a[data-delete]')
    page.wait_for_selector("form[action*='delete']")
    page.click("form[action*='delete'] button[type='submit']")
    # back on the builder: BOTH scopes still open
    page.wait_for_selector(f'ol[data-scope="{ch.pk}"]')
```

- [ ] **Step 7: Run to verify pass**

```bash
uv run pytest tests/test_builder_lazy_scopes.py -q -k delete ; echo "exit=$?"
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e -k delet ; echo "exit=$?"
```
Expected: exit=0 for both.

- [ ] **Step 8: Commit**

```bash
git branch --show-current
uv run ruff format . && uv run ruff check .
git add courses/views_manage.py templates/courses/manage/node_confirm_delete.html \
        courses/static/courses/js/builder.js tests/
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
import os

import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    """Every e2e module in this repo defines this (74 of them). Fixtures
    declared in a test module are module-LOCAL, so a new file inherits
    nothing -- and running this file alone, which Steps 2/5 and Task 9 all
    do, would raise SynchronousOnlyOperation the moment the ORM is touched
    under the sync Playwright greenlet."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _make_pa_user(username):
    """Copied from tests/test_e2e_builder.py -- do NOT hand-roll this.

    UserFactory sets the password to "password123", not TEST_PASSWORD, and
    creates no verified email, so allauth's AccountMiddleware bounces the
    session to verify-email and the login silently never takes.
    """
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    """allauth's field is name="login", not "username", and there is no
    `accounts:login` URL name -- the path is literal. The submit button is
    form-scoped because a bare button[type=submit] hits the shell header's
    language/logout buttons first."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _simulate_drag(page, src_selector, dst_selector, moves=1):
    """Dispatch native HTML5 DnD events.

    Playwright's pointer input (mouse.down/hover/up) and drag_to do NOT fire
    dragstart/dragover/drop in Chromium -- this repo measured that and ships
    this helper in tests/test_e2e_builder_ws2.py for exactly that reason.
    `moves` controls how many dragover events precede the drop: 1 exercises
    the drop-flushes-the-pending-frame path.
    """
    page.evaluate(
        """([srcSel, dstSel, moves]) => {
            const src = document.querySelector(srcSel);
            const dst = document.querySelector(dstSel);
            if (!src || !dst)
                throw new Error('selector not found: ' + srcSel + ' | ' + dstSel);
            const dt = new DataTransfer();
            const s = src.getBoundingClientRect(), d = dst.getBoundingClientRect();
            src.dispatchEvent(new DragEvent('dragstart', {bubbles: true,
                cancelable: true, dataTransfer: dt,
                clientX: s.x + s.width / 2, clientY: s.y + s.height / 2}));
            for (let i = 0; i < moves; i++) {
                dst.dispatchEvent(new DragEvent('dragover', {bubbles: true,
                    cancelable: true, dataTransfer: dt,
                    clientX: d.x + d.width / 2, clientY: d.y + d.height / 2}));
            }
            dst.dispatchEvent(new DragEvent('drop', {bubbles: true,
                cancelable: true, dataTransfer: dt,
                clientX: d.x + d.width / 2, clientY: d.y + d.height / 2}));
            src.dispatchEvent(new DragEvent('dragend', {bubbles: true,
                cancelable: true, dataTransfer: dt}));
        }""",
        [src_selector, dst_selector, moves],
    )


def _seed(owner, slug="e2e"):
    course = CourseFactory(slug=slug, owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="Part A")
    ch = ContentNodeFactory(course=course, kind="chapter", parent=part, title="Chap A")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="Unit A"
    )
    # push the course over SIZE_THRESHOLD so it does NOT auto-expand -- under
    # the threshold every assertion below would pass vacuously
    for i in range(160):
        ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=ch, title=f"U{i}"
        )
    return course, part, ch, unit


def test_toggle_expands_and_collapses(page, live_server):
    owner = _make_pa_user("pa")
    course, part, ch, _unit = _seed(owner)
    _login(page, live_server, "pa")
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
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}")
    page.dblclick(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    assert page.locator(f'ol[data-scope="{part.pk}"]').count() == 1


def test_expansion_survives_a_reload(page, live_server):
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}")
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    page.reload()
    page.wait_for_selector(f'[data-node="{ch.pk}"]')   # replaceState carried it


def test_collapsing_the_last_scope_survives_a_reload(page, live_server):
    """The empty set must be written as `open=` (present, empty), not omitted,
    or the reload re-seeds from the session and springs the tree back open."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner)
    _login(page, live_server, "pa")
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
    // Armed HERE, not around the <ol> removal: a click moves focus at
    // mousedown, so a dirty title's focusout fires BEFORE this handler's click
    // would -- and the rename guard reads `swapping`, which would still be
    // false, so the rename would commit on mouse-collapse but abandon on
    // keyboard-collapse.
    //
    // NARROW to the subtree actually being torn out. Arming for ANY toggle
    // click would swallow an unrelated pending rename: edit row A's title,
    // click row B's toggle, and A's focusout is suppressed while focus has
    // already left it -- the edit is lost silently, with no further commit
    // opportunity.
    var t = e.target.closest("[data-toggle]");
    if (!t) return;
    var row = t.closest("li.tree__row");
    var scope = row && row.querySelector(":scope > ol.tree__scope");
    var active = document.activeElement;
    if (scope && active && scope.contains(active)) swapping = true;
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

Wrap the two existing fetch call sites. **Each needs three edits, not one** — the counter is
a *counter* precisely because a rename commit, a drop and a toggle overlap routinely, and
with only the toggle incrementing it the pane never shows busy during the slowest operation
the spec cares about (the 4.47 s drop):

```js
// --- submit handler ---
    busyStart();                                   // before fetch(
    fetch(form.action, { …, body: withOpen(body) })
      …
      .then(function () { busyEnd(); })            // AFTER the existing .then/.catch chain
```

```js
// --- drop handler ---
    withOpen(body);
    busyStart();                                   // before fetch(
    fetch(root.getAttribute("data-node-move-url"), { … })
      …
      .then(function () { busyEnd(); })
```

`busyEnd()` must run on **both** the success and the failure path in each — a rejected fetch
that skips it leaves the pane stuck busy forever. Add `syncUrl();` inside both `.then` blocks
after `applyFragment(text);`.

Add the per-toggle pending state the spec requires ("it is obvious *which* row is loading"),
in `builder.css`:

```css
.tree__toggle[data-submitting] { opacity: .45; }
.tree__toggle[data-submitting] .ic { animation: builder-spin .7s linear infinite; }
@keyframes builder-spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 4: Style the busy state**

Append to `builder.css`:

```css
/* Visual only. It must NOT set pointer-events:none -- the per-toggle
   in-flight guard is what prevents double activation, and blocking pointer
   events here would make that guard dead code. */
.builder[data-busy] .builder__tree { opacity: .6; transition: opacity .1s ease; cursor: progress; }
```

- [ ] **Step 4b: Add the coverage the spec pins for this task**

Append to `tests/test_e2e_builder_toggle.py`:

```python
def test_a_failed_scope_fetch_leaves_the_row_usable(page, live_server):
    """The in-flight guard clears on BOTH paths, or the row wedges forever."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="fail")
    _login(page, live_server, "pa")
    page.route("**/scope/**", lambda route: route.fulfill(status=500, body=""))
    page.goto(f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'fail'})}")
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(".op-error")
    assert page.locator(".builder[data-busy]").count() == 0   # counter unwound
    page.unroute("**/scope/**")
    page.click(f'[data-toggle="{part.pk}"]')                  # still works
    page.wait_for_selector(f'[data-node="{ch.pk}"]')


def test_an_unrelated_toggle_click_still_commits_a_pending_rename(page, live_server):
    """The converse of the dirty-rename guard: arming `swapping` for ANY
    toggle would silently discard this edit."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="ren")
    other = ContentNodeFactory(
        course=course, kind="part", parent=None, title="Other part"
    )
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "ren"})
    page.goto(f"{live_server.url}{url}?open=")
    field = page.locator(f'[data-node="{other.pk}"] input.tree__title')
    field.click()
    field.fill("Renamed elsewhere")
    # Wait on the RENAME response, not on the scope fetch. They are different
    # requests, and asserting on the DB after the wrong one samples a race
    # window rather than an outcome -- it would flake on a slow runner and,
    # worse, could pass merely because the rename was slow rather than
    # suppressed.
    with page.expect_response(lambda r: "/node/rename/" in r.url and r.status == 200):
        page.click(f'[data-toggle="{part.pk}"]')   # a DIFFERENT row's toggle
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    other.refresh_from_db()
    assert other.title == "Renamed elsewhere"


def test_collapsing_over_a_dirty_rename_posts_nothing(page, live_server):
    """Driven by a real MOUSE click: focusout fires at mousedown, so a
    keyboard-only test would exercise the path that was already correct."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="dirty")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "dirty"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    field = page.locator(f'[data-node="{ch.pk}"] input.tree__title')
    field.click()
    field.fill("Half typed")
    page.click(f'[data-toggle="{part.pk}"]')       # collapses ch's own subtree
    page.wait_for_selector(f'[data-node="{ch.pk}"]', state="detached")
    ch.refresh_from_db()
    assert ch.title == "Chap A"                    # abandoned, not committed


def test_keyboard_traversal_still_issues_one_panel_fetch(page, live_server):
    """The toggle adds a focus stop before every container title."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="kbd")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "kbd"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    # Start FROM a title, or Tab may never reach the tree (the base shell has a
    # skip link, header nav and the builder's own header links first) and the
    # assertion would hold with zero fetches, guarding nothing.
    page.locator(f'[data-node="{part.pk}"] input.tree__title').focus()
    assert page.evaluate(
        "() => !!document.activeElement.closest('.tree__title')"
    ), "traversal must start inside the tree"
    calls = []
    page.on(
        "request",
        lambda r: calls.append(r.url)
        if "/build/node/" in r.url and r.url.rstrip("/").split("/")[-1].isdigit()
        else None,
    )
    for _ in range(9):                             # title -> toggle -> ~6 cluster -> next title
        page.keyboard.press("Tab")
    page.wait_for_timeout(400)                     # longer than the 150ms debounce
    assert len(calls) == 1                         # exactly one, not "at most"


def test_two_overlapping_tree_fetches_stay_busy_until_both_settle(page, live_server):
    """The whole reason §8 specifies a COUNTER rather than a boolean."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="busy")
    other = ContentNodeFactory(
        course=course, kind="part", parent=None, title="Second part"
    )
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "busy"})
    page.goto(f"{live_server.url}{url}?open=")
    page.route("**/scope/**", lambda route: page.wait_for_timeout(300) or route.continue_())
    page.click(f'[data-toggle="{part.pk}"]')
    page.click(f'[data-toggle="{other.pk}"]')
    assert page.locator(".builder[data-busy]").count() == 1
    page.wait_for_selector(f'ol[data-scope="{part.pk}"]')
    page.wait_for_selector(f'ol[data-scope="{other.pk}"]')
    assert page.locator(".builder[data-busy]").count() == 0   # counter unwound


def test_a_panel_fetch_never_sets_the_busy_state(page, live_server):
    """It fires on mere keyboard traversal; counting it would flicker the tree."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="nobusy")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "nobusy"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    flagged = []
    page.locator(f'[data-node="{ch.pk}"] input.tree__title').click()
    page.wait_for_timeout(50)
    flagged.append(page.locator(".builder[data-busy]").count())
    page.wait_for_timeout(300)
    assert flagged == [0]


def test_collapse_forgets_descendants_through_the_JS_toggle(page, live_server):
    """The JS half of the invariant. The no-JS half is a template-tag test; the
    mechanism here is different (subtree removal + collectOpen re-derivation),
    which is where a bug would actually live."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="forget")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "forget"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    page.click(f'[data-toggle="{ch.pk}"]')
    page.wait_for_selector(f'ol[data-scope="{ch.pk}"]')
    page.click(f'[data-toggle="{part.pk}"]')                  # collapse the parent
    page.wait_for_selector(f'ol[data-scope="{part.pk}"]', state="detached")
    page.click(f'[data-toggle="{part.pk}"]')                  # re-expand it
    page.wait_for_selector(f'ol[data-scope="{part.pk}"]')
    assert page.locator(f'ol[data-scope="{ch.pk}"]').count() == 0


def test_a_mutation_landing_mid_toggle_leaves_no_detached_scope(page, live_server):
    """Exercises the re-resolve-and-bail guard in the toggle's .then."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="midflight")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "midflight"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    page.route("**/scope/**", lambda route: page.wait_for_timeout(600) or route.continue_())
    page.click(f'[data-toggle="{ch.pk}"]')                    # slow scope fetch
    # a reorder returns _render_scope and replaces the ancestor scope under it
    page.click(f'[data-node="{ch.pk}"] button[name="direction"][value="down"]')
    page.wait_for_timeout(1200)
    assert page.locator(f'ol[data-scope="{ch.pk}"]').count() <= 1
    assert page.evaluate(
        """() => [...document.querySelectorAll('ol.tree__scope')]
                  .every(o => o.isConnected && o.closest('.builder'))"""
    )


def test_pk_substitution_survives_a_slug_containing_a_zero(page, live_server):
    """Guards the $-anchored replacement in scopeUrlFor and the panel URL."""
    owner = _make_pa_user("pa")
    course, part, ch, _u = _seed(owner, slug="mat-0-pp")
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'mat-0-pp'})}"
    )
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')   # a naive replace() 404s
```

Add `from tests.factories import ContentNodeFactory` to the file's import block if the
sweep above did not already.

- [ ] **Step 4c: Guard the busy state's CSS shape**

Append to `tests/test_builder_styles.py`:

```python
def test_busy_state_does_not_block_pointer_events():
    """If it did, the per-toggle in-flight guard would be dead code and
    test_double_click_yields_exactly_one_scope would pass vacuously."""
    css = _css()
    block = re.search(r"\.builder\[data-busy\][^{]*\{([^}]*)\}", css)
    assert block, "no [data-busy] rule found"
    assert "pointer-events" not in block.group(1)
```

Uses the file's own `_css()` helper (`tests/test_builder_styles.py:14`). It imports only
`re` and `pathlib.Path` — there is no `settings` import to match, and none is needed.

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e ; echo "exit=$?"
uv run pytest tests/test_builder_styles.py -q ; echo "exit=$?"
```
Expected: exit=0 for both.

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
def test_drag_with_a_single_dragover_still_drops(page, live_server):
    """Covers the drop-flushes-the-pending-frame case.

    ONE dragover then an immediate drop is the worst case for the rAF
    throttle: targetScope and the dataset.drop* values are set in the
    DEFERRED part, so a cancel-only rule leaves them unset and the gesture is
    silently discarded after preventDefault already promised it was legal.
    """
    owner = _make_pa_user("pa")
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
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "drag"})
    page.goto(f"{live_server.url}{url}?open={part.pk},{a.pk},{b.pk}")
    page.wait_for_selector(f'ol[data-scope="{b.pk}"]')
    _simulate_drag(
        page,
        f'[data-node="{unit.pk}"] .ica--grip',
        f'ol[data-scope="{b.pk}"]',
        moves=1,
    )
    page.wait_for_selector(f'ol[data-scope="{b.pk}"] [data-node="{unit.pk}"]')
    unit.refresh_from_db()
    assert unit.parent_id == b.pk


def test_drag_across_two_separately_opened_branches(page, live_server):
    """The reporter's actual gesture: open two chapters, drag between them."""
    owner = _make_pa_user("pa")
    course = CourseFactory(slug="drag2", owner=owner)
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
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "drag2"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    # Open BOTH branches through the real toggles, not by URL.
    page.click(f'[data-toggle="{a.pk}"]')
    page.wait_for_selector(f'ol[data-scope="{a.pk}"]')
    page.click(f'[data-toggle="{b.pk}"]')
    page.wait_for_selector(f'ol[data-scope="{b.pk}"]')
    _simulate_drag(
        page,
        f'[data-node="{unit.pk}"] .ica--grip',
        f'ol[data-scope="{b.pk}"]',
        moves=3,
    )
    page.wait_for_selector(f'ol[data-scope="{b.pk}"] [data-node="{unit.pk}"]')
    unit.refresh_from_db()
    assert unit.parent_id == b.pk
```

- [ ] **Step 2: Record the pre-change baseline — these must pass NOW and after**

```bash
uv run pytest tests/test_e2e_builder_toggle.py -q -m e2e -k drag ; echo "exit=$?"
```
Expected: exit=0. This is **not** a failing-test gate — today's `dragover` is
synchronous, so both drag tests already pass. They exist to catch the regression Step 3
could introduce; if either is red here, fix that before touching the handler.

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
Expected: exit=0.

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

In `builder.html`, `data-panel-url` already exists on `.builder` with `pk=0`. In `builder.js`,
replace the **whole** `focusin` handler — showing it complete, because the tail carries the
debounce that Task 8's keyboard-traversal test asserts on, and a partial paste would delete
it:

```js
  root.addEventListener("focusin", function (e) {
    // Mark consumption and timer clearing run for EVERY focusin, whatever the
    // target, BEFORE the .tree__title test. Tab now goes toggle -> title ->
    // ~6 cluster controls -> next title, and those stops can span more than
    // 150ms; if only titles cleared the timer, row A's fetch would fire while
    // the author was still inside A's cluster.
    var byPointer = pointerFocus;
    pointerFocus = false;
    if (panelTimer) { clearTimeout(panelTimer); panelTimer = null; }
    var t = e.target.closest(".tree__title");
    if (!t) return;
    var row = t.closest("li.tree__row");
    if (!row) return;
    var tpl = root.getAttribute("data-panel-url") || "";
    if (!tpl) return;
    // $-anchored: a `0` inside the course slug must not match.
    var url = tpl.replace(/\/0\/$/, "/" + row.getAttribute("data-node") + "/");
    clearMoving();
    // A deliberate click must not gain 150ms of latency; only keyboard
    // traversal is debounced, so tabbing across ten rows issues one fetch.
    if (byPointer) loadPanel(url);
    else panelTimer = setTimeout(function () { panelTimer = null; loadPanel(url); }, 150);
  });
```

Note the comment update: the tab sequence now begins with the toggle.

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

- [ ] **Step 1: Reconcile against the Task 0b enumeration**

Re-run the sweep and diff it against `docs/superpowers/plans/affected-tests.md`:

```bash
grep -rln "manage_builder\|/build/\|data-scope\|tree__row\|data-panel-url\|data-node-move-url" tests/ | sort
uv run pytest tests/ -q ; echo "exit=$?"
```

Any file failing that is **not** in the enumeration is a regression from Tasks 3–10, not a
migration item. Fix it as a defect before proceeding.

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

- [ ] **Step 1b: Test the plural forms actually render**

The whole reason both labels are rendered server-side is that JS cannot select a Polish
plural form — so the plural selection is the risky part, and `test_i18n_po_health.py` checks
catalog *health*, not the rendered string. Append to `tests/test_builder_lazy_scopes.py`:

```python
@pytest.mark.django_db
def test_polish_toggle_labels_use_all_three_plural_forms(client):
    from django.utils import translation

    owner = make_login(client, "owner")
    course = CourseFactory(slug="pl", owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="Cz")
    labels = {}
    for n in (1, 2, 5):
        while course.nodes.filter(parent=part).count() < n:
            ContentNodeFactory(
                course=course,
                kind="chapter",
                parent=part,
                title=f"R{course.nodes.filter(parent=part).count()}",
            )
        with translation.override("pl"):
            html = client.get(
                reverse("courses:manage_builder", kwargs={"slug": "pl"})
                + "?open="
            ).content.decode()
        labels[n] = re.search(
            r'data-toggle="%d"[\s\S]*?aria-label="([^"]+)"' % part.pk, html
        ).group(1)
    assert len({labels[1], labels[2], labels[5]}) == 3, labels
```

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

Re-run the committed probes from Task 0, both ways, so the numbers are comparable:

```bash
# offline render (no CSRF inputs in the count)
SLUG=mat-pp OPEN="" uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"

# real page in Chromium (CSRF inputs included) -- needs runserver + a session key
uv run python manage.py runserver &          # or a second terminal
uv run python manage.py shell -c "exec(open('scripts/perf/probe_browser.py').read())" -- --mint-session
SESSION=<key printed above> uv run python scripts/perf/probe_browser.py
```

The browser probe reports `per_row`, which is the post-change elements-per-row basis the
spec's targets depend on — the ~44 figure is an estimate and must be replaced with the
measured value.

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

**Known gaps, deliberate — each is a decision, not an omission:**

- The spec's `q`/filter rules (`_filtered_map`, `q` on hrefs and forms, `X-Builder-Info`'s
  `filtered` code, the `q_chain` precedence step) are reserved but not implemented.
  `open_ids` accepts `q_chain=None` so slice 2 does not retrofit a precedence step across a
  function boundary, and `_info_entries` emits **keyed** entries so slice 2 adds a key
  rather than a mechanism.
- **`X-Builder-Info` is not implemented in slice 1**, so a `_render_scope` response that
  truncates at the 500-pk ceiling is silently un-noticed. This is reachable in slice 1
  (`CEILING` ships here), and it is accepted because the ceiling can only be crossed by a
  page-level action — expand-all is slice 2, and a hand-edited URL lands on a page render,
  which *does* show the `info` entry (tested). Slice 2 adds the header and its JS renderer
  for both codes at once.
- The spec's `_builder_with_notice`-renders-the-same-tree test is **not** in slice 1: with
  no filter there is no divergence to detect yet beyond what
  `test_open_session_honours_a_stored_EMPTY_list` already covers. Slice 2 adds it.
- "`open=all` survives a collapse" is covered structurally by
  `test_collapse_href_drops_this_pk_AND_its_open_descendants` plus
  `test_toggle_expands_and_collapses`; the encoding-switches-to-an-enumeration half is a
  slice-2 concern because only expand-all emits `all` from the UI.

**Type consistency.** `open_ids()` is the module function throughout (the spec's `_open_ids`; imported as `_open_ids` in `views_manage.py`). `OpenSet.ids` is a `frozenset` everywhere; `_extra_container_pks` and `_render_scope` build plain sets locally rather than mutating it. `remember_node(request, slug, value, key=...)` is used for all three session dicts. `container_pks(cmap)` is used by both `builder_open.py` and `views_manage.py`.

**Placeholder scan:** none — every step carries the actual code or the exact command and its expected output.
