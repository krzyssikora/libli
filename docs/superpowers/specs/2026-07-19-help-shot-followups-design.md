# Help shot-quality follow-ups

Two committed-screenshot fixes that finish the help-pages refresh initiative (all
four content slices already merged: #145, #146, #148, #152, #154). Both were
deferred out of slice 3/4 as capture-harness/seed work rather than doc or CSS work.

## Purpose

1. **`demo.png` is a 16×16 placeholder.** The seed asset
   `courses/management/commands/seed_assets/demo.png` is 16×16, so wherever the demo
   course's shared image appears in a help screenshot it renders as a tiny speck.
2. **The roster shot illustrates the wrong thing.** `docs/help/teacher/roster.md`
   ("Roster management") is mostly about the **Course-Admin student picker** — the
   group edit form with a Cohort/Search-filtered checkbox list and an Added/saved
   counter — but its screenshot (`roster.en.png` / `roster.pl.png`) captures the
   read-only student name list on the group **detail** page. The illustration doesn't
   match the topic.

Goal: replace `demo.png` with a properly-sized illustrative diagram, re-point the
roster shot at the group edit form (the student picker), regenerate only the
affected committed PNGs, and add a guard so the tiny-image regression can't return.

## Architecture / components

### 1. New `demo.png` seed asset + generator

Replace `courses/management/commands/seed_assets/demo.png` (16×16) with a **~1200×800
(3:2)** PNG: a right triangle with labeled legs **a**, **b**, hypotenuse **c**, a
right-angle marker, and the caption **a² + b² = c²**, titled "Worked example", on a
light card using the brand palette (teal `#147E78` / amber `#C77B2A`, warm surfaces
per `core/static/core/css/tokens.css`). This fits both alt texts the seed uses for it
("Worked example diagram" for the Core lesson, "Decorative diagram" for the Bonus
lesson).

- **Generator:** a committed, deterministic Pillow script
  `courses/management/commands/seed_assets/make_demo_png.py` (Pillow 12.2 is a project
  dep) that draws the diagram and writes `demo.png` beside itself. Committing the
  generator keeps the asset reproducible/license-clean; the PNG itself is committed
  too (the repo is the deployment artifact — MEDIA is a dev-only dead end).
- **No seed logic change.** `seed_demo_course._image` references the asset by the
  literal filename `demo.png` and materializes its bytes into a `MediaAsset`; a larger
  file flows through unchanged. Keep the filename exactly `demo.png`.
- Use a bundled/DejaVu font or Pillow's default bitmap font — do **not** depend on a
  system font that may be absent in CI/other machines. The generator runs on demand
  (to regenerate the asset), not in CI.

### 2. Roster shot re-point (`tests/capture_help_screenshots.py`)

- **Route key.** Add `group_edit` to the `_u` resolver:
  `reverse("grouping:group_edit", kwargs={"pk": Group.objects.get(name="Demo Group", course=course).pk})`
  (mirrors the existing `group_detail` resolver).
- **SHOT change.** The current entry is
  `("roster", "demo_teacher", ("group_detail", {}), "ul.course-list", "ul.course-list")`.
  Change it to:
  - `login_as` → **`demo_admin`** (the seed's PLATFORM_ADMIN user). `demo_teacher` is a
    teacher + course owner but lacks `grouping.change_group`, and `group_edit` is
    gated by `@permission_required("grouping.change_group", raise_exception=True)` →
    it would 403. A PA passes `groups_manageable_by` (returns all groups). This also
    matches the doc, which states editing the roster "is a Course Admin's job."
  - route → `("group_edit", {})`.
  - wait selector → `[data-roster-list]` (the checkbox list; present once the picker
    renders).
  - clip selector → **`fieldset.roster:last-of-type`** — `group_form.html` has two
    `fieldset.roster` blocks (Teachers, then Students); the **Students** one (last) is
    the richer picker with the Cohort dropdown, name search, and Added/saved counter
    that the doc's "Picking students" / "Adding and removing" sections describe.
- **Doc alt text.** Update line 17 of `docs/help/teacher/roster.md` and
  `docs/help/teacher/roster.pl.md`: `![A group roster of students](static:…roster.en.png)`
  → an alt describing the picker (EN e.g. "The group edit form's student picker"; PL
  the faithful translation). The image path/filename stays `roster.en.png` /
  `roster.pl.png` so no other reference changes.

### 3. Regenerate only affected shots

`demo.png` renders in these SHOTS: **content-consume** (Core lesson, core-image),
**interactive** (Bonus lesson, bonus-image), **media-manager** (library grid), and
**content-editor** (Core lesson editor lists the image element); plus the re-pointed
**roster**. That's 5 shots × 2 locales (EN/PL) = **10 PNGs** under
`core/static/core/img/help/`.

To avoid churning the other ~48 committed PNGs with font/Chromium rendering drift from
this machine, add a small **`CAPTURE_ONLY` env-var allowlist** to the harness: when set
(comma-separated shot names), filter `SHOTS` to just those before capturing. Default
(unset) keeps the full run. Regenerate with
`CAPTURE_ONLY=roster,content-consume,interactive,media-manager,content-editor uv run python -m pytest tests/capture_help_screenshots.py`.
Commit only those 10 PNGs (+ the new demo.png + code/doc). Neighbour PNGs may render
slightly differently in fonts on this machine — that is why the allowlist exists;
leave them untouched.

### 4. Guard test

Add a falsifiable check (in `tests/test_help.py` or the seed's test module) that the
seed `demo.png` asset is a real image, e.g. open
`courses/management/commands/seed_assets/demo.png` with Pillow and assert
`width >= 400 and height >= 300`. Falsify: revert to the 16×16 asset → red. This
prevents the tiny-image regression from silently returning.

## Data flow

1. `make_demo_png.py` (run on demand) → writes `seed_assets/demo.png` (~1200×800).
2. `seed_demo_course` → `_image` reads those bytes into a `MediaAsset` for the demo
   course (Core + Bonus lessons), idempotently.
3. `capture_help_screenshots.py` (run on demand, `CAPTURE_ONLY` filter) → seeds under a
   frozen clock, drives Playwright as `demo_admin`/`demo_teacher`, writes the affected
   PNGs into `core/static/core/img/help/`.
4. Help topic pages embed those PNGs via the `static:` sentinel (unchanged);
   `test_every_topic_illustrated_both_locales` still passes (roster keeps EN+PL images).

## Error handling

- **`demo_admin` group access.** Confirm the seed's `demo_admin` is PLATFORM_ADMIN
  (it is — `seed_demo_course.py:101` creates it with `role=PLATFORM_ADMIN`) so
  `group_edit` renders 200, not 403. If a future seed change drops the PA, the capture
  raises on a non-200 — fail loud, not a silent blank shot.
- **Font availability.** The generator must not require a system font; use a bundled
  TTF or Pillow's default so regeneration works anywhere.
- **PNG determinism.** The harness is already deterministic (freezegun, fixed
  viewport). The `CAPTURE_ONLY` filter is the mechanism that keeps unaffected assets
  byte-stable in the commit (we simply don't regenerate them).

## Testing

- **Guard:** seed `demo.png` dimensions ≥ 400×300 (falsifiable — §4).
- **Existing (must stay green):** `test_every_topic_illustrated_both_locales` (roster
  still EN+PL illustrated), the seed tests (`_image` still materializes demo.png), and
  the capture-isolation tests (`tests/test_help_capture_isolation.py`,
  `tests/test_capture_urls.py`).
- **Manual verification (the real gate for a screenshot change):** after regenerating,
  visually confirm — new `demo.png` renders at a legible size in **content-consume** and
  **media-manager**; the **roster** shot shows the student picker (Cohort/Search
  filters + Added counter + checkbox list) — in both EN and PL. The capture harness is
  a regeneration tool, not run in CI, so the committed PNGs are the deliverable and
  eyeballing them is mandatory.

## Out of scope

- The pre-existing production `MEDIA_URL="media/"` relative-URL bug (filed as issue
  #153) — unrelated to these assets.
- Any change to unaffected help screenshots or topics.
