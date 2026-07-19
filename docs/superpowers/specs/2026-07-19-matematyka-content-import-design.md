# Design: Importing the "matematyka" course from LAL HTML content

**Date:** 2026-07-19
**Status:** Approved (brainstorming), pending spec review

## 1. Goal

Populate the existing local **"matematyka"** course with content that currently
lives as static HTML in `C:\Users\krzys\Documents\teaching\LAL\html`, in every
folder whose name starts with three digits (`001_…` through `150_…`).

The content must be expressed with **native libli elements**, not dumped as raw
HTML blocks. The libli element vocabulary was in fact designed *from* these HTML
files, so the working assumption is that **the entire course can be converted
with zero `HtmlElement`s**. Any fragment the parser cannot map natively is a
signal to *extend the mapping* (add a parser rule, or convert semantically via an
AI pass) — not to ship an HTML blob. An actual `HtmlElement` is a last-resort
escape hatch that requires explicit human sign-off.

## 2. Scope

- **21 parts** (three-digit folders), imported in folder order.
- **702 lessons + 95 quizzes** (797 HTML files, exact as of the scan).
- Media: **~253 `.mp4` (~3.6 GB), ~1195 `.png`, ~34 `.jpg`**, plus **157
  GeoGebra** and a few edpuzzle/Lumi external iframes. `.ggb` source files are
  *not* imported — GeoGebra content is already hosted on geogebra.org and
  referenced by iframe.

Out of scope: single-digit folders (`0_R_24_binarny`, `0_R_euklides`), loose
top-level files, and the `150_f_wykladnicza` part is imported but flagged as
incomplete (1 lesson, no quiz).

## 3. Target tree mapping

libli models content as a `ContentNode` tree
(`Part → Chapter → Section → Unit`), where a **Unit** is the only
element-bearing leaf and carries `unit_type ∈ {lesson, quiz}`. The source maps
directly:

| Source | libli node |
|---|---|
| one 3-digit folder | **Part** |
| consecutive files up to & including a `*_quiz.html` | **Chapter** |
| one `.html` file | **Unit** (`lesson`, or `quiz` if name ends `_quiz`) |
| pieces within a lesson | ordered **Element**s on the unit |

### File ordering within a part

Chapter grouping and element order depend on the order of `.html` files in a
folder. Filenames carry a numeric token (`005_…`, `wyr_alg_010_…`,
`f_lin_020_…`). **Sort key: the integer value of the ordering token, ascending;
tie-break lexicographic on the full filename.** For `NNN_slug.html` the token is
the leading number; for `prefix_NNN_slug.html` (e.g. `wyr_alg_`, `f_lin_`) it is
the number after the shared alphabetic prefix. The parser asserts every `.html`
file in a part yields a sortable token and fails loudly on any that doesn't, so
ordering is never silently wrong.

### Unit titles

A unit's title is taken from the **first `<h2>` in the file** (the source's
lesson heading — see `005_zbiory.html`'s `<h2>Zbiory - pojęcia podstawowe</h2>`).
If a file has no `<h2>`, fall back to the **de-slugged, diacritic-restored
filename** (same transform as part names, minus the ordering token). That first
`<h2>` is then **not** also emitted as a `TextElement` heading (it is the unit
title, not body content). Quiz units, which have no `<h2>`, take the de-slugged
filename. Unit titles appear in the Phase-1 review surface.

### Part naming

Slug after the digits → spaces, with Polish diacritics restored by hand
(the source slugs are ASCII-folded). Example:
`005_wyrazenia_algebraiczne` → **"wyrażenia algebraiczne"**.
Each part's restored name is listed in the Phase-1 review doc for approval.

### Chapter grouping and naming

A chapter is the run of files ending at the next `*_quiz.html` (inclusive) — this
*grouping* is deterministic. The chapter **name**, by contrast, is derived from
the lessons' content by a **human/AI reading pass in Phase 1**, not by the parser.
Name derivation is therefore explicitly **outside** the parser's "same input →
identical JSON" guarantee (§4.1): the parser emits the grouping and a placeholder
title; the reading pass fills the human-facing name, which the author reviews and
edits before any DB write.

### Edge cases

- **Trailing lessons after the last quiz** in a folder (e.g. `300_podsumowanie`
  in `001`): grouped into a final **quiz-less chapter** (name derived, e.g.
  "Podsumowanie").
- **`150_f_wykladnicza`** (1 lesson, 0 quizzes): imported as a single
  quiz-less chapter; flagged "incomplete" in the review doc.
- A part that begins with lessons and has its first quiz partway through works
  naturally — every file before the first quiz joins chapter 1.

## 4. Architecture: two-stage pipeline

```
HTML files ──▶ [parser] ──▶ per-unit JSON ──▶ [loader mgmt cmd] ──▶ DB
                              │                    (idempotent ORM writes)
                     (flagged fragments)
                              ▼
                     [AI subagent fixups]   ← only the long tail
```

Rationale: decoupling **parsing** from **loading** via an intermediate JSON
gives us (a) a reviewable artifact, (b) replayable/idempotent DB writes, and
(c) a surgical seam for AI fixups on just the fragments the deterministic parser
cannot map — instead of 702 non-deterministic whole-file conversions.

### 4.1 Parser (`scripts/lal_import/parser.py`, BeautifulSoup)

- Input: a part folder. Output: **one JSON file per unit** plus a **per-part
  flag report**.
- Walks each lesson's DOM top-to-bottom, emitting an **ordered element list**.
- Recognized patterns are mapped deterministically (§5). Unrecognized fragments
  become `{"type": "html", "flagged": true, "raw": "…"}` **and** an entry in the
  flag report — these are the to-do list for extending the mapping, never the
  intended final output.
- Deterministic and re-runnable: same input → identical JSON.

### 4.2 Intermediate JSON (unit payload)

One file per unit describing: `unit_type`, `title`, and an ordered
`elements: [...]` array where each entry is `{type, …fields}`. **JSON field names
mirror the concrete model fields exactly** (so parser and loader can't drift):

- `{"type":"text","body":"<p>…\\(x^2\\)…</p>"}` → `TextElement.body`
- `{"type":"video","media_src":"static/zbiory_poczatek.mp4"}` → resolved to
  `VideoElement.media` (a `MediaAsset` FK; the JSON holds the *source path*, hence
  the distinct `media_src` key, not the model's `media`)
- `{"type":"spoiler","label":"zobacz","body":"…"}` → `SpoilerElement.{label,body}`
- `{"type":"choice","stem":"…","multiple":true,"choices":[{"text":…,"correct":…,"feedback":…}]}`
  → `ChoiceQuestionElement.multiple` + `Choice.{text,is_correct,feedback}`

A small **JSON-key → model-field table** is maintained alongside the parser as the
single source of truth for every element type (the loader validates against it).
Media entries reference the **source file path**; the loader resolves them to
`MediaAsset`s. This JSON is the human review surface and the loader's input.

### 4.3 AI fixups

Only units whose JSON contains `flagged` fragments are routed to an AI subagent,
which rewrites those fragments into native element entries (or proposes a new
reusable parser rule when the pattern repeats). Goal: drive `flagged` count to
zero before load. Repeating flagged patterns are promoted into parser rules
rather than fixed one-by-one.

### 4.4 Loader (`courses/management/commands/import_lal_content.py`)

A Django management command that reads unit JSON for a part and writes the tree
+ elements via the ORM. It borrows `seed_demo_course`'s element-attachment call
(`Element.objects.create(unit=unit, content_object=obj)`) but **NOT** its
`_upsert` reconciliation — `_upsert` keys on "the join-row from this unit to an
instance of this model" and so assumes **at most one element of each type per
unit**. LAL lessons contain many `TextElement`s, `ImageElement`s, `VideoElement`s
each, which `_upsert` would collapse to one. Instead:

- **Node identity is keyed on tree position, not title.** A part is matched by
  its source folder; each chapter/unit is matched by `(parent, order)` — the
  0-based index of its source group/file within the parent — with `title`,
  `kind`, `unit_type` **updated in place** on re-run. This makes the loader
  rename-safe: an author renaming a chapter in the Phase-1 review does not create
  a duplicate subtree when the part is later re-run.
- **Elements are rebuilt, not upserted.** On each run, for every unit being
  (re)loaded the loader deletes all existing `Element` rows and their concrete
  element objects (via the model's own subtree-safe delete), then recreates the
  full ordered element list from the JSON. Concrete element rows have no natural
  identity, so a clean rebuild is the only well-defined idempotency mechanism.
  Re-running a part therefore converges to exactly the JSON's content with no
  duplication. (Because units are deleted+rebuilt, any per-student progress on a
  unit is not preserved across a re-run — acceptable for an authoring import into
  a not-yet-live course; noted so it is a conscious choice.)
- **Media deduped by content hash**, not basename — see §7.
- Refuses to load any unit that still contains a `flagged` fragment unless a
  `--allow-html` override is passed (that path emits an `HtmlElement` and logs
  it loudly — last resort only).
- Asserts every iframe host is on the embed allowlist before writing (§7, C2).
- Scoped to one part per invocation (`--part 001_zbiory_liczbowe`) for batching.

## 5. Lesson element mapping

Deterministic rules, extended as the scan reveals more repeatable patterns. The
mapping below is the starting set; §1's premise is that this set grows to cover
100% of the content.

| Source pattern | libli element |
|---|---|
| `<h2>/<h3>/<h4>`, `<p>`, `<ul>/<ol>/<li>`, `<strong>/<em>/<b>/<i>/<u>`, `<a>`, `<blockquote>`, `<code>` | **TextElement** (`body` = sanitized HTML; inline `\(…\)` math with `<`/`>` entity-escaped — see below) |
| `\[ … \]` display-math block | **MathElement** (`latex`) |
| local `<video><source src="static/*.mp4"></video>` | **VideoElement** ← uploaded `MediaAsset(video)` |
| `<img src="…png/jpg">` | **ImageElement** ← uploaded `MediaAsset(image)`; `alt`/`figcaption` from surrounding `<figure>/<figcaption>` |
| geogebra.org / edpuzzle / Lumi `<iframe>` | **IframeElement** (GeoGebra canonicalized via `courses.geogebra`; edpuzzle/Lumi require an allowlist change — see below) |
| `div.show_solution.ks_button` + sibling hidden `div.question_solution` | **SpoilerElement** (`label` = button text e.g. "zobacz", `body` = solution HTML+math) |
| `<table class="my_table*">` used as a data table | **TableElement** (rectangular grids only — see note) |
| (discovered during scan — more patterns to be added here) | native element TBD per pattern |
| genuinely unmappable fragment | flag → AI fixup → native; `HtmlElement` only with sign-off |

### Data tables (span/header/math handling)

`TableElement` stores a **rectangular grid**. The parser converts a source
`<table>` only when it is a plain rectangle: no `rowspan`/`colspan`, consistent
column count per row. Header rows (`<th>` or the first row) map to the
`TableElement` header mechanism; **math inside cells** is supported (cells are
rich text, so the same `<`/`>`-in-math escaping below applies per cell). A table
using spans, nested tables, or ragged rows is **flagged** for AI/author fixup
(re-expressed as a rectangular table, or split), never dropped. The `show_solution`
concept→reveal tables in §5 are *not* data tables — they map to SpoilerElements,
not TableElement. The pilot's coverage checklist includes at least one data table.

### Math is delimiter-compatible, but `<`/`>` inside math MUST be escaped

The source renders math with MathJax using `\( … \)` (inline) and `\[ … \]`
(display). libli renders with **KaTeX auto-render configured with the exact same
delimiters** (`courses/static/courses/js/editor.js`), so **no delimiter rewriting
is required** and display math maps to `MathElement`.

**However, inline math is not preserved verbatim.** `TextElement.body` is passed
through nh3 (`courses/sanitize.py`), an HTML parser, *before* KaTeX ever sees it.
A math fragment like `\(y<z\)` or `\(a>b\)` — pervasive in a math course — is
parsed as a stray HTML tag and **silently deleted** (verified: input
`<p>gdy \(x < 3\) oraz \(y<z\)\)</p>` loses the whole `\(y<z\)` span). Therefore
the parser MUST, for every `\(…\)` and `\[…\]` span it emits into a
`TextElement`/`SpoilerElement`/table-cell body, **entity-escape `<`→`&lt;` and
`>`→`&gt;` inside the span**. nh3 leaves entities intact, the browser decodes
them back to `<`/`>` in the DOM, and KaTeX then typesets correctly. `MathElement.latex`
is a plain `TextField` (no HTML sanitize) so its LaTeX is stored raw. This escaping
is an explicit parser rule with a regression test (`\(a<b\)` must survive a
sanitize round-trip).

### Sanitization constraints (drive some mappings)

`TextElement.body` is run through `courses/sanitize.py` (nh3), which allows
`p, br, div, strong, b, em, i, u, h2, h3, h4, ul, ol, li, a, blockquote, code,
pre` and strips everything else. Consequences the parser must respect:

- `<table>` is **not** allowed in text → data tables must become **TableElement**.
- `<sup>/<sub>` are stripped → exponents/indices must live in `\(…\)` LaTeX
  (the source already does this).
- `<img>/<figure>/<video>/<iframe>` are stripped from text → they must be their
  own dedicated elements (as mapped above).
- `<a href>` allows only `http/https/mailto` schemes; a **relative or local-file
  `href`** (e.g. a link to another lesson file) is dropped by nh3, silently losing
  the target. The parser flags relative/local `<a>` hrefs for author attention
  (rewrite to an absolute URL or an in-course link, or drop deliberately) rather
  than letting them vanish.

## 6. Quiz DSL parser (OpenEdX-style)

Quiz files interleave `<p>` stems with an answer DSL:

- `[x]` / `[ ]` lines = choice options; `[x]` marks a correct option.
- `{{selected: … }}` after an option = feedback shown when that option is picked.
- `= <value>` line = a fill-in answer (numeric or short text).
- `<!-- Zadanie N -->` comments delimit questions (also inferable from blank
  lines / stem `<p>` boundaries).

Mapping:

| DSL construct | libli element |
|---|---|
| a `[x]/[ ]` option group | **ChoiceQuestionElement** + `Choice` rows; per-option `{{selected:…}}` → the choice's feedback field |
| `= <number>` | **ShortNumericQuestionElement** |
| `= <text>` | **ShortTextQuestionElement** |

Widget-type and answer rules (confirmed against real files in the pilot, asking
the author when unclear):

- **Single- vs multi-select is a DSL signal, not a correct-count inference.**
  Widget type (`ChoiceQuestionElement.multiple`, radio vs checkbox — which changes
  UX *and* exact-set-match grading) is authoring intent and must not be guessed
  from how many options are correct (a legitimate multi-select can have exactly
  one correct answer). In the OpenEdX DSL, `[ ]`/`[x]` (square brackets) = checkbox
  = **multi-select**, and `( )`/`(x)` (parentheses) = radio = **single-choice**.
  The parser reads the bracket shape to set `multiple`. The samples seen so far are
  all `[ ]` (multi); the pilot confirms whether any `( )` radio questions exist.
- `= value` → numeric vs. text: **ShortNumericQuestionElement** when the value
  parses as a number, else **ShortTextQuestionElement**. Numerics must handle the
  **Polish decimal comma** (`2,5` ≡ `2.5`) and common equivalent forms
  (`1/2` ≡ `0.5`); the exact comparison/tolerance semantics of
  `ShortNumericQuestionElement` are inspected during the pilot and the parser
  normalizes to whatever that field expects. **Multiple `=` lines** for one
  question are treated as alternative accepted answers (verify the model supports
  this; otherwise flag).
- multiple `<p>` before a group all belong to the same stem.
- **Field-length ceilings:** `Choice.text` and `Choice.feedback` are
  `max_length=500`. An option or `{{selected:…}}` feedback (LaTeX inflates length)
  that would exceed 500 chars is flagged for author attention, not silently
  truncated.

## 7. Media pipeline

- Images and videos become per-course `MediaAsset`s, **deduped by content hash
  (SHA-256 of the file bytes)**, not by basename. `MediaAsset` has no DB
  uniqueness; dedup is loader logic. Two physically different files that share a
  basename across different part folders (plausible among ~1195 pngs, e.g.
  `rys1.png` in `001/static` and `007/static`) would collide under a basename key
  and silently substitute the wrong media — hashing the bytes avoids this while
  still collapsing genuine duplicates. The loader keeps a hash→MediaAsset map for
  the run; `original_filename` is stored for display only.
- **Video: local upload by default.** libli's admin-configured video upload
  ceiling will likely need raising. If a specific file exceeds a sane ceiling,
  the fallback (author-approved) is to **split it into smaller clips** imported
  as consecutive VideoElements, or raise the ceiling for that batch.
- GeoGebra / edpuzzle / Lumi remain **external iframes** — no local hosting.
  `IframeElement.url` is validated by `validate_embed_url` against
  `settings.ALLOWED_EMBED_DOMAINS`, whose default (`config/settings/base.py`) is
  only youtube/youtu.be/vimeo/geogebra. **edpuzzle and Lumi are not on it** and
  every such iframe would fail model validation at load. Before loading, the exact
  edpuzzle/Lumi hostnames (confirmed from the source files) must be added via
  `LIBLI_ALLOWED_EMBED_DOMAINS` (env) or the base default. The loader asserts each
  iframe host is allowlisted and refuses to run otherwise (fail loud, not silent
  skip).
- Media resolution happens in the loader (JSON references source paths; loader
  reads bytes from the source tree and creates/reuses the asset).

## 8. Workflow & batching

**Phase 1 — Scan (immediately after spec approval).**
Run the parser across **all 21 parts**; read content to derive chapter names;
produce a **review document**: every Part → its Chapters (proposed names) →
its Units, plus a summary of flagged/unmapped patterns discovered. Author
reviews and renames before any DB writes. No DB changes in this phase.

**Phase 2 — Pilot (part `001_zbiory_liczbowe`).**
Fully build part 001 into the live "matematyka" course. It exercises video,
math, data tables, the reveal/spoiler pattern, and 5 quizzes — broad coverage.
Author reviews it **rendered in libli**. Conversion rules and mappings are
locked based on findings.

**Phase 3 — Batches (remaining 20 parts).**
One part per batch, in folder order. Each batch: parse → fixup flagged → load →
author spot-check. New patterns discovered mid-run are added to the mapping and,
if they affect already-imported parts, those parts are re-run (idempotent).

## 9. Isolation & safety

- All repo changes happen in the git worktree
  `worktree-matematyka-content-import` (a parallel session shares this repo dir;
  branch is verified immediately before any commit/push — see the
  "shared-worktree, wrong-branch" hazard).
- The loader writes to the local dev DB only; it is idempotent and part-scoped,
  so a bad batch can be corrected and re-run without cleanup.

## 10. Deliverables

1. `scripts/lal_import/parser.py` (+ helpers) — HTML → unit JSON.
2. Intermediate unit-JSON tree (per part) — reviewable, git-ignored or committed
   per author preference.
3. `courses/management/commands/import_lal_content.py` — JSON → DB loader.
4. Phase-1 review document (parts/chapters/units + flag summary).
5. The populated "matematyka" course.

## 11. Open questions / to confirm during pilot

- Exact ceiling value for video upload; which (if any) videos need splitting.
- Whether intermediate JSON is committed to the repo or kept local-only.
- The precise single-choice vs. multi-select and numeric vs. text rules, against
  real quiz files.
- Whether the `show_solution` *table-of-reveals* pattern should render as N
  independent Spoilers (default) or a single grouped element — confirmed
  "Spoiler is fine" for the pilot; revisit if the scan shows a better native fit.
