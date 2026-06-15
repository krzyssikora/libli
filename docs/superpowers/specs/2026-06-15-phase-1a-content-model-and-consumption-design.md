# Phase 1a — Content Model & Lesson Consumption: Design Spec

*Spec date: 2026-06-15. First slice of [Phase 1](../../roadmap.md#phase-1--content-model-authoring--lesson-consumption).
Builds on the completed Phase 0 foundation (custom user, RBAC Groups, i18n, the
[0d UI shell](2026-06-14-phase-0d1-ui-foundation-design.md)). Borrows patterns — not schema —
from the Packt "educa" app per [packt-review.md](../../packt-review.md) (esp. §3). Views numbered
per [view-inventory.md](../../view-inventory.md).*

## Goal

Ship a **demonstrable end-to-end learner vertical slice**: an admin builds a course (via Django
admin + a seed command), an **enrolled student reads a lesson**, and **progress is recorded**.
This establishes libli's content schema — the single most expensive-to-reverse decision in the
project — and proves the full render → consume → progress pipeline before Phase 2's quiz engine
and Phase 1b's bespoke authoring UI land on top of it.

## Phase 1 slice split (decided in brainstorming 2026-06-15)

Phase 1 is the largest phase; it is split into vertical slices, each its own spec → plan → build:

- **1a (this spec) — Foundation + consumption.** Content schema + 5 lesson element renderers +
  student consumption + progress. **Authoring is Django admin + a seed command** (the roadmap's
  "admin/fixtures as scaffolding" principle). End state: a real learner experience.
- **1b — Authoring UI.** Bespoke course-builder tree editor, unit/element editors, media manager.
- **HTML element slice** (still Phase 1) — the arbitrary-HTML element (course-wide CSS/JS,
  per-unit JS, MathJax/LaTeX) with its dedicated **security design**. Deferred out of 1a precisely
  because it executes author-supplied JavaScript; **not** out of Phase 1. Rides with 1b or stands
  alone — decided later.

## Foundational decisions (locked in brainstorming)

1. **Content i18n — monolingual per course (+ reserved seam).** Each `Course` declares one content
   `language`; all its elements are authored once in that language. EN and PL courses coexist on
   the same platform. The UI *chrome* still follows the user's EN/PL preference (Phase 0). The
   schema reserves a seam (per-type text on its own model) so true per-element translation can be
   added later without a rewrite — **not built now**.
2. **Element storage — GFK join-row + concrete per-type models** (educa's borrowed pattern). Chosen
   over single-JSON (loses validation + queryable gradeable fields for Phase 2/3) and MTI (needs
   `django-polymorphic` for mixed-list downcasting + join-per-access). GFK resolves the join-row
   directly to the concrete object — no downcast tax, no extra dependency.
3. **"Skippable" middle levels — author-time structural optionality.** The 6 levels are a *maximum*
   depth, not a required chain. A course uses only the grouping levels it needs; Unit (with
   Elements) is the only mandatory content-bearing level.
4. **Hierarchy shape — one uniform `ContentNode` tree.** A single self-referential model with a
   `kind` discriminator (`part<chapter<section<unit`), an invariant that a child's kind is strictly
   deeper than its parent's, and one `order` space per parent — giving skipping **and** interleaving
   (units and sub-containers under the same parent) for free. Adjacency list, no `mptt`/`treebeard`.
5. **Progress — per-element "seen" → auto-complete, with a no-JS fallback.** A lesson unit
   auto-completes when **all** its elements have been seen (`IntersectionObserver`); an
   always-present **"Mark as done"** plain-form button guarantees completion even with JS off or a
   tracking miss. Per-unit `completed` is binary (clean rollups for Phase 2/3); the seen-set drives
   the within-unit fraction. **Hard constraint:** a student who consumed the whole unit must never
   be left incomplete.
6. **`Unit.obligatory` drives required-vs-additional completion.** Completion rolls up over
   *obligatory* units only; "additional" units are tracked and shown (✓ / "+N additional") but do
   **not** block parent/course completion. An optional whole chapter emerges naturally by marking
   its units additional — no separate flag on grouping nodes.
7. **Enrollment — a thin `Enrollment` through-model**, admin-assigned, `source='manual'` now, with
   `group`/`self` reserved for Phase 3 grouping. The anchor for "My courses" and access gating.
8. **Element types in 1a — text, image, video, iframe, math** (5). HTML element deferred (see
   above). `quiz` unit_type is **modeled but inert** (renders a "Phase 2" placeholder).

## Success criteria (Definition of Done)

1. **Schema** exists as a new `courses` app: `Subject`, `Course`, `ContentNode` (the tree),
   `Element` (GFK join-row) + 5 concrete element models, `Enrollment`, `UnitProgress`. Migrations
   present; `makemigrations --check` clean.
2. **Invariants enforced** (model `clean()` + constraints): kind-depth nesting
   (`part<chapter<section<unit`, root any kind), units are leaves, `unit_type` set iff `kind=unit`,
   only units own elements, `OrderField` scoped per parent (incl. null-parent course-level
   siblings) and per unit, `unique(student,course)` / `unique(student,unit)`.
3. **Five element types render** via the `{% render_element %}` convention
   (`courses/elements/{model_name}.html`): text (sanitised rich text), image (`<figure>` +
   `figcaption` + `alt`), video (whitelisted URL **or** upload), iframe (whitelisted), math
   (client-side KaTeX). Each element is wrapped in `<section data-element-id="{pk}">`.
4. **My courses** (`GET /courses/`, login-required) lists only the user's enrolled courses.
5. **Course outline** (`GET /courses/<slug>/`) renders the `ContentNode` tree with per-node
   progress rollups (`X/Y required ✓ · +N additional`). **Enrollment-gated**; staff/owner may
   preview **untracked**; non-enrolled non-staff → 403.
6. **Lesson unit** (`GET /courses/<slug>/u/<node_pk>/`) renders the unit's elements in order. A
   `quiz` unit renders a neutral "arrives in Phase 2" placeholder (no consumption/marking).
7. **Progress** records correctly: the seen endpoint (`POST …/u/<node_pk>/seen/`) merges
   element-ids (set union, idempotent), **ignores foreign ids**, and auto-completes when the unit's
   full element set is seen; the **fallback** (`POST …/u/<node_pk>/complete/`, plain form, no JS)
   sets `completed`. A unit that fits on screen auto-completes on first flush. Re-visiting never
   un-completes. Progress is written only for enrolled students.
8. **Security/validation:** `TextElement` sanitised to a safe tag subset on save (scripts stripped);
   video/iframe domains validated against `ALLOWED_EMBED_DOMAINS`; image/video uploads validated
   (extension/content-type, Pillow, size cap). Progress endpoints are login + enrollment gated and
   CSRF-protected.
9. **i18n:** all new UI strings via `gettext`, EN + real Polish, compiled. The rendered content
   region carries `lang="{course.language}"`.
10. **Authoring scaffolding:** all models registered in admin; a **`seed_demo_course` management
    command** builds a complete example (course → mixed tree → lesson units → all 5 element types →
    an enrolled demo student) used as deterministic fixture content.
11. **Tests** (pytest + factory_boy vs real PostgreSQL): model invariants, element render +
    sanitisation + whitelist, outline rollups (required/additional), progress (seen union,
    auto-complete, foreign-id rejection, fallback, gating, untracked preview), view access. A
    **Playwright e2e** extends the suite: seed → login as enrolled student → outline → open lesson
    → deterministic scroll → auto-complete reflected; plus the mark-done fallback path.
12. Full `pytest` suite green; `ruff` check + format clean; `manage.py check` clean;
    `makemigrations --check` clean; `collectstatic` clean.

---

## Data model

New app **`courses`** (mirrors educa; keeps content + learner-state cohesive). Learner-state models
(`Enrollment`, `UnitProgress`) live here in 1a; a `learning` app may be split out in Phase 3 if
grouping warrants — YAGNI now.

```python
# courses/models.py  (shapes, not literal final code)

class Subject(models.Model):
    title = CharField; slug = SlugField(unique=True)

class Course(models.Model):
    title = CharField; slug = SlugField(unique=True)
    subject = FK(Subject, null=True, on_delete=SET_NULL)
    language = CharField(choices=<enabled languages>)        # monolingual CONTENT language
    overview = TextField(blank=True)
    owner = FK(User, null=True, on_delete=SET_NULL)          # hook: CA scoping (inert in 1a)
    visibility = CharField(choices={assigned, open}, default='assigned')  # hook: self-enroll = Phase 3
    created = DateTimeField(auto_now_add); updated = DateTimeField(auto_now)

class ContentNode(models.Model):                             # Part / Chapter / Section / Unit
    KIND = {part, chapter, section, unit}; RANK = {part:0, chapter:1, section:2, unit:3}
    course = FK(Course, related_name='nodes')
    parent = FK('self', null=True, related_name='children')  # null = directly under the course
    kind = CharField(choices=KIND)
    order = OrderField(for_fields=['course', 'parent'])       # one order space per parent
    title = CharField
    unit_type = CharField(choices={lesson, quiz}, null=True, blank=True)  # iff kind=unit
    obligatory = BooleanField(default=True)                   # meaningful for units
    created/updated
    # clean(): RANK[parent.kind] < RANK[self.kind]; units are leaves;
    #          unit_type required iff kind=unit; null otherwise.

class Element(models.Model):                                 # the GFK join-row
    unit = FK(ContentNode, related_name='elements', limit_choices_to={'kind': 'unit'})
    order = OrderField(for_fields=['unit'])
    content_type = FK(ContentType, limit_choices_to=<the 5 element models>)
    object_id = PositiveIntegerField
    content_object = GenericForeignKey('content_type', 'object_id')

class ElementBase(models.Model):                             # abstract
    class Meta: abstract = True
    def render(self): return render_to_string(f'courses/elements/{self._meta.model_name}.html', {'el': self})

class TextElement(ElementBase):  body = TextField            # sanitised rich text (safe subset)
class ImageElement(ElementBase): image = ImageField; alt = CharField(blank); figcaption = CharField(blank)
class VideoElement(ElementBase): url = URLField(blank); file = FileField(blank)   # exactly one
class IframeElement(ElementBase): url = URLField; title = CharField(blank)        # whitelisted
class MathElement(ElementBase):  latex = TextField           # client-side KaTeX

class Enrollment(models.Model):
    student = FK(User); course = FK(Course)
    created_at = DateTimeField(auto_now_add)
    source = CharField(choices={manual, group, self}, default='manual')
    class Meta: constraints = [UniqueConstraint(student, course)]

class UnitProgress(models.Model):
    student = FK(User); unit = FK(ContentNode, limit_choices_to={'kind': 'unit'})
    seen_element_ids = JSONField(default=list)               # the fractional seen-set
    completed = BooleanField(default=False); completed_at = DateTimeField(null=True)
    updated_at = DateTimeField(auto_now)
    class Meta: constraints = [UniqueConstraint(student, unit)]
```

**`OrderField`** is lifted from educa (`courses/fields.py`) and adapted to scope correctly when
`parent` is null (course-level siblings share one order space).

`TextElement` is **sanitised rich text** (headings/bold/italic/lists/links) — *not* the deferred
arbitrary-HTML element. Sanitisation (nh3 or bleach) runs on `save()`; render trusts the stored
value. This keeps the security boundary crisp.

---

## Rendering & consumption

URLs in `courses/urls.py`; views in `courses/views.py`. All login-required.

| View (inventory #) | Route | Behaviour |
|---|---|---|
| My courses (3.1) | `GET /courses/` | Lists the user's `Enrollment`s → courses. |
| Course outline (3.4) | `GET /courses/<slug>/` | `ContentNode` tree + per-node rollups. Enrollment-gated. |
| Lesson unit (3.5) | `GET /courses/<slug>/u/<node_pk>/` | Renders elements in order; `quiz` → Phase-2 placeholder. |
| Mark seen (JS) | `POST …/u/<node_pk>/seen/` | Merges seen ids; auto-completes when all seen. |
| Mark done (fallback) | `POST …/u/<node_pk>/complete/` | Plain form POST → `completed=True`; no JS. |

**Element rendering** — a `{% render_element element %}` template tag calls
`element.content_object.render()`, dispatching to `courses/elements/{model_name}.html` by
convention. Each element is wrapped server-side in `<section data-element-id="{pk}">…</section>`
(the view-tracking hook). Math renders client-side via **KaTeX, vendored as a self-hosted static
asset** under `courses/static/courses/vendor/katex/` (consistent with the project's
self-hosted-assets policy — e.g. Inter in 0d-1; no CDN), loaded only on lesson pages that contain a
math element; video/iframe render the whitelisted embed; image renders `<figure>`/`<figcaption>`.

**Outline rollups** — per container node: `required` = obligatory descendant units, `done` = those
the student completed, plus an `additional done` count. Computed by fetching the course's nodes +
the student's `UnitProgress` (≈2 queries) and assembling in Python — **no denormalisation** (trees
are small). Displayed honestly, e.g. `Chapter 1 — 3/4 required ✓ · +1 additional`.

**Access control** — consuming requires `Enrollment(student, course)`. **Staff/owner may preview
untracked** (matches "Preview as student" 5.14 — no `UnitProgress` written). Non-enrolled non-staff
→ 403.

---

## Progress mechanics

- `courses/static/courses/js/progress.js`: an `IntersectionObserver` over `[data-element-id]`
  sections. First time an element enters view → add its id to a local seen-set → **debounced** POST
  of new ids to `…/seen/` (CSRF), with a final flush on `pagehide`/`visibilitychange`.
- Server (`seen` view): merges ids into `UnitProgress.seen_element_ids` (set union — idempotent),
  **ignores ids not belonging to the unit**, and when the set covers the unit's full element set →
  sets `completed` + `completed_at`. Returns the updated progress (JSON) so the UI can reflect done.
- **Short unit (fits on screen):** all elements intersect on load → first flush completes it.
- **`Mark as done`** sits at the unit's end as a plain `<form method=post action=…/complete/>` →
  completes server-side with **zero JS**. This is the guarantee against the false-incomplete hard
  constraint (JS off/errored, tracking miss, accessibility).
- Re-visiting a completed unit never un-completes; further seen-POSTs are harmless.

---

## Security, validation & i18n

- `ContentNode.clean()`: kind-depth invariant, unit-leaf, `unit_type` iff unit. `Element.unit`
  limited to `kind=unit` (`limit_choices_to` + clean).
- `TextElement`: sanitised to a safe tag subset on save (scripts stripped).
- `VideoElement.clean()`: **exactly one** of `url` / `file` set (XOR); a `url` is validated against
  the whitelist, an uploaded `file` against allowed types.
- Video/iframe: `ALLOWED_EMBED_DOMAINS` (settings constant; Phase 5 makes it admin-configurable)
  validated in `clean()`; non-whitelisted rejected.
- Uploads (image/video): extension + content-type check, Pillow validates images, size cap,
  course-scoped `upload_to`. ⚠️ **Production media serving** (whitenoise covers static, not media)
  is a **deploy-skeleton item**, out of 1a scope; 1a uses local `MEDIA_ROOT`/`MEDIA_URL`.
- Progress endpoints: login + enrollment gated, CSRF, foreign element-ids rejected.
- i18n: new UI strings via `gettext`, EN + real Polish, compiled (same flow as 0d). Rendered
  content region carries `lang="{course.language}"` for correct hyphenation/a11y independent of the
  chrome language.

---

## Authoring in 1a (admin + seed command)

All models registered in `courses/admin.py` for inspection/tinkering (`ContentNode` with
`kind`/`course` filters and autocomplete `parent`). Raw-admin GFK element creation is two-step and
clunky, so the **primary 1a authoring path is a `seed_demo_course` management command** that builds
a complete example end-to-end — course → mixed-depth tree → lesson units (obligatory + additional)
→ all 5 element types → an enrolled demo student. It makes the slice demonstrable without fighting
admin, provides deterministic content for the Playwright e2e, and embodies the roadmap's
"admin/fixtures as scaffolding." The 1b builder removes the clunk.

---

## Testing strategy

pytest + factory_boy against real PostgreSQL; extend the existing Playwright e2e suite.

- **Factories:** `CourseFactory`, `ContentNodeFactory` (container/unit variants), the 5 element
  factories, `EnrollmentFactory`, `UnitProgressFactory`.
- **Model:** kind-depth (valid + rejected nestings), unit-leaf, `OrderField` scoping incl.
  **null-parent course-level siblings** and per-unit, unique constraints, `unit_type` rule.
- **Elements:** each `render()` hits its template; sanitisation strips scripts; whitelist rejects
  bad domains; video "exactly one of url/file".
- **Rollups:** required-vs-additional math, nested subtree counts, obligatory logic.
- **Progress:** seen-set union/idempotency, auto-complete-when-all-seen, foreign-id rejection,
  mark-done fallback, non-enrolled blocked, staff preview untracked.
- **Views:** my-courses lists only enrollments, outline access gate, lesson render, quiz
  placeholder, 403 for non-enrolled.
- **Playwright e2e:** seed → login as enrolled student → outline → open lesson → deterministic
  scroll → auto-complete reflected; mark-done fallback path. (Marked `e2e`, excluded from the
  default run, run in CI — per the 0d-2 setup.)

---

## Out of scope (explicit)

- **Bespoke authoring UI** (course builder, element editors, media manager) — Phase 1b.
- **HTML element** (course CSS/JS, per-unit JS, MathJax sandboxing) — own Phase 1 slice.
- **Quiz behaviour / question types / marking** — Phase 2 (`quiz` unit_type is inert here).
- **Cohorts / groups / collections / self-enroll catalog / analytics matrix** — Phase 3
  (`Enrollment.source`, `Course.visibility` are reserved hooks only).
- **Notes & tags** — Phase 4 (no outline badges yet).
- **Per-element content translation** — reserved seam only.
- **DRF API** for content — not in 1a (server-rendered only).
- **Production media serving** — deploy-skeleton item.
- **Course CSS/JS files, colour-band config** — later (HTML slice / Phase 3).

---

## Likely task decomposition (for the plan)

1. `courses` app scaffold + `OrderField` (adapted) + `Subject`/`Course`.
2. `ContentNode` tree + invariants + admin.
3. `Element` GFK join + 5 concrete element models + sanitisation/whitelist validation + render
   convention + templates.
4. `Enrollment` + `UnitProgress` models + admin.
5. My-courses + outline views (+ rollups) + access control + templates.
6. Lesson unit view + element rendering + quiz placeholder.
7. Progress endpoints (`seen` + `complete`) + `progress.js`.
8. `seed_demo_course` command.
9. i18n extraction + Polish + compile.
10. Playwright e2e + final DoD pass.
