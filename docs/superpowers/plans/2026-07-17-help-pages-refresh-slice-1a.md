# Help pages refresh — slice 1a implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all 22 in-app help topics true — correct every drifted claim across 44 EN/PL files, rename one registry title, and fill one missing Polish translation.

**Architecture:** Docs-only. Each task owns one topic (both language files), opens with a **negative-tested grep gate** that must go red before editing and green after, and ends with a commit. Two tasks (`roster`, `groups-collections`) are prose rewrites rather than corrections. No view, template, model, or permission is touched.

**Tech Stack:** Markdown under `docs/help/`, rendered by `core/help.py` (`markdown` lib, `fenced_code` + `tables`). Django i18n (`makemessages`/`compilemessages`, `locale/{en,pl}/LC_MESSAGES/django.{po,mo}`). `uv run` for all tooling.

**Spec:** [2026-07-17-help-pages-refresh-slice-1a-design.md](../specs/2026-07-17-help-pages-refresh-slice-1a-design.md)
**Evidence:** [2026-07-17-help-pages-audit-findings.md](../specs/2026-07-17-help-pages-audit-findings.md)

---

## Global Constraints

Every task's requirements implicitly include this section.

**G1 — No line number anywhere is authoritative** (spec §5.1). Not in the spec, not in the findings, **not in this plan**. Measured drift: catalog citations up to **43 lines** off; doc-side and source-side citations drift too. **Locate every target by searching its file for the quoted string.** A citation that resolves to *plausible but different* text is the dangerous case — verify the quoted text matches before editing.

**G2 — Every PL label is a `msgstr` lookup, never a translation** (spec §5). Find the msgid the EN doc quotes; use its msgstr verbatim. Where a finding cites a *template* line, read the `{% trans %}` msgid there, then look up its msgstr. **The catalog is the final authority.** Exception: help-doc *section headings* are prose and have no catalog entry.

**G3 — Every gate must be negative-tested** (spec §6). Run it on the **pre-edit** tree and confirm it goes **red**. A gate never seen to fail is decoration (`[[falsify-tests-not-run-them]]`). Four ways gates here have already been green-but-blind, all verified:

| Hazard | Symptom | Rule |
|---|---|---|
| **Locale** | `grep -P` exits **2**, prints nothing, reads as "clean" | Always `LC_ALL=C.UTF-8` with `-P` + non-ASCII |
| **CRLF** | `grep -c '^msgid "Branding"$'` → **0** on a catalog containing it; `\n` in `-Pz` never matches | **Never `$`-anchor.** Use `\s+` or `\r?\n` |
| **Wrapped bold** | `**Dodaj\nużytkownika**` invisible to single-line grep (exit 1 = "clean") | Use `grep -rlzP '…\s+…'` |
| **Regex dialect** | `rg '+ Add element'` → parse error, prints nothing | Use GNU `grep` (BRE, `+` literal) or `rg -F` |

**G4 — Sense-scoped, never token sweeps** (spec §2.3). No findings §3.1.2 row is a `sed` candidate. Each carve-out below is verified; violating one corrupts correct text.

**G5 — The audit is a floor, not a ceiling** (spec §5). While editing a topic, re-verify its claims against the templates. Anything new is in scope. **Record additions in findings §3** (Task 26) so the pre-release re-audit has a true baseline.

**G6 — Out of scope, do not "fix" opportunistically:**
- The **17 undocumented element types**, per-option MCQ feedback, nesting/gating rules → slice 1b.
- The **four §3.5 H1 mismatches** — `branding-settings.md`, `sso.pl.md`, `integrations.md`, `integrations.pl.md` (spec §2.4, DoD #12). Each Verification below greps them **positively** to prove they survived.
- Any view/template/model/permission change.

**G7 — EN/PL asymmetry is per-line, not per-topic** (spec §5). Three carve-outs where PL is already correct — do not "fix" them back:
- `cohorts.pl.md` — `**Ustaw jako domyślną**` (EN says "Promote")
- `notifications.pl.md` — omits the bogus `flush`
- `drill-down.md:34` — EN `**3 selected**` is correct; only PL is wrong

**Every other finding in those topics still lands in the PL sibling.**

**G8 — Commit per task.** Message: `docs(help): <topic> — <what>`.

---

## File Structure

| File | Responsibility |
|---|---|
| `docs/help/{teacher,course-admin,platform-admin}/*.md` + `*.pl.md` | 44 content files; one task per topic pair |
| `core/help.py` | Registry — **one line changes** (Task 1) |
| `locale/{en,pl}/LC_MESSAGES/django.po` + `.mo` | Catalogs — Tasks 1 & 2 only |
| `docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md` | Evidence base — Task 26 appends |

---

### Task 1: The registry rename + both H1s + catalog regen

**Files:**
- Modify: `core/help.py` (the `_("Notes & tags")` line — find by search, G1)
- Modify: `docs/help/teacher/notes-tags.md` (H1)
- Modify: `docs/help/teacher/notes-tags.pl.md` (H1)
- Regenerate: `locale/{en,pl}/LC_MESSAGES/django.{po,mo}`

**Interfaces:**
- Produces: registry title `_("Tags & notes")`; PL H1 `# Tagi i notatki`. Task 3 (`notes-tags` body) depends on both.

- [ ] **Step 1: Negative-test the gates — all must be RED**

```bash
export LC_ALL=C.UTF-8
grep -rn --exclude-dir=__pycache__ -I 'Notes & tags' core/ locale/
grep -c '^#~' locale/en/LC_MESSAGES/django.po  # MUST be 0
grep -c '^#~' locale/pl/LC_MESSAGES/django.po  # MUST be 0
head -1 docs/help/teacher/notes-tags.md        # MUST be "# Notes & tags"
head -1 docs/help/teacher/notes-tags.pl.md     # MUST be "# Notatki i etykiety"
```
Expected: the first grep finds **exactly three** text hits — `core/help.py`, `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`. Both `#~` counts are 0; both H1s as shown. **If `#~` is not 0 before you start, stop — the baseline is wrong.**

⚠ **`--exclude-dir=__pycache__ -I` is mandatory, not tidiness.** `grep -r` does not respect `.gitignore`. Without them the gate also returns `Binary file core/__pycache__/help.cpython-313.pyc matches` and `Binary file locale/pl/LC_MESSAGES/django.mo matches`. The `.mo` clears after `compilemessages`, but **the `.pyc` only clears when Python re-imports `help.py`** — which happens in Step 6's pytest, *after* Step 5's gate. So the unfiltered gate reads **RED on a correct edit**, in a plan that trains you to read an unexpected gate result as "you have the wrong string."

- [ ] **Step 2: Rename the registry title**

In `core/help.py`, find the `Topic(` whose slug is `"notes-tags"` and change **only** its title:

```python
    Topic(
        "notes-tags",
        TEACHER,
        "grouping.view_collection",
        _("Tags & notes"),
        "help/teacher/notes-tags.md",
    ),
```

**Keep the slug `notes-tags`** (spec §4.2) — it is a URL segment. `msgid "Tags & notes"` already exists (→ `"Tagi i notatki"`), joining five existing references. **No new translation is authored.**

- [ ] **Step 3: Fix both H1s**

`docs/help/teacher/notes-tags.md` line 1: `# Notes & tags` → `# Tags & notes`

`docs/help/teacher/notes-tags.pl.md` line 1: `# Notatki i etykiety` → `# Tagi i notatki`

**The PL H1 must be `Tagi i notatki`** — the reused msgstr verbatim — **NOT** `Notatki i tagi`, which a mechanical `etykiety`→`tagi` swap would produce (spec §4.1).

- [ ] **Step 4: Regenerate the catalogs**

```bash
uv run python manage.py makemessages -l en -l pl --no-obsolete --ignore=.venv
uv run python manage.py compilemessages
```

**`--no-obsolete` is mandatory.** Without it, `makemessages` keeps the removed entry as `#~ msgid "Notes & tags"` / `#~ msgstr "Notatki i etykiety"` — leaving **`etykiety` alive in the catalog this slice exists to purge**, while passing every other gate. Repo convention: obsoletes have been stripped after the fact twice (`f28d663`, `9bbe82c`).

Inspect the diff for **fuzzy** flags (`[[uv-run-tooling]]`) — do not accept them blind.

- [ ] **Step 5: Verify the gates are GREEN**

```bash
export LC_ALL=C.UTF-8
grep -rn --exclude-dir=__pycache__ -I 'Notes & tags' core/ locale/   # → zero (incl. #~)
grep -c '^#~' locale/en/LC_MESSAGES/django.po  # → 0
grep -c '^#~' locale/pl/LC_MESSAGES/django.po  # → 0
grep -rn 'Tags & notes' core/help.py           # → 1
head -1 docs/help/teacher/notes-tags.md        # → "# Tags & notes"
head -1 docs/help/teacher/notes-tags.pl.md     # → "# Tagi i notatki"
git status --porcelain locale/                 # → all four artifacts modified
```

- [ ] **Step 6: Run the i18n + help tests**

```bash
uv run pytest tests/test_help.py tests/test_i18n_ws4.py -v
```
Expected: PASS. The translation-assertion test derives titles from `TOPICS`; `"Tagi i notatki" != "Tags & notes"` passes the PL≠EN guard.

**Note:** `tests/test_i18n_catalog.py` is a **name collision** — it tests the course *browse catalog page*, not the message catalog. The real catalog tests are `test_i18n_ws4.py`, `test_i18n_auth.py`, `test_i18n_notes.py`, `test_tags_i18n.py`.

- [ ] **Step 7: Commit**

```bash
git add core/help.py docs/help/teacher/notes-tags.md docs/help/teacher/notes-tags.pl.md locale/
git commit -m "docs(help): rename the Notes & tags topic to Tags & notes

Matches the product's own nav (base.html) and kills the last 'etykiety'
title. Reuses the existing msgid -> 'Tagi i notatki', so no translation is
authored and msgid 'Notes & tags' drops out. Slug stays notes-tags (URL
stability). Both markdown H1s move too -- the registry title is page chrome
and the H1 is a separate string; renaming only the registry would leave the
breadcrumb and the H1 disagreeing, with 'etykiety' still on the page.

makemessages --no-obsolete: without it the removed entry survives as a #~
block, leaving 'Notatki i etykiety' in the catalog."
```

---

### Task 2: Fill the `Multi-select grid` msgstr

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`
- Regenerate: `locale/pl/LC_MESSAGES/django.mo`

**Interfaces:**
- Consumes: Task 1's catalog regen (run after, so `makemessages` cannot clobber this).
- Produces: a non-empty msgstr for `Multi-select grid`. **Unblocks slice 1b**, whose PL element doc has no term to quote.

**⚠ REQUIRES USER APPROVAL BEFORE COMMITTING.** This is the **one string in the slice that must be authored rather than looked up** — G2's rule is by definition inapplicable, because the msgstr is what's missing. No test can validate an authored translation.

- [ ] **Step 1: Negative-test — the gate must be RED**

```bash
uv run python - <<'EOF'
import pathlib
# Block-level scan. A naive regex like msgid "X"\nmsgstr ""\n\n is FAIL-OPEN:
# it cannot see the 64 multi-line `msgid ""` blocks or the 27 msgid_plural
# entries in this catalog, so an empty msgstr in either shape is invisible.
text = pathlib.Path("locale/pl/LC_MESSAGES/django.po").read_text(encoding="utf-8")
blocks = text.split("\n\n")
untranslated = []
for b in blocks:
    lines = [l for l in b.splitlines() if not l.startswith("#")]
    if not any(l.startswith("msgid") for l in lines):
        continue
    if any(l.startswith('msgid ""') for l in lines[:1]):
        continue  # catalog header
    for i, l in enumerate(lines):
        if l.startswith("msgstr"):
            # empty iff `msgstr ""` with no continuation string line after it
            cont = lines[i+1] if i+1 < len(lines) else ""
            if l.rstrip().endswith('""') and not cont.startswith('"'):
                mid = next((x for x in lines if x.startswith("msgid ")), "?")
                untranslated.append(mid)
print("untranslated blocks:", len(untranslated))
for u in untranslated:
    print("  ", u)
EOF
```
Expected: `untranslated blocks: 1` and the one entry is `msgid "Multi-select grid"`. It is the **only** untranslated msgid in the catalog.

- [ ] **Step 2: Fill it**

Find `msgid "Multi-select grid"` (by search, G1) and set:

```
msgstr "Siatka wielokrotnego wyboru"
```

**Derivation** (follow the palette's own conventions, do not invent a style):
- `Switch grid` → `"Siatka przełączników"` establishes **Siatka** + genitive for a grid-of-X
- `Multiple choice` → `"Wielokrotny wybór"` gives the concept; its genitive is *wielokrotnego wyboru*
- `Matrix question` → `"Pytanie macierzowe"` confirms the register

The msgid is emitted from **three** call sites — `courses/templatetags/courses_manage_extras.py`, `courses/views_manage.py`, and **`templates/courses/manage/editor/_add_menu.html`** (the palette card this fix exists for) — so one msgstr fixes all three.

- [ ] **Step 3: Compile**

```bash
uv run python manage.py compilemessages
```
(No `makemessages` — the msgid already exists.)

- [ ] **Step 4: Verify GREEN**

Re-run **the same block-level scan from Step 1** (not a regex — see the fail-open note there):

```bash
# → "untranslated blocks: 0"
uv run pytest tests/test_i18n_ws4.py -v
git diff --stat locale/pl/LC_MESSAGES/django.po   # → 1 file changed, 1 insertion(+), 1 deletion(-)
```

⚠ **The `.po` is CRLF** (G3). If your editor rewrites it with LF, a one-line change becomes a whole-file diff and **buries the very string DoD #5 says must be visible in the PR**. `git diff --stat` must show a **one-line** change; if it doesn't, restore CRLF and redo the edit.

- [ ] **Step 5: Commit (string already approved)**

**The user approved `"Siatka wielokrotnego wyboru"` on 2026-07-17.** DoD #5 is satisfied. Still flag it explicitly in the PR body — an authored translation must not be buried in a regenerated catalog diff.

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(pl): translate the Multi-select grid palette label

The only untranslated msgid in the PL catalog (1 of 1,247), so that palette
card rendered in English for Polish users. Derived from the palette's own
conventions: 'Switch grid' -> 'Siatka przelacznikow' gives Siatka+genitive;
'Multiple choice' -> 'Wielokrotny wybor' gives the concept. User-approved.

Unblocks slice 1b, whose PL element doc had no rendered term to quote."
```

---

## Topic tasks (3–24)

**Every topic task follows this shape.** Steps are identical in form; the content differs.

1. **Negative-test the gate** — run the greps, confirm each finds its target. A gate that is already green means you have the wrong string (G1: locate by search).
2. **Apply the edits** — EN and PL together (spec §5: both files in one pass keeps parity verifiable).
3. **Re-run the gate** — confirm zero, and confirm the **positive** greps (carve-outs, out-of-scope H1s) still return their expected counts.
4. **Commit.**

**Sections correspond; line numbers do not.** `subjects.md`'s **Manage** is on a different line than `subjects.pl.md`'s. Never apply a "(+PL)" citation by line offset.

---

### Task 3: `notes-tags` — the topic that triggered this

**Files:** `docs/help/teacher/notes-tags.md`, `docs/help/teacher/notes-tags.pl.md`
**Depends on:** Task 1 (the H1s and registry rename).
**Findings:** **B00**, L49, §3.1.2 `etykiety`→`tagi` (**this file is the row's only in-scope target**), the 5th `Sprawdzanie testów` cross-link.

- [ ] **Step 1: Negative-test — all RED**

```bash
export LC_ALL=C.UTF-8
grep -rn 'The \*\*My tags\*\* page' docs/help/teacher/notes-tags.md
grep -o 'tykiet' docs/help/teacher/notes-tags.pl.md | wc -l   # 15 OCCURRENCES (on 13 lines)
grep -rn 'lekcja lub test\|lekcję lub test' docs/help/teacher/notes-tags.pl.md
grep -rn 'Sprawdzanie testów' docs/help/teacher/notes-tags.pl.md
```

- [ ] **Step 2: Fix B00 (both languages)**

**B00 is a three-way error in one sentence** — wrong term, wrong link, wrong page name:

> `notes-tags.md`: "The **My tags** page — reachable from the nav link of the same name — lists all the tags you have created."

Ground truth: the nav link is **Tags & notes** → `notes:overview` (`base.html`); the page's `<h1>` is **Tags & notes** (`my_tags.html`); "My tags" survives only as its `head_title`. **The real path is nav Tags & notes → the Manage tags tab** (`_tags_notes_tabs.html`; the sibling tab is **By course**).

Rewrite both languages to describe that path. PL msgstrs: **Tagi i notatki**, **Zarządzaj tagami**, **Według kursu**.

**Recommendation:** do not mention "My tags"/"Moje tagi" at all — it is invisible browser chrome, and mentioning it is what created B00.

- [ ] **Step 3: `etykiety` → `tagi` throughout the PL file (13 hits)**

**All 15 occurrences in this file mean the tags feature** — verified: `grep -rl 'tykiet' docs/help/teacher/` returns only this file. *(15 occurrences on 13 lines — count occurrences, not lines; two lines carry two each.)* But **this is still not a token sweep** (G4):
- The forms inflect: `etykiety`→`tagi`, `etykiet`→`tagów`, `etykietę`→`tag`, `etykietami`→`tagami`
- **Gender flips** (`etykieta` fem. → `tag` masc.), so agreeing words change: `usunięcia **jej**` → `**go**`; `swoją pierwszą` → `swój pierwszy`

Key msgstr lookups: `Tags` → **Tagi**; `Tags (%(n)s)` → **Tagi (%(n)s)**; `Add a tag…` → **Dodaj tag…**; `Add` → **Dodaj**; `Remove tag %(tag)s` → **Usuń tag %(tag)s**; `Manage tags` → **Zarządzaj tagami**.

- [ ] **Step 4: L49 — PL "test" → "quiz"**

`Każda lekcja lub **test**` → `Każda lekcja lub **quiz**`, and `otworzył lekcję lub **test**` → `lekcję lub **quiz**`. The latter paraphrases the very msgstr: `"Nie masz jeszcze żadnych tagów. Otwórz lekcję lub quiz i dodaj tag."`

- [ ] **Step 5: The cross-link**

`- [Sprawdzanie testów](quiz-review)` → `- [Sprawdzanie quizów](quiz-review)` (`msgid "Quiz review"`).

- [ ] **Step 6: Verify GREEN**

```bash
export LC_ALL=C.UTF-8
grep -rn 'tykiet' docs/help/teacher/notes-tags.pl.md          # → ZERO
grep -rn 'My tags' docs/help/teacher/notes-tags.md            # → zero
grep -rn 'Sprawdzanie testów' docs/help/teacher/notes-tags.pl.md  # → zero
head -1 docs/help/teacher/notes-tags.pl.md                    # → "# Tagi i notatki"
```
Eyeball: PL gender agreement is consistent after the fem→masc flip.

- [ ] **Step 7: Commit** — `docs(help): notes-tags — fix the phantom "My tags" nav link and etykiety→tagi`

---

### Task 4: `analytics`

**Files:** `docs/help/teacher/analytics.md`, `.pl.md`
**Findings:** §3.2 colour-bands, L32, §3.4 (**CONFIRMED** — apply spec §3 row 3's standard), §3.1.2 `Eksportuj`→`Eksport`.

- [ ] **Step 1: Negative-test** — `grep` for `with the **Analytics**`, `pass threshold`, `cherry-pick`, `not yet attempted` (EN); `przyciskiem **Analityka**`, `progu zaliczenia`, `wybór ręczny`, `**Eksportuj**` (PL). All must hit.

- [ ] **Step 2: The colour bands are a REWRITE, not a swap**

The doc's 3-colour model is **fabricated**. `courses/color_bands.py` has **five** bands, mins `[0, 40, 60, 75, 90]`, rendered `{{ label }} ({{ lo }}–{{ hi }}%)`:

| Band | Range | PL msgstr |
|---|---|---|
| None | 0–39 | **Brak** |
| Weak | 40–59 | **Słabo** |
| OK | 60–74 | **OK** |
| Good | 75–89 | **Dobrze** |
| Excellent | 90–100 | **Świetnie** |

**Grey (`#e5e5e7`) is the 0–39 `none` band — it is NOT "not attempted".** Not-attempted renders an **em dash**; the caption reads "— = not attempted yet, or awaiting review". **Nothing keys off "completed" or a "pass threshold"** — both are inventions and must not survive in any form.

The existing claim that bands are "computed per course" is **true** (`course.color_bands` is editable) — keep it.

- [ ] **Step 3: L32 — "cherry-pick … students or units"**

"cherry-pick" appears in **no template**. The control is: tick student rows, press **Apply selection** (PL **Zastosuj wybór**). **"or units" must die, not soften** — the only checkbox is `name="student"`; there is no unit subset.

- [ ] **Step 4: §3.4 — the Analytics entry point (CONFIRMED false)**

No course-facing template renders an Analytics link. Real teacher entry points: the dashboard **Teaching** panel (`core/home.html`), and the grouping pages (`my_groups.html`, `group_detail.html`, `collection_detail.html`). The builder's `_course_panel.html` link is Studio-only.

Apply spec §3 row 3's standard: **name the real entry points, invent nothing.**

- [ ] **Step 5: PL `**Eksportuj**` → `**Eksport**`** (`msgid "Export"`).

- [ ] **Step 6: Verify GREEN + eyeball** the band list names five bands with numeric ranges, no "pass threshold", and the em-dash/grey distinction is explicit.

- [ ] **Step 7: Commit** — `docs(help): analytics — replace the fabricated 3-colour band model with the real five`

---

### Task 5: `drill-down`

**Files:** `docs/help/teacher/drill-down.md`, `.pl.md`
**Findings:** L33, L34, L35, L36, §3.1.2 `Zastosuj`→`Zastosuj wybór`, cross-link, §3.4 + cherry-pick spillover (G5).

- [ ] **Step 1: Negative-test** — `press **Apply**`, `## Cherry-picking a subset of students`, `The **back** link`, `colour-configuration link`, `**Analytics** button` (EN); `**Zastosuj**`, `**3 zaznaczonych**`, `Odnośnik **wstecz**`, `Sprawdzanie testów` (PL).

- [ ] **Step 2: Apply**

| Find | Replace | msgid |
|---|---|---|
| `press **Apply**` | `press **Apply selection**` | `Apply selection` |
| PL `naciśnij **Zastosuj**` | `**Zastosuj wybór**` | `Apply selection` |
| PL `**3 zaznaczonych**` | `**Zaznaczono: 3**` | `%(n)s selected` → `Zaznaczono: %(n)s` |
| `The **back** link` | `The **← Analytics** link` | `Analytics` |
| PL `Odnośnik **wstecz**` | `Odnośnik **← Analityka**` | `Analytics` |
| `## Cherry-picking a subset of students` | `## Selecting a subset of students` | (in no template) |
| PL cross-link `Sprawdzanie testów` | `Sprawdzanie quizów` | `Quiz review` |

- [ ] **Step 2a: §3.4 spillover — APPLY it here too, don't just gate it**

The false **Analytics button** claim lives in **six** locations, not the one §3.4 cites: `analytics.md`, `analytics.pl.md`, `drill-down.md`, `drill-down.pl.md`, `gradebook-export.md`, `gradebook-export.pl.md`. **Task 4 fixes only its own two.** Apply the same rewrite here (Task 4 Step 4's standard): name the real entry points — the dashboard **Teaching** panel and the grouping pages — and invent no course-facing button.

**CARVE-OUT (M2):** the PL heading `## Wybór podzbioru uczniów` is **already correct** — it carries no invented term. Only the EN H2 says "Cherry-picking". Do not "fix" the PL.

- [ ] **Step 3: L36 — drop the colour-config link from the teacher-visible list**

It is gated `can_edit_bands` = `can_manage_course` — **invisible to teachers**. It is a *list member* inside a sentence about state round-tripping; the sentence's point stays true. **Drop the item and re-join the list** ("…across the Progress ↔ Results toggle and the Export link"). **Do not delete the sentence.**

- [ ] **Step 4: CARVE-OUT (G7)** — `drill-down.md:34`'s `**3 selected**` is **correct EN** (`msgid "%(n)s selected"` renders that in English). **Do not touch it.** L34 is PL-only.

Also already correct — leave: `**✕ Collapse**`/`**✕ Zwiń**`, `**Show all**`/`**Pokaż wszystkich**`, `**Students**`/`**Uczniowie**`.

- [ ] **Step 5: Verify GREEN.** `grep -rn '3 selected' docs/help/teacher/drill-down.md` **must still return 1** — zero means the carve-out was swept.

- [ ] **Step 6: Commit** — `docs(help): drill-down — Apply selection, ← Analytics, drop the admin-only colour link`

---

### Task 6: `gradebook-export`

**Files:** `docs/help/teacher/gradebook-export.md`, `.pl.md`
**Findings:** L37, L38, §3.1.2 `test`→`quiz`, cross-link, §3.4 + cherry-pick spillover.

- [ ] **Step 1: Negative-test** — `**This matrix view** —`, `cherry-picked student subset`, `**Analytics** button` (EN); `Dziennik testów (punkty surowe)`, `kształtu testowego`, `Sprawdzanie testów` (PL).

- [ ] **Step 2: Apply**

| Find | Replace | msgid |
|---|---|---|
| `**This matrix view**` | `**This matrix view (percentages)**` | `This matrix view (percentages)` |
| PL `**Ten widok macierzy**` | `**Ten widok macierzy (procenty)**` | same |
| PL `**Dziennik testów (punkty surowe)**` | `**Dziennik quizów (surowe wyniki)**` | `Quiz gradebook (raw marks)` |
| PL `kształtu testowego` | `kształtu **quizowego**` | §3.1.2 unit-type sense |
| `cherry-picked student subset` | `selected student subset` | (in no template) |
| PL `po jednej kolumnie **na test** z surowymi` | `**na quiz**` | §3.1.2 unit-type sense — a **third** `test` hit no other row targets |

- [ ] **Step 2a: §3.4 spillover — APPLY it here too, don't just gate it**

Same as Task 5 Step 2a: the false **Analytics button** claim is in this topic's **both** files. Apply Task 4 Step 4's standard — name the real entry points, invent nothing.

- [ ] **Step 3: CARVE-OUTS** — EN `**Quiz gradebook (raw marks)**` is **already exact**; L38 is PL-only. PL `**Eksport**` is **already correct** here — the live `Eksportuj` hit is in `analytics.pl.md` (G4: one token, three destinations). The **Max** row claim is correct. **(M2)** PL "wybrany podzbiór uczniów" is **already correct** — the cherry-pick fix is EN-only here.

- [ ] **Step 4: Verify GREEN**

```bash
export LC_ALL=C.UTF-8
grep -n 'test' docs/help/teacher/gradebook-export.pl.md
```
Review every hit by hand against the carve-out: `Send test event` / "zdarzenie testowe" is **"test" in its ordinary sense** and stays. Only unit-type `test` becomes `quiz`. **This gate cannot be a bare `→ zero`** — the word legitimately survives.

- [ ] **Step 5: Commit** — `docs(help): gradebook-export — full radio labels, PL quiz terminology`

---

### Task 7: `quiz-review`

**Files:** `docs/help/teacher/quiz-review.md`, `.pl.md`
**Findings:** L45, L46, L47, L48, §3.2 per-row Force-submit, §3 row 3 (entry point).

- [ ] **Step 1: Negative-test** — `the **Quiz review** button`, `each with a count`, `**Feedback** box`, `Both ask you to confirm first.` (EN); `**Oczekujące na sprawdzenie**`, `**Wymuś wysłanie** (patrz niżej)`, `Oba proszą najpierw o potwierdzenie.` (PL). Plus `grep -rlzP 'Wymuś\s+wysłanie'`.

- [ ] **Step 2: Apply**

| Find | Replace | msgid |
|---|---|---|
| PL `**Oczekujące na sprawdzenie**` | `**Oczekuje na ocenę**` | `Awaiting review` |
| PL `**Wymuś wysłanie**` — **the two bolded standalone hits only** (see Step 3's table) | `**Wymuś przesłanie**` | `Force-submit` |
| `**Feedback** box` | `**Feedback (optional)** box` | `Feedback (optional)` |
| PL `**Informacja zwrotna**` | `**Informacja zwrotna (opcjonalnie)**` | same |
| `each with a count` | `the first two with a count` | *Reviewed* has no count span |

- [ ] **Step 3: ⚠ THE SHARPEST CARVE-OUT IN THE SLICE (G4)**

`Wymuś wysłanie` is **wrong** standalone but **RIGHT** inside `**Wymuś wysłanie wszystkich (N)**` — `msgid "Force-submit all (%(n)s)"` → msgstr `"Wymuś wysłanie wszystkich (%(n)s)"`. **The product itself is inconsistent.** A `sed s/Wymuś wysłanie/Wymuś przesłanie/` **corrupts a correct label**.

**There are FIVE occurrences, not two — each needs its own verdict.** Locate them by search (G1); the line numbers below are orientation only:

| Occurrence | Sense | Verdict |
|---|---|---|
| bolded standalone (the per-row control) | wrong string | → **Wymuś przesłanie** |
| bolded standalone (the "closes and freezes" sentence) | wrong string | → **Wymuś przesłanie** |
| **unbolded prose** naming the per-row control ("Wymuś wysłanie jednego ucznia…") | wrong string, **not a label** | → **Wymuś przesłanie** — the prose names the same control, so it takes the fix |
| **unbolded prose**, bulk sense | already correct | **leave** |
| bolded `**Wymuś wysłanie wszystkich (N)**` | correct label | **leave — CARVE-OUT** |

**The carve-out rule is per-sense, not per-boldness.** Two of the five are unbolded, so "quote each label as-is" alone does not decide them — the question is *which control the text names*.

- [ ] **Step 4: §3.2 — rewrite the confirm claim, don't delete it**

"Both ask you to confirm first" → **only the bulk action confirms**; the per-row Force-submit fires immediately. This is a **behavioural warning worth keeping** — a teacher expecting a confirm will close an attempt by accident.

- [ ] **Step 5: §3 row 3 — the entry point**

The **Quiz review** button lives only in the Studio-gated course builder. The queue view itself **admits teachers** (`@login_required` + `can_review_course`) — they lack only the link. Honest framing: "the button lives in the course builder and needs course-manage access." **Do not invent a teacher path; do not omit it.**

- [ ] **Step 6: Verify GREEN — the carve-out gate expects TWO, not one**

```bash
export LC_ALL=C.UTF-8
grep -c 'Wymuś wysłanie wszystkich' docs/help/teacher/quiz-review.pl.md   # → 2, unchanged
grep -c 'Wymuś wysłanie' docs/help/teacher/quiz-review.pl.md              # → 2 (both bulk)
```

The bulk phrase occurs **twice** on the pre-edit tree — once as the bolded label `**Wymuś wysłanie wszystkich (N)**` and once in the unbolded prose above it. **Both are correct and both survive**, so this gate reads **2 before and 2 after**. A **0** means the sweep corrupted the correct label; a **1** means it caught one of the two.

The second gate must fall from **5 → 2**: the three wrong-sense occurrences are gone, the two bulk ones remain.

- [ ] **Step 7: Commit** — `docs(help): quiz-review — only the bulk force-submit confirms; PL label fixes`

---

### Task 8: `groups-collections` — REFRAME

**Files:** `docs/help/teacher/groups-collections.md`, `.pl.md`
**Findings:** §1.1, §1.2/§3 row 2, L39, L40, L41, L50, §3.1.2 `rocznik`→`kohorta` (**7 hits**, not the 5 cited), cross-link, `test`→`quiz`, **+ G5: archive is a 403 too**.

- [ ] **Step 1: Negative-test** — including the **wrapped** span:
```bash
export LC_ALL=C.UTF-8
grep -rn 'Create a group with \*\*New\*\*' docs/help/teacher/groups-collections.md
grep -o 'ocznik' docs/help/teacher/groups-collections.pl.md | wc -l   # 8 OCCURRENCES (on 7 lines — one line has "rocznika. Rocznikami")
grep -rlzP 'sprawdzanie\s+testów' docs/help/teacher/groups-collections.pl.md   # WRAPS — single-line grep MISSES it
```

- [ ] **Step 2: The Groups paragraph — third-person reframe**

Teachers hold **`view_group` only** — no `add_group`, no `change_group`, and (G5, beyond the audit) **no `delete_group`, so archive is a 403 too**. Every "Create… Save with **Save**" tells a teacher to do something they cannot.

Rewrite as **third-person description with a lead sentence stating teachers have read-only access**, absorbing:
- **L39** — there is **one hub, two tabs**. The top-bar **Groups** link *is* **My groups**; the sibling tab is **Manage**. The current "top-bar Groups list (or My groups)" implies two destinations. **This is the paragraph's first sentence — it dissolves unless named.**
- **L40** — the button is **New group** (PL **Nowa grupa**). Must survive **inside** the third-person prose ("a Course Admin creates one with **New group**…"), not beside it.
- **The archive/toggle sentence** — present in **both** languages (PL just wraps longer). Archive is 403 for teachers, so it belongs *inside* the third-person frame. **But do not sweep it together with the view toggle** — **Show archived**/**Show active** is a plain `?archived=` link and is **not** gated; teachers can use it.
- **State what teachers CAN do, positively:** `view_group`, plus full collection rights (`add/change/delete_collection`). The reframe must not read as "teachers can do nothing here."

- [ ] **Step 3: The Collections paragraph — a SEPARATE edit (§3 row 1)**

Teachers *hold* `add_collection` and `collection_create` *works* — but **zero templates link to it**. Drop the create claim; document **Edit** only (My groups → a collection → **Edit**); **state the gap plainly**: there is no in-app way to create one.

- [ ] **Step 4: `rocznik` → `kohorta` — PL only, 7 hits, WITH DECLENSION**

Not `sed`: `roczników`→**kohort**, `Rocznikami`→**Kohortami**, `## Roczniki`→**## Kohorty**, `**Rocznik**`→**Kohorta**. msgids: `Cohort`→Kohorta, `All cohorts`→Wszystkie kohorty, `Cohorts`→Kohorty.

- [ ] **Step 5: L41 + L50**

L41: the seeded name is the **literal English "Default"**; PL renders **"Default (domyślna)"** — only the parenthetical is translated. L50: `sprawdzanie **testów**` → `**quizów**` (wraps across a newline).

- [ ] **Step 6: Verify GREEN** — all greps zero, incl. `grep -rlzP 'sprawdzanie\s+testów'`. Eyeball: reads as description, not instruction; **New group** survived (absorbed, not dropped); the collections gap is stated.

- [ ] **Step 7: Commit** — `docs(help): groups-collections — reframe teacher-403 flows; state the missing collection-create`

---

### Task 9: `roster` — THE FULL REWRITE

**Files:** `docs/help/teacher/roster.md`, `.pl.md`
**Findings:** §1.2/§3 row 2 (**the whole topic**), L42, L43, **L44 (DISPUTED)**, §3.2 picker scope, §3.1.2 `rocznik`→`kohorta` (**8 occurrences on 7 lines** — count occurrences, not lines), `Przydziel uczniów`, cross-link.

> **Spec §6 sizes this apart from the rest.** It is "a step-by-step of a flow teachers are 403'd from". Do not estimate it at the same rate.

- [ ] **Step 1: Negative-test** — `press **Edit**,`, `with **New**`, `everyone eligible for the group's`, `Press **Save** to apply`, `its **Assign students** list` (EN); `ocznik` (8 hits), `**Szukaj po nazwisku**`, `**Przydziel uczniów**` (PL).

- [ ] **Step 2: ⚠ DISPUTE L44 in the PR — do not apply it as written**

L44 says PL `**Przydziel uczniów**` → `**Przypisz uczniów**`. **Verified false three ways:**
1. `msgid "Assign students"` **does not exist** in the catalog
2. No template renders that string in either language
3. `cohort_form.html` renders a **long** label (`Assign students to this cohort (moves them from their current cohort)` → `"Przypisz uczniów do tej kohorty (przeniesie ich z obecnej kohorty)"`) plus an **Assign**/**Przypisz** button

**L44's replacement is itself a string the product never renders** — it swaps one fabrication for another. The finding's *direction* is right (the doc invented a label); its *target* is wrong. **The EN has the identical defect and the audit missed it** (`its **Assign students** list`).

**Correct treatment — ONE ruling, not a choice:** **describe the control by what it actually renders** — a long checkbox-list label (`Assign students to this cohort (moves them from their current cohort)` / `Przypisz uczniów do tej kohorty (przeniesie ich z obecnej kohorty)`) plus an **Assign** / **Przypisz** button. **Do not bold a pseudo-label in either language.**

*Why this and not "drop the label":* the sentence's job is to tell a PA where cohort membership is changed. Dropping the label leaves the reader hunting; naming the real control is the same standard §3 row 3 applies to quiz-review — be true and be useful.

**Fix EN too.** `roster.md`'s `its **Assign students** list` is the identical fabrication and the audit missed it — it is *not* a PL-only finding.

**Record in findings §3.6** (Task 26). DoD #1 allows disputing; it must not be silently dropped.

- [ ] **Step 3: The rewrite — third-person, read-only lead**

Absorb (spec DoD #4 — "the corrected claim survives in the new prose"):
- **L42** — there is **no Edit button**: the group **name** is the edit link; rows carry only Archive/Delete; `group_detail.html` (where a teacher actually lands from My groups) has **no edit control at all**. *That last point is what makes the reframe useful rather than merely true.* "New" is **New group**.
- **L43** — **Szukaj wg nazwiska** must survive in the reframed "Picking students" section.
- **§3.2 picker scope** — **the highest-value fix in the topic**, and it sits *inside* the reframed section so it dissolves unless named. The picker lists **every non-staff user on the platform**; the course is never consulted.
- **§3.1.2 `rocznik`→`kohorta`** — 8 hits straddling the reframed section **and** the whole `## Roczniki przydziela się gdzie indziej` section, heading included. Declension + gender flip (masc.→fem.): `którego rocznika`→`której kohorty`.

- [ ] **Step 4: PRESERVE these — verified true and worth keeping through the rewrite**

The live `shown / total` counter; `Added: N` with its `(saved: N)` divergence hint; and **filtering never drops a selection** (every checkbox stays in the DOM). Re-voice them; do not lose them.

- [ ] **Step 5: Verify GREEN**

```bash
export LC_ALL=C.UTF-8
grep -rn 'Assign students' docs/help/teacher/roster.md         # → zero (the EN fabrication)
grep -rn 'Przydziel uczniów' docs/help/teacher/roster.pl.md    # → zero (the PL fabrication)
grep -o 'ocznik' docs/help/teacher/roster.pl.md | wc -l        # → zero (8 occurrences before)
grep -rn 'Szukaj po nazwisku' docs/help/teacher/roster.pl.md   # → zero
```
Eyeball: no second-person imperative survives in the group-editing flow; the lead states teachers are read-only; L42/L43/L44's corrected claims and the picker-scope fact are all present in the new prose.

- [ ] **Step 6: Commit** — `docs(help): roster — reframe to third person; picker is platform-wide, not course-scoped`

---

### Task 10: `builder`

**Files:** `docs/help/course-admin/builder.md`, `.pl.md`
**Findings:** §3.2 dashboard entry point (EN half), §3.2 structure-presets legend, L01, L02. **No §3.1.1 hit** — this topic's "Manage courses" is the *dashboard* claim, not the nav entry. Do not conflate.

- [ ] **Step 1: Negative-test** — `Manage courses`, `press **Build**`, `Add unit`, `chosen in the builder legend` (EN); `Zarządzaj kursami`, `Buduj`, `Dodaj jednostkę`, `w legendzie` (PL).

- [ ] **Step 2: RETARGET the dashboard claim — do not delete (G4)**

Both `Manage courses` and `Build` are **live strings** — they are simply not on the dashboard. The dashboard panel is **Studio**, and it links each owned course **straight into the builder** (no Build button). The **Manage courses** list, reached via the **All courses** link, *does* have Build per row.

Keep the parenthetical about the Manage-courses list — it preserves the true route the old sentence garbled.

- [ ] **Step 3: Structure presets are not chosen in the legend**

`_structure_legend.html` is a **static, read-only `<p>`**. The picker is the `structure` radio group on the course metadata form, reached via **Edit course metadata** in the builder's side panel.

- [ ] **Step 4: L01 + L02**

L01: `**Add unit**` does not exist → type a name into **New title**, then press the **+ Lesson** or **+ Quiz** chip (PL: **Nowy tytuł**, **+ Lekcja**, **+ Quiz**).
L02: append — going *shallower* is **blocked** while content exists at the level being removed.

- [ ] **Step 5: G5 — "one of four structure presets" is itself false**

`courses/ordering.py` `preset_for_flags()` returns `None` for a flag-triple matching no preset, and `courses/forms.py` handles that branch explicitly (`# Custom course`). **A course can be Custom.** Suggest "…(or a custom chain)". **Record in findings §3** (Task 26) and flag in the PR.

- [ ] **Step 6: CARVE-OUT** — `builder.md`'s "the outline on the left" is **correct here** (the builder tree really is the left column) and must **not** be swept with `content-editors`' L07, which targets a different screen.

- [ ] **Step 7: Verify GREEN.** `Manage courses`/`Zarządzaj kursami` **must still appear once each** — zero means the route was deleted instead of retargeted.

- [ ] **Step 8: Commit** — `docs(help): builder — retarget the dashboard route; presets live on the metadata form`

---

### Task 11: `content-editors`

**Files:** `docs/help/course-admin/content-editors.md`, `.pl.md`
**Findings:** findings §2 **[1a]** palette group count, spec §2.1 button name (4 of 6 hits), L03, L04, L05, L06, L07.

- [ ] **Step 1: Negative-test** — ⚠ **use `grep`, not `rg`** (G3: `rg '+ Add element'` → parse error, prints nothing):
```bash
export LC_ALL=C.UTF-8
grep -rn -e '+ Add element' -e 'outline on the left' -e 'Content** group and a' -e 'author-only **title**' docs/help/course-admin/content-editors.md
grep -rn -e '+ Dodaj element' -e 'konspekt po lewej' -e 'Matematyk' -e 'Ramka (iframe)' docs/help/course-admin/content-editors.pl.md
```

- [ ] **Step 2: The palette group count — MUST carry its condition (spec §2.1)**

| Context | Groups | Count |
|---|---|---|
| Top level of a **lesson** | Content, Interactive, Questions, Structure | **4** |
| Top level of a **quiz** | Content, Questions, Structure | **3** |
| **Nested** in a lesson | Content, Interactive | **2** |
| **Nested** in a quiz | Content | **1** |

**A bare "four groups" is a NEW false claim** — false in 3 of 4 contexts. Say: *at the top level of a lesson* the menu shows four groups — Content, Interactive, Questions, Structure — and **Interactive is absent in a quiz**.

**Do NOT** enumerate each group's contents, and **do NOT** document the nesting gates — both are slice 1b (G6). The `unit_is_quiz` gate is 1a's, because the sentence is untrue without it.

- [ ] **Step 3: Apply**

| Find | Replace | Ground truth |
|---|---|---|
| `+ Add element` (2 hits) | `Add element` | msgid `Add element`; rendered after a **fullwidth** `＋` |
| PL `+ Dodaj element` (2 hits) | `Dodaj element` | msgid `Add element` → `Dodaj element` |
| `Delete an element from its editor form` | delete via the **🗑 on its row**; the form offers only **Save**/**Cancel** | `_element_row_controls.html` / `_host_form.html` |
| `author-only **title**` | **Label (optional)** (placeholder *Shown in the element list*) | `Label (optional)` |
| PL `**Matematyka**` (2 hits) | **Wzór** | `Math` → `Wzór` |
| PL `**Ramka (iframe)**` | **Iframe** | `Iframe`→`Iframe`; **"Ramka" is Callout's PL name** — a different element |

- [ ] **Step 4: L07 — do NOT say "on the left"**

The editor is a **two-pane screen** (Editor + live Preview) with an **Editor/Split/Preview** toggle. The two-column split lives only inside a `min-width` media query — below it the panes stack, and in Editor/Preview mode one is `display:none`. **"Two-pane with a View toggle" is true at every width; "on the left" is not.**

- [ ] **Step 5: CARVE-OUTS — verified, do not touch**
- PL `zbyt duże ramki` — generic prose ("oversized iframes"), **not** an L06 hit
- `Give it a descriptive **title**` — that is the **Iframe element's own `Title` field**, not L04's element label. After L04 the two are correctly distinct (`Label (optional)` vs `Title`)
- **Do not add** the 5 undocumented Content types (Table, Gallery, Callout, Tabs, Columns) — slice 1b

- [ ] **Step 6: Verify GREEN + commit** — `docs(help): content-editors — palette groups with their condition; Wzór/Iframe PL names`

---

### Task 12: `quiz-editors`

**Files:** `docs/help/course-admin/quiz-editors.md`, `.pl.md`
**Findings:** findings §2 **[1a]** marking-fields scoping, spec §2.1 button name (2 of 6), L08, L09, L10.

- [ ] **Step 1: Negative-test** — incl. the **wrapped** span `grep -rlzP 'Wymaga\s+sprawdzenia'`.

- [ ] **Step 2: The marking fields are QUIZ-ONLY**

`_marking_fields.html` wraps all three in `{% if is_quiz %}` — **a lesson's editor does not render them at all**. Rewrite "Every question shares a few common fields" → the prompt/explanation are common; **three further fields appear only in a quiz**.

- [ ] **Step 3: L08 — `Stem` is an internal field name**

The rendered label varies by type: **Question**, **Prompt (optional)**, **Sentence with blanks**, **Sentence with gaps**.

⚠ **G5: L08's own list is incomplete** — the audit named three; there are **four** (`Sentence with gaps`, `_edit_dragfillblankquestion.html`). **Record in findings §3.**

⚠ **THE PL TRAP:** `Sentence with blanks` and `Sentence with gaps` are **distinct msgids sharing one msgstr** (both → **Zdanie z lukami**). **Mechanically mirroring EN's four-item list into PL produces a duplicate.** PL gets **three** entries.

- [ ] **Step 4: L09, L10, button name**

L09: `**Explanation**` → **Explanation (optional)** (PL **Wyjaśnienie (opcjonalne)**).
Button: `+ Add element` → **Add element** (2 hits here; 4 in Task 11 — **DoD #2's gate only goes green once both land**).
L10: eight `##` headings → the palette strings (**Jednokrotny wybór**, **Wielokrotny wybór**, **Krótki tekst**, **Liczba**, **Uzupełnij luki**, **Przeciągnij słowa**, **Dopasuj pary**, **Przeciągnij na obraz**, **Rozszerzona odpowiedź**). **Knock-on hits the finding omits:** the renamed types are referenced in running prose and the `## Zobacz też` block — locate by search and re-align.

- [ ] **Step 5: G5 — four undocumented PL-invention defects, none in the audit**

`quiz-editors.pl.md` invented translations for the marking fields — the exact §3.1.2 failure mode, **in a topic with no §3.1.2 row**:

| Doc says | Product renders | msgid |
|---|---|---|
| `Oceniane automatycznie` | **Automatycznie oceniane** | `Auto-marked` |
| `Wymaga sprawdzenia` (×2) | **Wymaga recenzji** | `Requires review` |
| `Maksymalna liczba prób` | **Maks. prób** | `Max attempts` |
| `Maksymalna liczba punktów` | **Maks. punktów** | `Max marks` |

**This is evidence the §3.1.2 table is itself a floor.** Record in findings §3 and flag in the PR.

- [ ] **Step 6: ⚠ THE `etykiet*` CARVE-OUT — five hits, do not touch any (G4)**

All five are the **generic label sense** and are **correct Polish**, verified against `msgid "Zones & labels"` → *Strefy i etykiety* and `msgid "Extra labels (distractors, one per line)"` → *Dodatkowe etykiety…*. **An `etykiety`→`tagi` sweep would corrupt all five.**

**Do not add** Matrix question / Multi-select grid — slice 1b (G6). This is *why* L08's replacement says "the label varies by type" rather than enumerating types.

- [ ] **Step 7: Verify GREEN.** `grep -rn 'etykiet' docs/help/course-admin/quiz-editors.pl.md` **must still return FIVE** — fewer means the sweep over-reached. Eyeball: EN's label list has **four** entries, PL's has **three**.

- [ ] **Step 8: Commit** — `docs(help): quiz-editors — marking fields are quiz-only; PL palette headings`

---

### Task 13: `media-manager`

**Files:** `docs/help/course-admin/media-manager.md`, `.pl.md`
**Findings:** §3.2 dashboard entry point (media-manager half), L11, L12, **+ a §3.1.2 `Przesyłanie plików` hit with no L-row** (see Task 25).

- [ ] **Step 1: Negative-test — TWO PL spans WRAP (G3)**
```bash
export LC_ALL=C.UTF-8
grep -rlzP 'licznikiem\s+użyć' docs/help/course-admin/media-manager.pl.md      # plain grep MISSES
grep -rlzP 'usunięcie\s+zostanie\s+odrzucone' docs/help/course-admin/media-manager.pl.md  # plain grep exits 1
```

- [ ] **Step 2: Retarget the entry point — a DIFFERENT sentence from `builder`'s**

`media-manager.md` says "…open your course's **Build**er, then press **Media library**." **Only the first clause is wrong**; the **Media library** step is correct. Unlike `builder`, `Manage courses`/`Build` may legitimately disappear entirely here — the media library is not on the course-list page.

- [ ] **Step 3: L11 + L12**

L11: `**usage count**` → renders **in use ×N** (expand it to list the units) or **unused**.
L12: deletion is **prevented, not refused** — the 🗑 ships `disabled` (*In use — cannot delete*) while in use; **the attempt cannot be made**.

- [ ] **Step 4: PL grammar note (G2 collision)**

`nieużywane` is **neuter**; `plik` is masculine. `plik jest **nieużywane**` is ungrammatical. Use `oznaczony jako **nieużywane**` — preserves the verbatim msgstr while agreeing. **Do not inflect a msgstr; restructure the sentence.**

- [ ] **Step 5: G5 — the "Choose media" claim is partly false**

The doc says all three fields share a **Choose media** button. `_edit_dragtoimagequestion.html` renders **Choose image**/**Change image**. Record in findings §3, flag in the PR. *(Gallery renders **Add image** but is undocumented — 1b — so do not add it.)*

- [ ] **Step 6: CARVE-OUT** — PL `**Zmienić nazwę**`/`**Usunąć**` are **infinitives governed by `możesz:`** — Polish grammar forces them. Leave.

- [ ] **Step 7: Verify GREEN.** `Media library`/`Biblioteka multimediów` **must still appear** — the correct step was kept, not collateral.

- [ ] **Step 8: Commit** — `docs(help): media-manager — in use ×N / unused; delete is disabled, not refused`

---

### Task 14: `branding-settings`

**Files:** `docs/help/platform-admin/branding-settings.md`, `.pl.md`
**Findings:** L28, §3.2 sign-up policy, §3.2 default theme, §3.1.2 `Branding`→`Wygląd` + `Przesyłanie plików`→`Przesyłanie` + role-label case.

- [ ] **Step 1: Negative-test** — incl. `grep -qzP '\*\*Przesyłanie\r?\nplików\*\*'` (**the bold span wraps**).

- [ ] **Step 2: Apply**

| Find | Replace | Ground truth |
|---|---|---|
| `**default theme** (light/dark)` | `(**Light**, **Dark** or **Auto** — Auto is the default)` | `THEME_CHOICES`, `default="auto"` |
| `open, restricted, or disabled` | either **Invite only** or **Open self-signup** | `SIGNUP_CHOICES` — **two** choices; "restricted"/"disabled" don't exist |
| `SSO and Integrations each have their own topic` | add **Notifications** | `_tabs.html` renders **six** tabs |
| PL `**Branding**`, `## Branding` | **Wygląd** | `Branding`→`Wygląd` |
| PL `**Przesyłanie plików**`, `## Przesyłanie plików` | **Przesyłanie** | `Uploads`→`Przesyłanie` |
| PL `Administratorzy Kursu` | `Administratorzy kursu` | `Course Admin`→`Administrator kursu` |

- [ ] **Step 3: OUT OF SCOPE — do not touch the H1s (G6)**

`# Branding & platform settings` (EN) and `# Branding i ustawienia platformy` (PL) are **§3.5 H01**. The EN registry title is `_("Branding & settings")` but its PL msgstr is `"Branding i ustawienia platformy"` — **EN and PL disagree about what the title even is**, which is exactly why H01 is deferred.

- [ ] **Step 4: CARVE-OUTS — verified TRUE, leave**

EN `**Signup policy**` is correct (Django auto-derives it — no `_()` override). Both Access behavioural claims verified: invitations bypass the signup policy; the domain allowlist is advisory for invites, enforced for self-signup.

- [ ] **Step 5: G5 — a PRODUCT defect to file, not fix**

`BrandingForm`/`AccessForm` auto-derived labels (**Name**, **Logo**, **Signup policy**, **Default theme**) carry no `_()` and appear in **no catalog entry** — they **render in English under a Polish UI**. `courses/forms.py` fixes this exact class with an explicit `labels` dict; `institution/forms.py` never got it. **Out of scope (G6) — file it** (Task 27).

*Consequence for the PL bullet — read carefully, the obvious fix is wrong:*

`msgid "Sign-up policy"` → `msgstr "Zasady rejestracji"` **does exist** in the catalog (a plain G2 lookup — **not** an authored string; do **not** route it through DoD #5's approval flow, and do not contradict Task 2's "one authored string" claim).

**But `Zasady rejestracji` is the section `<h2>`, not the field label.** The *field* renders **"Signup policy" in English** under a Polish UI (the auto-derived label bug above). So bolding **Zasady rejestracji** as if it were the field label would introduce a **new false claim** — the exact defect class §1 forbids, created by the fix.

**Decision:** do not bold a field label the product does not render in Polish. Describe the setting under its real section (**Dostęp**), and if a label must be quoted, quote what actually renders (`Signup policy`) with a parenthetical that it is untranslated pending the product fix (Task 27). **Do not silently substitute the `<h2>`.**

- [ ] **Step 6: Verify GREEN + positively confirm H01 survived:**
```bash
grep -c 'Branding & platform settings' docs/help/platform-admin/branding-settings.md   # → 1
grep -c 'Branding i ustawienia platformy' docs/help/platform-admin/branding-settings.pl.md  # → 1
```

- [ ] **Step 7: Commit** — `docs(help): branding-settings — two sign-up choices, Auto theme, PL tab names`

---

### Task 15: `cohorts`

**Files:** `docs/help/platform-admin/cohorts.md`, `.pl.md`
**Findings:** §3.1.3 `Add cohort`→**New cohort** + `Promote`→**Make default** (**these exist ONLY in §3.1.3 — `cohorts` has zero L-rows**, exactly the loss spec §2.2 warns of), §3.2 deletion, §3.2 archiving, §3.1.2 `Kohort z samodzielnym zapisem` + role-label case.

- [ ] **Step 1: Negative-test** — incl. `grep -qzP 'Administratorzy\r?\nKursu'` (**wraps**).

- [ ] **Step 2: The behavioural fixes — the highest-stakes in this topic**

| Claim | Truth |
|---|---|
| "A cohort can only be deleted once it has no members" | **No such precondition exists.** `delete_cohort` guards only the *default* cohort, then **reassigns members to Default** and deletes. The confirm page says "{{ counter }} students will be moved to the Default cohort." |
| "**Archive** retires a cohort … without deleting its history" | **It silently empties it** — `archive_cohort` reassigns **all members to Default** before setting `archived`. So **Un-archive** brings the cohort back **empty**. Undocumented. |

**msgid `"Add cohort"` and `"Promote"` are BOTH ABSENT from the catalog** — dead strings. Real: **New cohort**, **Make default**, **Un-archive**.

- [ ] **Step 3: CARVE-OUT (G7)** — PL `**Ustaw jako domyślną**` is **already correct**. Do not "fix" it back. **But the carve-out is that string and nothing more** — every other finding still lands in PL, including `**Dodaj kohortę**` → **Nowa kohorta** and the deletion-precondition sentence.

- [ ] **Step 3a: Apply the two §3.1.2 rows this task gates but never fixed**

| Find (PL, locate by search) | Replace | msgid |
|---|---|---|
| `**Kohort z samodzielnym zapisem**` | kohort w polu **Kto może się zapisać** | `Self enroll cohorts` |
| `Administrator Platformy; Administratorzy\nKursu` (**wraps** — use `-z`) | `Administrator platformy; Administratorzy kursu` | `Platform Admin` / `Course Admin` |

Both are real and both were negative-tested in Step 1 with no corresponding action. **This row spans multiple topics** (`create-a-course.pl.md` too) — Task 25 tracks it.

- [ ] **Step 4: G5 — `cohorts.pl.md` carries L41's defect in 3 places**

L41 is filed only against `groups-collections.pl.md`, but this file translates the seeded name in three spots (`Domyślnej`, „Domyślna", `Domyślną`). The stored name is the **literal English "Default"**, rendered **"Default (domyślna)"** — only the parenthetical is translated. Keep the `## Kohorta domyślna` *heading* (it names the concept, not the object) — flag that split for review. **Record in findings §3.**

- [ ] **Step 5: Verify GREEN.** `grep -c 'Ustaw jako domyślną' docs/help/platform-admin/cohorts.pl.md` **must still return 1** — the G7 carve-out held.

- [ ] **Step 6: Commit** — `docs(help): cohorts — deletion has no empty precondition; archiving empties the cohort`

---

### Task 16: `create-a-course`

**Files:** `docs/help/platform-admin/create-a-course.md`, `.pl.md`
**Findings:** §3.1.1 `Manage`→**Studio**, L20, §3.1.2 `Slug` + `Kohort z samodzielnym zapisem` + role-label case (**3 hits on 3 consecutive lines** — the audit cites only `users-roles.pl.md`).

- [ ] **Step 1: Negative-test** — `Open **Manage** and click`, `## Required fields` (EN); `otwórz **Zarządzaj**`, `**Slug**`, `Kohort z samodzielnym zapisem`, `Administrator` (PL).

- [ ] **Step 2: Apply**

| Find | Replace | msgid |
|---|---|---|
| `Open **Manage**` | `Open **Studio**` | `Studio`→`Studio` (untranslated by design) |
| PL `otwórz **Zarządzaj**` | `otwórz **Studio**` | same — the PL is **actively wrong** |
| `## Required fields` | `## Core fields` | Slug is `required = False` |
| `- **Slug** —` | `- **Slug** *(optional)* —` | `required = False` |
| PL `- **Slug** —` | `- **końcówka URL (slug)** *(opcjonalne)* —` | `Slug` → **końcówka URL (slug)** — msgstr is **deliberately lowercase**; quote verbatim |
| PL `**Kohort z samodzielnym zapisem**` | kohort w polu **Kto może się zapisać** | `Self enroll cohorts` |
| PL `Administratora Kursu`/`Administrator Platformy` (3 hits) | lowercase noun | `Course Admin`/`Platform Admin` |

- [ ] **Step 3: G4 — confine the `Manage`→`Studio` swap to the ONE nav sentence per language.** `Manage courses` remains the live course-list heading; **Manage** remains the Groups sub-tab.

- [ ] **Step 4: Judgement** — `## Required fields` → `## Core fields` is a call: Title and Structure genuinely *are* required on create; only Slug is the outlier. The `*(optional)*` marker makes it read truthfully either way. **PL `Pola podstawowe` is an authored heading** (headings are prose, no catalog entry) — flag for the Polish approver alongside Task 2's string.

Structure is required **on create only** — the doc covers the create form, so "required" is true in context. Don't assert it when editing.

- [ ] **Step 5: Verify GREEN + commit** — `docs(help): create-a-course — Studio nav, Slug is optional, PL field names`

---

### Task 17: `export-import`

**Files:** `docs/help/platform-admin/export-import.md`, `.pl.md`
**Findings:** §3.1.1 `Manage`→**Studio**, §3.1.3 (3 renames), L29, §3.2 missing media, §3.1.2 `Eksportuj`.

- [ ] **Step 1: Negative-test** — `Export course`, `**Export** on any node`, `Use **Manage**`, `**Import** inside`, `pre-flight page`, `clearly labelled placeholder`.

- [ ] **Step 2: ⚠ THREE CONTROLS, THREE STRINGS — two on ADJACENT template lines (G4)**

| Doc says | Truth | Note |
|---|---|---|
| `**Export course**` | **Export** (`builder.html`) | msgid `"Export course"` **absent** — dead string |
| node `**Export**` | **Export subtree** (`_tree_node.html`) | **icon-only** (aria-label/title on an `<svg>`) — say "the **Export subtree** icon", or the reader hunts for a text button |
| `**Import**` (builder) | **Import content** (`builder.html`) | msgid `"Import"` **absent** |
| `**Import course**` | ✅ **CORRECT — DO NOT RENAME** | live at `course_list.html`; msgid present |

**Spec §5.1 records that an earlier draft cited this exact line for the rename and would have broken a true label.**

- [ ] **Step 3: §3.2 — the media claim needs RESTRUCTURING, not a word swap**

The doc asserts **one** uniform behaviour; the product has **three**:
- missing **image** → exported as a **placeholder**
- missing **video** → the block is **left out of the export**
- **broken** content block → **left out of the export**

Real page title: **Export — missing media** ("pre-flight page" is in no template); buttons **Export anyway** / **Cancel**.

- [ ] **Step 4: L29 — the flow steps**

**Upload and preview** → the **Import preview** page → **Confirm import** / **Cancel**.

- [ ] **Step 5: Verify GREEN + positively confirm the correct string survived:**
```bash
grep -c 'Import course' docs/help/platform-admin/export-import.md      # → 1
grep -c 'Importuj kurs' docs/help/platform-admin/export-import.pl.md   # → 1
```

- [ ] **Step 6: Commit** — `docs(help): export-import — videos are dropped, not placeholdered; three distinct controls`

---

### Task 18: `first-run-wizard`

**Files:** `docs/help/platform-admin/first-run-wizard.md`, `.pl.md`
**Findings:** L31, §3.2 Team step reachability, §3.1.2 role-label case.

- [ ] **Step 1: Negative-test** — `can be **skipped**`, `every step it covered` (EN); `można **pominąć**`, `opisanych przez niego kroków`, `Administratora Platformy` (PL).

- [ ] **Step 2: L31 is NARROWER than it looks — do not over-correct**

**Identity, Access and SSO all have a Skip button.** Only **Team** lacks one — its **Next** advances without sending. **The false part is the universal quantifier, not the concept.** A fix that deletes the skip claim entirely is as wrong as the original.

*(Note `sso.html` ends with **Finish**, not Next — don't imply SSO has a Next.)*

- [ ] **Step 3: §3.2 — RETARGET, don't delete**

"Every step it covered" is false **only for Team**. Identity/Access/SSO genuinely map to the **Branding**/**Access**/**SSO** settings tabs; **Team** does not — invitations live at **Admin → People → Invitations**.

⚠ **The mapping is not name-for-name:** the wizard's *Identity* step corresponds to the *Branding* tab (PL **Wygląd**) — so the PL must quote "Wygląd", not "Tożsamość", for the tab.

- [ ] **Step 3a: Apply the §3.1.2 role-label row this task gates but never fixed**

`first-run-wizard.pl.md` — `prowadząc Administratora Platformy przez` → `Administratora platformy` (`msgid "Platform Admin"` → **Administrator platformy**; the noun is lowercase). Negative-tested in Step 1 with no corresponding action.

- [ ] **Step 4: msgctxt gotcha** — `"Next"` carries **`msgctxt "wizard"`** → **Dalej**. A plain `msgid "Next"` lookup can hit a different entry.

- [ ] **Step 5: CARVE-OUT (spec §2.3's worked example)** — `first-run-wizard.pl.md`'s `[Branding i ustawienia platformy](branding-settings)` is a **cross-link label to the topic**, matching the PL registry msgstr exactly. **It is NOT the tab.** The `Branding`→`Wygląd` sweep must not fire here.

- [ ] **Step 6: Verify GREEN.** `grep -c 'Branding i ustawienia platformy' docs/help/platform-admin/first-run-wizard.pl.md` **must still return 1**.

- [ ] **Step 7: Commit** — `docs(help): first-run-wizard — only Team lacks Skip; Team maps to People, not Settings`

---

### Task 19: `integrations`

**Files:** `docs/help/platform-admin/integrations.md`, `.pl.md`
**Findings:** §3.2 grade sync, L30, §3.1.2 `sekret podpisujący` + `adres URL punktu odbioru`.

- [ ] **Step 1: Negative-test** — `endpoint URL`, `signing secret`, `Once both are set`, `A delivery is queued`.

- [ ] **Step 2: The setup needs RESTRUCTURING — the trap is the relationship between two wrong halves**

The doc asserts a two-step setup, then hands the reader a test button that "confirms" it. **Both are wrong together.**

**Live grade sync needs all FOUR:** **Endpoint URL**, **Signing secret**, **Enable result sync** ticked, and a **Register subject code** on the course.

⚠ **Count carefully — findings §3.2's parenthetical lists only three.** `services.py` guards three (endpoint row, `enabled`, `external_id`); url+secret are enforced **upstream** in `forms.py`, which refuses to set `enabled` without them. The **user-facing four** are as above.

⚠ **The trap:** **Send test event** is gated on **url+secret only** — it does **not** check `Enable result sync`. So it becomes available, passes, and **proves nothing about live delivery**. The doc must warn about this.

- [ ] **Step 3: L30 — "one delivery per group" would create a NEW false claim**

`_student_groups(...) or [None]` means a student in **no** group still gets **exactly one** delivery. Stating only "one per group" implies zero for an ungrouped student. **Cover both.**

Also: a submission with questions needing manual review is **not** sent at submit time — it delivers once review completes.

- [ ] **Step 4: PL** — **Adres URL punktu końcowego**, **Klucz podpisujący**, **Włącz synchronizację wyników**, **Zapisz ustawienia integracji**. *Corroboration:* the button's disabled-title msgstr reads "Najpierw ustaw adres URL i **klucz podpisujący**" — the product's PL word is **klucz**, never *sekret*.

- [ ] **Step 5: OUT OF SCOPE (G6)** — `# Integrations (grade sync)` / `# Integracje (synchronizacja ocen)` are **§3.5 H03/H04**. Both H1s carry information the registry title lacks — exactly why §3.5 defers. **Do not touch.**

- [ ] **Step 6: CARVE-OUT** — `Send test event` / `zdarzenie testowe` is "test" in its **ordinary sense**, not the unit type. The §3.1.2 `test`→`quiz` row leaves it alone.

- [ ] **Step 7: Verify GREEN + positively confirm H03/H04 survived. Commit** — `docs(help): integrations — grade sync needs four things; the test event proves nothing`

---

### Task 20: `invitations`

**Files:** `docs/help/platform-admin/invitations.md`, `.pl.md`
**Findings:** §1.6 (**delete the whole section**), L21.

- [ ] **Step 1: Negative-test — BOTH gates (G3, spec DoD #3)**
```bash
export LC_ALL=C.UTF-8
grep -rilzP 'Add user|Dodaj\s+użytkownika' docs/help/platform-admin/invitations.md docs/help/platform-admin/invitations.pl.md
grep -rnE 'Adding a user directly|Dodawanie użytkownika bezpośrednio' docs/help/platform-admin/
```
⚠ **The first gate CANNOT see the headings** — "Adding" ≠ "Add user"; "Dodawanie" has no `Dodaj`+whitespace. **Verified by test: no match.** A body-only deletion strands both headings **and still passes gate 1**. Both gates are mandatory.

- [ ] **Step 2: Delete the WHOLE `## Adding a user directly` section — heading + body, both languages**

`accounts/urls.py` has **no user-create route**; "Add user" is in **no template**. The PL sibling carries `## Dodawanie użytkownika bezpośrednio` and loses the same section, or the section-for-section mirror breaks.

⚠ The PL bold span **wraps**: `**Dodaj\nużytkownika**`.

- [ ] **Step 3: L21 — `**Invite**` → **Send invitation** (PL **Wyślij zaproszenie**)**

**Judgement:** the form is **always visible** — nothing is "used" to open it. "use **Invite**" reads as a disclosure trigger; a bare rename keeps that false implication. Recast: fill in the form at the top of the tab; **Send invitation** sends it.

- [ ] **Step 4: CARVE-OUT (spec §2.3's worked example)** — `invitations.pl.md`'s `[Branding i ustawienia platformy](branding-settings)` is a **cross-link to the topic**, not the `Wygląd` tab. The sweep must not fire.

⚠ **This span WRAPS** (`[Branding i\nustawienia platformy]`), so `grep -cF 'Branding i ustawienia platformy'` returns **0** — G1 tells you to locate by searching for the quoted string, and that search finds nothing. Locate and gate it with `-z`:
```bash
LC_ALL=C.UTF-8 grep -rlzP 'Branding\s+i\s+ustawienia\s+platformy' docs/help/platform-admin/invitations.pl.md   # → 1 (carve-out held)
```
**Task 25's `Branding` row needs this same `-z` locator** to find all five hits.

- [ ] **Step 5: Verify GREEN** (both gates zero; `grep -rn 'Wygląd' docs/help/platform-admin/invitations.pl.md` → zero, carve-out held). Eyeball: both files end cleanly; no orphaned `##` or trailing blank.

- [ ] **Step 6: Commit** — `docs(help): invitations — delete the "Add user" section for UI that never existed`

---

### Task 21: `users-roles`

**Files:** `docs/help/platform-admin/users-roles.md`, `.pl.md`
**Findings:** §1.6 (**clause-only**), L21, §3.2 CA permissions (**+ the PL-is-worse asymmetry**), L25, L26, L27.

> **§1 of the spec leads with this topic** — "a PA assigning roles from this page picks the wrong one." Highest-stakes rewrite in the slice.

- [ ] **Step 1: Negative-test** — the `Add user` gate, `Either way|W obu przypadkach`, `cohorts for the courses`, `tworzy i edytuje kursy`, `Administrator Platformy|Administrator Kursu`.

- [ ] **Step 2: §1.6 — CLAUSE-only here (opposite of Task 20)**

Delete only "or **Add user** to create an account directly" / "lub **Dodaj użytkownika**…". **The `## Adding a user` heading SURVIVES.**

⚠ **The connective must go too:** the sentence continues "…**Either way** you choose the person's initial role" / "…**W obu przypadkach** wybierasz początkową rolę" — *in both cases*, with one case left. Drop it in both languages, or the surgical fix leaves ungrammatical prose.

The retained **Invite** takes its L21 fix — **and it takes Task 20's recast rule, not a bare rename.**

`users-roles.md` uses the same "Use **Invite** to…" phrasing Task 20 Step 3 explicitly rules insufficient: **the invite form is always visible, so nothing is "used" to open it**, and a bare `Invite` → `Send invitation` swap preserves that false implication while satisfying a grep. **One standard for L21 across both topics** — recast so the button *sends* rather than *opens*. (Without this, the two topics ship contradicting each other and DoD #1 counts L21 "applied" in both.)

- [ ] **Step 3: §3.2 — the Course Admin bullet. THREE TRAPS.**

| Claim | Truth |
|---|---|
| CA "manages … cohorts" | **False.** add/change/delete_cohort are PA-only |
| CA "builds and edits courses" | **Half-false.** `COURSE_PERMS` (incl. `add_course`) is in `PLATFORM_ADMIN_PERMS` **only** → **a CA cannot create a course**. A CA *can* edit one they **own** (`can_manage_course` = owner OR `change_course`) |
| PL "tworzy i edytuje kursy" | **Flatly false** — *creates*. The PL is **worse than EN** (G7 inverted: this needs an **extra PL-only fix**) |

⚠ **TRAP 1 — do NOT write "can view cohorts but not change them."** It looks like the natural reading of `view_cohort`, but it is a **NEW false claim**: `cohort_list` is gated on **`change_cohort`**, and the source comment says the `view_cohort` grant exists **only** to read cohort names in the group student-picker. **A CA cannot reach any cohort UI.** The true statement is **"cohorts are Platform Admin only."**

⚠ **TRAP 2 — do NOT drop "manages groups."** CA group management is **real**, just **owner-scoped** (`groups_manageable_by` filters CAs to `course__owner=user`). Deleting it over-corrects.

⚠ **TRAP 3** — add "A Platform Admin creates a course and assigns its owner." Not a finding, but without it the reader asks how a CA comes to own a course they cannot create.

- [ ] **Step 4: L25, L26, L27**

L25: the role select is **not** on the row — the row has only **Edit**; the select is on the **Edit user** page. *(The **Role** select on the People page is a **filter**.)* The `## Adding a user` sentence repeats this defect ("from their account row") — fix it there too.
L26: **Deactivate**/**Reactivate** are on the **Edit** page, not the row.
L27: `Administrator Platformy`/`Administrator Kursu` → lowercase noun (**4 hits**; one wraps `Administratora\n  Kursu`).

- [ ] **Step 5: Verify GREEN + commit** — `docs(help): users-roles — CAs cannot create courses or manage cohorts`

---

### Task 22: `notifications`

**Files:** `docs/help/platform-admin/notifications.md`, `.pl.md`
**Findings:** L22, L23, L24.

- [ ] **Step 1: Negative-test** — `**Purge now**`, `` `flush` ``, `**Wyczyść teraz**`, `okno retencji`.

- [ ] **Step 2: L22 — the job is `purge_notifications`**

`flush_webhooks` is the **unrelated SIS outbox flusher**; bare `flush` is Django's **database-wiping** builtin.

- [ ] **Step 3: L23 — a TWO-STRING problem, not a rename**

"Purge now" is **not wrong** — it just isn't the button; it's the `<h2>`. The button is **Purge old notifications now**. **A naive swap deletes a true fact** (the heading is how you find the button on a long tab). **Both strings survive:** heading in italics, button bolded. Same in PL (**Wyczyść teraz** / **Wyczyść stare powiadomienia teraz**).

- [ ] **Step 4: L24** — PL `**okno retencji (w dniach)**` → **Okno przechowywania (dni)**.

- [ ] **Step 5: G7 CARVE-OUT + a judgement call**

`notifications.pl.md`'s **omission of `flush` is the carve-out** — the PL is better than EN on that line. **Do not reintroduce `flush` in any form.** Adding `purge_notifications` (the *correct* name, for parity) is a **strict improvement**, not a revert — the carve-out forbids re-adding the *falsehood*. **Flag the choice in the PR.**

- [ ] **Step 6: G5 — two additions, neither in the audit**

`_notifications_tab.html` renders "Purge uses the saved retention value; save your changes first." — **the doc's "Set the retention window … Use Purge now" sequence implies the typed value applies immediately. It does not.** And there is a separate **Save retention settings** button the doc never names. Fold both in. **Record in findings §3.**

`msgid "Save retention settings"` → **`"Zapisz ustawienia przechowywania"`**. *(Supplied inline like every other msgstr here — but re-verify by msgid search before writing, per G1; the derivation flagged this one as unlooked-up and it was resolved afterwards.)*

- [ ] **Step 7: Verify GREEN**

```bash
grep -rn 'flush' docs/help/platform-admin/notifications.md      # GATE: red before (1 hit), → zero after
grep -rn 'flush' docs/help/platform-admin/notifications.pl.md   # NOT a gate — see below
```

⚠ **The PL grep is a carve-out confirmation, not a gate.** G7 records that `notifications.pl.md` **already omits `flush`** — so it is green *before any edit*, which G3 calls decoration. It proves only that the carve-out held (you did not *re-introduce* the falsehood). **Only the EN grep can go red**, because only `notifications.md` contains `flush` today.

- [ ] **Step 8: Commit** — `docs(help): notifications — the job is purge_notifications; Purge now is a heading`

---

### Task 23: `sso`

**Files:** `docs/help/platform-admin/sso.md`, `.pl.md`
**Findings:** L13, L14, L15 (×2 per file), L16.

- [ ] **Step 1: Negative-test** — `**Name**`, `**Server URL**`, `**Enabled**` (EN); `**Nazwa**`, `**Adres URL serwera**`, `**Włączone**`, `**Client ID** oraz` (PL).

- [ ] **Step 2: Apply**

| Find | Replace | msgid |
|---|---|---|
| `**Name**` | **Display name** | `Display name` |
| PL `**Nazwa**` | **Nazwa wyświetlana** | same |
| `**Server URL**` | **Issuer / discovery URL** | `Issuer / discovery URL` |
| PL `**Adres URL serwera**` | **Adres wydawcy / discovery** | same |
| `**Enabled**` (×2) | **Enable SSO** | `Enable SSO` |
| PL `**Włączone**` (×2) | **Włącz logowanie SSO** | same |
| PL `**Client ID** oraz **Client secret**` | **Identyfikator klienta** oraz **Sekret klienta** | `Client ID`/`Client secret` |

- [ ] **Step 3: ⚠ L15's replacement CONTAINS A VERB — re-read every sentence**

"Enabled" is an **adjective**; "Enable SSO" is an **imperative**. "toggle **Enable SSO** off" and PL "wyłącz **Włącz logowanie SSO**" (*disable Enable-SSO*) are both **near-gibberish**. Recast to "leave **Enable SSO** unticked" / "zostaw … niezaznaczone" — which matches the **checkbox** the product renders. **This is G4's failure mode: sense-scoped, not a token swap.**

- [ ] **Step 4: CARVE-OUTS**
- **`sso.pl.md`'s "etykieta dostawcy"** — explicit carve-out in **both** the findings row **and** spec §2.3. Generic *label* sense. Only the bolded `**Nazwa**` on that line changes.
- **`# SSO (OIDC)` — §3.5 H02, OUT OF SCOPE (G6).** It sits **three lines above** real L13/L14 edits, so it is genuinely at risk of a "while I'm here" fix.
- EN `**Client ID**`/`**Client secret**` are **correct** — L16 is PL-only.
- The wizard-skip claim ("it can be skipped and configured later") is **CORRECT** — `setup/sso.html` ships a **Skip** button. **L31 is about the wizard's Team step and belongs to `first-run-wizard` — do not let it bleed in.**

- [ ] **Step 5: Verify GREEN + positively confirm the carve-outs:**
```bash
grep -c 'etykieta dostawcy' docs/help/platform-admin/sso.pl.md   # → 1 (must NOT be zero)
head -1 docs/help/platform-admin/sso.pl.md                       # → "# SSO (OIDC)" UNCHANGED
```

- [ ] **Step 6: Commit** — `docs(help): sso — real field labels; Enable SSO is a checkbox, not a toggle`

---

### Task 24: `subjects`

**Files:** `docs/help/platform-admin/subjects.md`, `.pl.md`
**Findings:** §3.1.1 `Manage`→**Studio**, L17, L18, L19, §3.1.2 `Slug`.

- [ ] **Step 1: Negative-test** — incl. `grep -rlzP 'kursie w\s+\*\*Zarządzaj\*\*'` (**the PL span wraps**).

- [ ] **Step 2: Apply**

| Find | Replace | Ground truth |
|---|---|---|
| `**Add subject**` | **New subject** | `New subject` |
| PL `**Dodaj przedmiot**` | **Nowy przedmiot** | same |
| `row in **Manage**` | `row in **Studio**` | §3.1.1 |
| PL `kursie w **Zarządzaj**` | `kursie w **Studio**` | `Studio`→`Studio` |
| `**course count**` | a **used by N courses** link | it is a **filter link** |
| PL `**liczbę kursów**` | odnośnik **używany przez N kursów** | plural msgstr `[2]` |

- [ ] **Step 3: L18 IS THE TRAP — a wrong MODEL, not a wrong label**

"a name and a slug" — **there is no "name" field at all.** There are **two** title fields (**Title (English)**, **Title (Polish)** — the latter falls back to English when blank), and **the slug derives from the ENGLISH title specifically**. A PA who types only a Polish title gets a slug derived from an **empty string**.

**The replacement must name WHICH title drives the slug**, or it re-lands the same defect in nicer words.

- [ ] **Step 4: L19 likewise** — "course count" isn't just misnamed; the product renders a **link that filters the course list**, an affordance the doc omits entirely. Renaming the string while dropping the link satisfies a grep and still under-describes the UI.

- [ ] **Step 5: PL grammar (G2 collision)** — msgstrs must appear **verbatim in the nominative** (`Tytuł (angielski)`, `końcówka URL (slug)`). Cast the sentence as `z polami: X, Y oraz Z` — a colon list — rather than an instrumental construction that would force `Tytułem`/`końcówką`. **Do not inflect a msgstr; restructure the sentence.**

- [ ] **Step 6: CARVE-OUTS** — `subjects.pl.md`'s **"nowej etykiety"** is the generic *label* sense (explicit carve-out in findings **and** spec §2.3). `**Edytuj**`/`**Edit**` are correct and must survive the `Manage`→`Studio` edit.

- [ ] **Step 7: G5 — optional additions.** `subjects.pl.md`'s "Istniejące przedmioty można zmienić nazwę" is **ungrammatical Polish** (should be `Istniejącym przedmiotom można zmienić nazwę lub je usunąć`), and both languages say "renamed or removed" without naming the row's actual **Edit**/**Delete** buttons. **Record in findings §3.**

- [ ] **Step 8: Verify GREEN.** `grep -c 'nowej etykiety' docs/help/platform-admin/subjects.pl.md` **must still return 1**.

- [ ] **Step 9: Commit** — `docs(help): subjects — New subject, two title fields, the used-by filter link`

---

### Task 25: Walk the findings §3.1.2 table row-by-row (DoD #1a)

**Files:** none directly — this is a verification sweep across `docs/help/**`.

**Why this task exists:** DoD #1 keys on "every finding **naming that topic**", and **roughly half of findings §3.1.2's rows name no topic and give no doc-side line**. A topic-keyed pass sails straight past them. Several span **multiple** topics, so fixing one hit and calling it done is the likely failure.

- [ ] **Step 1: For each of the 18 rows, find EVERY hit by search (G1) and record its resolution**

**Re-derive every count by search — the numbers below are orientation, not truth** (G1 binds this plan too; an earlier draft of this very table stated "7 hits across 4 topics" while listing five files and sub-counts summing to ten). Use occurrence counts, not line counts:

```bash
export LC_ALL=C.UTF-8
grep -rozP 'Administrator[a-ząćęłńóśźż]*\s+(Platformy|Kursu)' docs/help/ | wc -l
```

| Row | Hits (re-derive) | Resolution |
|---|---|---|
| `Administrator Platformy/Kursu` | ~**11 occurrences across 5 files** — `users-roles.pl.md` (4), `create-a-course.pl.md` (3), `cohorts.pl.md` (2), `first-run-wizard.pl.md` (1), `branding-settings.pl.md` (1). The audit cites **only** `users-roles.pl.md`. One wraps (`Administratora\n  Kursu`) | applied per-topic (Tasks 14, 15, 16, 18, 21) |
| `Sprawdzanie testów (×5 cross-links)` | **5 files**, all in Teacher scope | applied |
| `Przesyłanie plików`→`Przesyłanie` | `branding-settings.pl.md` **and `media-manager.pl.md`** (no L-row, no topic attribution) — **coordinate so it resolves once, consistently.** The EN sibling is **correct** — PL-only | applied |
| `Kohort z samodzielnym zapisem` | `cohorts.pl.md` **and** `create-a-course.pl.md` | applied |
| `Slug`→`końcówka URL (slug)` | `create-a-course.pl.md`, `subjects.pl.md` | applied |
| `etykiety`→`tagi` | **ONLY** `notes-tags.pl.md` (13 hits) | **4 carve-out files untouched** |
| `Branding`→`Wygląd` | **2 of 5 hits** (`branding-settings.pl.md` tab refs only) | **3 carve-outs held** |
| `Eksportuj` | **3 hits, 3 different destinations** | applied per-topic |
| `Zastosuj` | **1 hit**, not the ×2 the row implies | applied |
| `test`→`quiz` | PL only, unit-type sense only | **`Send test event` untouched** |

**The eight rows not tabled above** (`Branding`, `Przesyłanie plików`, `Kohort z samodzielnym zapisem`, `sekret podpisujący`, `adres URL punktu odbioru`, `Slug`, `okno retencji`, `Matematyka`/`Ramka`) are enumerated in findings §3.1.2. **Walk all 18** — a plan-side list of ten reproduces, one level up, the exact partial coverage DoD #1a exists to prevent.

- [ ] **Step 2: Record every leave-untouched decision too** — the carve-outs are as much a result as the edits. A row resolved to "no hits" or "carve-out held" is a result, not a skip.

- [ ] **Step 3: Write the record into findings `### 3.6` and commit it** (G8)

Append the row-by-row table to the findings doc alongside Task 26's additions — **not** to the PR description alone. DoD #1a is gated on this walk; its evidence must live in the repo, where the pre-release re-audit will look for it. Cross-post to the PR body as well.

```bash
git add docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md
git commit -m "docs(help): record the §3.1.2 row-by-row walk (DoD #1a)"
```

---

### Task 26: Record the audit-floor additions (G5)

**Files:** Modify `docs/superpowers/specs/2026-07-17-help-pages-audit-findings.md`

**Why:** spec §5 — "Record additions in findings §3 so the pre-release re-audit has a true baseline." **The re-audit diffs against this document**; an unrecorded fix looks like a regression.

> **These 12 are a FLOOR, not a list.** G5 says anything new found while editing is in scope. If Tasks 3–24 surface a 13th, **append it** — do not treat this enumeration as closed. That is the exact failure mode this plan diagnoses in the audit itself; reproducing it one level up would be self-defeating.
>
> **Each topic task appends its own additions to §3.6 as it goes** — do not batch-discover them here at the end, or a finding made in Task 4 has to survive twenty tasks in someone's head.

- [ ] **Step 1: Ensure `### 3.6 Found during slice-1a execution` exists in the findings doc, and that it contains at least these** (each verified during derivation):

1. **L44 is WRONG** — `msgid "Assign students"` does not exist; the replacement is itself a fabrication. **EN has the identical defect and the audit missed it.**
2. **The false Analytics-button claim spans 6 locations, not 1** (§3.4 cites only `analytics.md`).
3. **"cherry-pick" spans 4 locations, not 1** (L32 cites only `analytics.md`); one is an **H2 heading**.
4. **Group archive is a teacher-403 too** (`group_archive` needs `change_group`) — §1.2 names only create/edit.
5. **L08's label list is incomplete** — a fourth variant, **Sentence with gaps**, exists.
6. **`quiz-editors.pl.md` invented FOUR marking-field translations** — the §3.1.2 failure mode in a topic with no §3.1.2 row. **Evidence the table is itself a floor.**
7. **`builder.md`'s "one of four structure presets"** ignores the **Custom** case.
8. **`media-manager.md`'s "Choose media"** is false for Drag to image (**Choose image**/**Change image**).
9. **`cohorts.pl.md` carries L41's defect in 3 places** (filed only against `groups-collections.pl.md`).
10. **`notifications`**: purge uses the **saved** value (the doc implies otherwise), and a **Save retention settings** button is never named.
11. **`subjects.pl.md`** has an ungrammatical sentence; neither language names the row's **Edit**/**Delete** buttons.
12. **`Administrator Platformy/Kursu` spans 4 topics / 7 hits**, not the one cited.

- [ ] **Step 2: Commit** — `docs(help): record the findings the audit missed, found during slice-1a execution`

*(No count in the subject line — a pinned number discourages the 13th.)*

---

### Task 27: File the product-gap issues (DoD #11)

**Files:** none — GitHub issues.

- [ ] **Step 1: File one issue per gap, each carrying the audit's citations**

| Gap | Content |
|---|---|
| **findings §1.1** | `grouping:collection_create` has a view, a URL and a test — and **zero templates linking it**. Teachers hold `add_collection`. Either build the "New collection" button or drop the feature. |
| **findings §1.2** | The Teacher manual documents flows teachers are **403'd** from (group create/edit — **and archive**, found during execution). Either re-file the topics under Course Admin or grant the perms. ⚠ **Granting is an access widening** — see `[[access-widening-reachability-tests]]`: drive every newly-reachable surface as the new role; latent 500s are likely. |
| **findings §1.3** | **Quiz review is unreachable for teachers.** The only link lives in the Studio-gated `_course_panel.html`. The queue view **admits teachers** — it's a missing link, not a locked door. **Same defect, same partial, that PR #72 fixed for Analytics.** The fix pattern exists. |
| **NEW (Task 14)** | `BrandingForm`/`AccessForm` auto-derived labels (**Name**, **Logo**, **Signup policy**, **Default theme**) carry no `_()` → they **render in English under a Polish UI**. `courses/forms.py` fixes this exact class with an explicit `labels` dict; `institution/forms.py` never got it. |
| **findings §1.5** | `seed_demo_course` sets `file="courses/images/demo.png"` but never creates it → the demo course's image renders **broken**. **Owned by slice 2** (the screenshot substrate drives this seed) — cross-reference, don't duplicate. |

- [ ] **Step 2: Cross-link each issue from the PR description.**

---

## Final verification (before opening the PR)

- [ ] **All DoD gates green, each having been seen RED first** (G3)

```bash
export LC_ALL=C.UTF-8
# DoD #3 — both gates
grep -rilzP 'Add user|Dodaj\s+użytkownika' docs/help/                                  # → zero
grep -rnE 'Adding a user directly|Dodawanie użytkownika bezpośrednio' docs/help/        # → zero
# DoD #2 — the button (grep, NOT rg)
grep -rn -e '+ Add element' -e '+ Dodaj element' docs/help/                             # → zero
# §3.4 — the false Analytics-button claim, ALL SIX locations (Tasks 4, 5, 6)
grep -rnE 'the \*\*Analytics\*\* button|przyciskiem \*\*Analityka\*\*' docs/help/        # → zero
# The two fabricated "Assign students" labels (Task 9 — L44 disputed)
grep -rn -e 'Assign students' -e 'Przydziel uczniów' docs/help/                         # → zero
# DoD #7 — the rename + no obsoletes
grep -rn 'Notes & tags' core/ locale/                                                   # → zero
grep -c '^#~' locale/en/LC_MESSAGES/django.po                                           # → 0
grep -c '^#~' locale/pl/LC_MESSAGES/django.po                                           # → 0
# DoD #10 — all 22 PL siblings still exist
git ls-files 'docs/help/**/*.pl.md' | wc -l                                             # → 22
# DoD #12 — the four out-of-scope H1s survived
grep -c 'Branding & platform settings' docs/help/platform-admin/branding-settings.md    # → 1
head -1 docs/help/platform-admin/sso.pl.md                                              # → "# SSO (OIDC)"
grep -c 'Integrations (grade sync)' docs/help/platform-admin/integrations.md            # → 1
grep -c 'Integracje (synchronizacja ocen)' docs/help/platform-admin/integrations.pl.md  # → 1
# Carve-outs held (positive greps — zero here means a sweep over-reached)
grep -c 'etykiet' docs/help/course-admin/quiz-editors.pl.md                             # → 5
grep -c 'etykieta dostawcy' docs/help/platform-admin/sso.pl.md                          # → 1
grep -c 'nowej etykiety' docs/help/platform-admin/subjects.pl.md                        # → 1
grep -c 'Ustaw jako domyślną' docs/help/platform-admin/cohorts.pl.md                    # → 1
grep -c 'Import course' docs/help/platform-admin/export-import.md                       # → 1
grep -c '3 selected' docs/help/teacher/drill-down.md                                    # → 1
grep -rn 'flush' docs/help/platform-admin/notifications.pl.md                           # → zero
```

- [ ] **DoD #8** — `uv run pytest` green (full suite)
- [ ] **DoD #9** — `uv run ruff check` + `uv run ruff format --check` clean
- [ ] **DoD #5** — the `Multi-select grid` msgstr is **user-approved** and flagged in the PR
- [ ] **DoD #6** — the SUSPECTED finding (findings §3.4) is resolved: **confirmed** during
      derivation (no course-facing template renders an Analytics link), so Task 4 applies
      §3 row 3's standard — name the real entry points, invent none. Not re-litigated.
- [ ] **DoD #1/#1a** — every finding applied or **disputed in the PR description** (L44 is disputed — see Task 9)
- [ ] **DoD #4** — both reframes **absorbed** their findings; the corrected claims survive in the new prose
- [ ] **Render `/help/`** in EN and PL and click through all 22 topics
