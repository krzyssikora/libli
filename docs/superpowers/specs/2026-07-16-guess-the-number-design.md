# Guess the number

A numeric self-check element with directional ("too big" / "too small") feedback. This is the last
unbuilt item on the interactive-elements roadmap, ported from the legacy Demo Course `.more_less_guess`
widget. This spec also carries one small bundled label rename (see §8).

## 1. Purpose

### 1.1 What it is

The author writes a stem containing exactly one `{{target}}` token. The student types a number into
the input the token becomes, and clicks Check (or presses Enter). The server compares it to the target
and answers with one of three verdicts:

- **correct** — reveal a custom success message, lock the input;
- **too big** / **too small** — a directional nudge; the student tries again, unlimited times.

### 1.2 Why it exists — evidence from real usage

The legacy widget's demo (`_template.html`, "Zgadnij liczbę między 10 a 20") frames this as a guessing
game, but all three real lesson usages are **numeric self-checks** where the direction hint nudges a
student to recheck their arithmetic:

- `001_zbiory_liczbowe/140_liczby_r_zast.html` — "O ile procent więcej tabletów sprzedała firma
  TeraSoft niż firma OpenArch?" (input below a prose prompt);
- `005_wyrazenia_algebraiczne/wyr_alg_145_wsm.html` — `\(201^2=\)` immediately followed by the input,
  **inline**, with several such rows stacked;
- the same file's success message is a full explanation containing math
  (`Tak, TeraSoft sprzedała o \(100\%\) niż OpenArch.`), not a bare "well done".

The element must serve **both** framings: the self-check (dominant, exact answers) and the
game/approximation (via a non-zero tolerance). Three consequences fall directly out of this evidence
and are load-bearing throughout:

1. the input must be able to sit **inline**, flowing against rendered KaTeX (§2.2, §5);
2. both the stem **and** the success message carry math, so the element must be math-bearing on both
   fields (§2.5 — this is a hard dependency, not a nicety);
3. wrong answers are **expected and repeated**, which is what forces the ungraded design (§1.3).

### 1.3 Why a new element and not an enhancement

The roadmap requires verifying overlap with existing elements before adding a new one. That check was
done, and the overlap is substantial:

- `ShortNumericQuestionElement` (`courses/models.py:1517`) already has exactly these matching
  semantics — `value` + absolute `tolerance`, parsed via `parse_number`. It already supports unlimited
  attempts in lessons (`max_attempts` is dormant outside quiz units) and a `NOT_MARKED` marking mode.
- `FillBlankQuestionElement` already does inline `{{token}}` authoring, and `blank_matches` already has
  a numeric branch, so `\(201^2=\){{40401}}` with `3,14 == 3.14` works today.

**The only genuinely novel behaviour is the directional hint.** A new element is still the right call,
and the decisive reason is **marks**. Both candidates for enhancement are `QuestionElement` subclasses,
which route every check through `check_answer` and record a `QuestionResponse` — feeding analytics and
the gradebook. This element is built around making *many wrong attempts*; recording each guess as a
graded response is wrong, and "guess a number between 10 and 20" as a gradebook row is nonsense.

The whole sibling family — Switch grid, Fill-in table, and both reveal gates — is ungraded *on
purpose*, for exactly this reason. This element joins that family.

Rejected alternatives, for the record:

- **Enhance `ShortNumericQuestionElement`** with a `directional_hint` flag: smallest possible diff, but
  stays graded, and its `stem` is a block prompt so it cannot produce the inline `201² = [input]`
  layout.
- **Enhance `FillBlankQuestionElement`** with a per-blank numeric hint: gets inline tokens free, but is
  also graded, has no per-blank tolerance, and bolts numeric-comparison config onto a text-blank
  element.

### 1.4 Non-goals (YAGNI — explicitly decided)

- **min/max range fields.** The stem states the range in prose ("Zgadnij liczbę między 10 a 20"); an
  auto-rendered range hint would be a second way to say the same thing.
- **Guess history / attempt counter.** Only the latest verdict is shown, as in the legacy widget.
- **Per-instance custom hint wording.** The "too big"/"too small" strings are i18n defaults. (The
  *success* message is customisable — that one has real evidence behind it; the hint wording does not.)
- **Cross-reload persistence.** Nothing is stored per student. A reload resets the widget.
- **Quiz availability.** The Interactive palette group is already quiz-hidden; no extra gating is
  needed (same conclusion as Fill-in table).
- **Answer secrecy.** See §4.4 — the success message is deliberately public to the client.

## 2. Architecture / components

### 2.1 Model — `GuessNumberElement(ElementBase)`

A plain `ElementBase` subclass, **not** a `QuestionElement`. Ungraded, lesson-only, persists nothing,
reveals nothing — explicitly **not** a reveal gate (mirror `SwitchGridElement`'s docstring, which is
the clearest statement of the self-check contract).

| Field | Type | Notes |
|---|---|---|
| `stem` | `TextField(blank=True)` | The `￿0￿` token-stem. **Not** sanitised in `save()` — sanitisation is a form-side ordered pipeline (§2.3). |
| `target` | `DecimalField(max_digits=20, decimal_places=8)` | Derived from the token by the form; never a form field itself. |
| `tolerance` | `DecimalField(max_digits=20, decimal_places=8, default=0, MinValueValidator(0))` | `0` = exact match (the default, and what every real usage needs). `> 0` enables the approximation/bisection game. |
| `success_message` | `TextField(blank=True)` | Sanitised in `save()` with **`sanitize_cell`** (math-aware — see §2.4). Blank falls back to a generic translated "Correct!". |
| `elements` | `GenericRelation(Element)` | Cascade: deleting this removes its join-row. |

`target`/`tolerance` deliberately mirror `ShortNumericQuestionElement`'s field shapes so numeric
behaviour stays consistent across the codebase.

**`render` must return rendered HTML, not a context dict.** The base `ElementBase.render` does not pass
`eid`, so this type overrides it, following `FillGateElement.render` / `SwitchGateElement.render`
exactly:

```python
def render(self, **_kwargs):
    from django.template.loader import render_to_string

    join = self.elements.order_by("pk").first()
    return render_to_string(
        "courses/elements/guessnumberelement.html",
        {"el": self, "eid": join.pk if join else 0},
    )
```

`eid` is the **`Element` join-row pk, not the concrete model pk** — that is what the endpoint takes,
and the distinction matters for nesting. The `**_kwargs` signature absorbs the render-context seam's
kwargs (`checklist`/`slug`/`node_pk`), which this element ignores.

### 2.2 Authoring

The author types one stem, e.g. `\(201^2=\){{40401}}`. Token placement decides layout for free, via
ordinary inline flow — a token at the end of a line renders the input inline (math flows into it); a
token on its own line renders it stacked. This is what lets one field serve both real usages.

`tolerance` and `success_message` are separate form fields (mirroring `ShortNumericQuestionElement`) —
deliberately not crammed into the token, which stays a pure answer marker.

### 2.3 Token module — `courses/guessnumber.py`

Neither existing token mechanism fits off the shelf, so this element gets its own small module,
modelled directly on **`courses/switchgate.py`** (the single-token-stem precedent) and reusing
`courses/fillblank.py`'s primitives:

- `courses.fillblank.parse()` extracts token *contents* but splits on `|` into alternatives, numbers
  tokens `￿0￿…￿n￿`, and raises on "no blanks" — its `to_author_stem(token_stem, blanks)` needs a
  `blanks` list this element does not have.
- `courses.switchgate.parse_stem()` enforces exactly-one, but only for the *fixed literal* `{{choice}}`
  marker, which carries no payload.

`courses/guessnumber.py` therefore provides, mirroring `switchgate.py`'s shape:

```python
SENTINEL_TOKEN = fillblank.SENTINEL + "0" + fillblank.SENTINEL   # reuse fillblank's sentinel

class GuessNumberError(ValueError): ...

def parse_stem(clean: str) -> tuple[str, str]:
    """-> (token_stem, raw_target_str). Exactly one {{...}} token; math masked first."""

def to_author_stem(token_stem: str, target: Decimal) -> str:
    """Inverse: SENTINEL_TOKEN -> '{{' + format_target(target) + '}}'."""

def render_stem(token_stem: str, widget_html: str) -> SafeString:
    """Split on the sentinel, splice the widget in — identical to switchgate.render_stem."""

def format_target(target: Decimal) -> str:
    """Canonical author-facing text for a stored target (§2.6)."""
```

**Math must be masked before token scanning.** `fillblank._mask_math` / `_restore_math` exist precisely
so that braces inside KaTeX (e.g. `\text{{x}}`) are not misread as a token. `parse_stem` reuses them;
if they must be imported across modules, promote them to public names rather than duplicating the
regex.

**Form-side pipeline and its ordering (a security invariant, not style).** `courses/fillblank.py`
mandates `sanitize_html(raw)` → `strip_sentinel` → `parse()`, as `FillGateElementForm.clean_stem`
implements. `strip_sentinel` must run on raw author input **before** parsing, so a stored token can
never be forged from prose. `clean_stem` for this element follows the same order:

```
sanitize_html(raw) -> fillblank.strip_sentinel(...) -> guessnumber.parse_stem(...)
```

The model's `save()` leaves `stem` alone. (`success_message` *is* sanitised in `save()` — it carries no
tokens, so it has no ordering constraint; see §2.4.)

**Validation** — all raised as form errors, never coerced or deferred to the DB:

1. Exactly one `{{...}}` token. Zero or two-or-more → error.
2. Token contents parse as a number via `parse_number`.
3. A literal `|` inside the token is **rejected** with an explicit error, rather than silently read as
   a fill-blank alternative. (`{{40401|40402}}` must not quietly mean two answers.)
4. The parsed value fits `max_digits=20, decimal_places=8` — see §2.6. **This check is mandatory, not
   defensive:** `target` is derived, not a form field, so Django's ModelForm `_post_clean` excludes it
   from `full_clean` and its `DecimalValidator` never fires. Without this the DB raises a
   numeric-overflow `DataError` (a 500), and over-precise input is silently rounded.

Reuse the transfer path's existing helper for (4) — `check_decimal_str(value, name, 20, 8)` in
`courses/transfer/payloads.py` — so authoring and import agree on one bound.

### 2.4 `success_message` — sanitiser and escaping

Use **`sanitize_cell`**, not `sanitize_html`. This is forced by §1.2: the real success message contains
math, and `sanitize_cell` stashes balanced `\(…\)` / `\[…\]` spans behind a nonce placeholder and
canonicalises them via `_canon_math` so KaTeX receives the right `textContent`; plain `sanitize_html`
runs nh3 with no math protection. Inline emphasis survives either way; math only survives the former.

The hidden div renders the message with `|safe`, which is sound precisely *because* `save()` sanitised
it. The edit partial mounts the same RTE surface (`data-rte-source`) the sibling stems use.

### 2.5 Math wiring — `_element_has_math` (hard dependency)

`_element_has_math` (`courses/views.py`) is the documented **single source of truth** for "does this
element carry math?", and `has_math` is what gates KaTeX itself: `templates/courses/lesson_unit.html`
loads `katex.min.js`, `auto-render.min.js` **and** `math.js` only `{% if has_math %}`. An unknown type
falls through to the container helpers and returns `False`.

So without a clause here, a unit whose only math is a guess-number stem (`\(201^2=\)`) or success
message (`\(100\%\)`) — the element's headline use case — loads **no KaTeX at all**, and the `math.js`
selector below never even runs. Add exactly one clause, covering **both** fields:

```python
if isinstance(obj, GuessNumberElement):
    return has_math_delimiters(obj.stem) or has_math_delimiters(obj.success_message)
```

Separately, `math.js`'s `renderInlineText` selector list (`.el--text, .el--table, …, .stepper,
.markdone`) gains this element's container class (§2.7) so its inline math is rendered — the same class
of gotcha the stepper hit with its `.stepper` selector.

### 2.6 Number formatting — the round-trip rule

The author's literal token text is **not** stored; the editor rebuilds the token from `target`. That
makes the formatting rule load-bearing, because the naive options are both broken:

- `str(target)` → `Decimal('40401.00000000')` renders `{{40401.00000000}}` (quantized by
  `decimal_places=8`);
- `str(target.normalize())` → `Decimal('4.0401E+4')` renders `{{4.0401E+4}}`, which `parse_number`
  then **rejects** on the next save, making the element uneditable.

The rule is therefore:

```python
def format_target(target: Decimal) -> str:
    return format(target.normalize(), "f")   # 'f' = fixed-point; never scientific notation
```

`format(…, "f")` strips the exponent `normalize()` introduces, so `40401.00000000 → "40401"` and
`40401.50000000 → "40401.5"`.

**Separator policy:** the rebuilt token always uses `.`, even if the author typed `,`. `parse_number`
accepts both on input; the canonical stored/rebuilt form is `.`. So `{{40401,5}}` re-renders as
`{{40401.5}}` — an intentional canonicalisation, and it must be tested (§6), because silent
comma/period drift is a bug this codebase has shipped before (the `dragimage` `parseFloat` locale bug).

### 2.7 Template, DOM hooks, and JS

- `templates/courses/elements/guessnumberelement.html` — student render.
- `templates/courses/manage/editor/_edit_guessnumber.html` — the edit-form partial. **Mandatory:** its
  absence 500s (`TemplateDoesNotExist`) the instant the palette card is clicked; `slidebreak` is the
  only element that legitimately lacks one.
- `courses/static/courses/js/guessnumber.js` — exposes an idempotent `window.libliInitGuessNumbers`.

**DOM contract** (pinned, because three consumers depend on exact names — `math.js`'s selector,
`libliInitGuessNumbers`'s query, and the e2e):

| Hook | Name |
|---|---|
| Container element | `<div class="guessnumber" data-guessnumber data-check-url="…" data-element-pk="…">` |
| `math.js` selector addition | `.guessnumber` |
| JS query | `[data-guessnumber]` |
| Idempotency ready-flag | `dataset.guessnumberReady === "1"` (sibling convention: `dataset.switchgateReady`) |
| Input | `[data-guess-input]` |
| Check button | `[data-guess-check]` |
| Verdict divs | `[data-guess-feedback="high"]`, `[data-guess-feedback="low"]`, `[data-guess-feedback="success"]` |

**The success message is server-rendered into a hidden div, not returned by the endpoint.** This is
load-bearing: real success messages contain math, and KaTeX must process it at page load. JS only
unhides it. (Its cost — the message is public to the client — is weighed in §4.4.) The "too big" /
"too small" divs are likewise pre-rendered hidden, from i18n defaults.

**No prepaint watchdog is needed, by design.** The reveal gates need one because they *hide lesson
content* and must fail open if JS dies. This element hides nothing — dead JS costs only the feedback,
never trapped content. A flat `has_guess_number` flag in `build_lesson_context` gates the `<script>`
tag in `lesson_unit.html`; that is the whole wiring.

**The `has_guess_number` flag must not be written the obvious way.** `build_lesson_context` scopes its
`elements` queryset to `parent__isnull=True`, so a flag computed from that queryset silently misses
tab-nested and column-nested children, and the JS never loads for them. This has bitten twice; both
stepper and mark-done ship explicit regression tests for it (see §6).

## 3. Data flow

1. **Render.** The server renders the token-stem via `guessnumber.render_stem`, splicing in a text
   input (`inputmode="decimal"`) plus a Check button, on the container described in §2.7. Reading the
   URL from `data-check-url` rather than a form `action` is deliberate: a no-JS Enter must not navigate
   to a JSON endpoint. Hidden verdict divs render alongside.
2. **Trigger.** JS submits on **Check click or Enter only** — see §3.2.
3. **Request.** `POST guess=<str>`, CSRF from the `csrftoken` cookie sent as an `X-CSRFToken` header
   (the convention both gate scripts use; `{% csrf_token %}` in the template is a MarkDone-only thing).
4. **Server.** Resolve element (soft) → access gate → `parse_number(guess)` → verdict.
5. **Response.** `{"correct": bool, "direction": "high"|"low"|null}`, where `direction` is from the
   **student's** perspective: `"high"` means *your guess is too big*.
6. **Apply.** On `correct` → unhide the success div, mark the input correct, lock it `readonly`. On a
   direction → unhide the matching hint div, hide the other. Nothing cascades; no content is revealed.

### 3.1 Verdict logic

```
n = parse_number(guess)
if n is None:           → {"correct": false, "direction": null}
elif abs(n - target) <= tolerance: → {"correct": true,  "direction": null}
elif n > target:        → {"correct": false, "direction": "high"}
else:                   → {"correct": false, "direction": "low"}
```

`parse_number` (`courses/marking.py`) is reused rather than reimplemented: it accepts a single `.`
**or** `,` decimal separator (so Polish `40401,0` works), rejects thousands separators and internal
whitespace, and returns `None` on anything malformed. Tolerance comparison is inclusive (`<=`), so a
guess exactly `tolerance` away from the target is correct.

Direction is measured against `target`, not against the edge of the tolerance band. With a non-zero
tolerance a guess just outside the band reports the direction it lies in, which is what a bisection
search needs.

**The legacy `standardizeDP` `eval()` is deliberately not ported.** The legacy ran `eval()` on student
input (`script.js:14-23`) as a decimal-separator hack, which silently also let `2+3` evaluate to `5`.
That is an accident of the hack, not a feature; `parse_number` replaces it.

### 3.2 Submit triggers

**Check click or Enter. Never blur.** The sibling precedent (`fillgate.js`, `switchgate.js`) submits
only on an explicit Confirm click or form submit, never on blur, and for good reason: blur-submit
stamps a "too big" on a student who merely tabbed away mid-thought. The legacy widget's blur-submit is
not carried over.

The Check button sits **immediately after the input, inline**, so the `201² = [input] [Check]` row
still flows as one line.

Two guards are required:

- **In-flight guard.** Ignore a submit while one is pending, so two responses cannot race (Enter
  followed quickly by a click). Without it a slow "too big" for guess *n* can land after "correct" for
  guess *n+1* and clobber the locked success state.
- **Post-lock guard.** Once correct, the widget is inert: no further submits, even though a `readonly`
  input still emits events.

## 4. Error handling

| Situation | Behaviour |
|---|---|
| Unparseable input (`abc`, `1 000`, `1.2.3`) | `{"correct": false, "direction": null}` → input goes red, no directional hint. Matches the legacy, which showed no direction for non-numeric input. |
| Missing or wrong-type `element_pk` | Benign `200 {"correct": false, "direction": null}` (soft lookup). Non-informative, so pks cannot be probed to distinguish element types. |
| No course access | Denied by the standard access gate, after the element resolves. |
| Network failure / non-200 | `.catch()` leaves the widget editable and shows no verdict — never locks, never falsely passes (fillgate precedent). |
| Unsaved editor preview (`data-element-pk == "0"`) | No-op; the widget renders but does not submit. |
| Empty input | Clears the verdict; no request. |
| Concurrent submits | Suppressed by the in-flight guard (§3.2), so responses cannot apply out of order. |
| JS absent entirely | The input renders inert. Nothing is hidden and nothing is lost — no watchdog needed (§2.7). |
| Over-long / over-precise token | Rejected as a form error at authoring time (§2.3), never reaching the DB. |

### 4.1 Check endpoint

`guessnumber_check`, flat route `courses/element/<int:element_pk>/guessnumber-check/`, `@require_POST`
`@login_required`. The name follows the `<form-key>_check` convention every sibling uses
(`fillgate_check`, `switchgate_check`, `switchgrid_check`, `filltable_check`). Persists nothing — no
`QuestionResponse`, no `UnitProgress`.

Uses the **soft pk lookup** (`.filter(pk=...).first()`, benign `200` on a missing or wrong-type pk),
which is the newer convention established by `switchgate_check` and followed by `switchgrid_check` and
`filltable_check` — deliberately **not** `fillgate_check`'s `get_object_or_404`. The course-access gate
runs after the element resolves.

### 4.4 Accepted: the success message is public to the client

Server-rendering the success message (§2.7) ships it to every client at page load, readable via View
Source — and per §1.2 that text may state the answer outright ("Tak, TeraSoft sprzedała o \(100\%\)…").

This is **accepted**, on the same reasoning as the rest of the design: the element is ungraded, nothing
is recorded, and a determined student can extract the target in a handful of guesses anyway — the
directional hint is a binary search by construction. It also matches the Spoiler/reveal-gate family,
which likewise ships revealable content to the client. Server-side *checking* still earns its place by
keeping the target itself out of the DOM.

The cost is real for the game framing, so the edit partial's hint text must warn authors: **the success
message is visible in the page source — do not put anything there that must stay secret.**

## 5. Styling

No view ships unstyled. This element defines real visual states, so they need explicit rules and a
light+dark pass:

- **States:** default, wrong (input tinted red, per §4), too-big/too-small hint visible, success
  (message shown, input locked/`readonly`).
- **Inline baseline alignment** is the one genuinely new design problem: the input sits inline against
  a KaTeX-rendered `\(201^2=\)`, whose baseline is not a plain text baseline. Vertical alignment of the
  input and the Check button against rendered math must be decided deliberately, not left to default
  `vertical-align`.
- Hint and success colours reuse the existing feedback tokens (the same palette the sibling self-checks
  use), so this element does not invent a second vocabulary for "wrong" and "correct".
- Verify with Playwright screenshots in **both light and dark** before shipping, and run the
  `frontend-design` skill over both the student widget and the authoring form.

## 6. Testing

**Token module / form**
- Round-trip: author `{{40401}}` → `target == Decimal("40401")` → editor re-renders exactly `{{40401}}`
  (not `{{40401.00000000}}`, not `{{4.0401E+4}}`).
- Round-trip boundaries: integer; trailing zeros (`{{40401.50}}`); 8 significant decimals; a value that
  would normalize to an exponent.
- Comma round-trip: `{{40401,5}}` → `target == Decimal("40401.5")` → editor re-renders `{{40401.5}}`
  (canonicalised — §2.6).
- Exactly-one-token validation: zero tokens → form error; two tokens → form error.
- Non-numeric token contents → form error.
- `|` inside the token → explicit form error (not silently two alternatives).
- Bounds: over-long integer part (>20 digits) → form error, **not** a DB `DataError`; >8 decimal places
  → form error, **not** silent rounding.
- Math masking: a stem whose KaTeX contains braces is not misparsed as a token.
- Sentinel forging: a stem containing a literal `￿0￿` in prose is stripped before parse.
- `tolerance` rejects negatives; `success_message` is sanitised with `sanitize_cell` and **retains
  math** (the `sanitize_html` regression this would otherwise be).

**Endpoint**
- Correct / high / low verdicts.
- Tolerance boundary: `abs(n - target) == tolerance` → **correct** (inclusive).
- Comma decimals: `40401,0` and `40401.0` both correct.
- Unparseable → `correct: false, direction: null`.
- Soft-pk probes: missing pk and wrong-type pk → benign `200`.
- Access gate: a user without course access is denied.
- `require_POST`; `login_required`.
- **Nothing is persisted** — no `QuestionResponse`, no `UnitProgress` row created.

**Context flags** (each guards a trap this codebase has already fallen into)
- `build_lesson_context(...)["has_guess_number"] is True` for a **top-level** element, for one **nested
  in a tab**, and for one **nested in a two-column column** — the `parent__isnull=True` trap (§2.7).
  The e2e below exercises rendering, not the flag, and would pass even with a wrong query.
- `build_lesson_context(...)["has_math"] is True` for math in the **stem** and, independently, for math
  in the **success_message** — the `_element_has_math` clause (§2.5). Without this the headline
  `\(201^2=\)` use case renders raw.

**Wiring / authoring** (each guards a step that has historically been missed)
- `manage_element_add` for `guessnumber` returns 200 — covers the
  `element_add` → `_host_form` → `_edit_guessnumber` render path, which row/palette tests do not reach.
  The reveal-gate `_edit_` partial was missed exactly this way (fixed in PR #100).
- `manage_editor` GET asserts the `guessnumber.js` `<script>` tag is present — gallery and reveal-gate
  both shipped with a broken preview because `editor.html` never loaded the enhancer.
- Transfer export/import round-trip, including a Decimal with trailing zeros.

**e2e**
- Wrong-high → "too big"; wrong-low → "too small"; correct → success message shown and input locked.
- After lock, further interaction submits nothing.
- Nested inside tabs.

**i18n**
- EN/PL catalogs complete; catalog tests run (the §8 rename *removes* translatable strings, which is
  exactly the case that has broken catalog tests before).

## 7. Touch-points

Adding an element type means keeping this set in lockstep; a miss in any one of them is a 500 or a
silently broken surface. **Symbol names, not line numbers** — the file positions drift every slice.

- `ELEMENT_MODELS` (`courses/models.py`) **30 → 31**, plus an `alter_element_content_type` migration.
  Next migration number is **0049**.
- `FORMAT_VERSION` (`courses/transfer/schema.py`) **stays 4** — a new element type is not an on-disk
  shape change.
- The `ELEMENT_MODELS` count is asserted in **two** places: `tests/test_transfer_schema.py` **and**
  `tests/test_models_multigrid.py`. Both must go 30 → 31.
- `courses/views.py`: `_element_has_math` clause (§2.5) **and** the `has_guess_number` flag in
  `build_lesson_context` (§2.7), plus the `guessnumber_check` view (§4.1).
- `courses/urls.py`: the flat check route.
- `courses/guessnumber.py`: new token module (§2.3).
- `FORM_FOR_TYPE` (`courses/element_forms.py`) + the new form; `save_element` (`courses/builder.py`);
  `_add_menu.html` palette card + icon sprite; the `element_add`/`element_save` allow-tuples and
  `_EDITOR_TYPE_LABELS` (`courses/views_manage.py`); `_ELEMENT_LABELS`
  (`courses/templatetags/courses_manage_extras.py`).
- **`element_summary` needs no branch.** It already ends in a generic fallback that picks up any element
  with a `stem` and rewrites `￿N￿` tokens to `___` — which is how `FillGateElement` and
  `SwitchGateElement` get their summaries with no per-class code. `GuessNumberElement` has a `stem`, so
  it inherits the right behaviour for free.
- Transfer trio: `SERIALIZERS` (`courses/transfer/export.py`), `VALIDATORS`
  (`courses/transfer/payloads.py`), `BUILDERS` (`courses/transfer/importer.py`) — payload in §7.1.
- `NESTABLE_TYPE_KEYS` (`courses/builder.py`) holds **transfer** keys → add `guess_number`. Also add
  `"guessnumber": "guess_number"` to the module-level `_NESTABLE_FORM_KEY_ALIASES` dict in the same
  file, which `resolve_scope` consults before the `NESTABLE_TYPE_KEYS` membership check.
- `math.js` selector (§2.5); the stylesheet (§5).
- JS enhancer wired into **both** `editor.js` (re-run `window.libliInitGuessNumbers(preview)` after each
  fragment swap, next to the gallery/tabs re-inits) **and** `editor.html` (the `<script defer>` tag).
- i18n EN/PL.

**Naming:** model `GuessNumberElement`; `ELEMENT_MODELS` entry `guessnumberelement`; form key
`guessnumber`; transfer key `guess_number`; endpoint `guessnumber_check`; JS `guessnumber.js`; templates
`courses/elements/guessnumberelement.html` and `courses/manage/editor/_edit_guessnumber.html`; palette
label EN "Guess the number" / PL "Zgadnij liczbę". Transfer keys are snake_case and differ from form
keys — that divergence is the established convention, not an inconsistency to fix.

### 7.1 Transfer payload

`Decimal` is **not** JSON-serializable (`json.dumps(Decimal(...))` raises `TypeError`), so decimals
travel as strings — the settled convention `_ser_numeric` / `_val_short_numeric` / `_build_numeric`
already use for `ShortNumericQuestionElement`.

```json
{
  "stem": "<token-stem string, sentinel form>",
  "target": "40401",
  "tolerance": "0",
  "success_message": "<sanitised html>"
}
```

- **Export:** `str(el.target)` / `str(el.tolerance)`.
- **Validate:** `check_decimal_str(data["target"], "target", 20, 8)` and the same for `tolerance`, plus
  a non-negative `tolerance` check. The stem validator mirrors the existing sentinel-token check
  (`_TOKEN_RE` in `payloads.py`) so an imported stem cannot carry stray or forged sentinels, and must
  assert exactly one token.
- **Build:** rehydrate with `Decimal(data["target"])`.

## 8. Bundled scope — rename the Two-column label to "Columns"

User-requested, and to ship in this same PR. **Label-only.** The model, form, and transfer keys stay
`twocolumnelement` / `twocolumn` / `two_column`; no migration, no `FORMAT_VERSION` bump.

It is a genuine correctness fix rather than a preference: the element already supports **2–4** columns,
so "Two columns" is a misnomer.

Two code sites change:

- `courses/templatetags/courses_manage_extras.py` — `_("Two columns")` → `_("Columns")`
- `courses/views_manage.py` — `_EDITOR_TYPE_LABELS["twocolumn"]`, `gettext_lazy("Two-column layout")` →
  `gettext_lazy("Columns")`
- `templates/courses/manage/editor/_add_menu.html` — `{% trans "Two-column layout" %}` →
  `{% trans "Columns" %}`

**`msgid "Columns"` already exists — this merges into it rather than minting it.** It lives in both
catalogs today (PL already translated "Kolumny") and is currently the **column-count field label**
(`courses/element_forms.py`, `templates/courses/manage/editor/_edit_twocolumn.html`). Two consequences:

1. **No new PL translation is needed** for "Columns" — the spec must not claim otherwise.
2. **The editor would show the word twice in a row** — heading "Columns" (`_EDITOR_TYPE_LABELS`) with
   the field label "Columns" directly beneath it. Resolve by relabelling the *count field* to
   `_("Number of columns")` / PL `"Liczba kolumn"` (a genuinely new msgid, needing a PL entry), leaving
   the heading as the plain "Columns".

Catalogs: `"Two columns"` ("Dwie kolumny") and `"Two-column layout"` ("Układ dwukolumnowy") both become
unreferenced and drop out; `"Columns"` stays (now with more referents); `"Number of columns"` is added.

No test currently asserts either renamed label (verified). Module-level translatable dicts must keep
using `gettext_lazy` — eager `gettext` froze labels to English once already (PR #46). Watch the
`makemessages` fuzzy-flag gotcha when the msgids shift.
