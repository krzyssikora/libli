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
- Tests: `courses/tests/test_spoiler_nesting.py` (resolve_scope + add-menu), `courses/tests/test_spoiler_transfer.py` (round-trip), the LAL loader tests (`tests/test_lal_loader_units.py`), a views/`build_lesson_context` test module, and the reveal e2e test module.

---

## Task 1: Widen the spoiler-child allowlist (model/loader/editor-scope/transfer)

**Files:**
- Modify: `courses/builder.py:34,60,65,118`
- Modify: `courses/lal_loader/builders.py` (add `_PARSER_TO_CANONICAL`; l.83 check)
- Test: `courses/tests/test_spoiler_nesting.py`, `courses/tests/test_spoiler_transfer.py`, `tests/test_lal_loader_units.py`

**Interfaces:**
- Consumes: existing `_attach`, `build_element`, `resolve_scope`, `validate_nesting`.
- Produces: `SPOILER_CHILD_TYPES` now includes the 5 canonical interactive keys; `resolve_scope(unit, spoiler_join_pk, SLOT_ID, form_key)` returns `(join, SLOT_ID)` for the 5 interactive form keys; the LAL loader accepts these as spoiler children. Task 3/4 rely on being able to CREATE a spoiler-nested gate (via loader or editor).

- [ ] **Step 1: Write the failing tests**

Add to `courses/tests/test_spoiler_nesting.py`, reusing that file's existing helpers `make_course_with_unit()` and `_spoiler_join(unit, parent=None, tab_id="")` (l.103-107, returns `(sp, join)`) and `NestingError` imported from `courses.builder` (NOT `courses.exceptions`):

`test_spoiler_nesting.py` already imports `pytest` and `SpoilerElement` at module scope — add ONLY the genuinely new imports (`from courses.builder import SPOILER_CHILD_TYPES, NESTABLE_TYPE_KEYS, NestingError` and `from courses import builder`; `make_course_with_unit`/`_spoiler_join` are already in the module).

```python
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

**Update the EXISTING loader rejection tests in `tests/test_lal_loader_units.py`:**
`test_build_spoiler_rejects_reveal_gate_child` (l.838) and
`test_build_spoiler_rejects_fillblank_child` (l.851) currently assert a
`reveal_gate`/`fillblank` spoiler child RAISES `LoaderError`. After Task 1 they no
longer raise — **invert both** to assert the child now loads under the spoiler join
(the new positive test below covers this; you may delete these two and rely on it, OR
retarget each to assert `parent=<join>, tab_id=SLOT_ID`). Keep
`test_build_spoiler_rejects_container_child` (l.770) unchanged — a container child
stays rejected.

Add a positive LAL-loader test in `tests/test_lal_loader_units.py`, building
`course`/`unit` inline via the file's existing convention (`CourseFactory` + `_unit()`,
or `make_course_with_unit()` — match the surrounding tests) and importing `SENTINEL`
the way the file's fillblank tests do (`from courses.fillblank import SENTINEL`), NOT a
pasted glyph. Query children via `spoiler.resolved_children()` (a `SpoilerElement`
method) or `spoiler.join_row().children.order_by("order", "pk")` — NOT
`join_row().resolved_children()` (`join_row()` returns an `Element`, which has
`.children`, not `resolved_children`):

```python
from courses.fillblank import SENTINEL  # if not already imported in the file

@pytest.mark.django_db
@pytest.mark.parametrize("child", [
    {"type": "reveal_gate", "label": "pokaż"},
    {"type": "switch_gate", "stem": "s", "options": ["a", "b"], "answer": 0},
    {"type": "fill_gate", "stem": "s", "answers": [["1"]]},
    {"type": "switch_grid", "prompt": "", "lines": [{"stem": "s", "cyclers": [{"options": ["a", "b"], "answer": 0}]}]},
    {"type": "fillblank", "stem": f"x = {SENTINEL}0{SENTINEL}", "blanks": [["0"]]},
])
def test_loader_accepts_interactive_spoiler_child(child):
    course, unit = make_course_with_unit()  # or CourseFactory()/_unit(course) per the file
    from courses.lal_loader.builders import build_element
    el = {"type": "spoiler", "label": "rozwiązanie", "elements": [child]}
    spoiler = build_element(course, unit, el, source_root="", source_dir="", allow_html=False)
    kids = spoiler.resolved_children()
    assert len(kids) == 1
```
(Confirm the real `build_element` signature in the file before running — match its exact keyword args.)

**Update the EXISTING transfer rejection test:**
`courses/tests/test_spoiler_transfer.py:97`
`test_validate_nesting_rejects_reveal_gate_spoiler_child` asserts `validate_nesting`
raises for a `reveal_gate` spoiler child. After widening it no longer raises —
**retarget it to a still-rejected container** (`tabs`), or delete it and rely on the
new round-trip test's "tabs-in-spoiler still rejected" assertion.

Add a transfer round-trip test in `courses/tests/test_spoiler_transfer.py` (follow
that file's export→import helpers): export a unit with a spoiler containing a
`switch_gate` child and a `fill_blank` child, import into a fresh course, assert both
survive as spoiler children with their data; and assert `validate_nesting` still
rejects a `tabs`-in-spoiler archive.

- [ ] **Step 2: Run the tests to verify they fail (RED)**

Run:
```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run pytest courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py tests/test_lal_loader_units.py -k "interactive or fill_blank or nestable_type_keys or spoiler_child_types or container" -v
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
  uv run pytest courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py tests/test_lal_loader_units.py courses/tests/test_callout_transfer.py courses/tests/test_fillgate_transfer.py -q
```
Expected: PASS (the `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)` invariant test still holds — `fill_blank` ∈ `SERIALIZERS`).

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check courses/builder.py courses/lal_loader/builders.py courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py tests/test_lal_loader_units.py
uv run ruff format --check courses/builder.py courses/lal_loader/builders.py courses/tests/
git add courses/builder.py courses/lal_loader/builders.py courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_transfer.py tests/test_lal_loader_units.py
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

No `unit_with_fillblank_in_spoiler`/`some_user`/`unit_text_only` fixtures exist — build
state INLINE using `test_spoiler_context.py`'s existing helpers (`lesson_unit_node`,
`student_user`) and construct the nested fillblank via the Task-1 loader `build_element`
(a `{"type":"spoiler","elements":[{"type":"fillblank",…}]}` dict) or directly via ORM
(`FillBlankQuestionElement.objects.create(...)` + `Element.objects.create(unit=…,
content_object=…, parent=<spoiler join>, tab_id=SpoilerElement.SLOT_ID)`). Follow how
`test_switchgate_context.py`/`test_fillgate_context.py` build a unit + call
`build_lesson_context` and assert the `has_*` key. Sketch:

```python
@pytest.mark.django_db
def test_has_questions_true_for_spoiler_nested_fillblank():
    # a unit whose ONLY question is a FillBlankQuestionElement nested as a spoiler child
    unit = <build via loader/ORM per above>
    user = <student_user per the file's helper>
    from courses.views import build_lesson_context
    assert build_lesson_context(unit, user)["has_questions"] is True


@pytest.mark.django_db
def test_has_questions_false_when_no_questions():
    unit = <a unit with only a TextElement>
    user = <student_user>
    from courses.views import build_lesson_context
    assert build_lesson_context(unit, user)["has_questions"] is False
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

Write a Django render test in `courses/tests/test_reveal_gate_render.py` that builds a
top-level spoiler with a `reveal_gate`, a `switch_gate`, and a `fill_gate` child (via
the Task-1 loader or ORM), renders the lesson unit, and asserts each gate's
`[data-reveal-gate]` element is a DIRECT child of a `.spoiler__child` div. **Fetch the
page via that file's existing `lesson_url()` helper (l.32,
`reverse("courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})`)
— NOT `get_absolute_url()`, which `ContentNode` does not define.** Build the unit inline
(no `unit_with_gates_in_spoiler` fixture exists):

```python
@pytest.mark.django_db
def test_spoiler_gate_child_is_direct_child_of_spoiler_child(client):
    unit = <build a top-level spoiler with reveal_gate + switch_gate + fill_gate children>
    html = client.get(lesson_url(unit)).content.decode()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for wrap in soup.select(".spoiler .spoiler__child"):
        gate = wrap.find(attrs={"data-reveal-gate": True})
        if gate is not None:
            assert gate.parent is wrap, "gate must be a DIRECT child of .spoiler__child"
```
Run it. **If it fails** (a wrapper intervenes for any of the 3 families), STOP and adjust the Step-3 `isGateWrapper` selector + Step-4 CSS to match the actual DOM before proceeding — the selectors below assume the direct-child DOM the tab-panel case uses. Record the actual DOM in the task report.

- [ ] **Step 2: Write the failing tests**

(a) Pre-hide CSS presence — a render test asserting the lesson `<style>` contains the spoiler pre-hide selector when the unit has a reveal-family gate (same inline unit + `lesson_url(unit)`):
```python
@pytest.mark.django_db
def test_lesson_prehide_css_covers_spoiler(client):
    unit = <build a top-level spoiler with a reveal_gate child>
    html = client.get(lesson_url(unit)).content.decode()
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

Extend `courses/tests/test_spoiler_nesting.py`. **No `client_pa`/`top_level_spoiler_unit`/
`top_level_spoiler_join`/`unit_with_tabs` fixtures exist** — reuse this file's existing
editor-page pattern: the current `test_spoiler_add_menu_hides_disallowed_cards` (l.226)
and `test_top_level_spoiler_renders_child_list_and_add_menu` (l.216) already build a
PA-authenticated client (via `make_pa`), a course/unit (`CourseFactory`/`_lesson_unit`),
a top-level spoiler (`_nested_spoiler`/`_spoiler_join`), and GET the editor page. Copy
that setup; do NOT invent fixtures. For the authoring POST, use the same
`manage_element_save` URL + form the file's other save tests use (grep the file for the
editor-save reverse()).

```python
@pytest.mark.django_db
def test_spoiler_add_menu_shows_allowed_interactive_cards():
    # build PA client + top-level spoiler + GET editor page exactly as
    # test_spoiler_add_menu_hides_disallowed_cards does; parse with BeautifulSoup and
    # select the spoiler's OWN addwrap (the `data-add-menu` whose data-parent == the
    # spoiler join pk) — NOT the page's top-level add-menu, which legitimately shows all.
    addwrap = <the spoiler's addwrap--nested element>
    present = {b["data-add-type"] for b in addwrap.select("[data-add-type]")}
    assert {"revealgate", "fillgate", "switchgate", "switchgrid", "fillblankquestion"} <= present
    # C1 guard — the 5 non-allowed interactive/structure cards are ABSENT in-spoiler:
    assert present.isdisjoint({"filltable", "spoiler", "stepper", "markdone", "guessnumber"})
    # no other question card leaks in-spoiler:
    assert present.isdisjoint({"choice-single", "shorttextquestion", "dragfillblankquestion"})


@pytest.mark.django_db
def test_author_switchgate_into_spoiler_succeeds():
    # POST the editor save (same reverse()/form the file's other save tests use) with
    # parent=<spoiler join pk>, tab=SpoilerElement.SLOT_ID, type=switchgate.
    resp = <client>.post(<editor-save url>, data=<switchgate add payload>)
    assert resp.status_code == 200
    # a SwitchGateElement child now exists under the spoiler join (query Element by parent)


@pytest.mark.django_db
def test_tabs_add_menu_unaffected():
    # PR#126 no-regression: the tab nested add-menu still shows the 4 gates and hides
    # questions — reuse the existing tabs add-menu test's setup (grep for it).
    ...
```
Update the existing `test_spoiler_add_menu_hides_disallowed_cards` (l.226) to reflect the new allowed set: gates + `fillblankquestion` are now SHOWN in-spoiler; only `filltable`/`spoiler`/`stepper`/`markdone`/`guessnumber` + the non-fillblank question cards stay hidden.

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
