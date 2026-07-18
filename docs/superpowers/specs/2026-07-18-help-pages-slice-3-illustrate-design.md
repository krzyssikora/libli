# Help pages slice 3 — illustrate every remaining topic (design)

**Date:** 2026-07-18
**Initiative:** Help-pages refresh (slice 3 of 3). Slice 1a/1b corrected drift + documented
element types (PRs #145/#146); slice 2 built the screenshot substrate + a builder PoC
(PR #148). This slice illustrates the remaining topics.

## Goal

Every registered help topic carries at least one screenshot in **both** English and
Polish, captured deterministically from the seeded demo course. There are 23 topics
(5 course-admin, 11 platform-admin, 7 teacher). Builder is currently the only one
illustrated, and only in EN; it is redone here for naming uniformity, and the other 22
are new. Shot count is topic-driven: one hero shot by default, more where a topic
documents genuinely distinct screens (no fixed cap).

## Scope decisions (user-approved)

- **Coverage:** all 22 remaining topics (plus builder redo). Comprehensive.
- **Polish:** each Polish doc embeds its **own PL-locale** screenshot (PL UI chrome),
  not the English image. Every surface is captured twice.
- **Shots per topic:** one hero shot; more where earned; not capped at a fixed number —
  driven by how many distinct screens the topic covers.
- **Architecture:** a single declarative shot registry (option A), driven once per
  locale, backed by one enriched seed.
- **Mode:** light only. Dark-mode image variants are deferred (see Out of scope).

## Out of scope (explicit)

- The frontend-design pass on `core/static/core/css/doc-page.css` (the `**Term** —
  description` wall-of-`<p>` readability problem, and the per-element-type-icon idea for
  content-editors). Deferred to a later slice **after** images, per the user's standing
  decision. This slice must not touch `doc-page.css`.
- Dark-mode screenshot variants (a raster can't theme-adapt; light/dark image swapping
  belongs with the design pass above).
- Any product or access change. This slice is docs + capture harness + seed only.
  Product gaps discovered while illustrating are filed as issues, never patched here
  (per the initiative's standing rule — see PRs #145/#148).

## Architecture

### Component 1 — Capture harness (declarative registry)

`tests/capture_help_screenshots.py`, rewritten from the slice-2 single-shot form into a
data-driven, dual-locale capture. It remains a **regeneration tool, not a CI test**:
still not `test_`-prefixed at the module level for its data, and the runnable entry stays
a single `test_`-named function that pytest collects only on an explicit path (verified
both directions in slice 2). It is never `@pytest.mark.e2e`.

- **`SHOTS` registry:** a list of `Shot` descriptors. Each carries:
  - `name` — PNG stem (e.g. `analytics-matrix`); the harness appends `.<locale>.png`.
  - `login_as` — `"demo_teacher"` (course-admin owner + group teacher; covers all CA and
    teacher topics) or `"demo_admin"` (platform-admin; covers the 11 PA topics).
  - `url` — path to navigate to (built from a slug/pk against the fixed seed).
  - `wait_selector` — element that must be visible before shooting.
  - `clip_selector` — element to element-clip (keeps shots tight and stable); `None`
    means full viewport.
  - `onboarded` — default `True`; the first-run-wizard shot sets `False`.
  - `prep` — optional callable for per-shot state the seed can't hold globally (e.g.
    flip `onboarded`, expand a drill-down row before the shot).
- **Two locale passes.** For `locale in ("en", "pl")`: set every demo user's `language`
  field to `locale`, then for each shot log in fresh as its `login_as` (the login signal
  writes `session[SESSION_KEY] = user.language`, and `SessionLocaleMiddleware` renders
  from it — so the whole UI renders in `locale`), navigate, wait, element-clip to
  `core/static/core/img/help/<name>.<locale>.png`.
- **Viewport / media:** 1280×800, `emulate_media(color_scheme="light",
  reduced_motion="reduce")`.
- **MEDIA serving.** Lesson-consumption captures render `ImageElement`s whose `<img>`
  points at `MEDIA_URL`, but `config/urls.py` only appends the media `static()` pattern
  under `DEBUG`, bound at import time — so flipping `DEBUG` at runtime does nothing. The
  harness activates a capture-only urlconf `tests/capture_urls.py` (re-exports
  `config.urls.urlpatterns` + unconditionally appends `static(MEDIA_URL,
  document_root=MEDIA_ROOT)`) via `override_settings(ROOT_URLCONF=...)` so MEDIA resolves.
- **Broken-image tripwire** (from slice 2) is retained and now load-bearing: any image
  request returning >= 400 on a captured page fails the run. This is what proves a lesson
  shot actually rendered its MEDIA image rather than a broken icon.
- **Time determinism** comes from the seed (below), not from freezing wall-clock in the
  harness — so a doc author regenerating one shot gets the same relative-time strings.

### Component 2 — Seed enrichment (`courses/management/commands/seed_demo_course.py`)

All additions stay **fully idempotent** (get_or_create / the existing `_upsert`
discipline) — the command is run repeatedly by the harness and by other seed tests.

- **`demo_admin`** — a `PLATFORM_ADMIN` user (mirrors the existing `_user` helper +
  `set_user_role`). Password = the shared `DEMO_PASSWORD`. Language toggled per pass by
  the harness like the others.
- **Fixed datetimes** on time-bearing rows so relative-time / timestamp strings render
  stably across regenerations: notification `created` timestamps and quiz-submission
  timestamps set to fixed constants. (Rows whose only time display is derived from these
  become deterministic; the plan enumerates exactly which fields.)
- **Per-surface state** so each PA/teacher page has something real to show:
  - a small set of **notifications** for `demo_teacher` and/or `demo_admin` (for the
    notifications topic + the bell);
  - one **invitation** (invitations topic);
  - a saved, **disabled OIDC/SSO config** (sso topic);
  - a **WebhookEndpoint** + one **WebhookDelivery** (integrations topic);
  - a **cohort** (cohorts topic);
  - **branding** fields set on the institution (branding-settings topic);
  - a second **subject** if one example reads thin (subjects topic).
  - Group + graded quiz + varied grades already exist from slice 2 (analytics,
    drill-down, quiz-review, roster, groups-collections, gradebook-export).
- **`onboarded`** left `True` by default (so non-wizard PA pages behave normally); the
  wizard shot's `prep` flips it `False` for that capture only.

### Component 3 — Doc edits (all `docs/help/**/*.md` + `*.pl.md`)

Each topic markdown embeds its shot(s) at the relevant section via the existing sentinel:

```markdown
![<alt text in the doc's own language>](static:core/img/help/<name>.<locale>.png)
```

- Alt text is authored **in the doc's language** — EN alt in `*.md`, PL alt in `*.pl.md`.
- **No gettext/msgid churn:** alt text and image paths live in the markdown files, not in
  the translation catalog. Unlike slices 1a/1b, this slice adds no translatable strings —
  so no `makemessages`/`.po`/`.mo` work, and the i18n catalog gates are untouched.
- Builder migrates: `builder-tree.png` → `builder-tree.en.png`, add `builder-tree.pl.png`;
  update both `builder.md` and `builder.pl.md` references. (Uniform `.<locale>.png`
  naming across the whole set.)
- Existing cross-links between topics are preserved.

### Component 4 — Coverage gate (a real test)

Harden slice 2's coverage scan into an assertion in the help test suite: for **every**
registered `Topic`, both the EN markdown and its `.pl.md` sibling contain at least one
`static:` image reference, and **every** referenced `static:` path resolves via
`django.contrib.staticfiles.finders.find` (proving the PNG is committed, not a dangling
reference). This mechanically enforces the "all 22 topics, both locales" goal and catches
a doc that references an un-regenerated image.

### Component 5 — Regeneration workflow

Update the harness docstring for the multi-shot / dual-locale workflow (install chromium
once; run the file by explicit path; it writes every `<name>.<locale>.png`). It stays out
of both CI jobs. No new CI wiring.

## Topic → surface mapping (spec-level; exact selectors finalized in the plan)

`demo-course` is the seeded slug; `demo_teacher` owns it. All `manage/courses/<slug>/...`
surfaces are reachable by the owner. Where a teacher-role topic documents a
collection/group-scoped analytics surface rather than the course-admin one, **the plan
verifies which surface the topic's prose actually describes** before wiring the URL
(see the teacher-analytics reachability history in memory).

| Topic | Role / login | Target surface (route name) |
|---|---|---|
| builder | demo_teacher | `manage_builder` (redo, uniform naming) |
| content-editors | demo_teacher | `manage_editor` (lesson unit editor) + a lesson-consumption view (`lesson_unit`) rendering content elements incl. the MEDIA image |
| quiz-editors | demo_teacher | `manage_editor` on the demo quiz unit |
| interactive-elements | demo_teacher | a lesson/consumption view showing self-check elements (may need a seeded interactive element) |
| media-manager | demo_teacher | `manage_media` (library) — possibly + upload panel |
| analytics | demo_teacher | analytics matrix (`manage_analytics` or the teacher collection analytics — plan verifies) |
| drill-down | demo_teacher | `manage_analytics_student` / expanded matrix (`prep` expands a row) |
| quiz-review | demo_teacher | `manage_review_queue` / `manage_review_submission` |
| groups-collections | demo_teacher | `my_groups` / `group_detail` / `collection_detail` |
| roster | demo_teacher | group roster surface (`group_detail` — plan verifies which is "roster") |
| gradebook-export | demo_teacher | analytics page showing the export controls (`manage_analytics`; the export route itself streams a file) |
| notes-tags | demo_teacher | `overview` (tags-and-notes hub) / `my_tags` |
| create-a-course | demo_admin | `manage_course_list` / `manage_course_create` |
| export-import | demo_admin | `manage_course_export` / `manage_course_import` surface |
| users-roles | demo_admin | `people` (Users tab) |
| invitations | demo_admin | `people` (Invitations tab) — needs seeded invitation |
| branding-settings | demo_admin | `settings` (Branding tab) — needs branding set |
| sso | demo_admin | `settings` (SSO tab) — needs disabled OIDC config |
| integrations | demo_admin | `settings` (Integrations tab) — needs endpoint + delivery |
| subjects | demo_admin | `manage_subject_list` |
| cohorts | demo_admin | `cohort_list` — needs a cohort |
| notifications | demo_admin/demo_teacher | `list` — needs seeded notifications |
| first-run-wizard | demo_admin | `setup` — `prep` sets `onboarded=False` |

## Error handling / edge cases

- **Tab-panel surfaces** (settings Branding/SSO/Integrations, people Users/Invitations):
  navigate directly to the tab URL/anchor; wait on the tab's own content selector, not
  the page shell, so the clip captures the right panel.
- **Streaming/download routes** (gradebook export, node export) have no HTML to shoot —
  the shot targets the page that offers the control, never the download response.
- **Idempotency:** every seed addition must survive reruns (the harness reseeds each
  invocation; other tests call `seed_demo_course` too — slice 2 made all seed rows
  hermetic under a module-scoped `MEDIA_ROOT`; the new MEDIA-rendering captures rely on
  that same discipline).
- **PL fidelity:** if a PL surface still shows an English string, that is a real product
  i18n gap — file an issue, do not fake the screenshot (same rule as the drift audit).

## Testing

- The **coverage gate** (Component 4) is the primary automated guard and runs in the
  normal non-e2e suite.
- The **capture harness** is run manually to (re)generate images; a green run + a clean
  broken-image tripwire + a visual eyeball of a sample of shots (light, both locales) is
  the acceptance evidence. Committed PNGs are the durable artifact.
- Full non-e2e suite green; `ruff check` + `ruff format --check` clean.
- No i18n catalog change expected; confirm `makemessages` shows no new/obsolete/fuzzy
  entries as a negative check (guards against an accidental translatable string sneaking
  in).

## Definition of done

1. All 23 topics have ≥1 committed screenshot in EN and PL; shot count matches each
   topic's distinct screens.
2. `seed_demo_course` enriched (PA user + per-surface state + fixed datetimes), still
   idempotent; all existing seed tests green.
3. Capture harness rewritten to the declarative dual-locale form; runs green and
   regenerates every image; broken-image tripwire clean.
4. Coverage gate asserts every topic (both locales) embeds ≥1 committed `static:` image.
5. Full non-e2e suite green; ruff clean; no i18n catalog churn.
6. `doc-page.css` untouched; no product/access change in the diff.

## Notes for execution

Given the size (23 × 2 locales × topic-driven shots + substantial seed work), building
via `/pipeline` (as slice 2) is the suggested execution path, but that is decided after
the plan. The plan should split work into reviewable tasks — plausibly: harness +
capture-urlconf substrate; seed enrichment; then doc+shot tasks batched by role
(course-admin, teacher, platform-admin); then the coverage gate; then a whole-branch
regeneration + review.
