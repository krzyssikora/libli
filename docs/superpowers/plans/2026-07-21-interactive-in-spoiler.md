# Interactive elements as spoiler children — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `reveal_gate`, `switch_gate`, `fill_gate`, `switch_grid`, and `fill_blank` (FillBlankQuestionElement) as depth-1 leaf children of a `SpoilerElement`, preserving their interactivity, across loader/editor/transfer, JS-wiring, the reveal cascade, and editor authoring.

**Architecture:** Four layers. (1) Widen the child allowlist — one canonical-key frozenset (`SPOILER_CHILD_TYPES`) read by three sites in three type-key namespaces, each normalized to canonical. (2) Make `has_questions` a flat unit-wide query so a spoiler-nested `fillblank` loads `question.js`. (3) Teach `reveal.js`'s cascade + the pre-hide CSS that a spoiler body is a scope. (4) Editor add-menu: show the 4 gate cards + a `fillblankquestion` card in a spoiler, guard the 5 non-allowed cards. No new element type, no migration.

**Tech Stack:** Django, vanilla JS (`reveal.js`), Django templates, pytest, Playwright (e2e), `uv run` for all tooling.

## Global Constraints

- **No migration; no new model.** All changes are allowlists, one query, JS/CSS, and a template. The parser is UNCHANGED (it already emits these as spoiler children).
- **Depth-1 invariant preserved.** All 5 types are leaves. Containers (`tabs`/`two_column`) and spoiler-in-spoiler stay rejected. A nested (depth-2) spoiler still takes no children (`resolve_scope`'s `join.parent_id is not None` guard is untouched).
- **Canonical key = transfer key.** `SPOILER_CHILD_TYPES` holds canonical keys `reveal_gate, fill_gate, switch_gate, switch_grid, fill_blank`. Each non-canonical check site normalizes first: editor form keys via `_NESTABLE_FORM_KEY_ALIASES`, the LAL loader's parser keys via `_PARSER_TO_CANONICAL` (only `fillblank`→`fill_blank` diverges).
- **REJECT-LOUDLY preserved for genuinely unsupported nesting** (containers, spoiler-in-spoiler): the widened allowlists still raise `LoaderError`/`NestingError`/transfer errors for those.
- **Tooling env:** run pytest as `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest …` from the worktree root. `ruff`/`pytest` are NOT on PATH — always `uv run`. Before every commit run `uv run ruff check <files>` and `uv run ruff format --check <files>`; fix with `uv run ruff format` + address check errors (plan code is verbatim and may not be ruff-clean).
- **Commit style:** end commit messages with the branch's two trailer lines (`Co-Authored-By: Claude …` / `Claude-Session: …`).

---

## File Structure

- `courses/builder.py` — `SPOILER_CHILD_TYPES` (l.60), `NESTABLE_TYPE_KEYS` (l.34), `_NESTABLE_FORM_KEY_ALIASES` (l.65), `resolve_scope` spoiler branch (l.118). [Task 1]
- `courses/lal_loader/builders.py` — new `_PARSER_TO_CANONICAL` + the spoiler-child check (l.83). [Task 1]
- `courses/views.py` — `has_questions` (l.340). [Task 2]
- `courses/static/courses/js/reveal.js` — `scopeOf` (l.44), `isGateWrapper` (l.60). [Task 3]
- `templates/courses/lesson_unit.html` — pre-hide `<style>` (l.39). [Task 3]
- `templates/courses/manage/editor/_add_menu.html` — Interactive group guard + per-card guards + fillblank card (l.27-48). [Task 4]
- Tests: `courses/tests/test_spoiler_nesting.py` (resolve_scope + add-menu), `courses/tests/test_spoiler_transfer.py` (round-trip), the LAL loader tests (`courses/tests/test_lal_loader_units.py`), a views/`build_lesson_context` test module, and the reveal e2e test module.

---

## Task 1: Widen the spoiler-child allowlist (model/loader/editor-scope/transfer)

**Files:**
- Modify: `courses/builder.py:34,60,65,118`
- Modify: `courses/lal_loader/builders.py` (add `_PARSER_TO_CANONICAL`; l.83 check)
- Test: `courses/tests/test_spoiler_nesting.py`, `courses/tests/test_spoiler_transfer.py`, `courses/tests/test_lal_loader_units.py`

**Interfaces:**
- Consumes: existing `_attach`, `build_element`, `resolve_scope`, `validate_nesting`.
- Produces: `SPOILER_CHILD_TYPES` now includes the 5 canonical interactive keys; `resolve_scope(unit, spoiler_join_pk, SLOT_ID, form_key)` returns `(join, SLOT_ID)` for the 5 interactive form keys; the LAL loader accepts these as spoiler children. Task 3/4 rely on being able to CREATE a spoiler-nested gate (via loader or editor).

- [ ] **Step 1: Write the failing tests**

Add to `courses/tests/test_spoiler_nesting.py`, reusing that file's existing helpers `make_course_with_unit()` and `_spoiler_join(unit, parent=None, tab_id="")` (l.103-107, returns `(sp, join)`) and `NestingError` imported from `courses.builder` (NOT `courses.exceptions`):

```python
import pytest
from courses.builder import SPOILER_CHILD_TYPES, NESTABLE_TYPE_KEYS, NestingError
from courses.models import SpoilerElement
from courses import builder


INTERACTIVE_SPOILER_FORM_KEYS = [
    "revealgate", "fillgate", "switchgate", "switchgrid", "fillblankquestion",
]


def test_spoiler_child_types_includes_interactive_leaves():
    for k in ("reveal_gate", "fill_gate", "switch_gate", "switch_grid", "fill_blank"):
        assert k in SPOILER_CHILD_TYPES
    for k in ("tabs", "two_column", "spoiler"):  # containers still excluded
        assert k not in SPOILER_CHILD_TYPES


def test_nestable_type_keys_includes_fill_blank():
    assert "fill_blank" in NESTABLE_TYPE_KEYS


@pytest.mark.django_db
@pytest.mark.parametrize("form_key", INTERACTIVE_SPOILER_FORM_KEYS)
def test_resolve_scope_accepts_interactive_form_key_in_spoiler(form_key):
    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    parent_join, tab = builder.resolve_scope(
        unit, str(join.pk), SpoilerElement.SLOT_ID, form_key
    )
    assert parent_join == join
    assert tab == SpoilerElement.SLOT_ID


@pytest.mark.django_db
def test_resolve_scope_still_rejects_children_of_nested_spoiler():
    # a spoiler whose OWN join.parent_id is not None (depth-2) takes no children
    _course, unit = make_course_with_unit()
    _outer_sp, outer_join = _spoiler_join(unit)
    _inner_sp, inner_join = _spoiler_join(unit, parent=outer_join, tab_id=SpoilerElement.SLOT_ID)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(inner_join.pk), SpoilerElement.SLOT_ID, "switchgate")
```

**Update the EXISTING `test_resolve_scope_rejects_disallowed_child_type_in_spoiler` (l.122-131):** its bad set is currently `("tabs", "spoiler", "revealgate", "choicequestion")`, but `revealgate` is now ALLOWED. Change the loop to `for bad in ("tabs", "spoiler", "choicequestion"):` — `tabs`/`spoiler` (containers) and `choicequestion` (a non-fillblank question form key) stay rejected; this doubles as the "non-fillblank question still rejected" regression assertion.

Add a LAL-loader test in `courses/tests/test_lal_loader_units.py` (follow that file's `build_element`/spoiler fixtures) — a spoiler JSON dict whose `elements` include one interactive child each; assert each loads with `parent=<spoiler join>`, `tab_id=SLOT_ID`, no `LoaderError`. Include the `fillblank` case explicitly (exercises `_PARSER_TO_CANONICAL`):

```python
@pytest.mark.django_db
@pytest.mark.parametrize("child", [
    {"type": "reveal_gate", "label": "pokaż"},
    {"type": "switch_gate", "stem": "s", "options": ["a", "b"], "answer": 0},
    {"type": "fill_gate", "stem": "s", "answers": [["1"]]},
    {"type": "switch_grid", "prompt": "", "lines": [{"stem": "s", "cyclers": [{"options": ["a", "b"], "answer": 0}]}]},
    {"type": "fillblank", "stem": "x = ￼0￼", "blanks": [["0"]]},
])
def test_loader_accepts_interactive_spoiler_child(child, course, unit):
    from courses.lal_loader.builders import build_element
    el = {"type": "spoiler", "label": "rozwiązanie", "elements": [child]}
    spoiler = build_element(course, unit, el, source_root="", source_dir="", allow_html=False)
    kids = spoiler.join_row().resolved_children()  # or query Element by parent
    assert len(kids) == 1
```
(Match the real `build_element` signature + child-query helper in that test file; the `fillblank` stem token uses the sentinel `￼` per `scripts/lal_import/fillblank`.)

Add a transfer round-trip test in `courses/tests/test_spoiler_transfer.py` (follow that file's export→import helpers): export a unit with a spoiler containing a `switch_gate` child and a `fill_blank` child, import into a fresh course, assert both survive as spoiler children with their data; and assert `validate_nesting` still rejects a `tabs`-in-spoiler archive.

- [ ] **Step 2: Run the tests to verify they fail (RED)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py courses/tests/test_lal_loader_units.py -k "interactive or fill_blank or nestable_type_keys or spoiler_child_types or container" -v
```
Expected: FAIL — `SPOILER_CHILD_TYPES` lacks the 5 keys; `resolve_scope` raises `NestingError` for the form keys; the loader raises `LoaderError`; transfer rejects.

- [ ] **Step 3: Widen `SPOILER_CHILD_TYPES` + `NESTABLE_TYPE_KEYS` + aliases (builder.py)**

`courses/builder.py` — update the comment above `SPOILER_CHILD_TYPES` and the frozenset (l.57-62):

```python
# Leaf children a spoiler may hold (server-enforced), in CANONICAL (transfer) keys.
# Static leaves PLUS the interactive leaves (reveal/fill/switch gate, switch grid,
# fill blank). Excludes spoiler itself and native containers (tabs/two_column) — the
# depth-1 leaf-only scope. Non-canonical callers normalize first: editor form keys via
# _NESTABLE_FORM_KEY_ALIASES, the LAL loader's parser keys via its _PARSER_TO_CANONICAL.
SPOILER_CHILD_TYPES = frozenset(
    {
        "text", "math", "image", "video", "iframe", "table", "gallery", "callout",
        "reveal_gate", "fill_gate", "switch_gate", "switch_grid", "fill_blank",
    }
)
```

Add `"fill_blank",` to the `NESTABLE_TYPE_KEYS` frozenset (l.34-55), e.g. after `"switch_grid",`:

```python
        "switch_grid",
        "fill_blank",
        "fill_table",
```

Add the fillblank form-key alias to `_NESTABLE_FORM_KEY_ALIASES` (l.65-73):

```python
    "fillblankquestion": "fill_blank",
    "fillgate": "fill_gate",
```
(insert `"fillblankquestion": "fill_blank",` into the dict, keeping alphabetical-ish order).

- [ ] **Step 4: Normalize the form key in `resolve_scope`'s spoiler branch (builder.py:118)**

Change the spoiler-branch check:
```python
        if type_key not in SPOILER_CHILD_TYPES:
            raise NestingError(f"{type_key} may not be nested inside a spoiler")
```
to normalize the incoming editor form key to canonical first (a static type's form key equals its canonical key, so the alias is a no-op for those — no regression):
```python
        child_key = _NESTABLE_FORM_KEY_ALIASES.get(type_key, type_key)
        if child_key not in SPOILER_CHILD_TYPES:
            raise NestingError(f"{type_key} may not be nested inside a spoiler")
```

- [ ] **Step 5: Normalize the parser key in the LAL loader (builders.py)**

`courses/lal_loader/builders.py` — add a module-level constant near the top (after imports):
```python
# The LAL parser emits "fillblank"; the canonical/transfer key is "fill_blank".
# Every other interactive/static parser type key already equals its canonical key.
_PARSER_TO_CANONICAL = {"fillblank": "fill_blank"}
```
Change the spoiler-child allowlist check (l.83) from:
```python
                if not child.get("flagged") and ctype not in SPOILER_CHILD_TYPES:
```
to:
```python
                canonical = _PARSER_TO_CANONICAL.get(ctype, ctype)
                if not child.get("flagged") and canonical not in SPOILER_CHILD_TYPES:
```
(Update the nearby comment: the check now permits interactive leaves too, via canonical normalization.)

- [ ] **Step 6: Run the tests to verify they pass (GREEN)**

Run the same command as Step 2. Expected: PASS (all new + updated tests).

- [ ] **Step 7: Run the broader affected suite (regression)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py courses/tests/test_lal_loader_units.py courses/tests/test_callout_transfer.py courses/tests/test_fillgate_transfer.py -q
```
Expected: PASS (the `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)` invariant test still holds — `fill_blank` ∈ `SERIALIZERS`).

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check courses/builder.py courses/lal_loader/builders.py courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py courses/tests/test_lal_loader_units.py
uv run ruff format --check courses/builder.py courses/lal_loader/builders.py courses/tests/
git add courses/builder.py courses/lal_loader/builders.py courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py courses/tests/test_lal_loader_units.py
git commit -m "feat(spoiler): allow interactive leaves as spoiler children (allowlist)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DAtycPcTv4NLRZctpoTA1u"
```

---

## Task 2: `has_questions` flat query (JS wiring for nested fillblank)

**Files:**
- Modify: `courses/views.py:340`
- Test: `courses/tests/test_spoiler_context.py` (the spoiler-specific `build_lesson_context` test module; follow its existing setup + `test_switchgate_context.py`/`test_fillgate_context.py` for the `has_*` assertion pattern).

**Interfaces:**
- Consumes: `question_ct_ids` (already computed at `views.py:334`).
- Produces: `build_lesson_context(node, user)["has_questions"]` is True when a question exists anywhere in the unit (incl. a spoiler-nested `fillblank`).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_has_questions_true_for_spoiler_nested_fillblank(unit_with_fillblank_in_spoiler, some_user):
    # unit_with_fillblank_in_spoiler: a unit whose ONLY question is a FillBlankQuestionElement
    # nested as a spoiler child (build via the loader from Task 1, or directly via ORM).
    from courses.views import build_lesson_context
    ctx = build_lesson_context(unit_with_fillblank_in_spoiler, some_user)
    assert ctx["has_questions"] is True


@pytest.mark.django_db
def test_has_questions_false_when_no_questions(unit_text_only, some_user):
    from courses.views import build_lesson_context
    assert build_lesson_context(unit_text_only, some_user)["has_questions"] is False
```

- [ ] **Step 2: Run the test to verify it fails (RED)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest -k has_questions -v
```
Expected: `test_has_questions_true_for_spoiler_nested_fillblank` FAILS (the top-level-only scan returns False for a spoiler-nested fillblank).

- [ ] **Step 3: Make `has_questions` a flat query (views.py:340)**

Change:
```python
    has_questions = any(el.content_type_id in question_ct_ids for el in elements)
```
to:
```python
    # Flat unit-wide (NOT scoped to parent__isnull=True) so a question nested in a
    # spoiler/tab — children keep their own `unit` FK — is still detected, arming
    # question.js/dnd.js. Only fill_blank is nestable today, so this only newly fires
    # for a nested fillblank; top-level behaviour is unchanged.
    has_questions = node.elements.filter(content_type_id__in=question_ct_ids).exists()
```

- [ ] **Step 4: Run the test to verify it passes (GREEN)**

Run the Step-2 command. Expected: PASS both.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views.py courses/tests/test_spoiler_context.py
uv run ruff format --check courses/views.py courses/tests/test_spoiler_context.py
git add courses/views.py courses/tests/test_spoiler_context.py
git commit -m "fix(lesson): detect nested questions unit-wide for JS wiring (has_questions flat)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DAtycPcTv4NLRZctpoTA1u"
```

---

## Task 3: Reveal-cascade spoiler scope (reveal.js + pre-hide CSS)

Teach the cascade + pre-hide that a spoiler body is a cascade scope, so a spoiler-nested `reveal_gate`/`switch_gate`/`fill_gate` reveals content WITHIN the spoiler. Verify the DOM assumption FIRST.

**Files:**
- Modify: `courses/static/courses/js/reveal.js:44,60-66`
- Modify: `templates/courses/lesson_unit.html:39-40`
- Test: a render/DOM test in `courses/tests/test_reveal_gate_render.py` (server-side render assertions) + an e2e test in `tests/test_e2e_reveal_gate.py` (mirror its login/seed/unit harness — `tests/test_e2e_fillgate.py` and `tests/test_e2e_guessnumber.py` both reuse it, incl. guessnumber's "behind a reveal gate" nesting smoke test as a pattern).

**Interfaces:**
- Consumes: a creatable spoiler-nested gate (Task 1); `has_reveal_gate` flat flag (already fires for spoiler-nested gates).
- Produces: no Python API change; the cascade/pre-hide now scope to `.spoiler`.

- [ ] **Step 1: DOM verification (Task-0 spike) — assert the gate is a direct child of `.spoiler__child`**

Write a Django render test that builds a top-level spoiler with a `reveal_gate`, a `switch_gate`, and a `fill_gate` child (via the Task-1 loader or ORM), renders the lesson unit, and asserts each gate's `[data-reveal-gate]` element is a DIRECT child of a `.spoiler__child` div:

```python
@pytest.mark.django_db
def test_spoiler_gate_child_is_direct_child_of_spoiler_child(client, unit_with_gates_in_spoiler):
    html = client.get(unit_with_gates_in_spoiler.get_absolute_url()).content.decode()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for wrap in soup.select(".spoiler .spoiler__child"):
        gate = wrap.find(attrs={"data-reveal-gate": True})
        if gate is not None:
            assert gate.parent is wrap, "gate must be a DIRECT child of .spoiler__child"
```
Run it. **If it fails** (a wrapper intervenes for any of the 3 families), STOP and adjust the Step-3 `isGateWrapper` selector + Step-4 CSS to match the actual DOM before proceeding — the selectors below assume the direct-child DOM the tab-panel case uses. Record the actual DOM in the task report.

- [ ] **Step 2: Write the failing tests**

(a) Pre-hide CSS presence — a render test asserting the lesson `<style>` contains the spoiler pre-hide selector when the unit has a reveal-family gate:
```python
@pytest.mark.django_db
def test_lesson_prehide_css_covers_spoiler(client, unit_with_gates_in_spoiler):
    html = client.get(unit_with_gates_in_spoiler.get_absolute_url()).content.decode()
    assert ".spoiler > .spoiler__child:has(> [data-reveal-gate])" in html
```
(b) e2e (Playwright) in the reveal e2e module, mirroring the existing reveal-gate e2e: a lesson with a top-level spoiler containing `[reveal_gate][text A][text B]` and a text element AFTER the spoiler. Open the spoiler, assert text A/B are hidden; click the gate; assert text A (and B, up to any next gate) become visible WITHIN the spoiler, and the text AFTER the spoiler stays unaffected; reload and assert the revealed state is restored (`restoreGates`).

- [ ] **Step 3: Run to verify RED**

Run the DOM/CSS tests + e2e:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest -k "spoiler and (prehide or gate_child)" -v
# e2e (foreground; match the project's e2e invocation):
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/test_e2e_reveal_gate.py -k spoiler -v
```
Expected: pre-hide-CSS test FAILS (selector absent); e2e FAILS (cascade reveals wrong content / leaks).

- [ ] **Step 4: Add `.spoiler` to `scopeOf` and refactor `isGateWrapper` (reveal.js)**

`courses/static/courses/js/reveal.js` — `scopeOf` (l.43-45):
```javascript
  function scopeOf(btn) {
    return btn.closest("[data-tab-panel], .slide, .spoiler");
  }
```
`isGateWrapper` (l.60-66) — invert the selector choice so the direct-child form serves BOTH tab-panel and spoiler, and only `.slide` uses the lesson-block form:
```javascript
  function isGateWrapper(wrapper, scope) {
    if (!wrapper) return false;
    var sel = scope.matches(".slide")
      ? ":scope > .lesson-block__body > [data-reveal-gate]"
      : ":scope > [data-reveal-gate]";
    return !!wrapper.querySelector(sel);
  }
```
(Update the comment at l.56-59 to note the three scopes and that spoiler + tab-panel share the direct-child selector.)

- [ ] **Step 5: Add the spoiler pre-hide CSS (lesson_unit.html)**

`templates/courses/lesson_unit.html` — extend the `has_reveal_gate` `<style>` (l.38-43) with a third selector mirroring the tab-panel rule:
```html
  <style>
    .reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block:not(.reveal-shown),
    .reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child:not(.reveal-shown),
    .reveal-armed .spoiler > .spoiler__child:has(> [data-reveal-gate]) ~ .spoiler__child:not(.reveal-shown) {
      display: none;
    }
  </style>
```

- [ ] **Step 6: Run to verify GREEN**

Re-run Step-3 commands. Expected: PASS (pre-hide CSS present; e2e cascade reveals within-spoiler, no leak, restore works).

- [ ] **Step 7: Regression — existing reveal e2e/tests (slide + tab-panel cascade) unchanged**

Run the full reveal e2e + any reveal.js-related unit tests foreground:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest tests/test_e2e_reveal_gate.py -v
```
Expected: PASS (slide and tab-panel cascades behave exactly as before — the selector inversion is behaviour-preserving for both: slide→lesson-block, tab-panel→direct).

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/reveal.js templates/courses/lesson_unit.html courses/tests/test_reveal_gate_render.py tests/test_e2e_reveal_gate.py
git commit -m "feat(reveal): scope the reveal cascade to a spoiler body (interactive-in-spoiler)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DAtycPcTv4NLRZctpoTA1u"
```

---

## Task 4: Editor add-menu authoring in a spoiler

Show the 4 gate cards + a `fillblankquestion` card in a spoiler's add-menu; guard the 5 non-allowed Interactive cards so they don't render a card whose POST would 400.

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html:27,34-38,48`
- Test: `courses/tests/test_spoiler_nesting.py` (add-menu tests — see the existing `test_spoiler_add_menu_hides_disallowed_cards` ~l.226).

**Interfaces:**
- Consumes: `resolve_scope` accepting the 4 gates + `fillblankquestion` (Task 1).
- Produces: the in-spoiler add-menu offers the 4 gate cards + fillblank; authoring a `switchgate` into a spoiler via `manage_element_save` succeeds.

- [ ] **Step 1: Write the failing tests**

Extend `courses/tests/test_spoiler_nesting.py`:
```python
@pytest.mark.django_db
def test_spoiler_add_menu_shows_allowed_interactive_cards(client_pa, top_level_spoiler_unit):
    html = client_pa.get(<editor url for top_level_spoiler_unit>).content.decode()
    # the in-spoiler add-menu (addwrap--nested under the spoiler) shows exactly these:
    for t in ("revealgate", "fillgate", "switchgate", "switchgrid", "fillblankquestion"):
        assert f'data-add-type="{t}"' in html
    # and NOT the non-allowed interactive/structure cards (C1 guard):
    for t in ("filltable", "spoiler", "stepper", "markdone", "guessnumber"):
        # assert absent within the spoiler's add-menu specifically (scope the assertion
        # to the spoiler addwrap, since a top-level add-menu on the same page DOES show them)
        ...
    # no other question card leaks in-spoiler:
    for t in ("choice-single", "shorttextquestion", "dragfillblankquestion"):
        ... # absent in the spoiler addwrap


@pytest.mark.django_db
def test_author_switchgate_into_spoiler_succeeds(client_pa, top_level_spoiler_join):
    # POST manage_element_save with parent=<spoiler join pk>, tab=SLOT_ID, type=switchgate
    resp = client_pa.post(<manage_element_save url>, data={...})
    assert resp.status_code == 200
    # a SwitchGateElement child now exists under the spoiler join


@pytest.mark.django_db
def test_tabs_add_menu_unaffected(client_pa, unit_with_tabs):
    # PR#126 no-regression: the tab nested add-menu still shows the 4 gates and hides questions
    ...
```
Scope the "absent" assertions to the spoiler's own `addwrap--nested` block (parse with BeautifulSoup and select the addwrap whose `data-parent` is the spoiler join pk), because the page's TOP-LEVEL add-menu legitimately shows filltable/stepper/etc. Update the existing `test_spoiler_add_menu_hides_disallowed_cards` to reflect the new allowed set (gates + fillblank now shown; only filltable/spoiler/stepper/markdone/guessnumber + non-fillblank questions hidden).

- [ ] **Step 2: Run to verify RED**

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest courses/tests/test_spoiler_nesting.py -k "add_menu or author_switchgate" -v
```
Expected: FAIL — the Interactive group is hidden in-spoiler; `fillblankquestion` hidden; the switchgate POST is currently rejected (before Task 1 it 400'd; after Task 1 the server accepts, but the card isn't offered until this task).

- [ ] **Step 3: Edit `_add_menu.html`**

(a) Interactive group guard (l.27): drop the `in_spoiler` clause:
```html
    {% if not unit_is_quiz %}
```
(b) Per-card guards on the 5 non-allowed cards (l.34-38): wrap each in `{% if not in_spoiler %}`:
```html
      {% if not in_spoiler %}<button type="button" class="typecard" data-add-type="filltable"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-filltable"/></svg>{% trans "Fill-in table" %}</button>{% endif %}
      {% if not in_spoiler %}<button type="button" class="typecard" data-add-type="spoiler"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-spoiler"/></svg>{% trans "Spoiler" %}</button>{% endif %}
      {% if not in_spoiler %}<button type="button" class="typecard" data-add-type="stepper"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-stepper"/></svg>{% trans "Step-by-step" %}</button>{% endif %}
      {% if not in_spoiler %}<button type="button" class="typecard" data-add-type="markdone"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-markdone"/></svg>{% trans "Checklist" %}</button>{% endif %}
      {% if not in_spoiler %}<button type="button" class="typecard" data-add-type="guessnumber"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-guessnumber"/></svg>{% trans "Guess the number" %}</button>{% endif %}
```
(c) A `fillblankquestion` card for the spoiler case — add INSIDE the Interactive group's `<div class="typemenu__group">` (before its closing `</div>` at l.39), in its own `{% if in_spoiler %}` block (it must NOT go in the `{% if not nested %}` Questions group):
```html
      {% if in_spoiler %}<button type="button" class="typecard" data-add-type="fillblankquestion"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-fillblank"/></svg>{% trans "Fill in the blanks" %}</button>{% endif %}
```
This renders in a spoiler (`in_spoiler=True`); in a tab (`nested=True, in_spoiler=False`) it's hidden, matching the existing tab behaviour (fillblank not offered in tabs). The Questions-group `fillblankquestion` at l.48 stays (`{% if not nested %}` — top level only), so no top-level duplication.

- [ ] **Step 4: Run to verify GREEN**

Re-run Step-2. Expected: PASS. Also confirm the top-level add-menu still shows all cards (a top-level add test), and the tabs add-menu is unaffected.

- [ ] **Step 5: i18n — the fillblank card string already exists**

`"Fill in the blanks"` is already a translated string (l.48), so no new msgid. Run the i18n catalog check if the project has one:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest -k i18n -q
```
Expected: PASS (no new/obsolete msgids).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check courses/tests/test_spoiler_nesting.py
git add templates/courses/manage/editor/_add_menu.html courses/tests/test_spoiler_nesting.py
git commit -m "feat(editor): author interactive elements inside a spoiler (add-menu)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DAtycPcTv4NLRZctpoTA1u"
```

---

## Task 5: Integration verification (live corpus)

Not a unit task — confirms the feature end-to-end against the blocked corpus parts.

- [ ] **Step 1: Reseed + reload the two previously-blocked parts**

```bash
SR="C:/Users/krzys/Documents/teaching/LAL/html"
uv run python -m scripts.lal_import.parser 100_geometria_2 --source-root "$SR" --force
uv run python -m scripts.lal_import.parser 104_geometria_3_czworokaty --source-root "$SR" --force
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run python manage.py import_lal_content --course matematyka --part 100_geometria_2 --source-root "$SR" --json-dir scripts/lal_import/out --allow-html
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run python manage.py import_lal_content --course matematyka --part 104_geometria_3_czworokaty --source-root "$SR" --json-dir scripts/lal_import/out --allow-html
```
Expected: both load WITHOUT the "non-leaf child (switch_gate) nested inside a spoiler" `LoaderError` (previously aborted). (Part 050 remains blocked by the unrelated pre-existing missing-video `kwadratowa_wzor.mp4` — note, don't fix here.)

- [ ] **Step 2: Live render a "rozwiązanie" unit + author check**

Start the DEBUG server (`.env` supplies DEBUG + libli_mat + media):
```bash
uv run python manage.py runserver 127.0.0.1:8000
```
Log in `pilot` / `pilot-pass-123`. Open a 100/104 unit with a switch-in-details "rozwiązanie" spoiler: toggle it open, step through the switch cyclers + confirm — each confirm reveals the next step WITHIN the spoiler (not content after it); reload and confirm revealed steps restore. Then in the editor, add a "Choose & confirm" (switchgate) inside a top-level spoiler, save, and confirm it renders and works in the lesson view.

- [ ] **Step 3: Hand the user the URLs + a one-line summary of what each demonstrates.**
