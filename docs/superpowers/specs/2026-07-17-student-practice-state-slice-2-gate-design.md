# Student practice state — slice 2: the reveal gate

> **SCOPE: the plain "Show more" reveal gate, alone.** It becomes the **first client-restoring
> element** in the codebase. No other element joins the mechanism: Fill in & confirm, Choose &
> confirm, Step-by-step, Switch grid, Fill-in table and Guess the number all stay off it, and get
> their own spec once the gate has proved the client path.
>
> **Slice 1** (the substrate: `UnitProgress.element_state`, migration 0050, the nine-signature render
> seam, `element_state_save`, `progress_reset`) shipped as **PR #139** and is on `origin/master`
> (merge `d0ad6af`). This spec builds on it and **corrects three of its predecessor's predictions**
> that the shipped code has since overtaken — see *What slice 1 already paid for*.
>
> **Reading rule.** The fenced `⚠️ SLICE 2 RECORD` section of
> `docs/superpowers/specs/2026-07-16-student-practice-state-design.md` (lines 724-988) is a
> **record, not a spec**. Its review-corrected constraints are binding *input* to this spec; its
> predictions about what slice 2 would have to build are **not**, and several are stale. Where this
> spec and the record disagree, **this spec wins**, and every such disagreement is called out
> explicitly rather than silently resolved.

## Purpose

Make a student's reveal-gate work **survive a page reload**.

A student who unlocks content behind a "Show more" gate and reloads is re-hidden today: `reveal.js`
persists nothing, so all gate state lives in DOM classes and evaporates. This is the exact hazard
that made Guess-the-number drop its `<form>` in PR #137 — an unarmed Enter reloaded the page and a
guess element sitting behind a gate lost the gate too.

Slice 1 built the whole persistence substrate but deliberately brought **no client-restoring
element** onto it: mark-done restores *server-side* through the `checked` context var, so it needed
no `data-state`, no client parse, no cascade replay. This slice builds that missing half and proves
it on the gate.

**Why the gate, and why alone.** It was slice 1's original proof element and was moved out precisely
because it is the **most entangled element in the codebase**, not the simplest — six of nine
spec-review CRITICALs were the gate tangling with something else, and none of them was visible from
its blob (`{"open": true}`, about as simple as a blob gets). The blob was never the hard part. What
is hard: prefix-closure across a general-sibling CSS combinator, per-scope grouping, three element
families emitting the same barrier attribute, a fourth DOM shape none of the selectors match, and a
boot-order constraint with a fail-closed failure mode. Those are the substrate. Every later
self-check inherits them.

### Non-goals

- **No new element type.** `ELEMENT_MODELS` does not change, so the `len(ELEMENT_MODELS)` /
  `ELEMENT_MODELS[-1]` count-asserts in `tests/test_transfer_schema.py` and
  `tests/test_models_multigrid.py` are not triggered.
- **No migration.** The field exists (slice 1). `makemigrations --check` must stay clean.
- **No second element on the mechanism.** Not even the stepper, which is base-rendered and monotone
  and would look cheap. It is not this slice's proof.
- **No new user-visible strings**, therefore no `makemessages` pass and no fuzzy-flag cleanup.
- **No teacher-facing surface, no analytics, no graded-quiz change.** Inherited from slice 1.
- **No fix for the reveal-gate x two-column mis-scoping.** Pre-existing on the click path; see
  *Explicitly not fixed*.

## What slice 1 already paid for

**This section exists because the record predicts work that is already done.** An implementer
following the record would either redo it or, worse, "fix" a seam that is already correct. All three
were verified against `origin/master` (`d0ad6af`).

**1. The blob already reaches all five state-carrying overriding leaves — the contract exists and is
`_state_context`.**

The record (line 441) says *"The helper is introduced in slice 1 … and slice 2 is what makes the five
overrides splat it in."* Slice 1 did both. `ElementBase._state_context` (`courses/models.py:340`)
returns `{el, eid, mine, slug, node_pk}`, and **each of the five state-carrying leaves** already
splats it:

| Leaf | `render()` at | Body |
|---|---|---|
| FillGateElement | `models.py:660` | `ctx = self._state_context(...)` → `render_to_string(tpl, ctx)` |
| SwitchGateElement | `models.py:683` | same |
| GuessNumberElement | `models.py:712` | same |
| SwitchGridElement | `models.py:739` | same |
| FillTableElement | `models.py:922` | same |

So `mine` reaches them **today**, and this slice's `mine_json` will reach them the moment it is added
to the helper — for free, with no per-leaf edit.

**"Every override" would be an overstatement — four others hand-build their context and never touch
the helper**, and a future leaf author could copy that pattern: `TableElement.render` (`:820`),
`GalleryElement.render` (`:1002`), `TabsElement.render` (`:1148`) and `TwoColumnElement.render`
(`:1256`). **The counts, stated precisely because two different ones are in circulation:**
`courses/models.py` has **ten** `render(self, *, element=None, state=None, slug=None, node_pk=None)`
definitions (`:363, 660, 683, 712, 739, 820, 922, 1002, 1148, 1256`), of which **six** reach
`_state_context` (`:365, 663, 686, 715, 742, 925`) and **four** hand-build. Slice 1's "nine-signature
seam" counts the nine *overrides* — i.e. all ten minus `ElementBase.render` (`:363`), which is the
helper's own caller, not an override. So: **ten signatures / six reach it**, or equivalently **nine
overrides / five reach it**. Do not mix the two framings; 6 + 4 = 10, and 5 + 4 = 9.
The four hand-builders are correct as they stand — Table and Gallery persist nothing (static
display; gallery slide position is an explicit non-goal), and the two containers deliberately
re-inject the whole map for their children rather than resolving a blob — but nothing (no test, no
ABC) *enforces* the helper.

**Consequence: the record's silent-failure warning is designed out for the five leaves the later
slices use — but only for those five.** The record (lines 443-445) warns that *"Failure mode if an
override forgets it: silent — an undefined `mine_json` renders `data-state=""` → `JSON.parse("")`
throws → the restore try/catch swallows it → the element never restores."* For the five, that mode is
now unreachable: forgetting `mine_json` would mean not splatting the helper, which is not something
those five can silently half-do. A **new** leaf that hand-builds its dict in the Table/Gallery style
could still hit it. `mine_json` goes in the helper for this reason, not merely for tidiness.

**2. `slug` and `node_pk` already reach those five templates too.**

The record (lines 499-508) says forwarding them is *"SLICE 2's job … Slice 2 must not forget it,
because the failure is silent"* — a template doing `{% url … as save_url %}` resolves `save_url` to
`""` (the `as` form swallows `NoReverseMatch`) and every save no-ops with no error. `_state_context`
returns both, and all five splat it, so this is **already paid**. It remains true and load-bearing
that a template must actually *resolve* the URL; it is no longer true that the context is missing.

**3. `RevealGateElement` is base-rendered.**

`models.py:640` declares `label`, `elements`, and **no `render()` override**. So the gate is rendered
by `ElementBase.render` (`models.py:363`), which builds its context from `_state_context` — meaning
the gate picks up `mine_json` through the helper regardless. Point 1 is what makes this slice's
helper change *also* correct for the other five; point 3 is why the gate itself never needed it.

## Architecture / components

Five changes. The save endpoint, the storage field, the migration, and `build_lesson_context`'s read
are **untouched** — slice 1 built them generically and they already do the right thing for the gate.

### 1. `courses/state.py` — register the gate's validator

The endpoint calls `state_svc.validate_state(element, obj, payload)` at `views.py:702`, and the
dispatch on `element.content_type.model` lives in `state.py:71` (inside `validate_state`, `:69`), so
registering the key **is** the entire server-side wiring. No endpoint change.

```python
def _val_revealgate(element, obj, payload):
    """{"open": True} -- monotone.

    A false/absent `open` is a well-formed "nothing to restore" -> EMPTY (drop the key),
    never REJECT (which would preserve a stale key on a well-formed request).
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"open": True} if payload.get("open") else EMPTY


# Keyed by content_type.model (the ELEMENT_MODELS namespace) -- NOT the form key
# ("markdone") and NOT the transfer key ("mark_done"). Those three namespaces have
# been a recurring trap; the registry does not add a fourth.
#   ^ EXISTING comment at state.py:61-63 -- it STAYS. Only the one new key is added.
VALIDATORS = {
    "markdoneelement": _val_markdone,
    "revealgateelement": _val_revealgate,   # NEW -- the only line this slice adds here
}
```

**The docstring states its rule inline rather than saying "see the spec"**, matching
`_val_markdone`'s (`"-- intersected with THIS element's items."`). A shipped source file must not
defer to a design doc the reader may not have. **And the namespace comment above the dict is not
optional context — it is the one note preventing exactly the mistake `"revealgateelement"` invites**
(the form key is `reveal_gate`, the transfer key `reveal_gate`; only the content-type `model` string
is correct here). An implementer copying the snippet must not drop it.

**The EMPTY case is non-obvious and therefore stated.** The gate is monotone, so the client never
sends a close — but `{"open": false}`, or a payload with no `open` key at all, is **EMPTY, not
REJECT**. It is a well-formed statement of "nothing to restore", and dropping the key is exactly
right; REJECT would preserve a stale key on a well-formed request. This distinction is the single
most dangerous conflation in the feature (slice 1's `state.py` module docstring says so): EMPTY
deletes, REJECT preserves, and they are distinct truthy sentinels for that reason.

**Extra keys are normalized away, not rejected.** The validator returns a *constructed*
`{"open": True}` rather than echoing the payload, so the stored blob's shape is owned by the server.
`{"open": true, "junk": 1}` stores `{"open": True}`.

**No re-verification.** Consistent with slice 1's established rule (`state.py` docstring): validators
check shape and referential validity only. `{"open": true}` is trusted. The gate has no server-side
correctness notion to re-derive — a click is the whole gesture — and the DOM is already
client-forgeable (any student can reveal gated content with devtools today; `reveal.js` has no server
round-trip at all). A forged `open` harms nobody but its author, and Reset undoes it.

**No bounds needed.** The record mandates per-string length and entry-count caps for free-text and
list-valued blobs. The gate's blob is a single constructed boolean key — unbounded input cannot grow
it, because the validator never copies input into the stored value. The caps bind the *later*
free-text slices (`filltable` cells, `fillgate` blanks), not this one.

### 2. `ElementBase._state_context` — add `mine_json`

**Two lines, not one — `courses/models.py` does not import `json` today.** Its imports are `re`,
`secrets`, `Decimal` and Django modules; omitting the import is a `NameError` on the first render of
any element.

```python
import json                        # NEW — models.py has no json import today

...
"mine_json": json.dumps(mine),     # in _state_context's returned dict
```

**Change list: `models.py:341` and `models.py:344-345` — the docstring needs TWO edits, not one.**
`_state_context`'s docstring opens (`:341`) with `"""{el, eid, mine, slug, node_pk} -- the leaf
contract.` — **that enumeration, not the NOT-note, is the canonical statement of what the helper
returns.** Fixing only the NOT-note leaves the header advertising five keys for a function that
returns six. So:

1. `:341` — the header enumeration gains `mine_json`: `{el, eid, mine, mine_json, slug, node_pk}`.
2. `:344-345` — the `NOT mine_json: … Slice 2 adds it with the first client-restoring leaf` note is
   replaced. **Verbatim, because every other comment this spec mandates comes with its exact text —
   and leaving this one to invention is how the header drifted in the first place:**

   ```python
   """{el, eid, mine, mine_json, slug, node_pk} -- the leaf contract.

   `mine_json` is json.dumps(mine), for a leaf to emit as data-state. Serialized
   HERE, in Python: there is no JSON filter in this project, and `{{ mine }}` would
   render Python's repr ({'open': True}), which JSON.parse rejects.

   Every leaf gets it whether or not it reads one -- the gate is the only consumer
   today. A leaf that hand-builds its own render_to_string context instead of
   splatting this (the Table/Gallery pattern) forfeits it silently.

   NOT `checked`: mark-done-only, added by ElementBase.render below.

   `eid == 0` means "a content object with no join row" (transient/mid-create),
   NOT "editor preview" -- the preview passes REAL join rows and is made inert
   by its context lacking slug/node_pk (so `{% url ... as save_url %}` -> "").
   """
   ```

This is the same stale-comment hazard §5b calls non-cosmetic for `editor.html:142`, and it bites the
exact reader §1 worries about: a future leaf author hand-building their own dict, who would never
learn from the header that `mine_json` is on offer.

**Serialized in Python, not the template — there is no JSON filter in this project.** Writing
`data-state="{{ mine }}"` would render Python's `repr` (`{&#x27;open&#x27;: True}` — single quotes,
capitalized `True`), which `JSON.parse` rejects, and the throw would land inside the boot of the one
element this slice exists to prove. `django.utils.html.json_script` is not an alternative: it emits a
`<script>` tag, not an attribute.

**Autoescaping is correct here and `|safe` must NOT be added.** Django turns `"` into `&quot;` inside
the attribute and the browser un-escapes it before `dataset.state`, so `data-state="{{ mine_json }}"`
round-trips and is safe. This is asserted by a test (see *Testing*), not assumed.

**Every element render pays one `json.dumps(mine)`; only the gate consumes it in this slice.** The
cost is not confined to the five overrides — `ElementBase.render` (`:365`) also calls
`_state_context`, so every base-rendered type (text, spoiler, callout, stepper, slide-break,
mark-done, …) carries an unused `mine_json` too: roughly twenty types per lesson, not five.

That is intended, and it is not dead code — the gate is base-rendered, so the helper's first consumer
ships in this slice. `json.dumps({})` on an already-resolved dict is negligible against the
`render_to_string` it sits inside, and the alternative (computing it only in the branch that needs it)
re-opens the per-leaf drift that point 1 above closes. An unused context variable on twenty types is
the price of the seam being uniform.

### 3. The ambient context key: `state` → `element_state`

`render_element` (`courses/templatetags/courses_extras.py:22`, `takes_context=True`) reads the
practice-state map off the ambient template context. It reads it under the key `state` — the most
generic word available — and **that key already collides**: `views_review.py:98` binds `state` to
`review_svc.submission_review_state(submission)`, a `{total, reviewed, remaining, fully_reviewed}`
dict consumed by `review_submission.html:75,78`.

**The collision is inert today and fails safe, but silently.** `review_submission.html` renders no
elements (`render_element` appears in exactly five templates: `tabselement.html`,
`twocolumnelement.html`, `manage/editor/_preview.html`, `_lesson_article.html`, `_quiz_article.html`
— that is not one of them). If it ever did, `_state_context` would evaluate
`{"total": 3, …}.get(<eid>)` → `None` → not a dict → `mine = {}` → every element renders fresh, with
no error anywhere. Slice 2 widens how many elements depend on that read, which is why it is fixed
now rather than after.

**The change — four production lines and two test lines:**

| Site | Change |
|---|---|
| `courses/views.py:402` | `"state": state` → `"element_state": state` |
| `courses/templatetags/courses_extras.py:67` (generic branch) | `state=context.get("state")` → `state=context.get("element_state")` |
| `courses/models.py:1157` (`TabsElement.render` re-inject) | `"state": state` → `"element_state": state` |
| `courses/models.py:1265` (`TwoColumnElement.render` re-inject) | same |
| `courses/tests/test_markdone_render.py:169` | `build_lesson_context(unit, student)["state"]` → `["element_state"]` |
| `courses/tests/test_markdone_render.py:177` | same |

**The two test lines are mandatory, not optional tidying.** Both live in
`test_build_lesson_context_state_map_excludes_drifted_entries` and read the context key directly;
without the rename they raise `KeyError` and go red. An implementer who trusts a "no test churn"
claim would read two red tests as evidence they broke something — or "fix" them by restoring the
`"state"` key, silently reintroducing the collision this change exists to remove.

**Not every `["state"]` in the tests moves.** `courses/tests/test_element_state_endpoint.py:57,71,81,93`
read `r.json()["state"]` — that is the **wire** format (the endpoint's JSON response body), which this
change does not touch. Only the two `build_lesson_context(...)["state"]` reads are context-key reads.

**The `render(state=…)` kwarg does NOT change**, and the asymmetry is deliberate. Keyword arguments
are scoped to the call and cannot collide with a template context; the ambient key is effectively a
global and can. The nine render signatures shipped in slice 1 and re-churning them would risk exactly
the `TypeError`-every-lesson break that plan-review *and* code-review both caught on the mark-done
build — for zero collision benefit. The kwarg's callers in
`courses/tests/test_render_seam.py:47,59,66,78,110,148,160,173` are therefore **unaffected**.

**Do NOT rename `views_review.py`'s `state`.** Renaming the ambient key removes the collision at its
source; renaming the review page's kills only today's instance and leaves `render_element` reading a
generic global that has already collided once before the feature is even finished.

**`slug` and `node_pk` are deliberately NOT renamed, and this is a decision, not an oversight.**
`render_element` reads **three** ambient keys, not one (`courses_extras.py:67-69`), and the
collision-class argument above would apply verbatim to `slug` — which is at least as generic a word as
`state`. They stay, for two reasons:

- **The rename's warrant is a demonstrated collision, not symmetry.** `state` has one
  (`views_review.py:98`). `slug` has none: every ambient binding reachable by an element render means
  the same thing — `views.py:403` binds `node.course.slug`, and the other element-rendering contexts
  bind it to nothing at all (`_lesson_article.html`, `_quiz_article.html` and `_preview.html` all use
  `course.slug` / `unit.course.slug` inline rather than a bare `slug`). `node_pk` is not a generic
  word in the first place. Renaming on symmetry alone is the prophylactic churn this section already
  declines for the nine `render(state=…)` kwargs.
- **Their absence is a load-bearing mechanism, and it survives either way.** The editor preview is
  inert *because* its context lacks `slug`/`node_pk` (→ `save_url == ""`). That works identically
  under any key name, so a rename would buy nothing here either.

**One subtlety that makes the exemption safe to verify:** the only template reading a bare `slug` /
`node_pk` is `markdoneelement.html:2` (and now `revealgateelement.html`), and it reads them from the
**leaf** context that `_state_context` builds from the *kwarg* — **not** from the ambient page
context. So the ambient `slug`/`node_pk` keys are read by `render_element` and nothing else, and
renaming them later stays a mechanical, contained change if a collision ever does appear.

**The naming rule, restated for the whole seam:** `element_state` = the ambient `{element_pk: blob}`
map (context key, and the `UnitProgress` field it comes from — same name, same data, deliberately);
`state` = that same map as a Python kwarg/local; `mine` = one leaf's own blob. After this change no
template context anywhere carries a bare `state` from this feature, and the word belongs to the
review page outright.

### 4. `templates/courses/elements/revealgateelement.html` — three attributes on the existing button

```django
{% load i18n %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
<button type="button" class="reveal-gate" data-reveal-gate hidden
        data-element-pk="{{ eid }}" data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
  ... unchanged ...
</button>
```

**No wrapper element may be introduced, and this is the constraint most likely to be violated by a
well-meaning refactor.** The gate is a bare `<button>` rendered directly inside `.lesson-block__body`,
and **three files pin that exact direct-child chain across two matched DOM shapes**:

| Site | Top-level chain | Nested-in-tab chain |
|---|---|---|
| `reveal.js:31-37` (`isGateWrapper`) | `:scope > .lesson-block__body > [data-reveal-gate]` | `:scope > [data-reveal-gate]` |
| `lesson_unit.html:39-40` (prepaint `<style>`) | `.reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block:not(.reveal-shown)` | `.reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child:not(.reveal-shown)` |
| `core/static/core/css/app.css:972-973` (`@media print`, opened at `:971`) | same chain **inverted** — `display: revert !important`; plus `[data-reveal-gate] { display: none !important }` at `:976` | mirrored |

A natural-looking wrapper `<div>` breaks all three at once, in three different ways, **none of which
fails loudly**: the prepaint guard stops hiding following blocks (**gated content leaks on load**),
the cascade stops detecting gate boundaries (**one click reveals the whole slide**), and the print
rule stops reverting (**a printed lesson silently loses its gated content**). Two further `app.css`
rules depend on the same shape: `:966` (`.reveal-gate[hidden] { display: none !important }`) and
`:967` (`.lesson-block[hidden], .tabs__child[hidden] { display: none !important }` — the latter is
what makes `hideWrapper`'s `gateWrap.hidden = true` actually take effect).

**Attribute choices:**

- **`data-element-pk`** carries the join-row pk for the POST body. **It is the ESTABLISHED name for
  exactly this concept — do not invent a new one.** Five elements already emit `data-element-pk="{{ eid }}"`
  and read it back in JS: `fillgateelement.html:8` (`fillgate.js:59`), `filltableelement.html:7`
  (`filltable.js:45`), switchgate (`courses_extras.py:266`, `switchgate.js:64`), guessnumber
  (`courses_extras.py:294`, `guessnumber.js:17`) and switchgrid (`courses_extras.py:357`,
  `switchgrid.js:76`) — i.e. **precisely the elements that follow the gate onto this mechanism**. An
  earlier draft of this spec invented `data-eid`; that would have been a sixth name for a concept that
  already has one, and the fourth entry in exactly the namespace trap `state.py:61-63` warns about
  ("Those three namespaces have been a recurring trap; the registry does not add a fourth"). It also
  buys the `pk == 0` convention for free: `fillgateelement.html:5` already documents "treats pk 0
  (unsaved preview) as a no-op", which is what `save()`'s `if (!eid) return;` mirrors.
- **`data-element-pk` is NOT `data-element-id`, and the distinction is load-bearing.** The `-id`
  stream is owned by `progress.js`'s IntersectionObserver seen-tracker (`progress.js:44,52`) and must
  stay top-level-only; a leaf emitting it would mis-mark an element as seen and cause premature
  auto-completion. The five elements above already coexist with that rule, which is the evidence
  `-pk` is safe here.
- **`data-state`** carries the blob. Verified free repo-wide (no `data-state` / `dataset.state`
  consumer exists in `courses/static/` or `templates/`).
- **`data-state-url`** is emitted **unconditionally**, mirroring `markdoneelement.html:3`'s
  `data-markdone-url="{{ save_url }}"`. In the editor preview `{% url … as save_url %}` resolves to
  `""` and the JS no-ops — the same mechanism, tested the same way. `data-state-url` is verified
  unused repo-wide; `data-state` likewise (no `dataset.state` consumer exists).
- **`data-state-url`, not `data-revealgate-url`.** All seven eventual state-carrying types POST to
  the one endpoint (`element_state_save`); a per-type URL attribute name would mint seven names for
  one thing.

`{% url … %}` on line 2 mirrors `markdoneelement.html:2` exactly.

### 5. `courses/static/courses/js/reveal.js` — restore mode, the restore pass, and save

#### 5a. `cascadeFrom` gains a `focus` option

`cascadeFrom` (`:70`) is written for a **click**, and replaying it on boot is not a drop-in. It
`target.focus()`es (`:117`) — restoring on load would **yank focus and scroll the viewport** to the
last restored gate before the student has touched anything; it mutates `scope.style.display = "block"`
(`:113`) as a focus-enabling workaround; and `firstRevealed()` (`:44`) / `focusTargetIn()` (`:57`)
write `tabindex="-1"` as a side effect of *resolving* a focus target, so suppressing only the terminal
`focus()` would still leave pointless DOM writes on every restored gate.

```js
var focus = opts.focus !== false;
...
if (hideWrapper) { ... }     // unchanged
if (!focus) return;          // NEW: skips focus-target resolution ENTIRELY
// existing focus block, unchanged
```

The early `return` sits **after** the `hideWrapper` block and **before** focus-target resolution, so
`{focus: false}` skips `focusTargetIn`, `firstRevealed` (and its `tabindex` writes), the
`display: contents → block` mutation, and the terminal `focus()` **as one unit**. A real click passes
no `focus`, so `opts.focus !== false` is `true` and today's behaviour is **byte-for-byte unchanged**.

**`hideWrapper` is preserved per-family, not replaced.** The two gate families differ on it: the plain
gate self-consumes (`{hideWrapper: true}`, `:121`), while fill/switch gates keep their answered Q&A
visible (`{hideWrapper: false}`, `fillgate.js:73`, `switchgate.js:80`). Restore **adds** focus
suppression to the option, it does not replace it: the plain gate restores with
`{hideWrapper: true, focus: false}`. Dropping `hideWrapper` would leave a dead "Show more" button
sitting above already-revealed content.

#### 5a-bis. What `hideWrapper: true` takes with it at boot — two accepted consequences

**`hideWrapper` hides more than a button, and making it fire at boot makes that durable.** For a
top-level gate, `ownWrapper` resolves to the whole `<section>` at `_lesson_article.html:31`:

```django
<section data-element-id="{{ el.pk }}" class="lesson-block">
  <div class="lesson-block__body">{% render_element el ... %}</div>
  {% include "notes/_block_notes.html" with element=el ... %}
</section>
```

`app.css:967`'s `.lesson-block[hidden] { display: none !important }` then removes **everything** in
that section. Both consequences below already occur on today's **click** path; what this slice changes
is that they now recur on **every subsequent load** instead of resetting on reload. Neither is a
merge-gate violation — no *gated* content is trapped; the content behind the gate is revealed, which
is the point — but both are stated rather than left to be discovered.

**1. The gate block's own notes anchor disappears with it.** The section carries
`{% include "notes/_block_notes.html" %}` → `<aside class="block-notes" data-anchor-element="…">`. A
student who anchors a note to a gate block and then opens the gate loses the **in-lesson handle** on
every later load. **Accepted:** the note itself is not lost — it remains readable and editable through
the *Tags & notes* hub ([[tags-and-notes-hub-status]]), which is a per-course notes index precisely
for notes whose anchor is not on screen. Annotating a "Show more" button is also a marginal gesture,
and the alternative — narrowing `hideWrapper`'s target on the restore path only — would make restore
diverge from the click path it is meant to replay, which is a worse trade than a note that lives in
the hub.

**2. The gate's element can never be marked *seen* on a restore load.** The same section is
`progress.js`'s IntersectionObserver target (`data-element-id`, observed via
`progress.js:52`); a `display: none` element never intersects. `progress.js` loads at
`lesson_unit.html:58`, **before** reveal.js (`:76`), but that ordering does not help — the observer
callback fires after layout, by which time restore has already set `hidden`.

**Accepted, and the reason it is narrow:** the gate is observed and marked seen on the load where the
student **clicks** it (it is visible until the click), and `seen_element_ids` is cumulative — so the
normal path is unaffected. The residual case is a student whose `seen` POST failed while the `state`
POST landed (two independent requests; `seen` is debounced): that element is then never re-observed,
`seen_count` can never reach `element_count`, and scroll-driven auto-completion is permanently
blocked for that unit. This is the same failure class slice 1's `break_ct_id` exclusion already
handles for slide-breaks ("without this, `element_count` could never equal `seen_count`"). It is
**not** fixed here: the manual *Mark as done* control (`courses:complete`, `_lesson_article.html:17`)
remains the escape hatch, and pre-emptively excluding gate elements from `element_count` would change
completion semantics for every lesson to fix a two-failure coincidence. Added to the tidy-up backlog.

#### 5b. `restoreGates` — a separate, un-exported pass, called from the IIFE body

```js
  // ORDER IS LOAD-BEARING, and it is the only thing guarding this: init MUST run first
  // so that even an uncaught throw inside restore leaves every gate un-hidden and
  // click-bound -- the student re-earns the content instead of being locked out of it.
  // There is no test for this (nothing in restore can throw once the null-scope discard
  // is in place); this comment is the guard. Do not reorder these two lines.
  initRevealGates(document);   // existing :146 -- un-hides buttons, binds clicks
  restoreGates(document);      // NEW, next line
```

That comment is given **verbatim on purpose**: §5c calls the ordering an untestable invariant whose
failure mode is content trapped hidden, and says "the comment is what stands between it and a
reviewer". A guard that *is* a comment must ship with its exact words, for the same reason §2 gives
the `_state_context` docstring verbatim.

**Terminology, stated once because the record and the existing comments are loose about it.**
`reveal.js` is loaded `defer` (`lesson_unit.html:76`), so the IIFE does **not** run at parse time: a
deferred script executes *after* the document is fully parsed and immediately *before*
`DOMContentLoaded`. The load-bearing fact is unaffected and is what matters: the IIFE — and therefore
`window.__revealBooted = true` (`:9`) — runs **before** `DOMContentLoaded`, which is when the prepaint
watchdog (`lesson_unit.html:10-14`) checks the flag. This spec says "IIFE body" where the record says
"parse time".

**`reveal.js:7-8`'s own comment is wrong on the same fact and IS corrected by this slice — change
list: `reveal.js:7-8`.** It currently reads *"Setting this eagerly, at parse time, is what lets that
fallback see the engine is alive."* This slice does not get to apply the `editor.html:142` rule
selectively: that comment is mandatory to fix *because* a stale comment is what a future reader cites
to delete a guard — and this one is in **the file this slice rewrites**, about **the very flag §5c's
fail-closed analysis turns on**, and it is the load-bearing half of the hoisting trap below (the flag
is set regardless of whether anything else worked). Replace with the accurate mechanism: the IIFE runs
after parsing and before `DOMContentLoaded`, which is what lets the watchdog see the engine is alive.

`restoreGates` is **never assigned to `window`**. `editor.js:77` calls
`window.libliInitRevealGates(preview)` after every fragment swap; keeping restore off the exported
surface makes **re-cascading** the editor's preview gates structurally impossible rather than merely
unlikely.

**`window`-absence covers re-runs only — restore DOES run once over the editor page on initial load,
and the spec must not claim otherwise.** `templates/courses/manage/editor/editor.html:144` loads
`reveal.js` **unconditionally** (no `{% if %}` guard, unlike `lesson_unit.html:76`), so the IIFE — and
with it `restoreGates(document)` — executes over the editor DOM, preview pane included. What makes
that pass inert is **the data, not the export surface**:

- every preview gate renders `data-state="{}"` (the editor context carries no `element_state`), so
  `storedOpen` returns `false` and the walk stops at it;
- a preview gate outside any `.slide` / `[data-tab-panel]` is additionally skipped by the null-scope
  guard.

**The null-scope guard does not cover the tab-nested preview case.** `tabselement.html:17` emits
`[data-tab-panel]`, so a gate nested in a tabs element *inside the preview* has a **non-null** scope
and reaches the `storedOpen` check — where `data-state="{}"` is the **sole** guard. That path is
tested explicitly (see *Testing*), because it is the one where a single mistake in the `mine_json`
default would start cascading an author's preview on every editor load.

**Consequence: an existing in-repo comment is now false and MUST be corrected in this slice.**
`templates/courses/manage/editor/editor.html:142` (in the `{% comment %}` block at `:139-143`) reads:

> *"the cascade is inert here (no .slide/[data-tab-panel] scope in the preview)."*

The parenthetical is wrong for exactly the reason above — a tabs element in the preview **does** emit
`[data-tab-panel]`. Leaving it is not cosmetic: this design makes a comment the *primary* guard for an
untestable invariant (§5c's call-site ordering), so a stale comment asserting a path does not exist is
precisely what a future reader would cite to delete the `data-state="{}"` guard this section calls
**sole**. Correct it to say the preview's inertness rests on `data-state="{}"` — and, for top-level
gates only, the absent scope. **Change list: `editor.html:139-143`.**

It must **not** be a per-button `initOne` concern: per-button init cannot express the ordering rule
below, and the editor re-run must not re-cascade.

**It must run in the IIFE body, not from a `DOMContentLoaded` handler — but not for the reason the
record gives.** The record's rationale is that `DOMContentLoaded` lands "after first paint", so the
restore would visibly pop content in and destroy the prepaint `<style>`'s no-flash property. **That
does not survive the `defer`**: the IIFE already runs after parsing, and there is no guaranteed paint
between the last deferred script and the `DOMContentLoaded` event that follows it — while a paint can
occur before *either*. The two placements are microseconds apart, and the no-flash property the
prepaint `<style>` provides is unaffected by the choice. **A restore repaint is possible under both
placements; it is accepted and not tested for.**

The two real reasons, both structural:

- **Ordering.** The IIFE body is the only place that can guarantee restore runs strictly *after*
  `initRevealGates` (see 5c). A `DOMContentLoaded` handler would also run after it, but the guarantee
  would then rest on listener-registration order rather than on two adjacent statements.
- **Encapsulation.** Keeping it a local call keeps `restoreGates` off `window` (below).

The **gallery/tabs listener ordering** the `libli:reveal` contract needs is satisfied independently
and needs no new mechanism: `lesson_unit.html` loads gallery (`:73`) → tabs (`:75`) → reveal (`:76`),
all `defer`, so they execute in document order, each binding its listeners in its own init before
reveal.js's IIFE runs.

#### 5c. Ordering is the structural guard — and the record's reasoning needs correcting here

**The record's fail-closed argument is half right, and the wrong half matters.** It says (lines
762-770) that a throw during restore *"leaves the watchdog believing the engine booted, `reveal-armed`
is never disarmed, and content stays permanently hidden with no working gate."*

`reveal-armed` is **never** removed on a healthy page. `lesson_unit.html:10-14` strips it inside a
`DOMContentLoaded` handler, and the full condition at `:11` is a three-way OR, not the single flag a
loose reading suggests:

```
!window.__revealBooted{% if has_fill_gate %} || !window.__fillGateBooted{% endif %}{% if has_switch_gate %} || !window.__switchGateBooted{% endif %}
```

The extra flags do not change any argument here: on a healthy page all present flags are set, so the
class stays; and on the hoisting-trap page below, `__revealBooted` is set at `:9` **regardless** of
whether anything else worked, which is exactly what makes that trap silent. `reveal.js:9` sets it when
the IIFE runs — which, per the terminology note above, is **before** `DOMContentLoaded`, so the check
always sees it. So **armed is the normal,
steady state** — it *is* the hiding mechanism, not a pre-boot phase to be exited. "Restore throws →
`reveal-armed` stays armed" describes every healthy page load too, and is not by itself a failure.

**The real hazard is narrower and entirely about order.** Armed CSS is only a trap when combined with
gates that cannot be clicked — i.e. a throw landing **before** `initOne` un-hides the buttons
(`:130`) and binds their click handlers (`:131`). Then the student has hidden content and no way to
earn it.

So: **run `restoreGates` strictly after `initRevealGates`.** Even a totally uncaught restore throw
then leaves every gate live and clickable — the student re-earns the content. It fails **fresh**, not
closed.

**The ordering is a comment-guarded invariant, not a tested one, and that is stated rather than
papered over.** Once the per-gate `try`/`catch` below is in place there is no *reachable* throw left
to write a test around, so a test asserting "restore runs after init" could only be a source-grep —
which this spec rules out as vacuous. The call site therefore carries a comment saying why the order
is load-bearing, and the per-gate catch below — which **is** falsifiable — is the primary guard. A
future edit hoisting `restoreGates` above `initRevealGates` would not go red; the comment is what
stands between it and a reviewer.

**Two `try`/`catch` layers, at different scopes, for different failures:**

**(1) Blob parse — inside `storedOpen`:**

```js
function storedOpen(btn) {
  try {
    var raw = btn.dataset.state;
    if (!raw) return false;
    var blob = JSON.parse(raw);
    return !!(blob && blob.open === true);
  } catch (e) {
    return false;   // drifted blob -> this gate simply stays live
  }
}
```

`blob.open === true` is a strict shape-check, not a truthiness test: a drifted `{"open": "yes"}` is
treated as absent rather than honoured.

**(2) The per-gate walk body — because `storedOpen`'s catch guards `JSON.parse` and NOTHING else.**
Throws from `ownWrapper`, `isGateWrapper`, `gate.matches` or `cascadeFrom` are not parse failures and
would propagate out of the IIFE, aborting the walk mid-way: gates already cascaded stay cascaded,
every **later scope** is silently skipped, and the resulting DOM is neither restored nor fresh. So
each gate's body is wrapped, and **a throw `break`s that scope**:

```js
try {
  // wrapper / family / storedOpen checks, then cascadeFrom
} catch (e) {
  break;   // unknown state for this gate -> restore nothing further IN THIS SCOPE
}
```

**`break`, not `continue`, and the reason is prefix-closure.** A throw means this gate's state is
*unknown*; continuing past it could restore a later gate whose prefix is not closed — the exact leak
5d exists to prevent. Stopping the scope is the conservative reading, and it degrades to "the student
re-earns from here", which is the whole fail-fresh posture. Other scopes are unaffected: the blast
radius of one bad gate is **its own scope, and no further**.

This is what makes "restore nothing on failure" true at the level it is claimed. Without (2), that
claim would hold for parse failures only.

#### 5d. The walk — two selectors, per-scope, prefix-closed

**Two selectors, because barriers are not restorables.** `[data-reveal-gate]` is emitted by **three**
element families, and both `reveal.js`'s boundary test (`:31-37`) and the prepaint CSS treat all three
as gates:

| Family | Emits | Restorable in this slice? |
|---|---|---|
| Show more | `revealgateelement.html:2` — `<button class="reveal-gate" data-reveal-gate hidden>` | **yes** |
| Fill in & confirm | `fillgateelement.html:2` — `<div class="fillgate" data-reveal-gate data-fillgate>` | no — no validator, can never be stored open |
| Choose & confirm | `courses_extras.py:265-266` (inside the `format_html(` at `:264`) — `<div class="switchgate" data-reveal-gate data-switchgate>` | no — same |

- **Barriers** (what stops the walk): `[data-reveal-gate]` — all three.
- **Restorables** (what may be cascaded): `button.reveal-gate[data-reveal-gate]` — the plain gate only.

**A fill/switch gate therefore always stops the walk, and that is correct, not a limitation:** the
student has not answered it. Without the split the leak is trivially reachable by ordinary authoring
one gate family over — an author inserts a *Fill in & confirm* above a Show-more the student had
opened; the fill-gate is not in the walk, so it cannot stop it; `cascadeFrom` stamps `.reveal-shown`
past the plain gate; the student sees content they never re-earned while the fill-gate's own content
stays hidden.

**The walk is GROUP-then-walk: one bucket per scope, an inner loop per bucket.** The enumeration,
the grouping, and both loop headers are given explicitly, because a flat single loop over all gates
— which recomputes `scopeOf` per iteration and lets one `break` abort every remaining scope — is
**exactly the wrong implementation this section rules out**, and a loop body shown without its header
reads like one.

```js
// RESTORABLE REPLACES initRevealGates's inline `sel` (reveal.js:139), which holds this
// exact literal today. ONE definition of "what a plain gate is", read by both init and
// restore -- two copies could drift, and the failure would be silent (a gate that is
// bound but never restored, or vice versa).
//
// PLACEMENT IS LOAD-BEARING: these two statements MUST be assigned ABOVE initRevealGates's
// definition -- and unconditionally above the `initRevealGates(document)` CALL at :146.
// `var` hoists the DECLARATION but not the ASSIGNMENT, and this refactor turns a
// function-local `var sel` (re-evaluated per call) into a module-level one read by a
// function that is INVOKED at parse-end. See the hazard note below.
var BARRIER    = "[data-reveal-gate]";                   // all three families
var RESTORABLE = "button.reveal-gate[data-reveal-gate]"; // the plain gate only

function restoreGates(root) {
  // `ctx`, NOT `scope`: in this file "scope" means scopeOf()'s return (a .slide /
  // [data-tab-panel]) -- see reveal.js:11-16 -- and BOTH meanings coexist here.
  // (initRevealGates:138 gets away with `var scope = root || document` because it has
  // no per-gate scope to confuse it; this function does.)
  //
  // NO self-match branch, deliberately. initRevealGates:140, initTabs and
  // initMarkDone:92 each pair querySelectorAll with `scope.matches && scope.matches(sel)`
  // because their `root` may itself BE the target node. This function is document-only
  // and never exported (see 5b), so `root` can never be a gate. Do not "fix" it back in.
  var ctx = root || document;

  // 1. ENUMERATE every barrier, in document order (querySelectorAll guarantees it).
  var gates = Array.prototype.slice.call(ctx.querySelectorAll(BARRIER));

  // 2. GROUP by scopeOf. Parallel arrays, not a Map: this file is ES5-idiomatic
  //    (var, function, Array.prototype.forEach.call) and must stay so.
  //    Each gate lands in EXACTLY ONE bucket -- scopeOf returns one node (or null) --
  //    so buckets partition `gates`; a gate can never be walked twice.
  //    Null-scope gates are DROPPED HERE and never bucketed (see (b)).
  var scopes = [], buckets = [];
  gates.forEach(function (gate) {
    var scope = scopeOf(gate);
    if (!scope) return;                                  // (b) null-scope: never bucketed
    var i = scopes.indexOf(scope);
    if (i === -1) { scopes.push(scope); buckets.push([gate]); }
    else { buckets[i].push(gate); }
  });

  // 3. WALK each bucket independently. `break` ends ONLY this bucket's loop;
  //    every other scope is untouched, which is the per-scope rule.
  buckets.forEach(function (bucket, bi) {
    var scope = scopes[bi];
    for (var j = 0; j < bucket.length; j++) {
      var gate = bucket[j];
      try {
        if (!isGateWrapper(ownWrapper(gate, scope), scope)) continue;  // (a) mis-scoped
        if (!gate.matches(RESTORABLE)) break;            // fill/switch gate: a real barrier
        if (!storedOpen(gate)) break;                    // closed gate: prefix-closure stops here
        cascadeFrom(gate, { hideWrapper: true, focus: false });
      } catch (e) {
        break;                                           // unknown state: stop THIS scope only (5c)
      }
    }
  });
}
```

**The shared-constant refactor introduces its own fail-closed trap — the one thing 5c claims to
design out — so its placement is a requirement, not style.** Hoisting `sel` out of `initRevealGates`
(M4's tidy-up) means a module-level `var` is now read by a function that is *invoked* at `:146`. `var`
hoists the declaration but **not** the assignment, so if `var RESTORABLE = "…"` were written *below*
that call, `RESTORABLE` would be `undefined` at use — **and nothing would throw**:
`document.matches` is undefined, so `scope.matches && scope.matches(RESTORABLE)` short-circuits
harmlessly; and `document.querySelectorAll(RESTORABLE)` — i.e. `querySelectorAll(undefined)` —
stringifies its argument to the type selector `"undefined"`, returning an **empty NodeList**.
(The identifier is `RESTORABLE`, not `sel`: the refactor above **removes** `sel` from `:139-141`. A
stale name here, in the one passage arguing that stale names get cited by future readers, would be
its own small joke.) No button is un-hidden, no click is bound — yet
`window.__revealBooted = true` was already set at `:9`, so the watchdog never disarms `reveal-armed`
and **every gated block on the page is trapped hidden, with no console error**. Both constants are
therefore assigned at the top of the IIFE, above `initRevealGates`'s definition.

**`continue` and `break` both scope to the inner `for`, and the difference is load-bearing:**
`continue` (the mis-scoped case) means *"this gate gates nothing here — go to the next gate in this
same scope"*; `break` (a barrier, a closed gate, or a throw) means *"stop restoring in this scope"*.
Neither ever crosses a bucket. Under a flat loop `break` would silently discard every later scope's
stored work — the failure this design exists to avoid.

**Prefix-closure is the correctness rule.** The stored set of open gates is **not guaranteed
prefix-closed**, and restoring a gate whose upstream gate is still closed reveals content the upstream
gate should be hiding. The prepaint selector uses a **general** sibling combinator (`~`), so
`cascadeFrom(gate2)` stamps `.reveal-shown` on blocks that are also after gate1 — making them visible
while gate1 is still closed — and `hideWrapper: true` then removes gate2 from the flow entirely. The
student sees a live closed gate1, a hidden middle, and fully-revealed content past a gate2 that is no
longer on screen.

**This is reached by ordinary authoring, not tampering:** a student opens gate2; the author later
inserts a gate *before* it, or reorders blocks in the builder. Stored-open gates behind a stop are
**ignored for this render and left in storage** — the student re-earns them, and a later reorder may
make them valid again.

**The rule is PER-SCOPE, not global.** A cascade never crosses
`scopeOf(btn) = btn.closest("[data-tab-panel], .slide")` (`:14-16`), so gates in different scopes are
causally independent and must not veto each other. A single global document-order walk with a global
stop is **wrong** and silently discards stored work. Three ordinary shapes break it: a slideshow
lesson (slide-breaks → multiple `.slide` scopes); `tabselement.html:17`, which emits one
`[data-tab-panel]` **per tab**; and `reveal_gate` being in `NESTABLE_TYPE_KEYS` (`builder.py:46`), so
a gate nested in a tab panel *precedes*, in document order, a top-level gate in the enclosing `.slide`
while sharing no scope with it.

**Do NOT restate this as "never restore a gate whose wrapper is not currently visible."** That is a
different rule and it is also wrong: `tabs.js:101` sets the `hidden` **attribute** on every inactive
panel from its own `initTabs(document)` IIFE call, and `lesson_unit.html` loads tabs.js (`:75`)
**before** reveal.js (`:76`) — so at restore time every gate outside the default-active tab is inside
a hidden panel and would never restore.

##### (a) The `isGateWrapper` check must come FIRST — and it binds all three families

**This is a correction to the record, derived during this design and not present in it.**

The record (lines 561-566) frames the two-column skip as being about restoring a *stored-open column
gate*, and places the rule with the restorables. The sharper case is a **fill-gate in a column**:
under the record's ordering it is a barrier, so it would `break` the walk and **veto every stored-open
top-level gate later in that slide** — silently discarding stored work, which is the hazard the
Purpose exists to fix.

It must not, and the CSS says why. `twocolumnelement.html:10-14` emits **neither** `[data-tab-panel]`
nor `.tabs__child` nor `.lesson-block__body`; the chain is
`.slide > .lesson-block > .lesson-block__body > .el--twocolumn > .twocolumn__column > .twocolumn__child > [data-reveal-gate]`.
The prepaint `:has(> .lesson-block__body > [data-reveal-gate])` therefore **never matches** the
two-column's `.lesson-block` — the gate sits four levels deeper — so a column-nested gate of **any**
family hides nothing at slide level and has **no standing to veto anything**.

Testing `isGateWrapper(ownWrapper(gate, scope), scope)` **before** dispatching on family makes *"is
this thing actually gating this scope?"* the first question — which is the one that matters — and
covers all three families with one guard.

The same shape is why a stored-open column gate must not restore either: `ownWrapper(btn, scope)`
(`:21-25`) returns the top-level `.lesson-block` wrapping the **entire two-column element**, so
`cascadeFrom(..., {hideWrapper: true})` would **hide the whole two-column element on load**, with no
gesture at all.

##### (b) Null-scope gates are dropped during bucketing and never walked

`scopeOf` returns `null` outside any `.slide` / `[data-tab-panel]`. **The discard happens at grouping
time** (step 2's `if (!scope) return;`), so a null-scope gate is never bucketed and the walk never
sees it. There is deliberately **no** `if (!scope) continue;` inside the walk — one guard, one place.

Without the discard, `ownWrapper(el, null)` climbs until `node.parentElement !== null` — i.e. to
`<html>` — after which `isGateWrapper(html, null)` calls `scope.matches(...)` on `null` and throws.
Such a gate could not restore regardless: `cascadeFrom` already returns early at `:74` when `scopeOf`
is falsy.

**This guard is defensive-only and is deliberately EXEMPT from the falsification rule** (see
*Testing*). Step 3's per-gate `try`/`catch` already backstops it: with the discard deleted, the
`isGateWrapper(html, null)` throw lands in that `catch` and `break`s the null bucket — nothing escapes
the IIFE and nothing cascades, so no test could go red. The discard is therefore worth having for
**clarity and for not routing normal control flow through an exception**, not because anything
observable depends on it. Saying so is the point: an unfalsifiable guard presented as a tested one is
how vacuous tests get written.

This is reachable in the editor preview, which renders outside any `.slide`.

##### `libli:reveal` keeps firing on restore

It is **not** a focus side effect. `reveal.js:82-84` documents it as a *"bubbling contract shared with
tabs.js/gallery.js: a gallery or other enhancer inside newly-visible content needs to know it just
became visible so it can re-measure (it was previously `display:none`)."* It stays inside the cascade
loop (`:85`), which the `focus: false` early-return does not reach.

**But "a restored gate makes content visible for exactly the same reason a clicked one does" is only
true in a VISIBLE scope, and the difference is real.** On the click path the scope is necessarily
visible — the student just clicked something in it. On the restore path it need not be:

- **Hidden tab panel:** `tabs.js:101` sets `hidden` on every inactive panel before reveal.js runs. A
  restored gate there dispatches `libli:reveal` into a `display: none` subtree, and `gallery.js`'s
  `measure()` reads `offsetHeight` (`:159, :162`) as **zero**. **Recovery exists and is not ours:**
  `tabs.js:107` re-dispatches `libli:reveal` on activation, precisely because "a gallery inside a
  hidden panel measured zero height".
- **Non-first slide:** `slideshow.js:47` hides every slide as its resting baseline and `show(0)`
  un-hides only slide 0; it loads at `lesson_unit.html:71`, **before** reveal.js (`:76`). It
  dispatches **no** `libli:reveal` at all (verified), so recovery falls to `gallery.js:165`'s
  `ResizeObserver`.

**Accepted and untested — and in fact the event is untested EVERYWHERE, which is worth stating
plainly.** Even in a visible scope, `gallery.js:183`'s ResizeObserver observes every `.gallery__item`
and re-measures the stage when the block goes `display: none` → rendered, **with or without** the
event. So `libli:reveal` is belt for the only listener that exists today, and no test can distinguish
its presence from its absence (see *Testing*, "Dropped, because it is UNFALSIFIABLE").

**It still fires, unconditionally, and that is the right call.** `reveal.js:82-84` documents it as a
*contract* — "a gallery **or other enhancer** inside newly-visible content needs to know" — and a
future listener without a ResizeObserver of its own would depend on it. Suppressing an event that
costs nothing, to remove a redundancy that only today's implementation makes redundant, would be
optimising against the contract. What is not acceptable is *claiming coverage we do not have*.

#### 5e. Save

Two lines added to the existing click handler (`:131`): cascade first (optimistic), then POST.

```js
btn.addEventListener("click", function () { reveal(btn); save(btn); });
```

```js
function save(btn) {
  var url = btn.dataset.stateUrl;
  if (!url) return;                       // editor preview: no slug/node_pk -> "" -> no-op
  var eid = parseInt(btn.dataset.elementPk, 10);
  if (!eid) return;                       // pk 0 == content object with no join row
                                          // (the convention fillgateelement.html:5 documents)
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
    body: JSON.stringify({ element: eid, state: { open: true } }),
    keepalive: true,                      // survives unload -- see below
  }).catch(function () {});               // monotone: keep the DOM. See below.
}
```

**`fetch("")` would hit the current page**, which is why the empty-URL no-op is a guard and not
tidiness. CSRF is read from the cookie (`CSRF_COOKIE_HTTPONLY` is unset, as `progress.js` relies on)
via a 4-line helper **duplicated** from `markdone.js:5-8`: each JS file here is a self-contained IIFE
and the project has no shared module system, so duplication is the existing convention, not a lapse.

**`keepalive: true` is not boilerplate and must not be dropped as noise.** It is the project's
established setting for fire-and-forget state POSTs (`markdone.js:64`, `progress.js:29`,
`slideshow.js:119`, `core/static/core/js/ui.js:90`), and it lets the request **outlive the page
unload**. That matters precisely here: a student who clicks a gate and immediately navigates or
reloads would otherwise lose the save — which is the Guess-the-number hazard (PR #137) the *Purpose*
opens with, reintroduced by the very feature meant to fix it. Its ~64KB body cap is irrelevant to a
blob that is one constructed boolean.

**The gate ignores the response body entirely, and this is a deliberate, recorded deviation from the
record.** The record's error table says a monotone type should *"record the echo as
last-known-persisted"* (adoption effect 1) while never re-rendering from it (effect 2). Effect 2 is
**forbidden** here and the record is emphatic about why: a REJECT or a skip echoes `{}`, and
"re-render a reveal gate from `{}`" means **closing it** — re-hiding content the student just
unlocked, on a **200**. There is no un-cascade in `reveal.js`.

Effect 1 is **provably dead for this type**: the blob has exactly one reachable value, the DOM only
moves forward, and nothing ever reads last-known-persisted back. Writing it would be a variable with
no reader — the same objection the record itself raises against introducing `mine_json` before it has
a consumer. So the gate records nothing and reverts nothing. The `.catch` exists to keep an unhandled
rejection out of the console, and carries a comment saying so.

**On failure the DOM is untouched and simply not marked persisted.** The student keeps what they
unlocked; it re-hides on the next load if the save never landed, and they re-earn it. Rolling a
monotone type back would re-hide content the student legitimately unlocked with a gesture that never
needed a server — precisely the *"new way to trap content permanently hidden"* the feature names a
merge gate.

## Data flow

**Save (student clicks a gate):**

```
click -> reveal(btn): cascadeFrom(btn, {hideWrapper: true})   [optimistic, focuses, as today]
      -> save(btn): POST /courses/<slug>/u/<node_pk>/state/
                    {"element": <join_pk>, "state": {"open": true}}
      -> @login_required + @require_POST
      -> get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
      -> can_access_course  (NOT is_enrolled -- the PR #136 scar)
      -> Element.objects.filter(pk=element_pk, unit=node)   [nested-in-tabs covered for free]
      -> validate_state -> VALIDATORS["revealgateelement"] -> {"open": True} | EMPTY | REJECT
      -> atomic: get_or_create UnitProgress -> select_for_update -> merge key -> save
      -> 200 {"element": …, "state": <blob now stored>}
           -> client IGNORES the body (monotone; see 5e)
        (non-200 / network error)
           -> DOM untouched, not marked persisted. Never re-hide.
```

**Restore (lesson GET):**

```
build_lesson_context (views.py:352-380)
  -> enrolled     -> get_or_create UnitProgress          [unchanged: feeds progress/seen_ids]
     authed, not  -> .filter().first()                   [passive viewer spawns no row]
  -> state = {int(k): blob for k, blob in row.element_state.items() if isinstance(blob, dict)}
  -> context["element_state"] = state                    [RENAMED from "state"]

lesson_unit.html -> {% render_element el %}              [el IS the Element join row]
  -> render_element reads context.get("element_state")
  -> generic branch -> obj.render(element=el, state=<map>, slug=…, node_pk=…)
       -> _state_context: eid = el.pk; mine = map.get(eid) or {}; mine_json = json.dumps(mine)
       -> revealgateelement.html emits data-state='{"open": true}'
  (tabs / two-column re-inject the MAP -> nested {% render_element child %} works unchanged)

reveal.js IIFE (defer: after parse, before DOMContentLoaded; after gallery.js + tabs.js)
  -> initRevealGates(document)   -- un-hide buttons, bind clicks     [FIRST: makes a throw survivable]
  -> restoreGates(document)      -- enumerate barriers -> group by scopeOf -> walk each bucket
       -> per gate, in a try/catch that breaks THIS scope only:
       -> cascadeFrom(gate, {hideWrapper: true, focus: false})
            -> .reveal-shown on following siblings + libli:reveal   [gallery re-measures]
            -> NO focus, NO scroll, NO tabindex writes, NO display mutation
```

## Error handling

| Case | Behaviour |
|---|---|
| `{"open": false}` / no `open` key | Validator → **EMPTY** → key dropped. A well-formed "nothing to restore", **not** a rejection. |
| Non-dict payload | **REJECT** → stored key untouched → 200 echoing it |
| Extra keys (`{"open": true, "x": 1}`) | Normalized to `{"open": True}` — the server owns the stored shape |
| Validator raises | Caught by slice 1's `validate_state` → REJECT, logged, never 500 |
| Drifted `data-state` (`""`, non-JSON, `{"open": "yes"}`) | `storedOpen`'s `try`/`catch` + strict `=== true` → returns `false` → the walk `break`s that scope; the gate stays **live and clickable**, content re-earnable |
| A gate's walk body throws (`ownWrapper` / `isGateWrapper` / `cascadeFrom`) | Per-gate `catch` → **`break` that scope only**. Earlier scopes keep their restore, later scopes are unaffected. Prefix-closure is preserved because an unknown gate stops its scope rather than being walked past. |
| A throw escapes the per-gate catch entirely | `initRevealGates` already ran → every gate live and clickable. Fails **fresh**, not closed. Belt, not the primary guard — and **not independently tested** (see §5c). |
| Drifted blob already **stored** server-side | Slice 1's read guards drop it (`views.py:370-379`, `_state_context`'s non-dict → `{}`) → renders fresh, 200 |
| Save fails (network / 4xx / 5xx) | DOM untouched, response ignored. **Monotone: never re-hide** — there is no un-cascade. |
| Save returns 200 echoing `{}` (REJECT) | Ignored. Re-rendering from `{}` would **close the gate on a success response**. |
| Gate nested in a two-column column | Restore: skipped by the walk — **neither restores nor vetoes**. Save: **not** guarded; it still POSTs (see *Explicitly not fixed*). |
| Fill/switch gate nested in a column | Same restore guard, same reason — it gates nothing at slide level |
| Gate with no `.slide` / `[data-tab-panel]` scope | **Never bucketed** — dropped at grouping time, so the walk never sees it (else `isGateWrapper` would throw on `null`). Defensive-only: the per-gate `catch` backstops it, so it is exempt from falsification. |
| Stored-open gate behind a closed gate (same scope) | Ignored for this render, **left in storage** — re-earnable, and valid again after a reorder |
| Editor preview, initial load | `editor.html:144` loads reveal.js unconditionally, so restore **does run once** over the preview. Inert via `data-state="{}"` (no `element_state` in the editor context) — plus the null-scope guard for gates outside any `.slide`/`[data-tab-panel]`. For a **tab-nested** preview gate the scope is non-null, so `data-state="{}"` is the **sole** guard. |
| Editor preview, after a fragment swap | `editor.js:77` re-runs `libliInitRevealGates` only; `restoreGates` is not on `window`, so a re-cascade is structurally impossible |
| Editor preview, save | `{% url … as save_url %}` → `""` (no `slug`/`node_pk` in the editor context) → `save()` no-ops before `fetch` |
| Forged / foreign `element` pk | **400**, nothing written (slice 1) |
| JS disabled / blocked | Nothing persists; the watchdog disarms `reveal-armed`; content never trapped |
| Previewer (author/teacher, not enrolled) | **Persists** — the PR #136 rule (personal, ungraded, absent from analytics) |
| Anonymous | No save (`@login_required`), no state |

## Testing

**The honest constraint, stated because it shapes everything below: this project has no JS test
runner.** Every behavioural claim about the walk is therefore a Playwright test in
`tests/test_e2e_reveal_gate.py` (7 tests today: `test_reveal_cascade`,
`test_reveal_gate_nested_in_tab_scopes_to_that_tab`, `test_reveal_gate_inert_in_quiz`,
`test_watchdog_unhides_when_reveal_js_blocked`, `test_focus_lands_on_next_gate`,
`test_focus_lands_on_scope_for_trailing_gate`, `test_single_slide_gate_collapses_its_run`).

**The walk gets NO source-presence coverage.** `courses/tests/test_reveal_refactor_static.py` asserts
things like `"window.libliRevealCascade" in SRC` — substring greps over the file. Those are **vacuous
by construction** for anything the walk does: they would pass against a completely broken restore.
Per the `falsify-tests-not-run-them` lesson (four vacuous tests shipped past review in one build, two
of them inside the fixes for the previous one), a grep is not evidence.

**Falsification is required, not optional.** Every walk test is falsified on the way in: delete the
guard it covers, confirm **RED**, restore. This is cheap here because the guards are single lines. **A
test that stays green with its guard deleted is deleted.**

**But that rule only applies to guards something observable depends on — and two of this slice's
guards do not qualify.** Defence-in-depth and falsifiability are in direct tension: a guard that is
correctly backstopped by another guard is, by construction, unfalsifiable. Left unsaid, that tension
resolves the wrong way — an implementer writes a test that cannot fail, and it ships looking like
coverage. So the split is stated up front:

| Guard | Falsifiable? | How to falsify / why not |
|---|---|---|
| **`querySelectorAll(BARRIER)` — enumerating all three families, not just restorables** | **Yes** | **This is the guard that actually prevents §5d's headline leak.** Change the enumeration selector to `RESTORABLE` → the top-level-fill-gate leak e2e goes RED |
| **GROUP-then-walk (steps 2+3): one bucket per scope, `break` bound to the inner loop** | **Yes** | **§5d's other headline decision, and it needs its own row.** Flatten steps 2 and 3 into a single `for` over `gates` with one `break` (the "single global document-order walk" §5d calls wrong) → a gate closed in tab panel 1 now vetoes panel 2 → the *Across scopes* e2e goes RED |
| `if (!storedOpen(gate)) break;` (prefix-closure) | **Yes** | **`break` → `continue`**, not deletion. Deleting the `break` leaves `if (!storedOpen(gate));` — a no-op, so **every** gate cascades unconditionally and the test reddens because gate1 restored, not because gate2 restored past a closed gate1. `continue` leaves gate1 closed and lets gate2 restore — which **is** the leak — so the test can only go red for the right reason |
| `if (!isGateWrapper(...)) continue;` (mis-scope) | **Yes** | Change `continue` → `break` → the column-nested fill-gate veto test goes RED; remove the check entirely → the two-column test goes RED |
| **per-gate `catch { break; }`** | **No** | **No walk-body call can throw once the null-scope discard is in place** — the full enumeration, since a partial one is the shortcut this table's own rule exists to prevent. In the walk body: `ownWrapper` cannot throw with a non-null `scope`; `isGateWrapper` guards `!wrapper` and its selector is a fixed literal; `gate.matches(RESTORABLE)` takes a valid literal; `storedOpen` has its own `catch`. Inside `cascadeFrom` under `{hideWrapper: true, focus: false}`: `scopeOf` (`:73`), `ownWrapper` (`:75`), `classList.add` (`:81`), `dispatchEvent` (`:85` — a listener's exception does not propagate to the dispatcher), `isGateWrapper(node, scope)` in the loop (`:87`), `classList.remove` (`:94`) and the `hidden` setter (`:95`) — none can throw, and `:87` is safe **only because the discard guarantees `scope` is non-null**, which is the honest statement of why these two guards mutually backstop. §5d(b) names the **one** throw source — `isGateWrapper(html, null)` — and the discard removes it before the walk. **Defensive-only, exempt** — kept to bound the blast radius of a throw a *future* edit introduces. |
| `blob.open === true` (strict shape) | **Yes** | Relax to truthiness → a seeded `{"open": "yes"}` restores → RED |
| `opts.focus !== false` (the **default** direction) | **Yes** | Default it to `false` → the two pre-existing focus e2e (`test_focus_lands_on_next_gate`, `test_focus_lands_on_scope_for_trailing_gate`) go RED |
| **the walk actually PASSING `{focus: false}`** (the **call-site** half) | **Yes** | A separate guard from the row above, which only pins the default. Remove `focus: false` from §5d's `cascadeFrom` call → boot-restore starts focusing and scrolling → the *Boot-restore moves neither focus nor scroll* e2e goes RED |
| **the walk actually PASSING `{hideWrapper: true}`** | **Yes** | **A specified behaviour that had no row and no test.** Weaken the restore call to `{hideWrapper: false, …}` (or hoist an early `return` above `reveal.js:91-96`) → a **live duplicate "Show more" button sits above already-revealed content on every reload**. Every listed test stays green without this: the feature e2e only asserts the content is revealed; the barrier / prefix-closure / across-scopes / two-column / drift / preview tests assert `.reveal-shown` presence or absence; and the seven pre-existing tests exercise the **click** path, which still passes `{hideWrapper: true}` via `reveal(btn)` (`:121`). Covered by the feature e2e's added assertion: **after the reload the gate button is gone** |
| **`models.py:1265` — `TwoColumnElement.render`'s `element_state` re-inject** | **Yes** | Revert that one line → a mark-done nested in a two-column column renders unticked despite stored state → the new column test goes RED. **Its Tabs twin (`:1157`) is already guarded** by `test_markdone_render.py:81`; the column half is not, and no gate test covers it (the walk skips column gates) |
| **`save()`'s `if (!url) return;`** | **Yes** | Delete it → `fetch("")` POSTs to the **current page**. e2e: click a gate in the editor preview and assert **no** request to `.../state/` *and* none to the editor's own URL → RED |
| **`if (!scope) return;` (null-scope discard)** | **No** | The per-gate `catch` backstops it: the `isGateWrapper(html, null)` throw is caught and `break`s the null bucket, so nothing observable changes. **Defensive-only, exempt.** |
| **`storedOpen`'s `try`/`catch` around `JSON.parse`** | **No** | `mine_json` is always `json.dumps(<dict>)` and the gate is base-rendered, so no server path can emit a non-JSON `data-state`. `JSON.parse` never throws. **Defensive-only, exempt** — kept **only** for future leaves that may emit `data-state` by another route. (A hand-edited DB row is **not** a reason: it still passes `build_lesson_context`'s isinstance-dict drop at `views.py:372-378`, `_state_context`'s at `models.py:353-354`, and `json.dumps` — so it too always yields valid JSON. That is exactly why the drift e2e is scoped to `{"open": "yes"}` and falsified against `=== true`.) |
| **`if (!gate.matches(RESTORABLE)) break;` (barrier)** | **No** | **Redundant with `storedOpen` today, and an earlier draft wrongly claimed otherwise.** This slice adds `data-state` to `revealgateelement.html` **only** — `fillgateelement.html:2` and the switchgate `format_html` (`courses_extras.py:265-266`) emit none — so for a fill/switch gate `btn.dataset.state` is `undefined`, `storedOpen`'s `if (!raw) return false;` fires, and the **next** line breaks the walk anyway. Deleting this line changes nothing observable. **Defensive-only, exempt** — kept because the slice that gives fill/switch gates their own `data-state` makes it load-bearing overnight, and re-deriving it then would be re-deriving §5d. |
| **`libli:reveal` firing inside the restore cascade (`:85`)** | **No** | **`gallery.js`'s ResizeObserver independently covers the only listener we have.** `gallery.js:183` observes every `.gallery__item`, so a block going `display: none` → rendered re-measures the stage whether or not the event fires. Suppressing `dispatchEvent` leaves any gallery assertion GREEN. **Defensive-only, exempt** — the event stays because `reveal.js:82-84` documents it as a *contract* ("a gallery **or other enhancer**…"), and a future listener without an RO of its own would need it. See the dropped gallery e2e. |
| **`save()`'s `if (!eid) return;`** | **No** | `eid == 0` is unreachable through `render_element`, which always passes `element=element` (`courses_extras.py:64-69`); only `test_render_seam.py:66` constructs the `element=None` case directly. **Defensive-only, exempt** — it mirrors the convention `fillgateelement.html:5` already documents. Note this does **not** share `if (!url) return;`'s status, despite sitting on the adjacent line. |
| **`restoreGates` being absent from `window`** | **No** | Falsify it by exporting `restoreGates` **and** calling it from `editor.js:77`'s block: every preview gate carries `data-state="{}"` (`storedOpen` → false), so none cascades and the editor tests stay **GREEN**. **Defensive-only, exempt** — belt for the day a preview context does carry state; `data-state="{}"` is what actually holds today. (`data-state="{}"` alone, **not** the null-scope discard: §5b establishes that a *tab-nested* preview gate has a **non-null** scope, so the discard covers top-level preview gates only. Overstating its reach here is exactly what §5b warns a future reader would cite to drop the guard it calls "sole".) |

The six exempt entries are **kept** — each is one line, and they keep normal control flow out of
exception paths and off future traps — but **no test claims to cover them, and no test may be written
that pretends to.**

**The pattern in the exempt half is worth naming, because it is the trap this spec kept walking
into.** Every exempt entry is exempt for the *same reason*: something else already covers it
(`storedOpen` covers the barrier guard; the null-scope discard covers the per-gate `catch`;
the per-gate `catch` covers the null-scope discard; `data-state="{}"` covers the export surface;
`render_element` covers `eid == 0`). **Defence-in-depth and falsifiability are in direct tension** — a
guard that is correctly backstopped cannot, by construction, be falsified. **Four separate drafts of
this table claimed a falsification that could never go red**, each time in a new row, which is why the
rule is written down rather than trusted to care:

> **Before writing "Yes", name the *other* guard that would have to be absent for the test to fail.
> If you can name one, the row is a "No".**

**The null-scope discard and the per-gate `catch` are mutually backstopping, and BOTH are therefore
exempt.** An earlier draft had them justifying each other in a circle — the discard exempt *because
the catch swallows its throw*, the catch falsifiable *via a throw only the discard-less path
produces*. Applying the rule above to the catch names the discard, so the catch is a "No" too. Two
guards can be defence-in-depth for each other; neither becomes testable by pointing at the other.

**Note what the last row means for the design's headline argument.** §5d's barrier/restorable split is
real and load-bearing, but the half that *enforces* it today is the **enumeration** (`BARRIER`), not
the `matches(RESTORABLE)` guard. The guard is the split's *future*; the enumeration is its *present*.
The first table row is therefore not optional coverage — without it, the entire split ships untested.

### Server-side (fast, pytest) — carry what a browser is not needed for

- **Validator, five cases:** `{"open": true}` → `{"open": True}`; `{"open": false}` → EMPTY;
  no `open` key → EMPTY; non-dict → REJECT; `{"open": true, "x": 1}` → `{"open": True}` (extra keys
  normalized away).
- **Endpoint round-trip:** a gate POST stores `{"open": True}` under the join-row pk and echoes it;
  an EMPTY drops the key.
- **`data-state` round-trips through parse — and the attribute must be UNESCAPED first, or the test
  fails on correct code.** Django renders `data-state="{&quot;open&quot;: true}"`; calling
  `json.loads` on that raw text raises `JSONDecodeError` **on a correct implementation** (verified).
  So the test must read the attribute the way a browser does: **`html.unescape()` a
  `data-state="([^"]*)"` regex capture, then `json.loads`.** (No HTML-parser option is offered here —
  see the next bullet: the project has none, and none is being added.) The unescape step is not
  incidental — it **is** the round-trip being tested.
  **Falsification (this is what makes it worth writing):** add `|safe` to the template. The
  `[^"]*` capture then truncates at the first raw `"` — yielding `{` — and `json.loads` goes RED,
  exactly as a browser's attribute parse would. It also catches the `repr`-vs-JSON serializer bug
  (`{'open': True}`), without a browser.
- **`data-state` renders `{}`** when nothing is stored.
- **No wrapper element is introduced — assert the CHAIN, not the attributes.** Asserting the three
  attributes are on the `<button>` passes **identically** with or without a wrapper `<div>` around it,
  so it cannot detect the thing §4 spends its longest passage forbidding.

  **Assert it with a regex over the decoded body — this project has NO HTML parser and none is being
  added.** `pyproject.toml` carries no BeautifulSoup / lxml / soupsieve, no test uses `assertInHTML`
  or `parse_html`, and the established style is plain substring assertion over `body`
  (`test_markdone_render.py:101-103`). A CSS-selector chain like `.lesson-block__body > button[...]` has
  nothing to run on; prescribing one would force either an unbudgeted dependency or a silent fallback
  to the very attribute-assert this bullet rejects. Render a full lesson and require the
  **direct-child** chains that `isGateWrapper` and the prepaint CSS actually match:

  ```python
  assert re.search(r'<div class="lesson-block__body">\s*<button[^>]*data-reveal-gate', body)
  # and, in a tab-nested fixture:
  assert re.search(r'<div class="tabs__child">\s*<button[^>]*data-reveal-gate', body)
  ```

  `\s*` absorbs the newlines the template's `{% load %}` / `{% url … as … %}` tags leave behind.
  **Falsify by wrapping the button in a `<div>`**: the intervening tag breaks the match → RED. (The
  `data-state` bullet above names its stdlib path — `html.unescape()` on a regex capture — for the
  same reason.)
- **`eid` provenance:** the emitted `data-element-pk` equals the passed join row's pk.
- **The rename:** the lesson context binds `element_state` (not `state`), and the existing render-seam
  and lesson tests stay green.
- **A mark-done nested in a TWO-COLUMN column resolves its ticks — a NEW test, and the only guard on
  `models.py:1265`.** The Tabs half of the rename is already guarded: revert `models.py:1157` and
  `courses/tests/test_markdone_render.py:81`
  (`test_nested_in_tabs_checklist_resolves_checked`) goes red. **The two-column half has no
  counterpart anywhere in the suite** — the `test_twocolumn_*` files cover model, transfer, registry,
  has_math, partial and save_views; none renders state. Yet `mark_done` is in `NESTABLE_TYPE_KEYS`
  (`builder.py:52`) and `_CONTAINER_REGISTRY` admits `TwoColumnElement` (`builder.py:74`), so a
  mark-done in a column is authorable **today**. Miss `models.py:1265` and its child
  `render_element` reads `context.get("element_state")` → `None` → `mine = {}` → **the student's
  ticks render unticked despite stored state**, silently, as a slice-1 regression shipped on a
  slice-2 PR. **This slice's own e2e cannot catch it** — the walk deliberately skips column-nested
  *gates*, so nothing else exercises that re-inject. Mirror
  `test_nested_in_tabs_checklist_resolves_checked` for a column. Falsify by reverting `models.py:1265`
  alone.

### e2e (Playwright, real gestures only — never `page.evaluate`)

`e2e-must-drive-real-ui` is a well-earned scar: an e2e that bypasses the real gesture ships broken UX
green.

**What the ban does and does not cover — stated because every restore test needs pre-existing state,
which no gesture on the page under test can produce.** The ban is on **performing the gesture under
test** via script: never click, type, or toggle through `page.evaluate`.

- **Seeding is setup, not a bypassed gesture.** Restore fixtures write
  `UnitProgress.element_state = {str(join_pk): {"open": True}}` **directly in the DB** before the page
  loads. That is legitimate: the gesture under test is *the reload*, and the stored state is its
  precondition. (A "click then reload" alternative is available and is exactly what the first e2e
  below does — it earns the state through the real button — but it cannot express the prefix-closure
  and non-default-tab fixtures, where a gate must be stored open in a configuration the current UI
  cannot reach.)
- **Reading state back is not the banned use either.** Assertions may evaluate — see the focus/scroll
  assertions below, which have no attribute-level equivalent.

**Fixture work is real and is budgeted here, not discovered mid-build.** `tests/test_e2e_reveal_gate.py`'s
only container helper is `_seed_tab1_gate(unit, tab1_children)` (`:96`), which seeds **tab 1 only**,
and there is **no two-column seeder at all**. Four of the tests below need more than exists:

- *Across scopes* needs a gate in **tab 2** → extend `_seed_tab1_gate` to take per-tab children (or add
  a sibling helper); the current signature cannot express it. **Mirror `tests/test_e2e_tabs.py:93`'s
  `_seed_tabs_element(unit, tabs, children)`** — `tabs` is `[(tab_id, label)]` and `children` maps
  `tab_id -> [obj]`, which is already exactly the shape needed (used at `test_e2e_tabs.py:502-509`).
- *Two-column* and *Column-nested fill-gate* need a gate inside a `TwoColumnElement` column → a **new**
  seeder creating the container plus child `Element` join rows with `parent=<container join row>` and
  `tab_id=<column id>` (the shape `builder.py`'s `resolve_scope` admits).

  **The column id CANNOT be hardcoded, and getting this wrong makes both tests pass VACUOUSLY.**
  This is the one place the tabs pattern must **not** be copied: `_seed_tab1_gate` and
  `test_nested_in_tabs_checklist_resolves_checked` both hardcode `"t000001"` and work, but
  `TwoColumnElement.default_data()` mints its ids with `secrets.token_hex(3)` via `new_column_id()`
  (`models.py:1188-1193`), and `save()` runs `normalize_ids`. A hardcoded `tab_id` therefore matches
  no column, `resolved_columns()` drops the child (`by_col.get(col["id"], [])`), and **the gate never
  renders at all** — at which point "the two-column element is not hidden" is trivially true (there is
  no gate in it) and "column-nested fill-gate does not veto" is trivially true (there is no fill-gate).
  Two green tests, zero coverage, no error. **Read the id back after save**, mirroring
  `tests/test_twocolumn_has_math.py:14-17`:

  ```python
  col = TwoColumnElement(data=TwoColumnElement.default_data())
  col.save()
  cid = col.data["columns"][0]["id"]      # minted by secrets -- never hardcode
  ```

  The same caveat binds the server-side "mirror `test_nested_in_tabs_checklist_resolves_checked` for a
  column" instruction: mirror its *structure*, not its hardcoded-id style.
- **The barrier-enumeration test and the column-nested fill-gate test need a `FillGateElement`, and
  `test_e2e_reveal_gate.py` has no fill-gate helper.** Its element helpers are exactly `_text` (`:84`)
  and `_gate` (`:90`). The one that exists lives in **another file** and is not importable as written:
  `tests/test_e2e_fillgate.py:98-105`'s `_fillgate(author_stem)`, which must round-trip author
  `{{answer}}` markup through `courses.fillblank.parse` into `stem` + `answers`:

  ```python
  token_stem, blanks = parse(author_stem)
  return FillGateElement.objects.create(stem=token_stem, answers=blanks)
  ```

  Mirror it into `test_e2e_reveal_gate.py`. **This one is on the critical path**: the barrier-
  enumeration test is the row this spec calls "not optional coverage — without it, the entire split
  ships untested". The column-nested variant needs this helper **and** the two-column seeder.
*(A **gallery** seeder — two `MediaAsset`s plus the `MIN_IMAGES` shape — was budgeted here in an
earlier draft as the most expensive of the four. It is **gone**, along with the gallery e2e that was
its only consumer: see "Dropped, because it is UNFALSIFIABLE".)*

This is the majority of the new e2e's cost. A plan that lists the tests without these **three**
helpers underestimates the slice.

- **The feature:** click the real gate → reload → content still revealed **AND the gate button is
  gone**. The second assertion is one line and it is the **only** coverage of the restore call's
  `{hideWrapper: true}` — without it, a restore that drops `hideWrapper` leaves a live duplicate
  "Show more" above the revealed content on every reload, and nothing else in this list reddens (see
  the table). **The click and the reload must be separated by an awaited response, or the test is
  flaky on correct code.** `save()` is
  fire-and-forget (`keepalive`, no awaited promise), so `page.click()` → `page.reload()` can reload
  before the POST commits. Slice 1 already solved this and the pattern is in-repo: wrap the click in
  `with page.expect_response(...)` on the `.../state/` endpoint before reloading — see
  `tests/test_e2e_markdone.py:86` (reload at `:92`), whose module docstring (`:5`) calls out exactly
  this. Given the `flaky-tests-separate-pr` scar, an unpinned race here is expensive: it would go red
  on an unrelated PR and cost a session to prove innocent.
- **The barrier enumeration — a TOP-LEVEL unanswered fill-gate above a stored-open plain gate → no
  block past the plain gate carries `.reveal-shown`.** This is §5d's headline leak, and **nothing else
  in this list covers it**: the prefix-closure test uses two plain gates (green under either
  enumeration selector), and the column-nested fill-gate test exercises the `continue` path (also
  green, since a `RESTORABLE`-only enumeration simply omits the fill-gate and the later gate restores
  as expected). Falsify by changing `querySelectorAll(BARRIER)` to `querySelectorAll(RESTORABLE)` and
  requiring RED.
- **Prefix-closure:** gate2 stored open behind a closed gate1 → gate1 renders as a live gate and
  **no block past gate2 carries `.reveal-shown`**. (The single-scope case pins nothing on its own —
  it passes under all three readings — so the next two are required alongside it.)
- **Across scopes:** gate closed in tab panel 1, gate stored open in panel 2 → **panel 2's restores**.
  **This is the test that pins GROUP-then-walk.** Falsify by flattening the bucketing into a single
  `for` over `gates` with one `break` — the "single global document-order walk" §5d calls wrong —
  which lets panel 1's closed gate veto panel 2 → RED.
  **This must assert on `.reveal-shown`, NOT on visibility — `to_be_visible()` gives a false
  RED.** `tabs.js:101` sets the `hidden` attribute on every inactive panel before reveal.js runs (the
  same fact the "Do NOT restate this as…" rule above depends on), so a correctly-restored gate in
  panel 2 is **inside a hidden panel** at assert time. An implementer reaching for `to_be_visible()`
  sees red on correct code and may "fix" the walk to chase it. Assert `.reveal-shown` class presence
  on panel 2's `.tabs__child` elements *while the panel is still hidden* — the discipline the
  prefix-closure bullet already uses — or click through to the tab first and *then* assert
  visibility.
- **Two-column:** a stored-open gate inside a column → the two-column element is **not** hidden, and a
  top-level stored-open gate later in the slide **still restores**.
- **Column-nested fill-gate does not veto** a later top-level stored-open gate — the (a) case above.
- **Boot-restore moves neither focus nor scroll.** (The "a real click still focuses" half is
  **dropped as duplicate coverage**: the table assigns that guard to the two pre-existing focus e2e,
  which pass no `focus` option via `reveal(btn)` at `reveal.js:121` and already redden if the default
  flips. This test pins the boot-restore half only; the table's separate call-site row covers the
  argument being passed.) **Assertion mechanism, named because it is not obvious:** focus via
  `expect(page.locator("body")).to_be_focused()` after a restore-only load — nothing in the document
  should have taken focus. (No click assertion here: that half is dropped, per the parenthetical
  above.) Scroll via `page.evaluate("window.scrollY") == 0`,
  **not** a viewport-absolute element-position comparison across a load — `unit-nav-container-scroll`
  is the scar there. Reading `scrollY` is an assertion, not a bypassed gesture (see the ban's scope
  above).

  **The scroll half needs a fixture precondition or it cannot fail: the restored gate's focus target
  must sit BELOW THE FOLD.** On a short fixture `scrollY` is `0` under both the correct and the
  falsified implementation, so that assertion would be decorative — the thing this section refuses
  everywhere else. Seed enough preceding blocks that a `focus()` would actually scroll. If that proves
  awkward, say so and let the **focus** assertion carry the test (removing `focus: false` moves
  `document.activeElement` off `<body>`, which reddens regardless of page height) — but then state
  that the scroll line is documentation of intent, not a guard.
*(The gallery e2e an earlier draft listed here is **dropped** — see the "Dropped, because it is
UNFALSIFIABLE" note below. It takes the gallery seeder, the most expensive of the fixtures, with it.)*
- **Drifted `data-state`** → the **gate button** is visible and clickable, **no** following block
  carries `.reveal-shown`, and clicking it *then* reveals the content. **Do NOT assert "the gated
  content is visible" — that is RED on correct code.** On a drifted blob the walk `break`s, the gate
  stays closed, and the prepaint `<style>` (`lesson_unit.html:39-40`) correctly keeps every following
  `.lesson-block:not(.reveal-shown)` at `display: none`. An earlier draft of this bullet said "content
  visible", contradicting its own error-table row and inviting the same `to_be_visible()` false-RED
  this section warns about for the non-default-tab case. The parallel with the **JS blocked** bullet
  below is misleading: there content genuinely *is* visible, because the watchdog disarms
  `reveal-armed` entirely.
  **The fixture must seed `element_state = {str(join_pk): {"open": "yes"}}` directly** — that is the
  **only reachable drift**. `data-state=""` and non-JSON `data-state` cannot occur (`mine_json` is
  always `json.dumps(<dict>)` and the gate is base-rendered), and `{"open": "yes"}` cannot arrive
  through the endpoint either, since `_val_revealgate` normalizes any truthy `open` to `True`. A
  hand-written row is the one path in. **Falsification scopes to the `=== true` strictness** (relax it
  → the drifted blob restores → RED), **not** to `storedOpen`'s `try`/`catch`, which is exempt above.
- **JS blocked** → content visible; `test_watchdog_unhides_when_reveal_js_blocked` stays green.

**Three editor-preview tests, not one — and the "same test" economy an earlier draft claimed is
withdrawn.** That economy assumed the preview always renders outside any `.slide`, so that one test
would cover both the null-scope guard and preview inertness. It does not hold: `editor.html:144`
loads reveal.js unconditionally, so restore runs on the preview at initial load, and
`tabselement.html:17` gives a **tab-nested** preview gate a **non-null** scope — the null-scope guard
never fires for it, leaving `data-state="{}"` as the only thing between an author and a preview that
cascades itself on every load. So:

1. **Null-scope / top-level preview gate:** it **neither throws nor cascades**, on initial load **and**
   across a fragment swap. That — an author's preview staying inert — is the whole of what it pins.
   **It does NOT pin the null-scope discard, and it does NOT pin `restoreGates`'s absence from
   `window`**; both are exempt (see the table), because the per-gate `catch` and `data-state="{}"`
   respectively keep this test green with either one removed. Stating a purpose the test cannot
   deliver is how the last three drafts of the table went wrong.
2. **Tab-nested preview gate:** non-null scope, `data-state="{}"` → does not cascade. Falsify by
   defaulting `mine_json` to a stored-open blob and requiring RED.
3. **Preview gate CLICK sends no request — the only guard on `save()`'s `if (!url) return;`.** Click
   a real gate in the preview and assert **no** request to `.../state/` **and none to the editor's
   own URL**. The second half is the point: `save_url` resolves to `""` there, and without the guard
   `fetch("")` POSTs to **the current page** — the editor itself. Falsify by deleting
   `if (!url) return;` and requiring RED. Tests 1 and 2 do not click, so neither covers this.

**Dropped, because it is UNFALSIFIABLE:** "a gallery behind a restored gate measures correctly". The
claim it tests — `libli:reveal` fires on restore, so the gallery re-measures — **cannot be made to go
red while `gallery.js`'s ResizeObserver exists.** `gallery.js:183` runs
`if (ro) items.forEach(function (it) { ro.observe(it); })`, so every `.gallery__item` is observed;
when restore stamps `.reveal-shown` and the block goes from `display: none` to rendered, each item's
box changes, the RO fires, `scheduleMeasure` → `measure()` runs, and `stage.style.minHeight` gets a
real value — **with `dispatchEvent` suppressed**. The other proposed falsification (hoisting
`if (!focus) return;` above the loop) reddens because *no cascade happens at all*, which the feature
e2e already pins — not because the event fired.

**The spec had already conceded this two sections up** ("recovery falls to `gallery.js:165`'s
`ResizeObserver`") and then failed to apply its own rule: name the other guard that would have to be
absent — the RO — and the row is a **No**. Stubbing `window.ResizeObserver` to force it red would be
worse than dropping it: the RO always exists in a real browser, so that test would pin a fallback path
production never takes. **The in-repo model (`test_e2e_tabs.py:517`) is subject to the identical
confound and is not evidence to the contrary.** Dropping this test also removes the gallery seeder —
two `MediaAsset`s plus the `MIN_IMAGES` shape — from the fixture budget, which was its only consumer.

**Dropped, because it is SUBSUMED:** "a stored-open gate in a non-default tab restores". `tabs.js:144`
calls `select(0)` at init, so **panel 2 in the *Across scopes* fixture already IS the non-default
panel** — that test asserts exactly this, and more. The subsumed version also stays green under
deletion of *every* guard in the diff (the `storedOpen` `break`, the `isGateWrapper` `continue`, the
`BARRIER` enumeration, the bucketing, `focus: false`), because what it guards against is an **added**
visibility check, not a deleted line — and *Across scopes* guards that too: adding such a check would
stop panel 2's gate restoring and redden it. The `hidden`-panel misreading §5d warns about
("Do NOT restate this as…") therefore stays pinned, by *Across scopes*.

**Dropped, because it is vacuous:** "multiple stored-open gates in one scope restore in document
order". With gate1 and gate2 both stored open, the two orderings do **not** produce identical DOM —
forward order leaves gate2's wrapper `hidden` *without* `.reveal-shown` (its own `cascadeFrom` strips
it at `reveal.js:94`), while reverse order leaves it `hidden` *with* `.reveal-shown` re-stamped by
gate1's cascade. But they **render identically**, which is what matters: `app.css:967`'s
`[hidden] { display: none !important }` wins regardless of `.reveal-shown`. So the assertion passes
under both orderings and guards nothing. This is the same trap the prefix-closure bullet
above flags ("the single-scope case pins nothing on its own"), and it would have been applied
inconsistently. **Document order is load-bearing only for the prefix-closure `break`**, which the
prefix-closure and across-scopes tests already cover.

### Regression

Full non-e2e suite green; `ruff check` **and** `ruff format --check`; **`makemigrations --check`
(this slice adds no migration)**; `manage check`. `test_po_catalog_clean` is unaffected — no new
strings.

**"Non-e2e suite green" is NOT sufficient here, and saying so is the point of this paragraph.** This
slice edits `cascadeFrom` (new `focus` option + early return) and `initRevealGates` (inline `sel` →
module-level `RESTORABLE`) — the **shared cascade engine**, whose only behavioural coverage is e2e. A
DoD that runs only the non-e2e suite would let that refactor ship with its regression tests unrun.

**THREE e2e files cover `cascadeFrom`, not one.** `cascadeFrom` is exported as
`window.libliRevealCascade` (`reveal.js:145`) and **the other two gate families call it**:
`fillgate.js:73` and `switchgate.js:80` both invoke it with `{hideWrapper: false}`. So the DoD is:

| File | Runs green | What it uniquely guards |
|---|---|---|
| `tests/test_e2e_reveal_gate.py` | all **seven** pre-existing, **plus** the new ones | `hideWrapper: true`; the plain-`<button>` fallback of `focusTargetIn` (`:63`); the watchdog; quiz inertness |
| `tests/test_e2e_fillgate.py` | all pre-existing | **`focusTargetIn`'s `[data-fillgate]` branch (`reveal.js:54-59`)** — `test_plain_gate_stops_at_fillgate_and_focuses_blank` (`:296`) is its **only** behavioural coverage |
| `tests/test_e2e_switchgate.py` | all pre-existing | **`focusTargetIn`'s `[data-switchgate]` branch (`:60-62`)** — `test_chains_to_next_gate_and_focuses_cycler` (`:255`) is its **only** behavioural coverage |

**Why the last two matter specifically: `if (!focus) return;` skips the entire block those branches
live in.** An earlier draft claimed `test_e2e_reveal_gate.py` was "the only behavioural coverage those
functions have" — **false**. Its focus pair only exercises `focusTargetIn`'s plain-`<button>` fallback
at `:63`; the `[data-fillgate]` and `[data-switchgate]` branches are reached from **those** files. And
`test_reveal_refactor_static.py:17`'s `data-fillgate` grep is the vacuous source-check this spec
dismisses everywhere else — it would stay green through any behavioural break. The section's own
argument applies verbatim to all three files.

The seven in `test_e2e_reveal_gate.py`: `test_reveal_cascade`,
`test_reveal_gate_nested_in_tab_scopes_to_that_tab`, `test_reveal_gate_inert_in_quiz`,
`test_watchdog_unhides_when_reveal_js_blocked`, `test_focus_lands_on_next_gate`,
`test_focus_lands_on_scope_for_trailing_gate`, `test_single_slide_gate_collapses_its_run`. The focus
pair is the direct guard on `opts.focus !== false` defaulting true (a real click must still focus,
byte-for-byte); `test_reveal_gate_inert_in_quiz` guards that the quiz page — which never loads
`reveal.js` — stays untouched.

`courses/tests/test_reveal_refactor_static.py:14` greps the literal
`"button.reveal-gate[data-reveal-gate]"`, which the `RESTORABLE` refactor **preserves** (it moves the
literal, it does not change it), so that file stays green without edit. That is luck, not design — it
is a source-grep, and this spec does not rely on it for anything.

## Deferred, and why the gate forecloses nothing

The record names **three unresolved mechanisms** for slice 2. **All three miss the gate**, and this
slice deliberately answers none of the two that remain rather than inventing provisional answers —
inventing them is exactly what made the record's later-slice blob table fiction, which review then had
to correct.

1. **"The blob never reaches five of six leaves."** **Already resolved** — by slice 1, not by this
   slice. See *What slice 1 already paid for*. `_state_context` is the contract; all five splat it.
2. **"Their verdicts are server-only and not client-derivable."** `switchgrid_check` returns per-cycler
   cells, `filltable_check` per-cell `correct`, `guessnumber_check` a `direction` — none is in the DOM,
   none is in the blob. A restored `{"done": true}` grid would be locked with no ✓/✗. **The gate has no
   verdict at all**, so it proves nothing here either way.
3. **"Three of the six render from positional template tags"** (`{% render_switch_gate el eid %}`), so
   their markup is built in Python and "the template emits `data-state`" has nowhere to land.
   `revealgateelement.html` is a **real template**, so this does not arise.

**The gate forecloses neither answer to (2), and that is why deferring is safe rather than merely
convenient.** Blobs are **per-type and opaque to the storage layer** — the field does not know what a
switch grid is — so "carry the verdict in the blob" is a per-validator decision that touches nothing
here. And "re-POST the stored input to the existing `*_check` endpoint on boot" is **per-element JS**,
additive to a leaf's own boot. Whichever way the self-checks go, **nothing in this slice's substrate
has to move**: not `_state_context`, not the endpoint, not the walk, not the rename.

Whichever they choose must still reconcile with the record's *Questions* rule ("never store the
verdict — it would freeze a stale verdict"), since an author editing `target`/`answer` freezes
"too big" exactly the same way. That reconciliation is **their** spec's job. This spec produces no
evidence about it and therefore claims none.

## Explicitly not fixed

**The reveal-gate x two-column mis-scoping.** `reveal_gate` is in `NESTABLE_TYPE_KEYS`
(`builder.py:46`) and `_CONTAINER_REGISTRY` registers `TwoColumnElement` as well as `TabsElement`
(`builder.py:73-74`), so `resolve_scope` admits a gate into a column through the ordinary editor
(`_element_row.html:131` includes the nested add-menu with `tab=column.id`; `_add_menu.html`'s
Interactive group carries no `{% if not nested %}` guard).

**Clicking such a gate is already broken today, with no persistence involved:** `scopeOf` returns the
`.slide`, `ownWrapper` returns the `.lesson-block` wrapping the **whole two-column element**, so the
click reveals the two-column element's *following siblings* and `hideWrapper: true` hides the entire
two-column element.

This slice's obligation is only to **not replay that on every page load** — which the (a) guard
achieves. Fixing the click path is a separate change with its own blast radius (`scopeOf`,
`isGateWrapper`, and the prepaint + print CSS would all need a `.twocolumn__child` shape), and it
belongs in its own PR. Added to the tidy-up backlog.

**The save path is deliberately NOT scope-guarded, and the consequence is stated rather than
discovered.** `data-element-pk` and `data-state-url` are emitted on every gate unconditionally, so clicking
a column-nested gate still POSTs `{"open": true}` and the server still stores it — under a key the
walk will **always** skip. The result is a write-only entry: inert on every subsequent load, and
clearable only by Reset.

That is accepted, for three reasons. Guarding the save would mean teaching `save()` the same
scope/wrapper logic the walk has, duplicating (a) on a second path to prevent a **harmless** row in a
personal, ungraded, analytics-invisible field. The blob is bounded (one constructed boolean key), so
it cannot grow. And if the two-column mis-scoping is ever fixed in its own PR, the already-stored keys
become **correct and useful** rather than garbage to migrate — the conservative outcome. What would
not be acceptable is leaving it *unstated*, since a reader of the walk's skip rule could reasonably
assume the save is skipped too.

## Execution notes

- **Isolate the test DB per worktree:** `DATABASE_URL=…/libli_<slug>` (the role has CREATEDB).
  Concurrent worktrees collide on `test_libli`, and the symptom is *errors, not failures*, plus a
  shifting test — easy to misread as a real break. A concurrent session is active on this machine.
- **`ruff` / `pytest` / `python` are NOT on PATH in bash** — use `uv run`.
- Run the heavy suite with **`-n auto`**; serial exceeds a subagent's 600s watchdog.
- **e2e needs an explicit `-m e2e`** — otherwise `addopts = -q -m 'not e2e'` deselects the file and
  pytest exits **5, looking like success**. Run focused e2e **foreground only, never backgrounded**
  (a backgrounded `-m e2e` leaves runaway browsers).
