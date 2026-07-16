# Guess the number

A numeric self-check element with directional ("too big" / "too small") feedback. This is the last
unbuilt item on the interactive-elements roadmap, ported from the legacy Demo Course `.more_less_guess`
widget. This spec also carries one small bundled label rename (see §7).

## 1. Purpose

### 1.1 What it is

The author writes a stem containing exactly one `{{target}}` token. The student types a number into
the input the token becomes. On submit the server compares it to the target and answers with one of
three verdicts:

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
and are load-bearing throughout: the input must be able to sit **inline**; the success message is
**custom per instance and contains math**; and wrong answers are **expected and repeated**.

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

## 2. Architecture / components

### 2.1 Model — `GuessNumberElement(ElementBase)`

A plain `ElementBase` subclass, **not** a `QuestionElement`. Ungraded, lesson-only, persists nothing,
reveals nothing — explicitly **not** a reveal gate (mirror `SwitchGridElement`'s docstring at
`courses/models.py:667`, which is the clearest statement of the self-check contract).

| Field | Type | Notes |
|---|---|---|
| `stem` | `TextField` | Sanitised on save. Stores exactly one placeholder token. |
| `target` | `DecimalField(max_digits=20, decimal_places=8)` | Parsed out of the `{{...}}` token by the form. |
| `tolerance` | `DecimalField(max_digits=20, decimal_places=8, default=0, MinValueValidator(0))` | `0` = exact match (the default, and what every real usage needs). `> 0` enables the approximation/bisection game. |
| `success_message` | `TextField(blank=True)` | Sanitised on save. Blank falls back to a generic translated "Correct!". |
| `elements` | `GenericRelation(Element)` | |

The field shapes for `target`/`tolerance` deliberately mirror `ShortNumericQuestionElement` so numeric
behaviour stays consistent across the codebase.

`render(self, **_kwargs)` resolves the join row and passes `eid`, exactly like `FillGateElement.render`
(`models.py:631`) and `SwitchGateElement.render` (`models.py:657`):

```python
join = self.elements.order_by("pk").first()
return {"el": self, "eid": join.pk if join else 0}
```

`eid` is the **`Element` join-row pk, not the concrete model pk** — that is what the endpoint takes,
and the distinction matters for nesting.

### 2.2 Authoring

The author types one stem, e.g. `\(201^2=\){{40401}}`. Token placement decides layout for free, via
ordinary inline flow — a token at the end of a line renders the input inline (math flows into it); a
token on its own line renders it stacked. This is what lets one field serve both real usages.

The form round-trips `{{40401}}` ↔ stored placeholder token + `target`, **reusing the existing
blank-token machinery** and the `{{answer}}` editor convention already shipped in PR #46. `tolerance`
and `success_message` are separate form fields (mirroring `ShortNumericQuestionElement`) — deliberately
not crammed into the token, which stays a pure answer marker.

**Validation:** exactly one token is required. Zero tokens or two-or-more tokens is a form error, not a
silent coercion. The token's contents must parse as a number (via `parse_number`), otherwise a form
error.

### 2.3 Check endpoint

`guess_check`, flat route `courses/element/<int:element_pk>/guess-check/`, `@require_POST`
`@login_required`. Persists nothing — no `QuestionResponse`, no `UnitProgress`.

Uses the **soft pk lookup** (`.filter(pk=...).first()`, benign `200` on a missing or wrong-type pk),
which is the newer convention established by `switchgate_check` and followed by `switchgrid_check` and
`filltable_check` — deliberately **not** `fillgate_check`'s `get_object_or_404`. The course-access gate
runs after the element resolves.

### 2.4 Template + JS

- `templates/courses/elements/guessnumberelement.html` — student render.
- `templates/courses/manage/editor/_edit_guessnumber.html` — the edit-form partial. **Mandatory:** its
  absence 500s (`TemplateDoesNotExist`) the instant the palette card is clicked; `slidebreak` is the
  only element that legitimately lacks one.
- `courses/static/courses/js/guessnumber.js` — exposes an idempotent `window.libliInitGuessNumbers`
  (guarded by a `dataset` ready-flag) for editor-preview re-init.

**The success message is server-rendered into a hidden div, not returned by the endpoint.** This is
load-bearing, not incidental: real success messages contain math, and KaTeX must process it at page
load. JS only unhides it. Consequence: `math.js` needs a selector covering it — the same class of
gotcha the stepper hit with its `.stepper` selector. The "too big" / "too small" divs are likewise
pre-rendered hidden, from i18n defaults.

**No prepaint watchdog is needed, by design.** The reveal gates need one because they *hide lesson
content* and must fail open if JS dies. This element hides nothing — dead JS costs only the feedback,
never trapped content. A flat `has_guess_number` flag in `build_lesson_context` gates the `<script>`
tag in `lesson_unit.html`; that is the whole wiring.

## 3. Data flow

1. **Render.** The server renders the stem with the token replaced by a text input
   (`inputmode="decimal"`), carrying `data-check-url` and `data-element-pk`. Reading the URL from a data
   attribute rather than a form `action` is deliberate: a no-JS Enter must not navigate to a JSON
   endpoint. Hidden verdict divs (too big / too small / success) render alongside it.
2. **Trigger.** JS submits on Enter, on blur, or on a Check click. Empty input clears the verdict and
   does not submit.
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

`parse_number` (`courses/marking.py:41`) is reused rather than reimplemented: it accepts a single `.`
**or** `,` decimal separator (so Polish `40401,0` works), rejects thousands separators and internal
whitespace, and returns `None` on anything malformed. Tolerance comparison is inclusive (`<=`), so a
guess exactly `tolerance` away from the target is correct.

Direction is measured against `target`, not against the edge of the tolerance band. With a non-zero
tolerance a guess just outside the band reports the direction it lies in, which is what a bisection
search needs.

**The legacy `standardizeDP` `eval()` is deliberately not ported.** The legacy ran `eval()` on student
input (`script.js:14-23`) as a decimal-separator hack, which silently also let `2+3` evaluate to `5`.
That is an accident of the hack, not a feature; `parse_number` replaces it.

## 4. Error handling

| Situation | Behaviour |
|---|---|
| Unparseable input (`abc`, `1 000`, `1.2.3`) | `{"correct": false, "direction": null}` → input goes red, no directional hint. Matches the legacy, which showed no direction for non-numeric input. |
| Missing or wrong-type `element_pk` | Benign `200 {"correct": false, "direction": null}` (soft lookup). Non-informative, so pks cannot be probed to distinguish element types. |
| No course access | Denied by the standard access gate, after the element resolves. |
| Network failure / non-200 | `.catch()` leaves the widget editable and shows no verdict — never locks, never falsely passes (fillgate precedent). |
| Unsaved editor preview (`data-element-pk == "0"`) | No-op; the widget renders but does not submit. |
| Empty input | Clears the verdict; no request. |
| JS absent entirely | The input renders inert. Nothing is hidden and nothing is lost — no watchdog needed (see §2.4). |

## 5. Testing

**Model / form**
- Token round-trip: author `{{40401}}` → stored placeholder token + `target == 40401` → editor
  re-renders `{{40401}}`.
- Exactly-one-token validation: zero tokens → form error; two tokens → form error.
- Non-numeric token contents → form error.
- `tolerance` rejects negatives; `stem` and `success_message` are sanitised on save.

**Endpoint**
- Correct / high / low verdicts.
- Tolerance boundary: `abs(n - target) == tolerance` → **correct** (inclusive).
- Comma decimals: `40401,0` and `40401.0` both correct.
- Unparseable → `correct: false, direction: null`.
- Soft-pk probes: missing pk and wrong-type pk → benign `200`.
- Access gate: a user without course access is denied.
- `require_POST`; `login_required`.
- **Nothing is persisted** — no `QuestionResponse`, no `UnitProgress` row created.

**Wiring / authoring** (each of these guards a step that has historically been missed)
- `manage_element_add` for `guessnumber` returns 200 — covers the
  `element_add` → `_host_form` → `_edit_guessnumber` render path, which row/palette tests do not reach.
  The reveal-gate `_edit_` partial was missed exactly this way (fixed in PR #100).
- `manage_editor` GET asserts the `guessnumber.js` `<script>` tag is present — gallery and reveal-gate
  both shipped with a broken preview because `editor.html` never loaded the enhancer.
- Transfer export/import round-trip.

**e2e**
- Wrong-high → "too big"; wrong-low → "too small"; correct → success message shown and input locked.
- Nested inside tabs.

**i18n**
- EN/PL catalogs complete; catalog tests run (the §7 rename *removes* translatable strings, which is
  exactly the case that has broken catalog tests before).

## 6. Touch-points

Adding an element type means keeping this set in lockstep; a miss in any one of them is a 500 or a
silently broken surface.

- `ELEMENT_MODELS` (`courses/models.py:259`) **30 → 31**, plus an `alter_element_content_type`
  migration. Next migration number is **0049**.
- `FORMAT_VERSION` (`courses/transfer/schema.py:14`) **stays 4** — a new element type is not an on-disk
  shape change.
- The `ELEMENT_MODELS` count is asserted in **two** places: `tests/test_transfer_schema.py` **and**
  `tests/test_models_multigrid.py`. Both must go 30 → 31.
- `FORM_FOR_TYPE` (`element_forms.py:785`); `save_element` (`builder.py:269`); `_add_menu.html` palette
  card + icon sprite; `element_add`/`element_save` tuples (`views_manage.py:860/913`);
  `_EDITOR_TYPE_LABELS` (`views_manage.py:727/750`); `_ELEMENT_LABELS` + `element_summary`
  (`courses_manage_extras.py:26/72`).
- Transfer trio: `SERIALIZERS` (`export.py:212/341`), `VALIDATORS` (`payloads.py:468`), `BUILDERS`
  (`importer.py:622/748`).
- `NESTABLE_TYPE_KEYS` (`builder.py:26`) holds **transfer** keys → add `guess_number`, and alias the
  form key `guessnumber` in `_NESTABLE_FORM_KEY_ALIASES` at `resolve_scope`.
- JS enhancer wired into **both** `editor.js` (re-run `window.libliInitGuessNumbers(preview)` after each
  fragment swap, next to the gallery/tabs re-inits) **and** `editor.html` (the `<script defer>` tag).
- i18n EN/PL.

**Naming:** model `GuessNumberElement`; `ELEMENT_MODELS` entry `guessnumberelement`; form key
`guessnumber`; transfer key `guess_number`; endpoint `guess_check`; JS `guessnumber.js`; templates
`courses/elements/guessnumberelement.html` and `courses/manage/editor/_edit_guessnumber.html`; palette
label EN "Guess the number" / PL "Zgadnij liczbę". Transfer keys are snake_case and differ from form
keys — that divergence is the established convention, not an inconsistency to fix.

## 7. Bundled scope — rename the Two-column label to "Columns"

User-requested, and to ship in this same PR. **Label-only.** The model, form, and transfer keys stay
`twocolumnelement` / `twocolumn` / `two_column`; no migration, no `FORMAT_VERSION` bump.

It is a genuine correctness fix rather than a preference: the element already supports **2–4** columns,
so "Two columns" is a misnomer.

Exactly three code sites, plus catalogs:

- `courses/templatetags/courses_manage_extras.py:39` — `_("Two columns")` → `_("Columns")`
- `courses/views_manage.py:750` — `gettext_lazy("Two-column layout")` → `gettext_lazy("Columns")`
- `templates/courses/manage/editor/_add_menu.html:25` — `{% trans "Two-column layout" %}` →
  `{% trans "Columns" %}`
- Catalogs EN + PL: two msgids (`"Two columns"` = "Dwie kolumny", `"Two-column layout"` = "Układ
  dwukolumnowy") **collapse into one** msgid `"Columns"` / PL "Kolumny".

No test currently asserts either label (verified). Module-level translatable dicts must keep using
`gettext_lazy` — eager `gettext` froze labels to English once already (PR #46). Watch the
`makemessages` fuzzy-flag gotcha when the msgids collapse.
