# Per-Course Structure / Depth Config — Design

**Date:** 2026-06-26
**Status:** Draft (brainstormed; pending user review)
**Type:** Roadmap-committed feature cycle — the agreed **next cycle ahead of any new development** (user explicit; valued above the existing author skip-levels flexibility). Its own spec → plan → build cycle. Origin: `differences.md` §"Course depth" + the "so many components, I feel lost" friction surfaced during the builder-authoring-UX batch (PR #36).

## Goal

Let a **simple course avoid the full `Part › Chapter › Section › Unit` depth.** Each course picks a **structure preset** that fixes which content levels it offers; the builder then only presents those levels (its `+` chips), and a small **structure legend** shows the configured shape at a glance. A complex course keeps all four levels; a simple one only ever deals with `course → unit`.

This narrows, per course, a capability that is currently **global**: today every course offers all four kinds because middle levels are author-time skippable but never *excluded*.

## Background / current state (verified in code)

- **Content tree:** one `ContentNode` model, `kind ∈ {part, chapter, section, unit}` (`courses/models.py:97-101`), `unit_type ∈ {lesson, quiz}` (nullable; required on units, forbidden on non-units; `models.py:103-105,138-142`). `RANK = {part:0, chapter:1, section:2, unit:3}` (`models.py:107`). `unit` is the only element-bearing leaf.
- **Depth is skippable but not restrictable.** `clean()` enforces only that a child's kind is *strictly deeper* than its parent's (`models.py:130-152`) — so middle levels may be skipped (a `unit` may sit directly under a `part`). `legal_child_kinds(parent_kind)` (`courses/ordering.py:126-133`) returns **every** strictly-deeper kind in RANK order; `parent_kind=None` (top scope) returns all four. There is **no per-course restriction** — the same kind menu is offered in every course. This matches `differences.md` §"Course depth" (part/chapter/section each individually skippable; course/unit/element obligatory).
- **`PRIMARY_CHILD_KIND`** (`ordering.py:123`) = `{None: "chapter", "part": "chapter"}` — the one-click `+` chip for scopes with ≥3 legal kinds (top scope, part); the remaining kinds go to a `+…` overflow. Scopes with <3 legal kinds (chapter→{section,unit}, section→{unit}) have no "primary"; all chips show inline.
- **Builder consumption:** `templates/courses/manage/_add_affordance.html` renders the add-row. It calls the `legal_child_kinds` / `primary_child_kind` / `kind_label` simple-tags from `courses/templatetags/courses_manage_extras.py:92-110` (thin wrappers over `ordering.py`). It loops `{% for kind in kinds %}`, rendering a chip per legal kind; the `unit` kind is special-cased into **two** chips (`+ Lesson` / `+ Quiz`, post-PR #36), other kinds render `+ <kind_label>`. `chip--primary` / `chip--overflow` classes come from the `primary` value.
- **Add path (server):** `manage_node_add` (`courses/views_manage.py`, the `courses:manage_node_add` URL) reads `kind` (explicit, wins) or infers `kind=unit` from a submitted `unit_type` (post-PR #36 resolution order), then calls `builder.add_node`, which runs `full_clean()`. **No course-level kind policy is consulted** — any structurally-legal kind is accepted.
- **Course model & forms:** `Course` (`courses/models.py`) holds course metadata; `CourseForm` (`courses/forms.py`) is the settings/edit form; course creation also flows through a create view/form. (Exact field list to be confirmed at implementation; this spec adds three fields + a picker widget to the create and settings forms.)
- **Existing migration precedent:** data backfills via `RunPython` are established (e.g. grouping `0002_default_cohort_backfill`, `0003`); roles/permissions caveats do not apply here (no permission rows are created).

## Scope

1. **Per-course structure model** — three booleans on `Course` + an `allowed_kinds` helper.
2. **Preset picker** (Flat / Chapters / Parts / Full) on the **create** form and the **settings** form, with a **narrowing guard**.
3. **Per-course `legal_child_kinds`** — intersect the global rank logic with the course's allowed set; thread the course through both call sites.
4. **Server-side enforcement** in `manage_node_add` (defense in depth).
5. **Data migration** — add fields + backfill existing courses to the kinds they actually use.
6. **Structure legend** in the builder.
7. **i18n** (EN/PL) for preset labels, legend, and validation messages.

### Not in this cycle (explicit)

- **Per-course custom *labels*** (renaming Part/Chapter/Section/Unit per course) — **not planned.** Levels keep their fixed, translated names.
- **Assisted auto-flatten on narrowing** (hoist children up + delete excluded nodes) — **deferred follow-up only.** v1 *blocks* a narrowing that would orphan content rather than transforming it.
- **A free "Custom" preset editor** (raw per-level toggles in the UI) — not exposed in v1. The model supports any combination; the UI offers four named presets and *displays* "Custom" read-only for courses whose flags match no preset (possible only via backfill of historically-mixed courses or the Django admin).
- **Changing the `unit`/element leaf** or `differences.md` element rules — untouched.

---

## Section 1 — Data model & core behavior

### 1.1 Storage (the flexible core)

Add three `BooleanField`s to `Course`:

- `uses_parts` (default `True`)
- `uses_chapters` (default `True`)
- `uses_sections` (default `True`)

`unit` is always present (mandatory leaf) and has no flag. Defaults are `True` (= Full) so any code path that bypasses the create form (Django admin, raw `Course.objects.create`, test factories) reproduces **today's** four-level behavior — backward-safe. The create form's *picker* defaults to **Chapters** (UI default ≠ model default, intentional).

A helper property returns the allowed set in RANK order, always ending in `unit`:

```python
@property
def allowed_kinds(self):
    ks = []
    if self.uses_parts:    ks.append("part")
    if self.uses_chapters: ks.append("chapter")
    if self.uses_sections: ks.append("section")
    ks.append("unit")
    return ks
```

**Why three booleans** rather than a stored preset name or a JSON/array field: any subset of `{part, chapter, section}` is *already* structurally valid (kinds nest by rank; skipping is permitted today), so there are **no illegal combinations to guard**. Booleans are queryable, need no JSON, and make the backfill a trivial per-kind `Exists` check. **Presets are purely a UI layer** that writes these flags — the model never stores "Flat/Chapters/Parts/Full," so adding a true Custom mode later is a UI-only change with zero schema churn.

### 1.2 Presets (UI layer only)

| Preset | uses_parts | uses_chapters | uses_sections | Shape |
|---|---|---|---|---|
| Flat | ✗ | ✗ | ✗ | course → unit |
| Chapters | ✗ | ✓ | ✗ | course → chapter → unit |
| Parts | ✓ | ✓ | ✗ | course → part → chapter → unit |
| Full | ✓ | ✓ | ✓ | course → part → chapter → section → unit |

A single source of truth maps preset key ↔ the three flags (a small module-level dict/list, co-located with the form or in `ordering.py`). A reverse lookup maps a flag-triple → preset key, or `None` (→ display "Custom"). The four presets cover 4 of the 8 possible flag combinations; the other 4 are reachable only by backfill of historically-mixed courses or admin edits and render as **Custom** (read-only label, never an offered radio).

### 1.3 Core behavior change — `legal_child_kinds`

`legal_child_kinds` gains the course's allowed set and intersects:

```python
def legal_child_kinds(parent_kind, allowed_kinds):
    # existing strictly-deeper-by-RANK logic, then keep only kinds in allowed_kinds
    return [k for k in <deeper kinds> if k in allowed_kinds]
```

`allowed_kinds` is passed (not the `Course`) to keep `ordering.py` free of model-instance coupling and trivially unit-testable. Both call sites thread it:

- The `legal_child_kinds` / `primary_child_kind` template tags accept the course (or its `allowed_kinds`) and forward it. `_add_affordance.html` already has `course` in context (it builds the `manage_node_add` URL with `course.slug`), so the template change is to pass `course.allowed_kinds` into the tags.
- `manage_node_add` passes the course's `allowed_kinds` when it validates (Section 4).

**`PRIMARY_CHILD_KIND` generalizes** from a static dict to "the shallowest legal child kind in this course's allowed set," computed from the (already course-aware) legal list: if a scope yields ≥3 legal kinds, the shallowest is `chip--primary` and the rest are `chip--overflow`; <3 legal kinds → no primary, all inline (unchanged rule, now per-course). Worked examples:
- **Flat course, top scope:** legal = `[unit]` → chips `+ Lesson` / `+ Quiz`, no primary, no overflow.
- **Chapters course, top scope:** legal = `[chapter, unit]` (2 kinds) → `+ Chapter`, `+ Lesson`, `+ Quiz` inline, no primary/overflow.
- **Full course, top scope:** legal = `[part, chapter, section, unit]` (≥3) → primary `+ Chapter` (shallowest non-trivial per current intent — see note), overflow `+…` holds the rest. To preserve current UX, keep the **primary = chapter** choice for the top scope when chapter is allowed; otherwise primary = the shallowest allowed kind. (Implementation note: the existing `{None:"chapter","part":"chapter"}` becomes "chapter if allowed at this scope, else shallowest legal" — a small function, not a static dict.)

### 1.4 Enforcement — view layer, not the model

Two layers, following the 3b "the view is the gate" precedent:

- **Builder chips** never offer an excluded kind (driven by the same course-aware function) — the normal path.
- **`manage_node_add`** rejects a POSTed `kind` not in `course.allowed_kinds` (a forged or stale POST must not bypass the policy). Return the same validation failure shape as an illegal-kind add today (422 / re-render), with a clear message.
- **`ContentNode.clean()` is unchanged.** Its strictly-deeper-by-RANK invariant is preset-independent and still correct. The preset is a **course policy**, not a **model invariant** — encoding it in `clean()` would wrongly reject existing valid nodes after a backfill edge case and couples the model to course config. Policy stays at the view/form layer.

---

## Section 2 — UI, migration, legend

### 2.1 Preset picker (create + settings forms)

A segmented/radio **structure picker** with four options (Flat / Chapters / Parts / Full). Each radio shows the preset **name** plus its **chain** (e.g. `Part › Chapter › Unit`) rendered via the existing `kind_label` so it is translated — the chain is the real affordance, so the exact preset *name* is low-stakes.

- **Create form:** default selection **Chapters**. The course is empty, so any choice is conflict-free; the chosen preset writes the three flags on create.
- **Settings form (`CourseForm`):** same picker, current preset preselected. If the course's flags match no preset (backfilled-mixed/admin), the picker additionally shows a read-only **"Custom"** indicator describing the current chain; selecting a named preset overwrites the flags (subject to the narrowing guard below).

The form maps the selected preset key → the three booleans on save (single source of truth from §1.2). The three booleans are **not** edited as raw checkboxes in v1.

### 2.2 Narrowing guard (form-level)

`form.clean()` (settings form; create form is empty so it never triggers) compares the **target** flags against the course's **existing** content. For each level being turned **off**, if any `ContentNode` of that kind exists in the course, raise a precise `ValidationError`:

> *"12 chapters use this level — remove or convert them before switching to Flat."*

(Count is real; the offending kind(s) named.) Turning a level **on** (widening) is always allowed and never validated. Multiple excluded-but-in-use levels → list them. This makes the *only* way to hit the guard a deliberate narrowing of a populated course; widening and new courses never see it.

### 2.3 Data migration

One migration module:

1. **Schema:** add `uses_parts` / `uses_chapters` / `uses_sections` (`BooleanField(default=True)`).
2. **`RunPython` backfill (forward):** for each existing `Course`, set each flag = whether any `ContentNode` of that kind exists in the course (`Exists` / `.filter(course=…, kind=…).exists()`). `unit` needs no flag. Result: a course that only used chapters→units lands on **Chapters**; one that used parts+chapters→units lands on **Parts**; a historically-mixed course (e.g. parts + bare sections, no chapters) lands on a valid **Custom** flag-set. **No content is ever orphaned, by construction** (a level is excluded only if unused).
3. **Reverse:** no-op.

Because the field default is `True`, the backfill *narrows* from Full down to actual usage; a course with content at every level stays Full.

### 2.4 Structure legend (builder)

A small, quiet panel in the builder (`builder.html`) rendering the course's configured chain from `course.allowed_kinds`, e.g. `Chapter › Unit` or `Part › Chapter › Section › Unit`, using the `kind_label` tag (translated). Purpose: answer "what shape is this course?" at a glance and reduce the "so many components, I feel lost" friction. Visual treatment follows existing builder eyebrow/legend styling; light + dark verified via throwaway Playwright screenshots.

---

## Section 3 — Testing (TDD throughout)

- **`Course.allowed_kinds`** — each of the 4 presets' flag-triples (and at least one Custom triple) returns the correct RANK-ordered list, always ending in `unit`.
- **Preset ↔ flags mapping** — preset key → triple and triple → preset key (incl. `None`/Custom) round-trip.
- **`legal_child_kinds(parent_kind, allowed_kinds)`** — intersection correctness across presets: Flat top scope → `[unit]`; Chapters top → `[chapter, unit]`; Full top → all four; deeper scopes filtered (e.g. Chapters course never yields `part`/`section`).
- **Primary/overflow generalization** — primary = chapter when allowed at the scope, else shallowest legal; <3 legal kinds → no primary.
- **`manage_node_add` server guard** — a forged POST adding an excluded kind (e.g. `part` in a Chapters course) is rejected; an allowed kind still succeeds.
- **Narrowing guard** — disabling an in-use level fails with the counted message; disabling an unused level and any widening pass; create form (empty course) never triggers it.
- **Migration backfill** — fixture courses: chapters-only ⇒ Chapters flags; parts+chapters ⇒ Parts flags; mixed ⇒ the exact in-use triple (Custom); all-levels ⇒ Full; empty course ⇒ default Full.
- **Builder template** — renders only allowed `+` chips for a given course; **legend** renders the configured chain.
- **i18n** — preset labels, legend, and validation messages have EN + PL; `.mo` compiled; no fuzzy flags.

## Open / confirm at implementation

- Exact `Course` create-view/form wiring (field names, template include) — confirm against `courses/forms.py` + create template.
- Final builder placement/markup of the legend panel — settle during the frontend-design pass (screenshots).
- Preset display names ("Parts" especially) — adjustable; the chain shown beside each makes the name low-stakes.

## Tooling / conventions

`uv run ...` (bash `ruff`/`pytest`/`python` are NOT on PATH); `uv run ruff check --fix && uv run ruff format` per task; EN+PL `{% trans %}` + compile `.mo` (watch makemessages fuzzy-flag re-marking); verify builder light + dark via throwaway Playwright screenshots (delete-after-review). Subagent-driven build (fresh implementer + two-stage review per task) per recent cycles.
