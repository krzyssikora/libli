# Help pages refresh — slice 1b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the 17 element types the palette registers but the help never described, plus per-option MCQ feedback and the nesting/gating rules, across three Course-Admin authoring topics in EN and PL.

**Architecture:** Additive documentation only — no product code changes. Two existing topics (`content-editors`, `quiz-editors`) gain their missing group members; one new topic (`interactive-elements`) is registered and written. Every element name is quoted from the rendered PL `msgstr`, never translated afresh. The one new translatable string is the new topic's title.

**Tech Stack:** Django help registry (`core/help.py`), markdown help docs (`docs/help/course-admin/*.md` + `.pl.md`), Django i18n catalog (`locale/pl/LC_MESSAGES/django.po`), `makemessages`, pytest (`tests/test_help.py`), ruff.

## Global Constraints

Copied verbatim from the spec (`docs/superpowers/specs/2026-07-17-help-pages-refresh-slice-1b-design.md`). Every task implicitly includes these.

- **Quote the catalog, never invent PL.** Every element name is the rendered `msgstr` from `locale/pl/LC_MESSAGES/django.po`. Use the ground-truth table below; re-resolve each `msgid` against the live catalog at implementation time and confirm the `msgstr` still matches before quoting it.
- **Verify behavior against source, never from memory.** Describe each type's student- and author-visible behavior only after reading its editor template / model (source map below).
- **CRLF everywhere.** The repo forces CRLF in the working tree. In grep gates: never use `$` line-anchors; `\n` never matches in `-Pz` (use `\r?\n`); count `-z` matches with `tr -cd '\0' | wc -c`. Use GNU `grep`, prefer `grep -F` for fixed strings. No doc line number is authoritative — locate by searching the quoted string.
- **`makemessages --no-obsolete` is mandatory** for the one new msgid, or the form survives as `#~`.
- **PL/EN parity.** Every EN addition has a PL sibling addition; every EN cross-link has its PL sibling with translated link text and the same (English) slug.
- **UTF-8 commit messages** — write the message to a file and `git commit -F`, then verify with `git log -1 --format=%B` (heredocs ASCII-strip em dashes / arrows).
- **Append to the §3.6 ledger.** Every fix or in-flight discovery is appended to `docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md` "Found during slice-1a execution" section (extend it for 1b) so the pre-release re-audit has a true baseline.
- **Strictly serial writers.** Only one implementer touches the shared worktree at a time (a read-only reviewer may overlap the next implementer, never two writers).

### Ground-truth element names (re-verify each at implementation time)

| Group | EN label | PL msgstr | msgid line (msgstr = next line) |
|---|---|---|---|
| Content | Table | Tabela | 947 |
| Content | Gallery | Galeria | 955 |
| Content | Callout | Ramka | 1064 |
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

> **Hazard:** Callout's PL is **Ramka** — the exact term the audit (L06) warns is *not* Iframe (Iframe stays "Iframe"). Do not let a nearby Iframe/Ramka confusion re-invent it.

### Source map — verify behavior against these

Content & Questions additions:

| Type (EN / PL) | Model | Editor template |
|---|---|---|
| Table / Tabela | `tableelement` | `templates/courses/manage/editor/_edit_table.html` |
| Gallery / Galeria | `galleryelement` | `_edit_gallery.html` |
| Callout / Ramka | `calloutelement` | `_edit_callout.html` |
| Tabs / Zakładki | `tabselement` | `_edit_tabs.html` |
| Columns / Kolumny | `twocolumnelement` | `_edit_twocolumn.html` |
| Matrix question / Pytanie macierzowe | `choicegridquestionelement` | `_edit_choicegridquestion.html` |
| Multi-select grid / Siatka wielokrotnego wyboru | `multigridquestionelement` | `_edit_multigridquestion.html` |

Slide break (`slidebreakelement`) has no editor form — it is a marker; verify its meaning against how it renders (the slideshow/deck split), not an editor.

Interactive additions (all `_edit_*.html` under `templates/courses/manage/editor/`):

| Type (EN / PL) | Model / form key | Editor template | Behavior to verify |
|---|---|---|---|
| Show more / Pokaż więcej | `revealgateelement` / `revealgate` | `_edit_revealgate.html` | "Show more" progressive reveal |
| Fill in & confirm / Uzupełnij i potwierdź | `fillgateelement` / `fillgate` | `_edit_fillgate.html` | fill-blank trigger + server check gates the reveal |
| Choose & confirm / Wybierz i zatwierdź | `switchgateelement` / `switchgate` | `_edit_switchgate.html` | "Choose ▾" cycler + server pk-check |
| Switch grid / Siatka przełączników | `switchgridelement` / `switchgrid` | `_edit_switchgrid.html` | multi-cycler self-check grid |
| Fill-in table / Tabela do uzupełnienia | `filltableelement` / `filltable` | `_edit_filltable.html` | fillable table cells, server-checked, no marks |
| Spoiler / Rozwijana treść | `spoilerelement` / `spoiler` | `_edit_spoiler.html` | `<details>` show/hide, zero JS |
| Step-by-step / Krok po kroku | `stepperelement` / `stepper` | `_edit_stepper.html` | inline "Show next" reveal walk |
| Checklist / Lista zadań | `markdoneelement` / `markdone` | `_edit_markdone.html` | self-tracking checklist, per-student persistent |
| Guess the number / Zgadnij liczbę | `guessnumberelement` / `guessnumber` | `_edit_guessnumber.html` | locked widget, no commit button |

### Nesting/gating facts (source: `courses/builder.py:34-55` `NESTABLE_TYPE_KEYS`; `_add_menu.html`)

- Containers (Tabs, Columns) hold the 9 Content leaves (Text, Math, Image, Video, Iframe, HTML, Table, Gallery, Callout) **and all 9 Interactive types**. They cannot hold another container, any Question type, or Slide break.
- Interactive is lesson-only (hidden in quizzes, `_add_menu.html:27`). Inside a quiz, a container's add-menu offers Content leaves only.
- Questions, Structure, and the containers themselves are hidden when nested (`_add_menu.html:24,25,41`), enforced server-side by `NESTABLE_TYPE_KEYS`.

### Environment

- Worktree root: `C:\Users\krzys\Documents\Python\own\libli\.claude\worktrees\help-pages-refresh-slice-1b` (branch `feat/help-pages-refresh-slice-1b`, off master `19c399e`). Run all commands here.
- Python tooling is via `uv run` (bash `ruff`/`pytest`/`python`/`django-admin` are NOT on PATH): `uv run pytest`, `uv run ruff`, `uv run python manage.py makemessages`.
- Cross-link format: `[Title](slug)` — English slug, link text translated in the PL sibling (e.g. EN `[Interactive elements](interactive-elements)`, PL `[Elementy interaktywne](interactive-elements)`).

---

### Task 1: Register and write the `interactive-elements` topic (EN + PL) + catalog

Creates the new topic end-to-end so `tests/test_help.py` (parametrized over `TOPICS`) goes green, including the translation gate that fails until the new title is translated. Written first so the other topics' cross-links to its slug resolve.

**Files:**
- Modify: `core/help.py` — add one `Topic(...)` after the `quiz-editors` entry (currently `core/help.py:88-94`).
- Create: `docs/help/course-admin/interactive-elements.md`
- Create: `docs/help/course-admin/interactive-elements.pl.md`
- Modify: `locale/pl/LC_MESSAGES/django.po` — via `makemessages`, then author the one new `msgstr`.
- Verify against: `tests/test_help.py`.

**Interfaces:**
- Produces: the slug `interactive-elements` (Course-Admin topic) that Tasks 2 and 3 link to; the msgid `"Interactive elements"` → msgstr `"Elementy interaktywne"`.

- [ ] **Step 1: Register the topic.** In `core/help.py`, directly after the `quiz-editors` `Topic(...)` (ends at `core/help.py:94`), add:

```python
    Topic(
        "interactive-elements",
        COURSE_ADMIN,
        "grouping.change_group",
        _("Interactive elements"),
        "help/course-admin/interactive-elements.md",
    ),
```

- [ ] **Step 2: Run the topic tests — expect the translation gate to FAIL.**

Run: `uv run pytest tests/test_help.py -q`
Expected: FAIL. `test_topic_english_file_exists_and_renders[interactive-elements]` fails (file missing) and `test_help_ui_string_translated_to_polish[Interactive elements]` fails (no PL msgstr yet). This confirms the gate sees the new topic.

- [ ] **Step 3: Write `interactive-elements.md` (EN).** H1 MUST be exactly `# Interactive elements` (equals the registry title — the §3.5 invariant). Structure, mirroring the voice/format of `content-editors.md` and `quiz-editors.md`:
  - An intro paragraph: these are **lesson-only** self-check / reveal elements added from a lesson's **Add element** menu (the **Interactive** group, absent when editing a quiz); most are self-checks (the student checks their own work — the family convention is a locked widget with the commit button removed) that record **no marks**; they are **nestable** inside Tabs/Columns (cross-link to `content-editors` for containers/nesting).
  - One `## ` section per type, in palette order (Show more, Fill in & confirm, Choose & confirm, Switch grid, Fill-in table, Spoiler, Step-by-step, Checklist, Guess the number). For each: name it by its EN label from the ground-truth table, and describe its behavior **verified against the editor template + model in the source map** (read each `_edit_*.html` before writing its paragraph). Match the depth of an existing entry — e.g. the `content-editors.md` "Video" paragraph is the target length/shape.
  - A `## See also` section linking `[Content editors](content-editors)` (containers and nesting) and `[Quiz editors](quiz-editors)` (question elements as the other lesson practice).

  Exemplar (voice/format target for ONE type — the implementer verifies and writes all nine to this standard):

```markdown
**Spoiler** — a collapsible block that hides its content behind a click, using a
native `<details>` toggle with no JavaScript. Use it to tuck away a hint, a worked
answer, or an aside a student can open when they choose.
```

- [ ] **Step 4: Write `interactive-elements.pl.md` (PL).** H1 MUST be exactly `# Elementy interaktywne` (equals the registry title's PL msgstr). Mirror the EN structure section-for-section. Each `## ` heading uses the type's **PL msgstr** from the ground-truth table (e.g. `## Rozwijana treść` for Spoiler). Cross-links use translated link text with the same slug: `[Edytory treści](content-editors)`, `[Edytory quizów](quiz-editors)`. The PL body must be genuine Polish prose, not an English copy (a test enforces PL ≠ EN).

- [ ] **Step 5: Extract the new msgid into the catalog.**

Run: `uv run python manage.py makemessages -l pl --no-obsolete`
Expected: the diff to `locale/pl/LC_MESSAGES/django.po` introduces `msgid "Interactive elements"` with an empty `msgstr ""` (plus benign line shifts). Verify no unrelated msgid was newly fuzzied:

Run: `git -C . diff locale/pl/LC_MESSAGES/django.po | grep -n "^+#, fuzzy\|^+msgid" | head`
Expected: only `+msgid "Interactive elements"` (and its neighbors from line shifts); if any `+#, fuzzy` appears on a pre-existing entry, revert that fuzzy flag (it is a makemessages artifact, not a change 1b intends).

- [ ] **Step 6: Author the one PL msgstr.** In `locale/pl/LC_MESSAGES/django.po`, set the new entry's translation:

```
msgid "Interactive elements"
msgstr "Elementy interaktywne"
```

- [ ] **Step 7: Compile and run the topic tests — expect PASS.**

Run: `uv run python manage.py compilemessages -l pl && uv run pytest tests/test_help.py -q`
Expected: PASS. In particular `test_help_ui_string_translated_to_polish[Interactive elements]`, `test_topic_english_file_exists_and_renders[interactive-elements]`, `test_topic_polish_file_renders_if_present[interactive-elements]`, and `test_polish_file_is_not_an_english_copy[interactive-elements]` all pass.

- [ ] **Step 8: Lint the Python change.**

Run: `uv run ruff check core/help.py && uv run ruff format --check core/help.py`
Expected: clean.

- [ ] **Step 9: Append a §3.6 ledger entry** to `docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md` noting the new topic was created (slug, title, msgstr) as slice-1b baseline.

- [ ] **Step 10: Commit.** Write the message to a file and commit with `-F` (UTF-8 safety), then verify.

```bash
printf '%s\n' \
  "docs(help): new Interactive elements topic (9 lesson-only self-check types)" \
  "" \
  "Register interactive-elements (Course-Admin, grouping.change_group); EN + PL" \
  "docs; author msgstr Elementy interaktywne via makemessages --no-obsolete." \
  "" \
  "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  > /tmp/1b_t1_msg.txt
git -C . add core/help.py docs/help/course-admin/interactive-elements.md docs/help/course-admin/interactive-elements.pl.md locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md
git -C . commit -F /tmp/1b_t1_msg.txt
git -C . log -1 --format=%B | head
```

---

### Task 2: `content-editors` — Content group (+5), Structure (+1), nesting/gating, cross-link

**Files:**
- Modify: `docs/help/course-admin/content-editors.md`
- Modify: `docs/help/course-admin/content-editors.pl.md`
- Read to verify: `_edit_table.html`, `_edit_gallery.html`, `_edit_callout.html`, `_edit_tabs.html`, `_edit_twocolumn.html`; `courses/builder.py:34-55`; `_add_menu.html`.

**Interfaces:**
- Consumes: the `interactive-elements` slug from Task 1.
- Produces: the nesting/gating section that `interactive-elements` cross-references.

- [ ] **Step 1: Absence gate — confirm the five names are not yet present.**

Run: `grep -Fc -e "**Table**" -e "**Gallery**" -e "**Callout**" -e "**Tabs**" -e "**Columns**" docs/help/course-admin/content-editors.md`
Expected: `0` for each (the five content types are undocumented). Also `grep -Fc "Slide break" docs/help/course-admin/content-editors.md` → `0`.

- [ ] **Step 2: Add the five Content types (EN).** In `content-editors.md`, under `## Content element types`, after the **HTML** paragraph, add one paragraph per type in palette order: **Table**, **Gallery**, **Callout**, **Tabs**, **Columns**. Verify each against its editor template (source map) before writing. Tabs and Columns are containers — describe them briefly here and defer the nesting rules to the new section in Step 4.

- [ ] **Step 3: Add the Structure section (EN).** Add a `## Structure` section (after the content types) documenting **Slide break** (`slidebreakelement`): a marker that splits a lesson into slides for the deck/slideshow view; verify against how it renders, not an editor form.

- [ ] **Step 4: Add the nesting/gating section (EN).** Add a `## Containers and nesting` section stating the facts from `NESTABLE_TYPE_KEYS`: Tabs and Columns can hold the content leaves (Text, Image, Video, Iframe, Math, HTML, Table, Gallery, Callout) and the Interactive self-checks, but not another container, a question, or a slide break; and that the Interactive types are lesson-only, so inside a quiz a container holds content blocks only. Cross-link `[Interactive elements](interactive-elements)` here for the nestable self-checks.

- [ ] **Step 5: Update the intro + See also cross-links (EN).** In the intro paragraph that currently says "See [Quiz editors](quiz-editors) for the Questions group.", add a parallel pointer for the Interactive group: "See [Interactive elements](interactive-elements) for the Interactive group." Add `[Interactive elements](interactive-elements)` to the `## See also` list.

- [ ] **Step 6: Mirror everything in `content-editors.pl.md` (PL).** Same five types using PL msgstrs as their bold names (**Tabela**, **Galeria**, **Ramka**, **Zakładki**, **Kolumny**), the Structure section (**Podział slajdów**), the containers/nesting section, and the cross-links with translated link text (`[Elementy interaktywne](interactive-elements)`). Genuine Polish prose. **Do not** write "Ramka" for Iframe anywhere — Ramka is Callout.

- [ ] **Step 7: Presence gate — EN and PL names present, quoted correctly.**

Run:
```bash
grep -Fc -e "Table" -e "Gallery" -e "Callout" -e "Tabs" -e "Columns" -e "Slide break" docs/help/course-admin/content-editors.md
grep -Fc -e "Tabela" -e "Galeria" -e "Ramka" -e "Zakładki" -e "Kolumny" -e "Podział slajdów" docs/help/course-admin/content-editors.pl.md
grep -Fc "interactive-elements" docs/help/course-admin/content-editors.md docs/help/course-admin/content-editors.pl.md
```
Expected: every count ≥ 1; the `interactive-elements` slug appears in both files (intro + nesting + See also).

- [ ] **Step 8: Topic tests still green.**

Run: `uv run pytest tests/test_help.py -q`
Expected: PASS (both content-editors files still render; PL ≠ EN).

- [ ] **Step 9: Append a §3.6 ledger entry** recording the content-editors additions (and any behavior found while verifying templates that wasn't in the plan).

- [ ] **Step 10: Commit** (`git commit -F`, UTF-8; message: `docs(help): content-editors — Table/Gallery/Callout/Tabs/Columns, Slide break, nesting`).

---

### Task 3: `quiz-editors` — Questions (+2), per-option MCQ feedback, cross-link

**Files:**
- Modify: `docs/help/course-admin/quiz-editors.md`
- Modify: `docs/help/course-admin/quiz-editors.pl.md`
- Read to verify: `_edit_choicegridquestion.html`, `_edit_multigridquestion.html`, `_edit_choicequestion.html:15,41-42`; `courses/models.py` `class Choice` (1489, `feedback` 1496); the quiz results/review templates and `tests/test_choice_inline_feedback.py` (behavior oracle for the lesson-vs-quiz reveal).

**Interfaces:**
- Consumes: the `interactive-elements` slug from Task 1.

- [ ] **Step 1: Absence gate.**

Run: `grep -Fc -e "Matrix question" -e "Multi-select grid" -e "per-option" docs/help/course-admin/quiz-editors.md`
Expected: `0` for each.

- [ ] **Step 2: Add the two question types (EN).** In `quiz-editors.md`, in palette order, insert between the **Match pairs** (`## Match pairs`) and **Drag to image** (`## Drag to image`) sections: `## Matrix question` (`choicegridquestionelement` — single-choice-per-row grid, partial credit per row, True/False preset) and `## Multi-select grid` (`multigridquestionelement` — set-per-row choice grid, all-or-nothing per row). Verify each against its editor template before writing.

- [ ] **Step 3: Add per-option MCQ feedback (EN).** In the existing `## Single / Multiple choice` section (do not rewrite the exact-match marking prose), add that each **choice** can carry optional per-option feedback, shown when a student gets an option wrong — a wrong pick, or a correct answer they missed (the product's own wording, `_edit_choicequestion.html:15`). Then the lesson-vs-quiz contrast, **verified against source**: in a **lesson** without per-option feedback a wrong answer shows only the verdict and does not reveal the correct choice (PR #132 dropped the lesson reveal list); in a **quiz** the correct answers are still revealed at results/review. Confirm the quiz-path wording against the results/review templates and `tests/test_choice_inline_feedback.py` before writing it.

- [ ] **Step 4: Cross-link (EN).** In the `## Where questions live` section (or `## See also`), add `[Interactive elements](interactive-elements)` — the lesson-only self-check cousins of questions-as-practice.

- [ ] **Step 5: Mirror in `quiz-editors.pl.md` (PL).** Insert `## Pytanie macierzowe` and `## Siatka wielokrotnego wyboru` between `## Dopasuj pary` (line ~67) and `## Przeciągnij na obraz` (line ~75). Add the per-option-feedback prose and the lesson-vs-quiz contrast in Polish, quoting the PL msgstr of the `_edit_choicequestion.html:15` hint. Add `[Elementy interaktywne](interactive-elements)` to `## Gdzie znajdują się pytania` / `## Zobacz też`.

- [ ] **Step 6: Presence gate.**

Run:
```bash
grep -Fc -e "Matrix question" -e "Multi-select grid" docs/help/course-admin/quiz-editors.md
grep -Fc -e "Pytanie macierzowe" -e "Siatka wielokrotnego wyboru" docs/help/course-admin/quiz-editors.pl.md
grep -Fc "interactive-elements" docs/help/course-admin/quiz-editors.md docs/help/course-admin/quiz-editors.pl.md
```
Expected: every count ≥ 1.

- [ ] **Step 7: Topic tests still green.**

Run: `uv run pytest tests/test_help.py -q`
Expected: PASS.

- [ ] **Step 8: Append a §3.6 ledger entry** for the quiz-editors additions (and any verified-against-source finding beyond the plan).

- [ ] **Step 9: Commit** (`git commit -F`; message: `docs(help): quiz-editors — Matrix question, Multi-select grid, per-option MCQ feedback`).

---

### Task 4: Final DoD sweep — full suite, catalog invariant, cross-link resolution, PR

**Files:**
- Read/verify only (no new content unless a gate fails): all six topic files, `core/help.py`, `locale/pl/LC_MESSAGES/django.po`, `docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md`.

- [ ] **Step 1: No obsolete/fuzzy catalog entries.**

Run: `uv run python manage.py makemessages -l pl --no-obsolete && git -C . diff --stat locale/pl/LC_MESSAGES/django.po`
Expected: no `#~` obsolete markers; the only intended content change is the `Interactive elements` entry from Task 1. If `makemessages` re-fuzzed a pre-existing entry, revert that flag. Then `grep -c "^#~" locale/pl/LC_MESSAGES/django.po` → `0`.

- [ ] **Step 2: i18n obsolete-invariant tests.**

Run: `uv run pytest tests/test_i18n_auth.py tests/test_i18n_notes.py tests/test_tags_i18n.py -q`
Expected: PASS. (Note: `tests/test_i18n_catalog.py` is a name-collision — it tests the browse-catalog page, not the `#~` invariant.)

- [ ] **Step 3: Every cross-link slug resolves to a registered topic.** All four topic slugs used in links (`content-editors`, `quiz-editors`, `interactive-elements`, `media-manager`, `builder`) must be registered in `core/help.py`.

Run: `grep -rhoE "\]\(([a-z-]+)\)" docs/help/course-admin/{content-editors,quiz-editors,interactive-elements}.md | sort -u`
Then confirm each captured slug appears as a `Topic("<slug>"` in `core/help.py`. Expected: no dangling slug.

- [ ] **Step 4: Full non-e2e suite + lint.**

Run: `uv run pytest -m "not e2e" -q && uv run ruff check . && uv run ruff format --check .`
Expected: all green. (Do NOT run `-m e2e` in the background — per prior lessons it spawns runaway browsers; if an e2e check is wanted, run a single focused test in the foreground.)

- [ ] **Step 5: Render each new/changed topic as a Course Admin (smoke).** Confirm the three topics render and the PL variants serve under a PL session.

Run: `uv run pytest tests/test_help.py -q`
Expected: PASS across all `TOPICS` params including `interactive-elements`.

- [ ] **Step 6: Confirm the §3.6 ledger is complete** — one entry per topic task plus the new-topic entry, each recording what was added and any beyond-plan finding.

- [ ] **Step 7: Push and open the PR.**

```bash
git -C . push -u origin feat/help-pages-refresh-slice-1b
```
Then open a PR to `master` summarizing: 17 element types + per-option MCQ feedback + nesting/gating documented across three topics (EN+PL); one new topic and one authored PL string. Reference the spec and the audit findings §2. PR body ends with the Claude Code footer.
