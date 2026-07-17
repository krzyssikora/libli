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

- **Login-capable users (verified).** Keep `demo_student`. Add a **Course-Admin** user who can open
  the builder, plus **at least 3** additional students (these are the group's members, below) to
  populate analytics. **Pin the builder-authorization
  mechanism explicitly:** course access in this project is governed by `is_staff` (and
  `accessible_courses` / `Group.teachers`), *not* by merely being a teacher — a `make_teacher`-style
  user without `is_staff` is redirected/403'd from the builder, which would make the capture's
  selector wait time out. The seed therefore gives the capture user `is_staff=True` (the Course-Admin
  path the `course-admin/builder` topic documents); the plan confirms whether course ownership or
  `Group.teachers` membership is additionally required for the specific builder URL. The seed must
  actually establish whatever CA↔demo-course relationship the builder URL needs, and a **fast
  (non-e2e) test asserts the seeded CA is authorized for the builder view** (it returns 200, not
  302/403) — pinning this load-bearing precondition in CI rather than discovering it only when
  capture's selector wait times out.
  Because the capture logs in through the **real allauth login form** (which rejects unverified
  accounts), every login-capable user must be a **verified allauth user**: the seed creates a
  **primary, verified `allauth.account.models.EmailAddress`** (`primary=True, verified=True`) for
  each, with an email the login form can authenticate against. (`force_login` is *not* the reason
  verified users are needed — it bypasses verification entirely; the real reason is that the
  capture deliberately drives the real form flow, the same reason the e2e suite uses
  `make_verified_user`.) The capture user's `User.theme` is set to `"light"` and `User.language` to
  `"en"` so the server resolves light theme and English chrome deterministically without relying on
  the UI toggle or an implicit default. Passwords come from a **single module-level constant** in
  the command, reused for all demo users (mirroring the existing `demo_student` password rather than
  scattering new literals) — mind the project's "no new password literals / GitGuardian" note and
  reuse or explicitly annotate the constant.
- **Diverse element types (leaf only).** Extend the lesson tree to cover a representative spread of
  **leaf** Content and Interactive element types (e.g. table, callout, and a self-check/interactive
  widget) on top of today's Text/Math/Iframe/Video/Image, so builder / content-editors /
  interactive-elements / quiz-editors surfaces show real variety. **Container elements that nest
  children (tabs, columns) are deliberately excluded from this slice's seed:** the existing
  `_upsert` helper reconciles exactly one leaf join-row per (unit, model), and idempotently seeding
  a container's nested children is materially more complex. Nested containers are deferred to slice
  3, which can add an idempotent nested-seeding helper if a screenshot needs them.
- **A graded quiz.** One quiz unit with a few question types plus **≥1 student submission**
  (attempt + graded result), so quiz-editors and quiz-review have real data. Each new row family is
  created through an **idempotent natural key** so a rerun adds nothing: the attempt via
  `get_or_create` on `(student, quiz unit)`, the graded result via `get_or_create` keyed on the
  attempt/`(student, gradeable)`. The plan confirms the exact model fields; the invariant is that no
  attempt/result row uses a bare `create()`.
- **A group with grades.** A group/cohort with several enrolled students and recorded results, so
  teacher analytics / drill-down / gradebook-export render a **populated** matrix rather than an
  empty state. The group has **≥3 enrolled students, each carrying its own recorded result**. Group
  membership is added through the idempotent M2M relation; each recorded grade is reconciled via
  `get_or_create` on `(student, gradeable item)`. A rerun adds nothing. **Crucially, the group
  members' results must land on the course's actual gradeable(s)** (e.g. the seeded graded quiz), not
  on some unrelated item — otherwise the matrix renders empty despite grades existing. In fact
  **these "recorded results" ARE the group members' own attempts+results on the seeded graded quiz**:
  the quiz and the group reference the same gradeable and the same student set (each group member
  gets its own idempotent attempt+result), so "graded quiz submission" and "group grade" are **one
  data family, not two**. A seed test asserts the intersection is non-empty (a group member with a
  result on a course gradeable). (Exact model/field names → plan.)
- **Fix the broken image (finding §1.5).** Ship a small **committed source PNG** inside the
  `courses` app (a seed asset, tracked in git) and have the seed **materialize** it into MEDIA so
  the demo image actually renders wherever the seed runs, replacing the hardcoded broken path.
  **Materialization must be idempotent:** `FileField.save()` routes through
  `Storage.get_available_name`, which appends a random suffix when the target name already exists —
  so a naive `.save()` writes a new `demo_<rand>.png` and mutates the row on every rerun. Guard it:
  materialize only when the asset has no file or its file is missing on disk, and pin the
  `MediaAsset` to a stable name (skip-when-present, or delete-then-save), so repeated runs converge
  to one file. MEDIA stays gitignored / DEBUG-only; the committed *source* is the durable thing.

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
- **Unresolvable target = fail loud, caught in CI.** Under `CompressedManifestStaticFilesStorage`
  (production), `static()` raises `ValueError: Missing staticfiles manifest entry` for a path not in
  the manifest, so a mistyped or uncollected `static:` reference would 500 the help page in
  production — and *test settings use plain, non-manifest storage*, where `static()` does **not**
  raise, so a render-only test would miss it. This slice therefore adds a **backend-agnostic
  coverage test** (see Testing) that scans every help topic for `static:` references and asserts
  each resolves to an existing file via `staticfiles.finders.find`. That catches authoring typos in
  CI regardless of storage backend; the production fail-loud behavior is accepted by design, since
  help content is repo-authored and gated by that test.

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
2. **Fixes every determinism knob:** viewport `1280×800`, light theme (seeded `User.theme="light"`
   + `page.emulate_media(color_scheme="light")`), English locale (seeded `User.language="en"`, no
   language switch), and `reduced_motion="reduce"` so animations are instant.
3. Logs in as the seeded Course-Admin via the **real allauth login form** (the established e2e
   `_login` pattern), navigates to the builder for the demo course **via its fixed slug
   (`demo-course`, pinned by the seed)** so the target URL is deterministic, and **waits on stable
   selectors** (never sleeps) before capturing.
4. Writes the PNG **into the source tree** at `core/static/core/img/help/…` (regeneration, not a
   temp dir), so the output is what gets committed. The output path is **anchored to the repo root**
   (via `settings.BASE_DIR` / `Path(__file__)`), never a bare cwd-relative string, since pytest's
   working directory is not guaranteed to be the repo root. **Capture extent is pinned:** the shot is
   an **element-clipped `locator(...).screenshot()` on the builder's content/tree container** — not a
   bare viewport clip (which would silently truncate a tree taller than 800px) and not `full_page=True`
   unless the plan finds the container clip insufficient; a content-scoped shot is the most
   deterministic and avoids below-fold/lazy surfaces. The plan pins the exact locator.

**Isolation requirement (load-bearing):** the capture module must **never run in the default
(unit) CI job or the e2e CI job** — it launches a browser and rewrites committed files. The
recommended mechanism is a **non-`test_`-prefixed filename** (e.g.
`tests/capture_help_screenshots.py` with a `test_`-named function inside): pytest does not
auto-collect it under any normal run, but `uv run pytest tests/capture_help_screenshots.py`
collects it explicitly to regenerate — a behavior the plan must **empirically verify** (see Testing),
since explicit-path collection of a function in a file that doesn't match `python_files` depends on
pytest's collection rules and project config. (Acceptable alternative: a dedicated `capture` pytest marker, excluded from **both** CI invocations
— `-m 'not capture'` on the default/unit job **and** on the e2e job — since a `capture`-marked,
`test_`-prefixed file would otherwise be auto-collected and run by the *default unit job*, not just
e2e. The **constraint** — never runs in either CI job, runs on explicit invocation — is fixed; the
plan picks the mechanism.) The exact
regeneration command is documented in the module and referenced from the plan.

### 5. PoC illustration + proof

- Embed one screenshot in **`docs/help/course-admin/builder.md`** (EN only) via the `static:`
  sentinel. The PL sibling (`builder.pl.md`) is left un-illustrated (slice 3). Help markdown is not
  in the gettext catalog, so this adds no `.po` churn.
- The Course builder is chosen for the PoC because it is server-rendered and stable (lowest
  capture fragility) and directly shows off the "diverse element types" seed.
- **Verify what the builder actually renders (load-bearing).** The MEDIA-serving mechanism, the
  no-broken-image guard, and the PoC's "shows off diverse elements" value all assume the builder page
  requests the demo `ImageElement`'s `<img>` and visibly displays element content. The plan must
  confirm this against the running builder and resolve to one of: **(i)** the builder renders the
  image → the MEDIA-serving + response-listener guard are exercised for real; **(ii)** the builder
  shows element cards / type labels without rendering the image → that still demonstrates element
  variety (acceptable PoC value), the response-listener guard applies to whatever image requests the
  page *does* make, and the §1.5 image fix is validated instead by the seed test's materialized-file
  assertion (and, if desired, a render check on the lesson/taking view); or **(iii)** the builder
  shows neither content nor a usable request → pick a builder preview/split-pane or a lesson (taking)
  view that renders content as the PoC target. The plan states which case holds and wires the guard
  accordingly — the guard is only a meaningful gate once **≥1 MEDIA image request is confirmed** on
  the captured page.

## Data flow

```
seed_demo_course (fixed data, incl. committed PNG → MEDIA)
        │
        ▼
capture harness  ──drives──▶  live_server UI  (builder, CA user, light, EN, 1280×800)
        │
        │ page.screenshot(...)
        ▼
core/static/core/img/help/builder-tree.png   (committed to the repo)
        │
        │ referenced by
        ▼
docs/help/course-admin/builder.md:  ![alt](static:core/img/help/builder-tree.png)
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
  render, theme resolution) must be pinned, not tolerated. **Time/date-derived UI is a further
  knob:** seeded attempts/results carry timestamps, so any surface rendering relative or absolute
  dates (quiz / analytics views, which slice 3 captures) must use **fixed seeded datetimes**. **The
  plan verifies** the builder view renders no date/time text (and if it does, applies the
  fixed-seeded-datetime knob to the builder too), rather than assuming absence; slice 3's
  time-bearing surfaces certainly will need it.
- **Determinism is scoped to one capture environment.** The knobs pin *within-run* reproducibility
  (for the guard and a stable shot); they do **not** guarantee byte-identical PNGs across machines,
  since OS font rendering and GPU rasterization differ. Regenerating on a different OS yields a
  spurious git diff — expected and acceptable, not a bug. Slice 3 (which recaptures against the same
  seed) should regenerate in a consistent environment; the plan notes the recommended one.
- **MEDIA is DEBUG-only served — the capture must serve it explicitly.** `config/urls.py` serves
  `MEDIA_URL` only under `DEBUG`, and `live_server` runs with `DEBUG=False`, so a MEDIA-backed
  `<img>` (like the demo image) would 404 during capture and produce exactly the broken image the
  DoD forbids. The harness must therefore **serve MEDIA during capture** via a concrete mechanism
  the plan implements — e.g. a capture-only urlconf that adds a `static(MEDIA_URL,
  document_root=MEDIA_ROOT)` route, or serving `MEDIA_ROOT` through WhiteNoise for the live server —
  **and** guard against a silent regression: the capture attaches a Playwright response listener and
  **fails if any image request on the captured page returns HTTP ≥ 400**. A broken image in the PoC
  is a slice failure, not cosmetic.
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

## Definition of done

Where earlier sections say "the DoD", they mean this list:

- The enriched `seed_demo_course` creates — **idempotently** — the verified users (Course-Admin
  with `is_staff` + students), diverse leaf elements, a graded quiz with ≥1 attempt/result, and a
  group with grades; the demo image is materialized to a **stable** MEDIA file (finding §1.5 closed).
- The `static:` sentinel resolves through `static()`; the renderer rewrite is unit-tested and leaves
  ordinary URLs untouched.
- One committed screenshot at `core/static/core/img/help/builder-tree.png`, embedded in
  `docs/help/course-admin/builder.md` (EN), captured with **no broken image** (the capture
  response-listener guard passed).
- Every Testing item below passes; the full non-e2e suite, `ruff`, and the i18n catalog gates are
  green; the capture module is excluded from both CI jobs yet collectable on explicit invocation.
- **Ordering:** proof test #2 and the coverage scan #6 stay **red until the one-time capture run
  produces and commits `builder-tree.png`** — that natural red is the desired falsifiable signal, not
  a failure. The PoC image must be captured and committed before those two tests can pass.

## Testing

All fast tests run in normal (non-e2e) CI. Only the capture module needs a browser, and it is
never collected by CI.

1. **Renderer unit test** (`tests/test_help.py` or sibling): `render_markdown_doc` rewrites a
   `static:`-prefixed image `src` to the `static()`-resolved URL, and leaves ordinary URLs
   (`http(s)://…`, `/…`) untouched.
2. **PoC proof test** (fast, non-e2e): the rendered HTML of the Course builder help topic contains
   an `<img>` produced from the `static:` sentinel, and the referenced asset **exists on disk**.
   Because `static()` returns a *URL*, not a path, the test bridges to disk by taking the rel path
   from the **raw `static:` markdown reference** (strip the `static:` prefix — never from the rendered
   `/static/…` `src`, which is content-hashed under manifest storage) and asserting
   `staticfiles.finders.find(rel_path)` returns an existing file — backend-agnostic (works under both
   test's plain storage and production manifest storage). This exercises the
   **reference→render→file-exists** tail without a browser; the seed link is covered by Testing #3
   and the capture link only by the one-time manual regeneration run.
3. **Seed unit tests** (extend `tests/test_seed_demo_course.py`): assert the new users (each with a
   verified primary `EmailAddress`, CA with `theme="light"` / `language="en"`), the diverse leaf
   elements, the quiz + attempt(s) + graded result, the group + students + grades, and the
   **materialized demo image file** (bytes written, `MediaAsset.file` names an existing file). Assert
   idempotency by **file identity, not just row counts**: a second `call_command` run leaves the same
   `MediaAsset.file` name (no `demo_<rand>.png`) and adds no attempt / result / grade / element rows.
   These file-existence / idempotency assertions **override `MEDIA_ROOT` to a per-test temp
   directory** so they are hermetic and never pollute shared on-disk state. Additionally, **sweep for
   and update any existing test or e2e that asserts the demo seed's current shape** (element /
   student / enrollment counts, "no quiz", "no groups"): the enrichment changes those counts, and per
   the project's count-assert history they must be updated, not merely supplemented.
4. **Collection checks (both directions)**: assert the capture module is **not** collected by a
   default `pytest` run nor by `-m e2e`, **and** that explicit invocation
   (`pytest tests/capture_help_screenshots.py`) **does** collect the capture function — the positive
   check guards against the regeneration command silently collecting zero tests. If the plan cannot
   empirically confirm the positive collection with the non-`test_`-prefixed mechanism, it falls back
   to the marker-based alternative, whose collection semantics are unambiguous. These checks **shell
   out to `pytest --collect-only` in a subprocess** and assert on the collected node list — an
   in-process test cannot reliably observe another collection.
5. **Existing suites stay green**: the `tests/test_help.py` TOPICS parametrization already
   auto-covers `builder.md`; the full non-e2e suite, `ruff`, and the i18n catalog gates must remain
   clean.
6. **`static:` coverage scan** (fast, non-e2e): for every help topic, render its **raw markdown with
   the `static:` rewrite disabled** (or parse the markdown to extract image nodes) and collect the
   `<img>` `src` values that begin with `static:`. This naturally excludes a topic that merely
   *documents* the sentinel in prose or a fenced code block — those render as text / `<code>`, not an
   `<img>`, so they yield no `static:` src (there is no *rendered* `<img src="static:...">` after the
   normal rewrite, so the scan must operate on this pre-rewrite form). Assert each collected sentinel
   resolves to an existing file via `staticfiles.finders.find` (rel path = the sentinel minus its
   `static:` prefix). This is the backend-agnostic guard from Component 2 that catches a typo'd or
   uncollected reference in CI before it can 500 a production page under manifest storage; it also
   protects slice 3's additions.

7. **CA builder-authorization test** (fast, non-e2e): assert the seeded Course-Admin can reach the
   demo-course builder view (HTTP 200, not 302/403), pinning the course-scoped access precondition in
   CI so a missing CA↔course relationship fails fast instead of only surfacing as a capture selector
   timeout.

The capture harness itself is exercised by being **run once** to produce the committed PoC image;
its correctness is evidenced by the committed screenshot and by proof test #2 passing against it.
