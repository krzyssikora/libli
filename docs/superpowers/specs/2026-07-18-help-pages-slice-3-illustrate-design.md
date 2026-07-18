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
    teacher topics) or `"demo_admin"` (platform-admin; covers the 11 PA topics). Caveat:
    the seven TEACHER-role topics are shot as a CA who *owns* the course. For a teacher
    topic whose surface differs between a plain teacher and an owner/CA (e.g. teacher
    collection analytics vs. the owner's `manage_analytics`), the plan confirms the CA-owner
    render matches the documented teacher view, or captures via the teacher-scoped route.
  - `url` — a **callable resolved at capture time** (after seeding), not a static string:
    it returns the path via `reverse(route_name, kwargs=...)` where the kwargs come from
    objects looked up by **stable keys** (course slug, unit title, group name, username) —
    never a hardcoded pk. Six target routes take an auto-increment `int` pk (`lesson_unit`,
    `manage_editor`, `manage_review_submission`, `manage_analytics_student`, `group_detail`,
    `collection_detail`); those pks are unknown at module-import time and are not stable
    constants, so **no captured URL may embed a literal pk**. Slug-only routes may still use
    a plain string.
  - `wait_selector` — element that must be visible before shooting.
  - `clip_selector` — element to element-clip (keeps shots tight and stable); `None`
    means full viewport.
  - `prep` — optional `prep(page)` callable, run **after** login + `goto` +
    `wait_selector` and **before** the screenshot, for on-page Playwright interactions
    (e.g. expand a drill-down row). It receives the Playwright `page` and nothing else.
    Per-shot DB differences live in the seed, not here; no shot needs a DB mutation at
    capture time (the `onboarded` flag is irrelevant — see Component 2).
- **Two locale passes.** `seed_demo_course` runs **once before** the locale loop; the
  per-pass `language` mutation happens after seeding (the seed's `_user` helper hardcodes
  `language="en"`, so reseeding *inside* the loop would clobber the pass locale back to EN
  and silently render EN chrome — do not reseed per pass). Then for `locale in ("en",
  "pl")`: set every demo user's `language` field to `locale`, and for each shot log in
  fresh as its `login_as` (the login signal writes `session[SESSION_KEY] = user.language`,
  and `SessionLocaleMiddleware` renders from it — so the whole UI renders in `locale`),
  navigate, wait, element-clip to `core/static/core/img/help/<name>.<locale>.png`.
  **Before each login the harness must clear the session** (explicit logout or a fresh
  Playwright browser context): navigating to `/accounts/login/` while already authenticated
  as the previous shot's user redirects away without re-submitting, so the `user_logged_in`
  signal never fires and the session keeps the wrong user and stale `_language`. A clean
  session per shot guarantees the signal re-fires and sets the correct user + locale. The
  simplest robust mechanism is `page.context.clear_cookies()` on the existing page — it
  drops the session cookie while keeping the viewport, `emulate_media`, and the `bad_images`
  response listener (all page/context-scoped, set up once). Note the alternatives' wrinkles:
  allauth logout is **POST-only** (`base.html`'s logout is a `<form method="post">`), so
  navigating to a logout URL won't actually log out; and a fresh browser context per shot
  requires re-applying viewport + `emulate_media` + the response listener to each new page.
- **PL-locale falsifiability.** The coverage gate checks only the `.pl.png` filename, not
  the pixels — so if the PL locale silently fails to take (signal misfire, clobbered
  `language`), EN pixels would ship under `.pl.png` names with every gate green. To prevent
  this, in the **PL pass** the harness asserts, per shot **before** the screenshot, that
  `page.content()` contains a known PL chrome string, so a wrong-locale render fails the run
  instead of shipping silently. Constrain the choice: the string must be **ungated**
  (present for *both* the `demo_teacher` and `demo_admin` roles — everything under
  `{% if user.is_authenticated %}` with no perm block: the account-menu **"Log out"** /
  **"Settings"**, or the **"Tags & notes"** nav link), present on *every* captured surface,
  and genuinely differ EN vs PL. It must **not** be a perm-gated label (Studio / Groups /
  Admin — absent on some roles → false failure) nor the lang-switch `EN`/`PL` codes
  (locale-invariant → false green). Allow a **per-shot override** string for a surface that
  legitimately lacks the common chrome (e.g. the wizard's minimal layout).
- **Viewport / media:** 1280×800, `emulate_media(color_scheme="light",
  reduced_motion="reduce")`.
- **MEDIA serving.** Lesson-consumption captures render `ImageElement`s whose `<img>`
  points at `MEDIA_URL`, but `config/urls.py` only appends the media `static()` pattern
  under `DEBUG`, bound at import time — so flipping `DEBUG` at runtime does nothing. The
  harness activates a capture-only urlconf `tests/capture_urls.py` (re-exports
  `config.urls.urlpatterns` + unconditionally appends `static(MEDIA_URL,
  document_root=MEDIA_ROOT)`) via `override_settings(ROOT_URLCONF=...)` so MEDIA resolves.
  The plan adds a fast **smoke check** (one `MEDIA_URL` asset returns 200 under the capture
  urlconf) before the full run, so a mis-wired urlconf fails fast rather than as a
  broken-image cascade.
- **Broken-image tripwire** (from slice 2) is retained and now load-bearing: it proves a
  lesson shot actually rendered its MEDIA image rather than a broken icon. To stay a
  targeted MEDIA proof rather than a noisy whole-run failure, `bad_images` is
  reset/asserted **per shot** (not once for the entire multi-page run), and is scoped to
  image requests whose URL starts with `MEDIA_URL` (a network `response` has a URL, not a
  clip), so an unrelated 404 elsewhere — a favicon, an avatar — doesn't fail the
  regeneration.
- **Time determinism.** Time-bearing surfaces drift across regenerations unless the clock
  is pinned (the notifications list/bell render `created_at|timesince`; invitations render
  `created_at|date`/`expires_at|date`; the course list renders `updated|date`; the people
  list renders `last_login`). The harness freezes the wall clock to a fixed instant for
  the **whole** run — seed **and** every capture — via a time-freezing context, so
  `timezone.now()`, every `auto_now`/`auto_now_add` write during seeding, the `last_login`
  stamp set at login, `timesince`, and `|date` all render identical strings on every
  regeneration. Fixed absolute seed constants alone do **not** work: `timesince` is
  `now - created_at`, so a fixed `created_at` against a live `now` drifts — freezing `now`
  is what makes it constant. (The plan confirms a freezing lib is available; `live_server`
  renders in the test process, so freezing there reaches server-side rendering.)

### Component 2 — Seed enrichment (`courses/management/commands/seed_demo_course.py`)

All additions stay **fully idempotent** (get_or_create / the existing `_upsert`
discipline) — the command is run repeatedly by the harness and by other seed tests.

- **`demo_admin`** — a `PLATFORM_ADMIN` user (mirrors the existing `_user` helper +
  `set_user_role`). Requires importing `PLATFORM_ADMIN` from `institution.roles`
  (the seed today imports only `COURSE_ADMIN`); `set_user_role` sets `is_staff` + the role
  group. Password = the shared `DEMO_PASSWORD`. Language toggled per pass by the harness
  like the others.
- **Deterministic timestamps.** With the clock frozen for the run (Component 1), rows
  created during seeding receive deterministic `auto_now_add`/`auto_now` values
  automatically, so no per-field constant-setting is needed for those. The plan must still
  **enumerate every time field rendered on a captured surface** and confirm each is
  covered by the freeze — notification `created_at` (`timesince`), invitation
  `created_at`/`expires_at` (`date`), course `updated` (`auto_now` `date`), user
  `last_login` (set at login) — and for any field the freeze cannot reach, seed it
  explicitly or choose a state that reads e.g. "Never".
- **Per-surface state** so each PA/teacher page has something real to show:
  - a small set of **notifications** for `demo_admin` (the notifications topic is
    PA-gated, so its shot logs in as `demo_admin`) — covers the notifications topic + the
    bell. `created_at` is `auto_now_add`, so under the frozen clock every row would read
    "0 minutes ago"; backdate each row to a fixed offset before the frozen `now` via a
    **post-create `.update()`** (`auto_now_add` ignores create-time values), giving varied,
    realistic relative times;
  - one **invitation**, created **unaccepted** with `expires_at` strictly after the frozen
    `now` — the `people_invitations` surface filters to pending, unexpired invites
    (`accepted_at__isnull=True, expires_at__gt=now`), so it renders only if created under
    the freeze (e.g. via `create_or_refresh_invitation`, whose default expiry then lands in
    the future) (invitations topic);
  - a saved, **disabled OIDC/SSO config** (sso topic);
  - a **WebhookEndpoint** + one **WebhookDelivery** (integrations topic);
  - a **cohort** (cohorts topic);
  - **branding** fields set on the institution (branding-settings topic) — `get_site_config()`
    caches for 300s and drives nav/theme chrome, invalidated by a save signal; the seed
    must write branding in a way that fires that invalidation (a plain model `.save()`
    does), or the harness clears the cache after seeding, so chrome across all shots
    reflects the seeded branding;
  - a second **subject** if one example reads thin (subjects topic).
  - a representative **interactive self-check element** on a lesson unit (e.g. a Switch
    grid or a reveal-gate "Show more") for the interactive-elements topic — the seed
    currently holds none of the self-check family (only callout/spoiler/table are
    present), so the shot has nothing to show without this;
  - an **`ImageElement` co-located on the content-rich lesson unit** (the "Core lesson"
    that holds text/math/iframe/video/callout/spoiler/table) so the content-editors
    consumption shot renders a MEDIA image and the broken-image tripwire is load-bearing.
    Today the only image is on the separate "Bonus lesson" unit, so no single unit shows
    both content elements and a MEDIA image. Implement this by **reusing the existing
    shared `demo.png` `MediaAsset`** — the `_image` helper already filters+reuses by
    `course`+`original_filename`, so no second asset is created and
    `test_seed_materializes_demo_image_idempotently`'s `.get(original_filename="demo.png")`
    stays single (a distinct second `demo.png` asset would make it `MultipleObjectsReturned`).
  - a personal **note** (on a lesson block) and a personal **tag** (on a unit) for
    `demo_teacher`, so the tags-and-notes hub (`overview`) and `my_tags` render populated
    rather than empty-state (notes-tags topic);
  - a **Collection** (`owner=demo_teacher`, `course=demo-course`, `groups` ← Demo Group) —
    `Collection.owner` and `course` are non-null FKs so both must be set; `demo_teacher`
    owns demo-course so `collection_detail` is reachable — giving collection-scoped surfaces
    (`collection_detail`, and the teacher collection analytics if that is the surface the
    analytics topic documents) data (groups-collections topic);
  - a **`REVIEW`-marking (manual) question** on the demo quiz **plus a SUBMITTED
    submission** carrying an answered-but-unreviewed response to it. This is a firm
    requirement, not conditional: the slice-2 quiz is `AUTO`-only and all three submissions
    are finalized, so `manage_review_queue`'s awaiting list (which needs a
    `MarkingMode.REVIEW` element per `courses/review.py`) and `manage_review_submission`'s
    review rows both render **empty** without it. Carry the unreviewed submission on
    **`demo_student`** (enrolled, not in Demo Group, currently submission-less) — not
    s1/s2/s3 (already finalized) and not a new grouped student (that would break
    `test_seed_quiz_group_populate_analytics`, which asserts exactly 3 group members).
    `reviewable_students` grants the course owner all *enrolled* students, so `demo_student`
    is reachable. Seed it idempotently, ordered so `finalize_submission` includes the REVIEW
    element in `max_score`, and key the URL callable on `demo_student` + the quiz unit title
    (quiz-review topic).
  - Group + graded quiz + varied grades already exist from slice 2 (analytics,
    drill-down, roster, groups-collections, gradebook-export).
- **`onboarded`** needs no seeding or per-shot toggling. It defaults to **`False`**
  (`institution/models.py`, `core/services._DEFAULTS`) and the seed does not call
  `mark_onboarded`. The only first-run gate is in the **`home`** view (a PA who isn't
  onboarded and hasn't skipped is redirected to the wizard); **no shot navigates to
  `home`**, and the `setup` view renders regardless of the flag. So the wizard shot simply
  navigates directly to `setup`, and every other PA shot is unaffected. (The plan confirms
  no global "finish setup" banner appears on captured pages — none was found in the base
  templates.)

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
  naming across the whole set.) This rename also requires updating **`tests/test_help.py`**,
  whose `test_builder_topic_embeds_existing_screenshot` hardcodes `builder-tree.png` in
  both its rendered-HTML assertion and its `finders.find(...)` call — fold that builder-
  specific test into (or align it with) the new coverage gate (Component 4).
- Existing cross-links between topics are preserved.

### Component 4 — Coverage gate (a real test)

Harden slice 2's coverage scan into an assertion in the help test suite: for **every**
registered `Topic`, both the EN markdown and its `.pl.md` sibling contain at least one
`static:` image reference, and **every** referenced `static:` path resolves via
`django.contrib.staticfiles.finders.find` (proving the PNG is committed, not a dangling
reference). This mechanically enforces the "all 22 topics, both locales" goal and catches
a doc that references an un-regenerated image. Implementation notes:
- **Do not** use `localized_doc_path` for the PL branch — it falls back to the English
  base when the `.pl.md` is absent, so a missing Polish doc would render the EN file, find
  the EN image, and pass silently (the exact falsifiability trap the project guards
  against). Instead derive the PL sibling directly
  (`topic.path.removesuffix(".md") + ".pl.md"`), **assert that file exists on disk**, and
  render that exact path via `render_markdown_doc(..., resolve_static=False)`, reusing the
  rendered-HTML `<img src="static:...">` extraction (extends slice 2's EN-only scan).
- For each locale, additionally assert that **every** `static:` image reference in the doc
  (topics may embed more than one — "more where earned") carries the **matching locale
  suffix** (`.en.png` in `*.md`, `.pl.png` in `*.pl.md`), so a PL doc that reuses even one
  EN image is caught — mechanically enforcing the "own PL-locale image" rule for all shots,
  not just the first.
- This new gate **supersedes** the existing `test_all_topics_static_refs_resolve` and
  **absorbs** `test_builder_topic_embeds_existing_screenshot` in `tests/test_help.py` —
  remove the superseded scans so two overlapping coverage tests don't drift apart.

### Component 5 — Regeneration workflow

Update the harness docstring for the multi-shot / dual-locale workflow (install chromium
once; run the file by explicit path; it writes every `<name>.<locale>.png`). It stays out
of both CI jobs. No new CI wiring.

## Topic → surface mapping (spec-level; exact selectors finalized in the plan)

`demo-course` is the seeded slug; `demo_teacher` owns it. All `manage/courses/<slug>/...`
surfaces are reachable by the owner. Where a teacher-role topic documents a
collection/group-scoped analytics surface rather than the course-admin one, **the plan
verifies which surface the topic's prose actually describes** before wiring the URL
(see the teacher-analytics reachability history in memory). The route names in the table
are **bare shorthand**; the `url` callable's `reverse()` needs the full `app:name` namespace
(`courses:manage_analytics`, `grouping:collection_detail`, `notes:overview`, `tags:my_tags`,
`institution:setup`, `notifications:list`, `accounts:people_invitations`, …) — the plan
supplies the exact namespaced name per shot.

| Topic | Role / login | Target surface (route name) |
|---|---|---|
| builder | demo_teacher | `manage_builder` (redo, uniform naming) |
| content-editors | demo_teacher | `manage_editor` (lesson unit editor) + a lesson-consumption view (`lesson_unit`) rendering content elements incl. the MEDIA image |
| quiz-editors | demo_teacher | `manage_editor` on the demo quiz unit |
| interactive-elements | demo_teacher | a lesson/consumption view showing the seeded interactive self-check element(s) (added to a lesson unit by the seed — see Component 2) |
| media-manager | demo_teacher | `manage_media` (library) — possibly + upload panel |
| analytics | demo_teacher | analytics matrix (`manage_analytics` or the teacher collection analytics — plan verifies) |
| drill-down | demo_teacher | `manage_analytics_student` for `demo_s1` ("Ada Demo") / expanded matrix (`prep` expands that row) |
| quiz-review | demo_teacher | `manage_review_queue` + `manage_review_submission` on the seeded manual-marking submission (see review-queue note) |
| groups-collections | demo_teacher | `my_groups` / `group_detail` / `collection_detail` |
| roster | demo_teacher | the roster/membership region of `group_detail` — a **distinct roster-focused clip** (own `clip_selector`/alt) from the groups-collections shot, which shares the same page; plan verifies which region is "roster" |
| gradebook-export | demo_teacher | analytics page showing the export controls (`manage_analytics`; the export route itself streams a file) |
| notes-tags | demo_teacher | `overview` (tags-and-notes hub) / `my_tags` |
| create-a-course | demo_admin | `manage_course_list` / `manage_course_create` |
| export-import | demo_admin | `manage_course_export` / `manage_course_import` surface |
| users-roles | demo_admin | `people` (Users tab) |
| invitations | demo_admin | `people_invitations` — needs seeded invitation |
| branding-settings | demo_admin | `settings_branding` — needs branding set |
| sso | demo_admin | `settings_sso` — needs disabled OIDC config |
| integrations | demo_admin | `settings_integrations` — needs endpoint + delivery |
| subjects | demo_admin | `manage_subject_list` |
| cohorts | demo_admin | `cohort_list` — needs a cohort |
| notifications | demo_admin | `list` — needs notifications seeded for `demo_admin` |
| first-run-wizard | demo_admin | `setup` (navigate directly; no prep, no `onboarded` toggle) |

## Error handling / edge cases

- **Tab-panel surfaces:** use the **dedicated per-tab routes** — `settings_branding`,
  `settings_sso`, `settings_integrations`, `settings_notifications`; `people` and
  `people_invitations` — (or the `?tab=` query param the settings view honors via
  `_active_tab`), not an anchor guess. Wait on the tab's own content selector, not the
  page shell, so the clip captures the right panel.
- **Review-queue emptiness:** the AUTO-only baseline renders both review surfaces empty, so
  the seed **firmly** adds a `REVIEW` question + an unreviewed SUBMITTED submission
  (Component 2). The plan verifies `manage_review_queue` and `manage_review_submission` are
  both non-empty for the seeded state.
- **Streaming/download routes** (gradebook export, node export) have no HTML to shoot —
  the shot targets the page that offers the control, never the download response.
- **Idempotency:** every seed addition must survive reruns (the harness seeds once per run,
  but other tests call `seed_demo_course` too, and it must be re-runnable — slice 2 made all seed rows
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

1. Every registered topic has ≥1 committed screenshot in EN and PL — mechanically
   enforced by the coverage gate (Component 4). The plan enumerates the expected shot list
   per topic as a checklist; shots beyond the first are reviewer-judgment ("more where
   earned"), not gate-enforced.
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
