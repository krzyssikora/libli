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
**[1a]** there): `content-editors.md:6-7` claiming the add-menu has two groups, and
`quiz-editors.md:6` claiming the marking fields are common to every question when
they are quiz-only.

**The palette group count is context-dependent — "four groups" would be a new
false claim.** `_add_menu.html` gates the groups:

| Context | Groups shown | Count |
|---|---|---|
| Top level of a **lesson** | Content, Interactive, Questions, Structure | **4** |
| Top level of a **quiz** | Content, Questions, Structure | **3** (Interactive gated `{% if not unit_is_quiz %}`, `:27`) |
| **Nested** in a lesson | Content, Interactive | **2** (Questions+Structure inside `{% if not nested %}`, `:41`) |
| **Nested** in a quiz | Content | **1** |

So 1a's replacement sentence **must carry the condition**: at the top level of a
lesson the menu shows four groups — Content, Interactive, Questions and Structure —
and Interactive is absent in a quiz. A bare "four groups" is false in three of the
four contexts, which §1's goal forbids.

**Gate ownership:** `_add_menu.html:27` (`unit_is_quiz`) is **1a's**, because 1a's
own sentence cannot be true without it. The nesting gates (`:24,25,41`) stay
**1b's**. *Enumerating each group's contents* is 1b.

### 2.2 In scope

1. **The findings, worked from every section of findings §3** — §3.1.1 through
   §3.4. **Each section carries findings that exist nowhere else**; none may be
   derived from another:
   - **§3.1.1** — the `Manage`→`Studio` targets (`create-a-course.md:3`,
     `export-import.md:22`, `subjects.md:21` +PL). These appear in **no** §3.2
     bullet and **no** L-row.
   - **§3.1.2** — the PL-invention table (the largest systematic cause).
   - **§3.1.3** — renamed buttons. Only half are itemized elsewhere; **`Add
     cohort`→New cohort, `Promote`→Make default, `Export course`→Export, node
     `Export`→Export subtree, and `Import`→Import content exist ONLY here** — and
     `cohorts` has **zero** L-rows, so an implementer working from §3.2/§3.3 alone
     would lose both cohort renames entirely.
   - **§3.1.4** — the title rename (§4).
   - **§3.2** — behavioural findings (incl. **B00**, the `notes-tags` nav drift),
     the highest-value fixes.
   - **§3.3** — label/name findings **L01–L50**.
   - **§3.4** — the one SUSPECTED finding (§5).

   **No finding total is given, deliberately.** The sections overlap — §3.2 and
   §3.3 duplicate at least L03, L12 and L22 with identical citations — so any sum
   would be arithmetic without a checkable denominator. That is the same defect
   that got the earlier "~80" removed; a "70" would repeat it. DoD #1 uses the 22
   topics as the denominator instead.
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

  > **This carve-out protects the *string*, not every sentence containing it.**
  > `builder.md:4-5` and `media-manager.md:4-5` say "Open it from **Manage
  > courses** on your dashboard: find your course and press **Build**" — still
  > wrong per findings §3.2, because `home.html:45` renders a **Studio** panel and
  > `:49` links straight to the builder with no Build button. **The fix there is
  > deleting the dashboard claim, not substituting "Studio" for "Manage".**

### 2.4 Out of scope (with reasons)

- **Findings §2 minus its [1a] items** → **slice 1b**: the 17 undocumented element
  types, **plus per-option MCQ feedback** (`courses/models.py:1477`) **plus the
  nesting/gating rules** (`_add_menu.html:24,25,41`). Correcting wrong prose and
  authoring 17 element sections × 2 languages are different jobs — one is
  mechanical and checkable against the audit, the other needs product
  understanding and prose review. Combined they make an unreviewable PR.
- **Product fixes** (findings **§1.1–1.3**) → issues (§3). Decision 2026-07-17: the
  docs PR stays docs-only. This excludes granting teachers
  `add_group`/`change_group` — an access widening whose blast radius is documented
  in `[[access-widening-reachability-tests]]`.
  *(Not §1.4 — fixed here, §4.3. Not §1.5 — owned by slice 2, §7. See the §3
  table, which is authoritative for all five.)*
- **The four H1 ≠ registry-title mismatches** (findings §3.5, H01–H04) → follow-up.
  They pre-date this slice, each needs a product decision (matching the registry
  would *delete* information, e.g. "Integrations (grade sync)" → "Integrations"),
  and `branding-settings` cannot be satisfied in both languages at once. Fixing
  them means renaming registry titles — new msgids — which breaks this slice's
  one-rename budget (§4).
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

**This ruling covers BOTH docs findings §1.2 names, not just roster.**
`groups-collections.md:22-25` (+PL `:23-26`) — "Create a group with **New**, give
it a **Name** and **Course**… Save with **Save**" — is the same defect:
second-person imperatives for a flow gated on `grouping.add_group`. It gets the
same third-person reframe. Without this, L40 (`New` → **New group**) would land as
a *polish* on a false instruction: the teacher told the correct name of a button
that 403s them.

**The reframe must absorb the L-rows, not delete them.** `roster.md`'s L42/L43/L44
and `groups-collections.md`'s L40 correct strings inside sentences the reframe
dissolves. "Applied" means **the corrected string survives in the new third-person
prose** — not that the false sentence merely vanished.

`roster.md` is the **one topic in this slice needing substantive rewriting rather
than correction**, and should be sized as such (§6). Re-filing either topic under
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

**Scope of the H1 rule: `notes-tags` only.** An earlier draft asserted this as an
invariant "across all 22 topics". That is not achievable in this slice — a
mechanical diff of every topic's H1 against its registry title found **four files
already mismatched** (findings §3.5, H01–H04: `branding-settings.md`, `sso.pl.md`,
`integrations.md`, `integrations.pl.md`). They are **out of scope** (§2.4): each
needs a product decision, and `branding-settings` cannot be satisfied in both
languages at once because its EN registry title lacks the "platform" its own PL
msgstr carries.

`notes-tags` satisfies the invariant *today*; **this slice's rename is what would
break it**, which is why 1a owns its two H1s and nothing else.

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

`django.po:1000-1001` — `msgid "Multi-select grid"` → `msgstr ""`. It is the
**only** untranslated msgid in the PL catalog (verified: exactly one empty msgstr
among 1,242 entries), so that palette card renders in English for PL users. Fix it
here rather than filing an issue:

- This slice already opens, regenerates and commits
  `locale/pl/LC_MESSAGES/django.po` — the exact file §6 calls a conflict hotspot.
  A separate branch buys a conflict in it for no reviewability gain.
- It is a **translation, not product logic**. The docs-only rule (§6 "Not
  touched") bars views, templates, models and permissions; a msgstr is content.
- **It unblocks 1b**: findings §2 notes the PL palette card has no rendered Polish
  term, so 1b's PL element doc would have nothing to quote.

**The value: `"Siatka wielokrotnego wyboru"`.**

This is the **one string in the slice that must be authored rather than looked
up** — §5's governing rule ("every PL label is a `msgstr` lookup") is by definition
inapplicable, because the msgstr is what's missing. So it needs a stated
derivation and a named approver.

*Derivation* — follow the palette's own conventions rather than inventing a style:
`Switch grid` → "Siatka przełączników" establishes **Siatka** + genitive for a
grid-of-X; `Multiple choice` → "Wielokrotny wybór" gives the concept, whose
genitive is "wielokrotnego wyboru". Hence **Siatka wielokrotnego wyboru**. The
sibling `Matrix question` → "Pytanie macierzowe" confirms the register.

*Approver:* **the user** (a Polish speaker) signs this off. No test or lookup can
validate an authored translation, so it must not land unreviewed — flag it
explicitly in the PR rather than burying it in a regenerated catalog diff.

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
  parity verifiable. Each `.pl.md` is a *section-for-section* mirror — **sections
  correspond, line numbers do not** (`subjects.md:21`'s **Manage** is at
  `subjects.pl.md:27`), so findings' "(+PL)" citations must never be applied by
  line offset. Three topics break even the section correspondence, and **they do
  not all get the same treatment**:
  - PL `notifications` and PL `cohorts` are ***better* than EN** — they already say
    the right thing (`notifications.pl.md:33` omits the bogus `flush`;
    `cohorts.pl.md:22` already says "Ustaw jako domyślną" where EN says "Promote").
    Here the EN fix has **no PL counterpart**: fix EN, leave PL alone.
  - PL `users-roles` is ***worse* than EN** — `users-roles.pl.md:18` says
    "Administrator kursu — **tworzy** i edytuje kursy", the CA-creates-courses
    claim §1 leads with and findings §3.2 calls flatly false. This needs an
    **extra PL-only fix on top of** the EN one. **Do not "preserve" it.** The
    asymmetry is a warning that EN↔PL is not 1:1 — not a licence to keep a
    falsehood.
- **Every PL label is a `msgstr` lookup, not a translation.** For each bolded PL
  UI string: find the msgid the EN doc quotes and use its `msgstr` verbatim. Where
  the finding's citation names a **template** line rather than a catalog line
  (seven rows do), resolve the `{% trans %}` msgid on that line, then look up its
  msgstr — **the catalog is always the final authority**. This discipline's
  absence caused ~20 findings.
- **Verify before rewriting.** Where a fix needs wording beyond the citation (e.g.
  the five colour bands), read the source first.
- **The SUSPECTED finding (findings §3.4) has a pre-made ruling.** `analytics.md:4-5`
  ("Open it from your course with the **Analytics** button") is the direct analogue
  of §3 row 3: a doc naming an entry point the reader's role cannot see. **If
  confirmed, apply row 3's standard** — name the real entry points (the dashboard
  **Teaching** panel, `home.html:33`, and the grouping pages) and do not invent a
  course-facing one. Do not re-litigate the decision; only decide whether the
  finding holds.

## 6. Files touched & DoD

**Touched:** 44 files under `docs/help/**`; `core/help.py` (one line);
`locale/en/LC_MESSAGES/django.po`; `locale/pl/LC_MESSAGES/django.po`;
`locale/en/LC_MESSAGES/django.mo`; `locale/pl/LC_MESSAGES/django.mo`.

**Not touched:** any view, template, model, or permission. (A msgstr value is
content, not product logic — §4.3.)

**Definition of done:**

Every scope item in §2.2 has exactly one gate here.

1. **Per topic**, every finding in findings **§3.1.1–§3.4** naming that topic is
   applied, or disputed in the PR description with reasoning. A finding is never
   silently dropped. The range is **all** of findings §3 — §3.1.1 and §3.1.3 carry
   findings that exist nowhere else (§2.2). *(Stated per-topic rather than as a
   count: the sections overlap, so a total would be arithmetic without a checkable
   denominator. The 22 topics are the denominator.)* **[gates §2.2 item 1]**
2. The two **[1a] items from findings §2** have landed: `content-editors.md:6-7`
   (+PL) states the group count **with its condition** (§2.1 — not a bare "four"),
   and `quiz-editors.md:6` (+PL) scopes the marking fields to quizzes.
   **[gates §2.2 item 2]**
3. `grep -rn "Add user" docs/help/` returns **zero**, in both languages.
   **[gates §2.2 item 3]**
4. Each of the five §3 rows has landed as its table row specifies — including the
   two reframes (`roster`, `groups-collections`), whose corrected L-row strings
   must survive in the new prose (§3). **[gates §2.2 item 4]**
5. `msgid "Multi-select grid"` has a non-empty msgstr, **user-approved** (§4.3),
   and the PL palette card renders Polish. **[gates §2.2 item 5]**
6. The SUSPECTED finding (findings §3.4) is confirmed-and-fixed or dropped with
   reasoning (§5). **[gates §2.2 item 6]**
7. `uv run pytest` green (full suite), including the help tests and the **i18n
   catalog tests** (§4.4). **Isolate the test DB**: `feat/student-practice-state`
   is live in a worktree and concurrent runs collide on the Postgres `test_libli`
   database — set a unique `DATABASE_URL` for this worktree
   (`[[test-db-contention-across-worktrees]]`; symptom is errors-not-failures and
   shifting tests).
8. `uv run ruff check` + `uv run ruff format --check` clean (`--check` is
   separately required, per `[[sis-webhook-guide-status]]`).
9. **All 22 `.pl.md` siblings still exist:**
   `git ls-files 'docs/help/**/*.pl.md' | wc -l` returns **22**.
   Cheap, but not vacuous: a missing or misnamed PL file is **invisible at
   runtime**. `localized_doc_path` (`core/help.py:27-41`) returns the `.pl.md`
   sibling *iff it exists on disk, else silently falls back to the English base* —
   so the PL page renders **English with a 200**, not a 500, and the automated
   coverage is fail-open the same way (`tests/test_help.py:83-89` and the
   english-copy guard at `:92-101` are both `if exists()`-guarded). The "fails
   loud" contract (`core/help.py:1-4`) protects only the EN base path. This slice
   renames no files (§4.2), so the check is a cheap guard against a typo, not a
   likely failure.
10. Issues filed for findings §1.1, §1.2 and §1.3 (rows 1–3 of §3). Rows 4 and 5
    get no issue — see §3.
11. `notes-tags.md:1` and `notes-tags.pl.md:1` match the renamed registry title in
    their language (§4.1). The four pre-existing H1 mismatches (findings §3.5) are
    **out of scope** and must not be "fixed" opportunistically (§2.4).

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
