# Show "Start fresh" only on units that can hold practice state

## Purpose

`templates/courses/_lesson_article.html:24-27` renders the **Start fresh** link unconditionally on
every lesson unit page. On a unit that holds nothing resettable — a video, an image, a block of
text — the link does nothing.

Three facts establish that:

1. `progress_reset` (`courses/views.py:507`) performs exactly one mutation,
   `rows.update(element_state={})` at `views.py:559`. Reset is scoped to `element_state` **alone**: it
   leaves `UnitProgress.completed`, `completed_at`, `seen_element_ids` and `updated_at` untouched, as
   the view's own comment (`views.py:552-558`) and the confirmation page ("lessons you have completed
   stay completed") both state. So the state a video-only unit *can* carry — the head pill's
   `UnitProgress.completed` flag, and its seen-element tracking — is deliberately out of reset's scope.
   **Do not confuse the head pill with `MarkDoneElement`.** The pill's button label is "Mark as done"
   (`_lesson_article.html:20`) and it writes `UnitProgress.completed`, which reset never clears;
   `MarkDoneElement` is a separate lesson element whose item ticks live in `element_state` and **are**
   cleared by reset (the confirm page's "clears your answers and ticks" refers to the latter).
2. A unit that has **never held** a state-bearing element therefore has nothing reset can clear, for
   any student. The bounded phrasing is deliberate — see the accepted cost below.
3. The current design already knows this — `progress_reset_confirm.html:24` dead-ends with "Nothing to
   clear here." — but only **after** a click and a full page load.

This change moves that knowledge to the point of render: the link is offered only where it *could* do
something for some student.

**The accepted cost, stated up front.** Because the gate is on the unit's current content (D1), it
hides the link in one case where reset would still be functional: an author deletes the last
state-bearing element from a unit after a student has stored a blob for it, leaving an **orphaned
blob** that the unit page will no longer offer to clear. This is knowingly accepted; §Error handling
names the surviving routes and their limits, and **test 7** pins the behaviour so a later author cannot
silently reverse the decision in either direction.

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

**Rejected alternative — the union rule (`has_stateful_elements or bool(element_state)`).** This is
the strictly stronger option and it deserves its own entry, because the flicker argument above does
**not** rule it out: on a capability-bearing unit the link would always show regardless of what JS
wrote, so nothing flickers; on a non-capability unit it would appear only when an orphaned blob exists
and vanish once cleared, which is correct rather than flickery. `element_state` is already in the
context (`views.py:421`), so the union costs zero extra queries and would delete the accepted cost above
and the flat-course degradation in §Error handling entirely.

It is nevertheless **not** adopted. The union was put to the decision-maker alongside the two pure
rules and capability-only was chosen deliberately, for a reason the union cannot offer: under
capability-only, the link's presence is a function of the lesson's *content alone* — the same for every
student, explainable in one sentence ("this lesson has interactive work in it"), and stable under any
sequence of student actions. The union makes presence depend on a per-student, JS-written blob in one
of its two branches, which is a harder rule to reason about and to test, in exchange for covering a
case (orphaned blobs) that requires an author to delete the last interactive element from a unit a
student has already worked. If that case turns out to matter in practice, the union is the first thing
to reach for and needs no new query to implement.

**D2 — Unit page only.** The per-container link (`_outline_node.html:24`) and the course-level link
(`outline.html:11`) stay unconditional. Rationale in §Non-goals; its known weak spot (flat courses) is
recorded in §Error handling.

**D3 — The type set is derived from existing registries, never hand-listed.** See §Architecture.

## Architecture / components

Four changes, in dependency order.

### C1. `courses/state.py` — `stateful_element_model_names()`

Practice state reaches storage by **two independent routes**, so the set of state-bearing element
types is a union of two existing registries:

| Route | Registry | Types today |
|---|---|---|
| Self-checks and gates | `courses.state.VALIDATORS` (keyed by `content_type.model`), consulted by `validate_state` from `element_state_save` | 8: `markdoneelement`, `revealgateelement`, `fillgateelement`, `switchgateelement`, `switchgridelement`, `filltableelement`, `guessnumberelement`, `stepperelement` |
| Lesson-mode question answers | `QuestionElement.RESTORABLE_IN_LESSON` class attr (base `False` at `models.py:1579`), consulted in `views.py:797` on save and in `render_element` on restore | 10: every question type in `ELEMENT_MODELS` |

The two sets are disjoint; the union is **18** of the 31 entries in `ELEMENT_MODELS`.

```python
def stateful_element_model_names():
    """content_type.model NAMES of every element type that can persist practice state:
    the validator registry UNION the question types that opt into RESTORABLE_IN_LESSON.
    Returns a sorted tuple of strings, fed straight to a content_type__model__in filter.

    DERIVED, never hand-listed. A literal list here would be a second hand-maintained
    copy of two registries that live elsewhere, in the same namespace they already use --
    and it would drift silently: a new state-bearing type would keep its state but lose
    its reset affordance.

    CONTRACT (restated at the UnitProgress.element_state field declaration, models.py:2340):
    these two routes are the only LIVE APPLICATION write routes into element_state --
    setting aside migration 0050's historical re-key and progress_reset's bulk clear,
    neither of which introduces a new state-bearing element type. A third such route must
    extend this function in lockstep, or whatever it persists becomes unresettable from
    the unit page.
    """
    from django.apps import apps          # lazy: keeps this module import-time model-free
    from courses.models import ELEMENT_MODELS

    known = set(ELEMENT_MODELS)
    return tuple(sorted(
        (set(VALIDATORS) & known)
        | {
            name
            for name in ELEMENT_MODELS
            if getattr(apps.get_model("courses", name), "RESTORABLE_IN_LESSON", False)
        }
    ))
```

**The `& known` intersection is load-bearing, not defensive noise.** Without it, a `VALIDATORS` key
that is not a real element model — a typo, or a type deleted from `ELEMENT_MODELS` without its
validator being unregistered — would flow into the `__in` filter and silently widen it, and any future
consumer that resolves these names to model classes would raise `LookupError`. Note precisely what the
intersection does and does not do: it does **not** protect the `apps.get_model` call, which only ever
sees `ELEMENT_MODELS` names (see §Error handling); it keeps the *returned tuple* honest. Today such a
typo is harmless: `validate_state` (`state.py:124`) just `.get()`s the registry and returns `REJECT`, so
one element silently fails to persist. **Test 8** re-raises the typo loudly in CI, and **test 9**
falsifies the intersection itself (test 8 alone cannot — the real registry is clean by construction, so
deleting `& known` leaves the whole suite green).

**Placement.** `state.py` is the state domain and already owns half the union. Its docstring calls it
"a pure module (no views, no writes)"; the real invariant that protects is *no model imports at import
time*, which a function-local import preserves. Put the function **immediately after `validate_state`**
so the module reads `VALIDATORS` (`state.py:110`) → `validate_state` → `stateful_element_model_names`
top-to-bottom, keeping the registry beside both of its consumers.

**Not cached — deliberately.** An earlier draft wrapped this in `@functools.cache`. That is unsafe
here: `VALIDATORS` is a module-level mutable dict, and the suite already mutates it
(`courses/tests/test_state_module.py:74` uses `monkeypatch.setitem`). Today's patch only replaces an
existing key, so the key-set is unchanged — but a future `setitem` with a new key, or a `delitem`,
would be invisible behind a cache and produce order-dependent test results. Tests 6 and 9 both
monkeypatch this surface, so a cache would actively break them. The uncached cost is 31
`apps.get_model` app-registry lookups plus 31 `getattr`s, no DB — negligible beside the query it feeds,
and stated in full here because it is the figure anyone revisiting the caching decision will weigh.
(Dropping the cache also removes the need for a `functools` import; `state.py` currently imports only
`logging`.)

**Sorted tuple, not a frozenset.** The names go directly into `content_type__model__in` (see C2), so
sorting here fixes the SQL parameter list's order end to end: identical query text run to run, captured
SQL diffs stay quiet, and a future query-text assertion stays possible. Set iteration order varies per
process and would deliver none of that. A sorted tuple is also trivially printable in a failure message.

**Rejected alternative — the free OR-chain.** `build_lesson_context` already computes nine
`.exists()`-backed `has_*` flags (plus `has_math` and `has_html`, which are computed in Python) which,
today, happen to cover all 18 types: `has_questions` covers all ten question types, and the other eight
`.exists()` flags cover the eight validator types. OR-ing them would cost zero extra queries. Rejected:
that coverage is **true only by coincidence** — it silently assumes every question type is restorable
in lessons, so the first question type shipped with `RESTORABLE_IN_LESSON = False` would make the chain
over-report and reintroduce exactly the no-op button this spec removes. It is also precisely the
hand-maintained OR-chain that the `_element_has_math` centralization deleted (`views.py:336-337`). One
`.exists()` beside the nine already there is the cheaper mistake.

### C2. `courses/views.py::build_lesson_context` — `has_stateful_elements`

```python
# Capability, NOT stored state: true iff this unit CONTAINS a state-bearing element
# type, regardless of whether this student has stored anything (spec D1).
has_stateful_elements = node.elements.filter(
    content_type__app_label="courses",
    content_type__model__in=state_svc.stateful_element_model_names(),
).exists()
```

**Insertion point, pinned:** immediately after `has_guess_number` (`views.py:367-369`), i.e. at the end
of the `has_*` block and **before** the `progress = None` / `state = {}` block that begins at
`views.py:371`. The flag is then added to the returned context dict beside its `has_*` neighbours.
`state_svc` is already imported (`views.py:27`). **No new import is required** — see below.

That ordering matters for one thing beyond tidiness: the `state` local does not exist yet at this point,
so any mutation that wants to consult stored state (test 7's falsification) must be applied at the
context-dict assembly, not here. Test 7 says so explicitly.

**Call it as `state_svc.stateful_element_model_names()`, through the module attribute.** This is
load-bearing for test 6, not just style: a `from courses.state import stateful_element_model_names` at
the top of `views.py` would bind the function object at import time, so test 6's
`monkeypatch.setattr("courses.state.stateful_element_model_names", …)` would never reach this call site
and the test would be permanently RED regardless of whether the seam is wired correctly.

**`app_label`-pinned join, not `get_for_model`-derived content-type ids.** Filtering on the joined
`django_content_type.model` alone would match a bare model name across every installed app; adding
`content_type__app_label="courses"` closes that completely, and is the established idiom in this
codebase — `Element.content_type` itself declares
`limit_choices_to={"app_label": "courses", "model__in": ELEMENT_MODELS}` (`models.py:323`).

An earlier draft instead built content-type ids via `ContentType.objects.get_for_model`, mirroring
`question_ct_ids` (`views.py:334`). That is **rejected**, for three reasons:

1. **It would break an existing query-count test.** `tests/test_html_element.py:280-319` loads two
   lesson pages under `CaptureQueriesContext` and asserts `len(q3) == len(q1)`; its own comment records
   that a cold `ContentType` cache makes the *first* captured request pay an extra CT `SELECT`, which is
   why it pre-warms exactly `MathElement` and `HtmlElement`. The eight validator-half models are reached
   today only through `content_type__model=` joins, never through `get_for_model`, so the id-based form
   introduces up to eight cold-cache CT SELECTs on the first lesson render in a process — red in
   isolated runs and nondeterministically red under `pytest -n auto`. The join form touches no CT cache
   and leaves that test alone.
2. **It would require a new `from django.apps import apps` import in `courses/views.py`** (there is no
   `apps` reference in that file today) purely to map the names back to model classes — a round trip the
   join form does not need.
3. It re-scrambles C1's sorted order into a set of ids, voiding the SQL-stability property C1 sorts for.

**Name.** `has_stateful_elements`, not `has_resettable_state` — the latter reads as "this student has
state that can be reset", which is precisely the rule D1 rejected, and the next reader would inherit
the wrong semantics. The chosen name is capability-shaped, matching its neighbours (`has_questions`,
`has_stepper`).

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
(`core/static/core/css/app.css:547-548`). Dropping the third flex child leaves title + pill correctly
placed, and the `max-width: 640px` rule (`courses.css:827-828`) that gives the title its own row
behaves identically with two children. No JS references `.lesson-unit__reset`.

### C4. A lockstep note at the storage surface

The contract in C1's docstring is about writes to `UnitProgress.element_state`. Put the reminder where
**every** such route must look, not where only one of them looks:

- **Primary site: the field declaration**, `UnitProgress.element_state` (`courses/models.py:2340`). A
  one-line comment naming `state.stateful_element_model_names()` as the function a new write route must
  extend in lockstep. This is the only location a direct writer necessarily encounters.
- **Secondary site:** beside `progress_reset`'s `rows.update(element_state={})` (`views.py:559`), the
  in-tree example of a direct write that bypasses the helper entirely.

An earlier draft put the note only beside `save_element_state` (`views.py:670`) — or, worse, inside it
at `views.py:685`/`691`, which is the same place. That is aimed at the wrong reader: this codebase's
established shape for such a write is a *direct* one (`progress_reset` at `views.py:559`, migration
0050's `up.element_state = …`), and an author writing a third direct route would never call the helper
and so would never see a comment attached to it. A note beside the helper is optional; the field-level
note is not.

## Data flow

```
lesson_unit GET  ->  full_lesson_render_context -> build_lesson_context(node, user)
                       |
                       +-- stateful_element_model_names()
                       |     (no DB, uncached: 31 apps.get_model lookups + 31 getattrs)
                       |     (VALIDATORS keys & ELEMENT_MODELS) U {RESTORABLE_IN_LESSON types}
                       |     -> sorted tuple of 18 names
                       |
                       +-- node.elements.filter(content_type__app_label="courses",
                       |                        content_type__model__in=<those names>).exists()
                       |     (one query, flat over the unit, incl. tab/column/spoiler children;
                       |      no ContentType cache involvement)
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
(`views.py:272-274`, `views.py:431-435`). Test 5 pins that this stays true, because the failure is
silent: Django renders `{% if has_stateful_elements %}` as false when the variable is simply absent, so
a future render site with a hand-assembled context would drop the link with no other signal.

The flag is a property of the **unit's content**, identical for every student and independent of
enrollment, so it is unaffected by the enrolled / non-enrolled (author-preview) split at
`views.py:375-385`.

## Error handling

- **Unknown name in `ELEMENT_MODELS`.** `apps.get_model` inside C1 raises `LookupError`. This is
  deliberately **not** caught: `ELEMENT_MODELS` is the canonical element-type list — every name in it
  resolving to a real model is already pinned by the transfer-schema tests — so a name in it that
  resolves to nothing is a broken deployment that should fail loudly, not silently drop a type and hide
  reset buttons.
- **Unknown key in `VALIDATORS`** cannot reach `apps.get_model` — but **not because of the
  intersection**. The resolution loop iterates `ELEMENT_MODELS`, so a `VALIDATORS` key is never passed
  to `get_model` whether or not `& known` is present. `& known`'s sole job is to keep the *returned
  tuple* free of names that resolve to nothing: under the join-based C2 such a name would merely widen
  the `__in` list harmlessly, but it would break any future consumer that does resolve names to
  classes, and it makes the function's output a lie about what exists. (Stating the mechanism precisely
  matters here — this project has been bitten by a confident, false mechanism surviving review.) Test 8
  surfaces the typo in CI; test 9 falsifies the intersection.
- **`getattr(..., "RESTORABLE_IN_LESSON", False)`** defaults to `False`, so non-question element types
  (which never define the attr) are correctly excluded without a type check.
- **A dangling GFK join row is an accepted false positive.** C2 matches on the join row's content type
  alone, so an `Element` row whose `content_object` has been deleted still flips the flag and shows the
  link on a unit that renders nothing stateful. This state is real, not hypothetical —
  `courses_extras.py:41-43` returns `""` for exactly that case. No `content_object` existence check is
  warranted: every one of the nine existing `.exists()`-backed `has_*` flags has the same property,
  checking would cost a fetch per row, and the failure mode is a link that reaches "Nothing to clear
  here." — the residual D1 already accepts.
- **Fail direction.** Every *runtime data* failure mode of this feature degrades to a hidden or
  spurious link, never a broken page — the flag only ever gates an anchor. The single deliberate hard
  failure is bullet 1's `LookupError`, which signals a broken build rather than bad data; no try/except
  is warranted around either.
- **Orphaned blobs — the surviving routes, and where they run out.** Per §Purpose, an author deleting
  the last state-bearing element from a unit strands a student's stored blob, which the unit page will
  no longer offer to clear. What remains depends on the course's structure preset:
  - **Structured course** (parts/chapters/sections exist): the container-level reset
    (`_outline_node.html:24`) clears that subtree — precise enough.
  - **Flat course** (no grouping nodes at all): `_outline_node.html` renders its reset link only in the
    non-unit `{% else %}` branch (lines 19-26), so **no container-level reset exists**. The only route
    **the UI still offers** is `outline.html:11`, which resets the **entire course**. The escape hatch
    degrades from "clear this subtree" to "clear everything".

    Precisely: the degradation is one of **discoverability, not reachability**. `progress_reset` is
    unchanged (§Non-goals), so the per-unit reset URL keeps working for anyone who navigates to it
    directly — `tests/test_e2e_practice_state.py:142-146` already reaches it that way — and its
    confirmation page would still report a non-zero `affected_count` for the orphaned blob.

  This degradation is accepted for now — an orphaned blob requires an author to delete the last
  interactive element from a unit a student has already worked, which is rare, and the student's own
  work elsewhere is what a whole-course reset would also take. Two remediations exist if it proves
  unacceptable in practice, both out of scope here: adopt the union rule (see the rejected alternative
  under D1 — zero new queries, removes this case entirely), or **add** a per-unit reset link to the
  outline's unit rows. Note the second is an addition, not a gating change: `_outline_node.html` renders
  no reset link on unit rows today, so there is nothing there to gate.

## Non-goals

- **The outline and course-level reset links are not gated.** Hiding those correctly requires a
  subtree roll-up ("does any unit under this node hold a state-bearing element"), which means an extra
  query plus a walk in `build_outline` on a hot page — real cost for a case that barely occurs, since a
  container almost always has *some* interactive unit beneath it. `progress_reset`'s "Nothing to clear
  here." remains the backstop there.
- **`lesson_unit.html:77`'s script-arming OR-chain stays exactly as it is.** That line
  (`{% if has_reveal_gate or has_fill_gate or has_switch_gate or has_switch_grid or has_fill_table or
  has_guess_number or has_stepper %}`, arming `state.js`) looks like the obvious next victim of
  `has_stateful_elements`, and substituting it would be **wrong**: it deliberately excludes
  `has_markdone` (markdone.js is armed separately at line 84) and every question type, which
  `has_stateful_elements` includes. The two sets answer different questions — "which JS must load" vs
  "can this unit hold state" — and collapsing them would load `state.js` on question-only lessons that
  do not need it.
- **`progress_reset` itself is unchanged.** Both routes, the confirmation interstitial, the
  `affected_count` computation, and the "Nothing to clear here." branch all stay exactly as they are.
- **Quiz units are unaffected** — `_lesson_article.html` renders only for lessons.
- **No migration, no new or changed translatable strings, no CSS change.**

## Testing

Every guard below must be **falsified**, not merely run green: delete the guard, observe RED, restore.
This codebase has shipped vacuous tests repeatedly (see the practice-state build's four cases), and the
specific hazard here is a test that passes because of the *fixture*, not the condition.

**Each test names its own falsification, and no test's falsification is *subsumed* by another's.** The
weaker phrasing is deliberate and was earned: "exactly one test fires per mutation" is unachievable
here, because tests 2 and 7 are both link-*absence* guards and deleting the `{% if %}` in C3 necessarily
fires both. What matters is that every test has at least one mutation that fires it and that no test's
entire falsification surface is covered by another test — test 7's `bool(element_state)` OR fires test 7
alone, which is the property that makes it a real guard. Where a listed mutation fires more than one
test, the co-firing tests are named.

**Namespace warning for every test below.** There are **two** symbols named `VALIDATORS`:
`courses.state.VALIDATORS` (content-type-model namespace — the one this spec means) and
`courses.transfer.payloads.VALIDATORS` (transfer-key namespace: `"callout"`, `"table"`,
`"mark_done"`…), which ~20 test modules already import by that bare name. Always import the former
qualified: `from courses import state` then `state.VALIDATORS`, never a bare `VALIDATORS`.

### Tests 1-7 — `courses/tests/test_reset_controls.py`

1. **`test_lesson_page_links_to_the_reset_interstitial` will go RED as written.** It currently seeds a
   bare `make_course_with_unit()` with **no elements at all** (`test_reset_controls.py:19-20`), which is
   precisely the case this spec hides. Update it to seed a state-bearing element using the recipe
   already proven in that same file at lines 71-78 — `MarkDoneElement.objects.create(prompt="P")` then
   `add_element(unit, el)` (no `MarkDoneItem` rows are needed; the flag is type-based, not
   content-based). *Falsification: none needed — its RED-ness on the unmodified test IS the signal.*
2. **A unit with only non-state elements renders no reset link.** Seed a `TextElement` via
   `add_element`; assert the `courses:progress_reset` URL for that unit is absent from the body.
   **Also assert `status_code == 200` and a positive anchor from the same head block** (the
   `courses:complete` URL, or the unit title) — "URL absent" is otherwise satisfied by a 302 to login, a
   403, a 404 or a 500, i.e. by every failure mode of the fixture rather than of the condition, which is
   exactly the hazard the preamble names.

   *Falsification: **append `"textelement"` to the name list at C2's call site** — i.e. widen the
   sequence passed to `content_type__model__in`, not C1's union. This fires test 2 alone: test 7's
   survivor is deliberately a `VideoElement`; test 6's monkeypatched tuple already contains
   `"textelement"`, so it stays green; and C1's output is untouched, so test 8 stays green. Do **not**
   widen C1's union instead — test 8 asserts both the 18-name equality and `"textelement"`'s absence, so
   that mutation necessarily co-fires it. Deleting the `{% if %}` in C3 also fires test 2, but it fires
   test 7 too, which would leave test 2 with no falsification of its own — the condition the preamble
   forbids.*
3. **A nested state-bearing element still shows the link.** Follow the working pattern in
   `courses/tests/test_switchgrid_context.py:59-77` (`test_has_switch_grid_flag_when_nested_in_tab`),
   the same flat-query-under-a-tab guard for a sibling flag: create a `TabsElement` with
   `TabsElement.default_data()`, attach it via `join = Element.objects.create(unit=unit,
   content_object=tabs)`, read `tab_id = tabs.data["tabs"][0]["id"]`, then create the child as
   `Element.objects.create(unit=unit, content_object=MarkDoneElement.objects.create(prompt="P"),
   parent=join, tab_id=tab_id)`. **Use `MarkDoneElement` as the nested child** — the cited test nests a
   switch grid via a local `_grid()` helper that does not exist in this module, so do not copy that
   part. Note `tests/factories.py:162` `add_element(unit, obj)` creates **top-level rows only** (no
   `parent`/`tab_id`), so the child row must be created directly.

   **Assert the rendered link, not the context flag.** Copy the cited test's *fixture*, not its
   assertion: it calls `build_lesson_context(unit, user)` directly and checks `ctx["has_switch_grid"] is
   True`, whereas this test lives in `test_reset_controls.py` where every test drives the client. Log in
   as an enrolled student, GET the unit, and assert `status_code == 200` plus the presence of the
   `courses:progress_reset` URL — the same shape as test 2. *Falsification: scope C2's query to
   `parent__isnull=True`.*
4. **A question-only unit shows the link.** Every other render-level test uses the *validator* half of
   the union, so nothing would catch an implementation that mishandles the `RESTORABLE_IN_LESSON` half,
   and a unit whose only interactive content is a question would silently lose its link. Seed
   `ShortTextQuestionElement.objects.create(stem="Q", accepted="x")` via `add_element` — and **nothing
   else**, so the question is genuinely the only interactive element.

   *Falsification: restrict **C2's** filter to the validator half only (e.g. intersect the name list with
   `state.VALIDATORS`). **Test 6 co-fires, unavoidably** — it monkeypatches the helper to return
   `"textelement"`, which any C2-side validator-half intersection filters straight back out; that is
   inherent to test 6's purpose (proving the helper's output reaches the filter), not a defect in this
   mutation. Test 5 stays green because its fixture carries a `MarkDoneElement` beside its question. Do
   **not** falsify by narrowing C1's union instead — that co-fires test 8, which is no better.*
5. **The flag survives the non-GET render path.** POST `courses:check_answer` for a question in a
   stateful unit **without** the JS-fragment header, so the no-JS branch at `views.py:837` re-renders
   the full page; assert the reset URL is still present. A missing context variable renders as false in
   Django with no error, which is why this needs a test rather than §Data flow prose.

   **The question type and the POST body, literally:** seed
   `ShortTextQuestionElement.objects.create(stem="Q", accepted="x")` and post
   `{"answer": "x"}` — `ShortTextQuestionElement.build_answer` is `post.get("answer", "")`
   (`models.py:1819`). The value **must be non-empty**: an absent or empty `answer` takes the
   `answer_is_empty` branch at `views.py:800-801` (which clears stored state) rather than the store
   branch at `802-804`, so the test would exercise a different path while still rendering 200. The
   in-repo precedent is `courses/tests/test_question_restore.py:193`, which posts exactly
   `{"answer": "paris"}` to this route.

   **Seed a `MarkDoneElement` alongside the question** in this unit. Without it the unit's only
   interactive element is the question, and test 4's falsification (restricting C2 to the validator
   half) would fire this test too — the co-firing the preamble asks us to avoid where it is cheap to
   avoid, and here it costs one extra fixture row.

   *Falsification: at `views.py:828`, keep the call and drop the key —
   `ctx = full_lesson_render_context(node, request.user); ctx.pop("has_stateful_elements")`. That is the
   minimal mutation with the right blast radius. Do **not** substitute a genuinely hand-assembled
   (sparse) context: it also breaks `tests/test_questions_consumption.py:182` and `:211` and
   `tests/test_unit_nav_render.py:790`, which drive this same path and assert on the rendered page.*
6. **The C1→C2 seam is live.** Every other test stays green if `build_lesson_context` hand-inlines the
   18 names instead of calling `state_svc.stateful_element_model_names()` — tests 2/3/4/5 assert
   rendered outcomes and test 8 asserts C1's output in isolation. That is the drift D3 exists to
   prevent: when a 19th stateful type ships, test 8 goes RED, the author updates C1 and the test
   literal, and a stale inlined list in `views.py` silently keeps the new type's link hidden.
   Monkeypatch `courses.state.stateful_element_model_names` to return a tuple containing
   `"textelement"`, then assert the reset link **appears** on a text-only unit. *Falsification: inline a
   literal list in C2.*
7. **The orphaned-blob decision is pinned.** §Purpose accepts, deliberately, that a stored blob on a
   unit whose stateful element has since been deleted is no longer offered a reset link. Nothing else
   records that choice, so a later author "fixing" it — or accidentally implementing the union rule —
   would pass unnoticed in both directions. Seed a stateful element **and a surviving `VideoElement`**,
   store an `element_state` blob for the student, delete the stateful element (leaving the blob and the
   video), and assert the link is **absent**. Comment the test with D1 and the union alternative.

   **The surviving element is not decoration.** §Purpose frames the accepted cost as an author deleting
   the *last state-bearing* element from a unit that still holds content; without a survivor the unit is
   empty, which is a degenerate case indistinguishable from test 2's fixture. It is a `VideoElement`
   rather than a `TextElement` specifically so test 2's `"textelement"` falsification leaves this test
   green — see test 2.

   **The fixture must be exact, or the falsification silently cannot fire.** The state the falsification
   would read is *not* the DB column — it is the `state` local (`views.py:373`), published as
   `ctx["element_state"]` at `views.py:421`. That local is (a) **always present but empty** unless a
   `state_row` exists (enrolled, or authenticated with a pre-existing row) — it is initialized
   unconditionally at `views.py:373`, so the *key* never goes missing, only its contents — and (b)
   rebuilt at `views.py:386-397` in a way that **drops every non-`dict` value and every non-int-coercible
   key**. So seed an
   **enrolled** student and a **str-keyed, dict-valued** blob captured before the deletion — e.g.
   `UnitProgress.objects.create(student=…, unit=unit, element_state={str(join_row.pk): {"items": [item.pk]}})`.
   Seed `{"5": True}` (non-dict value) or an unenrolled user and the context dict comes back empty, the
   falsification goes GREEN, and the implementer records a falsification that never happened — the exact
   hazard the preamble names.

   *Falsification: **at the context-dict assembly (`views.py:404-428`), publish
   `"has_stateful_elements": has_stateful_elements or bool(state)`.** The local is named `state`, not
   `element_state` — and it is assigned at `views.py:373`, **after** the `has_*` block where C2 sits, so
   applying the OR at C2's own line would raise `UnboundLocalError` on every lesson render and red the
   entire suite rather than test 7. This fires test 7 alone: test 2's unit has no blob, so it stays
   green.*

### Tests 8-9 — `courses/tests/test_state_module.py`

8. **The derived set is correct.** This tests `courses/state.py`, so it belongs here — the module
   already asserts `state.VALIDATORS` key-by-key (lines 102, 129, 181). Assert
   `set(state.stateful_element_model_names())` equals an **explicitly hard-coded set of all 18 names**
   written out in the test:

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
   `videoelement`) are absent, and assert **`set(state.VALIDATORS) <= set(ELEMENT_MODELS)`** — the
   registry contract C1's intersection relies on, and the guard that turns a registry typo into a loud
   CI failure rather than a silently dropped element.

   **This test bundles four guards, and each needs its own named falsification** — "change one name in
   C1's union" is not performable, since C1 contains no literal names to change. Use:
   - *18-name equality:* drop a term from a derivation clause in C1 — e.g. `(set(VALIDATORS) & known) -
     {"stepperelement"}`.
   - *Sortedness:* have C1 return the raw `set`/`frozenset` instead of `tuple(sorted(...))`. Write the
     assertion as `assert names == tuple(sorted(names))`, **not** `list(names) == sorted(names)` — a set
     of 18 strings could in principle iterate in sorted order, making the RED a property of hash seeding
     rather than of the guard; a set never equals a tuple, so the type mismatch fails deterministically.
   - *Inert-type absence:* it shares the equality guard's mutation; note that explicitly rather than
     inventing a second one.
   - *`VALIDATORS <= ELEMENT_MODELS`:* falsified **test-side**, by
     `monkeypatch.setitem(state.VALIDATORS, "nosuchelement", …)`. Label it as a test-side falsification —
     there is no production edit that fires it — or split it into its own test.
9. **The `& known` intersection itself.** Test 8's subset assertion guards the *production registry*,
   not the *intersection*: delete `& known` from C1 and the suite stays green, because the real
   `VALIDATORS` is clean by construction — leaving the one guard with a stated platform-wide rationale
   as the only one nothing falsifies. `monkeypatch.setitem(state.VALIDATORS, "nosuchelement", lambda
   *a: None)`, then assert the return is **still exactly the 18 names** (equality, not merely
   `"nosuchelement" not in …`, so a widened `__in` list is caught as a value change).

   **Do not assert "it does not raise".** Per §Error handling, no arrangement of `VALIDATORS` can make
   C1 raise — the resolution loop iterates `ELEMENT_MODELS` — so that half can never go RED under this
   or any other production edit, and would be exactly the vacuous assertion this section forbids.
   *Falsification: remove `& known` — `"nosuchelement"` then appears in the output.*

### Test 10 — a source-text guard under `tests/` (NOT `courses/tests/`)

10. **The write-route invariant — pinned at the mutation surface, not at the helper.** Nothing else
    pins the "two independent routes" claim C1 rests on: test 8 catches a new state-bearing *type*, not
    a new *write route*.

    **Count `element_state` writes, not `save_element_state` calls.** An earlier draft counted
    `save_element_state(` occurrences. That aims at the wrong surface: the contract concerns writes to
    `UnitProgress.element_state`, and a *direct* write is the established shape here — `progress_reset`
    does exactly that at `views.py:559`, as did migration 0050. A third route of that shape leaves the
    helper's call count untouched and ships a state-bearing type with no reset affordance.

    **The matcher must be explicit, because the confounders are textually adjacent.** The write at
    `views.py:559` is `rows.update(element_state={})` and the *read* at `views.py:565` is
    `rows.exclude(element_state={})` — any token keyed on `element_state=` matches both. Use a regex
    that keys on the surrounding operation:

    ```python
    WRITE = re.compile(
        r"\.update\(\s*element_state=|element_state\.pop\(|element_state\[[^\]]*\]\s*="
        r"|\.element_state\s*=(?!=)"
    )
    ```

    **The fourth alternation is mandatory, not belt-and-braces.** Plain attribute assignment is the
    house style for this write — migration 0050 spells it `up.element_state = forward_state(...)`, and
    six existing e2e fixtures spell it `progress.element_state = <blob>` (`tests/test_e2e_fillgate.py:136`,
    `test_e2e_filltable.py:217`, `test_e2e_guessnumber.py:131`, `test_e2e_reveal_gate.py:209`,
    `test_e2e_switchgate.py:139`, `test_e2e_switchgrid.py:159`). Without it the matcher is provably blind
    to the very shape this section calls the established one, and a fourth route written in house style
    ships green. The `(?!=)` guard against `==` follows `tests/test_builder_js_invariants.py:24`'s
    `panel\.innerHTML\s*=(?!=)`.

    Expected: **3** matches — `views.py:559` (`.update(`), `685` (`.pop(`), `691` (subscript assign).
    The new alternation adds no double-counts: `rows.update(element_state=` and
    `rows.exclude(element_state=` have no preceding dot on `element_state`, and `685`/`691` are followed
    by `.pop`/`[`, not `=`. Non-matching confounders, all containing the substring `element_state` and
    none of them writes: the comment at `383`; reads at `391`, `421`, `565`, `750`; and the *names*
    `save_element_state` (`670`, `772`, `775`, `801`, `803`) and `element_state_save` (`672`, `697`).

    **C1's docstring and C4's two comments must not spell `.element_state =` in prose**, or they will
    trip the widened matcher and move the expected count in the same commit that adds them.

    **Assert a count and a path set — never line numbers.** State the shape explicitly: the number of
    matches is 3, and the set of matching file paths is exactly `{"courses/views.py"}`. Line numbers are
    forbidden: C4 inserts a comment beside `views.py:559` and C2 inserts a block earlier in the same
    file, so this change itself moves all three sites.

    **Compare paths as POSIX strings.** This is a Windows box, so
    `str(p.relative_to(ROOT)) == "courses/views.py"` fails on `courses\\views.py` for a reason unrelated
    to the invariant. Use `p.relative_to(ROOT).as_posix()` (or compare `Path` objects), and say so in the
    test — this section has already taken responsibility for specifying the walk in full.

    **State the matcher's blind spot in the test.** It catches `.update()`, `.pop()`, subscript
    assignment and attribute assignment; it does **not** catch `setattr`, a queryset `.bulk_update`, an
    F-expression, or a write spelled through a local alias. The guard is a tripwire for the common
    shapes, not a proof.

    **Scope: the whole application, not one file.** C1's contract is platform-wide; a `views.py`-only
    scan would stay green for a new route in `courses/state.py`, another app, a signal handler, or a
    management command — exactly the drift this test exists to catch.

    **Derive the app list; do not hand-write it.** There are **nine** first-party apps
    (`config/settings/base.py:18-41`): `core`, `accounts`, `institution`, `courses`, `grouping`,
    `notes`, `notifications`, `tags`, `integrations`. A hand-written list is how this very spec first got
    it wrong — an earlier draft named six and silently dropped `accounts`, `institution` and `grouping`,
    the last of which owns cohort code and is a plausible home for a progress write. So walk
    `django.apps.apps.get_app_configs()` and **assert the resulting package set equals those nine
    names**, so a tenth app cannot be added without this guard noticing.

    **Filter by `Path(cfg.path).resolve().parent == ROOT`, NOT by "path is under `ROOT`".** The obvious
    filter is wrong for this repo's layout: the virtualenv lives **inside** the checkout (`.venv/`, per
    `.gitignore:4`, and `uv run` creates `<worktree>/.venv` the same way), so *every* third-party app
    config — Django's own, allauth, DRF, `django_extensions` — has a path under `ROOT` via
    `.venv/Lib/site-packages/`. Under the naive filter the nine-name assertion reds for a reason
    unrelated to the invariant, and the walk `rglob`s all of site-packages: precisely the over-broad scan
    this section claims to avoid (an earlier draft worried about a `venv/` spelled without the dot and
    let `.venv/` straight back in). First-party apps are *top-level packages of the repo*, so
    parent-equality is the filter that actually holds. Belt and braces: also reject any path containing a
    `.venv`, `site-packages`, or `node_modules` segment.

    Also walk `manage.py`, the `config/` package (`settings/`, `urls.py`, `asgi.py`, `wsgi.py`), and
    `scripts/` — all first-party in-tree Python that no app config covers. (`scripts/` holds one-off
    importers that do not touch `UnitProgress` today; walk it anyway, since "the whole application"
    should not depend on that staying true.) Skip any path containing a `migrations` or `tests` segment,
    any filename starting with `test_`, and `conftest.py`. The two cited precedents are single-file
    readers and offer no walk convention to inherit, so this one is specified here in full.

    **Read mechanism.** `Path(...).read_text(encoding="utf-8")`, following the repo's convention for
    source-text guards: a module under `tests/` with `ROOT = Path(__file__).resolve().parent.parent`
    (`tests/test_align_render.py:5-10`, `tests/test_builder_js_invariants.py:13-28`). It goes in
    `tests/`, not `courses/tests/test_state_module.py`, whose module-level
    `pytestmark = pytest.mark.django_db` would pull a DB fixture a pure text assertion does not need.
    The assertion message must name the contract — "a new write route into `element_state` must extend
    `state.stateful_element_model_names()` in lockstep" — so the next author reads it rather than
    bumping the number. *Falsification: add a fourth `element_state` write anywhere in scope.*

### e2e — `tests/test_e2e_unit_head_layout.py`

`_seed` (line 42) creates a unit with a single `TextElement`, so under this change the reset link
**disappears from that page**. The two tests measure only `.lesson-unit__title` and `.unit-done`, so
they would still pass — silently, while no longer guarding the three-item row they exist for (the
module docstring names "Mark done / Start fresh" explicitly). Three changes:

- **Keep the existing `TextElement` row and add a second `Element` row** for a
  `MarkDoneElement.objects.create(prompt="P")` — add, do not replace, since both tests share `_seed` and
  the text body is what gives the page realistic height. `MarkDoneElement` is chosen over a question
  element because it needs no child rows and no answer setup, and `markdone.js`'s boot pass is
  read-only (it POSTs only on click), so it adds no network traffic to a layout test.
- **Comment that row in `_seed`** with one line stating it is what keeps the reset link rendered
  (spec C3), so a future author tidying the fixture does not silently re-hide the link and re-hollow the
  module.
- **Extend `MEASURE`** (lines 63-77) to also return the `.lesson-unit__reset` rect, and assert it
  against `title_bottom` at both viewports exactly as `.unit-done` already is. Without this, restoring
  the third child leaves the row's widest action still unmeasured. Assert the link is present before
  measuring, so a regression that re-hides it fails loudly here rather than silently reducing coverage.

The e2e assertions are **layout regression guards, not falsifiable invariants** — they are explicitly
out of scope for the per-test RED report in §Definition of done.

### Definition of done

- Full non-e2e suite green (`uv run pytest -n auto`), against the worktree's own `libli_freshbtn`
  database. `tests/test_html_element.py`'s query-count assertion must be green **both** under `-n auto`
  and in isolation (`-k has_html`), since C2's rejected alternative is the thing that would break it.
- `uv run pytest -m e2e tests/test_e2e_unit_head_layout.py` green, run in the **foreground**
  (background `-m e2e` runs have spawned runaway browsers here before). **The `-m e2e` is mandatory**:
  `pyproject.toml:49` sets `addopts = "-q -m 'not e2e'"` and the module is `pytestmark =
  pytest.mark.e2e`, so a bare `uv run pytest tests/test_e2e_unit_head_layout.py` deselects both tests
  and exits 0 — a green run that executed nothing, in the one DoD item covering the only
  rendered-to-screen assertion in this build. Report the collected/passed count (2), not "green".
- `uv run ruff check`, `uv run ruff format --check`, `uv run python manage.py makemigrations --check`,
  and `uv run python manage.py check` all clean.
- Tests 2-10 each reported with their observed RED under their own named falsification (test 1's signal
  is its pre-change RED; the e2e assertions are exempt per above).
- **Look at the two-child head row.** This feature's whole visible output is a head row with the third
  child removed, on every text/video/image unit — and nothing above ever renders it to a screen: the
  e2e deliberately restores the *three*-child row, and tests 2 and 7 only assert a URL string is absent
  from HTML. Reasoned-about is not seen, and this repo's standing lesson is to screenshot styling
  changes before shipping. Screenshot a lesson unit with **no** stateful element at 1280px and 390px, in
  light and dark, and confirm the row reads as intentional: `justify-content: space-between` with
  `flex: 1` on the title should keep the pill hard right on desktop, and the `max-width: 640px` rule
  should give the title its own row with the pill left-aligned beneath it at phone width. If either
  reads as broken rather than merely different, the "no CSS change is required" claim in C3 is wrong and
  must be revisited before merge.
