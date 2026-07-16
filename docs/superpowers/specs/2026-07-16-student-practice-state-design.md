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

**Coercion, precisely** — the map key and the pks *inside* a blob are different cases:

- **The map key** is `str(element.pk)` on **write** (JSON object keys are strings, mirroring
  `views.py:628`) and `int(k)` on **read**. It cannot be int-coerced on write.
- **Item / choice pks inside a blob** are `int()`-coerced on **both** sides.

The mark-done build learned the inner half the hard way: a no-JS `getlist("item")` yields strings, and
an un-coerced string pk silently drops every tick against an int-keyed set — spec-review R2 catch.

### Migration

One migration (**provisional number 0050** — highest existing is `0049_guessnumberelement…`; the
implementer MUST run `makemigrations` against the real branch base and use whatever number it
assigns, never hardcode, since an adjacent number may be claimed by a sibling PR):

1. `AddField` `UnitProgress.element_state`, `JSONField(default=dict)` — back-fills to `{}`.
2. `RunPython` re-key: for each `UnitProgress` row, for each `checklist_state` key (a
   `MarkDoneElement` pk), find the `Element` join row with
   `content_type=<markdoneelement>`, `object_id=<key>`, `unit=<progress.unit>` and write
   `element_state[str(element.pk)] = {"items": [...]}`.
   **Note the shape change, not just the key change:** `checklist_state[str(pk)]` is a **bare list**
   today (`views.py:628`: `progress.checklist_state[str(element.pk)] = checked`), whereas
   `element_state` wraps it under `"items"`. Forward must **wrap**; backward must **unwrap**.
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
- **Reversible — and the backward function is lossy by necessity, which must be explicit.** It must:
  (a) **filter to `markdoneelement` join rows only**, dropping every other key. After slice 1
  `element_state` also holds `revealgate` blobs (after slice 2, six more types) that `checklist_state`
  structurally cannot represent — a naive re-key would write a gate blob into the checklist field.
  (b) map `element.pk → object_id`; (c) **unwrap** `blob["items"]` back to a bare list.
  Dropping non-mark-done keys is correct (the field they came from did not exist at that migration
  state) and must be commented as deliberate. **Named test: reversing a row holding a `revealgate`
  blob drops it and leaves a valid `checklist_state`.**
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

#### Validator contract

```python
STORE   = <normalized dict>      # write this blob under the key
EMPTY   = <sentinel>             # DELETE the key
REJECT  = <sentinel>             # LEAVE THE STORED KEY UNTOUCHED

def validate(element, obj, payload) -> dict | EMPTY | REJECT
```

- `element` is the `Element` join row; **`obj` is the concrete content object** (`element.content_object`).
  The validator needs it: mark-done must intersect against `obj.items` pks, switch-gate against valid
  choice pks. A validator that cannot see `obj` cannot validate.
- `payload` is the client's `state` blob, or — for the question fallback — the raw `fields` map.
- **EMPTY and REJECT must be distinct sentinels, never a bare falsy value.** They are *opposite*
  outcomes: EMPTY deletes the stored key, REJECT preserves it. An implementer who collapses both into
  `None`/`{}`/`False` makes a malformed blob **wipe the student's prior good state** — a silent
  data-loss bug that no 500 or log would reveal. This is the single most dangerous conflation in the
  feature.
- **Exceptions are caught by the endpoint and mapped to REJECT** (never 500). A validator may raise
  rather than returning REJECT explicitly.

**Validators check shape and referential validity ONLY — they do NOT re-verify correctness.** A
validator confirms the blob's shape and that its pks refer to things that exist and belong to this
element (mark-done intersects against `obj.items`; switch-gate against `obj`'s valid choice pks). It
does **not** recompute whether the student was *right*: `{"solved": true}` on a guess-number is
**trusted** without re-checking `obj.target`/`obj.tolerance`, and `{"open": true}` on a fill-gate is
trusted without re-deriving it from `blanks`.

This is a deliberate decision, and the two worked examples above are exactly why it must be written
down (slices 2 and 3 get thin plans against *this* spec, so nothing downstream would decide it). The
reasoning: practice state is **ungraded and personal**, absent from analytics and from every rollup;
the DOM is **already client-forgeable** (any student can reveal gated content with devtools today, and
`reveal.js` has no server round-trip at all); and the six `*_check` endpoints remain the real check
path, unchanged. Re-verifying would duplicate six checkers inside six validators to protect a record
whose only consumer is the student themselves. A forged `solved` harms nobody but its author, and
Reset undoes it.

**Consequence for the client protocol:** the client **does** send `solved` / `open` / `done`, and the
server stores them as given.

Types below are named by **form key for readability only**; the validator registry is keyed by the
content-type `model` string (`markdoneelement`, `revealgateelement`, …) — see *Save endpoint →
Dispatch key space*. Do not use this column as the registry key.

| Type (form key) | Blob | Direction |
|---|---|---|
| `markdone` | `{"items": [<MarkDoneItem.pk>, ...]}` | reversible |
| `revealgate` | `{"open": true}` | **monotone** |
| `fillgate` | `{"open": true, "blanks": ["<as typed>", ...]}` | **monotone** |
| `switchgate` | `{"open": true, "choice": <pk>}` | **monotone** |
| `stepper` | `{"shown": <int>}` | **monotone** |
| `switchgrid` | `{"choices": {"<cycler>": <pk>}, "done": <bool>}` | reversible |
| `filltable` | `{"cells": {"<r>,<c>": "<as typed>"}, "done": <bool>}` | reversible |
| `guessnumber` | `{"guesses": [<num>, ...], "solved": <bool>}` | **monotone** |
| any `QuestionElement` | `{"answer": <answer_to_json(answer)>}` | **fire-and-forget** |

**Direction is load-bearing, not documentation.** It has exactly **three** values, and every type
resolves to exactly one — there is no conditional direction:

- **monotone** — the DOM only ever moves one way (content revealed, a step shown, a guess added), and
  `reveal.js` has **no un-cascade**: nothing can re-hide a revealed sibling. A failed save **leaves
  the DOM as it is and simply does not mark it persisted** (the student re-earns it, or it re-hides on
  the next load). Rolling a monotone type back on the client would re-hide content the student
  legitimately unlocked with a gesture that never needed a server — precisely the *"new way to trap
  content permanently hidden"* this spec names a merge gate.
- **reversible** — the student can un-assert it (untick an item, re-cycle a switch, retype a cell), so
  a failed save **reverts the DOM** to last-known-persisted. `switchgrid` / `filltable` are
  reversible **outright**, not "reversible until `done`": once `done` their widget is locked and no
  further save occurs, so the direction never needs to flip and the flip point never needs defining.
- **fire-and-forget** — questions only. See below.

**Questions are neither, and forcing them onto the two-value axis breaks both rules:**

- *They cannot adopt.* A question's echo is `{"answer": <answer_to_json(...)>}`, and "re-render the
  widget from the echo" in JS would mean reimplementing `rehydrate` client-side — the exact thing
  *Restore — questions* rules out. The UI is already driven by `check_answer`'s own response.
- *They must never revert.* A student Checks, `check_answer` succeeds and paints feedback, the
  parallel state POST fails — reverting would wipe the answer **visibly on screen** and replace it
  with an older persisted one. That is the same silent data-loss class as the EMPTY/REJECT
  conflation.

So the question state-save is **fire-and-forget**: `question.js` **ignores the echo body entirely**,
never adopts, and never reverts. On failure the DOM is untouched and the answer is simply not
persisted — it re-persists on the next Check. Restore for questions is **server-side only** (see
*Restore — questions*), so the client has nothing to reconcile.

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
being rendered for**, so each type that needs the pk re-derives it by self-lookup. There are **seven**
such call sites:

- **Five in leaf `render()` overrides**, inline — `models.py:635` (FillGate), `:661` (SwitchGate),
  `:693` (GuessNumber), `:723` (SwitchGrid), `:910` (FillTable):
  ```python
  join = self.elements.order_by("pk").first()
  return render_to_string(..., {"el": self, "eid": join.pk if join else 0})
  ```
- **Two in container `render()` overrides**, via the named helper — `TabsElement.render`
  (`:1135`) and `TwoColumnElement.render` (`:1244`) each call `join = self.join_row()` **purely to
  compute `eid`**. That specific call is removable. **Their `resolved_tabs()` / `resolved_columns()`
  calls to `join_row()` are NOT** — those resolve children and are shared with `has_math` and the
  export walk, which have no `element` to be handed. Only the `eid` lookup goes.

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

**What the base hands each leaf** (today it passes `{"el", "checked"}`; `checked` is a **set** keyed
by content pk, consumed by `markdoneelement.html` as `{% if item.pk in checked %}`):

- `el`, `eid`, `slug`, `node_pk` — for every leaf.
- **`mine`** — this leaf's own **resolved blob** (leaves do not index the map).
- `checked` — **retained for mark-done only**, derived as `{int(i) for i in mine.get("items", ())}`.
  Keeping it means `markdoneelement.html`'s two `{% if item.pk in checked %}` sites are unchanged and
  stay O(1); the int-coercion is mandatory (JSON round-trips ints fine, but the no-JS `getlist` path
  yields strings — the same trap that silently dropped every tick in the mark-done build).

**The leaf's blob is named `mine`, NOT `state` — `state` always means the whole `{pk: blob}` map.**
The kwarg into every `render()` is the map, and containers re-inject the map into their child
context, so a leaf template that saw a `state` holding *its own blob* would be reading a different
shape from the identically-named variable one level up — silently, with no error. One name, one
meaning: `state` = map, `mine` = this leaf's blob (matching the Python variable above).

`eid` keeps its existing name (the templates that already use it keep working) and its **`0`
sentinel**, which means *a content object with no join row* — a transient, mid-create object, exactly
what `join_row()`'s `if join is None` branch already guards. **It does not mean "editor preview"**:
`_preview.html:16` renders `{% render_element el action_url=try_url %}` over **real join rows**
(`preview_elements = join_rows`, `views_manage.py:689/714`), so `eid` is already non-zero there. What
actually makes the preview inert is that its context carries `course`/`unit` but **no `slug`/
`node_pk`**, so `{% url … as save_url %}` resolves to `""` and the JS no-ops (see *Client save
discipline*). That is the mechanism to test, not an `element=None` path that never occurs.

With `element` passed explicitly, **seven per-render lookups are deleted**, and the ~8 further types
this feature touches get the pk handed to them rather than each adding an eighth, ninth, tenth
lookup.

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

> **Two different sets of seven — do not conflate them.** The **seven `eid` sites** above are
> {FillGate, SwitchGate, GuessNumber, SwitchGrid, FillTable, **Tabs, TwoColumn**}. The **seven
> `**_kwargs` overrides** in (2) below are {FillGate, SwitchGate, GuessNumber, SwitchGrid, **Table**,
> FillTable, **Gallery**}. They share only four members. Counting both plus the two containers whose
> signatures are renamed in (3), **nine `render()` signatures change in total.** Where *Slicing* and
> *Testing* say "the 7 overrides" they mean the `**_kwargs` set.

**2. The 7 `**_kwargs` overrides must take the real signature.**
`models.py:632` (FillGate), `:658` (SwitchGate), `:690` (GuessNumber), `:720` (SwitchGrid), `:804`
(Table), `:906` (FillTable), `:989` (Gallery) are all `def render(self, **_kwargs):` — they
**physically cannot receive server state today**. All 7 take the signature above (or they `TypeError`
the moment the caller passes `state`). Only the **five** listed in (1) also drop a self-lookup:
**Table (`:804`) and Gallery (`:989`) never resolved `eid` at all** and need the signature change
only — Table is static display and Gallery's slide position is an explicit non-goal, so neither
persists anything.

**Each of the five must also start forwarding `slug` / `node_pk` into its `render_to_string`
context.** They pass only `{"el", "eid"}` today, so a template doing `{% url … as save_url %}` would
silently resolve `save_url` to `""` (the `as` form swallows `NoReverseMatch`) and **every save would
no-op with no error** — the exact failure mode that made mark-done's ticks vanish in PR #136. This is
easy to miss because it fails silently and only under a real student session.

**The newly-persisting leaves need `eid` + `save_url`, but not uniformly:**

- `revealgateelement.html` (**slice 1's proof element**) and `stepperelement.html` have **neither**
  `eid` nor `save_url` — both are added.
- `markdoneelement.html` gains **`eid` only**. Its `save_url` already exists —
  `{% url 'courses:markdone_save' slug=slug node_pk=node_pk as save_url %}` on line 2, feeding
  `data-markdone-url` and the form `action` — and is merely repointed at the renamed route.

Do not assume the gate templates resemble the fill-gate family.

**The reveal gate's new attributes go ON THE EXISTING `<button>` — no wrapper element may be
introduced.** `revealgateelement.html` renders a bare
`<button type="button" class="reveal-gate" data-reveal-gate hidden>` directly inside
`.lesson-block__body`, and **three** places hardcode that exact direct-child chain:

| Site | Selector |
|---|---|
| `reveal.js:35` (`isGateWrapper`) | `:scope > .lesson-block__body > [data-reveal-gate]` |
| `lesson_unit.html:39` (prepaint `<style>`) | `.reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block:not(.reveal-shown)` |
| `core/static/core/css/app.css:961` (**duplicate** of the same rule) | same `:has(> .lesson-block__body > [data-reveal-gate])` chain |

Hanging `data-state` on a natural-looking new wrapper `<div>` **silently breaks all three at once**:
the prepaint guard stops hiding following blocks (**gated content leaks on load**) and the cascade
stops detecting gate boundaries (**one click reveals the whole slide**). Neither failure is loud.
Named test: a gate still hides its following siblings pre-boot.

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

- **Decorators and node resolution — inherited explicitly, not by implication:**
  `@login_required` + `@require_POST`, then
  `node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)` — exactly
  `markdone_save`'s first line. **`require_lesson=True` matters:** without it,
  `…/u/<quiz_node_pk>/state/` would accept writes on quiz units, contradicting both the non-goal that
  quiz behaviour is untouched and the Reset section's expectation that quiz `element_state` is empty.
  With it, that expectation becomes **structural** for the JSON path rather than a convention resting
  on a hidden palette. Tests: a quiz `node_pk` **404s**; a `node_pk` from a foreign course **404s**.

- **Body:** JSON `{"element": <join_row_pk>, "state": {...}}` for gates/self-checks, or
  `{"element": …, "fields": {...}}` for questions (see *Restore — questions*). The two are
  **mutually exclusive**; both present, or `fields` on a non-question element, → **400**.
  **Form-encoded fallback, mark-done only:** the existing no-JS form posts `element` plus a repeated
  `item` field, so the branch reads `request.POST["element"]` + `request.POST.getlist("item")`,
  **synthesizes `{"items": [...]}`** (int-coercing — `getlist` yields strings), runs it through the
  **same `markdoneelement` validator** as the JSON path, and redirects 302 + `#markdone-<eid>`. A
  form-encoded POST naming a **non-mark-done** content type → **400**. This path has **no
  reconcile by design**: the 302 re-renders the lesson from stored state, which *is* the echo.
- **Response — the body is authoritative, not the status code:**
  `JsonResponse({"element": …, "state": <the blob now stored for this element>})`. **On a skip or a
  validator rejection it echoes the *currently stored* blob** (or `{}` if none) — never the rejected
  input.

  **On 200 the client ADOPTS the echo — it does not compare-and-revert.** The echoed blob becomes
  last-known-persisted, and the widget re-renders from it. Adoption self-corrects a rejection (the
  echo is the unchanged prior blob) *and* a normalization, whereas comparing would fire on the
  server's own mandated normalizations and throw away correct work:

  - a student unticks their **last** mark-done item → client sends `{"items": []}` → the server
    **drops the key** (its own rule) → echoes `{}` → `{} != {"items": []}` → a comparing client would
    **re-tick the box the student just unticked**;
  - a **stale item pk is pruned** → echo `{"items": [3]}` vs sent `{"items": [3, 7]}` → a comparing
    client reverts, leaving the DOM *behind* the server;
  - **questions can never match by construction** — the client sends `fields`, the server echoes
    `{"answer": …}` computed by `build_answer`. The whole point is that the client *cannot* compute
    the blob, so every question save would revert.

  In all three the server stored the **correct** thing. Adoption is therefore the universal rule for
  200; **revert is only for non-200 / network failure**, and only for `reversible` types (see
  *Direction*).
- **Ownership:** `Element.objects.filter(pk=element_pk, unit=node)` — covers nested-in-tabs for free.
  A forged/foreign element → **400**.
- **Validation:** dispatch to the per-type validator. Unknown type or unparseable blob → skipped
  (200, echoing stored state), never 500.
- **Dispatch key space — content-type `model` string, one space only.** The registry is keyed by
  `element.content_type.model` (`"revealgateelement"`, `"markdoneelement"`, …), i.e. the
  `ELEMENT_MODELS` namespace — **not** the form/transfer keys the blob table lists for readability
  (`revealgate`, `reveal_gate`). Those three namespaces have been a recurring trap (see
  `NESTABLE_TYPE_KEYS` and its `_NESTABLE_FORM_KEY_ALIASES`); the registry does not add a fourth.
  **Questions are an `isinstance(obj, QuestionElement)` fallback checked *after* an exact-key miss** —
  they cannot be exact keys, since one behaviour covers ~10 concrete subclasses.
- **Concurrency:** `transaction.atomic()` → `get_or_create` → `select_for_update().get(...)` →
  per-key read-modify-write. This is the **only** concurrency-safe multi-element writer in the
  codebase and the reason for a single endpoint: element A's save must not clobber element B's key in
  the shared dict.
- **Order: validate BEFORE entering the atomic write block.** On REJECT / unknown type, read the
  echo with `.filter().first()` (echoing `{}` when absent) and return **without** `get_or_create` —
  otherwise a garbage POST from an author-previewer spawns an empty `UnitProgress` row, contradicting
  the care taken elsewhere that passive paths never create rows.
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

Mark-done keeps its existing no-JS form, repointed at the new endpoint. **Four content-pk sites move
to the join-row pk together — all of them, or the no-JS path breaks in two different ways:**

1. the hidden field `value="{{ el.pk }}"` → `value="{{ eid }}"` (`markdoneelement.html`);
2. the element `id="markdone-{{ el.pk }}"` → `id="markdone-{{ eid }}"`;
3. the form `action="{{ save_url }}#markdone-{{ el.pk }}"` → `…#markdone-{{ eid }}`;
4. the endpoint's redirect fragment `f"#markdone-{element.pk}"` — now already the join-row pk, since
   `element` *is* the join row.

Missing (1) makes the no-JS path silently write a key the read path never looks up — a tick that
appears to save and vanishes on reload. Missing (2)/(3) leaves the redirect fragment and the DOM `id`
in **different pk spaces**, so the post-save scroll lands nowhere. The no-JS form POST gets its own
test **including the anchor round-trip**, not only the JS path.

### Restore — gates & self-checks (client-side)

`build_lesson_context` (`courses/views.py:348`) puts an int-keyed `{element_pk: blob}` map into
context as `state`, for any authenticated viewer with `can_access_course`.

**The existing two-branch read is unchanged — this feature must not collapse it.** `views.py:352-360`
already does:

- **enrolled** → `UnitProgress.objects.get_or_create(...)`, and that row feeds `progress`,
  `seen_ids`, and `seen_count`. This `get_or_create` **stays**; removing it would break seen-tracking
  and completion.
- **authenticated but not enrolled** (author/teacher previewing) → `.filter().first()`, so a passive
  viewer does not spawn a row (the PR #136 lesson).

The state read **reuses whichever row is already in hand** — it adds no query and creates nothing of
its own. This is exactly today's `checklist` shape with `checklist` renamed to `state`; the rule is
"*the state read* never creates a row", **not** "no `get_or_create` on a GET".

Each participating leaf template emits its blob as **`data-state="{{ mine_json }}"`**. **Never
`data-element-id`** — that attribute stream is owned by `progress.js`'s IntersectionObserver
seen-tracker and must stay top-level-only.

**`mine_json` is serialized in Python, not the template — there is no JSON filter in this project.**
`ElementBase.render` hands leaves `mine_json = json.dumps(mine)` alongside `mine`. Writing
`data-state="{{ mine }}"` would render Python's `repr` (`{&#x27;open&#x27;: True}` — single quotes,
`True`), which `JSON.parse` rejects, and the throw lands inside the boot of the one element slice 1
exists to prove. `django.utils.html.json_script` is not an alternative: it emits a `<script>` tag, not
an attribute. Mark-done is no precedent here — it emits no `data-state` (below). Django's
autoescaping turns `"` into `&quot;` inside the attribute and the browser un-escapes it before
`dataset.state`, so `data-state="{{ mine_json }}"` is correct and safe; do **not** add `|safe`.

Each element's existing JS reads `data-state` on boot and reconstructs, then POSTs on change.

**Every restore must be defensively guarded — an unguarded throw fails CLOSED, not open.**
`reveal.js:9` sets `window.__revealBooted = true` **at parse time**, deliberately ("Setting this
eagerly, at parse time, is what lets that fallback see the engine is alive"). So a throw *during*
restore — a `JSON.parse` failure, a drifted shape like `{"shown": "3"}`, a missing key — leaves the
watchdog believing the engine booted, `reveal-armed` is never disarmed, and **content stays
permanently hidden with no working gate**. That is exactly the merge-gate violation this spec
forbids, reachable from one malformed blob. So each restore wraps parse + shape-check in a
`try`/`catch`, and on **any** failure restores nothing and leaves the widget fresh. This guard is
mandatory, not tidiness.

**Mark-done is the exception and emits no `data-state`.** It already restores server-side through the
`checked` context var (`{% if item.pk in checked %}` → a real `checked` attribute), which is what
makes its no-JS path correct, and `markdone.js`'s `persisted()` reads state back off the checkboxes
themselves. Adding `data-state` to it would be a second, redundant source of truth for the same
facts. "Each participating leaf emits `data-state`" means each leaf that restores **client-side**.

**The server keeps rendering everything fresh and visible; restore is client-side only.** This
preserves the no-JS invariant (*the server never hard-hides a step*) and avoids a second server-side
rendering path per element.

#### The shared cascade needs an explicit restore mode (slice 1's real work)

`libliRevealCascade` / `cascadeFrom` (`courses/static/courses/js/reveal.js`) is written for a
**click**, and replaying it on boot is **not** a drop-in. Concretely, it:

- calls `target.focus()` (`reveal.js:117`) — restoring gates on load would **yank focus and scroll
  the viewport** to the last restored gate, before the student has touched anything;
- mutates `scope.style.display = "block"` (`:113`) as a focus-enabling workaround;
- writes `tabindex="-1"` inside `firstRevealed()` / `focusTargetIn()` as a side effect of *resolving*
  a focus target — so suppressing only the terminal `focus()` still leaves pointless DOM writes on
  every restored gate;
- dispatches a bubbling `libli:reveal` per revealed node (`:85`);
- **returns early** when `scopeOf(triggerEl)` (`:14`) finds no `[data-tab-panel]` / `.slide`
  ancestor.

So the cascade takes an explicit restore mode — `cascadeFrom(trigger, {focus: false})` or equivalent
— that **skips the entire focus-target resolution block** (not merely the terminal `focus()` call,
which would leave the `tabindex` writes) **and the `display` mutation**, while a real click keeps
today's behaviour byte-for-byte. Restore ordering across multiple open gates in one scope must be
**document order**, so the cascade's "stop at the next gate" rule composes rather than fighting
itself.

**`libli:reveal` KEEPS firing on restore.** It is not a focus side effect — `reveal.js:82-84`
documents it as a *"bubbling contract shared with tabs.js/gallery.js: a gallery or other enhancer
inside newly-visible content needs to know it just became visible so it can re-measure (it was
previously `display:none`)."* A restored gate makes content visible for exactly the same reason a
clicked one does, so the listeners' need is identical; suppressing it would leave a gallery behind a
restored gate mis-measured. **This makes boot ordering load-bearing:** the gate restore must run
*after* `libliInitGallery` / `libliInitTabs` have bound their listeners, or the event fires into the
void. Pin the ordering explicitly and test it — a gallery behind a restored gate measures correctly
on load.

**This is the substance of slice 1, not a detail.** The claim that restore "runs inside the existing
boot in the same direction it already goes" is true of *visibility* only — focus, layout, and events
are all side effects a restore must not reproduce. Named tests: boot-restore moves neither focus nor
scroll; a real click still focuses; a gate with no `.slide`/`[data-tab-panel]` scope restores without
throwing.

**The fail-open watchdogs are untouched.** The arming `<script>` (`lesson_unit.html:5-29`), the
prepaint hide `<style>` (`:37-43` reveal, `:45-48` stepper — **plus a duplicate of the reveal
selectors in `core/static/core/css/app.css:961-962`**, which the reveal-gate DOM constraint also binds)
and the `DOMContentLoaded` boot-flag disarm (`__revealBooted`, `__stepperBooted`, `__fillGateBooted`)
stay exactly as they are. Restore runs **inside** the existing
boot and in the **same direction** it already goes — boot un-hides, restore un-hides more. A dead
script still disarms and shows everything. **This feature adds no new way to trap content
permanently hidden**, and that property is a merge gate.

Client save discipline (generalising `markdone.js`): `fetch` + `keepalive` + CSRF header (read from
the cookie — `CSRF_COOKIE_HTTPONLY` is unset, as `progress.js` relies on), and **no-op on an empty
save URL** (the editor preview resolves `{% url … as save_url %}` to `""` because `as` silences
`NoReverseMatch`; `fetch("")` would hit the current page).

**On 200, for `state`-carrying types (monotone + reversible): adopt the echoed state.** The returned
blob becomes last-known-persisted and the widget re-renders from it. Do **not** compare-and-revert —
the server normalizes (drops empty keys, prunes stale pks), so comparing would discard correct work
(see *Save endpoint → Response*).

**On non-200 / network error: revert only `reversible` state.** A `monotone` type (reveal gate,
fill/choose gate, stepper, guess-number) keeps its DOM as-is and is simply not marked persisted —
never rolled back. There is no un-cascade in `reveal.js`, and re-hiding earned content on a network
blip is the merge-gate violation this spec forbids.

**Questions (`fire-and-forget`) do neither.** `question.js` ignores the echo body and never touches
the DOM on failure — `check_answer` owns the UI. Adoption would require a client-side `rehydrate`;
reverting would wipe a visible answer. Both are forbidden.

### Restore — questions (server-side)

Questions restore differently, and this is the one place the design leans on an existing path rather
than adding one.

#### How a question answer reaches the server

**The client cannot compute the blob, and must not try.** `answer_to_json` (`quiz.py:67`) serializes
the output of `question.build_answer(request.POST)` — a **server-side, per-type parse**
(`check_answer`, `views.py:648`). Expecting `question.js` to produce `{"answer": …}` would mean
reimplementing ~10 `build_answer` variants in JavaScript, and they would drift from the Python on the
first schema change.

So question saves ride the same envelope but carry **raw submitted fields**, and the server parses:

```
POST …/u/<node_pk>/state/   {"element": <join_pk>, "fields": {"choice": ["3"], ...}}
```

The question validator (dispatched per *Save endpoint*) runs
`answer_to_json(question.build_answer(<fields>))` and stores `{"answer": …}`. `build_answer` takes a
querydict-like object, so the validator adapts the JSON field map (values are **lists**, mirroring
`QueryDict.getlist`) rather than the endpoint growing a second body format.

**An empty answer returns EMPTY, via `answer_is_empty` — the generic "empty state" rule does not
cover questions.** A blank question's blob is `{"answer": []}` / `{"answer": ""}`, never `{}`, so the
generic empty-blob check never fires. Without this, a student who hits Check on a blank input
persists an empty answer; on the next load the restore rule sets `feedback_for_pk` and re-marks it,
rendering a **wrong-verdict against a visibly blank input** — the same spurious-feedback class this
spec forbids two sections down. Use `courses/quiz.py:54 answer_is_empty`, the project's established
predicate for exactly this, already used by both other write paths (`views.py:1052`,
`views_manage.py:1169`). Negative test: Check with a blank input → **no key stored** → next load
renders fresh with no verdict.

`fields` and `state` are **mutually exclusive** on the envelope: gates/self-checks send `state` (a
blob the client owns), questions send `fields` (raw input the server parses). A body carrying both,
or `fields` for a non-question element, is a **400**.

**When does the client POST?** On **Check** only — `question.js`'s existing submit path, alongside
the `check_answer` request. Not on input/keystroke: mid-typing answers are noise, and `build_answer`
on a half-typed value is meaningless. This means an answer typed but never Checked is **not**
persisted, consistent with lesson-mode semantics today (nothing is recorded until you Check).

#### How saved state reaches the render

`render_element`'s question branch (`courses_extras.py:47-63`) already accepts exactly the
rehydration surface: `feedback_for_pk`, `selected_ids`, `submitted_values`, `mark_result`. **These
are tag parameters, not context reads** — and, critically, **the lesson template passes all four on
every render**: `_lesson_article.html:28` is

```
{% render_element el feedback_for_pk=feedback_for_pk selected_ids=selected_ids
                     submitted_values=submitted_values mark_result=mark_result %}
```

So **"the caller passed no explicit `feedback_for_pk`" is not a decidable condition** — the tag
cannot distinguish "omitted" from "passed as `None`". The rule must be per-element, not
per-invocation:

> Restore a question from `element_state` **iff** `mode == "lesson"` **and**
> `feedback_for_pk != element.pk` **and** a blob exists for `element.pk`.

`feedback_for_pk` names **the one element being live-checked**; every *other* element on that render
is a restore candidate. This matters because `check_answer`'s no-JS path (`views.py:673-682`)
re-renders the **whole lesson** with `feedback_for_pk=<checked element>.pk` — a single shared context
value. Under a naive "explicit args win" rule, checking one question would silently wipe the restored
state of every other answered question on the page. (If a sentinel is preferred over the pk
comparison, it must be a distinct `_UNSET` default — **never `None`**, which is a legitimate value.)

Then, for each restore candidate:

1. `answer = answer_from_json(question, blob["answer"])`
2. `mark_result = question.mark(answer)` — re-marked, never stored
3. `selected_ids, submitted_values = rehydrate(question, blob["answer"])`, then pass those plus
   `feedback_for_pk=element.pk`.

**Pass `rehydrate` the stored JSON (`blob["answer"]`), not the decoded `answer` from step 1.**
`rehydrate(question, latest_answer)` (`quiz.py:76`) is documented as taking the *stored* value, and
the quiz-resume precedent calls it that way (`views.py:915`). The two happen to be interchangeable for
every current type — which is exactly why picking the wrong one would go unnoticed until a type where
they diverge.

**All three calls run inside a `try`/`except` that falls back to rendering fresh.** This restore
executes inside `render_element` — **a template tag** — so an exception from `answer_from_json`,
`mark`, or `rehydrate` on a drifted blob (say a list where a ChoiceGrid now expects a dict, after an
author edits the question) **500s the entire lesson** for that student. The "malformed → treated as
absent, renders fresh, never a 500" rule is asserted for the whole feature but is only *implemented*
on the write path (validator exceptions → REJECT); this is its read-side half, on the surface where
it is hardest. On any exception: render fresh, pass **no** `feedback_for_pk`. Named test: a garbage
stored `answer` renders the question fresh with a 200.

Rules, each of which must be a test:

- **The live-checked element wins.** `check_answer` → `element_try` passes its own `mark_result` for
  `feedback_for_pk`'s element; that element is never restored over.
- **The no-JS whole-lesson re-render preserves every other element's restored state.** Named test —
  this is the case the naive rule breaks.
- **`mode="quiz"` never consults `element_state`.** Quiz rendering stays byte-identical.
- **`feedback_for_pk` is set only for elements that *have* saved state** — never blanket. The quiz
  page sets it for *every* element, and that is exactly what produced the literal `"None"` rendering
  in fresh inputs (`quiz-vs-lesson-consumption-divergence`, fixed with `|default_if_none:''`).
  Lessons must not reintroduce it.

**Known risk, to be re-verified during planning rather than assumed:** the quiz and lesson render
paths have diverged before and are a documented bug farm. The hypothesis that this generalises with
one change is *supported* by the shared signature but is **not proven**; slice 3 must verify it **per
type** before committing to the shape.

**The exact list slice 3 must verify — all 10 concrete `QuestionElement` subclasses:** Choice,
ShortText, ShortNumeric, FillBlank, DragFillBlank, MatchPair, DragToImage, ExtendedResponse,
**ChoiceGrid** (matrix), **MultiGrid** (multi-select grid). Do **not** take
`rollups._QUESTION_MODELS` (`rollups.py:25-34`) as the list — it holds **8** and its docstring calls
them "the roadmap's '9 types'", omitting ChoiceGrid and MultiGrid. Those last two matter most: their
payloads are the positional-list `""`-sentinel and list-of-lists shapes that needed surgical fixes in
their own builds.

**`answer_from_json` is not a true inverse of `answer_to_json` — verify per type.**
`answer_to_json` (`quiz.py:67-73`) converts `tuple → list` and `set → sorted list`, but
`answer_from_json` (`:85-91`) only restores the **set** case (for `ChoiceQuestionElement`) and returns
everything else unchanged — so a tuple-shaped answer round-trips back as a **list**. Whether any
`mark()` cares is precisely what per-type verification must establish. The codecs are proven **for
the quiz-resume path**, which is not the same claim as proven for every shape.

**Performance:** re-marking runs one `mark()` per persisted question per lesson load, and choice
marking re-queries `choices.all()` (a known double-query, already on the tidy-up backlog).
`build_lesson_context` already does per-type prefetching; the prefetch must cover the re-mark path or
a lesson with many answered questions becomes N+1.

### Reset

**There is no course-root `ContentNode`, so "whole course" needs its own route.** `ContentNode.Kind`
(`models.py:169-205`) is `part` / `chapter` / `section` / `unit` — **no course kind**. Top-level nodes
carry `parent=None` and `build_outline` assembles `roots` as a *list* (`rollups.py:108-124`). A course
therefore has no single node to name, and a lone `<int:node_pk>` route cannot express the
course-level reset the Purpose promises. Two routes:

```python
path("courses/<slug:slug>/reset/", views.progress_reset, name="progress_reset_course"),
path("courses/<slug:slug>/reset/<int:node_pk>/", views.progress_reset, name="progress_reset"),
```

**`progress_reset` is `@login_required`, GET + POST — a confirmation interstitial, not a bare POST.**
(`@login_required` matches `markdone_save`'s existing decorators and is required, not cosmetic: the
body is `UnitProgress.objects.filter(student=request.user, …)`, and an `AnonymousUser` is not a valid
FK value — the anonymous case must be rejected by the decorator, not left to `can_access_course`'s
`accessible_courses` helper.) `node_pk=None` targets the whole course.

- **GET** renders a confirmation page: the blast-radius count, what is *not* affected, a Cancel link,
  and a form whose POST performs the reset. GET has **no side effects** and creates nothing.
- **POST** (`+ CSRF`) performs the reset and redirects.

This resolves two problems at once and is why the earlier "POST-only, never GET" rule is dropped:

1. **The count needs a server round-trip.** A client-side `confirm()` cannot know "3 lessons" without
   asking the server. A server-rendered interstitial computes it inline — no count endpoint, no
   fetch, no JS.
2. **The no-JS path would otherwise have no confirmation at all.** Reset is the student's *protection*
   against automatic persistence; shipping it as a one-click, no-undo, no-confirm form for no-JS
   students would make the safety valve the hazard. The interstitial confirms for **everyone**,
   identically, with zero JS. (An enhancer may later collapse it to an inline `confirm()`, but the
   interstitial is the floor, not a fallback.)

- **Resolve the node:** `get_node_or_404(node_pk, slug, require_unit=False)` when `node_pk` is given.
  **This is not optional.** `can_access_course` authorizes against the course named by `slug`, but
  nothing otherwise ties `node_pk` to that course — a `node_pk` from a *different* course would
  resolve its subtree and wipe the student's state there, gated only by access to the slug's course.
  The existing helper enforces exactly this pairing (`courses/access.py`, used by every other
  node-scoped view). `require_unit=False` because reset targets parts/chapters/sections too. Test: a
  node from a foreign course **404s**.
- **Resolve the target units:**
  - `node_pk is None` → `units_in_order(course)` — the existing helper (`rollups.py:58`) already
    covers exactly this case.
  - otherwise → **new helper `units_under(node)` in `rollups.py`**. `_walk_preorder(course)`
    (`:37`) walks from `parent_id=None` over a whole course and cannot start from an arbitrary node.
    `units_under` is a plain parent_id-grouped descent from `node`, returning a **set**, inclusive if
    `node` is itself a unit. The pre-order subtlety `_walk_preorder`'s docstring warns about (sibling
    `order` is only locally monotonic, so a flat scan is not pre-order) is **irrelevant here** —
    reset does not care about order. Do not cargo-cult the ordering machinery into it.
- `UnitProgress.objects.filter(student=request.user, unit__in=<target units>).update(element_state={})`
  — one query. `student=request.user` always, so it is **IDOR-safe against other students by
  construction** (matching `course_results`); the cross-*course* hole is closed by `get_node_or_404`
  above, not by this filter. No read-modify-write: we clear, we do not merge.
- **`.update()` deliberately bypasses `UnitProgress.save()`**, so it fires neither `auto_now` on
  `updated_at` nor the `completed ⇒ completed_at` invariant. Both are fine and intended: reset does
  not touch `completed`, and nothing reads `updated_at` for practice state. Stated so a later reader
  sees a choice rather than an oversight.
- Quiz units in the target set are **expected** to hold `element_state == {}` (the Interactive
  palette is quiz-hidden — `unit_is_quiz`, `views_manage.py:692`), but that is a **UI gate, not a data
  constraint**, and reset does not depend on it: it clears whatever is there, which is correct either
  way. Do not rely on the emptiness elsewhere.
- Guarded by `can_access_course`.
- **Redirect:** a hidden `next` field on the form, validated with
  `url_has_allowed_host_and_scheme(next, allowed_hosts={request.get_host()}, require_https=request.is_secure())`,
  falling back to the course outline when absent or rejected. **Not `HTTP_REFERER`** — that is an
  open-redirect on a destructive POST and silently empty under a `Referrer-Policy` or a privacy
  extension. Test: a foreign `next` falls back rather than redirecting off-site.

**Two hard invariants, each pinned by its own named test:**

1. Reset **never** touches `seen_element_ids` or `completed`. Completion is scroll-driven (an
   IntersectionObserver, not an act of work) and feeds `build_progress_matrix` → teacher analytics. A
   student revising must not silently drag down what their teacher sees, and un-completing would be
   self-undoing anyway (it re-completes on the next scroll).
2. Reset **never** touches `QuizSubmission` / `QuestionResponse` / `Attempt`. Graded assessment
   history is not the student's to erase.

**UI.** A "Start fresh" control on the lesson page, a reset control per node in the outline (adapting
automatically to whichever nodes the course's structure preset actually has — Flat / Chapters / Parts
/ Full), and one course-level control using the no-`node_pk` route. The confirmation names the blast
radius rather than being vague:

> Start fresh? This clears your answers and ticks in **3 lessons**. Your quiz results are not
> affected.

**The count is "lessons in the target set with non-empty `element_state`" — not "lessons in the
subtree".** Reset only affects lessons that actually hold work; telling a student it clears 14
lessons when 3 have anything is exactly the vagueness this spec refuses elsewhere, and it makes a
harmless reset sound destructive. It is also cheaper: one
`UnitProgress.objects.filter(student=…, unit__in=…).exclude(element_state={}).count()`.

**It is computed once, in the GET interstitial** — not during the outline render. The outline already
walks the tree exactly once (`build_outline`, `rollups.py:108`); calling `units_under` per node there
would regress it to an N-walk, and `required_total` is not a substitute (it counts only *obligatory*
lessons). Because the outline's reset control is a **plain link to the interstitial**, the outline
paint runs **zero** extra queries — the count is computed only when a student actually asks to reset.

**Count zero → the interstitial says so and offers no destructive action** ("Nothing to clear here").
This also disposes of the per-node control on **quiz unit rows**: the outline contains quiz units,
whose `element_state` is empty, so their link leads to a "nothing to clear" page rather than a button
that silently does nothing. Suppressing the control on quiz rows is *also* acceptable; what is not
acceptable is a live-looking button that clears nothing next to copy saying quiz results are safe.

Styled per the existing `.btn--danger` / danger-zone pattern (`sso-names-and-danger-zone-status`), and
verified light + dark with screenshots. Copy is pluralized (`ngettext`) on the lesson count.

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
      → POST …/u/<node_pk>/state/  {element: <join_pk>, state: {...}}   [gates/self-checks]
                                   {element: <join_pk>, fields: {...}}  [questions, on Check]
      → can_access_course → element belongs to node? → validator (by content_type.model,
        isinstance(QuestionElement) fallback → build_answer + answer_to_json)
      → atomic: get_or_create UnitProgress → select_for_update → merge key → save
      → 200 {element, state: <BLOB NOW STORED>}
           → JS ADOPTS the echo as last-known-persisted and re-renders from it.
             (Do NOT compare-and-revert: the server normalizes — drops empty keys,
              prunes stale pks — and the question path echoes a blob the client
              never sent. Comparing would discard correct work.)
        (non-200 / network error)
           → reversible type → REVERT DOM to last-known-persisted
           → monotone type   → KEEP DOM, do not mark persisted  (never re-hide)
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
| `state` and `fields` both present, or `fields` on a non-question | **400** |
| Unknown content type for state | Skipped (REJECT) → **200 echoing the stored blob** (never 500) |
| Malformed / unparseable blob on **save** | Validator returns **REJECT** → stored key **untouched** → 200 echoing it → client **adopts** the echo (self-correcting) |
| Validator raises | Caught → mapped to **REJECT** (never 500) |
| Malformed blob already **stored** (schema drift) | Treated as **absent** → element renders fresh |
| Stale item/choice pk inside a blob | Ignored on read, pruned on next write (mark-done precedent). The echo carries the pruned blob; the client **adopts** it — it must not read the prune as a rejection. |
| Empty / default state | Validator returns **EMPTY** → key **dropped**, not stored as `{}` |
| Student unticks their last mark-done item | Sends `{"items": []}` → **EMPTY** → key dropped → echoes `{}` → client **adopts** `{}`. A comparing client would re-tick the box; adoption is what makes this correct. |
| Concurrent saves, two elements | `select_for_update` + per-key merge → neither clobbers |
| Save fails (network / 4xx / 5xx), **reversible** type | JS **reverts** the DOM to last-known-persisted |
| Save fails (network / 4xx / 5xx), **monotone** type | JS **keeps** the DOM (revealed stays revealed) and does not mark it persisted. Never re-hide — there is no un-cascade, and re-hiding earned content is the merge-gate violation. |
| Save fails, **question** (fire-and-forget) | DOM **untouched**; the answer is simply not persisted and re-persists on the next Check. Never revert — the answer is visible on screen and `check_answer` already succeeded. |
| Drifted blob **stored**, JS type | Restore's `try`/`catch` fires → restore nothing, widget fresh. **Mandatory:** `__revealBooted` is set at parse time, so an unguarded throw leaves `reveal-armed` armed and content permanently hidden (fails closed). |
| Drifted blob **stored**, question | Read-side `try`/`catch` around `answer_from_json`/`mark`/`rehydrate` → render fresh, no `feedback_for_pk`. Without it a drifted blob **500s the whole lesson** — the restore runs inside a template tag. |
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
`{% render_element el %}` emits `el.pk`.

**Scope the `assertNumQueries` guard to the five LEAF sites — a lesson with gates and no container.**
It cannot police the two container sites: `TabsElement.render` calls `join_row()` twice (once for
`eid`, once inside `resolved_tabs()`), and this spec keeps the `resolved_*` call. So an identical
`self.elements.order_by("pk").first()` still runs per container after the fix, and a total-count
assertion cannot distinguish the surviving query from a re-introduced `eid` one. Pin the containers'
`eid` provenance **by identity instead** — assert the rendered `eid` equals the passed join row's pk
with the container's own `join_row` patched to raise, so a re-derivation fails loudly.

**Editor preview inertness — test the real mechanism.** The preview renders **real join rows**
(`_preview.html:16`), so `eid` is non-zero there; what makes it inert is the absent `slug`/`node_pk`
→ empty `save_url`. Test *that*: render the actual editor preview as the course author, assert
`save_url` is empty and that no `UnitProgress` row is created or written. **Do not** test an
`element=None` path — it does not occur in the preview.

**Do NOT test multi-placement state isolation.** One content object in two join rows is unsupported
project-wide (`join_row()`'s docstring; it would break `resolved_tabs` and the export walk too).
Pinning it here would assert behaviour the surrounding code contradicts.

**Migration.** Re-key content pk → join-row pk **and wrap the bare list under `"items"`**; orphaned
key dropped; nested element re-keyed; `{}` and absent state; a row whose element was deleted.
**Backward:** unwraps `"items"` to a bare list, and **drops a `revealgate` blob** rather than writing
it into `checklist_state` (its own named test).

**Endpoint.** Forged element → 400; `state`+`fields` both present → 400; `fields` on a non-question →
400; garbage blob → **200 echoing the pre-existing stored blob** (not the rejected input); **a
rejected blob creates no `UnitProgress` row** (validate-before-`get_or_create`); empty state drops the
key; int-coercion of string pks; previewer persists; **concurrent two-element save does not clobber**
(the `select_for_update` path); `can_access_course` denies a stranger; **a quiz `node_pk` 404s**; **a
foreign-course `node_pk` 404s**; anonymous → redirected by `@login_required`.

**Fail-closed guards (the merge gate).** A **drifted stored blob** must never brick a lesson:
server-side, a garbage `answer` renders the question fresh with a **200** (not a 500 from inside the
template tag); client-side, a malformed `data-state` leaves the widget fresh **and `reveal-armed`
disarmed** — assert content is *visible*, since `__revealBooted` is set at parse time and an
unguarded throw would leave it hidden forever. Also: `data-state` round-trips through
`JSON.parse` (guards the `repr`-vs-JSON serializer bug).

**Reveal-gate DOM.** The gate's attributes live on the existing `<button data-reveal-gate>`; a gate
still hides its following siblings **pre-boot** (guards the three direct-child selectors against an
introduced wrapper).

**Reset.** Subtree walk across **all four structure presets** (Flat / Chapters / Parts / Full); reset
at unit / section / chapter; **course-level reset via the no-`node_pk` route**; **IDOR** (student A
cannot reset student B — assert via `student=request.user`, not a hand-passed pk); **a `node_pk` from
a foreign course 404s** (the cross-course hole `student=request.user` does *not* close — it is closed
by `get_node_or_404`); **GET is side-effect-free** (renders the interstitial, writes nothing, creates
no `UnitProgress` row); **POST performs and redirects**; a **foreign `next` falls back** to the
outline rather than redirecting off-site; the confirm count equals lessons with **non-empty** state
(not all lessons in the subtree); **count == 0 offers no destructive action**; and the two hard
invariants as their own **named** tests (`test_reset_does_not_touch_completion`,
`test_reset_does_not_touch_graded_records`).

**Questions.** The live-checked element's own `mark_result` wins over its stored state;
**`check_answer`'s no-JS whole-lesson re-render preserves every *other* answered element's restored
state** (the case a naive "explicit args win" rule breaks — named test); `mode="quiz"` renders
byte-identically (assert against a pre-change snapshot); `feedback_for_pk` set **only** for elements
with state (assert the negative: a fresh input renders `value=""`, never `"None"`); re-marking picks
up an author's corrected answer key; a question POSTs **only on Check**, not on input.

**Reveal-gate restore (slice 1).** Boot-restore moves **neither focus nor scroll**; a real click
still focuses; a gate outside any `.slide` / `[data-tab-panel]` scope restores without throwing;
multiple open gates in one scope restore in document order.

**e2e (the real gap).** Per element: drive the **real gesture** → reload → assert restored. Never
`page.evaluate` — that scar is well-earned (`e2e-must-drive-real-ui`). Plus: reset → reload → gone;
and a **fail-open** e2e (block the JS, assert content is visible, not trapped).

**Existing code and tests this breaks — in slice 1's scope, not CI-red surprises:**

- **`markdone.js` is rewritten, not "generalised".** It posts `{element, items}` and reads a
  `{"element", "items"}` response; its `last` is a per-checkbox `{value: bool}` map, not a blob.
  Moving to `{element, state: {items: […]}}` plus blob-level adoption is a rewrite of its
  save/reconcile core.
- **`courses/tests/test_render_seam.py:12` and `:19`** call `el.render(checklist={}, slug="x",
  node_pk=1)` directly — the very "no `TypeError`" break this spec guards, but in *test* code, so the
  7-override sweep must include it.
- **The route rename** breaks `courses:markdone_save` reverses and
  `tests/test_e2e_markdone.py`'s `"/markdone/" in r.url` response matcher.

**Regression.** Full non-e2e suite green; `test_po_catalog_clean` fuzzy-free; `ruff check` **and**
`ruff format --check`; `makemigrations --check`; `manage check`.

**Execution notes.** Isolate a per-worktree test DB (`DATABASE_URL=…/libli_<slug>`; the role has
CREATEDB) — concurrent worktrees collide on `test_libli`. Run the heavy suite with `-n auto`
(serial exceeds a subagent's 600s watchdog). e2e needs an explicit `-m e2e` (else `addopts = -q -m
'not e2e'` deselects the file and pytest exits 5 **looking like success**); run focused e2e
foreground only, never backgrounded.

## Open questions to resolve in planning

1. **Does the question rehydration generalise?** (Slice 3.) Verify per type against the 10-subclass
   list above; do not assume. Include the `answer_to_json`/`answer_from_json` tuple asymmetry.
2. **Prefetch shape for the re-mark path** — confirm `build_lesson_context`'s per-type prefetch covers
   `mark()` for every question type, or the N+1 lands on lessons with many answered questions.

*(Resolved during spec review, previously open: `data-state` has no existing consumer — a repo-wide
grep over `courses/static/` and `templates/` for `data-state` / `dataset.state` returns nothing, so
the generic attribute name is free.)*
