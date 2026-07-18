# Student practice state — graded self-checks (Switch grid, Fill-in table, Guess-the-number) onto client-restore

> **SCOPE: the three *graded* self-check elements — Switch grid (`SwitchGridElement`), Fill-in table
> (`FillTableElement`), and Guess-the-number (`GuessNumberElement`) — brought onto the client-restore
> mechanism, correct-only, together but alone.** Each locks today when the student answers it fully
> correctly; this slice makes that locked, all-correct state survive a page reload.
>
> **The stepper stays out.** Step-by-step (`StepperElement`) is *ungraded* — no `*_check` endpoint, no
> answer field, its own model docstring says "no persistence, no endpoint." Its restorable state is
> *how many steps were revealed*, a monotone progressive-reveal count, not a correct/done flag. That is
> a different mechanism and gets its own later spec.
>
> **Prior slices this builds on and reuses wholesale:** Slice 1 (the substrate: `UnitProgress.element_state`,
> migration 0050, the render seam, `element_state_save`, `progress_reset`) shipped as **PR #139**.
> Slice 2 (the plain reveal gate as the first client-restoring element: `mine_json`, the `element_state`
> ambient-key, `restoreGates`) shipped as **PR #140**. The two answered reveal-gates (Fill-in-&-confirm,
> Choose-&-confirm) shipped as **PR #147** and established the *correct-only, monotone-blob,
> server-renders-the-locked-answer* pattern this slice copies one element-family over.
>
> **Reading rule.** "The gate slice" means
> `docs/superpowers/specs/2026-07-17-student-practice-state-fill-switch-gate-restore-design.md`. Its
> mechanisms — the monotone validator, `data-state`/`data-state-url` on the widget div, the
> server-rendered locked appearance gated on the stored flag, the boot-time skip-arm, and the
> falsifiability doctrine — are the substrate this slice extends, not re-litigates.

## Purpose

Make a student's **fully-correct** graded self-check survive a page reload — the locked, all-green
completed appearance the widget shows the moment the last cell/cycler/guess lands correct.

Today, a student who completes a Switch grid, Fill-in table, or Guess-the-number sees the widget lock:
every cycler snaps to its correct option and disables; every table cell shows correct and goes
readonly; the number input locks with its success message. On reload, nothing persists — the widget
resets to blank/editable and the demonstrated, completed work is gone. This is the same class of loss
the gates fixed in PR #147, one element-family over.

The gate slice proved the cheapest form of restore: a **monotone** correct-only flag, with the correct
answer **rendered server-side** from the element's own answers rather than stored. These three
self-checks are monotone in exactly the same way — they lock **only** on *all-correct* — so they
inherit that pattern unchanged. There is **no verdict to store**: a completed self-check is all-green,
and "all-green" is derivable from the model's own answer fields.

## Scope decisions (settled in brainstorming)

**Completed-correct only.** Only the fully-correct, locked state survives. A wrong or *partial* attempt
persists nothing and restores to a fresh, editable widget. Persisting a partial attempt was considered
and dropped: to restore its per-cell red ✗ markers the client would need the server's per-cell verdict,
available only by **storing the verdict** (frozen stale the moment an author edits an accepted answer —
the doctrine `state.py` forbids) or **re-POSTing to `*_check` on every load** (the re-check-on-boot
mechanism reserved for a future slice). Both are avoided here. This is the decision that makes the
"verdict problem" disappear: a completed self-check has no interesting verdict — every cell is correct.

**The blob is monotone `{"done": true}`.** One reachable value, like the gates' `{"open": true}` but a
key that reads correctly for a self-check that does not gate content. The completed answer is **not**
stored; it is rendered server-side from each model's own answer fields, gated on `mine.done`.
Consequences, all accepted:

- **No free-text / no verdict enters the blob**, so no caps and no stale-verdict hazard.
- **The displayed answer self-heals.** If an author edits an accepted answer after a student completes
  the element, the restored locked state shows the *new* canonical answer. Correct by construction.
- **Canonical, not verbatim** (Fill-in table). A cell that accepts several pipe-delimited spellings
  shows the **first** alternative, which may differ from the exact variant the student typed. Accepted.
  Switch grid has no ambiguity (the correct option is the single index `answer`); Guess-the-number shows
  the canonical `target` (the student's exact within-tolerance guess is not stored — see below).

**Guess-the-number restores the target value.** The locked input shows the formatted `target` (the
canonical correct number), readonly, consistent with how the other two show their answers. The student
already solved it, so this is not a spoiler; their exact within-tolerance guess is not persisted
(monotone blob), so the canonical target is what is displayed.

**A shared JS state helper is extracted now.** The gate slice duplicated `storedOpen`/`saveOpen` across
`fillgate.js` and `switchgate.js` (a logged tidy-up-backlog item). This slice would add three more
copies. Instead it extracts a single shared global — `window.libliState` with `storedFlag(el, key)`
and `saveFlag(container, stateObj)` — refactors the two gate widgets onto it, and uses it for the three
new widgets. This closes the existing duplication debt rather than growing it (a targeted improvement
to code this slice touches).

### Non-goals

- **No new element type.** `ELEMENT_MODELS` does not change; the `len(ELEMENT_MODELS)` /
  `ELEMENT_MODELS[-1]` count-asserts in `tests/test_transfer_schema.py` and
  `tests/test_models_multigrid.py` are not triggered.
- **No migration.** `element_state` exists (slice 1). `makemigrations --check` stays clean.
- **No verdict storage, no re-check-on-boot, no partial/wrong-attempt restore, no per-cell marker
  restore** (see *Scope decisions*).
- **No change to `switchgrid_check` / `filltable_check` / `guessnumber_check`.** They remain the sole
  grader of a live attempt; this slice only persists the *completed* outcome and re-renders it.
- **No new user-visible strings** — no `makemessages` pass. `test_po_catalog_clean` stays green. All
  labels (`Confirm`/`Check`, success messages) already exist.
- **No `reveal.js` change.** None of these three emit `[data-reveal-gate]`, gate following content, or
  join the `restoreGates` walk. Restore here is purely each widget restoring its own locked appearance.
- **Stepper (Step-by-step) is deferred** to its own spec (ungraded, different mechanism).

## What the prior slices already paid for

Verified against `master` (PRs #139/#140/#147 merged).

1. **The state substrate is generic and untouched.** `element_state_save` (`views.py`), the
   `UnitProgress.element_state` store keyed by join-row pk, migration 0050, and `build_lesson_context`'s
   string→int-coerced `element_state` read all treat the blob opaquely. They handle three more families
   with zero change — exactly as they handled the gates.
2. **`mine_json` is already serialized** (`json.dumps(mine)`) in `ElementBase._state_context`
   (`models.py:341`). No template JSON filter is needed or exists.
3. **All three `render()` overrides already call `_state_context`.** `SwitchGridElement.render`
   (`models.py:754`), `FillTableElement.render` (`models.py:937`), `GuessNumberElement.render`
   (`models.py:727`) build the full `{el, eid, mine, mine_json, slug, node_pk}` context. **But two of
   the three then discard most of it** (see the render-path gap below).
4. **Each widget already has a lock path that defines the completed appearance.** `switchgrid.js`
   `lock()` (adds `switchgrid--locked`, hides Confirm), `filltable.js` `lock()` (disables inputs, hides
   Confirm), `guessnumber.js` correct branch (readonly, `guessnumber--done`, removes Check). The
   *restore* path does **not** call `lock()`; the server renders the identical locked look so it is
   correct before first paint. No new locked state is invented — the server reproduces what `lock()`
   already produces.

### The render-path gap this slice must close

The three elements differ in how markup is produced, which determines where `data-state` lands:

| Element | Renders via | Gets state context in the DOM today? |
|---|---|---|
| Switch grid | shim template → **positional tag** `render_switch_grid(el, eid)` | No — tag signature drops `mine`/`mine_json`/`slug`/`node_pk` |
| Guess-the-number | shim template → **positional tag** `render_guess_number(el, eid)` | No — same tag-signature drop |
| Fill-in table | **real template** `filltableelement.html` | Full ctx reaches the template context, but the markup ignores `mine`/`mine_json` |

So the two tag-rendered elements need their tag signatures widened (exactly as `render_switch_gate` was
in PR #147); the real-template element gets `data-state`/`data-state-url` added to its markup directly
(exactly as `fillgateelement.html` was).

## Architecture / components — five changes

### 1. `courses/state.py` — a monotone `done` validator, three keys

Add a sibling to `_val_open_gate`:

```python
def _val_done(element, obj, payload):
    """{"done": True} -- monotone. A graded self-check (switch grid / fill-in table /
    guess-the-number) that has been answered fully correctly. The whole gesture has one
    reachable value; the completed answer is NOT stored -- it is rendered server-side
    from the element's own answers, gated on this flag.

    A false/absent `done` is a well-formed "nothing to restore" -> EMPTY (drop the key),
    never REJECT.
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"done": True} if payload.get("done") else EMPTY
```

Register three keys (content_type.model namespace, the recurring 3-namespace trap):

```python
VALIDATORS = {
    "markdoneelement": _val_markdone,
    "revealgateelement": _val_open_gate,
    "fillgateelement": _val_open_gate,
    "switchgateelement": _val_open_gate,
    "switchgridelement": _val_done,
    "filltableelement": _val_done,
    "guessnumberelement": _val_done,
}
```

`_val_done` is deliberately a **separate small validator**, not a `_val_monotone_flag(key)` factory
shared with `_val_open_gate`. This matches `state.py`'s existing convention of named per-family
validators (`_val_markdone`, `_val_open_gate`), keeps each independently readable, and the duplication
is two trivial lines — unlike the JS `storedFlag`/`saveFlag` case (§4), which was five near-identical
copies with real drift risk and so is worth extracting. (A factory is an acceptable alternative if the
plan prefers it; not required.)

### 2. Model helpers — the canonical completed answer, per element

- **Switch grid**: already carries the correct index per cycler (`lines[i].cyclers[j].answer`). No new
  field; the render walks the existing structure. The un-hide is **bounds-safe** — compare index
  equality, never `options[answer]` — so an out-of-range **author-set** `answer` index (e.g. from an
  edited `options` list or a transfer/import; **not** the `element_state` blob, which only ever holds
  `{"done": true}`) renders nothing, not a 500.
- **Fill-in table**: add a `canonical_cells` property that returns a grid the **same shape as
  `normalize_data(data)["cells"]`** — static cells copied through unchanged; each answer cell's
  `answer` replaced by its first pipe-delimited alternative (`courses/filltable.py:split_alternatives`
  `[0]`; empty/absent → empty string). **Not** positional like `FillGateElement.canonical_answers`:
  `filltableelement.html` is a real Django template iterating `{% for row in data.cells %}{% for cell
  in row %}`, and Django cannot do runtime-variable 2-D indexing (`{{ grid.<r>.<c> }}` needs literal
  digit indices) nor `zip`. So `render()` substitutes `canonical_cells` **wholesale** for
  `ctx["data"]["cells"]` when `mine.done`, and the existing loop + `_filltable_cell.html` include run
  unchanged, branching only on `mine.done` for the readonly/locked styling.
- **Guess-the-number**: a display-formatted `target` via the **existing** helper
  `courses.guessnumber.format_target()` (`format(Decimal(target).normalize(), "f")`) — **not** a fresh
  normalizer. Bare `.normalize()` yields E-notation for round numbers (`100` → `1E+2`, `40401` →
  `4.0401E+4`), the exact defect `format_target`'s docstring records already fixing once; the new
  `canonical_target` property must reuse or thin-wrap `format_target`, never reinvent it.

### 3. Server-rendered "done" appearance (gated on `mine.done`)

- **Switch grid** — `render_switch_grid(el, eid)` → `render_switch_grid(el, eid, mine=None,
  mine_json="{}", save_url="")`; the shim `switchgridelement.html` passes `mine mine_json save_url`.
  When `mine.done`: every cycler shows its correct option (bounds-safe per-index un-hide), cyclers
  `disabled`, Confirm omitted, `switchgrid--success` (+ `switchgrid--locked` on cyclers). The
  `.switchgrid` div gains `data-state="{{ mine_json }}"` (autoescaped, never `|safe`) and
  `data-state-url`.
- **Guess-the-number** — `render_guess_number(el, eid)` → same three-param widening; shim passes them.
  When `mine.done`: input filled with `canonical_target`, `readonly`, `guessnumber--done`,
  `success_message` shown, Check removed. The `.guessnumber` div gains `data-state`/`data-state-url`.
- **Fill-in table** — real template `filltableelement.html` gains `data-state`/`data-state-url` on the
  `[data-filltable]` div and a locked branch: when `mine.done`, `render()` feeds the template
  `canonical_cells` in place of `data["cells"]` (see §2) and the existing cell loop renders each answer
  cell `readonly` + `filltable__input--correct`, Confirm omitted, `filltable__summary--success`.

**Unanswered-path invariant (all three):** when `mine` is absent/false, the rendered markup is
**byte-identical to today** — the new `mine=None`/`mine_json="{}"` tag params and the template's
`{% if mine.done %}` branch must not perturb the existing unanswered output. The Testing section's
`data-state="{}"` + "unanswered renders editable/unlocked" assertions guard this for each element. All
three also keep their `data-element-pk`/`data-check-url` unchanged; the check endpoints are untouched.

### 4. `window.libliState` — the shared JS helper

A new small always-available global (loaded before any widget script on a lesson page):

```js
window.libliState = {
  storedFlag: function (el, key) {           // strict shape, not truthiness
    try {
      var raw = el && el.dataset.state;
      if (!raw) return false;
      var blob = JSON.parse(raw);
      return !!(blob && blob[key] === true);
    } catch (e) { return false; }
  },
  saveFlag: function (container, stateObj) {  // fire-and-forget, keepalive, swallow errors
    var url = container.dataset.stateUrl;
    if (!url) return;                          // editor preview "" -> no-op
    var eid = parseInt(container.dataset.elementPk, 10);
    if (!eid) return;                          // pk 0 -> no join row
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ element: eid, state: stateObj }),
      keepalive: true,
    }).catch(function () {});
  },
};
```

`fillgate.js` and `switchgate.js` are refactored onto it (`storedOpen(el)` → `libliState.storedFlag(el,
"open")`; `saveOpen(c)` → `libliState.saveFlag(c, {open: true})`), removing their private copies. The
plan resolves where `csrf` lives (the helper hosts it, or reads the existing per-file `csrf()`), and
the include wiring so the helper is present whenever any consuming widget is (the `has_<type>` flag
mechanism in `build_lesson_context`).

### 5. Widget JS — save on complete, skip-arm on boot

For each of `switchgrid.js`, `filltable.js`, `guessnumber.js`:

- **Save on complete**: on the existing all-correct/lock branch, after locking, call
  `window.libliState.saveFlag(container, {done: true})`.
- **Skip-arm on boot**: in `initOne`, after latching the ready flag, if `libliState.storedFlag(container,
  "done")`, do not arm Confirm/submit — the server already rendered the locked state — and return. This
  mirrors the gate boot short-circuit.
- **Guess-the-number Enter guard**: `guessnumber.js` uses no `<form>` (deliberate — see
  [[guess-number-status]]), so a restored input cannot implicitly submit/navigate on Enter. Confirm in
  the plan; if that changes, add the gate's `preventDefault`-only guard.

## Testing / falsifiability

Every guard is falsification-proven: delete/neutralize the guard, watch the test go red, revert. Per
the doctrine, before claiming a test is falsifiable, name the single guard whose removal makes it fail.

**Server-side / unit (fast, via the real lesson view — the str/int-key seam):**
- `_val_done` registration for all three families and monotone behaviour (`{"done": true}` | EMPTY |
  REJECT on non-dict).
- `FillTableElement.canonical_cells` (first alternative per answer cell; empty shapes; static passthrough).
- Guess-the-number `canonical_target` formatting (trailing-zero strip).
- Each element's server-rendered locked render **through `client.get` on the lesson view** (never
  `obj.render()` with a str key): `data-state` present + autoescaped, done classes, answers shown
  locked/readonly/disabled, Confirm/Check omitted; unanswered path unchanged (`data-state="{}"`).
- **Switch grid bounds-safety**: an out-of-range persisted `answer` renders 200 with nothing un-hidden
  (no `options[answer]` IndexError).

**e2e (foreground, `-m e2e`; seed `element_state` as fixture setup, drive the real gesture):**
- Per element: complete it correctly → await the `/state/` POST → reload → still locked/all-correct,
  Confirm/Check gone; the answers shown match the model.
- Wrong/partial attempt → **no** `/state/` POST → reload → fresh, editable, unlocked.
- Guess-the-number: correct → reload → target value shown readonly, success message, done.
- The shared-helper refactor does not regress the two gates (the gate e2e files stay green).
- **Nested restore** (Switch grid + Fill-in table are in `NESTABLE_TYPE_KEYS` — nestable inside Tabs):
  one e2e that a completed **nested** switch grid / fill-in table restores correctly after reload (the
  widget JS `container`-scoped `dataset`/`closest` lookups and the server render must work inside a tab
  panel exactly as at top level). If the existing tabs-nesting e2e suite already exercises these two
  post-restore, cite it and fold it into the regression DoD instead of adding a new case.

**Regression / DoD:** full non-e2e suite; the three new e2e files plus `test_e2e_fillgate.py` /
`test_e2e_switchgate.py` (guarding the `libliState` refactor); ruff + format + `makemigrations --check`
+ `manage.py check`; a visual check of one restored locked self-check (both themes, no flash).

## Deferred

- **Step-by-step stepper** — ungraded progressive reveal; restorable state is a step count, not a done
  flag. Own spec.
- **Partial / wrong-attempt restore with per-cell markers** — needs stored verdict or re-check-on-boot;
  explicitly out of scope here.
- **Slice 3 (lesson-mode question answers)** — server-side rehydration, a separate mechanism.

Related: [[student-practice-state-status]], [[guess-number-status]], [[switch-grid-element-status]],
[[fill-in-table-status]], [[multi-select-grid-status]].
