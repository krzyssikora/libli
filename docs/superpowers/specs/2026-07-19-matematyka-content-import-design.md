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
- **~702 lessons + ~95 quizzes** (797 HTML files).
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

### Part naming

Slug after the digits → spaces, with Polish diacritics restored by hand
(the source slugs are ASCII-folded). Example:
`005_wyrazenia_algebraiczne` → **"wyrażenia algebraiczne"**.
Each part's restored name is listed in the Phase-1 review doc for approval.

### Chapter grouping and naming

A chapter is the run of files ending at the next `*_quiz.html` (inclusive).
Chapter **names are derived from the lessons' content** (read during Phase 1),
not from filenames, and presented for review/rename before any DB write.

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
`elements: [...]` array where each entry is `{type, …fields}` in libli terms
(e.g. `{"type":"text","body":"<p>…\\(x^2\\)…</p>"}`,
`{"type":"video","asset":"static/zbiory_poczatek.mp4"}`,
`{"type":"spoiler","label":"zobacz","body":"…"}`,
`{"type":"choice","stem":"…","choices":[{text,correct,feedback}], "multi":true}`).
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
+ elements via the ORM, following the proven `seed_demo_course` authoring
pattern:

- Nodes via `get_or_create(course, parent, title, defaults={kind, unit_type})`.
- Concrete element rows created, then attached with
  `Element.objects.create(unit=unit, content_object=obj)` preserving order.
- **Idempotent**: re-running a part does not duplicate nodes, elements, or media
  (media deduped by `(course, original_filename)`; upsert elements per unit).
- Refuses to load any unit that still contains a `flagged` fragment unless a
  `--allow-html` override is passed (that path emits an `HtmlElement` and logs
  it loudly — last resort only).
- Scoped to one part per invocation (`--part 001_zbiory_liczbowe`) for batching.

## 5. Lesson element mapping

Deterministic rules, extended as the scan reveals more repeatable patterns. The
mapping below is the starting set; §1's premise is that this set grows to cover
100% of the content.

| Source pattern | libli element |
|---|---|
| `<h2>/<h3>/<h4>`, `<p>`, `<ul>/<ol>/<li>`, `<strong>/<em>/<b>/<i>/<u>`, `<a>`, `<blockquote>`, `<code>` | **TextElement** (`body` = sanitized HTML; inline `\(…\)` math kept verbatim) |
| `\[ … \]` display-math block | **MathElement** (`latex`) |
| local `<video><source src="static/*.mp4"></video>` | **VideoElement** ← uploaded `MediaAsset(video)` |
| `<img src="…png/jpg">` | **ImageElement** ← uploaded `MediaAsset(image)`; `alt`/`figcaption` from surrounding `<figure>/<figcaption>` |
| geogebra.org / edpuzzle / Lumi `<iframe>` | **IframeElement** (GeoGebra canonicalized via `courses.geogebra`) |
| `div.show_solution.ks_button` + sibling hidden `div.question_solution` | **SpoilerElement** (`label` = button text e.g. "zobacz", `body` = solution HTML+math) |
| `<table class="my_table*">` used as a data table | **TableElement** |
| (discovered during scan — more patterns to be added here) | native element TBD per pattern |
| genuinely unmappable fragment | flag → AI fixup → native; `HtmlElement` only with sign-off |

### Math is delimiter-compatible (no conversion)

The source renders math with MathJax using `\( … \)` (inline) and `\[ … \]`
(display). libli renders with **KaTeX auto-render configured with the exact same
delimiters** (`courses/static/courses/js/editor.js`), so inline math is preserved
**verbatim** inside `TextElement.body`, and display math maps to `MathElement`.
No delimiter rewriting is required.

### Sanitization constraints (drive some mappings)

`TextElement.body` is run through `courses/sanitize.py` (nh3), which allows
`p, br, div, strong, b, em, i, u, h2, h3, h4, ul, ol, li, a, blockquote, code,
pre` and strips everything else. Consequences the parser must respect:

- `<table>` is **not** allowed in text → data tables must become **TableElement**.
- `<sup>/<sub>` are stripped → exponents/indices must live in `\(…\)` LaTeX
  (the source already does this).
- `<img>/<figure>/<video>/<iframe>` are stripped from text → they must be their
  own dedicated elements (as mapped above).

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

Ambiguities resolved during the pilot against real files, asking the author when
unclear:

- single-`[x]` group → single-choice vs. multi-select (likely: exactly one
  correct ⇒ single-choice; ≥2 correct ⇒ multi-select).
- `= value` → numeric vs. text (numeric when the value parses as a number).
- multiple `<p>` before a group all belong to the same stem.

## 7. Media pipeline

- Images and videos become per-course `MediaAsset`s, **deduped by
  `original_filename`** so re-runs never re-upload.
- **Video: local upload by default.** libli's admin-configured video upload
  ceiling will likely need raising. If a specific file exceeds a sane ceiling,
  the fallback (author-approved) is to **split it into smaller clips** imported
  as consecutive VideoElements, or raise the ceiling for that batch.
- GeoGebra / edpuzzle / Lumi remain **external iframes** — no local hosting.
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
