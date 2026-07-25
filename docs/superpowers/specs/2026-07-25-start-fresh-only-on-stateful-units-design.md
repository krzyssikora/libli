# Show "Start fresh" only on units that can hold practice state

## Purpose

`templates/courses/_lesson_article.html:24-27` renders the **Start fresh** link unconditionally on
every lesson unit page. On a unit that holds nothing resettable — a video, an image, a block of
text — the link does nothing.

Three facts establish that:

1. `progress_reset` (`courses/views.py:552-560`) performs exactly one mutation,
   `rows.update(element_state={})`. Reset is scoped to `element_state` **alone**: it leaves
   `UnitProgress.completed`, `completed_at`, `seen_element_ids` and `updated_at` untouched, as the
   view's own comment (`views.py:551-556`) and the confirmation page ("lessons you have completed stay
   completed") both state. So the state a video-only unit *can* carry — the head pill's
   `UnitProgress.completed` flag, and its seen-element tracking — is deliberately out of reset's scope.
   **Do not confuse the head pill with `MarkDoneElement`.** The pill's button label is "Mark as done"
   (`_lesson_article.html:20`) and it writes `UnitProgress.completed`, which reset never clears;
   `MarkDoneElement` is a separate lesson element whose item ticks live in `element_state` and **are**
   cleared by reset (the confirm page's "clears your answers and ticks" refers to the latter).
2. A unit that has **never held** a state-bearing element therefore has nothing reset can clear, for
   any student. The bounded phrasing is deliberate — see fact 3.
3. The current design already knows this — `progress_reset_confirm.html:24` dead-ends with "Nothing to
   clear here." — but only **after** a click and a full page load.

This change moves that knowledge to the point of render: the link is offered only where it *could* do
something for some student.

**The accepted cost, stated up front.** Because the gate is on the unit's current content (D1), it
hides the link in one case where reset would still be functional: an author deletes the last
state-bearing element from a unit after a student has stored a blob for it, leaving an **orphaned
blob** that the unit page will no longer offer to clear. This is knowingly accepted; §Error handling
names the surviving routes and their limits.

### Decisions taken (and the alternatives rejected)

**D1 — Gate on capability, not on stored state.** Show the link iff the unit *contains an element type
that can persist practice state*, not iff *this student currently has a stored blob for this unit*.

The state-based rule was considered and is in some ways stronger: `element_state` is already in the
lesson context (`courses/views.py:421`), so it costs zero queries, cannot drift, and would also cover
the orphaned-blob case above. It was rejected on UX grounds: it makes the control **flicker between
page loads**. Practice state is written by fire-and-forget JS, so a student who opens a reveal gate and
immediately wants to undo it would find no button until the next reload, and the button would vanish
again the moment they reset. A stable, predictable control beats a marginally more precise one.

**The residual is accepted, not eliminated.** D1 removes the *always*-no-op click (a text/video unit),
not every no-op click: on a unit full of gates and questions, a student who has touched none of them
still sees the link and still lands on "Nothing to clear here.". That residual is the price of a
control whose presence depends only on the lesson's content, and is the deliberate trade against the
flicker described above.

**D2 — Unit page only.** The per-container link (`_outline_node.html:24`) and the course-level link
(`outline.html:11`) stay unconditional. Rationale in §Non-goals; its known weak spot (flat courses) is
recorded in §Error handling.

**D3 — The type set is derived from existing registries, never hand-listed.** See §Architecture.

## Architecture / components

Three changes, in dependency order.

### C1. `courses/state.py` — `stateful_element_models()`

Practice state reaches storage by **two independent routes**, so the set of state-bearing element
types is a union of two existing registries:

| Route | Registry | Types today |
|---|---|---|
| Self-checks and gates | `courses.state.VALIDATORS` (keyed by `content_type.model`), consulted by `validate_state` from `element_state_save` | 8: `markdoneelement`, `revealgateelement`, `fillgateelement`, `switchgateelement`, `switchgridelement`, `filltableelement`, `guessnumberelement`, `stepperelement` |
| Lesson-mode question answers | `QuestionElement.RESTORABLE_IN_LESSON` class attr (base `False` at `models.py:1579`), consulted in `views.py:797` on save and in `render_element` on restore | 10: every question type in `ELEMENT_MODELS` |

The two sets are disjoint; the union is **18** of the 31 entries in `ELEMENT_MODELS`.

```python
def stateful_element_models():
    """content_type.model names of every element type that can persist practice state:
    the validator registry UNION the question types that opt into RESTORABLE_IN_LESSON.
    Returns a sorted tuple.

    DERIVED, never hand-listed. A literal list here would be a second hand-maintained
    copy of two registries that live elsewhere, in the same namespace they already use —
    and it would drift silently: a new state-bearing type would keep its state but lose
    its reset affordance.

    CONTRACT (see the note beside save_element_state): these two routes are the ONLY
    ways an element's practice state reaches UnitProgress.element_state. A third write
    route must extend this function in lockstep, or whatever it persists becomes
    unresettable from the unit page.
    """
    from django.apps import apps          # lazy: keeps this module import-time model-free
    from courses.models import ELEMENT_MODELS

    return tuple(sorted(
        set(VALIDATORS)
        | {
            name
            for name in ELEMENT_MODELS
            if getattr(apps.get_model("courses", name), "RESTORABLE_IN_LESSON", False)
        }
    ))
```

**Placement.** `state.py` is the state domain and already owns half the union. Its docstring calls it
"a pure module (no views, no writes)"; the real invariant that protects is *no model imports at import
time*, which a function-local import preserves.

**Not cached — deliberately.** An earlier draft wrapped this in `@functools.cache`. That is unsafe
here: `VALIDATORS` is a module-level mutable dict, and the suite already mutates it
(`courses/tests/test_state_module.py:74` uses `monkeypatch.setitem`). Today's patch only replaces an
existing key, so the key-set is unchanged — but a future `setitem` with a new key, or a `delitem`,
would be invisible behind a cache and produce order-dependent test results. The uncached cost is 31
`getattr`s over in-memory model classes, negligible beside the DB query it feeds. (This also removes
the need for a `functools` import; `state.py` currently imports only `logging`.)

**Sorted tuple, not a frozenset.** Set iteration order varies per process, which would reorder the
generated SQL parameter list run to run — harmless functionally, but it makes captured SQL diffs noisy
and defeats any future query-text assertion. A sorted tuple is also trivially printable in a failure
message.

**Rejected alternative — the free OR-chain.** `build_lesson_context` already computes nine `has_*`
flags which, today, happen to cover all 18 types (`has_questions` covers all ten question types;
the other eight flags cover the eight validator types). OR-ing them would cost zero extra queries.
Rejected: that coverage is **true only by coincidence** — it silently assumes every question type is
restorable in lessons, so the first question type shipped with `RESTORABLE_IN_LESSON = False` would
make the chain over-report and reintroduce exactly the no-op button this spec removes. It is also
precisely the hand-maintained OR-chain that the `_element_has_math` centralization deleted
(`views.py:336-337`). One `.exists()` beside the nine already there is the cheaper mistake.

### C2. `courses/views.py::build_lesson_context` — `has_stateful_elements`

```python
stateful_ct_ids = {
    ContentType.objects.get_for_model(apps.get_model("courses", name)).id
    for name in state_svc.stateful_element_models()
}
# Capability, NOT stored state: true iff this unit CONTAINS a state-bearing element
# type, regardless of whether this student has stored anything (spec D1).
has_stateful_elements = node.elements.filter(
    content_type_id__in=stateful_ct_ids
).exists()
```

Added to the returned context dict beside the existing `has_*` flags. `state_svc` is already imported
(`views.py:27`), as is `ContentType`.

**Name.** `has_stateful_elements`, not `has_resettable_state` — the latter reads as "this student has
state that can be reset", which is precisely the rule D1 rejected, and the next reader would inherit
the wrong semantics. The chosen name is capability-shaped, matching its neighbours (`has_questions`,
`has_stepper`).

**Content-type ids, not `content_type__model__in`.** Filtering on the joined
`django_content_type.model` matches a bare model name across **every installed app**. This mirrors
`has_questions` (`views.py:334`), which builds `question_ct_ids` from `ContentType.objects.get_for_model`
inline in exactly this way; `get_for_model` is in-process cached, so this adds no query in steady
state and is narrower than the looser form `has_reveal_gate` uses.

**The query is flat** — over `node.elements`, *not* scoped to `parent__isnull=True`. Children of a
Tabs, TwoColumn, or Spoiler join row keep their own `unit` FK (`models.py:299`; `SpoilerElement` is a
single-slot container, `SLOT_ID = "only"`, `models.py:397-405`), so a gate or question nested inside
any of those three containers is still found. This mirrors `has_questions` and `has_reveal_gate` and
the comments that justify them (`views.py:340-348`). Scoping to top level would hide the button on a
unit whose only interactive content lives inside a tab or spoiler — a live, reachable bug.

### C3. `templates/courses/_lesson_article.html` — the condition

Wrap the existing anchor (lines 24-27) in `{% if has_stateful_elements %}`. No other markup changes.

**No CSS change is required.** `.lesson-unit__head` is `display: flex; align-items: flex-start;
justify-content: space-between` with the title at `flex: 1; min-width: 0` and the pill at `flex: none`
(`courses/static/courses/css/courses.css:670-678`); `.lesson-unit__reset` is `flex: none`
(`core/static/core/css/app.css:547`). Dropping the third flex child leaves title + pill correctly
placed, and the `max-width: 640px` rule (`courses.css:827-828`) that gives the title its own row
behaves identically with two children. No JS references `.lesson-unit__reset`.

### C4. `courses/views.py::save_element_state` — a lockstep note

Add a short comment at `save_element_state` naming `state.stateful_element_models()` as the function
that must be extended whenever a new write route into `element_state` is introduced. This is the
cheap half of I7's invariant; the enforcing half is test 5 below.

## Data flow

```
lesson_unit GET  ->  full_lesson_render_context -> build_lesson_context(node, user)
                       |
                       +-- stateful_element_models()   (no DB, uncached, ~31 getattrs)
                       |     VALIDATORS keys  U  {ELEMENT_MODELS entries with RESTORABLE_IN_LESSON}
                       |
                       +-- ContentType.get_for_model(...) per name  (in-process cached)
                       |
                       +-- node.elements.filter(content_type_id__in=<those ids>).exists()
                             (flat over the unit, incl. tab/column/spoiler children)
                       |
                       v
                  ctx["has_stateful_elements"]
                       |
                       v
       _lesson_article.html  {% if has_stateful_elements %} ... Start fresh ... {% endif %}
```

**Three** sites render `courses/lesson_unit.html` — `views.py:593` (lesson GET), `views.py:837`
(`check_answer`'s POST re-render), and `notes/views.py:200` (the no-JS note-error 422 re-render). All
three funnel through `full_lesson_render_context` → `build_lesson_context`, so the flag reaches every
render path and they cannot drift; that single-sourcing is the stated reason those functions exist
(`views.py:272-274`, `views.py:431-435`).

The flag is a property of the **unit's content**, identical for every student and independent of
enrollment, so it is unaffected by the enrolled / non-enrolled (author-preview) split at
`views.py:375-385`.

## Error handling

- **Unknown name in `ELEMENT_MODELS`.** `apps.get_model` raises `LookupError`. This is deliberately
  **not** caught: `ELEMENT_MODELS` is the canonical element-type list, and a name in it that resolves
  to no model is a broken deployment that should fail loudly at first lesson render, not silently drop
  a type from the set and hide reset buttons.
- **`getattr(..., "RESTORABLE_IN_LESSON", False)`** defaults to `False`, so non-question element types
  (which never define the attr) are correctly excluded without a type check.
- **Fail direction.** Every failure mode of this feature is *hiding a usable link*, never *breaking a
  page* — the flag only ever gates an anchor. There is no fail-open/fail-closed tradeoff to make and no
  try/except is warranted anywhere in this change.
- **Orphaned blobs — the surviving routes, and where they run out.** Per §Purpose, an author deleting
  the last state-bearing element from a unit strands a student's stored blob, which the unit page will
  no longer offer to clear. What remains depends on the course's structure preset:
  - **Structured course** (parts/chapters/sections exist): the container-level reset
    (`_outline_node.html:24`) clears that subtree — precise enough.
  - **Flat course** (no grouping nodes at all): `_outline_node.html` renders its reset link only in the
    non-unit `{% else %}` branch (lines 19-26), so **no container-level reset exists**. The only
    surviving route is `outline.html:11`, which resets the **entire course**. The escape hatch
    degrades from "clear this subtree" to "clear everything".

  This degradation is accepted for now — an orphaned blob requires an author to delete the last
  interactive element from a unit a student has already worked, which is rare, and the student's own
  work elsewhere is what a whole-course reset would also take. If it proves unacceptable in practice,
  the fix is to gate the outline's **unit rows** rather than its containers, which reverses D2 and is
  explicitly out of scope here.

## Non-goals

- **The outline and course-level reset links are not gated.** Hiding those correctly requires a
  subtree roll-up ("does any unit under this node hold a state-bearing element"), which means an extra
  query plus a walk in `build_outline` on a hot page — real cost for a case that barely occurs, since a
  container almost always has *some* interactive unit beneath it. `progress_reset`'s "Nothing to clear
  here." remains the backstop there.
- **`progress_reset` itself is unchanged.** Both routes, the confirmation interstitial, the
  `affected_count` computation, and the "Nothing to clear here." branch all stay exactly as they are.
- **Quiz units are unaffected** — `_lesson_article.html` renders only for lessons.
- **No migration, no new or changed translatable strings, no CSS change.**

## Testing

Every guard below must be **falsified**, not merely run green: delete the guard, observe RED, restore.
This codebase has shipped vacuous tests repeatedly (see the practice-state build's four cases), and the
specific hazard here is a test that passes because of the *fixture*, not the condition.

**Namespace warning for every test below.** There are **two** symbols named `VALIDATORS`:
`courses.state.VALIDATORS` (content-type-model namespace — the one this spec means) and
`courses.transfer.payloads.VALIDATORS` (transfer-key namespace: `"callout"`, `"table"`,
`"mark_done"`…), which ~20 test modules already import by that bare name. Always import the former
qualified: `from courses import state` then `state.VALIDATORS`, never a bare `VALIDATORS`.

### `courses/tests/test_reset_controls.py`

1. **`test_lesson_page_links_to_the_reset_interstitial` will go RED as written.** It currently seeds a
   bare `make_course_with_unit()` with **no elements at all** (`test_reset_controls.py:19-20`), which is
   precisely the case this spec hides. Update it to seed a state-bearing element using the recipe
   already proven in that same file at lines 71-78 — `MarkDoneElement.objects.create(prompt="P")` then
   `add_element(unit, el)` (no `MarkDoneItem` rows are needed; the flag is type-based, not
   content-based). Its RED-ness on the unmodified test is the first falsification signal of the change.
2. **New: a unit with only non-state elements renders no reset link.** Seed a `TextElement` via
   `add_element` and assert the `courses:progress_reset` URL for that unit is absent from the body.
   Falsify by deleting the `{% if %}`.
3. **New: a nested state-bearing element still shows the link.** Follow the working pattern in
   `courses/tests/test_switchgrid_context.py:59-77` (`test_has_switch_grid_flag_when_nested_in_tab`),
   which is the same flat-query-under-a-tab guard for a sibling flag: create a `TabsElement` with
   `TabsElement.default_data()`, attach it via `Element.objects.create(unit=unit, content_object=tabs)`,
   read `tab_id = tabs.data["tabs"][0]["id"]`, then create the child with `parent=<tabs join row>,
   tab_id=tab_id`. Note that `tests/factories.py:162` `add_element(unit, obj)` creates **top-level rows
   only** — it takes no `parent`/`tab_id`, so the child row must be created directly. Assert the link is
   present. Falsify by scoping the `build_lesson_context` query to `parent__isnull=True` — this test
   exists specifically to pin C2's flat-query decision, and it is the only test that can.

### `courses/tests/test_state_module.py`

4. **The derived set is correct.** This tests `courses/state.py`, so it belongs here, not in
   `test_reset_controls.py` — this module is already where `state.VALIDATORS` is asserted key-by-key
   (lines 102, 129, 181). Assert `set(state.stateful_element_models())` equals an **explicitly
   hard-coded set of all 18 names** written out in the test:

   ```
   markdoneelement, revealgateelement, fillgateelement, switchgateelement,
   switchgridelement, filltableelement, guessnumberelement, stepperelement,
   choicequestionelement, shorttextquestionelement, extendedresponsequestionelement,
   shortnumericquestionelement, fillblankquestionelement, dragfillblankquestionelement,
   matchpairquestionelement, dragtoimagequestionelement, choicegridquestionelement,
   multigridquestionelement
   ```

   **Do not** assert it "contains every `ELEMENT_MODELS` entry whose model has `RESTORABLE_IN_LESSON`
   truthy" — that re-implements C1's production comprehension character for character, is green by
   construction, and can never go RED. Derive in production, **pin literally** in the test; that split
   is what makes drift trip, and it catches a name *swapped* for another, which a length assert alone
   would not. Also assert the return is sorted and that known-inert types (`textelement`,
   `videoelement`) are absent.
5. **The write-route invariant (I7).** Nothing else pins the "two independent routes" claim that C1
   rests on: test 4 catches a new state-bearing *type*, but not a new *write route*. Assert that
   `save_element_state` has exactly the two production call sites it has today
   (`views.py:772`/`775` via `validate_state`, and `views.py:801`/`803` via `RESTORABLE_IN_LESSON`) —
   a source-level count over `courses/views.py`, in the spirit of the existing
   `assert src.count("<guard>") == 2` guards in this suite. A third call site should force a
   deliberate decision about whether `stateful_element_models()` must grow. Keep the assertion message
   explicit about *why* it fired, so a future author reads the contract rather than bumping the number.

**Falsifiability note.** Tests 2 and 3 are the only ones that can fail from the production condition
being wrong; test 1 fails from the fixture, test 4 from the derivation, test 5 from the write surface.
State the falsification result for each in the task's completion report — not "passes", but "went RED
when X was removed".

### e2e — `tests/test_e2e_unit_head_layout.py`

`_seed` (line 42) creates a unit with a single `TextElement`, so under this change the reset link
**disappears from that page**. The two tests measure only `.lesson-unit__title` and `.unit-done`, so
they would still pass — silently, while no longer guarding the three-item row they exist for (the
module docstring names "Mark done / Start fresh" explicitly). Two changes:

- **Seed a state-bearing element** in `_seed`: `MarkDoneElement.objects.create(prompt="P")` attached
  with an `Element` row, the same minimal recipe as unit test 1. Chosen over a question element because
  it needs no child rows and no answer setup; `markdone.js`'s boot pass is read-only (it POSTs only on
  click), so it adds no network traffic to a layout test.
- **Extend `MEASURE`** (lines 63-77) to also return the `.lesson-unit__reset` rect, and assert it
  against `title_bottom` at both viewports exactly as `.unit-done` already is. Without this, restoring
  the third child leaves the row's widest action still unmeasured, and the module keeps failing to
  guard what its docstring claims. Assert the link is present before measuring, so a regression that
  re-hides it fails loudly here rather than silently reducing coverage.

### Definition of done

- Full non-e2e suite green (`uv run pytest -n auto`), against the worktree's own `libli_freshbtn`
  database.
- `tests/test_e2e_unit_head_layout.py` green, run in the **foreground** (background `-m e2e` runs have
  spawned runaway browsers here before).
- `uv run ruff check`, `uv run ruff format --check`, `uv run python manage.py makemigrations --check`,
  and `uv run python manage.py check` all clean.
- Every falsifiable guard above reported with its observed RED.
