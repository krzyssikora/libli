# Help screenshot substrate

Slice 2 of the help-pages-refresh initiative. Slices 1a (PR #145) and 1b (PR #146) made the
in-app `/help/` docs *true* and *complete*; this slice builds the **plumbing that lets help
topics carry real, deterministic, committed screenshots**, and proves it end-to-end on one
topic. Bulk illustration of the remaining ~22 topics is deferred to slice 3.

## Purpose

Help topics today are text-only. Screenshots would make them far more useful, but there is no
substrate to produce or reference them:

- **The seed is too thin to screenshot.** `courses/management/commands/seed_demo_course.py`
  creates 1 subject, 1 course, 5 content nodes, 6 elements (Text×2, Math, Iframe, Video, Image),
  and 1 student with a single passive enrollment. It has **no quizzes, no groups, no additional
  students, no attempts, no grades, no analytics data** — so the surfaces the help topics
  describe (builder variety, quiz editors, analytics matrices) cannot be captured with realistic
  content.
- **Its one image is broken.** The seed's `ImageElement` points a `MediaAsset.file` at the
  hardcoded MEDIA path `courses/images/demo.png`, but no such file exists on disk and no bytes are
  ever written — a broken image (audit finding §1.5, owned by this slice).
- **There is no capture flow.** No durable, deterministic screenshot capture exists. The only
  precedent is a throwaway loop in the notifications-slice-3 plan that wrote PNGs to a temp dir and
  deleted them.
- **There is no way to reference a committed image from a topic.** The help renderer emits
  markdown `src` verbatim, and production serves static assets through WhiteNoise
  `CompressedManifestStaticFilesStorage` (content-hashed filenames), so a hardcoded `/static/…`
  path would 404 in production.

This slice closes all four gaps: a rich deterministic seed, a reproducible Playwright capture
flow, a committed static home for images, and a manifest-safe reference mechanism — validated by
illustrating the **Course builder** help topic with one real screenshot.

### Scope decisions (approved during brainstorming)

- **Deliverable:** the full substrate **plus one proof-of-concept topic** (Course builder),
  illustrated EN-only, light theme. Remaining topics → slice 3.
- **Seed richness:** all three of — diverse element types, a graded quiz with student attempts,
  and a group with several students and recorded grades.
- **Capture variants (PoC):** light theme only, English only. The harness is parametrized so
  slice 3 can capture other themes/locales without rework.
- **Reference mechanism:** a `static:` sentinel in the markdown, resolved at render time through
  Django's `static()`.

### Non-goals

- Illustrating the other ~22 help topics (slice 3).
- Dark-theme or Polish screenshot variants for the PoC.
- Any change to element/quiz/group **models** or migrations.
- Any CI job that captures screenshots automatically. Capture is a manually-invoked
  regeneration tool.

## Architecture / components

Five components, each independently understandable and testable.

### 1. Enriched `seed_demo_course` (the deterministic fixture)

Extend the **existing** `courses` management command rather than adding a separate capture-only
fixture. It is already `@transaction.atomic` and idempotent (`get_or_create` throughout) and uses
fixed, non-random data — which is *more* deterministic than factories and doubles as a richer dev
demo. Enrichment (all additive; existing behavior preserved):

- **Login-capable users (verified).** Keep `demo_student`. Add a **Course-Admin/teacher** user
  with edit access to the demo course, and enough additional students to populate analytics. All
  users that the capture logs in as must be **verified allauth users** (mandatory email
  verification blocks `force_login`; capture logs in via the real form). The capture user's
  `User.theme` is set to `"light"` so the server resolves light theme deterministically without
  relying on the UI toggle. Passwords are fixed constants, consistent with the existing
  `demo_student` password.
- **Diverse element types.** Extend the lesson tree to cover a representative spread of Content
  and Interactive element types (e.g. table, callout, tabs/columns, and a self-check/interactive
  widget) on top of today's Text/Math/Iframe/Video/Image, so builder / content-editors /
  interactive-elements / quiz-editors surfaces show real variety.
- **A graded quiz.** One quiz unit with a few question types plus **≥1 student submission**
  (attempt + graded result), so quiz-editors and quiz-review have real data.
- **A group with grades.** A group/cohort with several enrolled students and recorded results, so
  teacher analytics / drill-down / gradebook-export render a **populated** matrix rather than an
  empty state.
- **Fix the broken image (finding §1.5).** Ship a small **committed source PNG** inside the
  `courses` app (a seed asset, tracked in git) and have the seed **materialize** it into MEDIA via
  `MediaAsset.file.save(name, ContentFile(bytes))`, so the demo image actually renders wherever the
  seed runs. MEDIA stays gitignored / DEBUG-only; the committed *source* is the durable thing. This
  replaces the hardcoded broken path.

The command stays idempotent: re-running it converges to the same rich state without duplication.

### 2. `static:` sentinel rewrite (the reference mechanism)

In `core/help.py`'s render path (`render_markdown_doc`), after markdown → HTML, rewrite any image
`src` beginning with the literal `static:` prefix by stripping the prefix and resolving the
remainder through Django's `static()` (which respects the manifest storage in production). Topic
authors write plain markdown:

```markdown
![Course builder with the demo course tree](static:core/img/help/builder-tree.png)
```

which renders (dev) as `<img … src="/static/core/img/help/builder-tree.png">` and (prod) as the
content-hashed URL. The rewrite is:

- **Scoped to the sentinel** — only `src` values starting `static:` are rewritten; ordinary URLs
  (`http(s)://…`, root-relative `/…`) pass through untouched, so future external images are
  unaffected.
- **Small and pure** — a well-bounded transform on the rendered HTML string (or an equivalent
  markdown-tree hook), unit-tested in isolation.

The renderer's existing "trusted, unsanitized, repo-authored" contract is unchanged; this adds one
deterministic rewrite of a repo-authored sentinel.

### 3. Static home for screenshots

Committed screenshots live under **`core/static/core/img/help/`**, consistent with `core` already
owning the help CSS (`core/static/core/css/doc-page.css`). Referenced only via the `static:`
sentinel (never a hardcoded URL). This is the first `img/` folder under any static dir — a new but
convention-consistent location (`<app>/static/<app>/<type>/…`).

### 4. Capture harness (the deterministic Playwright flow)

A Playwright-driven pytest module that reuses the established e2e substrate (`live_server` +
pytest-playwright `page`, sync API, `@pytest.mark.django_db(transaction=True)` so committed rows
are visible to the server thread). It:

1. Seeds by calling the enriched command: `call_command("seed_demo_course")` — the same fixed data
   every run.
2. **Fixes every determinism knob:** viewport `1280×800`, light theme (seeded `User.theme` +
   `page.emulate_media(color_scheme="light")`), English locale (the default; no language switch),
   and `reduced_motion="reduce"` so animations are instant.
3. Logs in as the seeded Course-Admin via the **real allauth login form** (the established e2e
   `_login` pattern), navigates to the builder for the demo course, and **waits on stable
   selectors** (never sleeps) before capturing.
4. Writes the PNG **into the source tree** at `core/static/core/img/help/…` (regeneration, not a
   temp dir), so the output is what gets committed.

**Isolation requirement (load-bearing):** the capture module must **never run in the default
(unit) CI job or the e2e CI job** — it launches a browser and rewrites committed files. The
recommended mechanism is a **non-`test_`-prefixed filename** (e.g.
`tests/capture_help_screenshots.py` with a `test_`-named function inside): pytest does not
auto-collect it under any normal run, but `uv run pytest tests/capture_help_screenshots.py`
collects it explicitly to regenerate. (Acceptable alternative: a dedicated `capture` pytest marker
plus a one-line change to the e2e CI invocation to exclude it. The **constraint** — never runs in
either CI job, runs on explicit invocation — is fixed; the plan picks the mechanism.) The exact
regeneration command is documented in the module and referenced from the plan.

### 5. PoC illustration + proof

- Embed one screenshot in **`docs/help/course-admin/builder.md`** (EN only) via the `static:`
  sentinel. The PL sibling (`builder.pl.md`) is left un-illustrated (slice 3). Help markdown is not
  in the gettext catalog, so this adds no `.po` churn.
- The Course builder is chosen for the PoC because it is server-rendered and stable (lowest
  capture fragility) and directly shows off the "diverse element types" seed.

## Data flow

```
seed_demo_course (fixed data, incl. committed PNG → MEDIA)
        │
        ▼
capture harness  ──drives──▶  live_server UI  (builder, CA user, light, EN, 1280×800)
        │
        │ page.screenshot(...)
        ▼
core/static/core/img/help/builder-*.png   (committed to the repo)
        │
        │ referenced by
        ▼
docs/help/course-admin/builder.md:  ![alt](static:core/img/help/builder-*.png)
        │
        │ render_markdown_doc → static: rewrite → static()
        ▼
/help/builder/  page renders  <img src="/static/…(hashed in prod)…">
        │
        │ asserted by
        ▼
fast non-e2e proof test  (img present + resolved file exists on disk)
```

The seed is the single source of truth for both the **committed screenshot** (via the capture
harness) and the **dev demo**; slice 3 captures more views against the same seed.

## Error handling

- **Determinism failures are the primary risk.** The harness fixes viewport, theme, locale, and
  motion; it waits on selectors rather than sleeping; and it seeds via the fixed-data command, not
  random factories. Any nondeterministic surface encountered during capture (animation, async
  render, theme resolution) must be pinned, not tolerated.
- **MEDIA is DEBUG-only served.** `config/urls.py` serves `MEDIA_URL` only under `DEBUG`. If a
  captured view renders a MEDIA-backed image, the harness must ensure that image is served during
  capture (or the captured view must not depend on MEDIA rendering). The **builder PoC** must be
  verified to render **without a broken image** in the committed screenshot — a broken image in the
  PoC is a slice failure, not a cosmetic issue.
- **The `static:` rewrite must be correct under manifest hashing.** It resolves through
  `static()`, which uses the manifest in production; the proof test asserts the resolved path
  points at a file that actually exists, catching a mis-typed or missing image.
- **Capture must not pollute CI.** The isolation mechanism is verified: a normal `uv run pytest`
  run and the e2e job must **not** collect the capture module (no browser launch, no file
  rewrite). This is an explicit test/DoD check, not an assumption.
- **Idempotency.** Re-running the enriched seed must not duplicate rows or fail; existing
  `seed_demo_course` idempotency is preserved and extended to the new data.

### Gate discipline (carried from slices 1a/1b)

- **CRLF-safe patterns** in every string gate (`$`-anchors and `\n` fail on CRLF; use `\r?\n`).
- **`makemessages --no-obsolete`** if any translatable string moves. Expected impact: **none** —
  seed content strings and help markdown are not gettext catalog entries — but this is **verified**
  during the plan, not assumed.
- **Positive carve-out gates** and **`-z` match counts via `tr -cd '\0' | wc -c`** where used.
- No line number in any doc is authoritative; locate by searching the quoted string.

## Testing

All fast tests run in normal (non-e2e) CI. Only the capture module needs a browser, and it is
never collected by CI.

1. **Renderer unit test** (`tests/test_help.py` or sibling): `render_markdown_doc` rewrites a
   `static:`-prefixed image `src` to the `static()`-resolved URL, and leaves ordinary URLs
   (`http(s)://…`, `/…`) untouched.
2. **PoC proof test** (fast, non-e2e — the end-to-end gate): the rendered HTML of the Course
   builder help topic contains an `<img>` whose resolved `src` corresponds to a static file that
   **exists on disk**. This proves seed→capture→commit→reference→render without a browser.
3. **Seed unit tests** (extend `tests/test_seed_demo_course.py`): assert the new users
   (verified, CA with `theme="light"`), the diverse elements, the quiz + attempt(s) + graded
   result, the group + students + grades, and the **materialized demo image file** (bytes written,
   `MediaAsset.file` resolvable). Assert idempotency (second run adds nothing).
4. **CI-isolation check**: the capture module is not collected by a default `pytest` run nor by
   `-m e2e` (e.g. assert collection is empty for that path under those selectors, or an equivalent
   guard).
5. **Existing suites stay green**: the `tests/test_help.py` TOPICS parametrization already
   auto-covers `builder.md`; the full non-e2e suite, `ruff`, and the i18n catalog gates must remain
   clean.

The capture harness itself is exercised by being **run once** to produce the committed PoC image;
its correctness is evidenced by the committed screenshot and by proof test #2 passing against it.
