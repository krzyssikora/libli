# Help pages refresh — slice 1b design (2026-07-17)

## Context

Slice 1a (PR #145, merged) made all 22 in-app help topics **true** — it corrected
drift, but stopped at "the palette shows four groups" and explicitly left
"enumerate each group's contents" to 1b. The docs are now true but **incomplete**:
`courses/models.py:259-291` registers **31** element types (`ELEMENT_MODELS`); the
docs describe **14**. Slice 1b closes that gap.

The evidence base is §2 of the audit findings
(`docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md:111-157`): 17
undocumented element types by palette group, plus per-option MCQ feedback, plus the
nesting/gating rules. This is pure **additive omission** — nothing documented was
deleted or renamed. Slice 1b is authoring, a distinct body of work from 1a's
corrections.

## Goal

Document the 17 missing element types, per-option MCQ feedback, and the
nesting/gating rules — in both languages (EN + PL) — so a Course Admin reading the
authoring manuals sees every element the palette actually offers, described by the
label the product actually renders.

## Scope

**In scope (all confirmed with the user):**

1. The **17 undocumented element types**, across all four palette groups.
2. **Per-option MCQ feedback** (`Choice.feedback` — the field on `class Choice`,
   `courses/models.py:1489,1496`; editor
   `templates/courses/manage/editor/_edit_choicequestion.html:15,41-42`).
3. The **nesting/gating rules** (what containers may hold; lesson-only Interactive;
   quiz-hidden vs nested-hidden groups).

**Out of scope (deferred):**

- Screenshots / illustration (slice 2 owns the seed + screenshot substrate; slice 3
  illustrates). 1b is prose-only.
- The four product gaps already filed as issues #141–#144.
- The `Choice.feedback` `help_text` tidy-up and the PL force-submit catalog
  inconsistency (both in `[[tidyup-backlog]]`; product/catalog changes, not docs).
- The §3.5 H1≠registry mismatches (H01–H04) — a separate deferred follow-up.

## Where it lands — three topics, six markdown files + one registry entry

All three topics are Course-Admin authoring manuals under
`docs/help/course-admin/`, gated `grouping.change_group` (verified: `core/help.py:81-94`
registers `content-editors` and `quiz-editors` exactly this way).

| File | Additions |
|---|---|
| `content-editors.md` + `.pl.md` | **Content** group: Table, Gallery, Callout, Tabs, Columns. **Structure** group: Slide break. The **nesting/gating** treatment (containers introduced here). |
| `quiz-editors.md` + `.pl.md` | **Questions** group: Matrix question, Multi-select grid. **Per-option MCQ feedback** on the Single/Multiple choice section. |
| `interactive-elements.md` + `.pl.md` **(NEW topic)** | The **9 lesson-only Interactive types**: Show more, Fill in & confirm, Choose & confirm, Switch grid, Fill-in table, Spoiler, Step-by-step, Checklist, Guess the number. |
| `core/help.py` | One new `Topic(...)` for the interactive-elements topic, registered directly after `quiz-editors`. |

**Why Slide break lives in content-editors, not builder.** The palette's "Structure"
group is an *editor* concept — elements you insert inside a unit — whereas the
`builder` topic ("Building a course") documents the *course outline* structure
(units, chapters, parts, the four presets). Slide break splits a lesson into slides
within the editor; it is not a course-outline control. It belongs beside the other
palette groups in content-editors. No `builder` cross-link is warranted (adding one
would conflate two unrelated senses of "structure"); if a reader looking at slides
needs it, the natural path is content-editors, which the builder topic already links
to for element editing.

## The new topic — `interactive-elements`

Mirror the `content-editors` registration exactly:

```python
Topic(
    "interactive-elements",
    COURSE_ADMIN,
    "grouping.change_group",
    _("Interactive elements"),
    "help/course-admin/interactive-elements.md",
)
```

- **Slug** `interactive-elements`. **Scope** `COURSE_ADMIN`. **Perm**
  `grouping.change_group` — identical to the two topics it sits beside.
- **Authored PL title** (user-approved): `_("Interactive elements")` → **"Elementy
  interaktywne"**. This is the one new msgid 1b introduces; it needs a `makemessages`
  run and a hand-authored `msgstr`, the same treatment 1a gave "Siatka wielokrotnego
  wyboru".
- **H1 = registry title invariant** (§3.5, established by 1a): the topic's markdown
  `# ` H1 must equal the rendered registry title in *each* language. EN H1
  "Interactive elements"; PL H1 "Elementy interaktywne". Both are authored to match,
  so the new topic satisfies the invariant on creation.
- **Cross-links (the exact edges — the DoD ↔ triangle expanded).** Five links, each
  with its PL sibling:
  1. `content-editors` → `quiz-editors` (Questions group) — *already exists*, keep.
  2. `content-editors` → `interactive-elements` (Interactive group) — new; a parallel
     pointer beside the existing Questions one.
  3. `interactive-elements` → `content-editors` (containers / where these nest) — new.
  4. `interactive-elements` → `quiz-editors` (question elements as the other lesson
     practice) — new.
  5. `quiz-editors` → `interactive-elements` — new; add to `quiz-editors`' "Where
     questions live" / "See also" area, since the Interactive self-checks are the
     lesson-only practice cousins of questions-as-practice. This is the edge that
     makes DoD #6's `interactive-elements ↔ quiz-editors` genuinely bidirectional.

## Ground-truth element names (the cardinal 1a rule)

The single biggest 1a failure was PL docs **inventing translations instead of
quoting the catalog**. Every element name below is the rendered `msgstr`, resolved
from `locale/pl/LC_MESSAGES/django.po` in this worktree (CR-stripped lookup, since
the catalog is CRLF). Implementers quote these verbatim; they do not translate the
English afresh.

| Group | EN label (`_add_menu.html`) | PL msgstr | po line |
|---|---|---|---|
| Content | Table | Tabela | 947 |
| Content | Gallery | Galeria | 955 |
| Content | Callout | **Ramka** | 1064 |
| Content | Tabs | Zakładki | 963 |
| Content | Columns | Kolumny | 969 |
| Questions | Matrix question | Pytanie macierzowe | 2246 |
| Questions | Multi-select grid | Siatka wielokrotnego wyboru | 1003 |
| Structure | Slide break | Podział slajdów | 1018 |
| Interactive | Show more | Pokaż więcej | 1028 |
| Interactive | Fill in & confirm | Uzupełnij i potwierdź | 1040 |
| Interactive | Choose & confirm | Wybierz i zatwierdź | 1046 |
| Interactive | Switch grid | Siatka przełączników | 1052 |
| Interactive | Fill-in table | Tabela do uzupełnienia | 1058 |
| Interactive | Spoiler | Rozwijana treść | 1034 |
| Interactive | Step-by-step | Krok po kroku | 1132 |
| Interactive | Checklist | Lista zadań | 1076 |
| Interactive | Guess the number | Zgadnij liczbę | 1082 |

**Hazard flagged:** Callout's PL is **Ramka** — the exact term the audit (L06) warns
is *not* Iframe. Do not let a nearby "Iframe/Ramka" confusion re-invent it. Quote the
table.

> These msgstrs are the catalog's authority **as it stands in this worktree today**.
> Per 1a's "a failing gate is a hypothesis" and "verify ground truth from source
> before every dispatch" lessons, each implementer task re-resolves the msgid it
> quotes against the live catalog at dispatch time and cites `file:line` on both
> sides — the table is the starting map, not a substitute for that check.

## Nesting / gating — one shared treatment, sourced from code

The rules are enforced server-side by `NESTABLE_TYPE_KEYS`
(`courses/builder.py:34-55`) and courtesy-mirrored in the palette
(`_add_menu.html`). Documented facts (verified against both):

- **Containers** (Tabs, Columns) hold: the 9 Content **leaf** types (Text, Math,
  Image, Video, Iframe, HTML, Table, Gallery, Callout) **and all 9 Interactive
  types**. They cannot hold: **another container** (no Tabs/Columns inside a
  Tabs/Columns), **any Question type**, or **Slide break**.
- **Interactive is lesson-only** — the whole group is hidden in a quiz
  (`_add_menu.html:27` `{% if not unit_is_quiz %}`). Consequence: inside a quiz, a
  container's add-menu offers Content leaves only.
- **Questions, Structure, and the containers themselves are hidden when nested**
  (`_add_menu.html:24,25,41`) — courtesy in the menu, enforced by
  `NESTABLE_TYPE_KEYS` on every add/save (`_add_menu.html:2-8` comment; the server
  "still enforces NESTABLE_TYPE_KEYS … regardless").

Stated once in `content-editors.md` where containers are introduced; the Interactive
topic cross-references it (its 9 types are nestable, so the rule matters there too).

## Per-option MCQ feedback — behavior confirmed as-is

User confirmed the current behavior is intended and should be documented as-is
(clears the `[[tidyup-backlog]]` open question). In `quiz-editors.md`, the Single /
Multiple choice section gains:

- Each **choice** can carry optional **per-option feedback**. It is **symmetric** —
  shown when a student gets an option wrong: a wrong pick, *or* a correct answer they
  missed. This is the product's own wording, quoted from the editor hint
  (`_edit_choicequestion.html:15`: "Optional feedback shows when a student gets an
  option wrong — a wrong pick, or a correct answer they missed."). PL implementer
  resolves that msgid's `msgstr` and quotes it.
- **Verdict-only fallback.** Without per-option feedback, a wrong answer in a
  **lesson** shows only the verdict (correct/incorrect) — the correct choice is *not*
  revealed (PR #132 dropped the reveal list). Per-option feedback is the author's
  opt-in to show the student more than a bare verdict. Document this so an author
  understands what a feedback-less lesson MCQ does.

The existing "Single / Multiple choice" prose (exact-match marking) stays; this is an
addition to that section, not a rewrite.

## Source map — verify behavior against these (for the plan, not prose here)

The implementer describes **every** type's student-visible and author-visible
behavior **verified against its template/model**, never from memory — the cardinal
rule applies to all 17, not just the Interactive 9. Editor-template names below were
confirmed present in `templates/courses/manage/editor/`; models are the
`ELEMENT_MODELS` entries (`courses/models.py:259-291`).

### Content & Questions additions

| Type (EN / PL) | Model | Editor template |
|---|---|---|
| Table / Tabela | `tableelement` | `_edit_table.html` |
| Gallery / Galeria | `galleryelement` | `_edit_gallery.html` |
| Callout / Ramka | `calloutelement` | `_edit_callout.html` |
| Tabs / Zakładki | `tabselement` | `_edit_tabs.html` |
| Columns / Kolumny | `twocolumnelement` | `_edit_twocolumn.html` |
| Matrix question / Pytanie macierzowe | `choicegridquestionelement` | `_edit_choicegridquestion.html` |
| Multi-select grid / Siatka wielokrotnego wyboru | `multigridquestionelement` | `_edit_multigridquestion.html` |

Slide break (`slidebreakelement`) has no editor form — it is a marker element; verify
its meaning against how it renders (the slideshow/deck split), not an editor.

### Interactive types

The implementer describes each type's student-visible and author-visible behavior
**verified against its template/model**, never from memory. The map (form key →
where to verify):

| Type (EN / PL) | Verify behavior against |
|---|---|
| Show more / Pokaż więcej | reveal-gate ("Show more" progressive reveal) — `revealgate` |
| Fill in & confirm / Uzupełnij i potwierdź | `fillgate` (fill-blank trigger + server check) |
| Choose & confirm / Wybierz i zatwierdź | `switchgate` ("Choose ▾" cycler + server pk-check) |
| Switch grid / Siatka przełączników | `switchgrid` (multi-cycler self-check) |
| Fill-in table / Tabela do uzupełnienia | `filltable` (fillable table cells, server-checked, no marks) |
| Spoiler / Rozwijana treść | `spoiler` (`<details>` show/hide, zero JS) |
| Step-by-step / Krok po kroku | `stepper` (inline "Show next" reveal walk) |
| Checklist / Lista zadań | `markdone` (self-tracking, per-student persistent) |
| Guess the number / Zgadnij liczbę | `guessnumber` (locked widget, no commit button) |

Shared framing to establish once in the topic: these are **lesson-only** (not
available in quizzes), most are **self-checks** (student checks their own work; the
family convention is a locked widget with the commit button removed), they record
**no marks**, and they are **nestable** inside Tabs/Columns.

## Gate gotchas carried from 1a (do not rediscover)

- **CRLF everywhere** → `$`-anchors silently fail; `\n` never matches in `-Pz` (use
  `\r?\n`); count `-z` matches with `tr -cd '\0' | wc -c`. Use GNU `grep`, not `rg`.
  (Already bit us once this session on the msgstr lookup.)
- **`makemessages --no-obsolete` is mandatory** for the one new msgid, or the removed
  form survives as `#~`.
- **Positive carve-out gates** — assert a count *stays* at its expected value, not
  merely "absent"; a substring can be correct prose elsewhere.
- **No line number in any doc is authoritative** (1a saw up to 43 lines of drift) —
  locate by searching the quoted string.
- **`tests/test_i18n_catalog.py` is a name collision** — the `#~`-obsolete invariant
  lives in `test_i18n_auth.py` / `test_i18n_notes.py` / `test_tags_i18n.py`.
- **UTF-8 commit messages** — write to a file + `git commit -F`, verify with
  `git log -1 --format=%B` (heredoc paths ASCII-strip em dashes / arrows).

## Definition of Done

1. All **17 element types** documented in EN and PL, each named by its catalog
   `msgstr` (quoted, not invented), in the topic assigned above.
2. **Per-option MCQ feedback** documented in `quiz-editors` (EN + PL), including the
   symmetric behavior and the verdict-only fallback.
3. **Nesting/gating** documented once in `content-editors` (EN + PL), cross-referenced
   from the Interactive topic.
4. **New `interactive-elements` topic** registered in `core/help.py`, EN + PL files
   present, H1 = registry title in both languages, perm-gated `grouping.change_group`.
5. **`_("Interactive elements")` → "Elementy interaktywne"** added to the catalog via
   `makemessages --no-obsolete`; PL `msgstr` authored; no `#~` obsolete entries left.
6. Cross-links added (content-editors ↔ interactive-elements ↔ quiz-editors), EN and
   PL parity.
7. Full non-e2e suite green; `ruff check` + `ruff format --check` clean;
   `tests/test_help.py` passes. That suite is **fully parametrized over `TOPICS`**,
   so the new topic is auto-covered with **no new test to write and no count to
   bump** (there is no hardcoded topic count — contrast the `ELEMENT_MODELS` count
   asserts): `test_topic_folder_matches_role`, `test_topic_english_file_exists_and_renders`,
   `test_topic_polish_file_renders_if_present`, `test_polish_file_is_not_an_english_copy`
   (PL must differ from EN), `test_topic_perm_is_real`, and `test_slugs_are_globally_unique`
   all extend to it automatically. **`test_help_ui_string_translated_to_polish`
   (`test_help.py:280-288`) is the gate for DoD #5** — it iterates `TOPICS` titles and
   fails until "Elementy interaktywne" has a PL `msgstr` ("a newly added topic can
   NEVER escape the translation gate", per its own comment).
8. Every fix or in-flight discovery appended to the audit findings' "Found during
   execution" ledger (§3.6 discipline) so the pre-release re-audit has a true
   baseline.

## Task decomposition (sketch — the plan refines this)

Strictly serial writers (1a's hard lesson: never two implementers on the shared
worktree at once). Roughly:

1. `core/help.py` registry entry + the two `interactive-elements` files scaffolded
   with correct H1s (unblocks cross-links).
2. `content-editors` pair — Content group (5) + Structure (1) + nesting/gating.
3. `quiz-editors` pair — Questions group (2) + per-option MCQ feedback.
4. `interactive-elements` pair — the 9 types + shared lesson-only/self-check framing.
5. Catalog: `makemessages --no-obsolete`, author the one `msgstr`, DoD gates
   (suite, ruff, i18n obsolete-invariant, help registry test).

## Process

Spec → spec-review → plan → plan-review → subagent-driven development, in the
isolated worktree `.claude/worktrees/help-pages-refresh-slice-1b` (branch
`feat/help-pages-refresh-slice-1b`, off master `19c399e` which contains the PR #145
merge). The stale slice-1a worktree is de-registered from git (its branch is merged);
only an OS-locked empty directory lingers.
