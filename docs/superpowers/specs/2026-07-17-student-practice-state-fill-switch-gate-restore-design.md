# Student practice state — Fill-in-&-confirm and Choose-&-confirm onto client-restore

> **SCOPE: the two answered reveal-gates — *Fill in & confirm* (`FillGateElement`) and *Choose &
> confirm* (`SwitchGateElement`) — brought onto the client-restore mechanism, together but alone.**
> They are the natural next elements after the plain gate: they already emit `[data-reveal-gate]` and
> already call `libliRevealCascade`, so the slice-2 restore walk already treats them as **barriers** —
> it stops at them only because they carry no stored-open state yet. This slice gives them that state.
>
> **The verdict-bearing self-checks stay out** (Switch grid, Fill-in table, Guess-the-number,
> Step-by-step). They show per-item ✓/✗ marks the client cannot re-derive, so they force the
> carry-verdict-in-blob vs re-check-on-boot decision this slice deliberately avoids. They get their own
> later spec.
>
> **Slice 1** (the substrate: `UnitProgress.element_state`, migration 0050, the render seam,
> `element_state_save`, `progress_reset`) shipped as **PR #139**. **Slice 2** (the plain "Show more"
> gate as the first client-restoring element: `_val_revealgate`, `mine_json`, the `element_state`
> ambient-key rename, `restoreGates`, the barrier/restorable split, the falsifiability doctrine)
> shipped as **PR #140**. This spec builds directly on both and reuses their substrate wholesale.
>
> **Reading rule.** "The slice-2 spec" means
> `docs/superpowers/specs/2026-07-17-student-practice-state-slice-2-gate-design.md`. Its mechanisms
> (`restoreGates`'s per-scope prefix-closed walk, `storedOpen`, `cascadeFrom`'s `focus`/`hideWrapper`
> options, the falsifiable-vs-exempt guard split) are the substrate this slice extends, not
> re-litigates. Where this spec changes slice-2 code, it says so and gives the before/after.

## Purpose

Make a student's **answered** reveal-gate work survive a page reload — both the content they unlocked
*and* the answered-and-locked appearance of the gate itself.

Today, a student who answers a *Fill in & confirm* or *Choose & confirm* gate correctly sees the
following content cascade open and the widget lock (readonly answer / disabled cycler). On reload,
`reveal.js` persists nothing: the content re-hides and the widget resets to blank/editable. This is
the same class of loss the plain gate fixed in slice 2, one element-family over — and it is worse
here, because these gates carry a *question*, so the reset discards the student's demonstrated answer,
not just a disclosure toggle.

Slice 2 built and proved the client-restore path on the plain gate. This slice is the cheapest
extension of it: the two gates are **monotone** (open ⟺ answered correctly), so they inherit slice 2's
`{"open": true}` blob unchanged and need **no verdict**. The correct answer they display on restore is
not stored — it is rendered from the element's own known-correct answer, gated on the open flag.

## Scope decisions (settled in brainstorming)

**Correct answers only.** A wrong attempt persists nothing and restores to a fresh, editable widget.
Persisting a wrong attempt was considered and dropped: to restore its per-blank red markers the client
would need the server's per-blank verdict, which is available only by **storing the verdict** (frozen
stale the moment an author edits the accepted answers — the doctrine `state.py` forbids) or
**re-POSTing to `*_check` on every load** (the re-check-on-boot mechanism reserved for the
verdict-bearing slice). Both undercut the cheap, verdict-free, synchronous character that makes these
two the right proof. So neither is built here.

**The blob stays monotone `{"open": true}`** — byte-identical to the plain gate. The correct answer is
**not** stored. It is rendered server-side from `FillGateElement.answers` / `SwitchGateElement.answer`,
gated on `mine.open`. Consequences, both accepted:

- **Free-text never enters the blob**, so the per-string length / entry-count caps the slice-2 spec
  flagged for a stored-answer fillgate are **not needed**. This is the main reason to render the
  answer rather than store it.
- **The displayed answer self-heals.** If an author edits the accepted answer after a student has
  opened the gate, the already-open gate shows the *new* correct answer next to the (still-earned)
  revealed content — never a frozen stale one. A canonical answer is always current by construction.
- **Canonical, not verbatim.** A fill-blank that accepts several spellings (`color`/`colour`) shows
  the **first** accepted alternative, which may differ from the exact variant the student typed.
  Accepted in brainstorming. Switch-gate has no ambiguity: the correct choice is the single index
  `answer`, which is exactly what the student cycled to.

### Non-goals

- **No new element type.** `ELEMENT_MODELS` does not change; the `len(ELEMENT_MODELS)` /
  `ELEMENT_MODELS[-1]` count-asserts in `tests/test_transfer_schema.py` and
  `tests/test_models_multigrid.py` are not triggered.
- **No migration.** The `element_state` field exists (slice 1). `makemigrations --check` stays clean.
- **No verdict storage, no re-check-on-boot, no per-blank marker restore** (see *Scope decisions*).
- **No wrong-attempt persistence.**
- **No change to `fillgate_check` / `switchgate_check`.** They remain the sole first-answer grader.
- **No new user-visible strings** — no `makemessages` pass, no fuzzy-flag cleanup.
- **No fix for the reveal-gate × two-column mis-scoping.** Inherited pre-existing hazard; the slice-2
  walk already skips column-nested gates and this slice does not change that (see *Deferred*).
- **No verdict-bearing self-check.** Switch grid, Fill-in table, Guess-the-number, Step-by-step stay
  off the mechanism.

## What slice 1 and slice 2 already paid for

Verified against local `master` (`19c399e`, PRs #139/#140 merged).

1. **The render seam reaches both leaves.** `FillGateElement.render` (`models.py:668`) and
   `SwitchGateElement.render` (`models.py:691`) both call `self._state_context(element, state, slug,
   node_pk)`, which since slice 2 returns `{el, eid, mine, mine_json, slug, node_pk}`
   (`models.py:340`). So `mine`, `mine_json`, `slug`, `node_pk` **already reach the fillgate template
   context today** — this slice only makes the template *use* them.
2. **`mine_json` is already serialized** (`json.dumps(mine)`) in the helper. No template JSON filter is
   needed or exists.
3. **The endpoint, field, migration, and lesson-context read are generic.** `element_state_save`
   (`views.py`), the `UnitProgress.element_state` store, migration 0050, and
   `build_lesson_context`'s `element_state` map all treat the blob opaquely and by join-row pk. They
   handle these two families with zero change — exactly as they handled the plain gate.
4. **`restoreGates` already enumerates both families.** `BARRIER = "[data-reveal-gate]"`
   (`reveal.js:168`) matches the fillgate `<div>` and the switchgate `<div>`; the walk buckets them by
   scope and currently `break`s on them via `if (!gate.matches(RESTORABLE)) break;` (`reveal.js:205`).
   This slice changes that one line's role (below).
5. **`cascadeFrom` already supports both option knobs.** `hideWrapper` (`reveal.js:101`) and `focus`
   (`:102`) exist; the click paths already pass `{hideWrapper: false}` for these two families
   (`fillgate.js:73`, `switchgate.js:80`). Restore adds only `{focus: false}` to that, exactly as the
   plain gate's restore does.
6. **Both widgets already have a `lock()` that defines the answered appearance.** `fillgate.js:41`
   (`reset`/`showWrong`/`lock`) and `switchgate.js:55` (`lock`) do readonly/disabled + `--done` +
   Confirm removal today, on the click path — **unchanged by this slice**. The *restore* path does not
   call `lock()`; instead the server renders the identical locked look (§2/§3) so it is correct before
   first paint (round-1 I3). No new locked state is invented — the server reproduces what `lock()`
   already produces.

## Architecture / components — five changes

### 1. `courses/state.py` — register both families under the monotone validator

`_val_revealgate` (`state.py:61`) already normalizes `{"open": true} → {"open": True}`,
false/absent → `EMPTY`, non-dict → `REJECT`. The two new families have the **identical** blob shape
and the identical monotone semantics, so they share it. Rename it family-neutral and register three
keys:

```python
def _val_open_gate(element, obj, payload):
    """{"open": True} -- monotone. Shared by every answered/clicked reveal gate
    (plain, fill, switch): a correct answer or a click is the whole gesture, and
    the blob has exactly one reachable value.

    A false/absent `open` is a well-formed "nothing to restore" -> EMPTY (drop the
    key), never REJECT (which would preserve a stale key on a well-formed request).
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"open": True} if payload.get("open") else EMPTY


# Keyed by content_type.model (the ELEMENT_MODELS namespace) -- NOT the form key
# and NOT the transfer key. Those three namespaces have been a recurring trap; the
# registry does not add a fourth.
VALIDATORS = {
    "markdoneelement": _val_markdone,
    "revealgateelement": _val_open_gate,
    "fillgateelement": _val_open_gate,     # NEW
    "switchgateelement": _val_open_gate,   # NEW
}
```

**No re-verification, no bounds.** Consistent with the module docstring: the validator constructs
`{"open": True}` rather than echoing input, so no free-text or list ever enters the stored value —
unbounded input cannot grow a single constructed boolean. The `*_check` endpoints remain the real
correctness path. A forged `open` reveals nothing the student could not already reveal with devtools,
and Reset undoes it.

**The two content-type strings are `fillgateelement` and `switchgateelement`** — Django's lowercased
class names, the same namespace as `revealgateelement`/`markdoneelement`. Not the form keys
(`fillgate` / `switchgate`) and not the transfer keys (`fill_gate` / `switch_gate`).

**The rename is not free — it requires a test edit, or the DoD suite goes RED (round-3 I1).**
`courses/tests/test_state_module.py` references `state._val_revealgate` **by name** at lines 84, 90 and
95, and asserts `VALIDATORS["revealgateelement"] is state._val_revealgate` at line 99. Renaming the
function to `_val_open_gate` makes all four raise `AttributeError`. Update those four references to
`_val_open_gate` as part of this change (the `revealgateelement` identity assertion still holds — it
now points at the renamed function). This is a required edit, listed here so it is not discovered as a
red suite mid-build.

### 2. `templates/courses/elements/fillgateelement.html` — data-state + locked render

The fillgate is a **real template**, so both changes land here (no tag-signature change).

```django
{% load i18n courses_extras %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
<div class="fillgate{% if mine.open %} fillgate--done{% endif %}" data-reveal-gate data-fillgate
     data-element-pk="{{ eid }}" data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
  {% comment %}... existing comment ...{% endcomment %}
  <form class="fillgate__form"
        data-check-url="{% url 'courses:fillgate_check' eid %}"
        data-element-pk="{{ eid }}">
    <div class="fillgate__body">
      {% if mine.open %}{% render_fill_blanks el el.canonical_answers locked=True %}
      {% else %}{% render_fill_blanks el %}{% endif %}
    </div>
    {% if not mine.open %}
      <button type="submit" class="fillgate__confirm" hidden>{% trans "Confirm" %}</button>
    {% endif %}
    <p class="fillgate__feedback" data-fillgate-feedback hidden></p>
    <span class="fillgate__msg" data-fillgate-message hidden>{% trans "Not quite — try again" %}</span>
  </form>
</div>
```

- **`data-state` / `data-state-url` / `data-element-pk` on the `<div data-reveal-gate>`.** `reveal.js`'s
  `storedOpen(gate)` reads `gate.dataset.state`, and `restoreGates` enumerates `[data-reveal-gate]` —
  so the attributes go on the barrier `<div>`, the node the walk holds. `data-element-pk` is already on
  the inner `<form>` (`fillgateelement.html:8`) for `fillgate.js`'s check POST; adding it to the `<div>`
  too lets `fillgate.js`'s new `saveOpen` (§4) read the join-row pk off the container. **This is NOT
  `reveal.js`'s `save()`** — that is bound only to plain-gate button clicks (`reveal.js:163`) and never
  runs on a fillgate div; the restore walk reads only `data-state`, it never POSTs. `data-state`
  autoescapes correctly (no `|safe`) — asserted by a test.
- **`save_url` resolved with `{% url … as save_url %}`** exactly like `revealgateelement.html:2`. In
  the editor preview the context lacks `slug`/`node_pk`, so it resolves to `""` and the save no-ops.
- **Locked render when `mine.open` — the full appearance is server-rendered, not applied by JS.**
  `render_fill_blanks` forwards a `locked` arg to `fillblank.render_inputs`, which gains it:
  `render_inputs(token_stem, submitted_values=None, locked=False)` — default `False`, so the quiz
  fill-blank caller is unaffected. When `locked`, each `<input>` is emitted with the canonical value,
  `readonly`, `class="question__blank-input is-correct"`, **and `size="max(len(value), 2)"`** —
  mirroring `fillgate.js:49`'s `inp.size = Math.max(inp.value.length, 2)`. **The `size` is not
  optional (round-2 C1).** The width-release rule at `app.css:1023-1032` is `width: auto; min-width:
  8ch`, and for a text input `width: auto` is sized by the `size` attribute (defaulting to ~20ch when
  absent) — so without `size`, a long answer renders in a fixed ~20ch box and is **clipped**,
  diverging visibly from the JS `lock()` appearance. With value + readonly + is-correct + size, the
  existing `[data-fillgate] .question__blank-input.is-correct:read-only` width-release + success
  styling (`app.css:1019-1032`) fits the box to the answer straight from the server HTML — so the
  locked answer is correct *before first paint*, the same prepaint-robust way `.reveal-armed` hides
  content, rather than a bet that `defer` beats paint. The Confirm button is suppressed when open
  (nothing to confirm), and
  `fillgate--done` is on the `<div>`. Consequently `fillgate.js` does **not** lock on boot — it only
  refrains from arming (see §4b).
- **`el.canonical_answers`** — a new read-only property on `FillGateElement` returning
  `[a[0] if a else "" for a in (self.answers or [])]` (first accepted alternative per blank). Cheap,
  pure, testable. `answers` is `list[list[str]]` (`models.py:665`, and `fillgate_check` iterates it at
  `views.py:808-811`), so `a[0]` is the canonical spelling. Placing it on the model (not in the
  template) keeps the template free of list-indexing logic.

### 3. `courses/templatetags/courses_extras.py` `render_switch_gate` — signature change

The switchgate's outer `<div data-reveal-gate>` is **built in Python** (`courses_extras.py:264-270`),
not in a template — `switchgateelement.html` is a one-line passthrough (`{% render_switch_gate el eid
%}`). So the attributes and the locked render land in the tag, and **the tag signature must change** to
receive `mine_json` and `save_url` (the URL is resolved in the template, matching the plain gate and
fillgate rather than calling `reverse` a second way inside the tag).

`switchgateelement.html`:

```django
{% load courses_extras %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
{% render_switch_gate el eid mine mine_json save_url %}
```

**`i18n` is deliberately not loaded** — the switchgate emits no `{% trans %}` in the template; every
user string (`Choose ▾`, `Confirm`, `Try again`) comes from `_()` inside `render_switch_gate`. (The
current file already loads only `courses_extras`; keep it that way. An earlier draft of this spec's
snippet loaded `i18n` unnecessarily — do not reintroduce it.)

`render_switch_gate(el, eid, mine=None, mine_json="{}", save_url="")`:

- Emit `data-state="{mine_json}"` and `data-state-url="{save_url}"` on the outer `<div>`, alongside the
  existing `data-element-pk` / `data-check-url`. **`mine_json` is passed pre-serialized from the
  template** (it is already in `_state_context`), **not** re-serialized in the tag —
  `courses_extras.py` does **not** import `json` today, and adding `json.dumps` here would be the exact
  `NameError`-on-first-render trap slice 2 hit in `models.py`. The tag receives `mine` (the dict) only
  to branch on `(mine or {}).get("open")` for the locked render — **null-safe: the `mine=None` default
  must not call `.get` directly**; the attribute string comes from `mine_json`. Passing both keeps the
  tag out of the serialization business entirely, parallel to how `fillgateelement.html` uses
  `{{ mine_json }}` for the attribute and `{% if mine.open %}` for the branch.
- **When `mine.open`:** render the cycler with `options[answer]` **visible** (not `hidden`) and the
  placeholder hidden, add `switchgate--done` to the `<div>`, mark the cycler `disabled`, and omit the
  Confirm button — the **complete** answered appearance, server-rendered so it is correct before first
  paint (no JS `lock()` on boot). `answer` is `el.answer` (`models.py:684`), a 0-based index into
  `el.options`; the correct option is the one the student cycled to, so this is verbatim, not merely
  canonical. The one thing the server cannot do is typeset the shown option's inline math — that stays
  a boot-time client step (see §4b). **Render bounds-safely (round-2 M2):** change the options generator
  to `enumerate(el.options)` so it yields `(k, o)`, and un-hide the span where `k == answer`, rather
  than indexing `options[answer]`. (The current generator at `courses_extras.py:242-246` yields a bare
  `(mark_safe(o),)` with **no** index, so adding `enumerate` is part of this change — the index is not
  already available.) `SwitchGateElementForm` clamps `0 <= answer < len(options)` at save
  (`element_forms.py:425`), but a transfer/import or a direct `.save()` (which only sanitizes options,
  `models.py:687-689`) could persist an out-of-range `answer`; the per-index compare degrades that to
  "no option shown" instead of an `IndexError` → 500 on the lesson page.

**Barrier attribute unchanged.** The `<div class="switchgate" data-reveal-gate data-switchgate>` shape
that `isGateWrapper` and the prepaint CSS match (slice-2 spec §4) is preserved — the new attributes are
additive on the same element.

### 4. `fillgate.js` / `switchgate.js` — save on correct, skip-arm on boot

**(a) Save `{"open": true}` on a correct answer.** Add a `saveOpen(container)` mirroring
`reveal.js:27-38`'s `save` (fire-and-forget, `keepalive`, ignore body, `.catch` swallows), reading
`data-state-url` + `data-element-pk`. It is a **per-file local**, distinct from — and identically
shaped to — `reveal.js`'s `save` (there is no shared module). Call it in the existing success branch,
right after the click-path `lock()` + cascade. **The click-path `lock()` is unchanged**; only the
*boot* path in (b) changes.

```js
// fillgate.js submit(), inside `if (data.correct)`:
var container = lock(form);
if (window.libliRevealCascade && container) {
  window.libliRevealCascade(container, { hideWrapper: false });
}
if (container) saveOpen(container);   // NEW: persist {"open": true}; guarded like the cascade above
```

```js
// switchgate.js submit(), inside `if (data.correct)`:
lock(container);
if (window.libliRevealCascade) {
  window.libliRevealCascade(container, { hideWrapper: false });
}
saveOpen(container);   // NEW -- container is submit()'s own arg, always present
```

`saveOpen` reads `container.dataset.stateUrl` (fillgate: the `.fillgate` div; switchgate: the
`.switchgate` div) and `container.dataset.elementPk`, guards `if (!url) return;` (editor preview) and
`if (!eid) return;`, POSTs `{"element": eid, "state": {"open": true}}`. `csrf()` already exists in both
files. Duplication of the ~10-line saver across `reveal.js` / `fillgate.js` / `switchgate.js` is the
project's established no-module-system convention (slice-2 spec §5e records the same call for `csrf()`).

**(b) Skip arming on boot when stored-open.** The locked *appearance* is server-rendered (§2/§3), so
the boot path does **not** call `lock()`. It only (i) does not arm the real submit/check path (no
re-check of an already-correct answer) — **but still binds a `preventDefault`-only submit handler**, so
a stored-open gate cannot navigate away (see below) — and (ii) for switchgate, typesets the shown
option's inline math. The short-circuit sits **after** the re-entry-guard flag is set, so an editor
fragment-swap re-run does not re-process a stored-open gate:

```js
// fillgate.js initOne(form):
if (form.dataset.fillgateReady === "1") return;
form.dataset.fillgateReady = "1";
var container = form.closest("[data-fillgate]");
if (storedOpen(container)) {
  // Server rendered it locked; do NOT arm Confirm or the real submit(). But still block
  // implicit submission (round-3 I2, below): bind a preventDefault-only handler and return.
  form.addEventListener("submit", function (e) { e.preventDefault(); });
  return;
}
var btn = form.querySelector(".fillgate__confirm");
if (btn) btn.hidden = false;         // arm Confirm (unanswered path, unchanged)
form.addEventListener("submit", ...);
```

```js
// switchgate.js initOne(container):
if (container.dataset.switchgateReady === "1") return;
container.dataset.switchgateReady = "1";
if (storedOpen(container)) { typesetMath(container); return; }   // NEW: typeset THEN return
var cycler = container.querySelector("[data-switchgate-cycler]");
... // arm Confirm, bind advance/submit, typesetMath (unanswered path, unchanged)
```

- **The `preventDefault`-only handler on the restored fillgate is load-bearing (round-3 I2).** A
  single-blank fill gate is a `<form>` with one text control and (when open) **no submit button**, so
  by HTML implicit-submission rules, pressing Enter in the readonly blank submits the form. The form's
  `action` is empty (the check URL lives in `data-check-url`, not `action` — `fillgateelement.html:3`),
  so that submit is a **GET navigation to the lesson URL** with `?blank=…` — a spurious full reload and
  scroll loss. The click path never hits this because it binds a real submit listener that
  `preventDefault`s; a bare `return` on restore would make restore **strictly worse** than the click
  path. The `preventDefault`-only handler restores the guarantee without re-checking. **Switchgate is
  exempt** — it has no `<form>` (the cycler/Confirm are `<button type="button">`s in a `<div>`), so
  there is no implicit submission to block; its boot short-circuit `return`s directly after
  `typesetMath`.
- **`typesetMath` before the switchgate `return` is load-bearing (round-1 C1).** Switchgate is the one
  family whose inline math is typeset *only* by its own `initOne` (`switchgate.js:108`); `math.js`'s
  global `renderInlineText(document)` covers `.fillgate` but **excludes** `.switchgate`. A bare
  `return` would leave a stored-open switchgate's shown option rendering raw LaTeX on every reload.
  Fillgate needs no such call — `.fillgate` is in the global list.
- **`storedOpen(el)` here is a small per-file local** reading `el.dataset.state` and checking
  `blob.open === true` in a `try/catch` — the same 4-line shape as `reveal.js:16-25`, duplicated per
  the no-module-system convention; not exported, and distinct from `reveal.js`'s identically-shaped
  `storedOpen`.
- **The short-circuit is placed AFTER the `...Ready` flag is set (round-1 M3).** So the re-entry guard
  always latches, and an editor fragment-swap re-run over an already-processed stored-open gate no-ops
  on the guard rather than re-typesetting or re-processing it.
- **No boot `lock()`, so no flash and no double-styling.** Because §2/§3 render the readonly/is-correct
  inputs (fillgate) and the disabled cycler + shown option + `--done` (switchgate) server-side, the
  locked look is in the initial HTML and styled by existing CSS before first paint — the no-flash
  property rests on the same prepaint-robust footing as content hiding, not on `defer` timing. Verified
  by screenshot (see *Testing*).

**No cross-file coordination.** `reveal.js` restores the *content* by reading `data-state` on the
`<div>` and cascading; `fillgate.js`/`switchgate.js` read the same `data-state` only to decide not to
arm. Each reads the attribute independently; neither calls the other.

### 5. `courses/static/courses/js/reveal.js` — the walk restores all three families

Today the walk (`reveal.js:199-212`) treats fill/switch gates as pure barriers:

```js
if (!isGateWrapper(ownWrapper(gate, scope), scope)) continue; // (a) mis-scoped
if (!gate.matches(RESTORABLE)) break;   // fill/switch gate: a barrier
if (!storedOpen(gate)) break;           // closed gate: prefix-closure
cascadeFrom(gate, { hideWrapper: true, focus: false });
```

Once fill/switch gates carry `data-state`, they become **restorable barriers**. The
`matches(RESTORABLE)` line changes role — from *"break on any non-plain gate"* to *"choose
`hideWrapper` by family"*:

```js
if (!isGateWrapper(ownWrapper(gate, scope), scope)) continue; // (a) mis-scoped — unchanged
if (!storedOpen(gate)) break;           // closed OR unanswered gate: prefix-closure
// Plain gate self-consumes (hideWrapper:true); fill/switch keep their answered Q&A (false),
// matching each family's click path (reveal(btn) vs fillgate.js:73 / switchgate.js:80).
cascadeFrom(gate, { hideWrapper: gate.matches(RESTORABLE), focus: false });
```

**Why this preserves every slice-2 invariant:**

- **Prefix-closure is unchanged in behaviour, only in mechanism.** An **unanswered** fill/switch gate
  renders `data-state="{}"` (no stored blob) → `storedOpen` returns false → `break` — the walk stops,
  exactly as the old `matches(RESTORABLE) break` made it stop. A closed **plain** gate stops the same
  way. So a stored-open gate behind an unanswered gate still does not leak.
- **The `BARRIER` enumeration is still load-bearing and unchanged.** `restoreGates` still enumerates
  `[data-reveal-gate]` (all three families), so the walk still *sees* an unanswered fill/switch gate in
  order to `break` on it. Narrowing the enumeration to `RESTORABLE` would skip it and let a later
  stored-open gate leak — the slice-2 headline leak, still guarded by the enumeration.
- **`hideWrapper` per family matches the click path.** Plain gate → `true` (self-consume);
  fill/switch → `false` (keep the answered Q&A visible). This is why the answered widget stays on
  screen after restore instead of vanishing.
- **`RESTORABLE`'s other meaning is untouched.** `initRevealGates` still binds click handlers to
  `button.reveal-gate[data-reveal-gate]` only (`reveal.js:176-178`); fill/switch gates get their
  handlers from their own JS. `RESTORABLE` now serves two readers (init-binding = plain only; the
  walk's `hideWrapper` choice), which agree on "the plain gate is a `<button.reveal-gate>`".

**`focus: false` is retained** — boot restore must not steal focus or scroll (slice-2 spec §5a). The
per-gate `try/catch` `break`, the null-scope discard, and the GROUP-then-walk structure are all
**unchanged**.

## Data flow

**Save (student answers correctly):**

```
type/choose -> Confirm -> submit(): POST /courses/.../<eid>/{fillgate|switchgate}_check
  -> {"correct": true}
  -> lock(container)                                   [readonly/disabled, --done, Confirm removed]
  -> libliRevealCascade(container, {hideWrapper:false}) [reveal following siblings; keep the Q&A]
  -> saveOpen(container): POST /courses/<slug>/u/<node_pk>/state/
                          {"element": <join_pk>, "state": {"open": true}}
       -> validate_state -> VALIDATORS["fillgateelement"|"switchgateelement"] -> {"open": True}
       -> merge under the join-row pk -> 200 (body ignored; monotone)
  (wrong answer)                                        -> showWrong / feedback; NOTHING persisted
```

**Restore (lesson GET, gate previously answered):**

```
build_lesson_context -> element_state = {join_pk: {"open": True}, ...}   [slice 1/2, unchanged]
render_element -> obj.render(element, state, slug, node_pk)
  -> _state_context: mine = {"open": True}; mine_json = '{"open": true}'
  -> fillgateelement.html: data-state='{"open": true}', --done, blanks pre-filled canonical, no Confirm
     switchgate tag:       data-state='{"open": true}', --done, options[answer] shown, no Confirm

reveal.js IIFE (defer; after parse, before paint):
  initRevealGates(document)   -- plain gates only (fill/switch bound by their own JS)
  restoreGates(document):
    per bucket, in order: mis-scope? continue. !storedOpen? break.
      cascadeFrom(gate, {hideWrapper: gate.matches(RESTORABLE), focus:false})
        -> fill/switch: reveal following siblings, KEEP the widget (hideWrapper:false), no focus

fillgate.js / switchgate.js IIFE (defer; own files):
  initOne: if stored-open -> do NOT arm the real submit (server already rendered the locked look);
           fillgate binds a preventDefault-only submit handler (block Enter implicit-submit);
           switchgate (no <form>) instead typesets the shown option's inline math, THEN returns
```

## Error handling

| Case | Behaviour |
|---|---|
| Correct answer | `lock` + cascade + `saveOpen` → `{"open": True}` stored under the join-row pk |
| Wrong answer | Feedback only; **nothing persisted**; reload → fresh editable widget |
| Restore, stored-open | Content cascades (reveal.js); widget renders locked with the answer **server-side** (readonly/is-correct or disabled cycler); `initOne` skips arming (switchgate also typesets math) |
| Restore, unanswered gate | `data-state="{}"` → `storedOpen` false → walk `break`s that scope (prefix-closure); widget editable |
| `{"open": false}` / no `open` key POSTed | Validator → **EMPTY** → key dropped (well-formed "nothing to restore", not a rejection) |
| Non-dict payload | **REJECT** → stored key untouched → 200 echoing it |
| Extra keys | Normalized to `{"open": True}` (server owns the stored shape) |
| Drifted stored blob (`{"open": "yes"}`) | `storedOpen`'s `=== true` → false → walk `break`s; widget stays editable, content re-earnable. `fillgate.js`/`switchgate.js` `storedOpen` likewise false → widget arms normally |
| Save fails (network / 4xx / 5xx) | DOM untouched, response ignored. **Monotone: never re-hide, never re-lock** |
| Author edits the accepted answer after a student opened the gate | Already-open gate shows the **new** canonical answer; content stays revealed. Self-heals, never stale |
| Gate nested in a two-column column | Restore: skipped by the walk (mis-scoped `continue`) — neither restores nor vetoes. Save: not scope-guarded (see *Deferred*) |
| Editor preview, initial load | `data-state="{}"` (no `element_state` in editor context) → no cascade, no lock; widget arms as a normal preview |
| Editor preview, save | `save_url` → `""` → `saveOpen` no-ops before `fetch` |
| Anonymous / JS disabled | No save, no restore; watchdog disarms `reveal-armed`; content never trapped |

## Testing

Follows the slice-2 falsifiability doctrine: **every guard a test claims to cover is falsified on the
way in** (delete/relax the guard → confirm RED → restore); a guard that stays green when deleted is
either a "No" (defence-in-depth, backstopped elsewhere — named, not tested) or the test is dropped.
Source-presence greps are vacuous and are not evidence.

### Server-side (pytest)

- **Validator, both families:** `_val_open_gate` under `fillgateelement` and `switchgateelement` →
  `{"open": true}`→`{"open": True}`; `{"open": false}`→EMPTY; no key→EMPTY; non-dict→REJECT;
  extra keys normalized. (Falsify: unregister a key → `validate_state` returns REJECT → round-trip
  test RED.)
- **Endpoint round-trip:** a `saveOpen`-shaped POST for a fillgate/switchgate join row stores
  `{"open": True}` and echoes it; an EMPTY drops the key. (Reuses slice-1 endpoint tests' shape.)
- **`FillGateElement.canonical_answers`:** `[["color","colour"],["x"]] → ["color","x"]`; `[]` and
  `[[]]` handled (`["", ...]`). (Falsify: return `a[-1]` → RED on a multi-alternative fixture.)
- **The render tests must not straddle the int/str key seam (round-2 I1).** `_state_context` looks up
  `mine = (state or {}).get(eid)` with `eid = element.pk`, an **int** (`models.py:358-359`); the stored
  `UnitProgress.element_state` is **str**-keyed and `build_lesson_context` int-coerces it at
  `views.py:376`. So a test has two valid paths and must pick one, not mix them: **(a)** render directly
  — `obj.render(element=el, state={el.pk: {"open": True}}, slug=…, node_pk=…)` with an **int** key,
  mirroring `test_render_seam.py:78`; or **(b)** seed `UnitProgress.element_state = {str(el.pk): {"open":
  True}}` and render through `build_lesson_context` / the lesson view. Seeding a **str** key and calling
  `render()` **directly** silently misses the int lookup → `mine = {}` → the *unanswered* branch renders
  → the stored-open assertions fail (or a paired unanswered test passes vacuously). The bullets below
  assume path (a) unless they name the lesson view.
- **fillgate template, stored-open (path (a), int key):** with `state = {el.pk: {"open": True}}`,
  the rendered `<div class="fillgate ... fillgate--done" ... data-state="...">` carries `data-state`
  that **HTML-unescapes then `json.loads` to `{"open": true}`** (the round-trip the slice-2 spec
  details — `html.unescape` a `data-state="([^"]*)"` capture, then `json.loads`; **falsify by adding
  `|safe`** → truncates at the first `"` → RED, and catches the `repr`-vs-JSON bug); the blanks render
  with the **canonical value** (`value="color"`), each carrying **`readonly`** and **`is-correct`**
  (the server-rendered locked appearance — falsify by rendering the open branch without `locked=True`
  → no `readonly` → RED); and **no `fillgate__confirm` button is present**.
  Fixture MUST seed a non-empty blob or the `|safe` falsification stays green (slice-2 lesson).
- **fillgate template, unanswered:** `data-state="{}"`, blanks empty, Confirm present.
- **switchgate tag, stored-open:** `data-state` round-trips to `{"open": true}`; `switchgate--done` on
  the `<div>`; `options[answer]` rendered **without** `hidden` and the placeholder hidden; no
  `switchgate__confirm`. (Falsify: render `options[0]` unconditionally → RED on an `answer != 0`
  fixture.)
- **switchgate tag, unanswered:** `data-state="{}"`, placeholder shown, options hidden, Confirm
  present — the pre-existing render, unregressed.
- **The DOM chain is preserved** — assert (regex over the decoded body, no HTML parser in this repo)
  that the barrier `<div>` is still the direct child `isGateWrapper` matches, both top-level and
  tab-nested; **falsify by wrapping it in a `<div>`** → RED. (Guards §4's "no wrapper" constraint for
  both families, the same way the slice-2 spec guards the plain gate.)

### e2e (Playwright, real gestures only — `tests/test_e2e_fillgate.py`, `tests/test_e2e_switchgate.py`)

These files already have the fixtures (`_fillgate` round-tripping `{{answer}}` markup via
`fillblank.parse`; the switchgate seeder) and already exercise the click paths, so the new tests are
added **here**, not in `test_e2e_reveal_gate.py`.

- **Fill gate, full round-trip:** type the correct answer → Confirm → content cascades and the blank
  locks → **await the `.../state/` POST** (`page.expect_response`, mirroring
  `test_e2e_markdone.py:86`, so the fire-and-forget save commits before reload) → reload → content
  **still revealed** AND the blank shows the answer **locked** (readonly, `fillgate--done`) AND **no
  Confirm button**. Together these cover the server-rendered locked appearance and the boot skip-arm;
  without them a restore that armed the widget or dropped the locked render would leave an editable
  answer green everywhere else.
- **Restored fill gate does not navigate on Enter (round-3 I2) — pin the gesture, don't just check the
  button is gone.** After the reload, focus the restored (readonly) blank and press `Enter`; assert the
  page did **not** navigate (URL unchanged, no reload) and **no** `fillgate_check` POST fired. (Falsify:
  drop the `preventDefault`-only handler from the boot short-circuit → Enter implicitly submits the
  single-blank form → GET navigation to the lesson URL → RED. "No Confirm button present" is a
  *different, weaker* guarantee and would pass vacuously without this gesture.)
- **Choose gate, full round-trip:** cycle to the correct option → Confirm → cascade + lock → await
  save → reload → content revealed, cycler shows the correct option **disabled**, `switchgate--done`,
  no Confirm.
- **Choose gate restores with math typeset (round-1 C1):** seed a stored-open switchgate whose correct
  option contains inline `\(...\)` math → reload → the shown option renders **typeset** (no raw
  `\(`/`\)` in the rendered text). (Falsify: drop `typesetMath` from the boot short-circuit → RED. This
  is the only guard on C1; `.switchgate` is absent from `math.js`'s global list.)
- **Wrong attempt persists nothing:** answer wrong → feedback shows → reload → widget **fresh and
  editable**, content **hidden**, **no** `.../state/` request was made. (Falsify: move `saveOpen` out
  of the `if (data.correct)` branch → a wrong attempt POSTs → RED.)
- **Prefix-closure across the new family:** a stored-open plain gate **after an unanswered fill gate**
  (same scope) → the plain gate does **not** restore (no `.reveal-shown` past the fill gate). Seed via
  DB. (Falsify: change the walk's `!storedOpen(gate) break` so an unanswered gate does not stop →
  RED. Also falsified by narrowing `restoreGates`'s enumeration to `RESTORABLE`, which skips the
  unanswered fill gate entirely → the plain gate leaks → RED.) This is the test that proves the
  `matches(RESTORABLE) break → storedOpen break` change is safe.
- **Answered fill gate restores AND lets a later gate through:** a stored-open fill gate followed by a
  stored-open plain gate (same scope) → **both** restore (fill gate's content revealed, widget kept
  and locked; plain gate's content revealed, button consumed). (Falsify: keep the old
  `matches(RESTORABLE) break` → the fill gate stops the walk → the later plain gate does not restore →
  RED.)

### Visual — the no-flash property (round-1 I3)

The locked appearance is server-rendered specifically so it is correct before first paint. Confirm it
with a **screenshot** (per [[verify-ui-with-screenshots]]) of a stored-open fill gate on load: the
canonical answer shows in full (fit to content by the server-emitted `size` + `.is-correct:read-only`
width-release, not clipped) and reads as locked, with no flash of an editable/clipped input. **The
fixture answer MUST be longer than ~20 characters (round-2 C1):** a short answer fits the default
~20ch box whether or not `size` is emitted, so it would pass vacuously and hide the clipping
regression the `size` attribute exists to prevent. This is a verification step, not an automated test
— paint timing is not deterministically assertable — but the robustness now rests on server-rendered
HTML + existing CSS, not on `defer` beating paint.

### Regression — the shared cascade engine has only e2e coverage

This slice edits `reveal.js`'s walk and both widgets' JS. Per the slice-2 spec, "non-e2e suite green"
is **not** sufficient. The DoD runs, green:

| File | Guards |
|---|---|
| `tests/test_e2e_reveal_gate.py` (7 pre-existing) | plain-gate cascade, `hideWrapper:true`, watchdog, quiz inertness, the two focus tests — the walk change must not regress them |
| `tests/test_e2e_fillgate.py` (pre-existing + new) | fillgate click path, `focusTargetIn`'s `[data-fillgate]` branch, the new restore tests |
| `tests/test_e2e_switchgate.py` (pre-existing + new) | switchgate click path, `focusTargetIn`'s `[data-switchgate]` branch, the new restore tests |

Plus: full non-e2e suite; `ruff check` **and** `ruff format --check`; `makemigrations --check` (no
migration); `manage check`; `test_po_catalog_clean` unaffected (no new strings).

## Deferred, and why this slice forecloses nothing

- **The verdict-bearing self-checks** (Switch grid, Fill-in table, Guess-the-number, Step-by-step).
  They show per-item ✓/✗ the client cannot re-derive, so each needs the carry-verdict-in-blob vs
  re-check-on-boot decision. This slice's monotone `{"open": true}` substrate touches none of that:
  their blobs are per-type and opaque to the storage layer, and their restore is per-element JS.
- **Wrong-attempt persistence / per-blank marker restore.** Requires a stored verdict or
  re-check-on-boot (see *Scope decisions*). Left for the verdict slice if ever wanted.
- **The reveal-gate × two-column mis-scoping.** Pre-existing on the click path; the slice-2 walk
  already skips column-nested gates and this slice's `(a) mis-scoped continue` is unchanged. The save
  path is not scope-guarded (a column-nested gate still POSTs a write-only, always-skipped key) — the
  same accepted trade the slice-2 spec records, for the same reasons (harmless, bounded, becomes
  correct if the mis-scoping is ever fixed). On the tidy-up backlog.

## Execution notes

- **Isolate the test DB per worktree:** `DATABASE_URL=…/libli_<slug>` in the worktree `.env` (the role
  has CREATEDB). Concurrent worktrees collide on `test_libli`; the symptom is *errors, not failures*.
  A concurrent session is often active on this machine.
- **`ruff` / `pytest` / `python` are not on PATH in bash** — use `uv run`.
- Run the heavy suite with **`-n auto`**; serial exceeds a subagent's 600s watchdog.
- **e2e needs an explicit `-m e2e`** — otherwise `addopts = -q -m 'not e2e'` deselects the file and
  pytest exits **5, looking like success**. Run focused e2e **foreground only** (a backgrounded
  `-m e2e` leaves runaway browsers).
- **Verify the main checkout with `git status`** — never infer "master untouched" from a worktree
  existing; subagents can write outside their stated cwd.
