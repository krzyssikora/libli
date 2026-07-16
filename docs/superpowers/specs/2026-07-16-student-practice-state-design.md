# Student practice state (persist & reset)

## Purpose

Make a student's **interactive lesson work survive a page reload** — and give them an explicit way to
throw it away and revise from scratch.

Today exactly **one** lesson element persists anything per-student: the mark-done checklist
(`UnitProgress.checklist_state`, PR #135/#136). Every other interactive element — both reveal gates,
Choose & confirm, Switch grid, Fill-in table, Guess the number, Step-by-step — is
*check-on-the-server, persist-nothing*: all state lives in DOM classes and JS closures and evaporates
on reload. Lesson-mode questions are the same; `check_answer` carries the literal comment
`# NOTHING is persisted`.

The consequences are already reachable in production code, not hypothetical:

- A student who unlocks content behind a "Show more" gate and reloads is **re-hidden** — their work is
  undone. This is the exact hazard that made Guess-the-number drop its `<form>` (PR #137): an
  unarmed Enter reloaded the page, and `reveal.js` persists nothing, so a guess element sitting
  behind a gate lost the gate too.
- A student working across two days, or on a different school machine, starts over every time.

After this change: interactive work **saves automatically** as the student goes (no Save button), and
a **Reset** control at any outline level — lesson, section, chapter, part, or whole course — clears
it deliberately.

### An honest reversal

The mark-done spec (`2026-07-15-markdone-checklist-design.md`, lines 8-13, 27-28) explicitly framed
this the other way round:

> Unlike every existing lesson self-check […] which is deliberately **ephemeral** — formative
> practice meant to reset each visit — the checklist records a deliberate student self-assertion and
> therefore persists.

and made it a non-goal:

> No retrofitting persistence onto other (rightly-ephemeral) elements.

**This spec reverses that stance deliberately, and the reversal should be understood rather than
glossed.** "Rightly ephemeral" was a post-hoc rationalisation of an implementation fact: no
persistence mechanism existed, because no element had needed one until the checklist forced the seam
to be built. Nothing in the product argued for forgetting a student's work — and the reveal-gate
hazard above shows ephemerality actively *destroying* work rather than helpfully resetting it. The
distinction the old spec drew (self-assertion vs. formative practice) does not survive the user's
counter-example: a student who gets a question wrong and wants to return to it tomorrow is *exactly*
served by remembering where they stopped, and is protected from any downside by Reset.

What survives from the old framing, and is retained here as a hard invariant: practice state is
**personal, ungraded, and invisible to analytics**.

### Non-goals

- **No new element types.** `ELEMENT_MODELS` does not change (so the `len(ELEMENT_MODELS)` /
  `ELEMENT_MODELS[-1]` count-asserts in `tests/test_transfer_schema.py` and
  `tests/test_models_multigrid.py` are not triggered).
- **No change to graded quiz behaviour.** `QuizSubmission` / `QuestionResponse` / `Attempt` are not
  read, written, extended, or reset by this feature. Quiz-mode rendering is byte-identical.
- **No teacher-facing surface.** No analytics column, no gradebook field, no "reset a student's
  progress" admin control. Practice state is personal.
- **No navigation state.** Tabs' active tab, gallery's slide index and spoiler open/closed are *not*
  persisted: they are presentation, not work; the spoiler is deliberately zero-JS and persisting it
  would mean adding JS to an element that has none; and a remembered-open spoiler sabotages revision.
- **No localStorage.** Persistence is server-side and cross-device (a school lab means a different
  machine tomorrow). Retained from the mark-done spec's non-goals.
- **No no-JS save path** for the newly-persisted types (see *No-JS* below). Mark-done keeps its
  existing no-JS form.
- **No attempt history.** One current state per element, not an append-only log (`Attempt` exists for
  the graded path; practice needs no audit trail).
- **No author opt-out.** Persistence is not a per-course setting.

## Architecture / components

### Storage — `UnitProgress.element_state` (replaces `checklist_state`)

`courses/models.py:1983` — `UnitProgress` already exists, keyed `(student, unit)` with a unique
constraint, and already carries `seen_element_ids` + `checklist_state`. Practice state rides on that
row. **No new table, no row-per-element.**

```python
class UnitProgress(models.Model):
    ...
    # Per-student practice state, keyed by Element (join-row) pk.
    # {"<Element.pk>": {...per-type blob}}
    element_state = models.JSONField(default=dict)
```

`checklist_state` is **merged into this field and removed.** They are the same concept in every
respect that matters — personal, ungraded, per-student, invisible to analytics, same access rule,
same reset semantics — and keeping them separate would mean two save endpoints, two render kwargs,
two things for reset to clear, and a choice for every future element author to get wrong.

**Key space: the `Element` join-row pk, everywhere.** This is a deliberate correction. Today the same
`UnitProgress` row holds two meanings of "pk": `seen_element_ids` holds **join-row** pks, while
`checklist_state` keys on the **content-object** pk. That inconsistency is why the mark-done leaf
template must emit *no* `data-element-id` (a content pk could collide with a join-row pk and mis-mark
an element as seen → premature auto-completion; `markdone-checklist-design.md` §Persistence). The
join-row pk wins because:

- it identifies a *placement*, which is what state belongs to;
- `QuestionResponse.element` (`models.py:2072`) already points at it;
- the question check route already **receives** it (`…/u/<node_pk>/q/<element_pk>/check/`), so
  content-keying would force a reverse lookup on every question save.

JSON object keys are strings; all pks are `int()`-coerced on read and write. (The mark-done build
learned this the hard way: a no-JS `getlist("item")` yields strings, and an un-coerced string key
silently drops every tick — spec-review R2 catch.)

### Migration

One migration (**provisional number 0050** — highest existing is `0049_guessnumberelement…`; the
implementer MUST run `makemigrations` against the real branch base and use whatever number it
assigns, never hardcode, since an adjacent number may be claimed by a sibling PR):

1. `AddField` `UnitProgress.element_state`, `JSONField(default=dict)` — back-fills to `{}`.
2. `RunPython` re-key: for each `UnitProgress` row, for each `checklist_state` key (a
   `MarkDoneElement` pk), find the `Element` join row with
   `content_type=<markdoneelement>`, `object_id=<key>`, `unit=<progress.unit>` and write
   `element_state[str(element.pk)] = {"items": [...]}`.
3. `RemoveField` `UnitProgress.checklist_state`.

Rules for the RunPython:

- Use the historical model via `apps.get_model`, and resolve the ContentType by
  `app_label`/`model` string — never import the real model or use `ContentType.objects.get_for_model`.
- **Orphaned keys** (element since deleted) are **dropped** — they are already dead data that the
  current read path ignores.
- **Ambiguity follows the documented 1:1 invariant** (`join_row()`, `models.py:1109`): the GFK is
  effectively 1:1 and `save_element` creates content + join row together. If >1 join row somehow
  matches, take the **lowest pk** — deterministic, and identical to what `join_row()` /
  `order_by("pk").first()` already resolve to, so the migration and the render path agree. Must not
  crash.
- **Reversible**: the backward function re-keys join-row pk → `object_id`.
- There is **no live instance and no real student data** (confirmed with the user), so the migration
  needs no batching, no rollback plan, and no volume check. It is still written correctly and
  reversibly because dev databases hold data.

### Per-type state blobs

**The blob is opaque to the storage layer and owned by each type.** The field does not know what a
stepper is. Each participating type registers a small **validator** that normalizes its own blob on
save.

The load-bearing rule: **an unknown, malformed, or unparseable blob is treated as absent, and the
element renders fresh — never a 500.** This mirrors `markdone_save`'s existing "garbage input is
skipped" property, and means a future schema change to any one type cannot brick a lesson for
everyone.

| Type (form key) | Blob |
|---|---|
| `markdone` | `{"items": [<MarkDoneItem.pk>, ...]}` |
| `revealgate` | `{"open": true}` |
| `fillgate` | `{"open": true, "blanks": ["<as typed>", ...]}` |
| `switchgate` | `{"open": true, "choice": <pk>}` |
| `stepper` | `{"shown": <int>}` |
| `switchgrid` | `{"choices": {"<cycler>": <pk>}, "done": <bool>}` |
| `filltable` | `{"cells": {"<r>,<c>": "<as typed>"}, "done": <bool>}` |
| `guessnumber` | `{"guesses": [<num>, ...], "solved": <bool>}` |
| any `QuestionElement` | `{"answer": <answer_to_json(answer)>}` |

**Questions store the answer only — never the verdict.** `mark_result` is rebuilt by re-marking the
stored answer at render time (see *Restore — questions*). This is not just economy: storing `correct`
would **freeze a stale verdict**, so an author fixing a wrong correct-answer would leave every
already-stored student answer marked against the old key. Re-marking keeps `mark()` the single source
of truth. `courses/quiz.py:67 answer_to_json` / `:85 answer_from_json` / `:76 rehydrate` already
handle every question type's payload shape and are proven on the quiz path — this feature **borrows
the quiz codecs; it does not extend the quiz spine**.

**Empty/default state drops the key** rather than storing `{}` (mark-done already does this;
`views.py:630`). This keeps `element_state == {}` meaning "nothing to restore" and makes reset's
result indistinguishable from never-touched.

### The render seam

The seam exists and is generic — the mark-done build created it (`ElementBase.render` gained kwargs;
`render_element` reads them from context, `takes_context=True`). It needs four changes.

**1. The generic branch must pass the join row down — the element should stop re-deriving its own pk.**

State is keyed by join-row pk, so every leaf needs to know its own join-row pk in order to emit its
`data-state` and POST the right key. Today `ElementBase.render` is **not told which join row it is
being rendered for**, so each type that needs the pk re-derives it by self-lookup. There are exactly
**five** such sites, all inside `render()` overrides — `models.py:635` (FillGate), `:661`
(SwitchGate), `:693` (GuessNumber), `:723` (SwitchGrid), `:910` (FillTable):

```python
join = self.elements.order_by("pk").first()
return render_to_string(..., {"el": self, "eid": join.pk if join else 0})
```

The fix is already sitting in the caller: **`render_element` has the join row — it is the tag's own
argument** (`obj = element.content_object`, `courses_extras.py:38`), and the **question branch
already passes it** (`obj.render(element=element, ...)`, `:50`). The generic branch simply never did.
So:

```python
# ElementBase.render (models.py:340)
def render(self, *, element=None, state=None, slug=None, node_pk=None):
    eid = element.pk if element else 0
    mine = (state or {}).get(eid, {})
    ...
```

`eid` keeps its existing name (leaf templates already use `{{ eid }}`) and its existing **`0`
sentinel for "no join row yet"** — which is what the editor preview relies on (an unsaved element has
no join row; the JS no-ops on `eid == 0`). With `element` passed explicitly, `eid = 0` now means
*genuinely unsaved* rather than *lookup missed*, and **five per-element queries per page render are
deleted**. It also scales: the ~8 further types this feature touches need the pk and must not each
add a sixth, seventh, eighth lookup.

**The 1:1 GFK assumption is retained, deliberately — this feature does not touch it.**
`TabsElement.join_row()` (`models.py:1109`) documents it explicitly: *"This concrete's single Element
join row (the GFK is effectively 1:1). The ONE handle every children-consumer uses: render(),
resolved_tabs(), has_math, and the export walk."* Multi-placement of one content object is
**unsupported project-wide** — it would break tab children resolution and the export walk, not just
state. So `element_state` adopts the same assumption rather than unilaterally supporting a case the
rest of the codebase rejects. Passing `element` is worth doing because it makes the pk
**authoritative rather than re-derived** and removes the queries — *not* because it fixes a
multi-placement bug. Do not write a test asserting two placements keep separate state: that would
pin behaviour the surrounding code does not support.

**2. The 7 overrides that currently swallow the context must take the real signature.**
`models.py:632` (FillGate), `:658` (SwitchGate), `:690` (GuessNumber), `:720` (SwitchGrid), `:804`
(Table), `:906` (FillTable), `:989` (Gallery) are all `def render(self, **_kwargs):` — they
**physically cannot receive server state today**. All 7 take the signature above (or they `TypeError`
the moment the caller passes `state`). Only the **five** listed in (1) also drop a self-lookup:
**Table (`:804`) and Gallery (`:989`) never resolved `eid` at all** and need the signature change
only — Table is static display and Gallery's slide position is an explicit non-goal, so neither
persists anything.

> **This is a known landmine.** A render-signature change that `TypeError`s every lesson containing a
> FillGate/Gallery/Table is precisely the break that plan-review *and* code-review both caught on the
> mark-done build. It gets explicit regression coverage (see *Testing*), not incidental coverage.

**3. `TabsElement.render` (`:1135`) and `TwoColumnElement.render` (`:1244`)** already forward and
**re-inject** the kwargs into their isolated `render_to_string` context — they take the renamed
kwargs and re-inject `state` (the **whole map**, not a resolved blob — children resolve their own).
Container templates need no change (a bare `{% render_element child %}` reads the re-injected
context), so **nesting works for free**.

**4. `render_element` (`courses/templatetags/courses_extras.py:22`)** reads `state` from context
alongside `slug`/`node_pk` — **no new tag parameters** (the mark-done precedent). Its generic branch
(`:64`) passes `element=element, state=context.get("state")`.

**`state` is passed as the whole `{element_pk: blob}` map, not a pre-resolved blob**, because
containers must re-inject the map for their children. Leaves resolve their own blob via `eid`. This
mirrors exactly how `checklist` works today — minimal deviation from a proven pattern.

`HtmlElement.render` (`:586`, signature `(self, unit, course, theme=None)`) is untouched — a sandboxed
iframe is an opaque world with its own `window.SEED` story, explicitly out of scope.

### Save endpoint — one writer, not six

`courses/urls.py` — one unit-scoped route replacing the mark-done route:

```python
path("courses/<slug:slug>/u/<int:node_pk>/state/", views.element_state_save, name="element_state_save"),
```

`element_state_save` copies `markdone_save`'s recipe (`views.py:566-632`) **verbatim**, because that
recipe is load-bearing:

- **Body:** JSON `{"element": <join_row_pk>, "state": {...}}` → `JsonResponse({"element":…, "state":…})`
  (the normalized state, so the client can reconcile). Form-encoded fallback retained for mark-done
  only → 302 + `#markdone-<pk>`.
- **Ownership:** `Element.objects.filter(pk=element_pk, unit=node)` — covers nested-in-tabs for free.
  A forged/foreign element → **400**.
- **Validation:** dispatch to the per-type validator by the element's content type. Unknown type or
  unparseable blob → skipped, never 500.
- **Concurrency:** `transaction.atomic()` → `get_or_create` → `select_for_update().get(...)` →
  per-key read-modify-write. This is the **only** concurrency-safe multi-element writer in the
  codebase and the reason for a single endpoint: element A's save must not clobber element B's key in
  the shared dict.
- **Access gate:** `can_access_course`, **not** `is_enrolled`. PR #136 is the scar — the gate must be
  lifted in **both** the write (endpoint) and the read (`build_lesson_context`) or saved state fails
  to re-render, and the client sees a 200 and never reverts.

**Why not fold persistence into the six existing `*_check` endpoints** (`fillgate_check`,
`switchgate_check`, `switchgrid_check`, `filltable_check`, `guessnumber_check`, `check_answer`) to
save a round-trip? Two reasons: it would mean six concurrent writers to one JSON dict, hence six
places to get `select_for_update` right; and it would not even suffice — a reveal gate or stepper has
**no check request** to piggyback on, so the state endpoint would be needed anyway and we would ship
both. One writer.

**No-JS.** State-saving is a **JS-only enhancement**. The existing check endpoints already return
JSON with no no-JS path, and Guess-the-number deliberately ships without a `<form>` at all. A no-JS
student therefore keeps **exactly today's behaviour** — nothing persists, nothing breaks.

Mark-done keeps its existing no-JS form, repointed at the new endpoint — **and its hidden element
field must change from the content pk to the join-row pk**: `markdoneelement.html` currently emits
`value="{{ el.pk }}"` (content pk, matching today's `checklist_state` keying); under join-row keying
it becomes `value="{{ eid }}"`. Missing this would make the no-JS path silently write a key the read
path never looks up — a tick that appears to save and vanishes on reload. The no-JS form POST is
covered by its own test, not only by the JS path.

### Restore — gates & self-checks (client-side)

`build_lesson_context` (`courses/views.py:348`) reads the row with **`.filter().first()`, never
`get_or_create` on a GET** (a passive viewer must not spawn a row — the PR #136 lesson), for any
authenticated viewer with `can_access_course`, and puts an int-keyed `{element_pk: blob}` map into
context as `state`.

Each participating leaf template emits its blob as **`data-state='{...}'`** (JSON, auto-escaped by
the template engine). **Never `data-element-id`** — that attribute stream is owned by `progress.js`'s
IntersectionObserver seen-tracker and must stay top-level-only.

Each element's existing JS reads `data-state` on boot and reconstructs, then POSTs on change.

**The server keeps rendering everything fresh and visible; restore is client-side only.** This
preserves the no-JS invariant (*the server never hard-hides a step*) and avoids a second server-side
rendering path per element.

**The fail-open watchdogs are untouched.** The prepaint arm (`reveal-armed` / `stepper-armed` inline
`<style>` in `lesson_unit.html:9-25`) and the `DOMContentLoaded` boot-flag disarm (`__revealBooted`,
`__stepperBooted`, `__fillGateBooted`) stay exactly as they are. Restore runs **inside** the existing
boot and in the **same direction** it already goes — boot un-hides, restore un-hides more. A dead
script still disarms and shows everything. **This feature adds no new way to trap content
permanently hidden**, and that property is a merge gate.

Client save discipline (generalising `markdone.js`): `fetch` + `keepalive` + CSRF header (read from
the cookie — `CSRF_COOKIE_HTTPONLY` is unset, as `progress.js` relies on), **revert the DOM to
last-known-persisted on failure**, and **no-op on an empty save URL** (the editor preview resolves
`{% url … as save_url %}` to `""` because `as` silences `NoReverseMatch`; `fetch("")` would hit the
current page).

### Restore — questions (server-side)

Questions restore differently, and this is the one place the design leans on an existing path rather
than adding one.

`render_element`'s question branch (`courses_extras.py:47-63`) already accepts exactly the
rehydration surface: `feedback_for_pk`, `selected_ids`, `submitted_values`, `mark_result`. **These
are tag parameters, not context reads** — the quiz page passes them explicitly. So `render_element`
gains context-derived defaults for the **lesson branch only**:

For a question element with saved state, in `mode="lesson"`, when the caller passed **no** explicit
`feedback_for_pk`:

1. `answer = answer_from_json(question, blob["answer"])`
2. `mark_result = question.mark(answer)` — re-marked, never stored
3. pass `feedback_for_pk=element.pk`, plus `selected_ids`/`submitted_values` via the existing
   `rehydrate` path.

Three rules, each of which must be a test:

- **Explicit tag args always win** over context-derived state. A live check (`check_answer` →
  `element_try`) passes its own `mark_result` and must be unaffected.
- **`mode="quiz"` never consults `element_state`.** Quiz rendering stays byte-identical.
- **`feedback_for_pk` is set only for elements that *have* saved state** — never blanket. The quiz
  page sets it for *every* element, and that is exactly what produced the literal `"None"` rendering
  in fresh inputs (`quiz-vs-lesson-consumption-divergence`, fixed with `|default_if_none:''`).
  Lessons must not reintroduce it.

**Known risk, to be re-verified during planning rather than assumed:** the quiz and lesson render
paths have diverged before and are a documented bug farm. The hypothesis that this generalises across
all ~10 question types with one change is *supported* by the shared signature but is **not proven**;
slice 3 must verify it per type before committing to the shape.

**Performance:** re-marking runs one `mark()` per persisted question per lesson load, and choice
marking re-queries `choices.all()` (a known double-query, already on the tidy-up backlog).
`build_lesson_context` already does per-type prefetching; the prefetch must cover the re-mark path or
a lesson with many answered questions becomes N+1.

### Reset

`courses/urls.py`:

```python
path("courses/<slug:slug>/reset/<int:node_pk>/", views.progress_reset, name="progress_reset"),
```

`progress_reset` is **POST-only** (`@require_POST` + CSRF; never GET — it is destructive).
`node_pk` may be **any** node kind: unit, section, chapter, part, or the course root.

- Resolve the subtree → the set of unit `ContentNode`s under `node` (inclusive if `node` is itself a
  unit). This needs a **new helper in `rollups.py`, `units_under(node)`**: the existing
  `_walk_preorder(course)` (`rollups.py:37`) walks from `parent_id=None` over a whole course, so it
  cannot start from an arbitrary node. `units_under` is a plain parent_id-grouped descent from
  `node`, returning a **set** — the pre-order subtlety that `_walk_preorder`'s docstring warns about
  (sibling `order` is only locally monotonic, so a flat scan is not pre-order) is **irrelevant here**,
  because reset does not care about order. Do not cargo-cult the ordering machinery into it.
- `UnitProgress.objects.filter(student=request.user, unit__in=<subtree units>).update(element_state={})`
  — one query. `student=request.user` always, so it is **IDOR-safe by construction** (matching
  `course_results`). No read-modify-write: we clear, we do not merge.
- Quiz units in the subtree are harmless: their `element_state` is already `{}`.
- Guarded by `can_access_course`.
- Redirects back to the referring outline/lesson.

**Two hard invariants, each pinned by its own named test:**

1. Reset **never** touches `seen_element_ids` or `completed`. Completion is scroll-driven (an
   IntersectionObserver, not an act of work) and feeds `build_progress_matrix` → teacher analytics. A
   student revising must not silently drag down what their teacher sees, and un-completing would be
   self-undoing anyway (it re-completes on the next scroll).
2. Reset **never** touches `QuizSubmission` / `QuestionResponse` / `Attempt`. Graded assessment
   history is not the student's to erase.

**UI.** A "Start fresh" control on the lesson page, and a reset control per node in the outline
(adapting automatically to whichever nodes the course's structure preset actually has — Flat /
Chapters / Parts / Full). The confirmation names the blast radius rather than being vague:

> Start fresh? This clears your answers and ticks in 14 lessons. Your quiz results are not affected.

Styled per the existing `.btn--danger` / danger-zone pattern (`sso-names-and-danger-zone-status`), and
verified light + dark with screenshots.

### i18n

New EN/PL strings: the reset buttons, the confirmation copy (pluralized on lesson count), and the
validator error strings.

**`makemessages` will fuzzy-match them** — it has on *every* element build, including validator
strings a plan's translation list didn't enumerate. The project-wide `test_po_catalog_clean` fails on
any `#, fuzzy` or `#~`. Strip the `fuzzy` token (keep `python-format`/`python-brace-format`), drop
`#| msgid` lines, set the correct PL.

### Transfer — explicitly untouched

`element_state` is **per-student**, so it is not course content: the transfer trio
(`SERIALIZERS`/`VALIDATORS`/`BUILDERS`), course export/import, and `FORMAT_VERSION` (currently **4**)
are **all unchanged**. No new element type ⇒ no new transfer key, no `NESTABLE_TYPE_KEYS` entry.

## Data flow

**Save (student ticks / opens a gate / answers):**

```
click → element JS updates DOM optimistically
      → POST …/u/<node_pk>/state/  {element: <join_pk>, state: {...}}
      → can_access_course → element belongs to node? → per-type validator
      → atomic: get_or_create UnitProgress → select_for_update → merge key → save
      → 200 {element, state}      → JS reconciles
        (non-200 / network error) → JS REVERTS the DOM to last-known-persisted
```

**Restore (lesson GET):**

```
build_lesson_context → UnitProgress.filter(student, unit).first()   [never get_or_create]
                     → context["state"] = {int(element_pk): blob}
lesson_unit.html {% render_element el %}          [el IS the Element join row]
  → render_element reads state map from context
     ├─ generic branch  → obj.render(element=el, state=<map>, slug=..., node_pk=...)
     │                   → eid = el.pk; mine = map.get(eid, {})   [no self-lookup query]
     │                   → leaf emits data-state='{...}'
     │                   → element JS boots, applies state (un-hides further)
     └─ question branch → answer_from_json → question.mark(answer) → mark_result
                        → render(element=el, feedback_for_pk=el.pk,
                                 selected_ids/submitted_values, mark_result)
  (tabs / two-column re-inject the state MAP → nested {% render_element child %} works unchanged)
```

**Reset:**

```
POST …/reset/<node_pk>/ → can_access_course
                        → units_under(node)  [set, order irrelevant]
                        → UnitProgress.filter(student=request.user, unit__in=…).update(element_state={})
                        → redirect back
   (seen_element_ids / completed / QuizSubmission / QuestionResponse / Attempt untouched)
```

## Error handling

| Case | Behaviour |
|---|---|
| Forged / foreign `element` pk | **400**, nothing written |
| Unknown content type for state | Skipped, 200 (never 500) |
| Malformed / unparseable blob on **save** | Per-type validator rejects → key untouched |
| Malformed blob already **stored** (schema drift) | Treated as **absent** → element renders fresh |
| Stale item/choice pk inside a blob | Ignored on read, pruned on next write (mark-done precedent) |
| Empty / default state | Key **dropped**, not stored as `{}` |
| Concurrent saves, two elements | `select_for_update` + per-key merge → neither clobbers |
| Save fails (network / 4xx / 5xx) | JS **reverts** the DOM to last-known-persisted |
| Overlapping in-flight saves, one fails | **Known limitation, carried over** from mark-done (PR #135 deferred): client/server may desync mid-burst. Out of scope; do not silently "fix" it here. |
| JS disabled / blocked | Nothing persists; **fail-open watchdogs still disarm**; content never trapped hidden |
| Element deleted after state stored | Orphan key ignored on read; migration drops it |
| Previewer (author/teacher, not enrolled) | **Persists** — the PR #136 rule (personal, ungraded, absent from analytics) |
| Anonymous user | No `UnitProgress`, no state, no save (access gate rejects) |

## Slicing

Three PRs. The cost is **breadth, not difficulty**.

**This is one spec and three plans — deliberately, and differently from the reveal-gate family**
(where each of the three slices got its own spec). There, each slice introduced *novel architecture*
— slice 1 built the cascade engine, slices 2–3 each added a check endpoint and a widget — so each
warranted its own design. Here the architecture is **wholly fixed by this document**: one field, one
endpoint, one reset, one seam. Slice 2 is mechanical repetition of a pattern slice 1 proves, and
slice 3's only novel design (question rehydration) is specified above. Three specs would triplicate
the architecture and invite drift between copies.

So: **the plan derived from this spec covers Slice 1 only.** Slices 2 and 3 get their own thin plans
written against *this* spec, with no new spec. If slice 3's rehydration hypothesis (see *Open
questions*) fails verification, that changes the picture — and slice 3 then earns a real spec of its
own rather than a thin plan.

**Slice 1 — substrate + proof.** `element_state` field + migration (add / re-key / drop
`checklist_state`); mark-done merged onto it; the **7 override fixes**; `element_state_save` with
validator dispatch; `progress_reset` + `units_under` helper + lesson "Start fresh" + per-node outline
control + confirm copy; and exactly **one further existing element brought onto the mechanism** as
proof: **Show more** (`revealgate`). (No element *type* is created — see Non-goals. "Brought onto the
mechanism" means an already-shipped type starts persisting.) Show more is the highest-pain type and
has the simplest possible blob (`{"open": true}`), so the slice proves the whole loop end-to-end
without blob shape muddying it. Mark-done + Show more also give reset something real to clear.

**Slice 2 — remaining gates & self-checks.** Fill in & confirm, Choose & confirm, Step-by-step,
Switch grid, Fill-in table, Guess the number. Mechanical repetition of a proven pattern: emit
`data-state`, restore on boot, save on change, e2e each.

**Slice 3 — lesson-mode questions.** Per *Restore — questions*: verify the shared-signature
hypothesis per type **before** committing to the shape.

## Testing

**The 7 overrides (explicit, not incidental).** A parametrized test rendering a lesson containing
each of FillGate / SwitchGate / GuessNumber / SwitchGrid / Table / FillTable / Gallery — top-level
**and** nested in tabs and two-column — asserting 200 and no `TypeError`. This exact class of break
was caught twice on the mark-done build; it does not get to ship on a third.

**`eid` provenance.** Assert `eid` comes from the **passed join row**: a leaf rendered via
`{% render_element el %}` emits `el.pk`, and rendered with `element=None` (the editor-preview path)
emits the `0` sentinel and no save URL. Assert the five self-lookups are gone via `assertNumQueries`
on a gate-heavy lesson, so the per-element query cannot silently return.

**Do NOT test multi-placement state isolation.** One content object in two join rows is unsupported
project-wide (`join_row()`'s docstring; it would break `resolved_tabs` and the export walk too).
Pinning it here would assert behaviour the surrounding code contradicts.

**Migration.** Re-key content pk → join-row pk; orphaned key dropped; nested element re-keyed;
`{}` and absent state; reversibility; a row whose element was deleted.

**Endpoint.** Forged element → 400; garbage blob skipped, not 500; empty state drops the key;
int-coercion of string pks; previewer persists; **concurrent two-element save does not clobber**
(the `select_for_update` path); `can_access_course` denies a stranger.

**Reset.** Subtree walk across **all four structure presets** (Flat / Chapters / Parts / Full); reset
at unit / section / chapter / course-root; **IDOR** (student A cannot reset student B — assert via
`student=request.user`, not a hand-passed pk); and the two hard invariants as their own **named**
tests (`test_reset_does_not_touch_completion`, `test_reset_does_not_touch_graded_records`).

**Questions.** Explicit tag args win over context state; `mode="quiz"` renders byte-identically
(assert against a pre-change snapshot); `feedback_for_pk` set **only** for elements with state (assert
the negative: a fresh input renders `value=""`, never `"None"`); re-marking picks up an author's
corrected answer key.

**e2e (the real gap).** Per element: drive the **real gesture** → reload → assert restored. Never
`page.evaluate` — that scar is well-earned (`e2e-must-drive-real-ui`). Plus: reset → reload → gone;
and a **fail-open** e2e (block the JS, assert content is visible, not trapped).

**Regression.** Full non-e2e suite green; `test_po_catalog_clean` fuzzy-free; `ruff check` **and**
`ruff format --check`; `makemigrations --check`; `manage check`.

**Execution notes.** Isolate a per-worktree test DB (`DATABASE_URL=…/libli_<slug>`; the role has
CREATEDB) — concurrent worktrees collide on `test_libli`. Run the heavy suite with `-n auto`
(serial exceeds a subagent's 600s watchdog). e2e needs an explicit `-m e2e` (else `addopts = -q -m
'not e2e'` deselects the file and pytest exits 5 **looking like success**); run focused e2e
foreground only, never backgrounded.

## Open questions to resolve in planning

1. **Does the question rehydration generalise?** (Slice 3.) Verify per type; do not assume.
2. **Prefetch shape for the re-mark path** — confirm `build_lesson_context`'s per-type prefetch covers
   `mark()` for every question type, or the N+1 lands on lessons with many answered questions.
3. **`data-state` vs. per-type attributes** — one generic attribute is proposed; if any element's JS
   already owns a conflicting attribute name, resolve at plan time.
