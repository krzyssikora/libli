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

Types below are named by **form key for readability only**; the validator registry is keyed by the
content-type `model` string (`markdoneelement`, `revealgateelement`, …) — see *Save endpoint →
Dispatch key space*. Do not use this column as the registry key.

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
- `state` — **this leaf's own blob**, i.e. `mine` (already resolved; leaves do not index the map).
- `checked` — **retained for mark-done only**, derived as `{int(i) for i in mine.get("items", ())}`.
  Keeping it means `markdoneelement.html`'s two `{% if item.pk in checked %}` sites are unchanged and
  stay O(1); the int-coercion is mandatory (JSON round-trips ints fine, but the no-JS `getlist` path
  yields strings — the same trap that silently dropped every tick in the mark-done build).

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

**2. The 7 overrides that currently swallow the context must take the real signature.**
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

**And the newly-persisting leaves gain `eid` + `save_url` for the first time.**
`revealgateelement.html` — **slice 1's proof element** — plus `stepperelement.html` and
`markdoneelement.html` currently have **no `eid` and no `save_url` at all`**. Slice 1 must add both to
the reveal gate; do not assume the gate templates already resemble the fill-gate family.

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

- **Body:** JSON `{"element": <join_row_pk>, "state": {...}}` for gates/self-checks, or
  `{"element": …, "fields": {...}}` for questions (see *Restore — questions*). The two are
  **mutually exclusive**; both present, or `fields` on a non-question element, → **400**.
  Form-encoded fallback retained for mark-done only → 302 + `#markdone-<eid>`.
- **Response — the body is authoritative, not the status code:**
  `JsonResponse({"element": …, "state": <the blob now stored for this element>})`. **On a skip or a
  validator rejection it echoes the *currently stored* blob** (or `{}` if none) — never the rejected
  input. That makes reconciliation self-correcting: the client compares what came back to what it
  sent and reverts on any difference, so a silently-rejected save cannot leave the DOM ahead of the
  server (see *Error handling*).
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

Each participating leaf template emits its blob as **`data-state='{...}'`** (JSON, auto-escaped by
the template engine). **Never `data-element-id`** — that attribute stream is owned by `progress.js`'s
IntersectionObserver seen-tracker and must stay top-level-only.

Each element's existing JS reads `data-state` on boot and reconstructs, then POSTs on change.

**The server keeps rendering everything fresh and visible; restore is client-side only.** This
preserves the no-JS invariant (*the server never hard-hides a step*) and avoids a second server-side
rendering path per element.

#### The shared cascade needs an explicit restore mode (slice 1's real work)

`libliRevealCascade` / `cascadeFrom` (`courses/static/courses/js/reveal.js`) is written for a
**click**, and replaying it on boot is **not** a drop-in. Concretely, it:

- calls `target.focus()` (`reveal.js:117`) — restoring gates on load would **yank focus and scroll
  the viewport** to the last restored gate, before the student has touched anything;
- mutates `scope.style.display = "block"` (`:113`) as a focus-enabling workaround;
- dispatches a bubbling `libli:reveal` per revealed node (`:85`), which other listeners may act on;
- **returns early** when `scopeOf(triggerEl)` (`:14`) finds no `[data-tab-panel]` / `.slide`
  ancestor.

So the cascade takes an explicit restore mode — `cascadeFrom(trigger, {focus: false})` or equivalent
— that **suppresses focus movement and the `display` mutation** on boot, while a real click keeps
today's behaviour byte-for-byte. Restore ordering across multiple open gates in one scope must be
**document order**, so the cascade's "stop at the next gate" rule composes rather than fighting
itself.

**This is the substance of slice 1, not a detail.** The claim that restore "runs inside the existing
boot in the same direction it already goes" is true of *visibility* only — focus, layout, and events
are all side effects a restore must not reproduce. Named tests: boot-restore moves neither focus nor
scroll; a real click still focuses; a gate with no `.slide`/`[data-tab-panel]` scope restores without
throwing.

**The fail-open watchdogs are untouched.** The prepaint arm (`reveal-armed` / `stepper-armed` inline
`<style>` in `lesson_unit.html:9-25`) and the `DOMContentLoaded` boot-flag disarm (`__revealBooted`,
`__stepperBooted`, `__fillGateBooted`) stay exactly as they are. Restore runs **inside** the existing
boot and in the **same direction** it already goes — boot un-hides, restore un-hides more. A dead
script still disarms and shows everything. **This feature adds no new way to trap content
permanently hidden**, and that property is a merge gate.

Client save discipline (generalising `markdone.js`): `fetch` + `keepalive` + CSRF header (read from
the cookie — `CSRF_COOKIE_HTTPONLY` is unset, as `progress.js` relies on), and **no-op on an empty
save URL** (the editor preview resolves `{% url … as save_url %}` to `""` because `as` silences
`NoReverseMatch`; `fetch("")` would hit the current page).

**Reconcile against the echoed state, not the status code.** Revert the DOM to last-known-persisted
on a non-200 or a network error **and** whenever the returned `state` differs from what was sent — a
validator rejection is a 200, so status alone would let the DOM drift ahead of the server and lose the
work silently on the next reload.

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
3. pass `feedback_for_pk=element.pk`, plus `selected_ids`/`submitted_values` via `rehydrate`.

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

`progress_reset` is **POST-only** (`@require_POST` + CSRF; never GET — it is destructive) and takes
`node_pk=None` for the course-level form.

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
  — one query. `student=request.user` always, so it is **IDOR-safe by construction** (matching
  `course_results`). No read-modify-write: we clear, we do not merge.
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

**Where it is computed matters.** Do **not** call `units_under` per node during the outline render —
the outline already walks the tree exactly once (`build_outline`, `rollups.py:108`) and an N-walk
would regress it. (`required_total` is not a drop-in substitute: it counts only *obligatory* lessons.)
Compute the count **on demand** — the confirm step, not the outline paint — so a page with 40 nodes
runs zero extra queries until a student actually clicks reset. If the count must appear before the
click, fold it into `build_outline`'s single walk rather than adding a second.

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
           → JS reconciles against the ECHOED state (the authority):
               echoed == sent → keep DOM
               echoed != sent → REVERT DOM  (covers a silently-rejected blob, which is ALSO 200)
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
| `state` and `fields` both present, or `fields` on a non-question | **400** |
| Unknown content type for state | Skipped → **200 echoing the stored blob** (never 500) |
| Malformed / unparseable blob on **save** | Validator rejects → key untouched → **200 echoing the stored blob** → client reverts on the mismatch |
| Malformed blob already **stored** (schema drift) | Treated as **absent** → element renders fresh |
| Stale item/choice pk inside a blob | Ignored on read, pruned on next write (mark-done precedent) |
| Empty / default state | Key **dropped**, not stored as `{}` |
| Concurrent saves, two elements | `select_for_update` + per-key merge → neither clobbers |
| Save fails (network / 4xx / 5xx) | JS **reverts** the DOM to last-known-persisted |
| Save "succeeds" but the blob was rejected | **200 + echoed state ≠ sent state → JS reverts.** The status code alone is *not* the revert trigger — a rejected blob returns 200, so keying revert on non-200 would leave the student's DOM ahead of the server and silently lose the work on next reload. |
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
`{% render_element el %}` emits `el.pk`. Assert the **seven** self-lookups are gone via
`assertNumQueries` on a lesson containing gates *and* a tabs container (the container's `eid` lookup
is one of the seven), so the per-render query cannot silently return.

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
400; garbage blob → **200 echoing the pre-existing stored blob** (not the rejected input); empty state
drops the key; int-coercion of string pks; previewer persists; **concurrent two-element save does not
clobber** (the `select_for_update` path); `can_access_course` denies a stranger.

**Reset.** Subtree walk across **all four structure presets** (Flat / Chapters / Parts / Full); reset
at unit / section / chapter; **course-level reset via the no-`node_pk` route**; **IDOR** (student A
cannot reset student B — assert via `student=request.user`, not a hand-passed pk); a **foreign `next`
falls back** to the outline rather than redirecting off-site; the confirm count equals lessons with
**non-empty** state (not all lessons in the subtree); and the two hard invariants as their own
**named** tests (`test_reset_does_not_touch_completion`,
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
