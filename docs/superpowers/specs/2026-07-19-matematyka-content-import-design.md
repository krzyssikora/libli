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

- **21 parts** (three-digit folders), imported in folder order. This count
  **includes** `150_f_wykladnicza`, which is in scope but incomplete (1 lesson, no
  quiz) — imported as a single quiz-less chapter and flagged as incomplete (§3).
- **702 lessons + 95 quizzes** (797 HTML files, exact as of the scan).
- Media: **~253 `.mp4` (~3.6 GB), ~1195 `.png`, ~34 `.jpg`**, plus **157
  GeoGebra** and a few edpuzzle/Lumi external iframes. `.ggb` source files are
  *not* imported — GeoGebra content is already hosted on geogebra.org and
  referenced by iframe.

Out of scope: single-digit folders (`0_R_24_binarny`, `0_R_euklides`) and loose
top-level files.

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
`f_lin_020_…`). **Sort key: the integer value of the *first maximal run of digits*
in the filename, ascending; tie-break lexicographic on the full filename.** The
"first digit run" rule is unambiguous whether or not the file has an alphabetic
prefix (`005…` → 5, `wyr_alg_010…` → 10) and needs no per-folder prefix
assumption. The parser asserts every `.html` file in a part yields a token and
fails loudly on any that doesn't. Two files that yield the **same** token almost
certainly indicate an authoring mistake: the parser still tie-breaks
deterministically but **emits a flag-report warning** rather than resolving it
silently.

### Unit titles

A **lesson** unit's title is taken from the **first `<h2>` in the file** (the
source's lesson heading — see `005_zbiory.html`'s
`<h2>Zbiory - pojęcia podstawowe</h2>`). If a lesson has no `<h2>`, fall back to
the **de-slugged, diacritic-restored filename** (same transform as part names,
minus the ordering token). That first `<h2>` is then **not** also emitted as a
`TextElement` heading (it is the unit title, not body content). A **quiz** unit's
title is **unconditionally** the de-slugged filename, regardless of whether the
quiz file happens to contain an `<h2>` (so a stray heading never becomes the quiz
title). Unit titles appear in the Phase-1 review surface.

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
HTML files ──▶ [parser] ──▶ manifest.json + per-unit JSON ──▶ [loader] ──▶ DB
              (runs ONCE       │        (editable source of      (idempotent
               to seed)        │         truth after seeding)     ORM writes)
                     (flagged fragments)
                              ▼
                     [AI subagent fixups]  ← edits the JSON in place; long tail only
```

Rationale: decoupling **parsing** from **loading** via an intermediate JSON
gives us (a) a reviewable artifact, (b) replayable/idempotent DB writes, and
(c) a surgical seam for AI fixups on just the fragments the deterministic parser
cannot map — instead of 702 non-deterministic whole-file conversions.

### 4.1 Parser (`scripts/lal_import/parser.py`, BeautifulSoup)

- Input: a part folder. Output, per part: a **`manifest.json`** (§4.5) describing
  the chapter tree, plus **one JSON file per unit** (§4.2), plus a **flag report**.
- Walks each lesson's DOM top-to-bottom, emitting an **ordered element list**.
- Recognized patterns are mapped deterministically (§5). Unrecognized fragments
  become `{"type": "html", "flagged": true, "raw": "…"}` **and** an entry in the
  flag report — these are the to-do list for extending the mapping, never the
  intended final output.
- Deterministic: same source → identical output. But **the parser runs to *seed*
  the JSON, not on every load.** Once seeded, the per-part JSON + manifest ARE the
  editable source of truth (chapter names and flagged-fragment fixups are written
  into them — §4.3, §4.5). To protect those edits, a re-parse of an
  already-seeded part is guarded:
  - default: **refuses** to overwrite (errors, listing edited files);
  - `--refresh-unmapped`: regenerates element JSON **only** for units still marked
    `fully_mapped:false` (never-edited, still-flagged), leaving edited units and
    all manifest names untouched;
  - `--force`: regenerates everything from source, discarding **all** edits —
    including the human-authored manifest chapter names — hence explicit and
    last-resort.

  So "re-running a part" in Phase 3 (§8) means re-running the **loader**
  (JSON→DB), which is always idempotent — *not* re-running the parser.

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

Each unit JSON also carries `fully_mapped: <bool>` (false while any fragment is
still `flagged`) **and** a `seed_hash` — the hash of the unit JSON as first
emitted by the parser. `--refresh-unmapped` (§4.1) regenerates a unit only when it
is **both** still-flagged (`fully_mapped:false`) **and** untouched since seed
(current file hash == `seed_hash`). A unit whose partial AI fixup resolved *some*
flagged fragments has a changed hash and is therefore preserved, even though it is
still `fully_mapped:false` — so incremental fixups are never clobbered.

A small **JSON-key → model-field table** is maintained alongside the parser as the
single source of truth for every element type (the loader validates against it).
Media entries reference the **source file path** (`media_src`), resolved **relative
to the directory of the source `.html` file** that the unit came from; the loader
knows that directory from the manifest and reads the bytes there. This JSON is the
human review surface and the loader's input.

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

- **Node identity is keyed on tree position, not title — for every level
  including the Part.** The Part is matched by `(course, order)` where `order` is
  its folder's index in the sorted list of 3-digit folders (recorded as
  `part.order` in the manifest, §4.5, so the loader knows it under `--part`
  without re-scanning); each chapter/unit is matched by `(parent, order)` — the
  0-based index (from the manifest) of its source group/file within the parent.
  `title`, `kind`, `unit_type` are **updated in place** on re-run. This makes the
  loader rename-safe at *all* levels: an author renaming a part or a chapter in the
  Phase-1 review does not create a duplicate subtree when the part is later
  re-run. (No new `ContentNode` field is needed — position is the anchor.)
- **Orphan nodes are pruned.** After matching, the loader **deletes any
  chapter/unit whose `(parent, order)` index is ≥ the current run's child count
  for that parent** (via `ContentNode.delete`, which is subtree-safe). Otherwise a
  re-run that yields fewer chapters/units than before would leave stale
  higher-index subtrees, and "converges to exactly the manifest" would not hold.
- **Elements are rebuilt, not upserted.** On each run, for every unit being
  (re)loaded the loader deletes all existing `Element` rows and their concrete
  element objects (via the model's own subtree-safe delete), then recreates the
  full ordered element list from the JSON. Concrete element rows have no natural
  identity, so a clean rebuild is the only well-defined idempotency mechanism.
  Re-running a part therefore converges to exactly the JSON's content with no
  duplication. Deleting a concrete `ImageElement`/`VideoElement` does **not**
  cascade to its `MediaAsset` (the element→asset FK is `on_delete=PROTECT`, on the
  asset side), so the shared asset survives an element rebuild; the rebuild
  **re-attaches** the asset by content-hash lookup (§7) rather than re-creating it.
  (Because units are deleted+rebuilt, any per-student progress on a unit is not
  preserved across a re-run — acceptable for an authoring import into a
  not-yet-live course; noted so it is a conscious choice.)
- **Media deduped durably by content hash**, not basename, and not just
  per-run — see §7.
- Refuses to load any unit that still contains a `flagged` fragment unless a
  `--allow-html` override is passed (that path emits an `HtmlElement` and logs
  it loudly — last resort only).
- Asserts every iframe host is on the embed allowlist before writing (§7, C2).
- Scoped to one part per invocation (`--part 001_zbiory_liczbowe`) for batching.

### 4.5 Per-part structure manifest (`manifest.json`) and flag report

The parser emits, per part, a manifest — the loader's structural input, so it never
re-derives the tree implicitly. It enumerates, in order:

```
{
  "part": {"source_folder": "001_zbiory_liczbowe", "order": 0, "title": "zbiory liczbowe"},
  "chapters": [
    {"order": 0, "title": "<human/AI-authored name>",
     "units": [
       {"order": 0, "unit_json": "005_zbiory.json", "source_html": "005_zbiory.html",
        "source_dir": "001_zbiory_liczbowe", "unit_type": "lesson", "title": "…"},
       ...
     ]}
  ]
}
```

`part.order` is the folder's index in the sorted list of 3-digit folders — the
loader's rename-safe anchor for the Part node (§4.4). Chapter `title`s start as
parser placeholders and are filled by the Phase-1 reading pass ("Chapter grouping
and naming", §3) — the manifest is where those human-facing names live and survive
loader re-runs. `source_dir` gives the loader the base for resolving each unit's
`media_src` paths. The manifest is a committed deliverable and the Phase-1 review
surface for structure.

Alongside the manifest, the parser writes a **per-part flag report**
(`flags.json`): a list of `{unit_json, kind, reason, raw_excerpt}` records, one per
flagged fragment or warning (unmapped pattern, duplicate ordering token, mixed
Zadanie, unknown hint form, over-length choice, relative `<a>` href, spanning
table, …). It is the AI-fixup worklist (§4.3) and part of the Phase-1 summary
(§8). Both `manifest.json` and `flags.json` live in the part's JSON output
directory.

## 5. Lesson element mapping

Deterministic rules, extended as the scan reveals more repeatable patterns. The
mapping below is the starting set; §1's premise is that this set grows to cover
100% of the content.

| Source pattern | libli element |
|---|---|
| `<h2>/<h3>/<h4>`, `<p>`, `<ul>/<ol>/<li>`, `<strong>/<em>/<b>/<i>/<u>`, `<a>`, `<blockquote>`, `<code>` | **TextElement** (`body` = sanitized HTML; inline `\(…\)` math with `<`/`>` entity-escaped — see below) |
| `\[ … \]` that is the **sole content of its block** | **MathElement** (`latex`, raw — no escaping) |
| `\[ … \]` occurring **mid-paragraph** (with surrounding text) | kept **inline** in the `TextElement` body, `<`/`>`-escaped like `\(…\)` |
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
column count per row. Header **rows** (`<th>` or the first row) and header **columns** (first-column
`<th>`) map to the `TableElement` header mechanism (or, if it supports only one
header axis, the unsupported axis is flagged rather than rendered as plain data);
**math inside cells** is supported (cells are
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

**HTML embodiment (how the DSL sits in the DOM).** In the source files the DSL
tokens are **bare text lines**, not wrapped in any tag — they appear as top-level
`NavigableString` text nodes *between* the `<p>` stem elements (confirmed in
`001_zbiory_liczbowe/039_zbiory_quiz.html`, e.g. a `<p>…</p>` stem followed by raw
lines `[x] \(3\in A\)`, `[ ] \(6\in A\) {{selected: …}}`, `= 2`). The parser
therefore walks the fragment's **top-level nodes in order**: an `<p>`/`<div>`
element is stem prose; a text node is split on newlines and each non-empty line is
classified by its **first non-space character(s)**:
- `[x]`/`[ ]`/`(x)`/`( )` → a choice option (bracket shape sets `multiple`, §below);
  a trailing `{{selected:…}}` on the same line is that option's feedback;
- a line whose first non-space char is `=` → a fill-in answer;
- an HTML comment `<!-- Zadanie N -->` → a question boundary.

Because a `=` sign also occurs *inside math* (`\(x = 3\)`), a `=` counts as answer
DSL **only** when it is the first non-space character of a top-level text line
(never inside a `\(…\)`/`\[…\]` span and never inside a `<p>` stem). Anything that
doesn't match a known DSL shape at top level is **flagged**, not silently dropped.
The exact whitespace/line conventions are re-confirmed against the real files in
the pilot.

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
- **ShortText answer matching** is specified, not left implicit like numerics
  were: the parser inspects `ShortTextQuestionElement`'s comparison semantics in
  the pilot (case sensitivity, whitespace trimming, Polish-diacritic handling) and
  normalizes the stored answer to match that contract; the chosen rules are
  recorded in the pilot notes.
- **Mixed Zadanie** — a single `<!-- Zadanie N -->` block that contains **both** a
  `[ ]/( )` option group **and** a `= value` line maps to no single element. Such
  a block is **flagged** for author resolution (split into two questions, or pick
  one), never silently reduced to one construct with the other dropped.
- multiple `<p>` before a group all belong to the same stem.
- **Unknown hint forms:** only `{{selected:…}}` is mapped to per-option feedback.
  Any other `{{…}}` hint form (e.g. `{{unselected:…}}`, general hints) is
  **flagged**, not silently ignored or swept into `raw`.
- **Field-length ceilings:** `Choice.text` and `Choice.feedback` are
  `max_length=500`. An option or `{{selected:…}}` feedback (LaTeX inflates length)
  that would exceed 500 chars is flagged for author attention, not silently
  truncated.

## 7. Media pipeline

- Images and videos become per-course `MediaAsset`s, **deduped durably by content
  hash (SHA-256 of the file bytes)**, not by basename. `MediaAsset` has no DB
  uniqueness or hash field today; this import **adds a nullable indexed
  `content_hash` field to `MediaAsset` (one small migration)** and the loader,
  before creating an asset, **queries `MediaAsset` by `(course, content_hash)`**
  and reuses any hit. This makes dedup survive across the one-part-per-invocation
  boundary and across re-runs (a per-run in-memory map alone would re-create
  assets every invocation, since two parts are never in the same run and a re-run
  starts with an empty map — leaking orphans). Basename collisions across the
  ~1195 pngs (e.g. `rys1.png` in `001/static` and `007/static`) are handled for
  free: different bytes → different hash → different asset. `original_filename` is
  stored for display only.
- **Orphan-asset sweep.** Because element rebuilds (§4.4) can leave a `MediaAsset`
  with no referencing element, the loader runs an optional
  `--gc-media` sweep that deletes course `MediaAsset`s referenced by no element.
  Off by default (a shared asset may be re-referenced by a not-yet-loaded part);
  run once after the full batch.
- **Video: local upload by default.** The admin-configured video ceiling is
  enforced in `MediaAsset.clean()` (via `validate_video_file`), which Django runs
  on `full_clean()` — **not** automatically on `save()`/`objects.create()`. The
  loader must decide explicitly: if it creates assets via plain ORM `create()` it
  **bypasses the ceiling entirely** (no raise needed, but we own file sanity); if
  it calls `full_clean()` first (recommended, to also catch bad extensions) the
  ceiling applies and must be raised. This is confirmed and chosen in the pilot.
  Where a genuinely oversized file is undesirable regardless, the author-approved
  fallback is to **split it into smaller clips** imported as consecutive
  VideoElements.
- GeoGebra / edpuzzle / Lumi remain **external iframes** — no local hosting.
  `IframeElement.url` is validated by `validate_embed_url` against
  `settings.ALLOWED_EMBED_DOMAINS`, whose default (`config/settings/base.py`) is
  only youtube/youtu.be/vimeo/geogebra. **edpuzzle and Lumi are not on it** and
  every such iframe would fail model validation at load. Before loading, the exact
  edpuzzle/Lumi hostnames (confirmed from the source files) must be added via
  `LIBLI_ALLOWED_EMBED_DOMAINS` (env) or the base default. The loader asserts each
  iframe host is allowlisted and refuses to run otherwise (fail loud, not silent
  skip).
- Media resolution happens in the loader: a unit's `media_src` is resolved
  **relative to that unit's `source_dir`** (from the manifest, §4.5 — the
  directory of the originating `.html`), so the loader reads the right bytes even
  though `media_src` values like `static/foo.mp4` are ambiguous on their own.

## 8. Workflow & batching

**Phase 1 — Scan & seed (immediately after spec approval).**
This is the **sole parser-seeding pass**: run the parser across **all 21 parts**
once, producing every part's `manifest.json` + unit JSON + `flags.json`. Read
content to derive chapter names (written into the manifests). Produce a **review
document**: every Part → its Chapters (proposed names) → its Units, plus a summary
of flagged/unmapped patterns. Author reviews and renames before any DB writes. No
DB changes in this phase. After Phase 1, the JSON + manifests are the editable
source of truth (§4.1); later phases do **not** re-seed them.

**Phase 2 — Pilot (part `001_zbiory_liczbowe`).**
Actually build part 001 into the local "matematyka" course (writing to the local
dev DB — §9, not a production target). It exercises video, math, data tables, the
reveal/spoiler pattern, and 5 quizzes — broad coverage. Author reviews it
**rendered in libli**. Conversion rules and mappings are locked based on findings.

**Phase 3 — Batches (remaining 20 parts).**
One part per batch, in folder order. Each batch operates on the **already-seeded**
JSON from Phase 1: fixup flagged (§4.3) → load → author spot-check. No re-seeding.
New parser rules discovered mid-run are re-applied to a part only via
`--refresh-unmapped` (regenerates just still-flagged, untouched-since-seed units,
§4.1 — preserving edits); the **loader** is then re-run (always idempotent).

## 9. Isolation & safety

- All repo changes happen in the git worktree
  `worktree-matematyka-content-import` (a parallel session shares this repo dir;
  branch is verified immediately before any commit/push — see the
  "shared-worktree, wrong-branch" hazard).
- The loader writes to the local dev DB only; it is idempotent and part-scoped,
  so a bad batch can be corrected and re-run without cleanup.

## 10. Deliverables

1. `scripts/lal_import/parser.py` (+ helpers) — HTML → `manifest.json` + unit JSON,
   including the JSON-key → model-field table (§4.2).
2. Per-part **`manifest.json`** (§4.5) + intermediate unit-JSON tree — reviewable,
   git-ignored or committed per author preference (§11).
3. A migration adding a nullable indexed **`MediaAsset.content_hash`** (§7).
4. `courses/management/commands/import_lal_content.py` — manifest+JSON → DB loader
   (with `--refresh-unmapped`, `--force`, `--allow-html`, `--gc-media` flags).
5. Phase-1 review document (parts/chapters/units + flag summary).
6. The populated "matematyka" course.

## 11. Open questions / to confirm during pilot

- The video-ceiling **enforcement point** (`full_clean()` vs bypassed on
  `create()`), and hence whether any ceiling raise or video splitting is needed
  at all (§7).
- Whether the intermediate JSON + manifest are committed to the repo or kept
  local-only.
- The precise single-choice vs. multi-select DSL signal (`( )` radios present?),
  numeric normalization, and ShortText matching rules, against real quiz files.
- Whether `TableElement` supports a header **column** (first-column `<th>`) as well
  as header rows — drives the §5 data-table mapping (support it, or flag the axis).
- Whether the `show_solution` *table-of-reveals* pattern should render as N
  independent Spoilers (default) or a single grouped element — confirmed
  "Spoiler is fine" for the pilot; revisit if the scan shows a better native fit.
