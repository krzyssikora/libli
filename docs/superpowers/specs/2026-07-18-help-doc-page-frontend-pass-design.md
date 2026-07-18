# Help doc-page frontend pass

Design pass on the in-app `/help/` doc surface — the last piece of the help-pages
refresh initiative (following PR #152, which illustrated every topic). Two goals:
make the element-type **term/description** blocks scannable, and prefix each
element-type entry with the **same monochrome icon** the course-admin sees in the
add-element palette. Token-driven CSS only (light + dark), reusing the existing
`#el-*` sprite; no product changes beyond the help/doc renderer.

## Purpose

The help topic pages render trusted repo markdown through `core/help.py`. Two
readability problems remain after the screenshot initiative:

1. **Wall of paragraphs.** `docs/help/course-admin/content-editors.md` lists the
   ~12 content element types as `**Text** — …` bold-lead paragraphs. Rendered, they
   are near-identical `<p>` blocks with no visual separation — you cannot scan for a
   type. `doc-page.css` only styles base prose/headings/code/tables, so there is no
   treatment for these term/description entries.

2. **No icons.** The authoring palette (`templates/courses/manage/editor/_add_menu.html`)
   shows each element type with a monochrome `#el-*` sprite icon. The docs show none,
   so the manual does not visually mirror the tool it documents.

Goal: a scannable term/description treatment for the element list, and a per-type
icon on every element-type entry across the three element surfaces
(content-editors list + interactive-elements/quiz-editors headings) — reusing the
existing sprite, driven by design tokens, working in both themes.

Out of scope (deferred to a separate follow-up slice, by user decision): re-pointing
the roster screenshot at the group membership editor, and fixing the 16×16
`demo.png` seed asset + re-capturing shots that include the media library.

## Architecture / components

### 1. Icon injection — token + render-time transform (`core/help.py`)

Reusing the `#el-*` sprite requires `<svg><use href="#el-…"/></svg>` in the DOM;
CSS alone cannot select a per-type icon. Authors mark each element-type entry with a
stable, language-independent token `{el:SLUG}`, where `SLUG` is the sprite id minus
its `el-` prefix (e.g. `{el:text}` → `#el-text`). A new transform in `core/help.py`,
a sibling of the existing `resolve_static_srcs`, rewrites these tokens **after**
`markdown.markdown()` renders:

- **List entry** (paragraph form, content-editors):
  `<p>{el:text} <strong>Text</strong> — …</p>`
  → a `.doc-elref` row: an icon in a fixed gutter, the original paragraph content as
  the body. The `<strong>` term lead is preserved (kept as a single row, not split
  into `<dt>/<dd>` — splitting on the em-dash is fragile because descriptions contain
  dashes).

- **Heading** (interactive-elements, quiz-editors `##` per element):
  `<h2>{el:revealgate} Show more</h2>`
  → the heading with a leading inline icon injected right after the opening tag.

**Matching contract.** The transform must produce two structurally different outputs
depending on the token's HTML context, so it applies **two ordered regex passes** over
the rendered HTML (python-markdown here runs only `fenced_code` + `tables`, no
`attr_list`, so `{…}` survives as literal text and is safe to match):

Both passes use a **function replacement** (`re.sub` with a callable), not a template
string, because the slug-membership check requires branching (see Slug validation): the
callback emits an `<svg>` only for a slug in `ELEMENT_ICON_SLUGS` and otherwise returns
the matched text unchanged, leaving an unknown/typo'd token as literal.

1. **Heading inject** (run first): match a **run of one or more** leading tokens on a
   heading — `<h([1-6])([^>]*)>\s*((?:\{el:[a-z0-9-]+\}\s*)+)` — noting the match **spans
   the opening tag** (groups 1–2 = level and attrs) **plus** the token run. Because
   `re.sub` with a callable replaces the *entire* match, the callback must **reconstruct
   the opening tag** and return `<h{group1}{group2}>` followed by one
   `<svg class="ic" aria-hidden="true" focusable="false"><use href="#el-SLUG"></use></svg>`
   **per token, in order** (each slug validated independently; an unknown one is re-emitted
   literally as its `{el:…}` text). It must **not** emit only the svgs — that would drop the
   `<h2>` opening tag. The heading text and closing `</hN>` lie outside the match and are
   left untouched. Matching a *run* (not a single token) is required for the one combined
   heading that mirrors two palette cards — `## {el:choice-single}{el:choice-multi} Single / Multiple choice`
   renders both icons. The tokens' trailing whitespace is consumed, so no stray space
   precedes the heading text.
2. **List-entry wrap** (run second): `<p>\s*\{el:([a-z0-9-]+)\}\s*(.*?)</p>` with the
   **non-greedy** `.*?` and `re.DOTALL` → the `.doc-elref` div in the emitted-markup form
   below (callback validates the single slug; unknown → returned unchanged). A list entry
   carries exactly one token. Non-greedy matching is required so two adjacent tokened
   paragraphs become two separate rows rather than one greedy match swallowing the span
   between them. `re.DOTALL` lets the body span the **soft-wrapped** lines markdown joins
   into a single `<p>`; a blank line still starts a new `<p>`, so **each element entry
   must be authored as a single paragraph** (a two-paragraph entry would leave its
   continuation as an orphaned untokened `<p>` outside the row — a known authoring
   constraint, not a supported layout). The leading token + whitespace is consumed, so the
   body starts at `<strong>`.

Heading-first ordering is harmless (headings never contain `<p>`), but fixed so the
contract is deterministic. A token that matches neither context (e.g. inside a list item
or inline run) is left untouched — no element surface authors one there, and leaving it
literal surfaces the mistake (caught by the no-leak test).

**Slug validation.** `ELEMENT_ICON_SLUGS` is a **hardcoded `frozenset`** in
`core/help.py` — the sprite ids minus their `el-` prefix — *not* read from the
template at import time (reading a Django template *name* as a filesystem path at
module import invites loader-ordering / `AppRegistryNotReady` problems, and buys
nothing here). Both regex passes only rewrite a token whose slug is in this set; an
unknown/typo'd slug is **left as literal text** (visible, caught by the no-leak test —
never a silent miss). A dedicated test (Testing §1) parses
`templates/courses/manage/_icon_sprite.html` for its `id="el-…"` symbols and asserts
the frozenset equals that set, so the hardcoded list can never silently drift from the
palette. The §4 slug list below has already been checked against the current sprite
ids by hand; this test makes that check permanent.

**Emitted markup** (illustrative):

```html
<!-- list entry -->
<div class="doc-elref">
  <svg class="ic" aria-hidden="true" focusable="false"><use href="#el-text"></use></svg>
  <div class="doc-elref__body"><strong>Text</strong> — the workhorse block…</div>
</div>

<!-- heading -->
<h2><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-revealgate"></use></svg>Show more</h2>
```

Icons are decorative (`aria-hidden="true" focusable="false"`), matching the palette;
the element name in text carries the meaning for assistive tech.

### 2. Sprite availability (`templates/help/doc.html`)

`<use href="#el-…">` resolves against a symbol present in the same document. The
sprite currently loads only on builder/editor pages, so `doc.html` gains
`{% include "courses/manage/_icon_sprite.html" %}` (a hidden 0×0 `<svg>`). The help
index page (`index.html`) does not need it. Cross-app include is fine — Django's
template loader is app-agnostic; the mild coupling is noted, not refactored (moving
the sprite would touch every editor template that includes it — out of scope).

The rendered doc content already sits inside `<article class="doc-page">…{{ content|safe }}…</article>`
in `doc.html`, so the `.doc-page`-scoped CSS in §3 has its container — no wrapper needs
to be added. The `{% include %}` goes inside that article (or the surrounding block),
so the injected `<svg><use>` elements are in the same document as the sprite symbols.

### 3. CSS (`core/static/core/css/doc-page.css`) — token-driven, both themes

Dark mode is driven by the `[data-theme="dark"]` attribute on the token set in
`core/static/core/css/tokens.css`; styling with tokens makes both themes work with
no media queries.

- **`.doc-elref` rows** — `display: flex`, `align-items: flex-start`, `gap: var(--space-3)`
  (icon gutter), `padding: var(--space-2) var(--space-3)`, `border-radius: var(--radius-md)`.
  Background `var(--surface-sunken)`, `border: 1px solid var(--border-default)`, body text
  the default `var(--text-primary)`; consecutive rows separated by a small vertical margin
  (`var(--space-2)`) for a scannable rhythm. The `<strong>` term stays emphasized (inherits
  the base `<strong>` weight; may be nudged with `var(--text-primary)` to keep contrast on
  the sunken surface). This is the goal-1 readability fix. These tokens are the concrete
  contract; minor spacing tuning during the frontend-design pass is allowed, but the
  surface/border/text tokens above are fixed.
- **`.doc-elref__body`** — the flex body child: `flex: 1; min-width: 0;` so it fills the
  remaining width and long unbreakable content (inline `<code>`, a URL) wraps instead of
  overflowing the row (`min-width: 0` overrides the default `min-width: auto`).
- **Icon sizing** — the palette's `.ic` rule lives in `editor.css`, not loaded on help
  pages, so `.doc-page .ic` is defined here: `width: 1.15rem; height: 1.15rem;
  flex: 0 0 auto; fill: currentColor;`. `fill: currentColor` means an icon takes its
  color from the surrounding text; the list-entry icon is therefore **deliberately**
  `var(--text-primary)` (inherited from the `.doc-elref` body — a full-strength marker
  next to the term), while heading icons are pinned to `var(--text-tertiary)` below (a
  quieter marker). The two weights are an intentional contrast, not an inheritance
  accident. In a `.doc-elref` row the icon aligns to the first line
  (`margin-top: ~0.15rem`); in a heading it sits inline.
- **Heading icons** — `.doc-page h2 .ic`: `display: inline-block; vertical-align: -0.12em;
  margin-right: var(--space-2); color: var(--text-tertiary);` so the glyph aligns with the
  heading baseline and reads as a quiet marker, not a second heading. Only `h2` is targeted
  — every element-type heading in §4 is `##`; no `h3` element entries exist, so no `h3 .ic`
  rule is added.
- **Token correction** — `doc-page.css` currently references phantom tokens
  `var(--surface-2, …)` and `var(--text-muted, …)` that do not exist in `tokens.css`,
  so those rules silently use their hardcoded literal fallbacks instead of riding the
  design system. Replace them with real tokens (`--surface-sunken`, `--text-tertiary`,
  keeping `--border-default`) so the help surface is genuinely token-driven. This is
  the "match the design system" half of goal 1.

### 4. Content edits (EN + PL)

Add `{el:SLUG}` tokens to every element-type entry, in both language files:

- `docs/help/course-admin/content-editors.md` / `.pl.md` — ~12 list entries:
  text, image, video, iframe, math, html, table, gallery, callout, tabs,
  twocolumn (Columns), slidebreak (Slide break).
- `docs/help/course-admin/interactive-elements.md` / `.pl.md` — 9 `##` headings:
  revealgate (Show more), fillgate (Fill in & confirm), switchgate (Choose & confirm),
  switchgrid (Switch grid), filltable (Fill-in table), spoiler, stepper (Step-by-step),
  markdone (Checklist), guessnumber (Guess the number).
- `docs/help/course-admin/quiz-editors.md` / `.pl.md` — ~10 `##` headings:
  choice-single **+** choice-multi (the single combined "Single / Multiple choice"
  heading carries **both** tokens, mirroring the palette's two cards), shorttext (Short text),
  shortnumeric (Short numeric), fillblank (Fill in the blanks), dragwords (Drag the
  words), matchpairs (Match pairs), switchgrid (Matrix question),
  switchgrid (Multi-select grid), dragimage (Drag to image), extended (Extended
  response).

**`switchgrid` is intentionally reused three times** — for Switch grid,
Matrix question, and Multi-select grid. This is not an error: the authoring palette
(`_add_menu.html`) itself points all three `data-add-type`s at `#el-switchgrid`
(`switchgrid`, `choicegridquestion`, `multigridquestion` all render `<use href="#el-switchgrid"/>`).
The docs mirror the palette exactly, so reusing the slug is the *correct* behavior, not a
collision to resolve. The per-entry icon test (Testing §4) encodes each entry's expected
slug from an explicit table, so this reuse is asserted deliberately rather than assumed.

Token placement: at the very start of the paragraph/heading line, before the bold
term or heading text. Non-element sections ("See also", "Where questions live", prose)
get no token and are untouched. Every slug in the lists above has been verified against
the current `id="el-…"` symbols in `_icon_sprite.html`.

## Data flow

1. `help_topic` view → `render_markdown_doc(rel_path)`.
2. `render_markdown_doc(rel_path, *, resolve_static=True)` reads the `.md`, runs
   `markdown.markdown(...)`, then applies `resolve_element_icons(html)` (new). Icon
   resolution runs **unconditionally** — it is *not* gated behind the existing
   `resolve_static` flag, because the two are orthogonal (icons touch `{el:…}` tokens,
   static touches `src="static:…"`) and the only non-help caller of this function (the
   SIS webhook guide, which passes `resolve_static=False`) contains no `{el:…}` tokens,
   so the added pass is a guaranteed no-op there. `resolve_static_srcs(html)` still runs
   afterward exactly as today when `resolve_static` is true. Passes are order-independent.
3. Rendered HTML → `help/doc.html`, which now also includes the icon sprite, so the
   `<use href="#el-…">` references resolve.
4. Browser applies `doc-page.css`: `.doc-elref` rows + sized icons, both themes via
   token variables.

## Error handling

- **Unknown slug.** A `{el:xyz}` with `xyz ∉ ELEMENT_ICON_SLUGS` is left as literal
  text — no exception (help pages are trusted content, but a render-time raise could
  500 a live page). Caught by the "no stray `{el:` survives render" test instead.
- **Malformed token.** Anything not matching `\{el:[a-z0-9-]+\}` is ordinary text and
  passes through untouched.
- **Slug set is static.** `ELEMENT_ICON_SLUGS` is a hardcoded `frozenset` literal, so
  there is no import-time file read to fail (this deliberately avoids the loader-ordering
  risk of resolving a template name to a path at import). Drift between the frozenset and
  the sprite is caught at **test** time (Testing §1), not runtime.
- **Consistency with existing renderer.** `resolve_element_icons` follows the same
  pure-function, regex-substitution shape as `resolve_static_srcs`; no new state, no I/O.

## Testing

Falsifiable guards (each must be able to go red if the behavior it protects is
removed — per the project's "falsify tests, don't run them" doctrine):

1. **Frozenset ↔ sprite parity.** Parse `templates/courses/manage/_icon_sprite.html`
   for every `id="el-…"` symbol; assert `ELEMENT_ICON_SLUGS` equals that set minus the
   `el-` prefix. Falsify: add a sprite symbol, or a stray frozenset member, without
   updating the other → red. (This is the drift guard that replaces import-time file
   reading.)
2. **Every doc token is a known slug.** Parse every `{el:SLUG}` token across all
   `docs/help/` markdown; assert each `SLUG` ∈ `ELEMENT_ICON_SLUGS`. Falsify: introduce
   a typo token → red.
3. **No literal leak.** For each element topic (content-editors, interactive-elements,
   quiz-editors), render via `render_markdown_doc` and assert the output contains
   **no** literal `{el:` substring. Falsify: skip the transform → red.
4. **Per-entry icon mapping (drives out silent wrong-icon bugs where a token points at
   the wrong sprite).** For a small authored expectation table —
   `{topic: {element-name → expected-slug(s)}}` covering a representative sample across
   all three surfaces (including the three `switchgrid` reuses and the dual-icon
   `choice-single`+`choice-multi` combined heading, plus at least one plain heading and
   one list entry) — render the topic and assert the element name and its expected
   `<use href="#el-SLUG">`(s) co-occur in the correct wrapper (`.doc-elref` div for a
   list entry; inside an `<h2>` for a heading). Falsify: swap two entries' tokens → red
   even though tests 2–3 stay green.
5. **Doc icons ⊆ palette icons (palette is the oracle).** Parse
   `templates/courses/manage/editor/_add_menu.html` for the set of `#el-…` slugs the
   authoring palette actually renders; parse all `docs/help/` markdown for the set of
   `{el:…}` slugs; assert the doc set is a **subset** of the palette set. This catches a
   doc entry that invents an icon the palette never shows (drift the author's own
   expectation table in §4 cannot catch, since it shares the author's assumptions).
   Falsify: token a doc entry with a real sprite id the palette doesn't use → red.
6. **Adjacent list entries stay separate.** Feed `resolve_element_icons` two consecutive
   tokened `<p>` blocks and assert it emits **two** `.doc-elref` divs, not one. Falsify:
   make the paragraph capture greedy (drop `?`) → the two collapse into one → red.
7. **Transform is targeted.** Assert `resolve_element_icons` leaves ordinary prose
   paragraphs and untokened headings byte-for-byte unchanged. Falsify: an over-broad
   regex that rewrites untokened text → red.
8. **Sprite present on the page.** A view-level test (authenticated, permitted user)
   for a topic page asserts the response includes the sprite symbol
   (`id="el-text"`), i.e. `doc.html` includes the partial. Falsify: remove the
   include → red.

Extend the existing `tests/test_help.py` rather than adding a parallel module.

**Manual verification.** Light + dark Playwright screenshots of the content-editors
and interactive-elements topic pages before shipping, self-critiqued for icon
alignment, row rhythm, and token-correct surfaces in both themes (per the project's
screenshot-verification habit).
