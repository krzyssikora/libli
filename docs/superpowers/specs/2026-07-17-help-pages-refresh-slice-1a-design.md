# Help pages refresh — slice 1a: correct the drift (design)

**Status:** design, awaiting review
**Evidence base:** [2026-07-17-help-pages-audit-findings.md](./2026-07-17-help-pages-audit-findings.md)
**Slice 1 of the help-pages refresh initiative** (see §7 for the slice map).

Throughout, `§N` means *this* spec; references to the evidence base are always
written **"findings §N"**.

## 1. Problem

The in-app help system (`/help/`, 22 topics, 44 files EN+PL) shipped in PR #71 and
has not been touched since. The UI moved underneath it. An audit (2026-07-17)
found **103 findings across all 22 topics; none is clean**.

The docs do not merely lag — in places they are *actively misleading*:

- `analytics.md:19-21` documents a 3-colour band model (green/yellow/grey, keyed
  on "completed" and a "pass threshold") that **does not exist**. The product has
  five percentage bands (`courses/color_bands.py:14-26`).
- `cohorts.md:21-22` states a cohort "can only be deleted once it has no members".
  There is **no such precondition**; deletion reassigns members to Default
  (`grouping/services.py:121-124`).
- `users-roles.md:18-19` tells a Platform Admin that Course Admins manage cohorts
  and create courses. **Both false** (`institution/roles.py:53-66,76-86`) — a PA
  assigning roles from this page picks the wrong one.
- `integrations.md:9-10` says grade sync needs a URL and a secret. It needs
  **four** things, and "Send test event" passes while sync is off
  (`integrations/services.py:69-73`, `institution/views_manage.py:79`).

**Goal:** every audited finding is resolved, and no topic makes a claim the
implementer found to be false while editing it.

That is deliberately narrower than "the docs become true". The audit is a **floor,
not a ceiling** — it is known to be non-exhaustive (§5), so completeness cannot be
promised by applying a list. This slice adds no screenshots (slice 2) and changes
no product behaviour (§3).

## 2. Scope

Doc edits, one registry rename, one msgstr. Nothing else.

### 2.1 The slice boundary is defect type, not findings-section number

**Wrong claims are 1a. Pure omissions are 1b.** This holds *regardless of which
findings section an item was filed under* — the audit grouped by discovery, not by
defect class, so the sections do not map cleanly onto slices.

Consequently these items sit in findings §2 but are **owned by 1a** (tagged
**[1a]** there): `content-editors.md:6-7` claiming the add-menu has two groups when
it has four, and `quiz-editors.md:6` claiming the marking fields are common to
every question when they are quiz-only. 1a corrects the group count and names the
four groups; *enumerating their contents* is 1b.

### 2.2 In scope

1. **The itemized findings.** Findings §3 enumerates, with a `file:line` citation
   on both sides:
   - **§3.2 — 19 behavioural findings** (incl. **B00**, the `notes-tags` nav
     drift), the highest-value fixes;
   - **§3.3 — 50 label/name findings**, IDs **L01–L50**;
   - **§3.1.4 — 1 title rename** (§4 below).

   **70 individually-cited findings.** Findings §3.1.1–§3.1.3 are *cross-cutting
   guidance* (sweeps and their carve-outs), not a separate population — their
   instances are itemized in §3.2/§3.3. There is deliberately **no "~80" figure**;
   see DoD #1 for the completeness criterion.
2. **The [1a] items from findings §2** (§2.1 above).
3. **Deleting the "Add user" claims** (findings §1.6) — `invitations.md:36-37` and
   `users-roles.md:7-8` document UI that has never existed (`accounts/urls.py` has
   no create route; "Add user" appears in no template).
4. **True-today wording** where a Class-3 gap makes a doc describe something
   unreachable (§3).
5. **The `Multi-select grid` msgstr** (findings §1.4). See §4.3 for why this one
   product-adjacent line is in scope.
6. Resolving the one **SUSPECTED** finding (findings §3.4) before rewriting it.

### 2.3 Sweeps are sense-scoped, never token replacements

Two findings sweeps look like `sed` candidates and are not. Both carve-outs are
recorded per-row in findings §3.1.1–§3.1.2; restated here because getting them
wrong corrupts correct files:

- **`etykiety` → `tagi` applies ONLY where it renders the *tags feature*** — i.e.
  `notes-tags.pl.md` (including its H1). `etykieta` is the product's correct
  Polish for a generic **label** (`django.po:1407`, `:1678`, `:3959`, `:4799`,
  `:4812`). **Leave untouched:** `quiz-editors.pl.md:63,66,71,74,75`,
  `sso.pl.md:12`, `subjects.pl.md:33`.
- **`Manage` → `Studio` applies ONLY to the *nav entry*.** "Manage" survives in
  the product: `Manage courses` is still the course-list `head_title` and `<h1>`
  (`templates/courses/manage/course_list.html:3,7`), reachable via **All courses**
  (`home.html:57`); **Manage** is still the Groups sub-tab
  (`templates/_groups_tabs.html:7`). Confine to the three cited files (+PL).

### 2.4 Out of scope (with reasons)

- **Findings §2 minus its [1a] items** → **slice 1b**: the 17 undocumented element
  types, **plus per-option MCQ feedback** (`courses/models.py:1477`) **plus the
  nesting/gating rules** (`_add_menu.html:24,25,41`). Correcting wrong prose and
  authoring 17 element sections × 2 languages are different jobs — one is
  mechanical and checkable against the audit, the other needs product
  understanding and prose review. Combined they make an unreviewable PR.
- **Product fixes** (findings §1.1–1.5) → issues (§3). Decision 2026-07-17: the
  docs PR stays docs-only. This excludes granting teachers
  `add_group`/`change_group` — an access widening whose blast radius is documented
  in `[[access-widening-reachability-tests]]`.
- **Any anti-rot mechanism.** Decision 2026-07-17: the app is near
  feature-complete and a re-audit is planned pre-release; re-running the audit
  costs ~20 minutes. See findings §4.

## 3. Class-3 gaps: what the docs say *today*

The audit found **five** places where the doc is right and the **product** is wrong
(findings §1.1–1.5). Each becomes a GitHub issue carrying the audit's citations,
but 1a must still leave the doc true *now*.

(Findings §1.6, the "Add user" claims, sits in that section because it documents UI
that never shipped — but it *is* doc-fixable, so it is handled in §2.2 item 3.)

| # | Gap | Issue? | What the doc says in 1a |
|---|---|---|---|
| 1 | `collection_create` has no caller (findings §1.1) | **file** | **Drop the create claim** and say the gap plainly: collections can currently only be edited (My groups → a collection → **Edit**, `collection_detail.html:8`), and there is **no in-app way to create one**. See rationale below. |
| 2 | Teachers 403 on group create/edit (findings §1.2) | **file** | **Keep filed under TEACHER; reframe the body** — see rationale below. This is a rewrite, not a prepended line. |
| 3 | Quiz review unreachable for teachers (findings §1.3) | **file** | **Describe the real path**: the **Quiz review** button in the course builder (`_course_panel.html:7`), noting it requires course-manage access. Do not invent a teacher path. |
| 4 | `Multi-select grid` untranslated (findings §1.4) | **no** — fixed here (§4.3) | Nothing; 1b documents the element. |
| 5 | `seed_demo_course` broken image (findings §1.5) | **no** — owned by slice 2 (§7) | Nothing. |

**Rows 4 and 5 need no issue.** Row 4 is fixed in this slice (§4.3). Row 5 is
already tracked by the slice map (§7) as slice-2 work; a duplicate issue would
track it twice.

**Rationale — row 1 (collections).** The **Edit** control is real
(`collection_detail.html:8`), but nothing anywhere creates a Collection: the only
references to `collection_create` are `grouping/urls.py:38`, `grouping/views.py:338`
and a test, and `grouping/admin.py` registers no Collection either. So the doc
would teach editing an object the reader cannot obtain. Applying the same standard
as row 3: say it plainly rather than describe a flow with a missing first step.

**Rationale — row 2 (roster/groups).** Findings §1.2 scopes this as *the whole
topic*: `roster.md` is a step-by-step of a flow teachers are 403'd from
(`grouping/views.py:189-190,223-224` vs `GROUPING_TEACHER_PERMS`,
`institution/roles.py:68-74`). A gating line prepended to imperative instructions
does not make them true — every "Press **Save**" still tells a teacher to do
something they cannot. **Reframe the body from second-person imperative to
third-person description** ("a Course Admin or Platform Admin adds students by
…"), with a lead sentence stating teachers have read-only access.
`roster.md` is the **one topic in this slice needing substantive rewriting rather
than correction**, and should be sized as such (§6). Re-filing the topic under
Course Admin is an IA decision, deferred to the issue.

**Rationale — row 3 (quiz review).** The least satisfying option, stated plainly: a
TEACHER-filed topic will describe an entry point most teachers cannot use. The
alternatives are worse — inventing a path is false, omitting it strands the
reader. The doc becomes *true*; the issue makes it *useful*. Same defect PR #72
fixed for the Analytics link, in the same partial, so the fix pattern exists.

## 4. The topic-title rename

`core/help.py:148` registers the Teacher topic as `_("Notes & tags")`, whose PL
msgstr is `"Notatki i etykiety"` (`django.po:219`) — the **only** one of the 22
registry titles carrying the terminology bug (verified: all 22 have translations).

**Rename it to `_("Tags & notes")`.** This fixes terminology and word order, and
matches the product's own nav (`base.html:77`). It costs no new translation:
`msgid "Tags & notes"` **already exists** (`django.po:2796-2797` → `"Tagi i
notatki"`), joining its five existing references
(`notes/course_notes.html:9`, `notes/overview.html:3`, `notes/overview.html:10`,
`tags/my_tags.html:7`, `templates/base.html:77`). `msgid "Notes & tags"` drops out.

### 4.1 The registry title is not the only title — fix the H1s too

The registry title renders as page chrome (`templates/help/doc.html:3,14,20` — head
title, sidebar, breadcrumb) **above the markdown body, whose own H1 is a separate
string**. Renaming only the registry leaves the breadcrumb reading "Tags & notes"
directly above an H1 reading "Notes & tags", and leaves `etykiety` on the page:

- `docs/help/teacher/notes-tags.md:1` — currently `# Notes & tags` → **`# Tags & notes`**
- `docs/help/teacher/notes-tags.pl.md:1` — currently `# Notatki i etykiety` →
  **`# Tagi i notatki`**

The PL H1 must be **`Tagi i notatki`** — the reused msgstr verbatim — **not** the
`Notatki i tagi` that a mechanical `etykiety`→`tagi` replacement would produce.

**Invariant to hold across all 22 topics:** a topic's markdown H1 equals its
registry title as rendered in that language.

### 4.2 Keep the slug

**Keep the slug `notes-tags`** and the file paths. It is a URL segment; renaming
breaks bookmarks for no gain, and slug ≠ title is already normal in this registry
(slug `create-a-course`, title "Creating a course").

*(An earlier draft justified this with "five inbound cross-links". That was wrong:
`grep -rn "notes-tags" docs/help/` returns **zero** — no help doc links to this
slug. The five cross-links belong to `quiz-review`
(`drill-down.pl.md:59`, `gradebook-export.pl.md:47`, `groups-collections.pl.md:48`,
`notes-tags.pl.md:49`, `roster.pl.md:43`) and are the last row of findings §3.1.2 —
they need their **label** fixed, "Sprawdzanie testów" → "Sprawdzanie quizów", but
their target is fine.)*

### 4.3 The `Multi-select grid` msgstr is in scope

`django.po:1000-1001` — `msgid "Multi-select grid"` → `msgstr ""`, the **only**
untranslated msgid in the catalog (1 of ~1000), so that palette card renders in
English for PL users. Fix it here rather than filing an issue:

- This slice already opens, regenerates and commits
  `locale/pl/LC_MESSAGES/django.po` — the exact file §6 calls a conflict hotspot.
  A separate branch buys a conflict in it for no reviewability gain.
- It is a **translation, not product logic**. The docs-only rule (§6 "Not
  touched") bars views, templates, models and permissions; a msgstr is content.
- **It unblocks 1b**: findings §2 notes the PL palette card has no rendered Polish
  term, so 1b's PL element doc would have nothing to quote.

### 4.4 Mechanics / gotchas

- **All four locale artifacts are tracked** (`git ls-files locale/`):
  `locale/{en,pl}/LC_MESSAGES/django.{po,mo}`. `locale/en/LC_MESSAGES/django.po:212`
  also carries `msgid "Notes & tags"`. `makemessages` regenerates **both** `.po`
  files; `compilemessages` must then run or the tracked `.mo` blobs go stale.
  Expect all four in the diff.
- Per `[[uv-run-tooling]]`, watch the **fuzzy-flag gotcha** — inspect the
  `makemessages` diff; do not accept fuzzies blind.
- Per `[[course-export-import-status]]`: **run the i18n catalog tests whenever a
  build removes translatable strings.** This build removes one.
- The existing translation-assertion test derives titles from `TOPICS`
  (`tests/test_help.py:280-287`), so the rename is covered:
  `"Tagi i notatki" != "Tags & notes"` passes the PL≠EN guard.

## 5. Approach

Findings §3 is a per-finding worklist with `file:line` on both sides, so most of
the work is mechanical: **apply findings §3 topic by topic, EN and PL together.**

- **The audit is a floor, not a ceiling.** It is demonstrably non-exhaustive —
  B00, the drift that *triggered* this whole effort, went unrecorded until
  spec-review caught it, because it had been handed to the subagents as a
  pre-known anchor. So: **while editing a topic, re-verify its claims against the
  templates**, and treat anything new as in scope. Record additions in findings §3
  so the pre-release re-audit has a true baseline.
- **Work per topic, not per sweep.** Both files of a topic in one pass keeps EN/PL
  parity verifiable — every `.pl.md` is a section-for-section mirror, so each EN
  fix has exactly one PL counterpart. Three asymmetries to preserve deliberately
  (findings §4): PL `users-roles` is *worse* than EN; PL `notifications` and PL
  `cohorts` are *better*.
- **Every PL label is a `msgstr` lookup, not a translation.** For each bolded PL
  UI string: find the msgid the EN doc quotes and use its `msgstr` verbatim. Where
  the finding's citation names a **template** line rather than a catalog line
  (seven rows do), resolve the `{% trans %}` msgid on that line, then look up its
  msgstr — **the catalog is always the final authority**. This discipline's
  absence caused ~20 findings.
- **Verify before rewriting.** Where a fix needs wording beyond the citation (e.g.
  the five colour bands), read the source first. Confirm or drop the SUSPECTED
  finding (findings §3.4).

## 6. Files touched & DoD

**Touched:** 44 files under `docs/help/**`; `core/help.py` (one line);
`locale/en/LC_MESSAGES/django.po`; `locale/pl/LC_MESSAGES/django.po`;
`locale/en/LC_MESSAGES/django.mo`; `locale/pl/LC_MESSAGES/django.mo`.

**Not touched:** any view, template, model, or permission. (A msgstr value is
content, not product logic — §4.3.)

**Definition of done:**

1. **Per topic**, every finding in findings §3.1.2–§3.3 naming that topic is
   applied, or disputed in the PR description with reasoning. A finding is never
   silently dropped. *(Stated per-topic rather than as a global count: findings
   §3.1's sweeps and §3.2/§3.3's items overlap, so a single total would be
   arithmetic without a checkable denominator. The 22 topics are the denominator.)*
2. `uv run pytest` green (full suite), including the help tests and the **i18n
   catalog tests** (§4.4). **Isolate the test DB**: `feat/student-practice-state`
   is live in a worktree and concurrent runs collide on the Postgres `test_libli`
   database — set a unique `DATABASE_URL` for this worktree
   (`[[test-db-contention-across-worktrees]]`; symptom is errors-not-failures and
   shifting tests).
3. `uv run ruff check` + `uv run ruff format --check` clean (`--check` is
   separately required, per `[[sis-webhook-guide-status]]`).
4. **All 22 `.pl.md` files still exist, and each PL page renders Polish rather than
   an English fallback.** This must be checked deliberately, because *nothing else
   catches it*: `localized_doc_path` (`core/help.py:27-41`) returns the `.pl.md`
   sibling **iff it exists on disk, else silently falls back to the English base** —
   a missing or misnamed PL file renders EN with a **200**, not a 500. The
   automated coverage is fail-open the same way
   (`tests/test_help.py:83-89` is guarded by `if (DOCS_ROOT / pl_rel).exists()`).
   The "fails loud" contract in `core/help.py:1-4` protects only the EN base path.
5. Issues filed for findings §1.1, §1.2 and §1.3 (rows 1–3 of §3). Rows 4 and 5
   get no issue — see §3.
6. Every topic's markdown H1 equals its registry title as rendered in that
   language (§4.1).

**Risks:**

- **`django.po` conflicts.** *Decision: proceed now; do not wait for
  `feat/student-practice-state`.* 1a's catalog delta is tiny — one msgid removed,
  one msgstr filled — so a rebase costs a `makemessages` re-run, whereas blocking
  a whole docs slice on an unrelated feature branch costs more. Re-run
  `makemessages` + `compilemessages` at rebase time.
- **Scale, concentrated unevenly.** 44 files and 70 itemized findings, most
  mechanical — but `roster.md` (+PL) is a rewrite, not a correction (§3 row 2),
  and should not be estimated at the same rate as the rest.

## 7. Slice map

| Slice | Scope | Status |
|---|---|---|
| **1a** | Correct the drift (this doc) | designed |
| **1b** | Findings §2 in full minus its [1a] items: the 17 element types + per-option MCQ feedback + the nesting/gating rules | not started |
| **2** | Screenshot substrate: deterministic seed (incl. the `seed_demo_course` broken image, findings §1.5) + Playwright capture + static/markdown plumbing (EN/PL × light/dark), proven on 2–3 topics | not started |
| **3** | Illustrate the remaining topics | not started |
| — | Class-3 product gaps (findings §1.1–1.3), one branch each | issues to file |

**Why 1a is first:** screenshots pin a doc to reality. Shooting them against text
we know is wrong bakes in the error. The audit's own trigger is the case in point —
a screenshot of the tags page would have shown "Tagi" beside prose saying
"etykiety".
