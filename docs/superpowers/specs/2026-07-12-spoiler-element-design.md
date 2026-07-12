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

The student template renders a native HTML disclosure:

```html
<details class="spoiler">
  <summary class="spoiler__toggle">{{ el.label|default:_("Reveal") }}</summary>
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
  (mirroring `_edit_revealgate.html`) followed by the **same RTE toolbar + `<textarea
  name="body" class="rte-source" data-rte-source>`** the Text element's `_edit_text.html`
  uses. Field names must match the form field names (`label`, `body`), or the host form
  round-trip breaks. A missing edit partial 500s `TemplateDoesNotExist` the instant the
  palette card is clicked (`_host_form.html` dynamically `{% include %}`s it), so this file
  is mandatory.

### Palette + builder plumbing

The Spoiler is added to the **Interactive** group of the add-menu and to every generic
element-dispatch site that must stay in lockstep (see Touch-points).

### Transfer (export / import)

A SERIALIZER / VALIDATOR / BUILDER trio keyed by the snake_case transfer key **`spoiler`**,
round-tripping `{label, body}`. Transfer keys differ from form keys by convention; here both
happen to be `spoiler`. No `FORMAT_VERSION` bump.

### Scope decisions (YAGNI)

- **Not nestable inside Tabs** for v1 — `NESTABLE_TYPE_KEYS` is untouched. Trivial to add
  later if demand appears.
- **No JS file, no reveal engine, no server-check endpoint, no `editor.html` `<script>`
  tag.** Native `<details>` covers all behaviour.
- Content is a single rich-text `body` field (prose + math), not nested child elements — a
  solution/hint is prose+math in practice, and this reuses the Text element's proven
  authoring and rendering path.

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
- **Blank label** → template supplies the translated default via `|default:_("Reveal")`; the
  stored value stays empty so the default stays language-appropriate at render time.
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
