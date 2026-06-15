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
   its units additional — no separate flag on grouping nodes. **Precise rule:** `obligatory` is read
   **only on `kind=unit` nodes** (ignored on containers); a unit's required/additional status is its
   **own** flag, independent of any ancestor's flags (no inheritance down the container chain). In
   1a, "required" totals count **obligatory units of `unit_type=lesson` only** — `quiz` units are
   inert (uncompletable until Phase 2) and are therefore **excluded from required totals** so a
   seeded demo course can reach 100%.
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
4. **My courses** (`GET /courses/`, login-required) lists only the user's enrolled courses. This is
   **enrollment-only by design**: staff/owners who can *preview* a course they're not enrolled in do
   **not** see it here — they reach it via direct slug URL (and, later, the 1b builder / admin). No
   "owned/previewable" section in 1a.
5. **Course outline** (`GET /courses/<slug>/`) renders the `ContentNode` tree with per-node
   progress rollups (`X/Y required ✓ · +N additional`). Access predicate (single source of truth,
   see Access control): **enrolled OR `user.is_staff` OR `course.owner_id == user.id`**; the latter
   two preview **untracked**. Anyone failing all three → 403. (A non-staff owner *does* qualify for
   untracked preview of their own course.)
6. **Lesson unit** (`GET /courses/<slug>/u/<node_pk>/`) renders the unit's elements in order. A
   `quiz` unit renders a neutral "arrives in Phase 2" placeholder (no consumption/marking).
7. **Progress** records correctly: the seen endpoint (`POST …/u/<node_pk>/seen/`) merges
   element-ids (set union, idempotent), **filters out** ids not belonging to the unit and
   non-integer/malformed ids (no error — see contract below), and **auto-completes when the unit has
   ≥1 element AND the seen-set covers them all**. The **fallback** (`POST …/u/<node_pk>/complete/`,
   plain form, no JS) completes directly. **Both paths are guarded by `if not progress.completed:`** —
   the first to fire (via *either* path) sets `completed=True` **and** `completed_at=now()`; every
   later completion attempt by either path is a **no-op** that never re-stamps or clears
   `completed_at`. **Completion is sticky:** once set it never reverts, **regardless of later
   element-set changes** (an author adding/removing elements after completion does not un-complete
   the unit; see the fraction-bar rule under Progress mechanics). A unit that fits on screen
   auto-completes on first flush. **Empty-unit rule:** a
   lesson unit with **zero elements never auto-completes** (no element can fire the observer) but is
   completable via the fallback button — so the hard "never left incomplete" constraint still holds.
   Re-visiting never un-completes. Progress is written only for enrolled students.
   **Seen-endpoint request/response contract:** the request body is a **bare JSON array of
   integers** (`Element` join-row ids — see "element-id" below) sent as `Content-Type:
   application/json`; the `sendBeacon` flush sends a `Blob` typed `application/json` so the server
   parses it identically to the `fetch` path. The server `json.loads()` the body: any **JSON array**
   → `200` with the updated progress JSON. Filtering is **per-element**: each entry is kept iff it is
   an integer that is a current `Element.pk` of this unit; valid entries are **merged** into the
   seen-set (and **can trigger completion**), invalid/foreign entries are individually dropped. So a
   **mixed** array merges its valid ids; an **empty** or **all-foreign** array leaves progress
   unchanged; all return `200`. Anything that is **not a JSON array** (object, scalar, non-JSON) →
   `400`.
   **"element-id" means the `Element` join-row pk** throughout — `data-element-id="{Element.pk}"`,
   the client seen-set, the stored `seen_element_ids`, and the foreign-id filter all key on the same
   `Element.pk` (never the concrete element's pk).
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
    language = CharField(choices=COURSE_LANGUAGES)           # monolingual CONTENT language; see note
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
    object_id = PositiveBigIntegerField                      # matches default BigAutoField PKs of the 5 element models
    content_object = GenericForeignKey('content_type', 'object_id')

class ElementBase(models.Model):                             # abstract
    class Meta: abstract = True
    def render(self): return render_to_string(f'courses/elements/{self._meta.model_name}.html', {'el': self})

class TextElement(ElementBase):  body = TextField            # sanitised rich text (safe subset)
class ImageElement(ElementBase): image = ImageField; alt = CharField(blank); figcaption = CharField(blank)
class VideoElement(ElementBase): url = URLField(blank); file = FileField(blank)   # clean(): XOR — exactly one (reject neither AND both)
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

**`Subject`** is **admin-only metadata in 1a** — no learner-facing surface (no catalog, filter, or
outline use; that arrives with the Phase-3 catalog). It exists so `Course.subject` has a target;
`seed_demo_course` creates one Subject for the demo course.

**`COURSE_LANGUAGES`** is a **`choices` sequence of `(code, label)` pairs** —
`[('en', 'English'), ('pl', 'Polski')]` — pinned in 1a (the Phase-0 enabled set), defined as an
explicit constant **not** bound to `settings.LANGUAGES`, so adding a future *chrome* language never
silently makes it a valid *content* language. The **stored value is the code** (`'en'`/`'pl'`); both
are valid BCP-47 / HTML `lang` attribute values, so `lang="{course.language}"` is well-formed.

**`OrderField`** is lifted from educa (`courses/fields.py`) and adapted to scope correctly when
`parent` is null (course-level siblings share one order space). It **auto-assigns** the next
integer within a scope on save when blank; it is **not** backed by a DB uniqueness constraint, so
transient duplicate `order` values within a scope are tolerated (ties broken by `pk`) and are not a
hard error. Re-parenting and gap-compaction on delete are **deferred to 1b** (the builder owns
reorder/move UX); 1a only needs stable per-scope ordering for display.

**Root-level units are legal** (a course whose root nodes, `parent=null`, are all `kind=unit` —
i.e. no container levels at all). The outline/rollup code and tree renderer MUST handle a
container-less course; this shape is covered by a test (see Testing).

`TextElement` is **sanitised rich text** (headings/bold/italic/lists/links) — *not* the deferred
arbitrary-HTML element. Sanitisation (nh3 or bleach) runs in `clean()`/`save()`, and **every write
path must go through it** — the `seed_demo_course` command and admin use `Model.save()`/
`full_clean()`; `bulk_create`/`QuerySet.update()`/raw fixtures are **disallowed** for `TextElement`.
Because render marks the stored body safe, an unsanitised write would be stored XSS — so render
**also re-sanitises as defense-in-depth** (cheap; idempotent on already-clean input).

**GFK cleanup:** each concrete element model declares a `GenericRelation(Element)` — with its
`content_type_field`/`object_id_field` pointing at `Element`'s GFK fields, scoped by that model's
ContentType — so deleting a concrete element **cascades** to the matching `Element` join-row (no
dangling rows; cross-model `object_id` collisions are disambiguated by ContentType and never
cascade the wrong row). Defensively, the render path **tolerates a null `content_object`** (skips
it) rather than 500-ing.

**`UnitProgress` invariant: `completed=True ⇒ completed_at is not None`.** Enforced in
`UnitProgress.save()` — whenever `completed` is true and `completed_at` is null, it is stamped
`now()`. This holds the invariant for **every** write path, including a Platform Admin toggling
`completed` directly in Django admin (so an admin edit can never leave a completed row without a
timestamp). The endpoint guards (`if not progress.completed`) still own the "first transition only,
never re-stamp" rule for the consumption paths.

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
self-hosted-assets policy — e.g. Inter in 0d-1; no CDN). The lesson view computes
`has_math` by comparing each join-row's `content_type_id` to a cached
`ContentType.objects.get_for_model(MathElement).id` (i.e. `has_math = any(el.content_type_id ==
math_ct_id for el in unit_elements)`) — **not** `el.content_type is MathElement` (that compares a
`ContentType` row to a model class and is always `False`). `get_for_model` is process-cached, so
this stays query-free over the already-fetched element set; it gates the KaTeX `<link>`/`<script>`
include — pages with no math element load no KaTeX. Video/iframe render the whitelisted embed; image renders a `<figure>`
that **always emits the `alt` attribute** (an empty `alt=""` is valid HTML and the intended marker
for a decorative image — never omitted) and **emits `<figcaption>` only when the caption is
non-blank**. The combination of empty `alt` with a non-blank caption is semantically odd but the
**author's responsibility** — the template enforces no coupling between the two.

**Outline rollups** — per node, over its **descendant `kind=unit` nodes**: `required` = descendant
units that are `obligatory AND unit_type=lesson` (per decision #6 — quiz units excluded in 1a),
`done` = those `required` units the student has `completed`, plus an `additional done` count
(completed **non-obligatory `unit_type=lesson`** units — the *same* `lesson`-only qualifier as
`required`, stated once; quiz units are uncompletable in 1a so they never appear in either tally).
**`required == 0` rendering:** when a node has zero required units (e.g. an all-quiz or all-additional
subtree), the `X/Y required` fragment is **suppressed entirely** (no `0/0`, no division) — the node
shows only `+N additional` if `N > 0`, else nothing — and such a node is treated as **vacuously
complete** wherever a node-level "done" mark is displayed. The course root rolls up all its
descendants the same way, so a
**container-less course** (units directly under the course) is just the degenerate case and renders
correctly. Computed by fetching the course's nodes + the student's `UnitProgress` for the course
(**2 queries**) and assembling in Python — **no denormalisation** (trees are small). The outline
shows only **binary unit done/required counts**; the **within-unit fractional bar** (seen N of M
elements, decision #5) lives on the **lesson page**, not the outline — so no per-unit element-count
query is needed at the outline. **`+N additional` = the count of *completed* additional (non-obligatory
lesson) units** — a "bonus done" tally, **no denominator** (the total additional count is a deferred
nicety); it renders only when `N > 0`. Displayed honestly, e.g. `Chapter 1 — 3/4 required ✓ · +1 additional`.

**Object scoping (every node route).** Routes use the **`<int:node_pk>`** converter (a non-integer
path simply doesn't resolve → 404). Each view runs these checks **in this exact order**, so a
mismatch always 404s *before* any 403 (never leaking another course's existence via a 403):
1. `get_object_or_404(ContentNode, pk=node_pk)` — missing → **404**;
2. **404 unless `node.course.slug == slug`** (URL-pairing/IDOR guard);
3. lesson/`seen`/`complete` routes: **404 unless `node.kind == 'unit'`** (and `seen`/`complete`
   additionally 404 unless `unit_type == 'lesson'`, per Progress mechanics);
4. only now evaluate the **access predicate against `node.course`** → **403** on failure.
So a user pairing a course they *can* access with a `node_pk` from another course gets **404** at
step 2, never a 403.

**Access control predicate (canonical, used by outline + lesson + seen + complete).** Access is
granted iff **`enrolled` OR `user.is_staff` OR (`course.owner_id is not None` AND `course.owner_id
== user.id`)**, where `enrolled` = `Enrollment.objects.filter(student=user, course=course).exists()`.
The explicit `owner_id is not None` guard prevents a null owner from ever matching (all routes are
`@login_required`, so `user` is authenticated and `user.id` is set). `is_staff` and owner access are
**untracked preview** (matches "Preview as student" 5.14 — **no `UnitProgress` written**). For a
previewer the endpoints **no-op without a DB write** but still return a normal-shaped response so
the client/JS needs no special-casing: **`seen` → `200`** with a synthetic progress JSON
(`{"seen_element_ids": [], "completed": false}`, reflecting that nothing was persisted); **`complete`
→** the same redirect/response as the enrolled path, just without the write. A non-staff owner
qualifies for preview of their own course. Anyone failing all three → **403**.

---

## Progress mechanics

- `courses/static/courses/js/progress.js`: an `IntersectionObserver` over `[data-element-id]`
  sections, configured `threshold: 0` (+ a small `rootMargin`, e.g. `0px 0px -10% 0px`), so **any
  partial intersection** marks an element seen — including an element **taller than the viewport**
  (marked on first partial entry, by design) and short ones visible on load. Elements that render
  **zero height** (or otherwise never intersect) are the residual edge case the **fallback button
  covers** — consistent with the hard constraint. First time an element enters view → add its id to
  a local seen-set → POST **debounced ~500 ms**. To avoid in-flight races and dropped-on-unload
  POSTs, the client sends its **cumulative local seen-set** (not deltas) and relies on **server-side
  idempotency** for dedup/ordering; the final flush on `pagehide`/`visibilitychange` uses
  **`navigator.sendBeacon`** (or `fetch(…, {keepalive: true})`) so the completing flush survives
  navigation. CSRF token is included on every send.
- Server (`seen` view): merges ids into `UnitProgress.seen_element_ids` (set union — idempotent),
  **filters ids not belonging to the unit** and malformed ids (per the §Success-criteria #7 HTTP
  contract). Auto-complete predicate, stated exactly: let `current = set(current Element.pks)`;
  complete iff **`current and current.issubset(set(seen_element_ids))`** (the `current` truthiness
  guard makes a **zero-element** unit never auto-complete). On first satisfaction → `completed=True`
  + `completed_at=now()` (first transition only). **Stale ids are harmless**: ids of deleted elements
  may linger in the stored set; the `issubset` direction (current ⊆ seen) ignores them, and 1a does
  **not** prune them. Returns the updated progress (JSON) so the UI can reflect done.
- **Short unit (fits on screen):** all elements intersect on load → first flush completes it.
- **`Mark as done`** sits at the unit's end as a plain `<form method=post action=…/complete/>` →
  sets `completed=True` + `completed_at=now()` server-side with **zero JS**, for **any** lesson unit
  including a **zero-element** one. This is the guarantee against the false-incomplete hard
  constraint (JS off/errored, tracking miss, empty unit, accessibility).
- Re-visiting a completed unit never un-completes; further seen-POSTs are harmless.
- **Within-unit fraction bar** (lesson page): shows `|seen ∩ current-elements|` over `current element
  count`. When the unit is `completed`, the bar renders **100%** regardless of the raw seen-set — so
  a unit completed before an author added an element never displays a contradictory "done but 3/4."
  When `current element count == 0` **and not completed** (the empty-unit case), the bar is **hidden
  entirely** (no `0/0`); only the `Mark as done` button shows.
- **Quiz units accept no progress:** because consumption/marking is Phase 2, both `seen` and
  `complete` **404 when `unit_type != 'lesson'`** (the lesson *view* still renders the quiz
  placeholder at 200). So progress endpoints are valid only for lesson units.

---

## Security, validation & i18n

- `ContentNode.clean()`: kind-depth invariant (vs **parent**), unit-leaf, `unit_type` iff unit. It
  **also re-validates against existing children** so an admin edit can't break the tree from above:
  reject changing `kind` to a rank **≥** any current child's rank, and reject converting a node that
  **has children** into a `unit` (units must stay leaves). `Element.unit` limited to `kind=unit`
  (`limit_choices_to` + clean).
- `TextElement`: sanitised to a safe tag subset in `clean()`/`save()` (scripts stripped); **all
  write paths go through it** (seed/admin use `save()`/`full_clean()`; no `bulk_create`/`update`),
  and **render re-sanitises as defense-in-depth** (see Data model).
- `VideoElement.clean()`: **exactly one** of `url` / `file` set (XOR); a `url` is validated against
  the whitelist, an uploaded `file` against allowed types.
- Video/iframe: `ALLOWED_EMBED_DOMAINS` (settings constant of **bare lowercase hosts**, e.g.
  `{"www.youtube.com", "youtu.be", "player.vimeo.com", "www.geogebra.org"}`; Phase 5 makes it
  admin-configurable) validated in `clean()`. Matching rule: parse the URL, **require `https`**, and
  accept iff the lowercased host **equals** a listed host **or** is a **subdomain** of one
  (`host == d or host.endswith("." + d)`); path/query ignored. Anything else rejected. (Listing both
  `youtube.com` forms / `youtu.be` is the author's responsibility — no implicit aliasing.)
- Uploads (image/video): extension + content-type check, Pillow validates images, size cap,
  course-scoped `upload_to`. ⚠️ **Production media serving** (whitenoise covers static, not media)
  is a **deploy-skeleton item**, out of 1a scope; 1a uses local `MEDIA_ROOT`/`MEDIA_URL`.
- Progress endpoints: login-required, **object-scoped to `node.course`** (404 on slug/kind
  mismatch), gated by the canonical access predicate, CSRF-protected; foreign/malformed ids
  **filtered** (200, per #7) — not an error.
- i18n: new UI strings via `gettext`, EN + real Polish, compiled (same flow as 0d). **Only the
  author-content region** carries `lang="{course.language}"`; surrounding **chrome labels** (e.g.
  "+N additional", "Mark as done") stay in the document's UI language and sit **outside** that
  `lang`-scoped region, so screen-reader language switching is correct for both.

---

## Authoring in 1a (admin + seed command)

All models registered in `courses/admin.py` for inspection/tinkering (`ContentNode` with
`kind`/`course` filters and autocomplete `parent`). Raw-admin GFK element creation is two-step and
clunky, so the **primary 1a authoring path is a `seed_demo_course` management command** that builds
a complete example end-to-end — course → mixed-depth tree → lesson units (obligatory + additional)
→ all 5 element types → an enrolled demo student. It makes the slice demonstrable without fighting
admin, provides deterministic content for the Playwright e2e, and embodies the roadmap's
"admin/fixtures as scaffolding." The 1b builder removes the clunk.

**Rerun contract (required for CI):** `seed_demo_course` is **idempotent** — re-running it must not
crash on the unique constraints (`Course.slug`, `Enrollment(student,course)`, etc.). It uses
`get_or_create`/`update_or_create` keyed on stable natural keys: course **slug**, the demo student's
**username**, and each node matched on **`(course, parent, title)`** — **not** on `order` (which is
non-unique and auto-assigned, so it can't be a reconciliation key). The seed gives every node a
**distinct title within its parent** (so `(course, parent, title)` resolves exactly one row, never
`MultipleObjectsReturned`) and **passes an explicit `order`** on create so node sequence is
deterministic. A second run reconciles to the same state rather than duplicating or erroring. (No
`--fresh` teardown needed; add one only if reconciliation proves fiddly.) Every element write goes
through `Model.save()` so `TextElement` sanitisation is never bypassed.

---

## Testing strategy

pytest + factory_boy against real PostgreSQL; extend the existing Playwright e2e suite.

- **Factories:** `CourseFactory`, `ContentNodeFactory` (container/unit variants), the 5 element
  factories, `EnrollmentFactory`, `UnitProgressFactory`.
- **Model:** kind-depth (valid + rejected nestings), **root-level unit allowed**, unit-leaf,
  `OrderField` scoping incl. **null-parent course-level siblings** and per-unit, unique constraints,
  `unit_type` rule, **`clean()` child re-validation** (rejects deepening kind ≥ a child's rank or
  unit-converting a node with children), **`UnitProgress.save()` stamps `completed_at` when an admin
  toggles `completed=True`** (invariant `completed ⇒ completed_at`).
- **Elements:** each `render()` hits its template; sanitisation strips scripts on save **and** a
  directly-poisoned stored value is re-sanitised at render; whitelist rejects bad domains; video XOR
  rejects **both neither-set and both-set**; **deleting a concrete element cascades** its `Element`
  join-row, and render **tolerates a null `content_object`**.
- **Rollups:** required-vs-additional math, nested subtree counts, **obligatory read only on units /
  no ancestor inheritance**, **obligatory quiz excluded from required**, **`required==0` node
  suppresses the `X/Y required` fragment** (no `0/0`) and is vacuously complete, **container-less
  course** rolls up correctly.
- **Progress:** seen-set union/idempotency; auto-complete-when-all-seen; **zero-element unit does
  NOT auto-complete but completes via fallback**; **both paths set `completed_at` (first transition
  only; never cleared)** and a **cross-path second completion is a no-op** (auto then `/complete/`,
  and vice-versa, never re-stamps); **fraction bar renders 100% once `completed` even if an element
  was added afterward**; seen HTTP contract (**bare-JSON-array body**; empty / all-foreign / mixed /
  malformed-id → 200 unchanged-or-merged; **non-array / non-JSON body → 400**); **`seen`/`complete`
  404 on a `quiz` unit**; mark-done fallback; non-enrolled blocked; **staff and non-staff-owner
  preview write no `UnitProgress`; previewer `seen` → 200 synthetic progress, `complete` no-op
  without write**; **mixed array merges valid ids and can complete the unit**.
- **Views & scoping:** my-courses lists only enrollments (**owner/staff non-enrolled course absent**);
  outline access gate (enrolled / staff / non-staff-owner / **null-owner non-match** / 403); **check
  order — slug-mismatch 404s before any 403** (enrolled-in-B user hitting B's node under A's slug →
  404, not 403); non-integer `node_pk` → 404; **non-unit lesson route → 404**; **IDOR test** —
  enrolled-in-A slug + B's `node_pk` → 404, no progress written; lesson render; quiz placeholder.
- **Embeds:** `ALLOWED_EMBED_DOMAINS` matching — exact host and subdomain accepted, non-listed host
  and **non-https** rejected.
- **Seed:** `seed_demo_course` is **rerun-idempotent** (run twice in one test → no IntegrityError,
  same row counts).
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
