# Spoiler element — show/hide disclosure

## Purpose

Add a new self-contained content element, **Spoiler**, to libli's unit builder: an
author-labelled button that expands and collapses a block of rich text + math. It is
two-way, repeatable, and ungraded — a general disclosure widget for hints, notes, extra
detail, or worked solutions.

It ports the legacy Flask/JS "Demo Course" `.show_solution` / `.question_solution` widget
(from `C:/Users/krzys/Documents/teaching/LAL/html/_template.html`), reframed as a general
disclosure rather than a question-specific "solution" toggle. It is the next member of the
**Interactive** palette group after the reveal-gate trilogy (Show more / Fill in & confirm /
Choose & confirm).

**Explicitly distinct from** the existing reveal-gate elements: the gates are thin dividers
that reveal *following sibling* elements via a client-side reveal-cascade engine, are
one-way (button removed after use), and require JS. The Spoiler is a self-contained element
that owns its hidden content, is two-way, and needs **no JS at all** — see Architecture.

### Naming

- Palette card: EN **"Spoiler"**, PL **"Rozwijana treść"**.
- Default button label (when the author leaves it blank): EN **"Reveal"**, PL **"Pokaż"**.

The reveal-gate's default label is "Show more"; the Spoiler's default is deliberately
different ("Reveal") to avoid confusion between the two.

## Architecture / components

### Mechanism — native `<details>`, zero JS, zero server endpoint

The student template (`templates/courses/elements/spoilerelement.html`, auto-resolved
from the model name by `ElementBase.render`) renders a native HTML disclosure. `|sanitize`
requires `{% load courses_extras %}` and the translated default requires `{% load i18n %}`;
follow the reveal-gate's `{% if el.label %}{{ el.label }}{% else %}{% trans "Reveal" %}{% endif %}`
pattern rather than `|default` for consistency:

```html
{% load i18n courses_extras %}
<details class="spoiler">
  <summary class="spoiler__toggle">{% if el.label %}{{ el.label }}{% else %}{% trans "Reveal" %}{% endif %}</summary>
  <div class="el el--text spoiler__body">{{ el.body|sanitize }}</div>
</details>
```

- **Collapsed by default** — the body is hidden until the summary is clicked, which is the
  whole point of a spoiler.
- **The no-JS fallback IS the real behaviour.** Native `<details>` gives expand/collapse,
  keyboard operation, and accessibility for free. Unlike the reveal-gates, nothing is
  `hidden` by JS and there is no enhancer to load, so the element also works correctly in
  the builder preview pane with no extra wiring. This sidesteps the twice-repeated
  editor.html enhancer-registration footgun (gallery and reveal-gate both shipped broken
  previews because `editor.html` never loaded their JS).
- **Math renders at load.** `math.js` runs `renderMath(document)` (a whole-document
  `[data-katex]` pass) and `renderInlineText(document)` (inline `\(…\)` prose math over the
  selector list `.el--text, .el--table, .el--gallery, .el--tabs, .fillgate`) once at page
  load. Because native `<details>` keeps its content in the DOM even when collapsed, and
  because the body carries the `.el--text` class, both display and inline math typeset at
  load with **no reveal event required**.
- **`has_math` gating (load-bearing dependency).** `lesson_unit.html` loads `math.js` (and
  KaTeX CSS) only `{% if has_math %}`, and `has_math` (computed in `courses/views.py`
  `build_lesson_context` ~L206 via `_element_has_math` ~L121) scans specific concrete element
  types for math delimiters. It has **no `SpoilerElement` branch today**, so a unit whose only
  math lives in a spoiler `body` would compute `has_math == False`, math.js would never load,
  and the "math renders at load" guarantee would silently fail. `courses/views.py` is
  therefore a required touch-point (see Touch-points item 15): add a `SpoilerElement` branch to
  `_element_has_math` returning `has_math_delimiters(obj.body)`, extend the `build_lesson_context`
  `has_math` OR-chain to cover spoilers, and import `SpoilerElement`. (The quiz `has_math` path
  is moot — spoilers are quiz-excluded.)

**Verification obligation:** during implementation, confirm that inline and display math
inside a *collapsed* `<details>` is actually typeset at load. This is expected to hold (the
content is in the DOM; KaTeX walks it regardless of CSS `display`). If — and only if — it
does not, the minimal remedy is to dispatch a bubbling `libli:reveal` event on the
`<details>` `toggle`→open event, mirroring how tabs do it. Do **not** build a JS enhancer
speculatively; only add one if this verification fails.

### Data model

`SpoilerElement(ElementBase)` in `courses/models.py`, added to the `ELEMENT_MODELS` list:

- `label = models.CharField(max_length=120, blank=True)` — button text; blank → default
  ("Reveal" / "Pokaż") supplied by the template, not stored.
- `body = models.TextField(blank=True)` — rich HTML, sanitized via `sanitize_html` in
  `save()`, identical to `TextElement.save`.
- `elements = GenericRelation(Element)` — cascade join-row cleanup, per every other element.

A migration adds the concrete table. **No `FORMAT_VERSION` bump** — a new element type does
not change the on-disk shape of existing types (per the choose-and-confirm lesson).

### Authoring

- `SpoilerElementForm(ModelForm)` in `courses/element_forms.py` with `fields = ["label",
  "body"]`, wired into `FORM_FOR_TYPE`.
- Edit partial `templates/courses/manage/editor/_edit_spoiler.html`: a "Button text" input
  (mirroring `_edit_revealgate.html`) with helptext **"Shown on the spoiler button. Leave
  blank for the default “Reveal”."** (PL: **"Wyświetlany na przycisku. Pozostaw puste, aby
  użyć domyślnego „Pokaż”."**), followed by the **same RTE toolbar + `<textarea name="body"
  class="rte-source" data-rte-source>`** the Text element's `_edit_text.html` uses. The label
  input must carry `maxlength="120"` and a placeholder (per `_edit_revealgate.html`), and the
  partial must render **both** field-error loops — `{% for e in form.label.errors %}` **and**
  `{% for e in form.body.errors %}` (easy to drop the `body` one when fusing the two partials).
  Field names must match the form field names (`label`, `body`), or the host form
  round-trip breaks. A missing edit partial 500s `TemplateDoesNotExist` the instant the
  palette card is clicked (`_host_form.html` dynamically `{% include %}`s it), so this file
  is mandatory.

### Palette + builder plumbing

The Spoiler is added to the **Interactive** group of the add-menu
(`templates/courses/manage/editor/_add_menu.html`) and to every generic element-dispatch
site that must stay in lockstep (fully enumerated in the **Touch-points** section below).
The card renders `<svg><use href="#el-spoiler"/></svg>`, so a matching `#el-spoiler` symbol
must be added to the icon sprite (see Touch-points / Styling).

**Quiz-unit availability.** The Interactive group in `_add_menu.html` is wrapped in
`{% if not unit_is_quiz %}` (mirrored by the `unit_is_quiz` guards in `views_manage.py`
around L689/L716). By joining that group the Spoiler inherits this gating and is therefore
**not offered inside quiz units** in v1 — consistent with the reveal-gate family. This is
intended: quiz "solutions" are handled by the existing post-submission answer reveal. If a
future need arises to expose spoilers in quizzes, it is a separate change to the group
gating, out of scope here.

### Transfer (export / import)

A SERIALIZER / VALIDATOR / BUILDER trio keyed by the snake_case transfer key **`spoiler`**,
round-tripping `{label, body}`. Transfer keys differ from form keys by convention; here both
happen to be `spoiler`. No `FORMAT_VERSION` bump.

- **VALIDATOR** `_val_spoiler` must be **strict**, mirroring `_val_text` (not the lax no-op
  `_val_reveal_gate`): `_exact_keys(data, ["label", "body"])`,
  `check_str(data["body"], _("body"))`, and `check_str(data["label"], _("label"),
  max_length=120)`. A lax validator would let a malformed archive (missing key / non-string
  `body`) reach the BUILDER and 500 on `sanitize_html`/render.
- **BUILDER** `_build_spoiler` must use `_clean_save(SpoilerElement(label=data.get("label",
  ""), body=data["body"]))` — matching the body-bearing `_build_text` precedent — so import
  runs `full_clean` (enforcing the 120-char `label` cap) + `save` (sanitizing `body`), rather
  than the validation-skipping `.objects.create` path used by `_build_reveal_gate`.

### Styling

The template introduces three BEM classes — `.spoiler`, `.spoiler__toggle`,
`.spoiler__body` — which must be styled per the project's "every view ships styled" rule; a
bare native `<details>` shows the browser-default disclosure triangle, which clashes with the
bespoke design and the reveal-gate's custom chevron. Add rules to the same stylesheet the
reveal-gate/element styles live in (locate `.reveal-gate`'s CSS file and co-locate there).
Visual target: mirror the reveal-gate affordance — give the toggle a button-like focus ring
and hit area, and space the expanded `.spoiler__body`. Must work in **both light and dark
themes**.

**Chevron / marker suppression (pinned down):** the native disclosure triangle is removed
cross-browser with `.spoiler__toggle { list-style: none; }` **plus**
`.spoiler__toggle::-webkit-details-marker { display: none; }`. The chevron is a **CSS
pseudo-element** on `.spoiler__toggle` (`::after`, an inline-SVG data-URI background or a
bordered caret — matching the reveal-gate chevron), rotated via `.spoiler[open]
.spoiler__toggle::after`. No chevron markup is added to the `<summary>` (keeping the render
snippet as shown), and the `#el-spoiler` sprite symbol is scoped to the palette card only —
it is **not** reused as the toggle chevron. A monochrome currentColor line-SVG `#el-spoiler` symbol is
added to `templates/courses/manage/_icon_sprite.html` for the palette card, per the
monochrome-icon convention. It **must reuse the same `viewBox`/coordinate box as the
neighbouring `#el-*` palette symbols** in that sprite (copy a sibling's `viewBox`), not an
arbitrary size — a mismatched icon box was a real shipped bug for the table element.

### Scope decisions (YAGNI)

- **Not nestable inside Tabs** for v1 — `NESTABLE_TYPE_KEYS` is untouched. Trivial to add
  later if demand appears.
- **No JS file, no reveal engine, no server-check endpoint, no `editor.html` `<script>`
  tag.** Native `<details>` covers all behaviour.
- Content is a single rich-text `body` field (prose + math), not nested child elements — a
  solution/hint is prose+math in practice, and this reuses the Text element's proven
  authoring and rendering path.

### Touch-points (files/sites to change, in lockstep)

Adding an element type touches many dispatch sites; a missed one either 500s or silently
drops the type. All must land together:

1. `courses/models.py` — `SpoilerElement(ElementBase)` model + add `"spoilerelement"` to
   `ELEMENT_MODELS`.
2. Migration — `uv run python manage.py makemigrations courses` for the new table.
3. `courses/element_forms.py` — `SpoilerElementForm(fields=["label","body"])` + register in
   `FORM_FOR_TYPE`.
4. `courses/builder.py` — ensure `save_element` handles the `spoiler` type key (it dispatches
   through `FORM_FOR_TYPE`; confirm the `spoiler` key resolves).
5. `courses/views_manage.py` — add `"spoiler"` to **both** allow-tuples (the `element_add`
   tuple ~L884 and the `element_save` tuple ~L941) **and** add `"spoiler"` →
   `_EDITOR_TYPE_LABELS` (~L738), value `_("Spoiler")` (EN) / "Rozwijana treść" (PL), using
   the surrounding `gettext_lazy` convention. Without these the palette click / save are rejected and the
   "assert 200" test cannot pass. (This is the CRITICAL site the first review flagged.)
6. `courses/templatetags/courses_manage_extras.py` — add `"spoilerelement"` →
   `_ELEMENT_LABELS` (~L45), value `_("Spoiler")` (EN) / "Rozwijana treść" (PL), using the
   surrounding `gettext`/`gettext_lazy` convention. **Required (not optional):**
   `element_summary` (~L75) dispatches on `el.__class__.__name__` and falls through to
   `return name` for classes with no explicit branch — so without one it renders the literal
   "SpoilerElement" in the builder row (the exact bug the gallery element shipped with). Add an
   explicit branch mirroring `RevealGateElement`, e.g. `if name == "SpoilerElement": return
   el.label or _("Reveal")`, and a test asserting the row summary is the label, not the class
   name.
7. `templates/courses/manage/editor/_add_menu.html` — palette card in the **Interactive**
   group (`<svg><use href="#el-spoiler"/></svg>`).
8. `templates/courses/manage/_icon_sprite.html` — `#el-spoiler` monochrome line-SVG symbol.
9. `templates/courses/elements/spoilerelement.html` — student render (see Mechanism).
10. `templates/courses/manage/editor/_edit_spoiler.html` — edit-form partial (see Authoring).
11. Transfer trio — SERIALIZER (`courses/transfer/export.py`), VALIDATOR
    (`courses/transfer/payloads.py`), BUILDER (`courses/transfer/importer.py`), keyed
    `spoiler`. **No `FORMAT_VERSION` bump.**
12. CSS for `.spoiler*` classes + the sprite symbol (see Styling).
13. i18n — EN + PL catalogs (`uv run python manage.py makemessages`); labels + helptext.
14. `NESTABLE_TYPE_KEYS` — **untouched** (not nestable in v1).
15. `courses/views.py` — add a `SpoilerElement` branch to `_element_has_math` (~L121)
    returning `has_math_delimiters(obj.body)`, extend the `build_lesson_context` `has_math`
    OR-chain (~L206) to include spoilers, and import `SpoilerElement`. Without this, math.js
    is not loaded for a spoiler-only unit (see "Math renders at load" / `has_math` gating).

## Data flow

**Authoring:** PA/CA clicks the "Spoiler" palette card → `element_add` builds a
`SpoilerElementForm` → `_host_form.html` includes `_edit_spoiler.html` → author types a
button label and rich body → `element_save` → `save_element` persists the `SpoilerElement`
(sanitizing `body`) and its `Element` join-row.

**Student render:** the unit's element list renders `spoilerelement.html` → native
`<details>` collapsed → `math.js` typesets body math at load → student clicks summary →
browser expands/collapses natively. No network, no marks, no state persisted.

**Transfer:** export walks the unit's elements → the `spoiler` SERIALIZER emits `{label,
body}` → import's VALIDATOR checks shape → BUILDER reconstructs a `SpoilerElement`. Round-
trip is lossless.

## Error handling

- **Missing edit partial** → `TemplateDoesNotExist` 500 on palette-card click. Prevented by
  shipping `_edit_spoiler.html` and covering the `manage_element_add` GET/POST path with a
  200-asserting test.
- **Unsanitized HTML** → XSS risk. Prevented by `sanitize_html(self.body)` in
  `SpoilerElement.save`, identical to `TextElement`.
- **Blank label** → the template branches `{% if el.label %}{{ el.label }}{% else %}{% trans
  "Reveal" %}{% endif %}` (matching `revealgateelement.html`); the stored value stays empty so
  the default stays language-appropriate at render time. Note `|default:_("Reveal")` is **not**
  used — you cannot invoke `_()` inside a filter argument in a Django template.
- **Math not rendering in a collapsed `<details>`** → the verification obligation above; the
  bounded remedy (a `toggle` → `libli:reveal` dispatch) is documented but only applied if
  verification fails.
- **Transfer key drift** → the transfer trio uses `spoiler` consistently; a round-trip test
  guards against serializer/builder mismatch.

## Testing

- **Model:** `save()` sanitizes `body`; `label`/`body` blank-allowed.
- **Authoring render path:** GET and POST `manage_element_add` for type `spoiler` assert 200
  (exercises `element_add` → `_host_form` → `_edit_spoiler`, the path that row/palette tests
  miss). POST persists a `SpoilerElement` with the submitted `label` + `body`.
- **Student render:** `spoilerelement.html` renders a `<details>` with the label in
  `<summary>` (or the default when blank) and the sanitized body in `.el--text`.
- **Math loads for a spoiler-only unit (guards C1):** a lesson unit whose **only**
  math-bearing element is a spoiler (no Math element and no math-in-Text sibling) must compute
  `has_math == True` so `math.js`/KaTeX are loaded. The test must isolate the spoiler this way
  — a unit with any other math element would pass vacuously and not exercise the `has_math`
  branch. Assert `has_math` (or the rendered `math.js` script tag) is present.
- **Transfer round-trip:** export → import reproduces `{label, body}` exactly.
- **Element-count assertion:** bump any test that asserts the total number of registered
  element types / `ELEMENT_MODELS` length.
- **Palette / summary:** the "Interactive" group of `_add_menu.html` includes a Spoiler card;
  `element_summary` / `_ELEMENT_LABELS` return a sensible label.
- **i18n:** EN and PL catalogs carry the new strings ("Spoiler"/"Rozwijana treść",
  "Reveal"/"Pokaż", "Button text", helptext).

### Tooling / DoD

- `ruff`, `pytest`, and `python` are **not** on the bash PATH — invoke via `uv run`.
- Definition of Done runs `uv run ruff check` **and** `uv run ruff format --check`, plus the
  full test suite. If any translatable strings are removed, also run the i18n catalog
  no-obsolete tests.
