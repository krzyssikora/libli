# Builder Filter and Expand-All — Slice 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the builder a title filter that finds any node in a 944-node course in under a second, plus deliberate expand-all / collapse-all controls — without re-introducing the cost slice 1 removed on any other path.

**Architecture:** One new DB-free module (`courses/builder_filter.py`) owns all filter derivation: a diacritic-folding table, the 2-character floor, match selection, the ancestor walk and the 100-match cap. It returns a **restricted** children-map that the tree templates render from, while the **full** map continues to feed open-set sanitisation and the collapse-href descendant sets. `q` rides every fragment request; a new `manage_tree` GET serves the top scope so the filter can swap the pane without a page load. On the client, a single module-scoped *tracker* holds the last applied query and is the one value every request path and `syncUrl` read.

**Tech Stack:** Django 5.2 templates + views, vanilla JS (`builder.js`, no build
step — `var`/`function` throughout, with two deliberate modern exceptions noted
where they appear: the spread in `effectiveQ`, because `.length` counts UTF-16
units where Python counts code points, and `replaceChildren` in the info-slot
registry), pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-07-28-builder-filter-and-expand-all-design.md`. **Read it before starting** — it supersedes §9/§10 of the slice-1 spec and records 17 deltas from it. Section references below (§1, §3c, §5z …) are to that document.

**Predecessor:** slice 1 is merged on this branch (PR #189). Its spec is `docs/superpowers/specs/2026-07-27-builder-large-course-performance-design.md`; its §2 (precedence), §4 (no-JS parity), §5 (toggle) and §8 (notice/busy channel) are load-bearing here and are **not** restated in the slice-2 spec.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python/tooling is only reachable through `uv run`.** Bare `pytest`/`ruff`/`python` are not on PATH. Use `uv run pytest …`, `uv run ruff format .`, `uv run ruff check .`.
- **Never run two pytest invocations at once.** Concurrent runs collide on the Postgres test database.
- **Two databases, deliberately.** This worktree's git-ignored `.env` points `DATABASE_URL` at `libli_blcp`, so pytest uses `test_libli_blcp` and cannot collide with parallel sessions. The perf probes need the real `mat-pp`, which lives in the shared dev database, so **every probe command carries an explicit `DATABASE_URL=postgres://libli:libli@localhost:5432/libli` prefix**. Tests never need `mat-pp`; probes never need the test DB.
- **e2e tests need `-m e2e` explicitly** or they are silently deselected and pytest exits 5. **Exit 5 is not a pass.**
- **Pytest verdict lines do not survive a Bash pipe.** Check the exit code, or `grep FAILED`.
- **`{# #}` template comments must be single-line.** Use `{% comment %}…{% endcomment %}` for multi-line.
- **New user-visible strings need msgids in both `pl` and `en` catalogs.** Regenerate with `-l pl -l en --no-obsolete`; clear every fuzzy entry (two deletions: the `#, fuzzy` line and the `#| msgid` line).
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD`.
- **ruff selects `E, F, I, UP, B, S`.** Appended imports go at the **top** with the existing block — `E402` rejects a mid-file import, and isort is `force-single-line`.
- **Every code block here is meant to be pasted verbatim, then formatted.** End each task with `uv run ruff format .` and `uv run ruff check .` *before* the commit step.
- **Verify `git branch --show-current` immediately before every commit** — a parallel session has switched branches under this worktree before. Expected: `worktree-builder-large-course-perf`.
- **Constants, exact values from the spec:** `MIN_QUERY = 2` (folded chars, after stripping), `MATCH_CAP = 100`, ceiling `500` (`builder_open.CEILING`, read **through the module**), size threshold `150`.
- **Falsify every guard.** A test that cannot go red is treated as not written: delete what it protects, require RED, restore. Slice 1 shipped two vacuous tests before this was enforced.

## Where the code goes

| File | Responsibility |
| --- | --- |
| `courses/builder_filter.py` *(new)* | All filter derivation. No view imports, no DB. `fold`, `is_active`, `filtered_map`. |
| `courses/builder_open.py` | Precedence. Gains the §3c restructure (sentinel lifted out of step 2's predicate; `q_chain` above both session reads). |
| `courses/views_manage.py` | `_raw_q`, `FilterContext`, `_filter_context`, `manage_tree`, the `X-Builder-Info` header, the §3m reorder guard, `builder_force`, `_tree_context`'s five new keys. |
| `courses/urls.py` | The `manage_tree` route. |
| `courses/static/courses/js/builder.js` | The tracker (§5z), `setTreeParams`, the filter/clear/expand-all/collapse-all handlers, the info-slot registry. |
| `courses/static/courses/css/builder.css` | Filter control, info slot `:empty` rule, disabled bulk controls. |
| `templates/courses/manage/builder.html` | Filter form, bulk controls, the always-present info slot, five new `data-*` attributes. |
| `templates/courses/manage/_scope.html`, `_tree_node.html`, `_move_buttons.html`, `_add_affordance.html`, `node_confirm_delete.html`, `_move_picker.html` | Hidden `q`, percent-encoded `q` in hrefs, filter-aware empty text, `disabled` grip/arrows. |
| `courses/templatetags/courses_manage_extras.py` | `toggle_href` preserves `q` (via `urlencode`, so it needs no separate escaping rule). |
| `tests/test_builder_filter.py` *(new)* | `builder_filter` unit tests, no DB. |
| `tests/test_builder_filter_views.py` *(new)* | View/integration rows from §8. |
| `tests/test_e2e_builder_filter.py` *(new)* | The `-m e2e` rows from §8. |

---

## Task 0: Baseline — enumerate the affected tests before changing behaviour

**Files:**
- Create: `docs/superpowers/notes/2026-07-28-affected-tests-slice2.md`

**Not under `.superpowers/`** — `.gitignore:13` ignores that whole directory, so
`git add` on a named path there exits 1 and the commit step then has nothing
staged. Slice 1's ledger lived there as an untracked working note; these two are
committed, so they go somewhere tracked.

**Interfaces:**
- Consumes: nothing.
- Produces: the green-baseline gate every later task re-runs.

- [ ] **Step 1: Record which existing tests touch the surfaces this slice changes**

Run each and record the exit code:

```bash
uv run pytest tests/test_builder_lazy_scopes.py tests/test_builder_open_ids.py \
  tests/test_manage_node_ops.py tests/test_manage_element_ops.py \
  tests/test_manage_move_picker.py tests/test_manage_affordance.py \
  tests/test_builder_styles.py tests/test_builder_js_invariants.py \
  tests/test_manage_builder.py tests/test_builder_duplicate_unit.py \
  tests/test_manage_node_duplicate.py tests/test_tree_badge.py \
  tests/test_manage_duplicate_button.py \
  tests/test_i18n_po_health.py -q
```

`tests/test_tree_badge.py` renders `_tree_node.html` **directly** through
`render_to_string` with a hand-built context (`:55-56`), so Tasks 6 and 8 edit
the exact template it asserts on — and because that context defines neither `q`
nor `filtered`, both new `{% if %}` branches take their falsy arm there. That
is the intended outcome, but it is worth a recorded before-state rather than an
assumption. `tests/test_manage_duplicate_button.py` counts `data-op="duplicate"`
in the builder page, and Task 6 Step 4 adds an input inside that very form.

The last three are in the list because later tasks assert them green without
them ever having been baselined: **Task 3 Step 8** runs
`tests/test_manage_builder.py`, and Tasks 6 and 7 both change `node_duplicate`
— Task 6 Step 7 puts `q` on its redirect (`views_manage.py:714`'s
`_redirect_to_builder`), Task 7 Step 4 adds `_stash_builder_force` beside it —
which is exactly what `tests/test_builder_duplicate_unit.py` and
`tests/test_manage_node_duplicate.py` exercise. Task 16 Step 1 also re-runs
`test_manage_builder.py` under the "anything red is a regression" rule, which
is meaningless without a recorded before-state.

Expected: exit 0.

- [ ] **Step 2: Record the e2e baseline for the files this slice will touch**

```bash
uv run pytest tests/test_e2e_builder_toggle.py tests/test_e2e_builder_reorder.py \
  tests/test_e2e_builder_ws2.py tests/test_e2e_builder_authoring.py \
  tests/test_e2e_builder.py tests/test_e2e_builder_tree_layout.py \
  tests/test_e2e_inline_rename.py -m e2e -q
```

`test_e2e_inline_rename.py` is in this list because it drives the rename form
in `_tree_node.html` (Task 6 Step 4 adds a hidden `q` to it) **and** builder.js's
rename/`swapping` lifecycle — which Task 11 Step 7, Task 12's toggle-chain
reshape, Task 13's `pointerdown` arming and Task 14's M15 conversion of the
submit handler all touch. It is the single suite most exposed by this slice's
JS work.

Expected: exit 0. **If this exits 5, the marker was dropped — that is not a pass.**

`test_builder_js_invariants.py` (which regexes `builder.js`'s source) and the
three extra e2e files are in this list because the slice rewrites `withOpen`,
the toggle's `.then` chain, every `.catch`, `syncUrl`, the `swapping` lifecycle
and the picker fetch — all of which those suites exercise.

- [ ] **Step 3: Write the ledger**

**`docs/superpowers/notes/` does not exist yet** — `docs/superpowers/` holds
only `plans/` and `specs/`. Create it first (an editor tool will do so
implicitly; `mkdir -p docs/superpowers/notes` removes the doubt):

```bash
mkdir -p docs/superpowers/notes
```

Create `docs/superpowers/notes/2026-07-28-affected-tests-slice2.md` recording, for each file above: the exit code, the test count, and a one-line note on why this slice can affect it. Name explicitly the three that encode behaviour this slice **changes**:

- `tests/test_manage_node_ops.py` — reorder now refuses under an active filter (Task 8).
- `tests/test_manage_move_picker.py` — the picker gains `q` (Task 6).
- `tests/test_builder_styles.py` — new selectors for the filter control and disabled bulk controls (Task 9).
- `tests/test_builder_duplicate_unit.py`, `tests/test_manage_node_duplicate.py`
  — `node_duplicate`'s redirect gains `q` (Task 6) and its success path gains
  `_stash_builder_force` (Task 7). Expect redirect-URL assertions to need
  updating; that is migration, not regression.

Also record `tests/test_manage_builder.py`, which nothing in this slice edits
but Tasks 3 and 16 both assert green.

Anything outside this list going red during Tasks 1–16 is a regression, not migration noise.

- [ ] **Step 4: Commit**

```bash
git branch --show-current   # expect worktree-builder-large-course-perf
git add docs/superpowers/notes/2026-07-28-affected-tests-slice2.md
git commit -m "chore(builder): baseline the tests slice 2 can affect"
```

---

## Task 1: `courses/builder_filter.py` — fold, floor, matching, walk

**Files:**
- Create: `courses/builder_filter.py`
- Test: `tests/test_builder_filter.py`

**Interfaces:**
- Consumes: nothing. The module imports only `unicodedata` and compares `node.kind != "unit"` against a string literal — deliberately, since that is what keeps it DB-free and lets the tests use a `FakeNode`. The literal matches `ContentNode.Kind.UNIT`'s value.
- Produces:
  - `MIN_QUERY: int = 2`, `MATCH_CAP: int = 100`
  - `fold(s: str) -> str`
  - `is_active(q) -> bool`
  - `filtered_map(cmap, q) -> tuple[dict, set[int], int, int, bool]` returning `(restricted_cmap, chain_ids, shown, total, q_active)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_filter.py`:

```python
import re
import unicodedata

from courses.builder_filter import MATCH_CAP
from courses.builder_filter import filtered_map
from courses.builder_filter import fold
from courses.builder_filter import is_active


class FakeNode:
    """Structural stand-in: filtered_map must never touch the ORM."""

    def __init__(self, pk, parent_id, title, order=0, kind="unit"):
        self.pk = pk
        self.parent_id = parent_id
        self.title = title
        self.order = order
        self.kind = kind


def _map(nodes):
    cmap = {}
    for n in nodes:
        cmap.setdefault(n.parent_id, []).append(n)
    return cmap


def test_fold_maps_every_polish_letter_to_ascii():
    assert fold("ĄĆĘŁŃÓŚŹŻ ąćęłńóśźż") == "acelnoszz acelnoszz"


def test_fold_handles_l_stroke_in_both_directions():
    # The one letter NFKD cannot reach: U+0142 has no decomposition, so a
    # generic "NFKD then drop combining marks" fold leaves it in place.
    assert fold("Łąka") == "laka"
    # The containment the filter actually performs, in both directions --
    # `fold(x) in fold(x)` would be true whatever fold did.
    assert fold("laka") in fold("Rozdział: Łąka i las")
    assert fold("ŁĄKA") in fold("rozdzial: laka i las")


def test_fold_handles_decomposed_input():
    # Imported HTML arrives NFD; without U+0300-U+036F in the table this
    # returns "ka\u0328ty" -- base `a` followed by a DANGLING combining
    # ogonek. Written ESCAPED on purpose: the precomposed "k\u0105ty" is a
    # DIFFERENT string, indistinguishable from it in a terminal and in a
    # diff, and that difference is the whole point of this row. An ASCII
    # query misses the node entirely.
    assert fold(unicodedata.normalize("NFD", "Kąty")) == "katy"


def test_is_active_applies_the_floor_to_the_FOLDED_length():
    assert is_active("ab") is True
    assert is_active("a") is False
    assert is_active(" a ") is False
    assert is_active("") is False
    assert is_active(None) is False
    # Two code points, one folded character: a raw-length floor lets it through.
    assert is_active(unicodedata.normalize("NFD", "ą")) is False


def test_below_floor_returns_the_map_unchanged_and_inactive():
    nodes = [FakeNode(1, None, "Trygonometria", kind="chapter")]
    cmap = _map(nodes)
    restricted, chains, shown, total, active = filtered_map(cmap, "a")
    assert active is False
    assert chains == set()
    assert (shown, total) == (0, 0)
    assert restricted == cmap


def test_the_returned_map_is_never_the_argument_even_when_blank():
    # Effect 2 (spec 3e) mutates the restricted map. Aliasing it to the full
    # map on the blank path corrupts what _open_ids and _open_descendants read
    # in the same request, and no filtered test can catch that.
    nodes = [FakeNode(1, None, "A", kind="chapter")]
    cmap = _map(nodes)
    restricted, *_ = filtered_map(cmap, "")
    assert restricted is not cmap
    assert restricted[None] is not cmap[None]


def test_active_with_zero_matches_is_still_active():
    nodes = [FakeNode(1, None, "Trygonometria", kind="chapter")]
    restricted, chains, shown, total, active = filtered_map(_map(nodes), "zzzz")
    assert active is True
    assert (shown, total) == (0, 0)
    assert restricted == {}


def test_walk_includes_a_matched_container_itself_and_every_ancestor():
    part = FakeNode(1, None, "Część", kind="part")
    chap = FakeNode(2, 1, "Trygonometria", kind="chapter")
    unit = FakeNode(3, 2, "Sinus", kind="unit")
    restricted, chains, shown, total, active = filtered_map(
        _map([part, chap, unit]), "sinus"
    )
    assert chains == {1, 2}  # ancestors; the unit owns no scope
    assert restricted[2] == [unit]
    assert restricted[1] == [chap]
    assert (shown, total) == (1, 1)

    _, chains2, *_ = filtered_map(_map([part, chap, unit]), "trygo")
    assert chains2 == {1, 2}  # the matched CONTAINER is in its own chain


def test_cap_keeps_the_first_MATCH_CAP_in_order_pk_with_scattered_pks():
    # Scattered, non-sequential pks: CPython iterates small sequential ints
    # ascending, so a sorted->list mutation would stay green on tidy pks.
    # DISTINCT pks: filtered_map indexes by pk, so a repeated list collapses
    # 240 nodes to 6 and every count assertion below becomes unreachable.
    nodes = [
        FakeNode(9001 + i * 7919, None, f"Zadanie {i}", order=i % 7)
        for i in range(240)
    ]
    restricted, chains, shown, total, active = filtered_map(_map(nodes), "zadanie")
    assert total == len(nodes)
    assert shown == MATCH_CAP
    kept = restricted[None]
    assert len(kept) == MATCH_CAP
    # The cap is applied to the (order, pk)-sorted match list, so the kept SET
    # is the 100 lowest (order, pk) pairs. The emitted ROW order is the input
    # order of cmap[parent] -- see the sibling-order test.
    lowest = sorted((n.order, n.pk) for n in nodes)[:MATCH_CAP]
    assert sorted((n.order, n.pk) for n in kept) == lowest


def test_restricted_map_preserves_sibling_order_and_groups_roots_under_none():
    """PRESERVES, never re-sorts. _children_map already emits each parent's
    children in (order, pk) order (views_manage.py:140), so the input order IS
    the correct order -- the fixture must be built that way or the test
    asserts a sort filtered_map deliberately does not perform.
    """
    b = FakeNode(11, None, "Alfabet", order=0, kind="chapter")
    a = FakeNode(10, None, "Alfa", order=1, kind="chapter")
    restricted, *_ = filtered_map(_map([b, a]), "alfa")   # cmap order
    assert restricted[None] == [b, a]


def test_client_floor_never_exceeds_the_server_floor_on_latin_input():
    # The dangerous direction (spec 5c): client above the floor while the
    # server is below it sends a filter fetch that omits `open`, and the
    # server's blank `q` collapses the tree. Measured Latin count: 0.
    def client_measure(s):
        """A mirror of builder.js's effectiveQ. The UTF-16 half must be
        EXPLICIT: Python has no `.length`, so spelling this `len(stripped)`
        makes the astral falsification unreachable -- both spellings agree on
        every BMP input, so the test could not tell the two measures apart.
        """
        t = re.sub(r"^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$", "", s)
        stripped = "".join(
            c
            for c in unicodedata.normalize("NFC", t)
            if not (0x0300 <= ord(c) <= 0x036F)
        )
        return len(stripped.encode("utf-16-le")) // 2   # what .length counts

    for ch in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻß" + "Ĳǆǉǌǳ" + "a\u0085":
        assert client_measure(ch) <= len(fold(ch)), ch
    # The two inputs that catch a bare trim() and a .length count.
    assert client_measure("a\u0085") == 1
    assert client_measure("𝐀") == 2 > len(fold("𝐀"))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_builder_filter.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'courses.builder_filter'`.

- [ ] **Step 3: Write the module**

Create `courses/builder_filter.py`:

```python
"""Title filtering for the builder tree, for one request.

Deliberately free of view imports and of the ORM: everything arrives as
arguments, so the whole module is unit-testable without a database. The
builder already loads the full children-map in one query; this module
selects matches from it in memory and walks `parent_id` upward, so the
filter adds no query (spec section 1).
"""

import unicodedata

MIN_QUERY = 2  # chars of the FOLDED query, after stripping -- see spec 1a
MATCH_CAP = 100  # matches kept, in (order, pk) order


def _build_fold_table():
    """Three sources, and all three are load-bearing (spec 1b).

    1. U+00C0-U+024F decomposed via NFKD, keeping entries whose stripped base
       is ASCII.
    2. `l` and `L` with stroke, which NFKD cannot reach -- U+0142 has NO
       decomposition, so a generic fold silently leaves every one in place
       and `laka` stops matching `Łąka`.
    3. The combining marks themselves, DELETED, so decomposed (NFD) input
       folds the same as precomposed. Titles imported from external HTML
       arrive NFD; without this, fold(NFD("k\u0105ty")) is "ka\u0328ty" --
       base `a` plus a DANGLING combining ogonek, NOT the precomposed
       "k\u0105ty" it renders identically to -- and an ASCII query misses
       that node with no symptom.
    """
    table = {}
    for cp in range(0x00C0, 0x0250):
        ch = chr(cp)
        base = "".join(
            c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)
        )
        if base != ch and base and base.isascii():
            table[cp] = base
    table[0x0142] = "l"
    table[0x0141] = "L"
    table.update({cp: None for cp in range(0x0300, 0x0370)})
    return str.maketrans(table)


_FOLD_TABLE = _build_fold_table()


def fold(s):
    """Case- and diacritic-insensitive form. `translate` BEFORE `casefold`
    so the table can carry both cases."""
    return s.translate(_FOLD_TABLE).casefold()


def is_active(q):
    """The floor test, alone -- needs no cmap.

    Its own function because one consumer runs where no tree exists: the
    reorder guard in node_move's `mode == "reorder"` branch fires before any
    children-map is loaded (spec 3m), so it can call neither filtered_map nor
    _filter_context. Re-testing the floor inline anywhere else is forbidden;
    this is the single copy.
    """
    return len(fold((q or "").strip())) >= MIN_QUERY


def _copy(cmap):
    """A NEW outer dict with NEW lists, always -- even on the blank path.

    Returning `cmap` itself would make the restricted and full maps the same
    object on the most common path, at which point effect 2's insertion
    (spec 3e) mutates the map _open_ids and _open_descendants read from in
    the same request.
    """
    return {parent: list(kids) for parent, kids in cmap.items()}


def filtered_map(cmap, q):
    """(restricted cmap, chain ids, shown, total, q_active).

    `chain_ids` is every matched CONTAINER plus every ancestor of every
    match -- the node itself included, or a matched chapter arrives collapsed
    and the row the author searched for is the one they cannot see.
    """
    if not is_active(q):
        return _copy(cmap), set(), 0, 0, False

    needle = fold(q.strip())
    index = {n.pk: n for kids in cmap.values() for n in kids}
    matches = [n for n in index.values() if needle in fold(n.title)]
    matches.sort(key=lambda n: (n.order, n.pk))
    total = len(matches)
    kept = matches[:MATCH_CAP]

    keep_pks = set()
    chains = set()
    for node in kept:
        keep_pks.add(node.pk)
        if node.kind != "unit":
            chains.add(node.pk)
        cur = node.parent_id
        while cur is not None and cur in index:
            keep_pks.add(cur)
            chains.add(cur)
            cur = index[cur].parent_id

    restricted = {}
    for parent, kids in cmap.items():
        rows = [n for n in kids if n.pk in keep_pks]
        if rows:
            restricted[parent] = rows
    return restricted, chains, len(kept), total, True
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_builder_filter.py -q
```

Expected: PASS, 11 tests.

- [ ] **Step 5: Falsify three guards**

For each, make the mutation, confirm RED, restore:

1. Delete `table.update({cp: None for cp in range(0x0300, 0x0370)})` → `test_fold_handles_decomposed_input` must fail.
2. Change `is_active` to `len((q or "").strip()) >= MIN_QUERY` → `test_is_active_applies_the_floor_to_the_FOLDED_length` must fail on the NFD case.
3. Change `_copy` to `return cmap` → `test_the_returned_map_is_never_the_argument_even_when_blank` must fail.

If any stays green, the test is not guarding what it claims.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/builder_filter.py tests/test_builder_filter.py
git commit -m "feat(builder): filter derivation module — fold, floor, match, walk"
```

---

## Task 2: `open_ids` precedence restructure and the `_remember_open` gate

**Files:**
- Modify: `courses/builder_open.py:119-179` (the `open_ids` body)
- Modify: `courses/views_manage.py:218-239` (`_remember_open`)
- Test: `tests/test_builder_open_ids.py`

**Interfaces:**
- Consumes: **nothing from Task 1.** The restructure only reorders `open_ids`'s
  branches, and `_remember_open` receives `q_active` as an argument — Task 8's
  reorder guard is the first real consumer of `is_active`.
- Produces: `open_ids(request, course, cmap, *, mode, q_chain=None)` with `q` outranking both session reads; `_remember_open(request, course, opened, *, q_active)`.

- [ ] **Step 1: Write the failing tests**

First add the one import the file lacks, at the **top** with the existing
block (isort is force-single-line; `E402` rejects a mid-file import). The file
already imports `pytest`, `reverse`, `open_ids`, `_children_map`,
`remember_node`, both factories and `make_login`
(`tests/test_builder_open_ids.py:1-14`); only this is missing:

```python
from courses.builder_open import OPEN_KEY
```

Only that one — `TEST_PASSWORD` is never referenced by the tests below (they
use `make_login`), and ruff selects `F`, so an unused import fails this task's
own `ruff check` gate.

Then append to `tests/test_builder_open_ids.py`:

```python
def test_q_chain_beats_the_open_session_sentinel(rf, small_course_cmap):
    """The no-JS mutation SUCCESS path redirects to ?open=session&q=...

    Step 1 fires before step 3 in the shipped code, so without the
    restructure the author gets their stored PRE-FILTER set over a filtered
    map: every match below the top level invisible, under a notice claiming
    to have found them.
    """
    course, cmap = small_course_cmap
    request = rf.get("/", {"open": "session", "q": "trygo"})
    request.session = {OPEN_KEY: {course.slug: [111, 222]}}
    opened = open_ids(request, course, cmap, mode="page", q_chain={333})
    assert set(opened.ids) == {333}
    assert opened.explicit is False


def test_q_chain_beats_the_notice_carrier(rf, small_course_cmap):
    course, cmap = small_course_cmap
    request = rf.post("/", {})
    request.session = {OPEN_KEY: {course.slug: [111, 222]}}
    opened = open_ids(request, course, cmap, mode="notice", q_chain={333})
    assert set(opened.ids) == {333}


def test_an_explicit_enumeration_still_beats_q_chain(rf, small_course_cmap):
    """Step 2 must keep winning, or 'filter, then toggle' cannot work: a
    no-JS toggle href under a filter carries a real enumeration."""
    course, cmap = small_course_cmap
    request = rf.get("/", {"open": "111,222", "q": "trygo"})
    request.session = {}
    opened = open_ids(request, course, cmap, mode="page", q_chain={333})
    assert set(opened.ids) == {111, 222}
    assert opened.explicit is True


def test_open_session_never_reaches_parse_in_page_mode(rf, small_course_cmap):
    """`session` matches no digits, so _parse would yield the EMPTY set with
    explicit=True -- a collapsed tree that _remember_open then persists."""
    course, cmap = small_course_cmap
    request = rf.get("/", {"open": "session"})
    request.session = {OPEN_KEY: {course.slug: [111]}}
    opened = open_ids(request, course, cmap, mode="page", q_chain=None)
    assert set(opened.ids) == {111}


def test_q_chain_matters_at_the_function_boundary(rf, small_course_cmap):
    """The spec-3b invariant. mode='page' is NOT optional: the signature's
    default is 'fragment', which skips step 4 and returns the empty set for
    BOTH branches, making the assertion vacuous."""
    course, cmap = small_course_cmap
    request = rf.get("/", {})
    request.session = {}
    assert set(open_ids(request, course, cmap, mode="page", q_chain=set()).ids) == set()
    assert set(open_ids(request, course, cmap, mode="page", q_chain=None).ids) != set()
```

Add the fixture at the top of the file if it is not already there:

```python
@pytest.fixture
def small_course_cmap(client, db):
    """Under SIZE_THRESHOLD, so step 4 fires and q_chain=None is
    distinguishable from q_chain=set()."""
    owner = make_login(client, "sc-owner")
    course = CourseFactory(slug="sc", owner=owner)
    a = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    b = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    c = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    cmap = {None: [a, b, c]}
    for n, pk in ((a, 111), (b, 222), (c, 333)):
        n.pk = pk
    return course, cmap
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_builder_open_ids.py -q -k "q_chain or open_session_never"
```

Expected: FAIL on `test_q_chain_beats_the_open_session_sentinel` and `test_q_chain_beats_the_notice_carrier` (both return the stored set).

- [ ] **Step 3: Restructure `open_ids`**

In `courses/builder_open.py`, replace the block from `# Step 1 -- the no-JS post-mutation sentinel` through the `if mode == "fragment"` early return with:

```python
    # The sentinel is lifted OUT of step 2's predicate. `present` alone cannot
    # separate them, and step 1 mutates it -- so hoisting the q_chain block
    # without this makes `?open=3,4&q=...` resolve to the chains (breaking
    # "an explicit open wins"), and leaving `if present:` intact sends
    # "session" into _parse, which matches no digits and yields the EMPTY set
    # with explicit=True: a collapsed tree that _remember_open then persists.
    sentinel = present and raw == "session" and mode == "page"

    # Step 2 -- an explicit value wins, including the empty string.
    if present and not sentinel:
        return _finalize(_parse(raw, containers), containers, explicit=True)

    # Step 3 -- the filter's chains. Above BOTH session reads: `q` is a signal
    # in the request being served, while the sentinel and the notice carrier
    # are fallbacks for a request that carries no signal. Below step 2, which
    # is what makes "filter, then toggle" work.
    if q_chain is not None:
        return _finalize(q_chain, containers)

    # Step 1 -- the no-JS post-mutation sentinel, page mode only.
    if sentinel:
        stored = _stored_open(request, course.slug)
        if stored is not _MISSING:
            return _finalize(stored, containers, explicit=True)
        # missing/flushed -> fall through to 4-6

    # A no-JS conflict/validation re-render is the same author, same tab,
    # mid-loop -- it cannot be a bookmark, so reading the carrier is safe.
    if mode == "notice":
        stored = _stored_open(request, course.slug)
        if stored is not _MISSING:
            # explicit=False: safe to RENDER from, not safe to write back.
            return _finalize(stored, containers, explicit=False)

    if mode == "fragment":
        return _finalize(set(), containers)  # step 6
```

Update the module docstring's step order to match.

- [ ] **Step 4: Gate `_remember_open` on `q_active`**

In `courses/views_manage.py`, change the signature and add the gate:

```python
def _remember_open(request, course, opened, *, q_active):
    """Persist ONLY an author-chosen open set (precedence steps 1-2).

    The `q_active` gate is the half slice 1 could not write, and the parent
    spec pins it: without it a no-JS author filters, clicks a toggle whose
    href carries `open = <the filter's chains> +- pk`, that arrives via step 2
    as explicit=True, and the DERIVED chains are written over their real
    pre-filter expansion -- permanently, since the no-JS path has no stash.

    Gated on q_active, NOT on `"q" in request.GET`: a below-floor `?q=a`
    renders unfiltered, so its `open` is a genuine author-chosen set and
    suppressing the write would lose it.
    """
    if q_active or not opened.explicit:
        return
    remember_node(
        request,
        course.slug,
        sorted(opened.ids)[: builder_open.SESSION_OPEN_LIMIT],
        key=OPEN_KEY,
    )
```

Update its single call site in `builder()` to pass `q_active=` (Task 3 supplies the value; for now pass `False` so the tree stays green).

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_builder_open_ids.py -q
```

Expected: PASS, exit 0.

- [ ] **Step 6: Falsify**

Move the `if q_chain is not None:` block back below the `mode == "notice"` read → `test_q_chain_beats_the_notice_carrier` must fail. Move it below the sentinel → `test_q_chain_beats_the_open_session_sentinel` must fail. Restore.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/builder_open.py courses/views_manage.py tests/test_builder_open_ids.py
git commit -m "feat(builder): q outranks both session reads; _remember_open gates on q_active"
```

---

## Task 3: `FilterContext` — one derivation, three renderers

**Files:**
- Modify: `courses/views_manage.py` (add `_raw_q`, `FilterContext`, `_filter_context`; rewire `builder()`, `_builder_with_notice()`, `_render_scope()`, `_tree_context()`)
- Test: `tests/test_builder_filter_views.py` *(new)*

**Interfaces:**
- Consumes: `builder_filter.filtered_map`, `builder_filter.is_active`, `builder_filter.MIN_QUERY` (Task 1); `open_ids` (Task 2).

**Deliberate deviation from spec 1:** the spec says "`views_manage` imports it
as `_filtered_map`, exactly as slice 1 aliased `open_ids`". This plan imports
the MODULE (`from courses import builder_filter`) and calls
`builder_filter.filtered_map(...)` / `builder_filter.MIN_QUERY` instead —
because that is what makes the `MIN_QUERY` monkeypatch tests bite, for exactly
the reason `_info_entries` reads `builder_open.CEILING` through its module.
- Produces:
  - `_raw_q(request) -> str` — POST then GET.
  - `FilterContext(cmap, opened, open_ids, shown, total, q_active, q_raw)`.
  - `_filter_context(request, course, cmap, *, mode, extra_open=()) -> FilterContext`.
  - `_tree_context(course, cmap, ids, *, q, filtered, expand_all_disabled, q_min)`.
  - `_expand_all_disabled(cmap) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_filter_views.py`:

**Exactly these imports, and no more.** `django.test.Client` is NOT imported
here: its only consumer is `test_manage_tree_access_control`, which Task 4
Step 1 appends. Ruff selects `F`, and `tests/**`'s per-file ignores cover only
`S105/S106/S107` (`pyproject.toml:39-41`) — so importing it now fires `F401` at
**this task's own** Step 10 `ruff check` gate and the task cannot reach its
commit. Same trap as `TEST_PASSWORD` in Task 2 Step 1. Each later task adds the
imports its own rows need, at the top with this block.

```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


@pytest.fixture
def filtered_course(client, db):
    """part > chapter > units, with exactly one matching unit deep down.

    `make_login(client, username)` takes the CLIENT and returns the USER
    (tests/factories.py:175) -- the repo idiom is the pytest-django `client`
    fixture plus `owner = make_login(client, "...")`, as in
    tests/test_builder_lazy_scopes.py:52.
    """
    owner = make_login(client, "pa")
    course = CourseFactory(slug="filt", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Czesc I"
    )
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Rozdzial"
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria & wektory"
    )
    miss = ContentNodeFactory(course=course, kind="unit", parent=chap, title="Logika")
    # A CHILDLESS container, so _scope.html's {% empty %} branch is reachable
    # at all: without it no scope in this fixture is ever empty under
    # `open=all`, and the unfiltered half of the empty-message row cannot pass.
    # "Pusty" matches no query used anywhere in this plan.
    ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Pusty"
    )
    return client, course, part, chap, hit, miss


def test_a_filtered_page_shows_the_match_and_hides_the_rest(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    assert f'data-node="{hit.pk}"' in body
    assert f'data-node="{chap.pk}"' in body
    assert f'data-node="{part.pk}"' in body
    assert f'data-node="{miss.pk}"' not in body


def test_a_below_floor_query_renders_unfiltered_and_emits_no_filter_entry(
    filtered_course,
):
    """?q=a is a PRESENT q that is INACTIVE. Catches a q_active derived from
    bool(q.strip()) rather than from the floor."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "a", "open": "all"}).content.decode()
    assert f'data-node="{miss.pk}"' in body
    assert 'data-info-key="filter"' not in body


def test_data_applied_q_holds_the_raw_q_and_is_always_present(filtered_course):
    """A conditionally-emitted attribute puts null in the tracker; the
    TypeError surfaces later in the input handler and filtering goes silently
    inert (spec 3k)."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    for params, expected in (({}, ""), ({"q": "a"}, "a"), ({"q": "trygo"}, "trygo")):
        body = client.get(url, params).content.decode()
        assert f'data-applied-q="{expected}"' in body, params


def test_data_q_min_is_emitted_and_read_through_the_module(filtered_course, monkeypatch):
    client, course, *_ = filtered_course
    monkeypatch.setattr("courses.builder_filter.MIN_QUERY", 3)
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    assert 'data-q-min="3"' in client.get(url).content.decode()


def test_a_matched_container_renders_OPEN_over_an_empty_scope(filtered_course):
    """Spec 1d. The fixture must pick a matched container with NO matching
    descendant, or the scope is non-empty and the row proves nothing."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "rozdzial"}).content.decode()
    toggle = body.split(f'data-toggle="{chap.pk}"')[1].split(">")[0]
    assert 'aria-expanded="true"' in toggle
    assert f'aria-controls="tree-scope-{chap.pk}"' in toggle
    assert f'data-node="{hit.pk}"' not in body       # no descendant matched
    # The "No matching titles." wording is Task 6's; asserting it here would
    # make this task's own gate red until then.


def test_remember_open_does_NOT_write_while_a_filter_is_active(filtered_course):
    """Asserted ON THE SESSION, never on the render. Driven through a TOGGLE
    under an active filter: a bare filtered GET resolves via step 3, which is
    not `explicit`, so the write is already suppressed and the row would pass
    without the rule. This is the half slice 1 could not write."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    client.get(url, {"open": f"{part.pk},{chap.pk}"})     # persists the real set
    before = client.session.get("builder_open", {}).get(course.slug)
    client.get(url, {"q": "trygo", "open": str(part.pk)})  # a toggle, filtered
    assert client.session.get("builder_open", {}).get(course.slug) == before


def test_remember_open_DOES_write_under_a_below_floor_q(filtered_course):
    """The half where this spec deliberately narrows the parent's "q is
    absent" to "q is ACTIVE". A presence gate (`"q" in request.GET`) is
    strictly stricter and passes the row above too, so only this one catches
    it -- and the loss it prevents is invisible: a no-JS author silently stops
    persisting expansions whenever a stray ?q=a sits in the URL."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    client.get(url, {"q": "a", "open": f"{part.pk},{chap.pk}"})
    stored = client.session.get("builder_open", {}).get(course.slug)
    assert stored == sorted([part.pk, chap.pk])


def test_counts_under_a_filter_are_the_filtered_counts(filtered_course):
    """The toggle promises what the filtered view will actually show."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    # The chapter has two units in full, one under the filter.
    assert "1 item" in body or "1 element" in body
    assert "2 items" not in body
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_filter_views.py -q
```

Expected: FAIL — no `data-applied-q` in the markup.

- [ ] **Step 3: Add `_raw_q` and `FilterContext`**

Add `from dataclasses import dataclass` and `from courses import builder_filter` to the import block at the **top** of `courses/views_manage.py` (E402 rejects a mid-file import; isort is force-single-line). Then, near the other helpers:

```python
def _raw_q(request):
    """POST then GET. Named because NINE non-rendering sites need their own
    read: the six _redirect_to_builder mutation sites, node_delete's GET,
    _move_picker (NOT node_move's GET, which only delegates to it), and
    node_move's mode=="reorder" guard. Without one helper the resolution
    rule is re-expressed ten times.

    Mutation forms carry a hidden `q` in the body; toggles, manage_node_scope
    and manage_tree carry it in the query string. The body wins because the
    JS collector sets it there.
    """
    if "q" in request.POST:
        return request.POST["q"]
    return request.GET.get("q", "")


@dataclass(frozen=True)
class FilterContext:
    """A record, not a tuple: it carries seven things and two of them are
    easy to leave out and expensive to leave out.

    q_raw -- if this is not handed back, all three renderers re-do the
    POST-then-GET read to populate the `q` context key, reinstating the
    resolution rule in three places. It is the RAW value, not the normalized
    one, because a half-typed ?q=a must survive into the input and every href.

    opened AND open_ids -- _tree_context must render from the union with
    effect 1, while _remember_open must read `opened` untouched, or builder()
    persists forced-open pks as though the author had chosen them.
    """

    cmap: dict
    opened: builder_open.OpenSet
    open_ids: frozenset
    shown: int
    total: int
    q_active: bool
    q_raw: str
```

- [ ] **Step 4: Add `_filter_context` and effect 2**

```python
def _filter_context(request, course, cmap, *, mode, extra_open=()):
    """The one owner of q resolution, the restricted map, effect 2 and the
    open set.

    `mode` is required and has no default: the three callers need "page",
    "notice" and "fragment", and open_ids's own default is "fragment" -- so a
    mode-less helper would silently put builder() on the fragment row and
    destroy both the session seed and the <=150-node rule, on the one path
    where they matter.
    """
    q_raw = _raw_q(request)
    restricted, chains, shown, total, q_active = builder_filter.filtered_map(
        cmap, q_raw
    )
    # The chain set when q is ACTIVE, not when it is non-empty: a filter that
    # matches nothing yields an EMPTY chain set, and passing None there would
    # fall through to steps 4-6 (spec 3b).
    opened = _open_ids(
        request, course, cmap, mode=mode, q_chain=chains if q_active else None
    )
    ids = set(opened.ids) | _extra_container_pks(extra_open, cmap)
    _apply_effect_two(restricted, extra_open, cmap)
    return FilterContext(
        cmap=restricted,
        opened=opened,
        open_ids=frozenset(ids),
        shown=shown,
        total=total,
        q_active=q_active,
        q_raw=q_raw,
    )


def _apply_effect_two(restricted, extra_open, full_cmap):
    """Re-insert each forced pk's node into the RESTRICTED map.

    `setdefault`, not `restricted[...]`: _children_map only creates a key for
    a parent that HAS children (views_manage.py:139-141), and the restricted
    map is built by regrouping the kept nodes -- so a matched container with
    no matching descendants has no key of its own, and a filter that matched
    nothing has no None key. Spec 1d ships an add affordance into exactly
    those empty scopes, so "filter for a chapter, add a unit inside it" would
    raise KeyError -> 500.

    Applies to EVERY pk regardless of kind, units included; effect 1 keeps
    the container-only filter. Splitting the kind test across the two effects
    is what makes both pinned requirements satisfiable at once.
    """
    if not extra_open:
        return
    index = builder_open.nodes_by_pk(full_cmap)
    for pk in extra_open:
        node = index.get(pk)
        if node is None:
            continue
        rows = restricted.setdefault(node.parent_id, [])
        if any(existing.pk == node.pk for existing in rows):
            continue  # idempotent: a duplicate row breaks the DOM collector
        rows.append(node)
        rows.sort(key=lambda n: (n.order, n.pk))
```

- [ ] **Step 5: Extend `_tree_context` and add the ceiling helper**

```python
def _tree_context(course, cmap, ids, *, q, filtered, expand_all_disabled, q_min):
    """`cmap` here is the FULL map: _open_descendants builds the descendant
    sets a COLLAPSE href subtracts, and over the restricted map an open
    descendant the filter excluded would survive in the emitted `open` and
    spring back the moment the filter is cleared.
    """
    return {
        "open_ids": ids,
        "open_joined": ",".join(str(p) for p in sorted(ids)),
        "open_descendants": _open_descendants(cmap, ids),
        "builder_url": reverse("courses:manage_builder", kwargs={"slug": course.slug}),
        "q": q,
        "filtered": filtered,
        "expand_all_disabled": expand_all_disabled,
        "q_min": q_min,
    }


def _expand_all_disabled(cmap):
    """Read CEILING THROUGH the module: tests monkeypatch
    courses.builder_open.CEILING, and a by-value import desyncs this guard
    from the patched number -- the same trap _info_entries documents.
    """
    return len(builder_open.container_pks(cmap)) > builder_open.CEILING
```

- [ ] **Step 6: Rewire the three renderers**

`builder()`:

```python
    cmap = _children_map(course)
    fc = _filter_context(request, course, cmap, mode="page")
    _remember_open(request, course, fc.opened, q_active=fc.q_active)
    context = {
        "course": course,
        "children_map": fc.cmap,
        "top_nodes": fc.cmap.get(None, []),
        "info": _info_entries(
            fc.opened, q_active=fc.q_active, shown=fc.shown, total=fc.total
        ),
    }
    context.update(
        _tree_context(
            course,
            cmap,
            fc.open_ids,
            q=fc.q_raw,
            filtered=fc.q_active,
            expand_all_disabled=_expand_all_disabled(cmap),
            q_min=builder_filter.MIN_QUERY,
        )
    )
    return render(request, "courses/manage/builder.html", context)
```

`_builder_with_notice()` (`views_manage.py:730-743`) is **not** the identical
shape — it carries `notice`, passes `status=` to `render`, and must call
neither `_remember_open` nor `_take_builder_force` (a *failed* mutation has
nothing to persist and nothing created to force-include). Written out, because
pasting `builder()`'s body here silently drops the notice:

```python
    cmap = _children_map(course)
    fc = _filter_context(request, course, cmap, mode="notice")
    context = {
        "course": course,
        "children_map": fc.cmap,
        "top_nodes": fc.cmap.get(None, []),
        "notice": message,
        "info": _info_entries(
            fc.opened, q_active=fc.q_active, shown=fc.shown, total=fc.total
        ),
    }
    context.update(
        _tree_context(
            course,
            cmap,                       # the FULL map, always
            fc.open_ids,
            q=fc.q_raw,
            filtered=fc.q_active,
            expand_all_disabled=_expand_all_disabled(cmap),
            q_min=builder_filter.MIN_QUERY,
        )
    )
    return render(request, "courses/manage/builder.html", context, status=status)
```

**Its `_info_entries(opened)` call at `:740` is the one most easily missed**,
and the cost is delayed: Task 5 Step 3 makes `q_active`/`shown`/`total`
keyword-**required**, so a call site left positional becomes a `TypeError` on
every no-JS 409/422 render — a path nothing exercises until Task 6 Step 9 adds
`test_builder_with_notice_under_a_filter_returns_the_chains_open`, one whole
task after the breakage lands.

**All three callers must be rewired in this step.** `_tree_context`'s four new
arguments are keyword-only and defaultless, so `_render_scope`
(`views_manage.py:351`) and `_builder_with_notice` (`:742`) raise `TypeError`
on the first fragment or notice render until they pass them:

```python
    context.update(
        _tree_context(
            course,
            cmap,                       # the FULL map, always
            fc.open_ids,
            q=fc.q_raw,
            filtered=fc.q_active,
            expand_all_disabled=_expand_all_disabled(cmap),
            q_min=builder_filter.MIN_QUERY,
        )
    )
```

On the fragment path `expand_all_disabled` and `q_min` are computed but unused
— `_scope.html` consumes neither, and only `builder.html` emits their
attributes. Passing them anyway keeps one signature rather than two.

`_render_scope()` takes `mode="fragment"`, passes its own `extra_open=extra_open`, and — critically — **`nodes` comes from the RESTRICTED map in both branches**.

**Delete `views_manage.py:330-331` — the existing `opened = _open_ids(...)` and
`ids = set(opened.ids) | _extra_container_pks(extra_open, cmap)` lines.**
`_filter_context` now does both internally, so leaving them costs a second
`_open_ids` resolution and, worse, leaves a live `ids` local that an
implementer will hand to `_tree_context` instead of `fc.open_ids` — silently
dropping effect 1. Nothing catches that: ruff sees a used variable, and the
open set it computes is right on the *unfiltered* path, which is what most
fragment tests exercise. The third argument to `_tree_context` is
**`fc.open_ids`**.

```python
    fc = _filter_context(request, course, cmap, mode="fragment", extra_open=extra_open)
    if scope_ref == "top":
        nodes, updated, parent_kind = (
            fc.cmap.get(None, []),
            course.updated.isoformat(),
            None,
        )
    else:
        parent = ContentNode.objects.filter(pk=scope_ref, course=course).first()
        nodes = fc.cmap.get(int(scope_ref), [])
        updated = parent.updated.isoformat() if parent else course.updated.isoformat()
        parent_kind = parent.kind if parent else None
```

…and the context dict it builds must ALSO carry the restricted map:

```python
    context = {
        "scope_id": scope_ref,
        "scope_updated": updated,
        "parent_kind": parent_kind,
        "nodes": nodes,
        "children_map": fc.cmap,        # RESTRICTED -- the recursive descent
        "course": course,               # and _tree_toggle's counts read this
    }
```

**Both keys, not one.** `_scope.html` iterates `nodes`, **not** `children_map`,
and `_render_scope` builds `nodes` from its own separate read — so swapping only
`children_map` ships a toggle that returns **every** child of the expanded scope
into a filtered pane. But swapping only `nodes` is just as wrong in the other
direction: `_tree_node.html`'s recursive descent and `_tree_toggle.html`'s counts
both read `children_map`, so a fragment would render unfiltered grandchildren
under filtered rows and report unfiltered counts — while the page-render count
test stays green. `parent`, `parent_kind` and `updated` keep resolving against
the full course: a scope's own identity is not a filtering question.

**`_info_entries` needs its interim signature in THIS task, not Task 5.** The
shipped one is `_info_entries(opened)` (`views_manage.py:355`), and the
`builder()` snippet above already calls it with three keywords — so "Task 5
gives it its body" must not be read as "defer it". Without this edit every row
of Step 8's three-suite gate dies on `TypeError: _info_entries() got an
unexpected keyword argument 'q_active'`, including the `_builder_with_notice`
and `_render_scope` paths. Widen the signature now and leave the body alone:

```python
def _info_entries(opened, *, q_active=False, shown=0, total=0):
    """Interim: accepts the filter keywords but still emits only the
    truncation entry. Task 5 Step 3 replaces the body, adds the `code` key
    and DROPS these defaults (by then all three call sites pass them)."""
    # ... existing truncation-only body, unchanged ...
```

The defaults are what keep this task self-contained; Task 5 removes them.

- [ ] **Step 7: Emit three of the four `data-*` attributes**

On `.builder` in `templates/courses/manage/builder.html`:

```html
         data-applied-q="{{ q }}"
         data-q-min="{{ q_min }}"
         {% if expand_all_disabled %}data-expand-all-disabled{% endif %}
```

`data-applied-q` and `data-q-min` are **unconditional**. `data-expand-all-disabled` is emitted **by presence** and read with `hasAttribute` — the value form renders the string `"False"`, which is truthy in JS, so the bail would fire on every course and expand-all would be silently dead everywhere. (`data-tree-url` waits for Task 4's route.)

- [ ] **Step 8: Run the tests**

```bash
uv run pytest tests/test_builder_filter_views.py tests/test_builder_lazy_scopes.py tests/test_manage_builder.py -q
```

Expected: PASS, exit 0.

- [ ] **Step 9: Falsify two guards**

Both real red gates land later (Tasks 7 and 11), so this step needs its own
runnable ones — "confirm by hand" is not a falsification. Write these two rows
into `tests/test_builder_filter_views.py` **now**, as part of this task; Tasks
7 and 11 then add the user-visible versions on top.

```python
def test_effect_two_reinserts_into_a_parent_with_no_key(filtered_course):
    """Task 3's own red gate for `setdefault`. Direct on the helper, because
    the user-visible route (a no-JS add into an empty filtered scope) is not
    wired until Task 7. `chap` matches "rozdzial" and has no matching
    descendant, so the restricted map has NO key for it at all.
    """
    # `courses` sorts BEFORE `courses.views_manage`. ruff's I rules apply to
    # nested blocks too, and `ruff format` does not reorder imports -- pasted
    # the other way round this is an I001 at Step 10's `ruff check` gate,
    # which the commit depends on. (Verified: I001 fires on the nested block.)
    from courses import builder_filter
    from courses.views_manage import _apply_effect_two
    from courses.views_manage import _children_map

    _, course, part, chap, hit, miss = filtered_course
    cmap = _children_map(course)
    restricted, *_ = builder_filter.filtered_map(cmap, "rozdzial")
    assert chap.pk not in restricted, "fixture drifted; the row proves nothing"
    _apply_effect_two(restricted, (hit.pk,), cmap)
    assert [n.pk for n in restricted[chap.pk]] == [hit.pk]


def test_a_filtered_scope_fragment_returns_only_matching_children(filtered_course):
    """Task 3's own red gate for `nodes` AND `children_map` both coming from
    the RESTRICTED map. Task 11's e2e drives this through the browser; this
    drives the endpoint directly, in the commit that introduces the bug.

    Request PART's scope, not the chapter's. The chapter's children are units
    with no children of their own, so `children_map` is never read on that
    path and the second falsification below cannot go red. From `part`:
      * `nodes`        -> part's children: chapter "Rozdzial", NOT "Pusty"
      * `children_map` -> the recursive descent into Rozdzial: `hit`, not `miss`
    Under q=trygo the fragment carries no `open`, so precedence step 3 resolves
    to the chains {part, chap} and the descent actually happens (spec 3b).
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse(
        "courses:manage_node_scope", kwargs={"slug": course.slug, "pk": part.pk}
    )
    text = client.get(
        url, {"q": "trygo"}, **{"HTTP_X_REQUESTED_WITH": "fetch"}
    ).content.decode()
    assert f'data-node="{chap.pk}"' in text
    assert f'data-node="{hit.pk}"' in text, "the descent did not happen; row is vacuous"
    assert f'data-node="{miss.pk}"' not in text   # children_map is restricted
    assert "Pusty" not in text                    # nodes is restricted
```

Then falsify:

1. Change `_apply_effect_two`'s `setdefault` to `restricted[node.parent_id]` →
   `test_effect_two_reinserts_into_a_parent_with_no_key` must fail with
   `KeyError`.
2. Point `_render_scope`'s `nodes` back at `cmap` instead of `fc.cmap` → the
   same row must fail on the **`"Pusty"`** assertion. Restore it, then point
   `children_map` back at `cmap` instead → it must fail on the **`miss`**
   assertion. Two separate mutations, two different assertions: that is what
   proves Step 6's "both keys, not one" rather than assuming it.
3. **The `_remember_open` `q_active` gate**, which is the slice's only
   silent-data-loss guard and is falsified nowhere else — Task 2 Step 6
   mutates the `q_chain` ordering, not the gate. Two mutations, two rows:
   - Drop `q_active or` from `_remember_open`'s early return →
     `test_remember_open_does_NOT_write_while_a_filter_is_active` must fail;
     the filter's derived chains get written over the author's real expansion,
     permanently, since the no-JS path has no stash.
   - Restore, then change the gate to
     `if "q" in request.GET or not opened.explicit:` →
     `test_remember_open_DOES_write_under_a_below_floor_q` must fail. A
     presence gate is strictly stricter, so it passes the first row too; only
     this second mutation catches it, and the loss it prevents is invisible.

Restore each. Confirm the exact route name against `courses/urls.py:169`
before running — the row is worthless if it 404s.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/views_manage.py templates/courses/manage/builder.html tests/test_builder_filter_views.py
git commit -m "feat(builder): FilterContext — one q resolution, restricted map, effect 2"
```

---

## Task 4: `manage_tree` — the endpoint the filter swaps through

**Files:**
- Modify: `courses/urls.py`
- Modify: `courses/views_manage.py`
- Modify: `templates/courses/manage/builder.html`
- Test: `tests/test_builder_filter_views.py`

**Interfaces:**
- Consumes: `_render_tree`, `_require_manage` (slice 1).
- Produces: route `courses:manage_tree` at `…/build/tree/`; `data-tree-url` on `.builder`.

- [ ] **Step 1: Write the failing tests**

First add the import this task's first row needs, at the **top** with the
existing block (`E402`; isort is force-single-line). Task 3 deliberately left
it out because nothing used it there yet, and an unused import fails that
task's `ruff check`:

```python
from django.test import Client
```

Then append to `tests/test_builder_filter_views.py`:

```python
def test_manage_tree_access_control(filtered_course):
    """The same rows as manage_node_scope MINUS the pk row -- four in total.
    NOT 'non-numeric pk -> 404': this route has no pk, so such a test would
    guard nothing (the resolver would 404 before the view ran)."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})

    assert Client().get(url).status_code in (301, 302)

    other = Client()
    make_login(other, "nobody")
    assert other.get(url).status_code == 403

    assert client.get(url).status_code == 200

    missing = reverse("courses:manage_tree", kwargs={"slug": "no-such-course"})
    assert client.get(missing).status_code == 404


def test_manage_tree_returns_the_top_scope_and_nothing_else(filtered_course):
    """applyFragment consumes firstElementChild; returning .builder__tree
    with its header would break that single-element contract."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    body = client.get(url).content.decode().strip()
    assert body.startswith("<ol")
    assert 'data-scope="top"' in body
    assert "builder__tree" not in body


def test_manage_tree_honours_q(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    assert f'data-node="{hit.pk}"' in body
    assert f'data-node="{miss.pk}"' not in body
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_filter_views.py -q -k manage_tree
```

Expected: FAIL — `NoReverseMatch: Reverse for 'manage_tree' not found`.

- [ ] **Step 3: Add the view**

In `courses/views_manage.py`, beside `node_scope`:

```python
@login_required
def manage_tree(request, slug):
    """The whole top scope, as a fragment, for the filter and expand-all.

    builder() returns a full page and is the only builder view with no
    _wants_fragment branch; manage_node_scope is declared <int:pk> so it
    cannot serve the top scope. Adding a fragment branch to builder() would
    silently change its contract for every existing test that sends
    X-Requested-With: fetch.
    """
    course = _require_manage(request, slug)
    return _render_tree(request, course)
```

- [ ] **Step 4: Add the route**

In `courses/urls.py`, beside `manage_node_scope`:

```python
    path(
        "manage/courses/<slug:slug>/build/tree/",
        views_manage.manage_tree,
        name="manage_tree",
    ),
```

- [ ] **Step 5: Emit `data-tree-url`**

Add to `.builder` in `templates/courses/manage/builder.html`:

```html
         data-tree-url="{% url 'courses:manage_tree' slug=course.slug %}"
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_builder_filter_views.py -q
```

Expected: PASS.

- [ ] **Step 7: Falsify**

Replace `_require_manage(request, slug)` with `get_object_or_404(Course, slug=slug)` → the non-manager row must fail (200 instead of 403). Restore.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/urls.py courses/views_manage.py templates/courses/manage/builder.html tests/test_builder_filter_views.py
git commit -m "feat(builder): manage_tree endpoint + data-tree-url"
```

---

## Task 5: `X-Builder-Info` and the always-present info slot

**Files:**
- Modify: `courses/views_manage.py` (`_info_entries`, `_render_scope`)
- Modify: `templates/courses/manage/builder.html`
- Modify: `courses/static/courses/css/builder.css`
- Test: `tests/test_builder_filter_views.py`

**Interfaces:**
- Consumes: `FilterContext` (Task 3).
- Produces: `_info_entries(opened, *, q_active, shown, total) -> list[dict]` where each dict has `key`, `text`, `code`; `X-Builder-Info` on **every** `_render_scope` response.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_builder_filter_views.py`:

```python
def test_render_scope_always_sets_the_header_and_uses_none_when_empty(filtered_course):
    """`none` rather than an absent header: the client cannot otherwise tell a
    rename 200 (must NOT clear) from a code-less scope response (must clear).
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    assert client.get(url)["X-Builder-Info"] == "none"
    filtered = client.get(url, {"q": "trygo"})
    assert filtered["X-Builder-Info"] == "filter;shown=1;total=1"


def test_the_header_is_machine_readable_under_the_polish_locale(
    filtered_course, monkeypatch
):
    """A human string in the header would reach the JS as a value it then
    pastes into a role=status region, in whatever locale the request happened
    to use -- and `raw.split(", ")` would shred it into bogus keys.

    CEILING=0 forces the TRUNCATION entry alongside the filter one, and it is
    the only notice whose Polish contains a non-ASCII character
    ("...zakresów."). Without it this row cannot fail: "Filtrowane: 1 / 1" is
    pure ASCII, so an implementation that put the human text in the header
    would still satisfy every assertion below.

    Note what actually bites: `ó` IS latin-1-encodable, so Django does NOT
    MIME-encode it -- the header simply comes back non-ASCII. `isascii()` is
    the load-bearing assertion; the `=?utf-8?` one covers the strings that are
    not latin-1-encodable.
    """
    monkeypatch.setattr("courses.builder_open.CEILING", 0)
    client, course, *_ = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    # The session key, NOT `with override("pl")` and NOT Accept-Language
    # alone. Two middlewares/signals stack against both:
    #   * core.middleware.SessionLocaleMiddleware (installed at
    #     config/settings/base.py:48) calls translation.activate per request
    #     (core/middleware.py:48-54), discarding an ambient `override`.
    #   * `make_login` calls force_login, which fires user_logged_in, and
    #     core/signals.py:14-21 seeds session["_language"] from user.language
    #     -- which accounts/models.py:28 defaults to "en". That key is what
    #     SessionLocaleMiddleware PREFERS (core/middleware.py:49-51), so it
    #     never reaches Accept-Language at all.
    # So Accept-Language alone renders `en` and the Content-Language guard
    # below goes red. Seed the session, exactly as
    # tests/test_builder_lazy_scopes.py:634-641 already does.
    session = client.session
    session["_language"] = "pl"
    session.save()
    resp = client.get(
        url, {"q": "trygo"}, HTTP_ACCEPT_LANGUAGE="pl", **{"HTTP_X_REQUESTED_WITH": "fetch"}
    )
    # Content-Language alone: this response is a bare <ol> fragment, so the
    # "Filtrowane" notice (which lives in builder.html's info slot) is never
    # part of it. core/middleware.py:43 subclasses LocaleMiddleware, whose
    # process_response sets this header.
    assert resp["Content-Language"] == "pl", (
        "the Polish locale is not actually active; the assertions below would "
        "be vacuous"
    )
    value = resp["X-Builder-Info"]
    assert value.isascii()
    assert "=?utf-8?" not in value


def test_a_rename_and_a_422_carry_no_header_at_all(filtered_course):
    """They never reach _render_scope, so they neither set nor clear."""
    client, course, part, chap, hit, miss = filtered_course
    rename = reverse("courses:manage_node_rename", kwargs={"slug": course.slug})
    resp = client.post(
        rename,
        {"node": hit.pk, "token": hit.updated.isoformat(), "title": "Nowy", "q": "trygo"},
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200
    assert "X-Builder-Info" not in resp

    # the 422 half the test's name promises: an empty title is rejected by the
    # form, and _op_error.html never reaches _render_scope either
    bad = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": course.slug}),
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "",
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert bad.status_code == 422
    assert "X-Builder-Info" not in bad


def test_the_info_slot_is_present_and_empty_on_an_unfiltered_page(filtered_course):
    """Present, not hidden, and with NO text content: `:empty` does not match
    an element containing whitespace, and one newline leaves a sunken grey bar
    on every builder page, permanently."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert 'class="builder__info"' in body
    assert "hidden" not in body.split('class="builder__info"')[1].split(">")[0]
    marker = body.split('class="builder__info"')[1]
    open_tag_end = marker.index(">")
    assert marker[open_tag_end + 1 : open_tag_end + 6].startswith("</ul>")


def test_a_server_rendered_notice_is_visible_without_js(filtered_course):
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    assert 'data-info-key="filter"' in body
```

No `override` import is needed — the locale is driven through the request.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_filter_views.py -q -k \
  "always_sets_the_header or machine_readable or info_slot_is_present or notice_is_visible"
```

Expected: a **mixed** run. RED: the three rows above (`KeyError:
'X-Builder-Info'` for the first two, no `data-info-key` for the third and
fourth). `test_a_rename_and_a_422_carry_no_header_at_all` is deliberately
**not** selected — it asserts the header is *absent*, so it is already green
before Steps 3-4 exist and would blur the gate, exactly as in Tasks 6, 8 and 9.

- [ ] **Step 3: Rewrite `_info_entries`**

**Dropping Task 3's defaults makes the three keywords required, so confirm all
three call sites already pass them before you do it** — `builder()`,
`_builder_with_notice()` (`:740`) and `_render_scope` (Step 4 below). Task 3
Step 6 rewires the first two; a positional survivor becomes a `TypeError` on
the path it serves, and only `_builder_with_notice`'s is covered by a test in
this plan.

```python
def _info_entries(opened, *, q_active, shown, total):
    """Keyed, so an incoming entry REPLACES rather than stacks.

    ONE WORD PER CONCEPT: the info key, the header code prefix and the
    data-msg-* suffix are the same token. Three near-synonyms would force the
    JS to carry a prefix->key map that lives nowhere, and a registry keyed off
    the code prefix would never match the server-rendered
    data-info-key="truncation" entry -- appending a second copy, which is the
    bug the read-on-init rule exists to close.

    ONE MSGID per notice: the same literal appears here and in the
    data-msg-<key> attribute, deliberately, so makemessages collapses them.
    Two entries would let the page and the fragment route disagree.
    """
    entries = []
    if opened.truncated:
        entries.append(
            {
                "key": "truncation",
                "code": f"truncation;limit={builder_open.CEILING}",
                "text": _("Only the first %(limit)s scopes were opened.")
                % {"limit": builder_open.CEILING},
            }
        )
    if q_active:
        # Emitted whenever q is active, INCLUDING shown == total == 0:
        # "Filtered: 0 / 0" over an empty tree is the only explanation the
        # author gets.
        entries.append(
            {
                "key": "filter",
                "code": f"filter;shown={shown};total={total}",
                "text": _("Filtered: %(shown)s / %(total)s")
                % {"shown": shown, "total": total},
            }
        )
    return entries
```

- [ ] **Step 4: Set the header in `_render_scope`**

At the end of `_render_scope`, after the `render(...)` call:

```python
    resp = render(request, "courses/manage/_scope.html", context)
    entries = _info_entries(
        fc.opened, q_active=fc.q_active, shown=fc.shown, total=fc.total
    )
    # ALWAYS set, `none` when nothing applies. The parent spec pairs "absent
    # when none apply" with "an absent header clears all keys", and the client
    # cannot implement that pair: the submit handler serves both a rename
    # (_rename_result.html, no header, must NOT clear) and an add (a scope, no
    # codes, MUST clear), and those are byte-identical from its side.
    resp["X-Builder-Info"] = ", ".join(e["code"] for e in entries) or "none"
    return resp
```

- [ ] **Step 5: Make the slot always present**

Replace `builder.html:23` with a **single line, no whitespace inside the element**:

```html
    <ul class="builder__info" role="status" data-info>{% for entry in info %}<li data-info-key="{{ entry.key }}">{{ entry.text }}</li>{% endfor %}</ul>
```

No `hidden` attribute: a server-set `hidden` makes every server-rendered notice invisible without JS and regresses slice 1's shipped truncation notice.

Add to `courses/static/courses/css/builder.css`:

```css
/* :empty, not [hidden] -- a render-time hidden attribute would hide every
   SERVER-rendered notice from a no-JS author. The one-line markup above is
   load-bearing: :empty does not match an element containing whitespace, and
   the server's text nodes would survive the JS's <li> removals, leaving a
   permanent sunken bar. */
.builder__info:empty { display: none; }
```

- [ ] **Step 6: Add the two message templates**

On `.builder` in `builder.html` — **the same msgid as the Python literals above**:

```html
         data-msg-truncation="{% trans 'Only the first %(limit)s scopes were opened.' %}"
         data-msg-filter="{% trans 'Filtered: %(shown)s / %(total)s' %}"
```

Both are phrased so **no varying numeral governs a noun** — "Filtered: 100 / 940", never "showing 100 results", because the latter needs a plural form JS cannot select.

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/test_builder_filter_views.py tests/test_builder_lazy_scopes.py -q
```

Expected: PASS.

- [ ] **Step 8: Falsify**

1. Change `or "none"` to `or ""` and drop the header when empty → `test_render_scope_always_sets_the_header_and_uses_none_when_empty` must fail.
2. Put the `<ul>` back behind `{% if info %}` → `test_the_info_slot_is_present_and_empty_on_an_unfiltered_page` must fail.
3. Insert a newline inside the `<ul>` → the same test must fail on the `</ul>` adjacency assertion.
4. Build the header from the human text instead of the code — i.e.
   `", ".join(e["text"] for e in entries)` in Step 4 →
   `test_the_header_is_machine_readable_under_the_polish_locale` must fail on
   `value.isascii()`.

   **The truncation monkeypatch in that row is what makes this bite.** The
   filter notice's Polish is `"Filtrowane: %(shown)s / %(total)s"` → rendered
   `"Filtrowane: 1 / 1"`, which is **pure ASCII** — so with only that entry
   present the mutation produces an ASCII header and the row stays green. The
   only non-ASCII string `_info_entries` can emit is the truncation one
   (`"Otwarto tylko pierwsze %(limit)s zakresów."`), and `filtered_course` is
   nowhere near the ceiling, so it never fires on its own.

Restore all four.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/views_manage.py templates/courses/manage/builder.html courses/static/courses/css/builder.css tests/test_builder_filter_views.py
git commit -m "feat(builder): X-Builder-Info header + always-present info slot"
```

---

## Task 6: `q` on the no-JS path — forms, hrefs, redirects, the picker

**Files:**
- Modify: `templates/courses/manage/_tree_node.html`, `_scope.html`, `_add_affordance.html`, `_move_buttons.html`, `node_confirm_delete.html`, `_move_picker.html`
- Modify: `courses/templatetags/courses_manage_extras.py` (`toggle_href`)
- Modify: `courses/views_manage.py` (`_redirect_to_builder`, `node_delete`, `node_move` GET)
- Test: `tests/test_builder_filter_views.py`

**Interfaces:**
- Consumes: `_raw_q` (Task 3); the `q` and `filtered` context keys (Task 3).
- Produces: `_redirect_to_builder(course, q="")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_toggle_hrefs_preserve_q(filtered_course):
    """Sliced to the TOGGLE anchor specifically.

    A bare `assert "q=trygo" in body` is vacuous: Step 5 puts `&q=trygo` into
    the delete and Move href of every rendered row (and Task 9 adds two bulk
    hrefs), so it passes with the toggle_href edit reverted entirely. Nothing
    else in this plan can go red against that, which is how an unguarded edit
    ships.
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    # The toggle is an <a> whose href toggle_href builds and which ends
    # `#node-<pk>`; slice backwards from its data-toggle hook to that anchor's
    # own `href="`.
    marker = f'data-toggle="{chap.pk}"'
    assert marker in body, "the chapter toggle did not render; the row proves nothing"
    tag = body[body.rindex("<a", 0, body.index(marker)) : body.index(marker)]
    assert "q=trygo" in tag, tag
    assert f"#node-{chap.pk}" in tag, "not the toggle anchor -- re-derive the slice"


def test_markup_hrefs_percent_encode_q(filtered_course):
    """Django autoescapes HTML but does NOT percent-encode. A query with an
    `&` splits into a second parameter -- filtering for `x&open=all` makes the
    delete-confirm GET arrive with open=all attached -- and a `#` truncates
    the href outright."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    # The query must BOTH contain `&`/space AND FOLD INTO a title. A query
    # that matches nothing renders an empty restricted map, `_scope.html`
    # takes {% empty %}, no _tree_node.html is included -- so there is no
    # delete or Move href in the response at all and the falsification is
    # unreachable. `hit` is titled "Trygonometria & wektory" for this row.
    # MEASURED, not eyeballed. Two earlier drafts of this row shipped a query
    # that matched NOTHING: fold("tryg & wek") is not a substring of
    # fold("Trygonometria & wektory"), because `tryg` is followed by
    # `onometria`. Check any replacement the same way -- run
    # `fold(q) in fold(title)` and require True -- rather than by reading it.
    body = client.get(url, {"q": "metria & wek"}).content.decode()
    assert f'data-node="{hit.pk}"' in body, "no row rendered; the row proves nothing"
    # space -> %20 or +, & -> %26; the raw `&` must NOT survive into the href
    assert "q=metria%20%26%20wek" in body or "q=metria+%26+wek" in body
    # The template writes `&amp;q=`, so THAT is what the HTML source holds.
    delete_href = body.split('data-delete="')[0].rsplit('href="', 1)[1]
    assert "&amp;q=" in delete_href
    assert "& wek" not in delete_href


def test_the_six_redirect_sites_carry_q(filtered_course):
    """One assertion per SITE, not one site standing for six.

    The four non-rename sites are otherwise unguarded by anything in this
    plan: Task 7's rows that follow those same redirects assert a row is
    PRESENT, which is equally true of a fully unfiltered render -- so dropping
    `_raw_q(request)` at node_add (:489), node_move reorder (:585), node_move
    reparent (:621) or node_duplicate (:715) would pass every other row here.
    """
    client, course, part, chap, hit, miss = filtered_course
    rename = reverse("courses:manage_node_rename", kwargs={"slug": course.slug})
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    dup = reverse("courses:manage_node_duplicate", kwargs={"slug": course.slug})

    delete = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})

    def tok(node):
        """Every mutation bumps `updated`, so read the token immediately
        before the post that uses it -- a token captured up front is stale by
        the second iteration and the row 409s instead of redirecting."""
        node.refresh_from_db()
        return node.updated.isoformat()

    def check(label, url, payload, q="trygo"):
        payload["q"] = q
        resp = client.post(url, payload)
        assert resp.status_code == 302, f"{label}: {resp.status_code}"
        assert "open=session" in resp["Location"], label
        assert f"q={q}" in resp["Location"], label

    check("rename", rename, {"node": hit.pk, "token": tok(hit), "title": "Nowy"})
    check("add", add, {
        "parent": chap.pk, "parent_token": tok(chap),
        "kind": "unit", "unit_type": "lesson", "title": "Dodana",
    })
    # BELOW the floor here only: Task 8 refuses a reorder under an ACTIVE
    # filter with 422, so q=trygo would assert against the refusal, not the
    # redirect. `miss` is not the first child, so "up" is a real move.
    check("reorder", move,
          {"mode": "reorder", "node": miss.pk, "direction": "up",
           "token": tok(miss)}, q="a")
    check("reparent", move,
          {"mode": "reparent", "node": miss.pk, "new_parent": part.pk,
           "position": 0, "node_token": tok(miss)})
    check("duplicate", dup, {"node": hit.pk, "token": tok(hit)})
    # LAST, and the sixth site: node_delete's NON-bespoke branch, i.e. no
    # `open` in the POST. The bespoke `open`-carrying branch is
    # test_node_delete_bespoke_redirect_carries_q.
    check("delete", delete, {"node": miss.pk, "token": tok(miss)})


def test_node_delete_bespoke_redirect_carries_q(filtered_course):
    """views_manage.py:672-675 builds its own redirect rather than going
    through _redirect_to_builder, and it is the JS-REWRITTEN path: a no-JS
    confirm POST carries no `open` and takes :675 instead. Driving this as a
    no-JS delete would go green on the six-site edit alone while :674 kept
    dropping q for every JS author."""
    client, course, part, chap, hit, miss = filtered_course
    delete = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    resp = client.post(
        delete,
        {"node": miss.pk, "token": miss.updated.isoformat(), "open": str(chap.pk), "q": "trygo"},
    )
    assert resp.status_code == 302
    assert "q=trygo" in resp["Location"]


def test_the_no_js_move_picker_round_trip_stays_filtered(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    picker = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    body = client.get(picker, {"node": hit.pk, "q": "trygo"}).content.decode()
    assert 'name="q"' in body
    assert 'value="trygo"' in body


def test_every_tree_form_carries_a_hidden_q(filtered_course):
    """Step 4's edit is the most-repeated one in this task and the whole no-JS
    story rests on it, yet nothing else can observe it: every other row POSTs
    `q` in the payload BY HAND, so all four forms could ship without the input
    and the suite would stay green while a no-JS author loses the filter on
    every rename, add, reorder and duplicate.

    Asserted per FORM, not once over the body -- a single hidden input
    anywhere would otherwise satisfy all four.
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo", "open": "all"}).content.decode()
    forms = {
        "rename": 'class="tree__rename"',
        "add": 'class="tree__add"',
        "reorder": 'data-op="reorder"',
        "duplicate": 'data-op="duplicate"',
    }
    for label, marker in forms.items():
        assert marker in body, f"{label}: form absent; the row proves nothing"
        frag = body.split(marker, 1)[1].split("</form>", 1)[0]
        assert 'name="q"' in frag and 'value="trygo"' in frag, label


def test_the_delete_confirm_round_trip_stays_filtered(filtered_course):
    """The GET nothing else reaches. Both other delete rows POST straight to
    manage_node_delete, so `node_confirm_delete.html`'s hidden input, its
    Cancel href and node_delete's GET context key are all unguarded -- and if
    the context key is forgotten, `{{ q }}` renders empty, the {% if q %}
    input disappears, and the confirm POST silently drops the filter.
    """
    client, course, part, chap, hit, miss = filtered_course
    confirm = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    body = client.get(confirm, {"node": miss.pk, "q": "trygo"}).content.decode()

    # 1. the hidden input the confirm POST will carry
    form = body.split("<form", 1)[1].split("</form>", 1)[0]
    assert 'name="q"' in form and 'value="trygo"' in form

    # 2. the Cancel href. No `open` in the GET, so the template takes its
    #    `{% else %}?open=session{% endif %}` arm and `q` appends with `&`.
    assert "?open=session&amp;q=trygo" in body

    # 3. the POST that form makes -- the filter must survive the redirect
    resp = client.post(
        confirm, {"node": miss.pk, "token": miss.updated.isoformat(), "q": "trygo"}
    )
    assert resp.status_code == 302
    assert "q=trygo" in resp["Location"]


def test_an_empty_filtered_scope_says_no_matching_titles(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    filtered = client.get(url, {"q": "rozdzial"}).content.decode()
    assert "No matching titles." in filtered or "Brak pasuj" in filtered
    plain = client.get(url, {"open": "all"}).content.decode()
    assert "No children yet." in plain or "Nie ma jeszcze" in plain
```

- [ ] **Step 2: Run to verify failure**

Select the six new rows **by name**. `-k` is a substring match over the whole
test id, so a bare `-k "q"` also drags in every already-green Task 3/4/5 row
whose name happens to contain a `q` (`test_data_applied_q_…`,
`test_a_below_floor_query_…`, `test_data_q_min_…`, `test_manage_tree_honours_q`
…) — the red gate is still in there, but buried, and "expected red" becomes
indistinguishable from "regression":

```bash
uv run pytest tests/test_builder_filter_views.py -q -k \
  "preserve_q or percent_encode_q or redirect_sites or bespoke_redirect \
   or move_picker_round_trip or no_matching_titles \
   or every_tree_form or delete_confirm_round_trip"
```

Expected: all eight FAIL — no `q=trygo` anywhere in the markup.

- [ ] **Step 3: `toggle_href` preserves `q`**

In `courses/templatetags/courses_manage_extras.py`, in `toggle_href`, replace the `urlencode` call:

```python
    params = {"open": joined}
    q = context.get("q") or ""
    if q:
        params["q"] = q          # omitted entirely when blank -- one saved
                                 # parameter on every container toggle href
    query = urlencode(params)
    return f"{context.get('builder_url', '')}?{query}#node-{node.pk}"
```

`urlencode` percent-encodes, which is why the toggle href needs no separate escaping rule.

- [ ] **Step 4: Hidden `q` in every tree form**

In `_tree_node.html` (the rename form and the unit duplicate form), `_add_affordance.html` and `_move_buttons.html`, add inside each `<form>`:

```html
      {% if q %}<input type="hidden" name="q" value="{{ q }}">{% endif %}
```

`{% if q %}` — value-gated, never presence-gated. Unconditional emission would add an empty hidden input to 944 rename + 944 reorder + 807 duplicate + 138 add forms on `mat-pp` under `open=all`, on a page this work exists to shrink. Because `q` is value-gated, an absent input and an empty one are the same thing.

- [ ] **Step 5: Percent-encode `q` in the two markup hrefs**

In `_tree_node.html`, the delete and Move links:

```html
      <a class="ica" href="{{ move_url }}?node={{ node.pk }}{% if q %}&amp;q={{ q|urlencode }}{% endif %}" data-move="{{ node.pk }}" ...>
      <a class="ica ica--danger" href="{{ delete_url }}?node={{ node.pk }}{% if q %}&amp;q={{ q|urlencode }}{% endif %}" data-delete="{{ node.pk }}" ...>
```

`{{ q|urlencode }}`, never bare `{{ q }}`: these are hand-built hrefs rather than `urlencode` dicts, and Django autoescapes HTML but does not percent-encode.

**`builder.js:524-530`'s click-time rewrite deliberately does NOT touch `q`.**
On every transition where `q` ends up **active**, the whole top scope is
re-rendered through `manage_tree`, so the markup value is current by
construction. The one path that skips the fetch — Task 11's
`if (eff === effectiveQ(pendingQ))` branch, e.g. typing `a` into an unfiltered
box, or clearing a `?q=a` — leaves these hrefs holding the previous value, but
that value is **below the floor and therefore inert**: the server renders
unfiltered either way. Setting `q` at click time would add a sixth
`q`-writing client path on the one gesture that is a full-page navigation, to
fix nothing.

- [ ] **Step 6: The filter-aware empty message**

In `_scope.html`:

```html
  {% empty %}
    <li class="tree__empty">{% if filtered %}{% trans "No matching titles." %}{% else %}{% trans "No children yet." %}{% endif %}</li>
```

Without this, an author who mistypes a query is told their **course** is empty.

- [ ] **Step 7: `q` on the redirects**

`_redirect_to_builder` takes `q` as an argument rather than reading the request — it has **eight** callers, and `element_move` (`:861`) and `element_delete` (`:877`) are two the parent spec deliberately excludes from the `q` rule:

```python
def _redirect_to_builder(course, q=""):
    """The ONLY places allowed to emit the open=session sentinel.

    `q` is passed IN, not read from the request: this helper has EIGHT
    callers, and element_move/element_delete are excluded from the q rule by
    the parent spec. Reading `request` here would silently extend the rule to
    two editor-originated redirects nobody asked to change.
    """
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    params = {"open": "session"}
    if q:
        params["q"] = q
    return redirect(f"{url}?{urlencode(params)}")
```

The six mutation sites pass `_raw_q(request)`; the two element sites pass nothing.

`node_delete`'s bespoke branch (`:672-675`) needs its own edit:

```python
        if "open" in request.POST:
            url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
            params = {"open": request.POST["open"]}
            q = _raw_q(request)
            if q:
                params["q"] = q
            return redirect(f"{url}?{urlencode(params)}")
        return _redirect_to_builder(course, _raw_q(request))
```

- [ ] **Step 8: The delete-confirm form and the Move picker**

In `node_confirm_delete.html`, beside the existing hidden `open`:

```html
      {% if q %}<input type="hidden" name="q" value="{{ q }}">{% endif %}
```

**Value-gated, not presence-gated.** The neighbouring `open` uses an `open_present` flag because absent-vs-empty is meaningful for `open`; it is not for `q`, and a `q_present` twin would be a flag nothing consumes. Its Cancel link needs its own `q` too. `node_confirm_delete.html:18` currently
reads `{% if open_present %}?open={{ open|urlencode }}{% else %}?open=session{% endif %}`;
both branches already emit a `?`, so `q` appends with `&` in either case.
**Keep the `{% url %}` tag — do NOT substitute `{{ builder_url }}`:** that key
comes from `_tree_context`, and `node_delete`'s GET context
(`views_manage.py:645-656`) is `{course, node, counts, open_present, open}`, so
the variable would render empty and Cancel would point back at the
delete-confirm path. Only the `q` clause is new.

```html
    href="{% url 'courses:manage_builder' slug=course.slug %}{% if open_present %}?open={{ open|urlencode }}{% else %}?open=session{% endif %}{% if q %}&amp;q={{ q|urlencode }}{% endif %}"
```

`node_delete`'s GET puts `_raw_q(request)` in its context (`:645-656`), beside
the existing `open_present`/`open` keys:

```python
        "q": _raw_q(request),
```

**For the picker the edit site is `_move_picker` (`views_manage.py:797-807`),
not `node_move`** — `node_move`'s GET branch (`:625-627`) only delegates, so an
implementer editing there finds nothing to change and the picker row stays red.
Add the same key to the render dict it builds:

```python
            "children_map": cmap,       # unchanged -- see the warning below
            "nodes_top": cmap.get(None, []),
            "q": _raw_q(request),       # new
```

`_move_picker.html`'s reparent form then carries it as a hidden input, beside
the existing `node_token` at `:6` — value-gated, like every other `q` input in
this task:

```html
  {% if q %}<input type="hidden" name="q" value="{{ q }}">{% endif %}
```

**While you are in that context dict: its `children_map` (`:804`) and
`nodes_top` (`:805`) must stay the FULL map.** So must `link_picker`'s
`children_map`/`top_nodes` (`:275`). These are *destination candidate* lists and
the slot positions the numeric `position` field indexes into — restricting them
would make the picker compute positions against a filtered child list, and
offering only matching destinations would leave a filtered author unable to move
anything out of the match set. This is the one place the spec calls the risk
live rather than theoretical, precisely because the `q` edit lands one line
away.

- [ ] **Step 9: Add the two view-level halves of the precedence fix**

The unit tests above pin `open_ids`. Both *paths* need pinning too, because
the sentinel one is the common one and would stay broken if only the notice
one were covered. Append to `tests/test_builder_lazy_scopes.py`:

```python
def test_a_no_js_mutation_SUCCESS_under_a_filter_returns_the_chains_open(client, db):
    """The redirect lands on ?open=session&q=..., and step 1 fires before
    step 3 in the shipped code -- so without the restructure the author gets
    their stored PRE-FILTER set over a filtered map."""
    owner = make_login(client, "pa")
    course, part, chap, hit = _deep_course(owner)
    session = client.session
    session[OPEN_KEY] = {course.slug: []}          # populated, and NOT the chains
    session.save()
    rename = reverse("courses:manage_node_rename", kwargs={"slug": course.slug})
    resp = client.post(
        rename,
        {"node": hit.pk, "token": hit.updated.isoformat(), "title": "Nowy", "q": "nowy"},
    )
    body = client.get(resp["Location"]).content.decode()
    assert f'data-scope="{chap.pk}"' in body       # the chain is OPEN


def test_builder_with_notice_under_a_filter_returns_the_chains_open(client, db):
    owner = make_login(client, "pa")
    course, part, chap, hit = _deep_course(owner)
    session = client.session
    session[OPEN_KEY] = {course.slug: []}
    session.save()
    rename = reverse("courses:manage_node_rename", kwargs={"slug": course.slug})
    resp = client.post(
        rename,
        {"node": hit.pk, "token": "stale-token", "title": "Nowy", "q": "trygo"},
    )
    assert resp.status_code == 409
    assert f'data-scope="{chap.pk}"' in resp.content.decode()


def test_step_2_still_beats_step_3(client, db):
    """A no-JS toggle href under a filter carries a real enumeration, and it
    must win -- the half a move-step-3-to-the-top implementation breaks."""
    owner = make_login(client, "pa")
    course, part, chap, hit = _deep_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo", "open": str(part.pk)}).content.decode()
    assert f'data-scope="{part.pk}"' in body
    assert f'data-scope="{chap.pk}"' not in body   # the chains did NOT win
```

Add `_deep_course` beside `_big_course` in the same file:

```python
def _deep_course(owner):
    """part > chapter > one matching unit, ABOVE nothing in particular --
    the depth is what matters, not the size. `hit` must match both "trygo"
    and (after the rename) "nowy"; `chap` must NOT match "trygo", or the
    chain-vs-enumeration distinction the tests turn on disappears.
    """
    course = CourseFactory(slug="deep", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="P0"
    )
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Rozdzial"
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria"
    )
    return course, part, chap, hit
```

**These two rows belong here, not in Task 2.** They need `q` on the redirect
(Step 7 above) *and* `_filter_context` wired into `builder()` (Task 3); at the
end of Task 2 both are still missing, so they would be red for reasons that are
not the behaviour under test.

- [ ] **Step 10: Run the tests**

```bash
uv run pytest tests/test_builder_filter_views.py tests/test_manage_node_ops.py \n  tests/test_manage_move_picker.py tests/test_tree_badge.py \n  tests/test_manage_affordance.py tests/test_manage_duplicate_button.py \n  tests/test_builder_duplicate_unit.py tests/test_manage_node_duplicate.py -q
```

The last five are the suites Task 0 baselined as at-risk from **this** task:
`_tree_node.html` (badge), `_add_affordance.html` (affordance), the duplicate
form, and `node_duplicate`'s redirect. Run them in the commit that can break
them — deferring to Task 16 puts the breakage seven commits from its cause,
the same argument Task 9 Step 5 and Task 14 Step 5 already make.

Expected: PASS. `test_manage_node_ops` may need its expected redirect URLs updated — that is the behaviour change Task 0 predicted, not a regression.

- [ ] **Step 11: Falsify**

1. Change `{{ q|urlencode }}` to `{{ q }}` in the delete href →
   `test_markup_hrefs_percent_encode_q` must fail.
2. Drop the `_raw_q(request)` argument from **`node_add`'s**
   `_redirect_to_builder` call (`:489`) — a site no other row in this plan
   reaches — → `test_the_six_redirect_sites_carry_q` must fail on the `add`
   label. This is what proves the row covers six sites rather than standing on
   the rename one.
3. Revert `toggle_href` to `urlencode({"open": joined})` (Step 3 undone) →
   `test_toggle_hrefs_preserve_q` must fail. Before the slice-to-the-anchor
   fix this mutation left the row green, because the delete and Move hrefs
   carry `q=trygo` too.
4. Remove the hidden input from **`_tree_node.html`'s rename form only** →
   `test_every_tree_form_carries_a_hidden_q` must fail on the `rename` label
   and on that label alone. Per-form assertions are what make a single missed
   form visible.
5. Drop the `"q": _raw_q(request)` key from `node_delete`'s GET context
   (`:645-656`) → `test_the_delete_confirm_round_trip_stays_filtered` must
   fail on the hidden-input assertion, because `{% if q %}` then takes its
   falsy arm.

Restore each.

- [ ] **Step 12: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/ templates/ tests/test_builder_filter_views.py tests/test_builder_lazy_scopes.py
git commit -m "feat(builder): q rides the no-JS path — forms, hrefs, redirects, picker"
```

---

## Task 7: `builder_force` — the no-JS force-include channel

**Files:**
- Modify: `courses/views_manage.py` (`node_add`, `node_duplicate`, `node_move` reparent, `builder()`)
- Test: `tests/test_builder_filter_views.py`

**Interfaces:**
- Consumes: `_apply_effect_two` (Task 3), `remember_node` (slice 1).
- Produces: `_stash_builder_force(request, slug, node)`, `_take_builder_force(request, slug) -> tuple[int, ...]`; session key `builder_force`.

- [ ] **Step 1: Write the failing tests**

First add the import `test_force_inclusion_is_idempotent` needs, at the **top**
with the existing block (`E402`; isort is force-single-line). Neither Task 3's
block nor Task 4's addition carries it, and the model — not just its factory —
is queried below:

```python
from courses.models import ContentNode
```

Then append:

```python
def test_a_no_js_unit_add_under_a_filter_shows_the_new_row(filtered_course):
    """The unit kind is load-bearing: a container would survive a
    `& container_pks(...)` intersection and hide the trap."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Zupelnie inny tytul",
            "q": "trygo",
        },
    )
    assert resp.status_code == 302
    body = client.get(resp["Location"]).content.decode()
    assert "Zupelnie inny tytul" in body


def test_builder_force_is_consumed_exactly_once(filtered_course):
    """The clear is the half with no visible symptom when it is missing: an
    uncleared stash passes every other row while pinning a stale pk into
    every filtered render for that slug."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Zupelnie inny tytul",
            "q": "trygo",
        },
    )
    client.get(resp["Location"])
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    second = client.get(url, {"q": "trygo"}).content.decode()
    assert "Zupelnie inny tytul" not in second


def test_an_add_into_an_EMPTY_filtered_scope_does_not_500(filtered_course):
    """The destination has NO key in the restricted map: _children_map only
    creates keys for parents that HAVE children, and spec 1d ships an add
    affordance into exactly this scope."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Nowa lekcja",
            "q": "rozdzial",  # matches the CHAPTER; no descendant matches
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200
    assert "Nowa lekcja" in resp.content.decode()


def test_a_no_js_reparent_into_a_NON_MATCHING_destination_shows_the_node(
    filtered_course,
):
    """The row that actually proves the stash carried a CHAIN. An add form
    can only be submitted from a scope that is already visible, so its parent
    is a match or a walked ancestor either way and a bare-pk stash would pass
    that row. The Move picker is the one no-JS surface offering a destination
    the filter excludes."""
    client, course, part, chap, hit, miss = filtered_course
    other = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Zupelnie inny"
    )
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    resp = client.post(
        move,
        {
            "mode": "reparent",
            # `miss`, NOT `hit`: moving a node that still matches the query
            # makes the row vacuous -- filtered_map would select it on its own
            # and walk `other` -> `part` into the chains unaided, so both
            # assertions pass with _stash_builder_force deleted entirely.
            "node": miss.pk,
            "new_parent": other.pk,
            "position": 0,
            "node_token": miss.updated.isoformat(),
            "q": "trygo",
        },
    )
    assert resp.status_code == 302
    body = client.get(resp["Location"]).content.decode()
    assert f'data-node="{miss.pk}"' in body
    assert f'data-node="{other.pk}"' in body   # the CHAIN, not just the pk


def test_a_forced_row_does_not_move_shown_or_total(filtered_course):
    """The rule is invisible in the markup and would otherwise rot: if a
    forced pk counted, the X-Builder-Info notice would stop matching the cap
    it describes."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Zupelnie inny tytul",
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert "Zupelnie inny tytul" in resp.content.decode()
    assert resp["X-Builder-Info"] == "filter;shown=1;total=1"


def test_force_inclusion_is_idempotent(filtered_course):
    """A duplicate <li data-node=X> makes the DOM collector double-count and
    dragover's :scope > queries pick an arbitrary one."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Trygonometria druga",  # ALSO matches q
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    # _tree_node.html:26-27 emits the title TWICE per row -- `value="..."` and
    # `title="..."` on the same input -- so a correct, non-duplicated row
    # yields 2. Count a per-row-unique token instead.
    new_pk = ContentNode.objects.get(title="Trygonometria druga").pk
    assert resp.content.decode().count(f'data-node="{new_pk}"') == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_filter_views.py -q -k \
  "no_js_unit_add or NON_MATCHING_destination or consumed_exactly_once"
```

Expected: a **mixed** run, and the naive selector gets it exactly backwards.

- RED: `test_a_no_js_unit_add_under_a_filter_shows_the_new_row` and
  `test_a_no_js_reparent_into_a_NON_MATCHING_destination_shows_the_node`. Both
  follow a **redirect**, where the next page GET re-derives the restricted map
  from `q` alone and knows nothing of the new pk. These are the only two rows
  this task makes pass, and **neither contains "force" or "EMPTY"**.
- GREEN already: `test_builder_force_is_consumed_exactly_once` — it asserts a
  title is *absent* on the second render, which is trivially true with no
  stash at all. It turns red only if Step 3's `store.pop` clear is omitted,
  which is what Step 7's falsification 2 checks.

`-k "force or EMPTY"` would select **only already-green rows**:
`test_an_add_into_an_EMPTY_filtered_scope_does_not_500`,
`test_a_forced_row_does_not_move_shown_or_total` and
`test_force_inclusion_is_idempotent` all drive the **fragment** add path, where
`extra_open` already flows through `_filter_context` → `_apply_effect_two` —
shipped in Task 3, `setdefault` included — so the `KeyError` is unreachable
here and the shown/total rule already holds. Run them at Step 6 as
carry-forwards; do not expect them red now.

- [ ] **Step 3: Add the stash helpers**

```python
FORCE_KEY = "builder_force"


def _stash_builder_force(request, slug, node):
    """Stash a created/moved node's chain for EXACTLY the next page render.

    extra_open exists only on FRAGMENT renders, but a no-JS add, duplicate or
    reparent REDIRECTS -- and the following page GET re-derives the restricted
    map from `q` alone, knows nothing of the new pk, and that node's title
    will rarely match. The author would land on a filtered tree with their new
    node ABSENT, indistinguishable from failure, on the path with the least
    feedback.

    Stores a sorted list[int]: no SESSION_SERIALIZER is configured, so
    Django 5.2 uses JSONSerializer and a set raises
    "TypeError: Object of type set is not JSON serializable".

    Stores the UNFILTERED chain -- do NOT copy _persist_chain's
    `& container_pks(cmap)` intersection. That one deliberately drops a unit's
    own pk because it feeds the OPEN set; this one feeds extra_open, whose
    effect 2 applies to every pk regardless of kind. Copying the intersection
    makes a no-JS unit add under a filter return a tree without the row the
    author just created.
    """
    remember_node(
        request,
        slug,
        sorted(_ancestor_chain(node))[: builder_open.SESSION_OPEN_LIMIT],
        key=FORCE_KEY,
    )


def _take_builder_force(request, slug):
    """Read and CLEAR. builder() is the sole reader and the sole clearer:
    _builder_with_notice follows a FAILED mutation, so there is nothing
    created to force-include, and letting it read would leave the clear site
    undefined."""
    store = request.session.get(FORCE_KEY) or {}
    pks = tuple(store.pop(slug, ()))
    if pks:
        request.session[FORCE_KEY] = store
        request.session.modified = True
    return pks
```

- [ ] **Step 4: Stash on the three mutation paths**

Three separate insertions, each beside the existing `_persist_chain` line —
**and each with its own local name**, because only one of the three binds
`new_node`:

```python
# node_add, views_manage.py:488  (binds `node`)
        _persist_chain(request, course, node)
        _stash_builder_force(request, course.slug, node)
        return _redirect_to_builder(course, _raw_q(request))

# node_move reparent, views_manage.py:620  (binds `node`)
            _persist_chain(request, course, node)
            _stash_builder_force(request, course.slug, node)
            return _redirect_to_builder(course, _raw_q(request))

# node_duplicate, views_manage.py:714  (binds `new_node`)
        _persist_chain(request, course, new_node)
        _stash_builder_force(request, course.slug, new_node)
        return _redirect_to_builder(course, _raw_q(request))
```

Pasting one form into all three raises `NameError` at runtime on the no-JS
redirect path — which no fragment test exercises.

- [ ] **Step 5: Consume in `builder()`**

```python
    cmap = _children_map(course)
    force = _take_builder_force(request, course.slug)
    fc = _filter_context(request, course, cmap, mode="page", extra_open=force)
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_builder_filter_views.py -q
```

Expected: PASS.

- [ ] **Step 7: Falsify three guards**

1. Change `sorted(_ancestor_chain(node))` to `sorted(_ancestor_chain(node) & container_pks(_children_map(course)))` → the unit-add row must fail.
1b. Delete `_stash_builder_force` from `node_move`'s reparent branch → the
   non-matching-reparent row must fail. (It is the only row that can: every
   other force-include case involves a node the filter would keep anyway.)
2. Drop the `store.pop` clear (read without removing) → `test_builder_force_is_consumed_exactly_once` must fail.
3. Revert `_apply_effect_two`'s `setdefault` to `restricted[...]` → `test_an_add_into_an_EMPTY_filtered_scope_does_not_500` must fail with `KeyError`.

Restore all three.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/views_manage.py tests/test_builder_filter_views.py
git commit -m "feat(builder): builder_force — the no-JS force-include channel"
```

---

## Task 8: Ordering suppressed while a filter is active

**Files:**
- Modify: `courses/views_manage.py` (`node_move`'s reorder branch)
- Modify: `courses/static/courses/js/builder.js` (the `dragstart` bail)
- Modify: `templates/courses/manage/_move_buttons.html`, `_tree_node.html`
- Test: `tests/test_builder_filter_views.py`

**Interfaces:**
- Consumes: `builder_filter.is_active` (Task 1), `_raw_q` (Task 3), the `filtered` context key (Task 3).
- Produces: a 422 refusal branch in `node_move`; a `dragstart` bail on a
  `disabled` grip in `builder.js` — without which the rule is unobservable (see
  Step 4).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_arrows_and_the_grip_render_disabled_under_a_filter(filtered_course):
    """Both halves. Dropping `draggable` alone leaves .ica--grip's
    `cursor: grab` and `:active { cursor: grabbing }` intact, so the row still
    looks draggable -- the lying affordance this rule exists to remove.

    A SECOND MATCHING SIBLING is mandatory. _move_buttons.html already renders
    both arrows disabled on `is_first`/`is_last` alone, and under `q=trygo` the
    shared fixture gives `chap` exactly ONE surviving child -- so `hit` would
    be both first and last, both arrows would be disabled without the
    `or filtered` edit, and deleting that edit could not turn this row red.
    With two matches, `hit` is first-but-not-last, so the DOWN arrow is
    disabled only by `or filtered`.

    Added here rather than in the fixture: shown/total are asserted as 1/1 by
    test_counts_under_a_filter_are_the_filtered_counts and by
    test_a_forced_row_does_not_move_shown_or_total, and a second permanent
    match would redden both.
    """
    client, course, part, chap, hit, miss = filtered_course
    ContentNodeFactory(course=course, kind="unit", parent=chap, title="Trygonometria II")
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    filtered = client.get(url, {"q": "trygo"}).content.decode()
    row = filtered.split(f'data-node="{hit.pk}"')[1].split("</li>")[0]
    assert "disabled" in row.split('value="down"')[1].split(">")[0], (
        "the DOWN arrow is the one only `or filtered` can disable here"
    )
    assert row.count("disabled") >= 3  # up, down, grip
    assert 'draggable="true"' not in row

    plain = client.get(url, {"open": "all"}).content.decode()
    prow = plain.split(f'data-node="{hit.pk}"')[1].split("</li>")[0]
    assert 'draggable="true"' in prow


def test_a_reorder_under_an_active_filter_is_refused_on_both_branches(filtered_course):
    """The form is trivially replayable, so the markup alone is not a guard."""
    client, course, part, chap, hit, miss = filtered_course
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    before = list(
        type(hit).objects.filter(parent=chap).order_by("order", "pk").values_list("pk", flat=True)
    )

    frag = client.post(
        move,
        {"mode": "reorder", "node": hit.pk, "direction": "down",
         "token": hit.updated.isoformat(), "q": "trygo"},
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert frag.status_code == 422
    assert "op-error" in frag.content.decode()

    page = client.post(
        move,
        {"mode": "reorder", "node": hit.pk, "direction": "down",
         "token": hit.updated.isoformat(), "q": "trygo"},
    )
    assert page.status_code == 422
    assert "builder__tree" in page.content.decode()  # a full page, not a bare fragment

    after = list(
        type(hit).objects.filter(parent=chap).order_by("order", "pk").values_list("pk", flat=True)
    )
    assert before == after


def test_a_reorder_under_a_BELOW_FLOOR_q_still_succeeds(filtered_course):
    """The refusal row above passes under a truthiness gate
    (request.POST.get("q")) or a presence gate, both of which wrongly refuse
    here -- while the arrows render ENABLED, because `filtered` is False."""
    client, course, part, chap, hit, miss = filtered_course
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    resp = client.post(
        move,
        {"mode": "reorder", "node": hit.pk, "direction": "down",
         "token": hit.updated.isoformat(), "q": "a"},
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200


def test_a_positioned_REPARENT_under_a_filter_still_succeeds(filtered_course):
    """A drop and the Move picker post the same mode=reparent shape and are
    indistinguishable server-side, so a guard widened to "any positioned move"
    would break the one route spec 3m designates for moving while filtered."""
    client, course, part, chap, hit, miss = filtered_course
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    resp = client.post(
        move,
        {"mode": "reparent", "node": hit.pk, "new_parent": part.pk,
         "position": 0, "node_token": hit.updated.isoformat(), "q": "trygo"},
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200
    hit.refresh_from_db()
    assert hit.parent_id == part.pk
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_filter_views.py -q -k \
  "arrows or refused_on_both_branches or BELOW_FLOOR_q_still or REPARENT"
```

Expected: a **mixed** run, and the split matters.

- RED: `test_the_arrows_and_the_grip_render_disabled_under_a_filter` (no
  `disabled` on the grip yet) and
  `test_a_reorder_under_an_active_filter_is_refused_on_both_branches` (the
  reorder succeeds with 200 and the sibling order changes).
- GREEN already: `test_a_reorder_under_a_BELOW_FLOOR_q_still_succeeds` and
  `test_a_positioned_REPARENT_under_a_filter_still_succeeds`. Both assert that
  something keeps working, so they pass before the guard exists. They are here
  to catch an over-broad guard at Step 6, not to go red now.

- [ ] **Step 3: Add the server guard**

In `node_move`, at the very top of the `mode == "reorder"` branch:

```python
    if mode == "reorder":
        # Every position-based op computes against the FULL sibling list while
        # a filtered scope renders a SUBSET (spec 3m): reorder_node swaps
        # full-list neighbours, so "Move down" mutates the course with NO
        # visible change and the author clicks again, and again.
        #
        # is_active, not `request.POST.get("q")`: this branch runs before any
        # children-map is loaded, so no FilterContext exists -- and a
        # truthiness gate would refuse under a below-floor ?q=a, where the
        # tree renders unfiltered and the arrows render ENABLED.
        #
        # Scoped to mode=="reorder" ONLY. A drop posts mode=reparent with a
        # position, indistinguishable from the Move picker's form -- and the
        # picker's slot indices are computed against the FULL child list, so
        # they are correct by construction. Widening this guard would break
        # the one route left for moving while filtered.
        if builder_filter.is_active(_raw_q(request)):
            msg = _("Clear the filter to reorder.")
            if not _wants_fragment(request):
                return _builder_with_notice(request, course, msg, status=422)
            return render(
                request, "courses/manage/_op_error.html", {"message": msg}, status=422
            )
```

**Branch on `_wants_fragment` like every other 422 in this file** (`node_add:480-486`, `node_rename:540-549`, `node_move` reparent `:612-618`, `node_duplicate:706-712`). `_op_error.html` is **two lines** — no `base.html`, no stylesheet, no navigation — so returning it unconditionally ships a no-JS author a bare unstyled string.

- [ ] **Step 4: Disable the markup affordances**

In `_move_buttons.html`, both buttons:

```html
  <button class="ica" type="submit" name="direction" value="up"{% if is_first or filtered %} disabled{% endif %} ...>
  <button class="ica" type="submit" name="direction" value="down"{% if is_last or filtered %} disabled{% endif %} ...>
```

**And one client-side guard in `builder.js`**, because the markup alone is
neither sufficient nor testable: a `dragstart` dispatched programmatically
ignores the `draggable` attribute, and `builder.js:535`'s handler checks only
`e.target.closest(".ica--grip")` — so `dragover`/`drop` still run and the drop
POSTs `mode=reparent`, which §3m deliberately does not refuse server-side. This
repo's `_simulate_drag` dispatches native `DragEvent`s through `page.evaluate`
(Chromium will not fire DnD from Playwright input), so without this guard the
e2e in Step 5 cannot observe the rule at all.

The merged handler in full — **one** `var grip`. The existing body already
opens with `var grip = …; if (!grip) return;`, so pasting the new guard above
it verbatim would declare `grip` twice in the same function:

```js
  root.addEventListener("dragstart", function (e) {
    var grip = e.target.closest(".ica--grip");
    if (!grip) return;
    if (grip.disabled) { e.preventDefault(); return; }   // new
    var row = grip.closest(".tree__row");
    drag = { pk: row.getAttribute("data-node"), kind: row.getAttribute("data-kind"),
             token: row.getAttribute("data-updated") };
    e.dataTransfer.effectAllowed = "move";
  });
```

In `_tree_node.html`, the grip:

```html
      <button type="button" class="ica ica--grip"{% if filtered %} disabled{% else %} draggable="true"{% endif %} aria-label="{% trans 'Drag to move' %}" title="{% if filtered %}{% trans 'Clear the filter to reorder.' %}{% else %}{% trans 'Drag to move' %}{% endif %}"><svg class="ic"><use href="#bi-grip"/></svg></button>
```

`disabled` **and** dropping `draggable`: the grip is a `<button>`, so `disabled` picks up `.ica:disabled { opacity: .35; cursor: default; }` (`builder.css:60`) and `:active` never matches — otherwise `.ica--grip { cursor: grab }` (`:62`) and `.ica--grip:active { cursor: grabbing }` (`:155`) survive and the author presses a live-looking grip for nothing.

- [ ] **Step 5: The drag e2e is written in Task 10, not here**

The markup row above proves the attribute is gone; only a real gesture
proves the *behaviour*. That row — `test_drag_is_inert_while_a_filter_is_active`
— lives in **Task 10 Step 1**, together with the `_simulate_drag` helper and
the `ContentNode` import it needs, because `tests/test_e2e_builder_filter.py`
does not exist yet: Task 10 Step 1 **creates** it, and anything written here
would be overwritten.

Nothing to do in this step. Do not add the row here, and do not skip Task 10
Step 1's copy list — it is what makes this rule observable at all.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_builder_filter_views.py tests/test_manage_node_ops.py \n  tests/test_tree_badge.py tests/test_manage_affordance.py -q
```

`test_tree_badge.py` renders `_tree_node.html` directly and this task edits the
grip inside it; `_move_buttons.html` sits in the same rows.

Expected: PASS. The drag e2e runs in Task 10 once its file exists — invoking it
here exits 4 (file not found), which is not a pass.

- [ ] **Step 7: Falsify**

1. Change `builder_filter.is_active(_raw_q(request))` to `bool(request.POST.get("q"))` → `test_a_reorder_under_a_BELOW_FLOOR_q_still_succeeds` must fail.
2. Widen the guard to fire for `mode == "reparent"` too → `test_a_positioned_REPARENT_under_a_filter_still_succeeds` must fail.
3. Return `_op_error.html` unconditionally → the no-JS half of the refusal row must fail on the `builder__tree` assertion.
4. Remove `or filtered` from **both** buttons in `_move_buttons.html` →
   `test_the_arrows_and_the_grip_render_disabled_under_a_filter` must fail on
   the DOWN-arrow assertion. Without this fourth check the `_move_buttons.html`
   edit ships unguarded: the grip's `disabled` comes from `_tree_node.html` and
   would keep the count at 3 on its own.

Restore all four.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/views_manage.py courses/static/courses/js/builder.js templates/courses/manage/ tests/
git commit -m "feat(builder): suppress ordering while a filter is active"
```

---

## Task 9: The filter control and the two bulk controls — markup and CSS

**Files:**
- Modify: `templates/courses/manage/builder.html`
- Modify: `courses/static/courses/css/builder.css`
- Test: `tests/test_builder_styles.py`, `tests/test_builder_filter_views.py`

**Interfaces:**
- Consumes: the `q`, `filtered`, `expand_all_disabled`, `builder_url` context keys (Task 3).
- Produces: `[data-filter]`, `[data-filter-clear]`, `[data-expand-all]`, `[data-collapse-all]` hooks.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_clear_anchor_is_always_in_the_dom_and_hidden_when_blank(filtered_course):
    """`{% if q %}` puts NOTHING in the DOM on an unfiltered page, so the JS
    rule has no element to show -- and `clear.hidden = !box.value` on a null
    querySelector throws inside the input handler on the most common entry
    point there is, killing filtering before the debounce is scheduled."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    blank = client.get(url).content.decode()
    assert "data-filter-clear" in blank
    tag = blank.split("data-filter-clear")[1].split(">")[0]
    assert "hidden" in tag

    filtered = client.get(url, {"q": "trygo"}).content.decode()
    tag2 = filtered.split("data-filter-clear")[1].split(">")[0]
    assert "hidden" not in tag2


def test_the_filter_input_has_an_accessible_name(filtered_course):
    """"Filter" labels the BUTTON, not the field."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert 'id="builder-q"' in body
    assert 'for="builder-q"' in body


def test_expand_all_loses_its_href_over_the_ceiling(filtered_course, monkeypatch):
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})

    monkeypatch.setattr("courses.builder_open.CEILING", 0)
    over = client.get(url).content.decode()
    # Split on the ANCHOR's hook (with its trailing newline), never on the bare
    # string: `.builder` carries `data-expand-all-disabled` earlier in the
    # document and "data-expand-all" is a prefix of it, so a bare split lands
    # inside the <section> tag and every assertion below reads the wrong slice.
    tag = over.split("data-expand-all\n")[1].split(">")[0]
    assert "href" not in tag
    assert 'aria-disabled="true"' in tag
    assert "data-expand-all-disabled" in over

    monkeypatch.setattr("courses.builder_open.CEILING", 500)
    under = client.get(url).content.decode()
    assert "href" in under.split("data-expand-all\n")[1].split(">")[0]
    assert "data-expand-all-disabled" not in under


def test_both_bulk_controls_stay_ENABLED_under_an_active_filter(filtered_course):
    """Spec 6z. The tempting rule -- disable them while filtering, since a
    filtered tree is already fully open -- is FALSE once step 2 wins: after
    any toggle under a filter the resolved set is not the chains and filtered
    containers genuinely are collapsed."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    for hook in ("data-expand-all\n", "data-collapse-all\n"):
        # Split FORWARD from the hook: the href follows it in the markup, so
        # slicing backwards to the last `<a` yields only the class attribute.
        # And the hook needs its trailing newline -- `.builder` carries
        # `data-expand-all-disabled`, of which "data-expand-all" is a PREFIX,
        # and that attribute appears earlier in the document.
        tag = body.split(hook)[1].split(">")[0]
        assert "aria-disabled" not in tag
        assert "href" in tag


def test_expand_all_under_a_filter_returns_only_filtered_rows(filtered_course):
    """open=all + q renders the RESTRICTED map -- ~226 rows on mat-pp, not
    944 -- which is why 6z keeps the control enabled rather than disabling it
    on a cost argument that does not hold."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    body = client.get(url, {"open": "all", "q": "trygo"}).content.decode()
    assert f'data-node="{hit.pk}"' in body
    assert f'data-node="{miss.pk}"' not in body


def test_both_bulk_hrefs_carry_q(filtered_course):
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    for query in ("trygo", "a"):  # active AND present-but-inactive
        body = client.get(url, {"q": query}).content.decode()
        expand = body.split("data-expand-all\n")[1].split(">")[0]
        assert f"q={query}" in expand
```

In `tests/test_builder_styles.py`, add:

```python
def test_the_info_slot_hides_when_empty_via_empty_not_hidden():
    css = _css()          # the file's existing helper (line 14)
    assert ".builder__info:empty" in css
    assert "display: none" in css.split(".builder__info:empty")[1].split("}")[0]


def test_the_filter_control_is_styled():
    css = _css()
    assert ".builder__filter" in css
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_builder_filter_views.py tests/test_builder_styles.py -q -k \
  "clear_anchor or accessible_name or expand_all or bulk or filter_control"
```

Expected: FAIL — no `data-filter-clear` in the markup.

**`info_slot` is deliberately NOT in that expression.** It would match
`test_the_info_slot_is_present_and_empty_on_an_unfiltered_page`, green since
Task 5, turning a red gate into a mixed run where "expected red" and
"regression" look the same — the problem already fixed for Task 6 Step 2.

**One row the selector does still drag in:**
`test_expand_all_under_a_filter_returns_only_filtered_rows` matches
`expand_all` but is **green already** — it only GETs `manage_tree` with
`open=all&q=trygo` and asserts the restricted map renders, and both the route
(Task 4) and the restricted map (Task 3) shipped earlier. Expect it green;
everything else in the expression is red.
`test_the_info_slot_hides_when_empty_via_empty_not_hidden` is in the same
position: it guards the `.builder__info:empty` rule that **shipped in Task 5**,
so it is a carry-forward regression guard, not a red gate for this task. Run it
with the rest at Step 5; do not expect it red at Step 2.

- [ ] **Step 3: Add the header controls**

In `templates/courses/manage/builder.html`, inside `.builder__tree`'s `<header class="manage__head">`, after the `<h1>`:

```html
      <form class="builder__filter" method="get" action="{{ builder_url }}" data-filter>
        <label class="visually-hidden" for="builder-q">{% trans "Filter by title" %}</label>
        <input id="builder-q" type="search" name="q" value="{{ q }}">
        <button class="btn btn--ghost btn--small" type="submit">{% trans "Filter" %}</button>
        <a class="btn btn--ghost btn--small" href="{{ builder_url }}"
           data-filter-clear{% if not q %} hidden{% endif %}>{% trans "Clear" %}</a>
      </form>
      {% if expand_all_disabled %}
      <a class="btn btn--ghost btn--small" data-expand-all
         aria-disabled="true"
         title="{% trans 'This course is too large to expand at once.' %}">{% trans "Expand all" %}</a>
      {% else %}
      <a class="btn btn--ghost btn--small" data-expand-all
         href="{{ builder_url }}?open=all{% if q %}&amp;q={{ q|urlencode }}{% endif %}">{% trans "Expand all" %}</a>
      {% endif %}
      <a class="btn btn--ghost btn--small" data-collapse-all
         href="{{ builder_url }}?open={% if q %}&amp;q={{ q|urlencode }}{% endif %}">{% trans "Collapse all" %}</a>
```

**Keep each hook attribute last on its line, with the `href` on the next line.**
The §8 rows slice forward from `"data-expand-all\n"` precisely because
`.builder` also carries `data-expand-all-disabled`, and the bare string is a
prefix of it — reflowing these two tags onto one line silently redirects those
assertions into the `<section>` tag.

Notes an implementer must not "simplify":

- The Clear anchor is **rendered unconditionally**, carrying `hidden` when `q` is blank. `hidden` is safe on a `.btn` because `app.css:42` already ships `.btn[hidden] { display: none; }` with a comment naming this exact trap; a new component class would re-open it.
- `data-filter` has **no `data-op`**, so `builder.js`'s submit handler (which gates on `form[data-op]`) lets it through untouched on the no-JS path.
- The form carries **no `open`**: precedence step 2 would outrank step 3 and matches inside collapsed branches would never appear.
- Collapse-all's `open=` is **present-but-empty**, never omitted — omitting it re-seeds from the session and collapses nothing.
- Both bulk hrefs carry `q` — the active kind so a no-JS bulk gesture stays inside the filter, and the present-but-inactive kind so a below-floor query survives the navigation.

- [ ] **Step 4: Style them**

Append to `courses/static/courses/css/builder.css`:

```css
/* The header row is .manage__head, and app.css:591 already declares
   `.manage__head .btn { margin-left: auto; }` (reset to 0 at :644 for narrow
   viewports). Every .btn in the row claims the free space, so the filter form
   is laid out around that rule rather than fighting it: it takes the free
   space itself and the buttons after it sit flush.
   `flex: 1 1 0`, never `1 1 auto` -- with `auto` the base size is max-content
   and wrap is decided on that BEFORE shrinking. */
/* NO `margin-left: auto` here. Auto margins absorb only the free space that
   remains AFTER flex-grow has been resolved, and `flex: 1 1 0` on this same
   item consumes all of it -- so the margin would be a no-op sitting next to a
   genuinely load-bearing line, reading as though it did something. The form
   claims the free space by GROWING; that is the whole mechanism. */
.builder__filter { display: flex; gap: var(--space-2); flex: 1 1 0; min-width: 0; }
.builder__filter input[type="search"] { flex: 1 1 0; min-width: 0; }
.builder__tree .manage__head .btn { margin-left: 0; }   /* the row now has FIVE
   controls: app.css:591 gives every .manage__head .btn `margin-left: auto`,
   which was right when the row held one <h1> and two buttons. With Import,
   Export, Expand all, Collapse all and the form, only the FORM should claim
   the free space.
   The `.builder__tree` prefix is load-bearing twice over: it keeps other
   manage pages untouched, and it raises specificity above app.css:591 so the
   reset wins regardless of stylesheet load order. An unscoped
   `.manage__head .btn` ties on specificity and would depend on builder.css
   being linked after app.css (base.html:46-48) -- true today, and exactly the
   kind of accident that breaks silently when someone moves the rule. */
```

- [ ] **Step 5: Run the tests, then screenshot**

```bash
uv run pytest tests/test_builder_filter_views.py tests/test_builder_styles.py \n  tests/test_manage_builder.py -q
uv run pytest tests/test_e2e_builder_tree_layout.py -m e2e -q
```

**The second command is not optional.** `tests/test_e2e_builder_tree_layout.py`
pins `1.7 < tree/panel width ratio < 2.4` at a fixed 1000px viewport, and this
task puts a `flex: 1 1 0` form plus two more anchors into that header — a grown
min-content width can push the `2fr` track and break the ratio. Run it **in the
commit that can break it**: deferred to Task 16 Step 1 it surfaces eight tasks
and seven commits later, mixed in with every JS change, and bisecting the CSS
back out is far harder. (`-m e2e` is mandatory; exit 5 is not a pass.)

If the ratio moves, `.builder__tree` needs `min-width: 0` — add it and say so
in `docs/superpowers/notes/2026-07-28-affected-tests-slice2.md` (Task 0's
ledger, the only one that exists yet) rather than relaxing the ratio. If you
write there, add that path to Step 7's `git add`.

Then verify the header at **1400px and at a narrow width**, in **light and dark**, judging dark on its own rather than inferring it from light. The narrow width is the one that matters: this is where the repo's recorded `flex: 1 1 auto` wrap trap bites.

- [ ] **Step 6: Falsify**

Wrap the Clear anchor in `{% if q %}` → `test_the_clear_anchor_is_always_in_the_dom_and_hidden_when_blank` must fail. Restore.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add templates/courses/manage/builder.html courses/static/courses/css/builder.css tests/
git commit -m "feat(builder): filter control and bulk controls — markup and CSS"
```

---

## Task 10: `builder.js` — the tracker and the five applied-`q` senders

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Test: `tests/test_e2e_builder_filter.py` *(new)*

**Interfaces:**
- Consumes: `data-applied-q`, `data-q-min` (Task 3).
- Produces: `appliedQ` (module-scoped string), `effectiveQ(s)`, `setTreeParams(target, opts)`, `updateClearVisibility()`.

- [ ] **Step 1: Write the failing e2e**

Create `tests/test_e2e_builder_filter.py`. **A new e2e module inherits
nothing**, so copy SEVEN things from `tests/test_e2e_builder_toggle.py`, not
three: `pytestmark` (`:11`), the `_allow_async_unsafe` autouse fixture (`:15`),
`_make_pa_user` (`:24`), `_login` (`:44`, which assumes the user ALREADY
exists — always call `_make_pa_user` first), `stamp`
(`:117`), `assert_no_navigation` (`:122`, which READS the sentinel `stamp`
plants — always call `stamp` first, then the gesture, then the assertion), and
`_simulate_drag` (`:56`, which dispatches native `DragEvent`s — Chromium will
not fire DnD from Playwright input).

**`_simulate_drag` is the seventh for a reason.** Its only consumer is
`test_drag_is_inert_while_a_filter_is_active`, which belongs to **Task 8's**
rule but is written *here* (Task 8 Step 5 explains why). If you skip either,
two things break: that row raises `NameError`, and `ContentNode` — imported in
the block below — is used by nothing, so `F401` fires at this task's own
Step 8 `ruff check` gate and the commit is blocked.

The full import block the new file needs:

```python
import os

import pytest
from django.urls import reverse

from courses.models import ContentNode
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_verified_user
```

Then add the seeds and two shorthands this file needs — **none of them exists
today**, and `_seed` in the toggle file takes an *owner*, not a `page`:

```python
def _builder(course):
    return reverse("courses:manage_builder", kwargs={"slug": course.slug})


def _center(locator):
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _seed_flat(owner):
    """chapter > one matching unit. The chapter title must NOT contain
    "tryg", or it joins the match chain and renders already-expanded -- at
    which point clicking its toggle COLLAPSES it, no request is issued, and
    the toggle rows below wait forever on a removed element.
    """
    course = CourseFactory(slug="e2ef", owner=owner)
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Rozdzial"
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria"
    )
    return course, chap, hit


def _seed_two(owner):
    """_seed_flat plus a NON-matching sibling, for the rows that assert the
    filter hides something."""
    course, chap, hit = _seed_flat(owner)
    miss = ContentNodeFactory(course=course, kind="unit", parent=chap, title="Logika")
    return course, chap, hit, miss


def _seed_deep(owner):
    """part > chapter > matching unit, for the stash and expand-all rows,
    which need two nested scopes to tell apart."""
    course = CourseFactory(slug="e2ed", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Czesc"
    )
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Rozdzial"
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria"
    )
    return course, part, chap, hit
```

Every e2e below takes the owner from `_make_pa_user("pa")` and seeds before
`_login`. Then:

```python
def test_a_toggle_under_a_filter_carries_the_APPLIED_q(page, live_server):
    """Three values are in play during the 300ms debounce: the hidden input
    holds the last RENDERED q, the box holds what is currently typed, and the
    tracker holds what the pane actually shows. Sending the live value returns
    markup filtered by `trygo` into a pane rendered for `tryg`."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    # ?open= as well as ?q=: under an active filter every ancestor of every
    # match is in `chains`, so `chap` would render ALREADY EXPANDED and the
    # click below would collapse it -- no request, and the wait would time out
    # on a removed element. An explicit empty `open` wins by precedence step 2.
    page.goto(f"{live_server.url}{_builder(course)}?q=tryg&open=")

    # Kill every filter fetch for the whole row, so appliedQ CANNOT advance
    # past the rendered `tryg` no matter when the debounce fires. Without this
    # the assertions depend on page.fill and page.click both completing inside
    # the 300 ms window: if the timer wins, applyFilterState swaps the top
    # scope (removing the toggle mid-click) and writes appliedQ = "trygo", and
    # the last assertion fails intermittently on a loaded machine. Sleeping or
    # "do NOT wait for the debounce" is sampling a race, not pinning a rule.
    #
    # `**/build/tree/**` matches manage_tree ONLY -- the toggle's own request
    # is /build/node/<pk>/scope/ (courses/urls.py:169) and is untouched. The
    # aborted fetch raises a "Network error" notice this row does not assert
    # on, and [data-busy] deliberately does not block pointer events
    # (builder.css:196-198), so the toggle click still lands.
    page.route("**/build/tree/**", lambda route: route.abort())

    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/" in r.url else None)

    page.fill("#builder-q", "trygo")
    page.click(f'[data-toggle="{chap.pk}"]')
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')

    scope_reqs = [u for u in sent if "/scope/" in u]
    assert scope_reqs, "the toggle issued no request"
    assert "q=tryg" in scope_reqs[-1]
    assert "q=trygo" not in scope_reqs[-1]
```

**And the drag row Task 8 deferred to here** — it belongs to Task 8's rule, but
this is the step that creates the file. It is the only row that can observe
that rule at all: a programmatic `dragstart` ignores the `draggable`
attribute, so the markup assertion in Task 8 cannot prove the behaviour.

```python
def test_drag_is_inert_while_a_filter_is_active(page, live_server):
    """The row that catches the targetFor-index-into-full-list defect, which
    produces no error and no visible symptom in the filtered pane. Uses the
    real gesture via _simulate_drag (tests/test_e2e_builder_toggle.py:56),
    never page.evaluate."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    # NOT `other = ContentNodeFactory(...)`: the name is never read, and ruff
    # selects `F`, so F841 would fail this task's own Step 8 lint gate. The
    # filtered_course fixture uses the same unbound-call idiom for "Pusty".
    ContentNodeFactory(course=course, kind="unit", parent=chap, title="Logika")
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    before = list(
        ContentNode.objects.filter(parent=chap)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )
    moved = []
    page.on("request", lambda r: moved.append(r.url) if "node/move" in r.url else None)
    _simulate_drag(page, f'li[data-node="{hit.pk}"] .ica--grip', f'ol[data-scope="{part.pk}"]')
    page.wait_for_timeout(400)
    assert moved == []
    after = list(
        ContentNode.objects.filter(parent=chap)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )
    assert before == after
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q
```

Expected: **one** failure —
`test_a_toggle_under_a_filter_carries_the_APPLIED_q`, because the toggle
request carries no `q` at all. `test_drag_is_inert_while_a_filter_is_active`
should already **pass**: it exercises Task 8's **`dragstart` bail**, which
shipped two tasks ago. Not the server guard — a drop posts `mode=reparent`,
which that guard is deliberately scoped *not* to refuse (Task 8 Step 7's
falsification 2 requires that widening it break a test). So a red drag row here
means Task 8 Step 4's `builder.js` edit was lost, not that this task is
incomplete; look there first, not at `node_move`. (Exit 5 means the
marker was dropped; that is not a pass.)

- [ ] **Step 3: Add the tracker**

Near the top of the IIFE in `builder.js`, beside `collectOpen`:

```js
  // ---- the applied-q tracker -------------------------------------------------
  // The floor applies in the COMPARISON, never in either value. Storing the
  // effective form makes a ?q=a page send q="" on the first toggle, and
  // syncUrl then strips the `a` from the address bar.
  // TWO values, and conflating them breaks the clear path (spec 5z).
  //   appliedQ  -- what the pane is SHOWING; written when a response lands;
  //                read by the five senders, syncUrl and rewriteBulkHrefs
  //   pendingQ  -- what the latest ISSUED request will apply; written at issue
  //                time; read by the skip-comparison, and only that
  // appliedQ alone is stale during an in-flight filter: type `trygo`, click
  // Clear before it lands, and the clear compares "" against "" (appliedQ has
  // not advanced), returns early, issues NO request and never bumps treeGen --
  // so the filter response lands unopposed and repaints filtered markup over
  // an empty box. The counter cannot save it: the losing path sends nothing.
  var appliedQ = root.getAttribute("data-applied-q") || "";
  var pendingQ = appliedQ;
  var qMin = parseInt(root.getAttribute("data-q-min"), 10) || 2;

  function effectiveQ(s) {
    // Mirrors builder_filter.is_active. NFC, not NFD: measured over all of
    // Unicode, an NFD client measure exceeds the server's fold for 11,371
    // characters (Hangul, Hebrew, Katakana, Arabic, Indic), NFC for 83, and
    // Latin for 0 either way.
    //
    // The explicit class, not trim(): Python's str.strip() takes U+0085 and
    // U+001C-1F, which trim() does not, so "a\u0085" would be 2 to the client
    // and 1 to the server -- the direction that collapses the tree.
    //
    // [...s].length, not .length: .length counts UTF-16 units and Python
    // counts code points, so every astral character measures 2 here and 1
    // there -- the same dangerous direction, for the whole astral plane.
    // Every class member is written as an ESCAPE, never a literal byte:
    // U+001C-001F and U+0085 are invisible in an editor and in a diff, and
    // if one is lost to a paste that normalises whitespace the client floor
    // silently disagrees with str.strip() in the direction that collapses
    // the tree. Same for the combining-mark class.
    var TRIM = /^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$/g;
    var MARKS = /[\u0300-\u036f]/g;
    var t = (s || "").replace(TRIM, "").normalize("NFC").replace(MARKS, "");
    return [...t].length >= qMin ? (s || "").replace(TRIM, "") : "";
  }
```

- [ ] **Step 4: Route every request path through one helper**

`withOpen` is called from exactly two sites — the submit handler (`:240`) and the drop handler (`:638`) — so "the collector sets `q` on every fragment request" is false. **The toggle builds its own query string** (`:487-490`), and it is the most common fragment request:

```js
  // SET, never append: mutation forms already carry a hidden q, so appending
  // puts two values in the FormData and QueryDict.get returns the LAST -- the
  // collector would win only by accident of ordering.
  function setTreeParams(target, opts) {
    var open = (opts && opts.openOverride !== undefined)
      ? opts.openOverride
      : collectOpen();
    if (target.set) {                       // FormData or URLSearchParams
      target.set("open", open);
      target.set("q", appliedQ);
    } else {                                // a URL
      target.searchParams.set("open", open);
      target.searchParams.set("q", appliedQ);
    }
    return target;
  }
  function withOpen(body) { return setTreeParams(body); }
```

Then update the four remaining senders to use it:

- the toggle (`:487-489` — **not** `:490`, which is the `fetch(` line and
  must survive): three statements become two, and `body` must still be
  bound because `:490` calls `body.toString()`:
  ```js
      var open = collectOpen();
      var body = setTreeParams(new URLSearchParams(), {
        openOverride: open ? open + "," + pk : pk,
      });
  ```
- the drop and the submit handler: already covered through `withOpen`
- the Move-picker fetch (`:276`), written out because the surrounding lines
  decide what `fetch` receives:

  ```js
        var u = new URL(mv.getAttribute("href"), window.location.origin);
        u.searchParams.set("q", appliedQ);
        fetch(u.pathname + u.search, { headers: { "X-Requested-With": "fetch" } })
  ```

  `u.pathname + u.search`, matching the click-time delete-href rewrite at
  `:528-530`; `u.toString()` would work too but would spell an absolute URL
  where the file consistently uses relative ones.

  **Deliberately unguarded**, and recorded as such rather than left to look
  like an oversight: no row in this plan asserts `q` on the picker request,
  because the edit is belt-and-braces — every transition that makes `q` active
  re-renders the whole top scope, so the href it parses already carries the
  current `q`. This line matters only for the window between a filter
  response landing and the next re-render. If you would rather guard it, the
  cheap version is a Playwright `page.on("request")` row in Task 10.

  Set **only `q`** — **not** `setTreeParams(u)`.
  Sets, does not append: the href already carries a rendered `q`, so appending
  yields `?node=5&q=X&q=X` and works only because `QueryDict.get` takes the
  last. And `setTreeParams` would additionally stamp `open`, which
  `_move_picker` never reads — it consumes `request.GET["node"]` and nothing
  else (`views_manage.py:778-782`) — so on `mat-pp` after an expand-all every
  picker GET would carry a ~1 KB comma-joined pk list, on a slice whose whole
  premise is request cost.

- [ ] **Step 5: `syncUrl` writes the tracker**

```js
  function syncUrl() {
    var u = new URL(window.location.href);
    u.searchParams.set("open", collectOpen());
    // Writes the TRACKER, not "whatever this request sent" -- which is
    // undefined for the clear fetch (sends no q) and for collapse-all (issues
    // no request at all, yet calls this). Deletes only when the tracker is
    // blank, so a below-floor `a` survives in the address bar.
    if (appliedQ) u.searchParams.set("q", appliedQ);
    else u.searchParams.delete("q");
    history.replaceState(null, "", u.toString());
  }
```

- [ ] **Step 6: Run the e2e**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q
```

Expected: PASS.

- [ ] **Step 7: Falsify**

Revert the toggle to its own `URLSearchParams` without `setTreeParams` → the test must fail on the missing `q`. Restore.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/static/courses/js/builder.js tests/test_e2e_builder_filter.py
git commit -m "feat(builder): applied-q tracker + setTreeParams across every request path"
```

---

## Task 11: `builder.js` — the filter fetch, the clear path and the stash

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Test: `tests/test_e2e_builder_filter.py`

**Interfaces:**
- Consumes: `appliedQ`, `effectiveQ`, `setTreeParams` (Task 10); `data-tree-url` (Task 4).
- Produces: `preFilterOpen` (module-scoped, initialised `null`), `treeGen` (shared generation counter), `applyFilterState(q)`.

- [ ] **Step 1: Write the failing e2e**

```python
def test_typing_a_query_filters_without_navigating(page, live_server):
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    stamp(page)                 # plants window.__samedoc; assert_no_navigation
                                # only READS it, so the order is load-bearing
    page.fill("#builder-q", "trygo")
    # Wait on the non-matching row DISAPPEARING, never on the matching one
    # appearing: these fixtures are under SIZE_THRESHOLD, so a bare page GET
    # takes precedence step 4 and opens every container -- `hit` is already in
    # the DOM at load, the wait returns instantly, and the assertions below run
    # inside the 300 ms debounce, before any fetch exists.
    page.wait_for_selector(f'li[data-node="{miss.pk}"]', state="detached")
    assert_no_navigation(page)  # AFTER the gesture, or it cannot detect one
    assert "q=trygo" in page.url


def test_the_filter_fetch_omits_open(page, live_server):
    """Collapse the target's ancestor chain FIRST. Without that the row is
    vacuous: filtering is done by the restricted map, so sending
    open=<collector> and sending nothing produce identical rows on any tree
    whose match ancestors are already open."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None)
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'li[data-node="{hit.pk}"]')
    assert sent and "open=" not in sent[-1]


def test_typing_below_the_floor_into_an_UNFILTERED_tree_issues_no_request(
    page, live_server
):
    """Without the applied-state guard the first character takes the clear
    path, the stash is null, and the fallback sends the collector's full
    enumeration -- a complete re-render triggered by one keystroke."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None)
    page.fill("#builder-q", "t")
    page.wait_for_timeout(600)
    assert sent == []


def test_a_single_astral_character_issues_no_filter_fetch(page, live_server):
    """The ONE row that can go red against a `.length` client measure, which
    is worth ~1M characters of tree-collapsing exposure: .length counts UTF-16
    units and Python counts code points, so an astral character is 2 here and
    1 there. Every other floor row uses BMP input, where the two agree."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None)
    page.fill("#builder-q", "\U0001D400")
    page.wait_for_timeout(600)
    assert sent == []


def test_the_client_reads_data_q_min_rather_than_hardcoding_it(
    page, live_server, monkeypatch
):
    """The view-level row asserts the ATTRIBUTE; only this one can go red
    against a by-value `2` in builder.js."""
    monkeypatch.setattr("courses.builder_filter.MIN_QUERY", 3)
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None)
    page.fill("#builder-q", "tr")          # 2 chars, below a floor of 3
    page.wait_for_timeout(600)
    assert sent == []


def test_clearing_a_BELOW_FLOOR_query_scrubs_it_from_the_url_and_the_hrefs(
    page, live_server
):
    """The skip path, which issues no request and therefore reaches no
    response handler. effectiveQ("a") and effectiveQ("") are BOTH "", so the
    guard returns early -- and without syncUrl/rewriteBulkHrefs on that path
    `?q=a` outlives the Clear it was cleared by. No other row exercises it:
    every other clear crosses the floor and takes the fetch path.

    The HREF half of this rule is asserted in Task 13, not here:
    rewriteBulkHrefs is still a no-op stub at the end of this task, so an
    href assertion would be red for a reason that is not the behaviour
    under test.
    """
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=a&open=all")
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None)
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    assert sent == [], "the skip path must issue no request"
    assert "q=" not in page.url


def test_clear_restores_the_pre_filter_expansion(page, live_server):
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open={part.pk}")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')   # the chain opened
    page.click("[data-filter-clear]")
    # `part`'s scope is open in BOTH states, so waiting on it is satisfied by
    # the still-filtered markup and the assertion then races the response.
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]', state="detached")
    assert page.locator(f'ol[data-scope="{part.pk}"]').count() == 1


def test_collapse_everything_filter_clear_comes_back_EMPTY(page, live_server):
    """The stash === null rule: a legitimately empty pre-filter set stashes as
    "", and `if (!stash)` misreads it as absent."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'li[data-node="{hit.pk}"]')
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    assert page.locator('ol.tree__scope[data-scope]:not([data-scope="top"])').count() == 0


def test_clicking_the_clear_control_hides_it(page, live_server):
    """box.value = "" fires NO input event, so a visibility rule living only
    in that handler never runs on this path. Emptying by TYPING passes
    regardless, which is why this row clicks the control."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    assert page.locator("[data-filter-clear]").is_visible()
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    assert not page.locator("[data-filter-clear]").is_visible()


def test_a_clear_is_not_overwritten_by_an_in_flight_filter_response(page, live_server):
    """ONE generation counter across every data-tree-url request. With a
    counter per path the released filter response repaints filtered markup
    over an empty input."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")

    held = []
    def handler(route):
        if "q=trygo" in route.request.url and not held:
            held.append(route)          # hold the FILTER response
        else:
            route.continue_()
    page.route("**/build/tree/**", handler)

    page.fill("#builder-q", "trygo")
    page.wait_for_timeout(400)
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    held[0].continue_()                  # release it late
    page.wait_for_timeout(400)

    assert page.locator(f'li[data-node="{miss.pk}"]').count() == 1
    assert page.locator('[data-info-key="filter"]').count() == 0
    assert "q=" not in page.url
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q
```

Expected: FAIL — typing does nothing; there is no filter handler.

- [ ] **Step 3: Add no-op stubs for the two later collaborators**

`applyFilterState` below calls `applyInfo` (Task 12) and `rewriteBulkHrefs`
(Task 13). Those are separate commits, so at the end of *this* task neither
identifier exists — and a `ReferenceError` inside the `.then` is swallowed by
the `.catch` as "Network error", skipping everything ordered after it: the
tracker write, the stash clear and `syncUrl`. Every row in this task would fail
for a reason that is not the behaviour under test. Ship the stubs now; Tasks 12
and 13 replace their bodies.

```js
  function applyInfo() {}          // replaced in Task 12
  function rewriteBulkHrefs() {}   // replaced in Task 13
```

Task 12 Step 3 and Task 13 Step 5 give their real bodies; deleting the stub
line is part of those steps.

- [ ] **Step 4: Add the state and the shared counter**

```js
  // null, NOT "" -- a legitimately empty pre-filter set stashes as "", and
  // `if (!stash)` misreads that as absent, so an author who had everything
  // collapsed, filtered, then cleared would get the filter's chains open
  // instead of the empty tree they started from.
  var preFilterOpen = null;
  // ONE counter for EVERY data-tree-url request: filter, clear and
  // expand-all all applyFragment the same pane. With a counter per path, a
  // filter response landing after a clear repaints filtered markup, writes
  // the tracker back and restores ?q= -- filtered markup over an empty box.
  var treeGen = 0;
  var filterTimer = null;
```

- [ ] **Step 5: The one entry point**

```js
  var box = root.querySelector("#builder-q");

  function updateClearVisibility() {
    var clear = root.querySelector("[data-filter-clear]");
    if (clear) clear.hidden = !box.value;
  }

  function applyFilterState(live) {
    var eff = effectiveQ(live);
    // Compared against pendingQ, not appliedQ (see above). Guarded on what is
    // APPLIED-or-IN-FLIGHT, not on what the box contains: otherwise the first
    // character typed into an unfiltered tree takes the clear path, the stash
    // is null, and the fallback re-renders everything the author had open --
    // on mat-pp after an expand-all, the multi-second render, from one
    // keystroke.
    if (eff === effectiveQ(pendingQ)) {
      // No FETCH is needed -- the pane already shows the right thing -- but
      // the tracker still moved, and syncUrl/rewriteBulkHrefs are otherwise
      // only ever called from a response handler. Skipping them here strands
      // a below-floor query: load ?q=a, click Clear, and eff === "" on both
      // sides, so without these two lines `?q=a` stays in the address bar and
      // in both bulk hrefs while the box reads empty -- a reload or a
      // middle-click silently restores a filter the author just cleared.
      appliedQ = live;
      pendingQ = live;
      rewriteBulkHrefs();
      syncUrl();
      return;
    }
    pendingQ = live;          // at ISSUE time, before the fetch

    var url = new URL(root.getAttribute("data-tree-url"), window.location.origin);
    if (eff) {
      // Entering a filter: stash BEFORE the first fetch, and only on the
      // unfiltered -> filtered transition (refining does not re-stash).
      if (preFilterOpen === null) preFilterOpen = collectOpen();
      url.searchParams.set("q", live);
      // NO `open`: step 2 outranks step 3, so a filter fetch carrying it
      // would return only the scopes that happened to be open already, and a
      // match three levels down inside a collapsed branch would never appear.
    } else {
      // Clearing. Never omits `open`: that is the fragment-absent path, i.e.
      // the EMPTY set, which would collapse the course to its top rows.
      url.searchParams.set(
        "open", preFilterOpen === null ? collectOpen() : preFilterOpen
      );
    }

    var gen = ++treeGen;
    busyStart();
    fetch(url.toString(), { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        return r.text().then(function (text) {
          if (gen !== treeGen) return;          // stale: touch NOTHING
          if (r.status !== 200) { notice(msg("network", "Network error — please try again.")); return; }
          applyFragment(text);
          applyInfo(r);                          // Task 12
          appliedQ = live;                       // BEFORE syncUrl and the rewrite
          if (!eff) preFilterOpen = null;        // consumed on APPLY, not on issue
          rewriteBulkHrefs();                    // Task 13
          syncUrl();
        });
      })
      .catch(function () { notice(msg("network", "Network error — please try again.")); })
      .then(function () { busyEnd(); });
  }
```

The ordered steps — busy → `applyFragment` → header → **tracker write** → **bulk-href rewrite** → `syncUrl` — are load-bearing: `syncUrl` and the rewrite **both read the tracker**, so writing it afterwards leaves `?q=tryg` over an unfiltered tree, and rewriting before it puts the previous value in the bulk hrefs.

- [ ] **Step 6: Wire the three entry points**

```js
  if (box) {
    root.addEventListener("input", function (e) {
      if (e.target !== box) return;
      updateClearVisibility();
      clearTimeout(filterTimer);
      filterTimer = setTimeout(function () { applyFilterState(box.value); }, 300);
    });
    // Enter / the Filter button. Without this the most obvious "apply the
    // filter" gesture is a full-page navigation that discards the stash.
    root.addEventListener("submit", function (e) {
      var form = e.target.closest("[data-filter]");
      if (!form) return;
      e.preventDefault();
      clearTimeout(filterTimer);
      applyFilterState(box.value);
    });
    root.addEventListener("click", function (e) {
      if (!e.target.closest("[data-filter-clear]")) return;
      e.preventDefault();
      clearTimeout(filterTimer);        // else it fires and issues a SECOND clear
      box.value = "";
      updateClearVisibility();          // box.value = "" fires no input event
      applyFilterState("");
    });
  }
```

- [ ] **Step 7: Discard the stash on a mutation while filtered**

In **both** the submit handler (`:215`) and the drop handler (`:618`), after a successful apply:

```js
    if (appliedQ) preFilterOpen = null;   // the tree changed underneath it
```

Naming both sites is what stops the rule being implemented in whichever handler the implementer happened to be editing.

- [ ] **Step 8: Run the e2e**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q
```

Expected: PASS.

- [ ] **Step 9: Falsify four guards**

1. In the **clear (`else`) branch's ternary** —
   `preFilterOpen === null ? collectOpen() : preFilterOpen` → change it to
   `!preFilterOpen ? collectOpen() : preFilterOpen`. The clear then falls back
   to `collectOpen()` over the *filtered* tree, whose chains are open, and
   `test_collapse_everything_filter_clear_comes_back_EMPTY` must fail.

   **Not the stash guard** (`if (preFilterOpen === null) preFilterOpen = …`):
   that row makes exactly one filter fetch, and `preFilterOpen` is `null` at
   that moment under both spellings, so mutating it there is a no-op and the
   row stays green. The ternary is the site the test actually reaches.
2. Drop the `eff === effectiveQ(pendingQ)` skip guard entirely (the whole `if`,
   not just one operand) — the below-floor no-request row must fail. **The
   guard compares against `pendingQ`, not `appliedQ`**; falsification 3b below
   covers swapping the operand, which is a different defect.
3. Use a per-path counter instead of `treeGen` — the in-flight overwrite row must fail.
3b. Compare the skip guard against `appliedQ` instead of `pendingQ` — the same
   row must fail, and for a different reason: the clear is skipped entirely, so
   no request is issued and nothing is there to discard.
4. Remove `updateClearVisibility()` from the click handler — the clear-hides-it row must fail.
5. Remove `rewriteBulkHrefs(); syncUrl();` from the **skip** branch (leaving
   the two tracker writes) →
   `test_clearing_a_BELOW_FLOOR_query_scrubs_it_from_the_url_and_the_hrefs`
   must fail. It is the only row that reaches that branch.

Restore each.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/static/courses/js/builder.js tests/test_e2e_builder_filter.py
git commit -m "feat(builder): filter fetch, clear path, stash, shared generation counter"
```

---

## Task 12: `builder.js` — the info-slot registry

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Test: `tests/test_e2e_builder_filter.py`

**Interfaces:**
- Consumes: `X-Builder-Info` (Task 5), `data-msg-truncation`, `data-msg-filter` (Task 5).
- Produces: `applyInfo(response)`.

- [ ] **Step 1: Write the failing e2e**

```python
def test_a_fragment_borne_notice_lands_on_a_page_that_had_none(page, live_server):
    """Without the always-present slot the JS has nowhere to insert, and the
    throw is swallowed by the .catch and mislabelled 'Network error' while the
    tree still updates -- so no other row notices."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector('[data-info-key="filter"]')


def test_the_info_slot_replaces_by_key(page, live_server):
    """From a ?q= PAGE LOAD, or the test passes vacuously: the registry bug is
    that the JS knows only about entries it inserted itself."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    page.fill("#builder-q", "trygono")
    page.wait_for_timeout(500)
    page.fill("#builder-q", "trygonom")
    page.wait_for_timeout(500)
    assert page.locator('[data-info-key="filter"]').count() == 1


def test_an_absent_header_does_NOT_clear_the_slot(page, live_server):
    """A rename 200 is _rename_result.html and carries no header. The
    server-side row proves only that it is absent; this proves the client
    IGNORES an absent header rather than clearing on it."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    page.wait_for_selector('[data-info-key="filter"]')
    row = page.locator(f'li[data-node="{hit.pk}"] input.tree__title')
    row.fill("Trygonometria II")
    row.press("Enter")
    page.wait_for_timeout(400)
    assert page.locator('[data-info-key="filter"]').count() == 1


def test_clearing_the_filter_removes_the_filter_entry(page, live_server):
    """The ONLY path on which `none` does any work."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    page.wait_for_selector('[data-info-key="filter"]')
    page.click("[data-filter-clear]")
    page.wait_for_timeout(500)
    assert page.locator('[data-info-key="filter"]').count() == 0


def test_the_empty_info_slot_is_not_rendered(page, live_server):
    """Both at load AND after a filter -> clear cycle: the second catches the
    JS leaving a whitespace text node, which makes the sunken bar permanent."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    assert page.evaluate(
        "document.querySelector('.builder__info').matches(':empty')"
    )
    page.fill("#builder-q", "trygo")
    page.wait_for_selector('[data-info-key="filter"]')
    page.click("[data-filter-clear]")
    page.wait_for_timeout(500)
    assert page.evaluate(
        "document.querySelector('.builder__info').matches(':empty')"
    )
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q -k \
  "fragment_borne or replaces_by_key or absent_header \
   or removes_the_filter_entry or empty_info_slot"
```

Expected: a **mixed** run. `-k "info or slot"` would be worse than useless
here — it selects neither row the stated expectation describes.

- RED: `test_a_fragment_borne_notice_lands_on_a_page_that_had_none` (no entry
  ever appears from a fragment), `test_clearing_the_filter_removes_the_filter_entry`
  (the stub never removes one) and `test_the_empty_info_slot_is_not_rendered`
  (times out waiting for `[data-info-key="filter"]`). **None of the first two
  contains "info" or "slot".**
- GREEN already, against Task 11's `function applyInfo() {}` stub:
  `test_the_info_slot_replaces_by_key` and
  `test_an_absent_header_does_NOT_clear_the_slot`. Both load `?q=trygo`, get
  one server-rendered `<li>`, and the stub adds nothing — so `count() == 1`
  holds for the wrong reason. They are Step 6's falsification targets, not red
  gates.

- [ ] **Step 3: Add the registry**

**First delete Task 11 Step 3's stub line** — `function applyInfo() {}` — and
replace it with the block below. Two `function applyInfo` declarations in one
IIFE do not error (the later hoisted declaration wins), so a leftover stub is
invisible to every test in this plan and just leaves dead, misleading source.

```js
  // ---- the info slot ---------------------------------------------------------
  var infoSlot = root.querySelector("[data-info]");

  function applyInfo(response) {
    // header ABSENT -> not a tree-pane response, ignore ENTIRELY. A rename
    // 200, a 422 and both panel fetches never reach _render_scope, so they
    // neither set nor clear -- by construction, not by a call-site list.
    var raw = response.headers.get("X-Builder-Info");
    if (raw === null || !infoSlot) return;

    if (raw === "none") { infoSlot.replaceChildren(); return; }

    // grammar:  entry ( ", " entry )*   with   entry := key ( ";" name "=" value )*
    raw.split(", ").forEach(function (entry) {
      var parts = entry.split(";");
      var key = parts[0];
      var params = {};
      parts.slice(1).forEach(function (p) {
        var kv = p.split("=");
        params[kv[0]] = kv[1];
      });
      var template = msg(key, "");
      if (!template) return;
      var text = template.replace(/%\((\w+)\)s/g, function (_m, name) {
        return params[name] !== undefined ? params[name] : "";
      });
      // Replace by KEY -- the info key, the code prefix and the data-msg-*
      // suffix are deliberately the same token, so no prefix->key map exists
      // to get wrong.
      var existing = infoSlot.querySelector('[data-info-key="' + key + '"]');
      var li = document.createElement("li");
      li.setAttribute("data-info-key", key);
      li.textContent = text;             // element nodes only: never leave a
      if (existing) existing.replaceWith(li);   // text node inside the slot,
      else infoSlot.appendChild(li);            // or :empty stops matching
    });
  }
```

The registry operates on **server-rendered** entries too, because it queries the live DOM rather than a private list. Without that, a reload while filtered renders a server-side `filter` entry, the next toggle re-asserts `filter;…`, the JS finds nothing in its own registry and appends a **second** copy.

- [ ] **Step 4: Call it from every tree-pane response**

Add `applyInfo(r)` to the submit handler and the drop handler — both already
use the nested `r.text().then(…)` form, so `r` is in scope.

**In the submit handler it goes at the TOP of the `r.text().then(function
(text) {…})` body, before the status branches — NOT beside `applyFragment`.**
`applyFragment(text)` lives in the **else** arm of
`if (r.status === 200 && form.getAttribute("data-op") === "rename")`
(`builder.js:243-252`); a rename 200 takes `applyRename(form, text)` instead
and would never reach `applyInfo` at all. That is precisely the path
`test_an_absent_header_does_NOT_clear_the_slot` drives, so placing the call in
the else arm makes that row pass vacuously and makes Step 6's falsification 1
unable to go red:

```js
    }).then(function (r) {
      return r.text().then(function (text) {
        applyInfo(r);          // FIRST, on every arm. A rename 200 and a 422
                               // carry no header, so this is a no-op there --
                               // by construction, not by a call-site list.
        if (r.status === 200 || r.status === 409) {
```

**The drop handler has a status split too** (`builder.js:642-651`: 200/409 →
`applyFragment`, else 422 → `notice`), but there it does not matter: a 422 drop
returns `_op_error.html`, which never reaches `_render_scope` and so carries no
header at all. Placing the call beside `applyFragment` in the 200/409 arm is
sufficient there.

`applyFilterState` (Task 11 Step 5) and expand-all (Task 13 Step 3) **already
carry `applyInfo(r)`** in their ordered chains — do not add a second call.

**The toggle handler needs its whole chain reshaped**, because it does
`.then(function (r) { if (r.status !== 200) throw …; return r.text(); })` —
which discards the `Response` before the body resolves, so `applyInfo(r)` has
nothing to read. Do not improvise this: the non-200 branch has to move, and it
interacts with Task 14's M15 rewrite. Replace `builder.js:490-517` with:

```js
    fetch(scopeUrlFor(pk) + "?" + body.toString(), {
      headers: { "X-Requested-With": "fetch" },
    }).then(function (r) {
      // NESTED so `r` survives into the body handler. applyInfo needs the
      // Response; the old `return r.text()` threw it away.
      return r.text().then(function (html) {
        // The non-200 branch moves HERE and stops being a `throw`. Task 14
        // converts the error arm below to the two-argument `.then` form,
        // which deliberately no longer sees throws from the success path --
        // so a thrown "bad status" would become an unhandled rejection and
        // the author would get no notice at all.
        if (r.status !== 200) {
          notice(msg("network", "Network error — please try again."));
          return;
        }
        // A foreign applyFragment may have replaced this row while we waited.
        var live = root.querySelector('li.tree__row[data-node="' + pk + '"]');
        var ctl = live && live.querySelector(':scope > .tree__rowhead [data-toggle]');
        if (!live || !ctl || !ctl.dataset.submitting) return;
        var incoming = parseFragment(html).firstElementChild;
        if (!incoming) return;
        var dup = live.querySelector(":scope > ol.tree__scope");
        if (dup) dup.remove();
        live.appendChild(incoming);
        ctl.setAttribute("aria-expanded", "true");
        ctl.setAttribute("aria-controls", "tree-scope-" + pk);
        if (ctl.dataset.labelCollapse) {
          ctl.setAttribute("aria-label", ctl.dataset.labelCollapse);
        }
        applyInfo(r);   // AFTER the staleness guard: a response whose row
                        // vanished must not repaint the info slot either.
        syncUrl();
      });
    }).catch(function () {
      notice(msg("network", "Network error — please try again."));
    }).then(function () {
      var ctl2 = root.querySelector('[data-toggle="' + pk + '"]');
      if (ctl2) delete ctl2.dataset.submitting;   // BOTH paths, or the row wedges
      busyEnd();
    });
```

The lines above it are unchanged except for Task 10 Step 4's edit, which
already replaced the hand-built `body.set("open", …)` with
`setTreeParams(new URLSearchParams(), {openOverride: …})`. Leave
`t.dataset.submitting`, `busyStart()` and `scopeUrlFor(pk)` alone.

- [ ] **Step 5: Run the e2e**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q
```

Expected: PASS.

- [ ] **Step 6: Falsify**

1. Change `if (raw === null …) return;` to treat an absent header as a clear → `test_an_absent_header_does_NOT_clear_the_slot` must fail.
2. Skip the "read server-rendered entries" behaviour by keeping a private array instead of querying the DOM → `test_the_info_slot_replaces_by_key` must fail.
3. Replace the `raw === "none"` clear's `infoSlot.replaceChildren()` with
   `infoSlot.innerHTML = "\n"` → `test_the_empty_info_slot_is_not_rendered`
   must fail on the second assertion.

   **Attack the CLEAR, not the insert.** Inserting with
   `insertAdjacentHTML("beforeend", "\n<li>…</li>")` does not redden that row:
   its second assertion runs after a filter → clear cycle, the clear response
   carries `X-Builder-Info: none`, and `replaceChildren()` removes *every*
   child including any stray text node — so `:empty` matches again and the
   mutation is invisible. The residue only survives if the clear itself leaves
   a text node behind.

Restore each.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/static/courses/js/builder.js tests/test_e2e_builder_filter.py
git commit -m "feat(builder): X-Builder-Info client registry"
```

---

## Task 13: Expand-all and collapse-all

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Test: `tests/test_e2e_builder_filter.py`

**Interfaces:**
- Consumes: `data-expand-all`, `data-collapse-all`, `data-expand-all-disabled` (Tasks 3, 9); `setTreeParams`, `appliedQ` (Task 10); `treeGen`, `applyInfo` (Tasks 11, 12).
- Produces: `rewriteBulkHrefs()`.

- [ ] **Step 1: Write the failing e2e**

```python
def test_expand_all_then_collapse_all(page, live_server):
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    page.click("[data-expand-all]")
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')
    page.click("[data-collapse-all]")
    page.wait_for_timeout(300)
    assert page.locator('ol.tree__scope[data-scope]:not([data-scope="top"])').count() == 0
    assert "open=" in page.url


def test_collapse_all_does_not_navigate(page, live_server):
    """It is an <a href>. After a navigation the server renders the same
    collapsed toggles and the same open= in the address bar, so every other
    collapse-all assertion passes through the bug."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    stamp(page)
    page.click("[data-collapse-all]")
    page.wait_for_timeout(300)
    assert_no_navigation(page)


def test_collapse_all_resets_aria_on_every_toggle(page, live_server):
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    page.click("[data-collapse-all]")
    page.wait_for_timeout(300)
    for t in page.locator("[data-toggle]").all():
        assert t.get_attribute("aria-expanded") == "false"
        assert t.get_attribute("aria-controls") is None


def test_collapse_all_over_a_dirty_rename_posts_nothing(page, live_server):
    """A REAL MOUSE CLICK, not keyboard activation: a click moves focus at
    mousedown, so the dirty title's focusout fires BEFORE the click handler,
    when `swapping` is still false and isConnected is still true -- and
    commitRename fires a real POST whose applyRename then no-ops on a detached
    form. DB holds the new title, tree shows the old, nothing is reported.
    The keyboard path was already correct."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    posted = []
    page.on("request", lambda r: posted.append(r.url) if r.method == "POST" else None)
    page.locator(f'li[data-node="{hit.pk}"] input.tree__title').fill("Brudny tytul")
    page.mouse.click(*_center(page.locator("[data-collapse-all]")))
    page.wait_for_timeout(400)
    assert not [u for u in posted if "rename" in u]


def test_expand_all_fires_a_request_UNDER_the_ceiling(page, live_server):
    """The under-ceiling half catches a data-expand-all-disabled emitted BY
    VALUE: "False" is truthy in JS, so the bail fires on every course and the
    control is silently dead everywhere."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None)
    page.click("[data-expand-all]")
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')
    assert sent


def test_the_bulk_hrefs_stay_current_after_a_js_filter_apply(page, live_server):
    """They sit in the header, OUTSIDE every fragment applyFragment swaps, so
    nothing else refreshes them -- and a middle-click on a stale one opens an
    unfiltered open=all render."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    page.fill("#builder-q", "trygo")
    # Same trap: `hit` is already rendered at load on an under-threshold
    # fixture, and rewriteBulkHrefs only runs in the RESPONSE handler ~300 ms
    # later -- so a no-op wait reads the server-rendered href.
    page.wait_for_selector(f'li[data-node="{miss.pk}"]', state="detached")
    href = page.locator("[data-expand-all]").get_attribute("href")
    assert "q=trygo" in href


def test_an_over_ceiling_expand_all_never_grows_an_href(page, live_server, monkeypatch):
    """The `if (!href) return;` guard, as a runnable row rather than a hand
    check. Over the ceiling the server omits the href on purpose; without the
    guard `new URL(null, origin)` yields "/null" and rewriteBulkHrefs turns a
    deliberately inert control into a live link to a 404.

    Collapse-all is the control group: it always has an href, so it proves the
    rewrite still ran and this row is not passing because nothing happened.

    BARRIER NOTE, measured rather than copied. Do NOT reuse the neighbouring
    row's `li[data-node=miss]` + state="detached" wait: under CEILING=0
    `_finalize` truncates the resolved set to EMPTY, so the page loads with the
    chapter COLLAPSED and that <li> is never in the DOM. `state="detached"`
    resolves instantly on a selector that never existed, and the assertions
    would then run inside the 300 ms debounce, before any fetch — reading the
    server-rendered href and failing. Wait on the `filter` info entry instead:
    at load the slot holds only a `truncation` entry (no `q` in the URL), so
    the `filter` entry is a true happens-after signal for the response.
    """
    monkeypatch.setattr("courses.builder_open.CEILING", 0)
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    expand = page.locator("[data-expand-all]")
    assert expand.get_attribute("href") is None, (
        "the server rendered an href over the ceiling; the row proves nothing"
    )
    assert page.locator('[data-info-key="filter"]').count() == 0
    page.fill("#builder-q", "trygo")
    page.wait_for_selector('[data-info-key="filter"]')   # the response landed
    assert expand.get_attribute("href") is None
    assert "q=trygo" in page.locator("[data-collapse-all]").get_attribute("href")


def test_the_bulk_hrefs_are_scrubbed_when_a_below_floor_q_is_cleared(page, live_server):
    """The href half Task 11 deferred to here, now that rewriteBulkHrefs has a
    real body. This is the SKIP path -- no request, no response handler -- so
    the rewrite happens only because applyFilterState calls it inline. The
    server rendered `q=a` into this href, so a no-op leaves it there and a
    middle-click reopens a filter the author cleared.
    """
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=a&open=all")
    assert "q=a" in page.locator("[data-expand-all]").get_attribute("href"), (
        "the server did not render q into the href; the row proves nothing"
    )
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    for hook in ("[data-expand-all]", "[data-collapse-all]"):
        assert "q=" not in page.locator(hook).get_attribute("href"), hook
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q -k "expand or collapse or bulk"
```

Expected: FAIL — the clicks navigate.

- [ ] **Step 3: Expand-all**

```js
  root.addEventListener("click", function (e) {
    var el = e.target.closest("[data-expand-all]");
    if (!el) return;
    e.preventDefault();
    // Both bails. The markup guard is authoritative (the server omits the
    // href over the ceiling), but a preventDefault-then-fetch handler never
    // consults the markup, so without these the disabled control still fires
    // its request. hasAttribute, never getAttribute: the value form renders
    // "False", which is truthy.
    if (el.getAttribute("aria-disabled") === "true") return;
    if (root.hasAttribute("data-expand-all-disabled")) return;

    var url = new URL(root.getAttribute("data-tree-url"), window.location.origin);
    setTreeParams(url, { openOverride: "all" });   // sends the APPLIED q
    var gen = ++treeGen;
    busyStart();
    fetch(url.toString(), { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        return r.text().then(function (text) {
          if (gen !== treeGen) return;
          if (r.status !== 200) { notice(msg("network", "Network error — please try again.")); return; }
          applyFragment(text);
          applyInfo(r);
          rewriteBulkHrefs();
          syncUrl();          // writes the resulting ENUMERATION: the
        });                   // collector can only ever emit one
      })
      .catch(function () { notice(msg("network", "Network error — please try again.")); })
      .then(function () { busyEnd(); });
  });
```

Under a filter this renders from the **restricted** map — ~226 rows on `mat-pp`, not 944 — so it stays enabled and is cheap. It is a no-op when nothing under the filter is collapsed; that is accepted rather than detected, since detecting it means reasoning about which containers the server considers open.

- [ ] **Step 4: Collapse-all — no request at all**

```js
  root.addEventListener("pointerdown", function (e) {
    // Arm `swapping` BEFORE the click: a mouse click moves focus at
    // mousedown, so a dirty title's focusout fires first, and the rename
    // guard would read swapping === false and isConnected === true and commit.
    // Slice 1's arming is deliberately NARROWED to the clicked toggle's own
    // subtree, so this control inherits neither half.
    if (!e.target.closest("[data-collapse-all]")) return;
    var active = document.activeElement;
    if (active && active.closest("ol.tree__scope[data-scope]:not([data-scope='top'])")) {
      swapping = true;
    }
  });

  root.addEventListener("click", function (e) {
    if (!e.target.closest("[data-collapse-all]")) return;
    e.preventDefault();          // it is an <a href>; "no request at all" is
                                 // false without this, and the navigation
                                 // would discard the stash
    swapping = true;
    try {
      root
        .querySelectorAll('ol.tree__scope[data-scope]:not([data-scope="top"])')
        .forEach(function (ol) { ol.remove(); });
    } finally {
      swapping = false;
    }
    root.querySelectorAll("[data-toggle]").forEach(function (t) {
      t.setAttribute("aria-expanded", "false");
      t.removeAttribute("aria-controls");
      // The server-rendered label pair: JS cannot select a Polish plural form.
      var label = t.getAttribute("data-label-expand");
      if (label) t.setAttribute("aria-label", label);
    });
    rewriteBulkHrefs();
    syncUrl();
  });
```

**Accepted cost:** a half-typed rename in a nested row is discarded rather than committed. Under collapse-all the row is removed either way, so the choice is between losing the uncommitted text and shipping a database/tree divergence the author is never told about.

**Second accepted cost, recorded so it is a decision and not a surprise:**
neither bulk control discards `preFilterOpen`. Filter → Expand all → Clear
restores the *pre-filter* enumeration, undoing that expand-all; filter →
Collapse all → Clear re-opens what was just collapsed. This is deliberate and
**consistent with the toggle**, which does not discard the stash either — the
stash means "what the tree looked like before the filter", and every open-set
gesture made *inside* a filter is scoped to that filter. Only a MUTATION
discards it (Task 11 Step 7), because a mutation changes the tree the stashed
enumeration refers to. Do not add `preFilterOpen = null` here without also
adding it to the toggle, or the two gestures start disagreeing.

- [ ] **Step 5: Keep the hrefs current**

**First delete Task 11 Step 3's other stub line** — `function rewriteBulkHrefs() {}`
— and replace it with this. Same trap as Task 12 Step 3: a duplicate
declaration is silently harmless and permanently confusing.

```js
  function rewriteBulkHrefs() {
    // These two sit in .builder__tree's header, OUTSIDE every fragment
    // applyFragment swaps and outside what manage_tree returns -- so unlike
    // the delete and Move hrefs, nothing else refreshes them.
    //
    // Called from the RESPONSE handlers, never from the controls' own click
    // handlers: a click-time rewrite cannot fix the case this exists for,
    // because a middle-click dispatches auxclick, not click.
    root.querySelectorAll("[data-expand-all], [data-collapse-all]").forEach(
      function (el) {
        var href = el.getAttribute("href");
        if (!href) return;       // never ADD one: over the ceiling the control
                                 // is href-less on purpose, and
                                 // new URL(null, origin) yields "/null"
        var u = new URL(href, window.location.origin);
        if (appliedQ) u.searchParams.set("q", appliedQ);
        else u.searchParams.delete("q");
        el.setAttribute("href", u.pathname + u.search);
      }
    );
  }
```

- [ ] **Step 6: Run the e2e**

```bash
uv run pytest tests/test_e2e_builder_filter.py -m e2e -q
```

Expected: PASS.

- [ ] **Step 7: Falsify**

1. Remove `e.preventDefault()` from collapse-all → `test_collapse_all_does_not_navigate` must fail.
2. Remove the `pointerdown` arming → `test_collapse_all_over_a_dirty_rename_posts_nothing` must fail.
3. Change `hasAttribute` to `getAttribute` on `data-expand-all-disabled` → `test_expand_all_fires_a_request_UNDER_the_ceiling` must fail.
4. Drop the `if (!href) return;` guard from `rewriteBulkHrefs` →
   `test_an_over_ceiling_expand_all_never_grows_an_href` must fail, because
   `new URL(null, origin)` yields `/null` and the control acquires a live
   href. (A runnable row, not a hand-check — Task 3 Step 9 rules those out.)

Restore each.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/static/courses/js/builder.js tests/test_e2e_builder_filter.py
git commit -m "feat(builder): expand-all and collapse-all"
```

---

## Task 14: The four deferred slice-1 minors

**Files:**
- Modify: `courses/views_manage.py` (M10), `courses/static/courses/js/builder.js` (M15, M16)
- Test: `tests/test_manage_element_ops.py` (M20)

**Interfaces:** none new. This task lands **after** the feature tasks are green, so a bisect separates it from the feature.

- [ ] **Step 1: M20 — the missing 409 regression test**

The behaviour was decided in the parent spec's §4 as an accepted trade (the 409 renders into the editor, which has no tree pane); only the coverage is missing. Add to `tests/test_manage_element_ops.py`:

**There is no `TextElementFactory` in this repo** — `tests/test_link_transfer.py:15`
and `tests/test_inbound_link_warning.py:13` both say so in comments, and the
idiom is to build the element through `Element` + its concrete model. And
`element_save` (`views_manage.py:1256-1287`) rejects a POST that carries no
`type`/`unit` with `HttpResponseBadRequest` **before** any conflict check, so
the payload below must carry both or the response is a 400 that proves nothing.

**Before writing the test, read `element_save`'s conflict branch and derive the
expected status from it** rather than from this plan — the point of the row is
to pin the behaviour that exists, and slice 1's review recorded it as a 409 on
`_element_conflict`.

**Capture the pk BEFORE the delete.** `Collector.delete()` sets the deleted
instance's `pk` to `None` (`django/db/models/deletion.py`), and Django's test
client refuses `None` in POST data outright — `TypeError: Cannot encode None
for key 'unit' as POST data` — so posting `unit.pk` after `unit.delete()`
errors in the client and never reaches `element_save` at all.

```python
def test_element_save_conflict_after_the_unit_vanished(client, db):
    """The 'unit vanished mid-edit' path, pinned so it stays a decision.

    NOTE the branch this actually takes: with the unit gone, element_save's
    ConflictError handler re-queries it, gets None, and returns
    `_render_tree(request, course, status=409)` (views_manage.py:1299-1300) --
    a TREE pane, not the editor. Spec 4's "the conflict renders into the
    editor" describes the OTHER arm (`:1301-1303`), the one where the unit
    still exists. Derive the expected status by reading that branch, not from
    this plan.
    """
    owner = make_login(client, "pa")
    course = CourseFactory(slug="conf", owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", parent=None)
    element = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="before")
    )
    unit_pk = unit.pk                      # BEFORE the delete -- see above
    stale_token = unit.updated.isoformat()
    unit.delete()
    url = reverse("courses:manage_element_save", kwargs={"slug": course.slug})
    resp = client.post(
        url,
        {
            "type": "text",
            "unit": unit_pk,
            "element": element.pk,
            "unit_token": stale_token,
            "body": "after",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 409
```

Because that arm returns `_render_tree`, this response **does** carry the
`X-Builder-Info` header Task 5 added — `_render_tree` wraps `_render_scope`.
That is consistent with `test_a_rename_and_a_422_carry_no_header_at_all`, which
covers only the two paths that never reach `_render_scope`.

- [ ] **Step 2: M10 — DROPPED, and the reason recorded**

The ledger entry reads "`_persist_chain` re-runs `_children_map` on the no-JS
redirect path", implying a caller already holds that map. **It does not.**
`_persist_chain` is called from `node_add` (`views_manage.py:488`), `node_move`'s
reparent branch (`:620`) and `node_duplicate` (`:714`), and `grep -n
"_children_map("` shows the only call sites are `:247`, `:271`, `:329`, `:412`
(inside `_persist_chain` itself), `:733` and `:796` — none of the three callers
computes one. Threading a map in would mean *adding* `_children_map(course)` to
each caller to pass it down: the same query, moved.

A real fix would give `_persist_chain` a narrower dependency (the container-pk
set) and find someone who already has it. Nobody on the no-JS redirect path
does. **Record M10 as investigated-and-dropped in
`docs/superpowers/notes/2026-07-28-affected-tests-slice2.md`** — Task 0's
ledger, and the only one that exists at this point; Task 16's progress note is
not created until Task 16 Step 5 — with this finding, so it is not re-opened on
the same false premise. Step 6's `git add` includes that path, or the finding
is written and never committed.

- [ ] **Step 3: M15 — the `.catch` mislabel, file-wide**

The tree-pane `.catch` sites in `builder.js` also swallow errors thrown inside
their success `.then`, mislabelling them "Network error". Fix those
**together**, since this slice added two more fetches and Task 12 already
reshaped the toggle's chain.

**Exactly five sites, and two deliberate exclusions.** Apply the rewrite to:
the submit handler, the toggle (as Task 12 Step 4 reshaped it), the drop
handler, and the two fetches this slice added — `applyFilterState`
(Task 11 Step 5) and expand-all (Task 13 Step 3).

**Identify them by shape, not by line number.** Tasks 11–13 insert two new
fetches and rewrite the toggle's whole chain, so every numeral in the shipped
file has moved by the time this task runs. The criterion is the one already
used below to exclude the other two: a site qualifies iff it pairs
`busyStart()` with a trailing `.then(…)` **whose body calls `busyEnd()`**.
(Not "whose body *is* `busyEnd()`" — the toggle's trailing handler also clears
`ctl2.dataset.submitting`, and it is one of the five.)

**Do NOT touch `loadPanel` or the Move-picker fetch.**
Neither has a `busyStart`/`busyEnd` pair, so the snippet's trailing
`.then(function () { busyEnd(); })` would decrement a counter nothing
incremented and corrupt the busy state for every other request. Neither nests
`r.text().then(…)`. And `loadPanel`'s `.catch` is deliberately gated on
`id === panelReq` (its comment at `:305-308` explains why: an ungated slow
FAILURE from an earlier row would replace a later row's loaded panel with an
error box) — the snippet has no such gate and would drop that guard. They are
panel fetches, not tree-pane fetches; M15 is not about them.

```js
    }).then(function (r) {
      return r.text().then(function (text) { /* success work */ });
    }, function () {
      notice(msg("network", "Network error — please try again."));   // network only
    }).then(function () { busyEnd(); });
```

The two-argument `.then` form separates a rejected fetch from a throw in the success path.

**The submit handler's error arm is TWO statements, not one.** Its shipped
`.catch` (`builder.js:264-267`) is `notice(...)` **and** `releaseForm(form);`,
and dropping the second leaves the rename form's input permanently locked after
any network failure — with nothing in this plan covering it. Its arm reads:

```js
    }, function () {
      notice(msg("network", "Network error — please try again."));
      releaseForm(form);
    }).then(function () { busyEnd(); });
```

**Accepted consequence, stated rather than discovered:** the whole point of the
two-argument form is that a *throw* in the success path no longer reaches this
arm — so such a throw now also skips `releaseForm`. That is the right trade
here (the success arm already calls `releaseForm(form)` on every status
branch, so only a genuine bug in `applyFragment`/`applyRename` could skip it,
and silently mislabelling that bug as "Network error" is what M15 exists to
stop). Do **not** "fix" it by moving `releaseForm` into the trailing
`.then(function () { busyEnd(); })`: that runs on the stale-response path too.

- [ ] **Step 4: M16 — the `swapping` blur disarm**

`swapping` latches true if `pointerup` never fires (window blur mid-press). `pointerFocus` has the same shape:

```js
  window.addEventListener("blur", function () { swapping = false; pointerFocus = false; });
```

- [ ] **Step 5: Run the affected suites**

```bash
uv run pytest tests/test_manage_element_ops.py tests/test_manage_node_ops.py -q
uv run pytest tests/test_e2e_builder_toggle.py tests/test_e2e_builder_filter.py -m e2e -q
uv run pytest tests/test_e2e_builder_ws2.py tests/test_e2e_builder_authoring.py \
  tests/test_e2e_builder_reorder.py tests/test_e2e_inline_rename.py -m e2e -q
```

Expected: exit 0 for all three.

**The third command is not optional, for the same reason Task 9 Step 5 runs the
layout suite.** M15 rewrites the submit handler (`:264`) and the drop handler
(`:652`) — the two most-used gestures — and the two-argument `.then` form
deliberately stops a throw in the success path from producing any notice at
all. `test_e2e_builder_ws2.py` is the only suite that drives the drop handler,
and `test_e2e_builder_authoring.py`, `test_e2e_builder_reorder.py` and
`test_e2e_inline_rename.py` are the ones that drive the submit handler.
Deferring them to Task 16 puts the breakage one commit and six steps away from
its cause, mixed in with the probe and screenshot work. (`-m e2e` mandatory;
exit 5 is not a pass.)

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add courses/ tests/ docs/superpowers/notes/2026-07-28-affected-tests-slice2.md
git commit -m "fix(builder): clear the four deferred slice-1 minors"
```

---

## Task 15: Catalogs

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ compiled `.mo`)

**Interfaces:** none.

- [ ] **Step 1: Regenerate**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

- [ ] **Step 2: Check the count**

**Eight new msgids** are expected: the `filter` notice text, "Clear", "Expand all", "Collapse all", the over-ceiling tooltip, "No matching titles.", "Filter by title", and "Clear the filter to reorder."

**Two existing msgids gain a further reference and must NOT appear as new entries:**

- `"Only the first %(limit)s scopes were opened."` — shipped in slice 1 (`views_manage.py:369-370`, `django.po:2237`). `data-msg-truncation` adds a *reference*, not an entry. **If the diff shows a new entry for it, the Python literal and the template literal have drifted apart** — that is the defect §3i's one-msgid rule exists to prevent.
- `"Filter"` — already ships with five references (`django.po:3509`), including `templates/courses/manage/media/manager.html:36`. The submit button reuses it; only the field's accessible name is new.

- [ ] **Step 3: Translate, and clear every fuzzy entry**

A fuzzy entry arrives **pre-filled with an unrelated translation**, so leaving one ships a wrong Polish string that reads as deliberate. Clearing is **two deletions** per entry: the `#, fuzzy` line and the `#| msgid` line.

Polish for the eight, matching the existing register:

```
"Filtered: %(shown)s / %(total)s"  -> "Filtrowane: %(shown)s / %(total)s"
"Clear"                            -> "Wyczyść"
"Expand all"                       -> "Rozwiń wszystko"
"Collapse all"                     -> "Zwiń wszystko"
"This course is too large to expand at once."
                                   -> "Ten kurs jest zbyt duży, aby rozwinąć go naraz."
"No matching titles."              -> "Brak pasujących tytułów."
"Filter by title"                  -> "Filtruj według tytułu"
"Clear the filter to reorder."     -> "Wyczyść filtr, aby zmienić kolejność."
```

**No varying numeral governs a noun** in either `data-msg-*` string — "Filtrowane: 100 / 940", never "pokazano 100 wyników", because the latter needs a plural form the JS cannot select.

- [ ] **Step 4: Compile and verify**

```bash
uv run python manage.py compilemessages
uv run pytest tests/test_i18n_po_health.py -q
grep -rc "#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
```

**Both catalogs, expect 0 in each.** Step 1 regenerates `-l pl -l en`, so
`makemessages` can leave a fuzzy in `en` just as easily — and a fuzzy arrives
pre-filled from an unrelated msgid, so it ships a wrong string that reads as
deliberate. Checking only `pl` lets that through both gates.

- [ ] **Step 5: Pin the one-msgid rule — the row that had to wait for the catalog**

**This row belongs here, not in Task 5.** It asserts the Polish render, and
`"Filtered: %(shown)s / %(total)s"` does not exist in `locale/pl` until Step 1
of this task creates it and Step 4 compiles it — I checked: neither "Filtered"
nor "Filtrowane" appears in the catalog today. Placed in Task 5 it would be RED
from Task 5 through Task 14, reddening the whole-file gate at the end of Tasks
5, 6, 7, 8 and 9 for a reason that is not a regression.

(Its sibling, `test_the_header_is_machine_readable_under_the_polish_locale`,
correctly stays in Task 5: the only Polish string it depends on is the
truncation notice, which slice 1 already shipped at `django.po:2237`.)

Append to `tests/test_builder_filter_views.py`:

```python
def test_one_msgid_per_notice(filtered_course):
    """The page route and the fragment route render the SAME literal, so
    makemessages collapses them into one catalog entry. Two entries would let
    them be translated differently and disagree about what the tree shows.

    They are not directly comparable -- the server interpolates while the
    attribute keeps its placeholders -- so a literal equality assertion fails
    on a CORRECT implementation. Substitute, then compare.
    """
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    # The login signal has already pinned session["_language"] to "en", so
    # Accept-Language is never consulted. Without this seed the row still
    # passes, but vacuously: it would compare an English template against an
    # English render and could not detect the two literals drifting apart.
    session = client.session
    session["_language"] = "pl"
    session.save()
    body = client.get(url, {"q": "trygo"}, HTTP_ACCEPT_LANGUAGE="pl").content.decode()
    assert "Filtrowane" in body, "the Polish catalog is not active; the row is vacuous"
    template = body.split('data-msg-filter="')[1].split('"')[0]
    rendered = body.split('data-info-key="filter">')[1].split("<")[0]
    assert template % {"shown": 1, "total": 1} == rendered
```

```bash
uv run pytest tests/test_builder_filter_views.py -q -k one_msgid_per_notice
```

Expected: PASS. If it fails on the `"Filtrowane"` guard, `compilemessages` did
not run or the msgstr is still empty — fix the catalog, not the test.

**Falsify:** give `data-msg-filter` a *different* msgid from the Python
literal — e.g. change the template to `{% trans 'Filtered: %(shown)s of %(total)s' %}`,
re-run `makemessages`, translate the new entry differently — and this row must
fail. Restore, and re-run `makemessages`/`compilemessages` so the stray entry
does not ship.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check .
git branch --show-current
git add locale/ tests/test_builder_filter_views.py
git commit -m "i18n(builder): eight new msgids for the filter and bulk controls"
```

`tests/` is in the `git add` because Step 5 adds a row to it; `locale/` alone
would leave that test uncommitted.

---

## Task 16: Migrate the suite, measure, and record the verdict

**Files:**
- Modify: whichever existing tests encode the changed behaviour
- Modify: `docs/superpowers/notes/2026-07-28-slice2-progress.md`

**Interfaces:** none.

- [ ] **Step 1: Run the whole affected set**

Chunked, in the **foreground**, one invocation at a time. Never background a long run — three subagents stalled forever on notifications that never arrived.

```bash
uv run pytest tests/test_builder_filter.py tests/test_builder_filter_views.py tests/test_builder_open_ids.py tests/test_builder_lazy_scopes.py -q
uv run pytest tests/test_manage_node_ops.py tests/test_manage_element_ops.py tests/test_manage_move_picker.py tests/test_manage_affordance.py tests/test_builder_styles.py tests/test_builder_js_invariants.py -q
uv run pytest tests/test_i18n_po_health.py tests/test_manage_builder.py tests/test_tree_badge.py tests/test_manage_duplicate_button.py tests/test_builder_duplicate_unit.py tests/test_manage_node_duplicate.py -q
uv run pytest tests/test_e2e_builder_filter.py tests/test_e2e_builder_toggle.py tests/test_e2e_builder_reorder.py -m e2e -q
uv run pytest tests/test_e2e_builder_ws2.py tests/test_e2e_builder_authoring.py tests/test_e2e_builder.py tests/test_e2e_builder_tree_layout.py tests/test_e2e_inline_rename.py -m e2e -q
```

Each must exit 0. Anything red outside the three files Task 0 predicted is a regression.

- [ ] **Step 2: Teach the existing probe about `q`**

`scripts/perf/` holds exactly two probes, `probe_tree_render.py` and
`probe_browser.py`. **Neither takes `--course`/`--q`/`--open`** — both are driven
by environment variables and run through `manage.py shell -c "exec(open(...).read())"`,
and `probe_browser.py`'s own comment records that argparse errors with
"unrecognized arguments" under that invocation. There is no `probe_builder.py`.
So the filtered timing needs one small extension rather than a new script.

Add a `Q=` variable to `probe_tree_render.py` beside the existing `SLUG=`/`OPEN=`
handling. Keep the env-var interface — it is what makes the `manage.py shell`
invocation work.

**Spell the whole diff, because the probe's own comment (`:72-76`) records the
failure a partial one produces:** a wrong or absent `open_ids` renders the tree
*silently collapsed*, "which would make every 'after' number look like a huge
win for the wrong reason". The probe builds its render context by hand at
`:77-88`, so **every** key has to move together:

**Written against the file as it actually is.** The probe deliberately carries
no view imports beyond `_children_map`, so it ships its own `_descendants`
(`:39`), and its locals are `ids` (`:67`) and `ctx` (`:77`) — not `open_ids`
and `context`:

```python
# beside SLUG/OPEN (:24-25)
Q = os.environ.get("Q", "")

# after `ids` is resolved (:67), before ctx is built (:77)
render_map = cmap
if Q:
    # Imported HERE, not at the top. `_containers` (:28-33) and `_descendants`
    # (:39) are deliberate local copies so the probe RUNS ON TODAY'S CODE --
    # their docstrings say so in as many words ("so this probe runs BEFORE
    # courses.builder_open exists"). A module-level import executes
    # unconditionally and would destroy exactly that property, making the
    # BEFORE half of every comparison impossible on a clean checkout. Inside
    # the `if Q:` block the import only runs when the caller asked for a
    # filtered measurement, which by definition is an AFTER run.
    from courses.builder_filter import filtered_map

    restricted, chains, shown, total, _active = filtered_map(cmap, Q)
    render_map = restricted
    ids = chains
    print(f"filtered: shown={shown} total={total}")

ctx = {
    "nodes": render_map.get(None, []),
    "children_map": render_map,                    # RESTRICTED when Q is set
    "open_ids": ids,
    "open_joined": ",".join(str(p) for p in sorted(ids)),
    "open_descendants": _descendants(cmap, ids),   # the FULL map, always
    "q": Q,
    "filtered": bool(Q),
    "scope_id": "top",
    "scope_updated": course.updated.isoformat(),
    "parent_kind": None,
    "course": course,
    "builder_url": f"/manage/courses/{course.slug}/build/",
}
```

`q` and `filtered` matter: without them the timed render skips the per-row
`{% if q %}` hidden inputs and the `{% if filtered %}` branches, and measures a
cheaper page than the one that ships. Report rows and scopes alongside the
milliseconds so the 226/126 prediction is checkable.

- [ ] **Step 3: Measure against `mat-pp`**

Every probe carries the explicit dev-DB prefix (the perf data lives in the
shared dev database; this worktree's `.env` points pytest elsewhere):

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli SLUG=mat-pp Q=trygo \
  uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
DATABASE_URL=postgres://libli:libli@localhost:5432/libli SLUG=mat-pp OPEN=all \
  uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
DATABASE_URL=postgres://libli:libli@localhost:5432/libli SLUG=mat-pp \
  uv run python manage.py shell -c "exec(open('scripts/perf/probe_tree_render.py').read())"
```

Record against the targets:

| Metric | Target | Prediction to check |
| --- | --- | --- |
| filter round trip | < 1 s | ≥ 700 ms (≈226 rows across ~126 scopes) — a **lower bound** from a row-linear model that under-counts per-scope work. The number most at risk. |
| expand-all | busy visible throughout; no "Page unresponsive" | ~2.5 s server-side |
| toggle round trip | < 300 ms | **re-measure** — `_render_scope` now does the filter walk on every fragment |
| unfiltered page load | no regression on 991 ms / 83 KB / 968 elements | — |

**Do not optimise `_render_scope`'s full-cmap rebuild in this slice.** Narrowing it would help only the *unfiltered* toggle — under a filter the full map is required by both `_open_ids`'s sanitisation and the ancestor walk — and would fork the fragment contract. If the toggle misses in production, that narrowing is still the sanctioned first remedy.

- [ ] **Step 4: Screenshot the UI**

Playwright, **light and dark**, judged separately rather than inferred from one another: the header at 1400px and narrow, a filtered tree, the "Filtered: n / m" notice, an empty filtered scope, and the disabled grip/arrows.

- [ ] **Step 5: Write the ledger**

Create (it does not exist yet — no earlier step writes it) or append to
`docs/superpowers/notes/2026-07-28-slice2-progress.md`: per-task commit ranges,
the falsification results, the measured numbers against the table above, and
any deviation from this plan with its reason.

- [ ] **Step 6: Final lint and commit**

```bash
uv run ruff format --check . && uv run ruff check .
git branch --show-current
git add docs/superpowers/notes/2026-07-28-slice2-progress.md scripts/perf/probe_tree_render.py
git commit -m "chore(builder): slice 2 verdict — measurements and ledger"
```

---

## Verification checklist before the PR

- [ ] Every task's falsification produced RED and was restored.
- [ ] `uv run ruff format --check .` and `uv run ruff check .` both exit 0.
- [ ] Every suite in Task 16 Step 1 exits 0 — and the e2e runs carried `-m e2e` (exit 5 is not a pass).
- [ ] `grep -rc "#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po` returns 0 for **both**; `.mo` files regenerated with `compilemessages`, never merged by hand.
- [ ] The branch is rebased on master and the `.mo` files regenerated **after** the rebase — a tracked binary `.mo` has no 3-way merge.
- [ ] `git branch --show-current` is `worktree-builder-large-course-perf`.
- [ ] The measured filter round trip is recorded in the PR body against the < 1 s target, with the before-numbers from the spec.
