# Help pages refresh — slice 1a: correct the drift (design)

**Status:** design, awaiting review
**Evidence base:** [2026-07-17-help-pages-audit-findings.md](./2026-07-17-help-pages-audit-findings.md)
**Slice 1 of the help-pages refresh initiative** (see §7 for the slice map).

## 1. Problem

The in-app help system (`/help/`, 22 topics, 44 files EN+PL) shipped in PR #71
and has not been touched since. The UI has moved underneath it. An audit
(2026-07-17) found **103 findings across all 22 topics; none is clean**.

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
  **four** things, and the "Send test event" button passes while sync is off
  (`integrations/services.py:69-73`, `institution/views_manage.py:79`).

This slice makes the docs true. It does not add screenshots (slice 2) and does
not change the product (§3).

## 2. Scope

Doc edits, plus one registry rename. Nothing else.

**In:**

1. The ~80 **Class-1 drift findings** (findings doc §3), across all 44 files:
   - the `Manage` → `Studio` sweep (§3.1.1);
   - the **PL-invention sweep** (§3.1.2) — ~20 findings, the largest single
     cause. The rule: *quote the rendered `msgstr`; never translate the English
     afresh.* The user-reported `etykiety`/`tagi` mismatch is one instance;
     `rocznik`→`kohorta`, `test`→`quiz`, `Branding`→`Wygląd` are the same bug.
   - renamed buttons (§3.1.3);
   - the wrong behavioural claims (§3.2) — the highest-value fixes;
   - label/name corrections (§3.3).
2. The **help topic title rename** (§4 below).
3. **Deleting the "Add user" claims** (findings §1.6) — `invitations.md:36-37`
   and `users-roles.md:7-8` document UI that has never existed
   (`accounts/urls.py` has no create route; "Add user" appears in no template).
4. **True-today wording** where a Class-3 gap makes a doc describe something
   unreachable (§3).
5. Resolving the one **SUSPECTED** finding (§3.4) before rewriting it.

**Out (with reasons):**

- **The 17 undocumented element types** (findings §2) → **slice 1b**. Correcting
  wrong prose and authoring 17 new element sections × 2 languages are different
  jobs: one is mechanical and verifiable against the audit, the other needs
  product understanding and prose review. Combined they make an unreviewable PR.
- **All product fixes** (findings §1) → issues (§3). Decision 2026-07-17: keep
  the docs PR docs-only. Notably this excludes granting teachers
  `add_group`/`change_group` — an access widening whose blast radius is
  documented in `[[access-widening-reachability-tests]]`.
- **Any anti-rot mechanism.** Decision 2026-07-17: the app is near
  feature-complete and a re-audit is planned before release; re-running the audit
  costs ~20 minutes. See findings §4.

## 3. Class-3 gaps: what the docs say *today*

The audit found **five** places where the doc is right and the **product** is
wrong (findings §1.1–1.5). Each becomes a GitHub issue carrying the audit's
citations. But slice 1a must still leave the doc saying something true *now*.

(Findings §1.6, the "Add user" claims, sits in that section because it documents
UI that never shipped — but it *is* doc-fixable, so it is handled in §2.3 above,
not here.)

Decisions:

| Gap | Issue | What the doc says in 1a |
|---|---|---|
| `collection_create` has no caller (findings §1.1) | file | **Drop the create claim.** Document editing only: My groups → a collection → **Edit** (`collection_detail.html:8`). Do not document a button that does not exist. |
| Teachers 403 on group create/edit (§1.2) | file | **Keep the topics filed under TEACHER; state the gating.** Add an explicit line: editing group membership requires Course Admin or Platform Admin; teachers see groups read-only. Re-filing the topic is a product/IA decision, deferred to the issue. |
| Quiz review unreachable for teachers (§1.3) | file | **Describe the real path**: the **Quiz review** button in the course builder (`_course_panel.html:7`), noting it requires course-manage access. Do not invent a teacher path. When the issue lands (PR #72's pattern, same partial), this reverts to one line. |
| `Multi-select grid` untranslated (§1.4) | file | Nothing — 1b documents the element; the msgstr is a code fix. |
| `seed_demo_course` broken image (§1.5) | file | Nothing — slice 2 concern. |

**Rationale for the quiz-review call:** it is the least satisfying option and
worth stating plainly. A TEACHER-filed topic will describe an entry point most
teachers cannot use. The alternatives are worse: inventing a path is false, and
omitting the entry point leaves a reader stranded. The doc will be *true*, and
the issue makes it *useful*. This is the same defect PR #72 fixed for the
Analytics link in the same partial, so the fix pattern already exists.

## 4. The topic-title rename

`core/help.py:148` registers the Teacher topic as `_("Notes & tags")`, whose PL
msgstr is `"Notatki i etykiety"` (`django.po:219`) — the **only** one of the 22
titles carrying the terminology bug (verified: all 22 have translations).

**Rename it to `_("Tags & notes")`.** One change fixes three things:

1. **Terminology** — kills the last `etykiety` title.
2. **Word order** — matches the product's own nav (`base.html:77`).
3. **Cost** — `msgid "Tags & notes"` **already exists** (`django.po:2796-2797` →
   `"Tagi i notatki"`), referenced by `base.html:77` and `my_tags.html:7`.
   `core/help.py:148` simply becomes a third reference. **No new translation is
   authored**, and `msgid "Notes & tags"` drops out.

**Keep the slug `notes-tags`** and the file paths. The slug is a URL segment and
the target of five inbound PL cross-links; renaming it would break bookmarks for
no gain. Slug ≠ title is already normal in this registry (e.g. slug
`create-a-course`, title "Creating a course").

**Mechanics / gotchas:**

- Removing a msgid means running `makemessages`. Per `[[uv-run-tooling]]`,
  watch the **fuzzy-flag gotcha** — inspect the diff, do not accept fuzzies blind.
- Per `[[course-export-import-status]]`: **run the i18n catalog tests in the DoD
  whenever a build removes translatable strings.** This build removes one.
- The existing translation-assertion test derives titles from `TOPICS`, so the
  rename is covered automatically: `"Tagi i notatki" != "Tags & notes"` passes
  the PL≠EN guard.

## 5. Approach

The audit is a per-finding worklist with `file:line` on both sides, so the work
is mechanical: **apply findings §3, topic by topic, EN and PL together.**

- **Work per topic, not per sweep.** Both files of a topic in one edit pass keeps
  EN/PL parity verifiable — the audit confirms every `.pl.md` is a
  section-for-section mirror, so every EN fix has exactly one PL counterpart.
  Two known asymmetries to preserve deliberately (findings §4): PL `users-roles`
  is *worse* than EN, PL `notifications` and `cohorts` are *better*.
- **Every PL label is a `msgstr` lookup, not a translation.** For each bolded PL
  UI string: find the msgid the EN doc quotes, use its `msgstr` verbatim. This is
  the discipline whose absence caused ~20 findings.
- **Verify before rewriting.** The audit cites truth for each finding; where a fix
  needs wording beyond the citation (e.g. the 5 colour bands), read the source
  first. One finding is SUSPECTED (§3.4) — confirm or drop it.

## 6. Files touched & DoD

**Touched:** 44 files under `docs/help/**`; `core/help.py` (one line);
`locale/pl/LC_MESSAGES/django.po` (regenerated).

**Not touched:** any view, template, model, or permission.

**Definition of done:**

1. Every Class-1 finding in findings §3 is applied or explicitly disputed in the
   PR description (the audit is the checklist; a finding is not silently dropped).
2. `uv run pytest` green (full suite), including the help tests and the **i18n
   catalog tests** (§4).
3. `uv run ruff check` + `uv run ruff format --check` clean
   (per `[[sis-webhook-guide-status]]`, `--check` is separately required).
4. `/help/` renders every topic in EN and PL without error — the renderer reads
   from disk and **fails loud** on a missing file (`core/help.py:1-4`), so a
   broken path is a 500, not a blank.
5. Issues filed for every Class-3 gap, each carrying its audit citations.
6. No `docs/help/**` file contains a string from the findings §3.1.2 table's
   left-hand column (manual grep; not a committed test, per the §2 decision).

**Risks:**

- **`django.po` is a merge-conflict hotspot.** The live
  `feat/student-practice-state` worktree may add strings. Sequence this slice
  around that branch's merge, or expect to regenerate.
- **Scale.** 44 files, ~80 findings. The risk is a silently skipped finding, which
  DoD #1 addresses by making the audit the checklist.

## 7. Slice map

| Slice | Scope | Status |
|---|---|---|
| **1a** | Correct the drift (this doc) | designed |
| **1b** | Document the 17 missing element types | not started |
| **2** | Screenshot substrate: deterministic seed + Playwright capture + static/markdown plumbing (EN/PL × light/dark), proven on 2–3 topics | not started |
| **3** | Illustrate the remaining topics | not started |
| — | Class-3 product gaps (findings §1), one branch each | issues to file |

**Why 1a is first:** screenshots pin a doc to reality. Shooting them against text
we know is wrong bakes in the error. The audit's own trigger — the user noticing
`etykiety` — is a case in point: a screenshot of that page would have shown
"Tagi" next to prose saying "etykiety".
