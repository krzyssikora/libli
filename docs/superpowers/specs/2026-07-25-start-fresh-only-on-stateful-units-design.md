# Show "Start fresh" only on units that can hold practice state

## Purpose

`templates/courses/_lesson_article.html:24-27` renders the **Start fresh** link unconditionally on
every lesson unit page. On a unit that holds nothing resettable — a video, an image, a block of
text — the link is not merely noise: it is a **guaranteed no-op**.

Three facts establish that:

1. `progress_reset` (`courses/views.py:552-560`) performs exactly one mutation,
   `rows.update(element_state={})`. It never touches `UnitProgress.completed`; the confirmation page
   states this explicitly ("lessons you have completed stay completed"). So the one piece of state a
   video-only unit *can* carry — the **Mark as done** tick — is deliberately out of scope for reset.
2. Therefore a unit with no state-bearing element has nothing reset can clear, ever, for any student.
3. The current design already knows this — `progress_reset_confirm.html:24` dead-ends with "Nothing to
   clear here." — but only **after** a click and a full page load.

This change moves that knowledge to the point of render: the affordance is offered only where it can
do something.

### Decisions taken (and the alternatives rejected)

**D1 — Gate on capability, not on stored state.** Show the link iff the unit *contains an element type
that can persist practice state*, not iff *this student currently has a stored blob for this unit*.

The state-based rule was considered and is in some ways stronger: `element_state` is already in the
lesson context (`courses/views.py:421`), so it costs zero queries and cannot drift. It was rejected on
UX grounds: it makes the control **flicker between page loads**. Practice state is written by
fire-and-forget JS, so a student who opens a reveal gate and immediately wants to undo it would find no
button until the next reload, and the button would vanish again the moment they reset. A stable,
predictable control beats a marginally more precise one.

**D2 — Unit page only.** The per-container link (`_outline_node.html:24`) and the course-level link
(`outline.html:11`) stay unconditional. Rationale in §Non-goals; this is load-bearing, not laziness.

**D3 — The type set is derived from existing registries, never hand-listed.** See §Architecture.

## Architecture / components

Three changes, in dependency order.

### C1. `courses/state.py` — `stateful_element_models()`

Practice state reaches storage by **two independent routes**, so the set of state-bearing element
types is a union of two existing registries:

| Route | Registry | Types today |
|---|---|---|
| Self-checks and gates | `state.py::VALIDATORS` (keyed by `content_type.model`) | 8: `markdoneelement`, `revealgateelement`, `fillgateelement`, `switchgateelement`, `switchgridelement`, `filltableelement`, `guessnumberelement`, `stepperelement` |
| Lesson-mode question answers | `QuestionElement.RESTORABLE_IN_LESSON` class attr, consulted in `views.py:797` on save and in `render_element` on restore | 10: every question type in `ELEMENT_MODELS` |

The two sets are disjoint; the union is **18** of the 31 entries in `ELEMENT_MODELS`.

```python
@functools.cache
def stateful_element_models():
    """content_type.model names of every element type that can persist practice state:
    the validator registry UNION the question types that opt into RESTORABLE_IN_LESSON.

    DERIVED, never hand-listed. A literal list here would be a fourth namespace beside
    the three VALIDATORS' own comment warns about, and it would drift silently: a new
    state-bearing type would keep its state but lose its reset affordance.
    """
    from django.apps import apps          # lazy: keeps this module import-time model-free
    from courses.models import ELEMENT_MODELS

    return frozenset(VALIDATORS) | {
        name
        for name in ELEMENT_MODELS
        if getattr(apps.get_model("courses", name), "RESTORABLE_IN_LESSON", False)
    }
```

**Placement.** `state.py` is the state domain and already owns half the union. Its docstring calls it
"a pure module (no views, no writes)"; the real invariant that protects is *no model imports at import
time*, which a function-local import preserves. `@functools.cache` is safe: model classes are fixed
per process, and the app registry is guaranteed populated by the time a view calls this.

**Rejected alternative — the free OR-chain.** `build_lesson_context` already computes nine `has_*`
flags which, today, happen to cover all 18 types (`has_questions` covers all ten question types;
the other eight flags cover the eight validator types). OR-ing them would cost zero extra queries.
Rejected: that coverage is **true only by coincidence** — it silently assumes every question type is
restorable in lessons, so the first question type shipped with `RESTORABLE_IN_LESSON = False` would
make the chain over-report and reintroduce exactly the no-op button this spec removes. It is also
precisely the hand-maintained OR-chain that the `_element_has_math` centralization deleted
(`views.py:336-337`). One indexed `.exists()` beside the nine already there is the cheaper mistake.

### C2. `courses/views.py::build_lesson_context` — `has_resettable_state`

```python
has_resettable_state = node.elements.filter(
    content_type__model__in=state_svc.stateful_element_models()
).exists()
```

Added to the returned context dict beside the existing `has_*` flags. `state_svc` is already imported
(`views.py:27`).

**The query is flat** — over `node.elements`, *not* scoped to `parent__isnull=True`. Children of a
Tabs/TwoColumn join row keep their own `unit` FK, so a gate or question nested inside a tab, spoiler,
or column is still found. This mirrors `has_questions` and `has_reveal_gate` and the comments that
justify them (`views.py:340-348`). Scoping to top level would hide the button on a unit whose only
interactive content lives inside a tab — a live, reachable bug, since Spoiler/Switch grid/Fill-in
table are all nestable.

### C3. `templates/courses/_lesson_article.html` — the condition

Wrap the existing anchor (lines 24-27) in `{% if has_resettable_state %}`. No other markup changes.

**No CSS change is required.** `.lesson-unit__head` is `display: flex; align-items: flex-start;
justify-content: space-between` with the title at `flex: 1; min-width: 0` and the pill at `flex: none`
(`courses/static/courses/css/courses.css:670-678`); `.lesson-unit__reset` is `flex: none`
(`core/static/core/css/app.css:547`). Dropping the third flex child leaves title + pill correctly
placed, and the `max-width: 640px` rule (`courses.css:827-828`) that gives the title its own row
behaves identically with two children.

## Data flow

```
lesson_unit GET  ->  build_lesson_context(node, user)
                       |
                       +-- stateful_element_models()   (cached; no DB)
                       |     VALIDATORS keys  U  {ELEMENT_MODELS entries with RESTORABLE_IN_LESSON}
                       |
                       +-- node.elements.filter(content_type__model__in=<that set>).exists()
                             (one indexed query, flat over the unit incl. nested children)
                       |
                       v
                  ctx["has_resettable_state"]
                       |
                       v
       _lesson_article.html  {% if has_resettable_state %} ... Start fresh ... {% endif %}
```

`check_answer`'s POST re-render goes through the same `build_lesson_context`, so the two render paths
cannot drift — which is the stated reason that function exists (`views.py:272-274`).

The flag is a property of the **unit's content**, identical for every student and independent of
enrollment, so it is unaffected by the enrolled / non-enrolled (author-preview) split at
`views.py:375-385`.

## Error handling

- **Unknown name in `ELEMENT_MODELS`.** `apps.get_model` raises `LookupError`. This is deliberately
  **not** caught: `ELEMENT_MODELS` is the canonical element-type list, already asserted against
  `ELEMENT_MODELS`-derived counts elsewhere in the suite, and a name in it that resolves to no model is
  a broken deployment that should fail loudly at first lesson render, not silently drop a type from the
  set and hide reset buttons.
- **`getattr(..., "RESTORABLE_IN_LESSON", False)`** defaults to `False`, so non-question element types
  (which never define the attr) are correctly excluded without a type check.
- **Fail direction.** Every failure mode of this feature is *hiding a usable button*, never *breaking a
  page* — the flag only ever gates an anchor. There is no fail-open/fail-closed tradeoff to make and no
  try/except is warranted anywhere in this change.
- **Orphaned blobs stay reachable.** If an author deletes the last state-bearing element from a unit, a
  student's stored blob for it becomes unreachable *from that unit page*. It remains clearable via the
  outline's container-level and course-level resets, which D2 keeps unconditional — this is the
  concrete reason D2 is load-bearing.

## Non-goals

- **The outline and course-level reset links are not gated.** Hiding those correctly requires a
  subtree roll-up ("does any unit under this node hold a state-bearing element"), which means an extra
  query plus a walk in `build_outline` on a hot page — real cost for a case that barely occurs, since a
  container almost always has *some* interactive unit beneath it. `progress_reset`'s "Nothing to clear
  here." remains the backstop there, and (per §Error handling) those links are the escape hatch for
  orphaned blobs.
- **`progress_reset` itself is unchanged.** Both routes, the confirmation interstitial, the
  `affected_count` computation, and the "Nothing to clear here." branch all stay exactly as they are.
- **Quiz units are unaffected** — `_lesson_article.html` renders only for lessons.
- **No migration, no new or changed translatable strings, no CSS change.**

## Testing

Every guard below must be **falsified**, not merely run green: delete the guard, observe RED, restore.
This codebase has shipped vacuous tests repeatedly (see the practice-state build's four cases), and the
specific hazard here is a test that passes because of the *fixture*, not the condition.

### Unit tests — `courses/tests/test_reset_controls.py`

1. **`test_lesson_page_links_to_the_reset_interstitial` will go RED as written.** It currently seeds a
   bare `make_course_with_unit()` with **no elements at all** (`test_reset_controls.py:19-20`), which is
   precisely the case this spec hides. Update it to seed a state-bearing element (e.g. a
   `MarkDoneElement` via `add_element`, the pattern already used at `test_reset_controls.py:71-78`).
   Its RED-ness on the unmodified test is the first falsification signal of the whole change.
2. **New: a unit with only non-state elements renders no reset link.** Seed a `TextElement` (or
   `VideoElement`) and assert the `courses:progress_reset` URL for that unit is absent from the body.
   Falsify by deleting the `{% if %}`.
3. **New: a nested state-bearing element still shows the link.** Put a gate or question inside a
   `TabsElement` (child join row, `parent` set) and assert the link is present. Falsify by scoping the
   `build_lesson_context` query to `parent__isnull=True` — this test exists specifically to pin C2's
   flat-query decision, and it is the only test that can.
4. **New: the derived set is correct.** Assert `stateful_element_models()` is a superset of
   `set(VALIDATORS)`; assert it contains every `ELEMENT_MODELS` entry whose model has
   `RESTORABLE_IN_LESSON` truthy; assert it excludes a known-inert type (`textelement`,
   `videoelement`); and pin `len(...) == 18` so adding a state-bearing type trips a deliberate review
   step. This mirrors the existing `ELEMENT_MODELS` count assert in `tests/test_transfer_schema.py`.

**Falsifiability note.** Tests 2 and 3 are the only ones that can fail from the production condition
being wrong; test 1 fails from the fixture and test 4 from the derivation. State the falsification
result for each in the task's completion report — not "passes", but "went RED when X was removed".

### e2e — `tests/test_e2e_unit_head_layout.py`

`_seed` (line 42) creates a unit with a single `TextElement`, so under this change the reset link
**disappears from that page**. The two tests measure only `.lesson-unit__title` and `.unit-done`, so
they will still pass — silently, while no longer guarding the three-item row they exist for (the module
docstring names "Mark done / Start fresh" explicitly). Add a state-bearing element to `_seed` so the
crowded worst case is still what gets measured. Verify by asserting the link is present in that seeded
page before measuring.

### Definition of done

- Full non-e2e suite green (`uv run pytest -n auto`), against the worktree's own `libli_freshbtn`
  database.
- `tests/test_e2e_unit_head_layout.py` green, run in the **foreground** (background `-m e2e` runs have
  spawned runaway browsers here before).
- `uv run ruff check`, `uv run ruff format --check`, `uv run python manage.py makemigrations --check`,
  and `uv run python manage.py check` all clean.
- Every falsifiable guard above reported with its observed RED.
