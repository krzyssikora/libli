# Wielomiany long division as KaTeX arrays

## Purpose

The 73 long-division worked examples in the **Wielomiany** part of `mat-pp` render as
ordinary full-width tables with a grid of borders. In the legacy course they render as
borderless, shrink-to-fit column arithmetic with a horizontal rule under selected rows
and a highlight on the digits in play at each step.

The LAL import is what lost this. `scripts/lal_import/tables.py:158` (and `:357`,
`:385`) hardcodes `"border": "grid"` for every table, and the intermediate JSON has no
representation for either a per-row rule or a cell highlight — so both were dropped at
import and cannot be recovered from the database.

Rather than extend `TableElement` with a row-rule flag and a highlight class, this
replaces each of these tables with a **`MathElement` holding a KaTeX `array`**. A
long-division layout *is* mathematical typesetting; `array` expresses it natively with
`\hline`, needs no new schema, and reads better than the table did.

### Decisions taken during design, and why

Settled with the user during brainstorming. Recorded so the implementation does not
silently re-litigate them.

| Decision | Rationale |
|---|---|
| Convert to **`MathElement`**, not `TextElement` | `templates/courses/elements/mathelement.html` renders `<div class="el el--math" data-katex>{{ el.latex }}</div>`, and `math.js:renderOne` calls `katex.render(..., {displayMode: true})`. The `latex` field is a plain `TextField` with no sanitiser, so the array's `&` column separators pass through untouched. A `TextElement` would route the same string through `nh3`, which escapes every `&` to `&amp;`. That happens to survive (`math.js` reads `textContent`, which decodes it) but it is a needless hop through an escaping layer. |
| The converter reads the **legacy HTML**, never the database | The imported copy has already lost the row rules and all 77 highlighted cells. The source files are the only faithful record. |
| **`{r}` right-aligned** columns | User's choice over `{c}`. `{c}` is faithful to the legacy `text-align: center`, but right-alignment is the convention for column arithmetic and lines the terms up on their right edge. |
| **Repoint the existing `Element` join**; keep the orphaned `TableElement` rows | The join row carries `unit`, `parent`, `tab_id`, `order` and `title`. Repointing `content_type`/`object_id` preserves all of them, including position inside a spoiler. Deleting and recreating would not. Element deletion in libli is a hard delete with no backups, so the orphan rows are cheap insurance: reverting is one more repoint. |
| Highlight via **`\htmlClass` + a CSS token pair**, not `\colorbox` | `\colorbox` compiles to an inline `background-color`, so it can never respond to the theme — in dark mode the legacy pure yellow sits on `#2C2925`. It also **inflates the highlighted row**: measured, the array is 6px taller and one `\hline` gap goes to 50px against 46/47px elsewhere. The `\htmlClass` variants keep the row rhythm even. |
| Highlight is `--warning-subtle` fill with **`--tc-orange`** ink | Measured **5.09:1 light, 7.11:1 dark** — passes AA in both. The first candidate, `--warning` on `--warning-subtle`, looks fine on screen but measures **2.79:1 in light** and was rejected on the number, not the look. `--tc-orange` is the author-text colour family, already contrast-tested against ten surfaces (`core/static/core/css/tokens.css:63`, `:106`). |
| An **underline** highlight was rejected outright | In a long-division array an underline under a digit reads as a subtraction rule. It collides semantically with the `\hline`s regardless of how it looks. |
| **`scripts/lal_import/tables.py` is left unchanged** | A re-import would revert this work, but the user does not re-run the importer: units in this part have since been split in two and edited by hand (unit 1144 did not exist at import time). Fixing the importer would imply a re-import path that must not be taken. The trap is recorded under *Risks*. |
| `.el--math` gains **`overflow-x: auto`** | In scope per the user. `.el--math` currently has no CSS at all. |
| Ambiguity is resolved by **sibling-file majority, falling back to the plain variant** | Six tables are indistinguishable by cell text alone. See *Matching*. |

### Out of scope

- The four `wzór | nazwa` formula reference tables (`330#0`, `340#0`, `350#0`, `480#2`).
  They are genuine data tables and stay as tables.
- The other 27 table elements in the Wielomiany subtree.
- The remaining 164 borderless tables elsewhere in `mat-pp` (237 course-wide). This part
  only.
- Any change to `TableElement`, its editor, or its border presets.
- Deleting the orphaned `TableElement` rows. A later one-line cleanup pass.

## Selection rule

A source table converts when **all four** hold:

1. `<table>` carries class `my_table_noborder`;
2. at least one `<tr>` has `border-bottom` in its inline `style`;
3. the first row is **not** the `wzór | nazwa` header pair;
4. no cell holds more than one `\(…\)` run.

(4) is a refusal, not a filter: such a cell has no correct array slot — unwrapping it
splices the runs and eats the text between them, and `\text{}` renders the delimiters
literally — so neither the cell nor its table converts. Zero cells in this corpus hit it,
so the count below is unchanged; it is in the rule because the module outlives the
corpus.

Measured over `C:\Users\krzys\Documents\teaching\LAL\html\045_wielomiany\*.html`:
123 tables total → 77 pass (1) and (2) → **73** pass (3). The four excluded by (3) are
exactly the formula tables listed under *Out of scope*.

## Conversion

Per cell, from the legacy `<td>`:

| Input | Output |
|---|---|
| `\(X\)` | `X` |
| `\(\)` or empty `<td>` | empty slot |
| text that is not a single math run | `\text{...}` |
| text holding **two or more** math runs | refused — see selection rule (4) |
| `class="red_on_yellow"` | wrapped in `\htmlClass{mk mk-amber}{...}` |

Per row: a `border-bottom` in the row's inline style appends `\hline`.

Ragged rows pad with empty slots to the widest row. The column spec is `r` repeated to
that width. Output carries **no `\[...\]` wrapper** — `MathElement` renders in
`displayMode` already.

```
\begin{array}{rrrrr}
1 & 2 & 4 &  &  \\ \hline
7 & 4 & 5 & : & 6 \\
6 &  &  &  &  \\ \hline
...
 &  & \htmlClass{mk mk-amber}{1} &  &
\end{array}
```

**A rule on the final row still needs its row terminator.** Emitting a bare `\hline`
after the last row is a KaTeX parse error (`\hline valid only within array
environment`). The terminator is emitted when the row is not last **or** the row is
ruled. Four tables hit this: `130#5`, `130#8`, `140#5`, `140#8`.

## Matching

The command pairs each `TableElement` in the node-408 subtree with a source table by
**normalised cell-text grid** — the only signal the two sides share, since the database
copy has neither rules nor highlights.

Observed: 62 nodes, 98 table elements, **71 matched**.

| unit | title | tables |
|---|---|---|
| 423 | Przygotowanie do dzielenia wielomianów | 10 |
| 424 | Dzielenie wielomianów 1 | 10 |
| 425 | Porównanie dzielenia liczb i wielomianów | 2 |
| 426 | Porównanie dzielenia liczb i wielomianów | 2 |
| 427 | Ćwiczenia | 40 |
| 436 | Twierdzenie Bézout | 1 |
| 438 | Pierwiastki całkowite 2 | 1 |
| 441 | Pierwiastki wymierne 1 | 1 |
| 442 | Pierwiastki wymierne 2 | 3 |
| 1144 | Mnożenie wielomianów 2 | 1 |

Matching is **content-based and global within the part**, deliberately not driven by the
import manifest's `source_html`: units 425 and 426 share a title (a hand split of one
imported unit) and unit 1144 postdates the import entirely. A file→unit map would miss
both.

### Ambiguity

Two text grids each map to three source tables whose generated LaTeX differs:

- `130#9` (5 highlighted cells) ≡ `150#0` ≡ `155#0` (0 highlighted)
- `140#9` (6 highlighted cells) ≡ `150#1` ≡ `155#1` (0 highlighted)

The row rules are identical across each group; **only the highlighting differs**, and
the two plain members of each group are byte-identical to each other. So the choice is
binary: highlighted or plain.

Resolution, in order:

1. Take the modal source file among the unit's *unambiguous* matches. If the ambiguous
   grid has a candidate in that file, use it.
2. Otherwise — no unambiguous siblings, or no candidate in the modal file — take the
   variant carrying no `\htmlClass` markup. If that variant is not unique, refuse and
   report rather than guess.

Verified against the live data — all six resolve, and rule 2's target is unique in both
groups:

| unit | tables | ambiguous | resolves via |
|---|---|---|---|
| 423 | 10 | 1 | sibling majority → `130` |
| 424 | 10 | 1 | sibling majority → `140` |
| 425 | 2 | 2 | no unambiguous sibling → plain |
| 426 | 2 | 2 | no unambiguous sibling → plain |

### Source tables with no counterpart

`450#2` and `450#5` match nothing. Unit 459 (`Zadania prowadzące do równań
wielomianowych`), the unit imported from `450_wielomiany_rownania.html`, now holds two
unrelated geometry tables — the lesson was rewritten by hand. The command **reports and
skips** them; it must not invent an element.

Net: **71 conversions**, 2 reported as absent.

## Application

A management command modelled on `courses/management/commands/recolour_imported_content.py`,
which solves the same problem class ("restore what the LAL import dropped, match on
content, dry-run by default").

- Arguments: `--course` (required), `--source-dir`, `--apply`, `--list-matches`.
- **Dry-run by default.** `--apply` wraps the writes in one transaction.
- Per match: create `MathElement(latex=...)`, then repoint the existing `Element` row's
  `content_type` and `object_id`. Nothing else on the join changes.
- Idempotent: a join already pointing at a `MathElement` is skipped, so a second run is
  a no-op rather than a double conversion.
- Refuses to write and reports if: a text grid matches more than one source table and
  the resolution rules above do not settle it; or a source table in the selection has no
  DB counterpart (the two known ones are listed, not treated as an error).

## Rendering changes

**`courses/static/courses/js/math.js`** — add a scoped trust predicate to the
`[data-katex]` render call:

```js
trust: (c) => c.command === "\\htmlClass" && /^mk mk-[a-z]+$/.test(c.class)
```

An **equality** check, not a prefix. `\htmlStyle` and `\htmlData` would let authored
LaTeX inject arbitrary CSS and data attributes; `\href` and `\url` arbitrary URLs. All
stay denied. Verified: 30 class-carrying spans, 0 parse errors.

This **does** widen the surface, and the value check is what bounds the widening.
`MathElement.latex` being staff-authored and unsanitised is not a justification: the
comparable raw-authoring surface, `HtmlElement`, is deliberately **not** trusted in the
page — `courses/models.py:1006-1019` renders it through `htmlsandbox.build_srcdoc` into
a cross-origin sandboxed iframe. `\htmlClass` puts an author-chosen class straight into
the top-level lesson DOM, which is the primitive this project otherwise sandboxes. KaTeX
hands the class over in the same context object (`{command: "\\htmlClass", class: …}`),
so a command-only predicate would admit any class the stylesheet already defines —
including the full-viewport `position: fixed; inset: 0` classes (`courses.css:2287`,
`app.css:477`) as an overlay on a student's lesson page, or a `.visually-hidden`-shaped
class to conceal content. No script, no URL and no HTML injection (the value reaches the
DOM as `className` on a node KaTeX builds), so the ceiling is visual — but it is real,
and the `mk mk-*` pattern is the whole requirement, so nothing else needs through.

**`courses/static/courses/css/courses.css`** — add:

```css
.el--math { overflow-x: auto; }
.el--math .mk { border-radius: 3px; padding: .02em .2em; margin: 0 -.05em; }
.el--math .mk-amber { background: var(--warning-subtle); color: var(--tc-orange); }
```

Widths were measured against the 648px content column: 72 of the 73 arrays fit; the only
one over is `160#34` at 653px, by 5px. `overflow-x` matters mostly on narrow viewports,
where all of them exceed the column.

The trust predicate is added to the **`[data-katex]` path only**. `math.js:renderInlineText`
uses `renderMathInElement` for inline `\(...\)` in prose and is deliberately left without
it, so `\htmlClass` works in a `MathElement` and nowhere else. That is the whole
requirement here; widening it would extend the trust to author prose across every
element type.

## Testing

The converter is a pure function (table HTML → LaTeX string), so it tests directly
without a database.

1. **Selection rule** — over the real source directory, selects exactly 73 and excludes
   exactly the four `wzór | nazwa` tables.
2. **Trailing `\hline`** — a table whose last row is ruled produces `\\ \hline`, and the
   result parses. Falsify by removing the `or rules[i]` clause; expect the KaTeX error.
3. **Highlight** — a `red_on_yellow` cell produces `\htmlClass{mk mk-amber}{...}`; a
   plain cell does not.
4. **Ragged padding** — a short row pads to the widest, so the column count is uniform.
5. **`\text{}` fallback** — a non-math cell is wrapped, not emitted raw.
6. **Ambiguity resolution** — the four-unit table above is the fixture; assert 423→`130`,
   424→`140`, 425/426→plain.
7. **Idempotency** — running the command twice converts 71 then 0.
8. **Join preservation** — after conversion, `unit`, `parent`, `tab_id`, `order` and
   `title` are unchanged, and the `TableElement` row still exists.
9. **Render** — a converted unit page emits `.el--math` at the position the table held.
10. **CSS contrast** — `--tc-orange` on `--warning-subtle` clears 4.5:1 in both themes,
    in the style of the existing `tests/test_text_colour_css.py`.

Per the project's standing rule, each test is falsified with a mutant chosen from the
failure mode it claims to catch — a test that cannot go red is not evidence.

## Risks

- **A future re-import silently reverts all 71.** `scripts/lal_import/tables.py` still
  hardcodes `"border": "grid"` and still drops rules and highlights. Deliberate: the
  importer is not re-run, and several units in this part have since been split or
  rewritten by hand, so a re-import would destroy more than it restored.
- **Content matching can match hand-authored content** that happens to be byte-identical
  to an imported grid. Mitigated by scoping to the node-408 subtree and by
  `--list-matches`; the same residual risk `recolour_imported_content` documents.
- **The orphaned `TableElement` rows are invisible.** Nothing in the UI lists them, so
  the revert path is a note in this spec, not a feature.
