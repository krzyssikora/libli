# Phase 2d-ii — Drag-to-image — Design

**Status:** spec (brainstormed 2026-06-21)
**Slice:** Phase 2d-ii — the second slice of the Phase 2d split. Adds the **8th question type, drag-to-image**: the student drags/assigns text (or KaTeX) labels onto author-defined **rectangle zones** drawn over an image. It is a third consumer of the **2d-i drag-and-drop substrate** (`courses/dnd.py`): the answer is the same `{target → token}` shape (each zone is a target, the pool is the set of labels), so `build_pool`, `mark_slots`, the `getlist("slot")` payload, the withhold/feedback state machine, and the resume/results paths are **reused unchanged**. The genuinely new work is **the image overlay rendering, the rectangle-zone authoring canvas, and a shared touch (tap-to-assign) enhancement** added to `dnd.js`.
**Predecessors:** 2a (the `QuestionElement` abstract base, `MarkResult`, `mark()`/`build_answer()`, the answer→submit→feedback round-trip with JS-fragment + no-JS transports, `render()` per-type dispatch, `REVEAL_TEMPLATE`, the no-leak/IDOR/CSRF invariants). 2b (`normalize_text`, the `_accepted_lines` newline splitter). 2c (the `marking_mode`/`max_attempts`/`max_marks` fields on `QuestionElement`; the `QuizSubmission`/`QuestionResponse`/`Attempt` persistence; the withhold-until-exhausted/correct feedback state machine; the quiz-vs-lesson render `mode`). **2d-i** (the whole substrate: `dnd.build_pool`, `dnd.mark_slots`, `dnd._render_select`/`render_selects`/`render_match_rows`, the `expected_tokens()` contract, `static/courses/js/dnd.js`, `_MarkingFieldsMixin`, the choice/match-pairs **inline-formset** authoring plumbing, and the §4.4 per-type registration touchpoints). All file references are to the post-2d-i (PR #24) tree on `master`.

---

## 1. Purpose & scope

### 1.1 Phase 2d decomposition (recap)

Phase 2d is sub-split into three slices, each its own spec → plan → build cycle:

- **2d-i — DnD substrate + drag-fill-blanks + match-pairs (DONE, PR #24):** the shared progressive-enhancement substrate, proven by the two "assign tokens to slots" types.
- **2d-ii — drag-to-image (this slice):** the third DnD type — drag labels onto author-defined rectangle zones over an image — built on the now-proven substrate; adds the image + drop-zone authoring UI (the heaviest single authoring piece in Phase 2) and a shared **touch tap-to-assign** enhancement.
- **2d-iii — extended-response + the `[R]` human-review path:** the 9th type (long free text, required/forbidden keywords) + the first `[R]`-native student-facing "awaiting review" states. (The teacher review *queue* stays Phase 3 — it needs groups.)

"2e — Results & metrics" is unchanged and still follows. After this slice, **8 of 9** question types exist (only extended-response remains).

### 1.2 What this slice IS / IS NOT

**Is:** one new `QuestionElement` subclass + its `DragZone` sub-row model, one form (+ inline formset), per-type render + reveal templates, a new **zone-authoring canvas** JS module, a **tap-to-assign** addition to the shared `dnd.js`, marking via the reused substrate, one migration, i18n, and tests. Works in **both** lesson units (formative, always-reveal) and quiz units (persisted, attempt-capped, withhold-gated) by reusing the existing dispatch.

**Is NOT (deferred / out of scope):**
- **No extended-response / `[R]`-native type** (2d-iii) and **no results/metrics dashboards** (2e).
- **No new view functions, URLs, or persistence model.** `QuizSubmission`/`QuestionResponse`/`Attempt` and the `check_answer`/`quiz_answer`/`quiz_finish`/`quiz_results` views are reused unchanged; `latest_answer` stores this slice's payload (the same token-text list shape every DnD type uses). As in 2d-i, **"no new views" does NOT mean "zero existing-code edits"** — the per-type registration touchpoints in §5 must all be wired.
- **Rectangles only** (locked in brainstorming) — no points/pins, polygons, or circles. A point need is expressible as a small rectangle; multi-shape support is an explicit non-goal for this slice.
- **No "consume-once" tokens** — labels are reusable and the pool never depletes (substrate rule); a label may be the correct answer for more than one zone.
- **No line-drawing / connector UI.** The presentation is "labels → zones," consistent with the substrate.
- **No change to existing types** beyond the **additive, behaviour-preserving** tap-to-assign in `dnd.js` (§4.2) and the enumerated §5 registration edits.

### 1.3 The four brainstormed decisions (locked)

1. **Zone shape = axis-aligned rectangles only.** Stored as **fractional** `x/y/w/h` (0–1) of the image box so zones scale to any rendered image size and never depend on pixel dimensions.
2. **Student rendering / no-JS fallback = "numbered badges + select list below" (layout A).** Each zone gets a CSS-absolute number badge over the image; **below** the image a numbered list of native `<select name="slot">` (one per zone), badge-number ↔ row-number. The selects never overlap the image (mobile-safe, long/KaTeX labels fit) and are the no-JS source of truth. JS enhancement overlays real drop targets on the rectangles + a chip pool.
3. **Authoring = draw-rectangle canvas + per-zone label list.** Reuse the existing `MediaAsset` image picker (the one `ImageElement` uses); the author drags to draw a rectangle, clicks to select/resize, ⌫ deletes; each zone row carries its `correct_label`. Distractors textarea + the shared marking mixin, exactly as the other DnD types. A no-JS authoring fallback exposes numeric `x/y/w/h` fields per zone.
4. **Touch = add tap-to-assign to the shared substrate.** `dnd.js` gains a **tap-a-chip-then-tap-a-target** (and tap-to-clear) interaction that benefits **all three** DnD types, not just this one. It still only ever **sets the `<select>` value** — drag, keyboard, and no-JS paths are unchanged.

### 1.4 Marking (reused verbatim from the substrate)

Each zone is a target with **exactly one expected token** (`DragZone.correct_label`). Marking is per-zone, identical to drag-fill/match-pairs:

- `pool = dnd.build_pool(self)` = correct labels (in `zones` order) + `_accepted_lines(distractors)`, de-duplicated by `normalize_text`, deterministic order (§2d-i `build_pool`).
- `n_correct, reveal = dnd.mark_slots(expected, pool, chosen)`; `fraction = n_correct / n_zones` (partial credit); `correct = (n_correct == n and n > 0)`.
- Token **text** is the value (pool-order-independent, stable against author reorder/distractor edits; only deleting the exact chosen label drops a zone to unfilled). Forged / non-member labels score wrong, never error (membership tested on the `normalize_text` form).
- Case-insensitive matching (substrate default; no `case_sensitive` field on this type, consistent with drag-fill/match-pairs).
- Only the auto-markable `[A]` path is exercised here; `[N]`/`[R]` modes already exist on the base from 2c and behave for this type exactly as for every other — recorded, no per-target reveal — with **no `[R]`-native UI** (that is 2d-iii).

### 1.5 Non-goals

No new dependency. The zone-authoring canvas and the tap-to-assign enhancement are small vanilla-JS additions (no DnD/canvas library), consistent with the project's bespoke, no-framework front end. No change to `MarkResult` (`correct`/`fraction`/`reveal`). No change to the substrate's marking/pool functions (they are consumed as-is; only a new render helper and a new touch handler are added).

---

## 2. Data model (`courses/models.py`)

One new concrete `QuestionElement` subclass + one sub-row model → **one migration adding both tables**. The subclass declares `elements = GenericRelation(Element)` (the 1a GFK join-row) and a `REVEAL_TEMPLATE`.

### 2.1 `DragToImageQuestionElement`

```
class DragToImageQuestionElement(QuestionElement):
    """Drag labels onto author-defined rectangle zones over an image. Marking is
    per-zone via the shared DnD substrate; each zone's correct token is a DragZone row.
    `stem` (inherited) is the optional prompt above the image."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_dragimage.html"

    media = models.ForeignKey(
        "MediaAsset", on_delete=models.PROTECT, limit_choices_to={"kind": "image"}
    )                                            # same pattern as ImageElement
    alt = models.CharField(max_length=255, blank=True)   # image alt text; "" = decorative
    distractors = models.TextField(blank=True)           # newline-delimited wrong labels
    elements = GenericRelation(Element)

    def expected_tokens(self):
        # Order is load-bearing: expected_tokens()[n] must align with zone n (the nth
        # <select name="slot"> and the nth badge). DragZone.order mirrors the formset/
        # authored order — keep zones order stable; never reorder rows independently.
        return [z.correct_label for z in self.zones.all()]

    def build_answer(self, post):
        return post.getlist("slot")

    def mark(self, answer):
        from courses import dnd
        expected = self.expected_tokens()
        pool = dnd.build_pool(self)
        n_correct, reveal = dnd.mark_slots(expected, pool, answer)
        n = len(expected)
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=reveal,
        )
```

- `on_delete=PROTECT` for `media` mirrors `ImageElement` (a `MediaAsset` cannot be deleted while an element references it). The `limit_choices_to` keeps admin/forms to image-kind assets; the form additionally scopes the queryset by **course** via `_CourseScopedMediaForm` (§4.1).
- `mark`/`build_answer`/`expected_tokens` are byte-for-byte the drag-fill shape — the only difference from `DragFillBlankQuestionElement` is `zones`/`correct_label` instead of `dragblanks`/`correct_token` and the absence of a token-stem (zones are spatial, not inline in `stem`). `dnd.build_pool(self)` works unchanged because it calls `self.expected_tokens()` + `self.distractors` (the substrate's only two requirements of a question).

### 2.2 `DragZone`

```
class DragZone(models.Model):
    question      FK(DragToImageQuestionElement, on_delete=CASCADE, related_name="zones")
    correct_label CharField(max_length=500)    # plain text + KaTeX; never sanitised
    x  FloatField()   # left,  fraction 0..1 of image width
    y  FloatField()   # top,   fraction 0..1 of image height
    w  FloatField()   # width, fraction 0..1
    h  FloatField()   # height,fraction 0..1
    order  OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]
```

- `related_name="zones"` is distinct from `blanks`/`dragblanks`/`pairs` (consistent with 2d-i's deliberate distinct names; the prefetch is `"zones"`, §5).
- **Coordinate validation** lives in `DragZone.clean()` *and* is enforced by the formset/form (`clean` so it holds for admin/fixtures too): `0 ≤ x ≤ 1`, `0 ≤ y ≤ 1`, `0 < w ≤ 1`, `0 < h ≤ 1`, `x + w ≤ 1 + ε`, `y + h ≤ 1 + ε` (small `ε` for float rounding from the canvas). A zone with `w` or `h` of 0 is rejected (degenerate, undroppable). Out-of-range coords from a forged/buggy client surface as a friendly form error, never a render that overflows the image.
- `correct_label` follows the **MCQ `Choice.text` convention**: plain text + KaTeX delimiters (`\(x^2\)`), **never HTML-sanitised**, `max_length=500` (matching `Choice.text`/`DragBlank.correct_token`). The form validates length ≤ 500 (a bound `CharField` on the formset `ModelForm`, so Django enforces it automatically — no extra check needed).

### 2.3 Persistence (reused, unchanged)

In a quiz, `QuestionResponse.latest_answer` (and each `Attempt.answer`) stores the **ordered list of chosen label-text strings**, one per zone, `""` for an unfilled zone — exactly what `build_answer` returns and what drag-fill/match-pairs already store. No schema change (the 2c JSONField accepts any type-specific shape).

- **Resume rehydration:** `quiz.rehydrate(question, latest_answer)` returns `(selected_ids=set(), submitted_values=latest_answer)` via its default (non-choice) branch — this type falls into that default **unchanged**. The template consumes `submitted_values` through a new `dnd.render_zone_selects(zones, pool, chosen)` helper (§3.1) that pre-selects the option whose **normalized** value equals `chosen[i]`, or the placeholder if empty / no-longer-a-member (deleted label) — same semantics as `_render_select`.
- **Edit-during-resume safety:** because stored values are label *text* (not a positional pool index), a mid-quiz author edit that reorders zones, moves a rectangle, or adds/removes distractors leaves every still-valid placement correct on resume; only deleting the exact chosen label drops that zone to unfilled. (Stored `fraction` is still not re-marked against edited expected answers — the 2c §5.2 limitation; all moot once `submitted`.)

---

## 3. The substrate: rendering, transport & marking

### 3.1 Rendering (`render()` + new helper + new templates)

`DragToImageQuestionElement` inherits `QuestionElement.render(...)` (it dispatches to `courses/elements/dragtoimagequestion.html` by `self._meta.model_name`). The template:

- Renders the optional `stem` (sanitized rich text) above the image.
- Renders the **image** (`el.media.file.url`, `alt=el.alt`) inside a positioned wrapper, with a **CSS-absolute number badge per zone** placed at the zone's fractional `x/y` (badge shows `forloop.counter`). **Each badge carries `data-zone="{index}"` and `data-x/data-y/data-w/data-h` (the fractions)** — these are the single carrier of zone geometry the JS reads (§4.2). Badges are pure CSS — present and positioned with JS off.
- Renders, **below** the image, the numbered list of `<select name="slot">` via a new **`dnd.render_zone_selects(zones, pool, chosen)`** helper (a sibling of `render_match_rows`): an `<ol class="dnd__rows">` of `(badge number, <select>)` rows in `zones` order, each `<select>` built by the existing `dnd._render_select(pool, chosen[i])` (leading "— choose —" placeholder, normalize-aware pre-selection, every option value+label `format_html`-escaped). `name="slot"` is uniform with the other DnD types, so `build_answer` is `post.getlist("slot")`.

`render_zone_selects` is the only new substrate function; it mirrors `render_match_rows` exactly but emits a number badge instead of a `left` label. **Index is the join key:** the nth badge (`data-zone="n"`), the nth `<select>`, and `expected_tokens()[n]` all refer to the same zone (all built from `self.zones` in `["order","pk"]` order); the JS zips badge[i] ↔ select[i] by index. Geometry lives only on the badges (not duplicated onto the select rows).

**JS enhancement (`dnd.js`, extended — §4):** the script finds the block's `<select name="slot">`s and the zone geometry, hides the selects, overlays an absolutely-positioned **drop target** per zone on the image (from the fractional coords × the rendered image box), and shows the chip pool. Drop **or tap** sets the corresponding `<select>` value (+ dispatches `change`) — the server payload is identical whether the student dragged, tapped, or used the dropdown. Pure decoration: if it throws or never loads, the numbered selects remain fully usable.

- New `_reveal_dragimage.html` mirrors `_reveal_fillblank.html`: iterate the `reveal` tuple (`{index, correct, accepted}`), show each zone's number + the expected label, marked correct/incorrect. (No `left` augmentation — drag-to-image uses the 3-key dict as-is, indexed by zone order.)

**Positional invariant (load-bearing).** Marking pairs `getlist("slot")[i]` with `expected[i]` purely by **position**, so the template MUST emit exactly one `<select name="slot">` per zone in `self.zones` order (the same `["order","pk"]` order `expected` is built from). Browsers submit same-named controls in document order, so `getlist` preserves it. The JS **must not reorder/add/remove the `<select>` nodes** (it hides them and overlays targets in place). Asserted by a test that submits after JS enhancement and checks the recorded answer matches the zones in order.

**Progressive enhancement.** With JS off: image + numbered badges + numbered `<select>` list + submit = a complete, working question, **no orphaned UI** (the chip pool and on-image drop targets are JS-injected, absent without JS). With JS on: drag, tap, or dropdown — all three converge on the `<select>` value.

### 3.2 Marking (`build_answer` + `mark`) — reused

`build_answer(self, post)` → `post.getlist("slot")` (a list of submitted label-text strings, `""` for unfilled; no pad/truncate — length normalization to `n_zones` lives in `mark_slots`'s defensive `chosen[i]`-for-`range(n_zones)` reading). `mark(self, answer)` reconstructs `expected` (= `expected_tokens()`) and `pool` (= `dnd.build_pool(self)`, the same function `render` uses) and calls `dnd.mark_slots` — see §1.4. Forged/edited-away labels score wrong, never error. Because `mark` touches `self.zones`, the quiz/lesson render paths must prefetch `"zones"` (§5). `fraction` is a `float`; the 2c quiz boundary converts to `Decimal` and quantizes (`fraction × max_marks`), unchanged.

### 3.3 Feedback & the withhold rule (reused)

In a **lesson** (formative): always-reveal `_question_feedback.html` + `_reveal_dragimage.html`, like every 2a/2b/2d-i type. In a **quiz**: the 2c withhold state machine unchanged — pre-reveal (wrong, attempts remain) shows only "Incorrect — try again (N left)" with no `reveal`; reveal (correct, or wrong-on-last-attempt) renders the per-zone reveal. The no-leak invariant holds by reusing 2c's reveal-gated context construction; this type adds no new path that could leak an expected label.

**Empty-answer guard (quiz path, 2c §3.1 step 3):** "empty" = **every** zone unset (all `slot` values `""`) → rejected without burning an attempt; a partially-filled submit is a real attempt with partial credit (consistent with fill-blank / the other DnD types). Reuses `quiz.answer_is_empty`'s list-branch unchanged.

**`[N]`/`[R]` behaviour (unchanged from 2c):** `[N]` records the token-text payload + standard "Answer recorded" ack, no per-zone reveal, no score; `[R]` records + "awaiting review". No `[R]`-native UI (2d-iii).

---

## 4. Front-end JS

### 4.1 Authoring canvas (new module `static/courses/js/zone-editor.js`)

A small vanilla-JS module that turns the image + the `DragZone` inline formset into a draw-on-image editor. It does **not** invent its own persistence — it reads/writes the **formset's hidden coordinate fields** (`x/y/w/h` per form row), so the server sees a normal formset POST.

- On load: reads existing formset rows, draws each as a rectangle overlay on the image at its fractional coords, with its number badge + linked label input.
- **Draw:** pointer-drag on the image creates a new rectangle → appends a new formset row (via the formset's `TOTAL_FORMS` empty-form template, the same mechanism the choice/match-pairs add-row uses) and writes its fractional coords.
- **Select / resize / move:** clicking a rectangle (or its label row) selects it (highlight both); drag handles resize, drag body moves; coords written back as fractions, clamped to `[0,1]` and `x+w,y+h ≤ 1`.
- **Delete:** ⌫ / a row ✕ marks the formset row `DELETE` (standard Django formset deletion) and removes the overlay.
- **No-JS fallback:** with the module absent, the formset still renders its rows with **numeric `x/y/w/h` inputs** (plain number fields) + the label input — authoring remains possible (rarely needed, but keeps the no-JS invariant true on the authoring side too).

The coords are stored as fractions, so the editor is resolution-independent and the same numbers drive student rendering.

### 4.2 Tap-to-assign in the shared substrate (`static/courses/js/dnd.js`, extended)

Additive, behaviour-preserving change benefiting **all three** DnD types:

- Today `enhance()` builds draggable chips + per-target drop slots and wires `dragstart`/`drop` + a keyboard re-show. **Add a tap interaction:** tapping (click) a chip selects it (visual "armed" state); tapping a target then assigns the armed chip's token to that target's `<select>` (+ `change`) and disarms; tapping a **filled** target with no chip armed **clears** it (sets `<select>` to `""`). Tapping the armed chip again disarms it.
- This reuses the existing `setSelect(sel, value)` path — the `<select>` stays the single source of truth; drag, keyboard, and no-JS are all unchanged. For drag-to-image the "targets" are on-image zone overlays the JS builds from each badge's `data-x/y/w/h` (§3.1) × the rendered image box, linked to `select[i]` by the `data-zone` index; for drag-fill/match-pairs they are the existing inline slots — the same code path, so a tap works everywhere.
- Idempotent via the existing `data-dndReady` guard; `window.libliEnhanceDnd` re-enhance hook unchanged (the manage live-preview keeps working).

---

## 5. Existing-code touchpoints (per-type registration)

As established in 2d-i §4.4, a new question type is wired through many hard `isinstance`/enumerated/`type_key` points; none pick up a new subclass automatically. Each must be done for `dragtoimagequestion` (confirmed against the post-2d-i tree). Where a 2d-i hook already generalised a branch, reuse it; otherwise add the enumerated edit alongside the existing DnD types.

**Consumption (`courses/views.py` / `courses/quiz.py`):**

- **Prefetch (perf).** In `lesson_unit`/`quiz_unit`, build `dragimage_qs` and `prefetch_related_objects(dragimage_qs, "zones")` **guarded by `if dragimage_qs:`** (alongside the existing `blanks`/`dragblanks`/`pairs` prefetches). Without it, `mark`/`render` rebuilding the pool from `self` triggers N+1.
- **KaTeX detection (lesson path only).** Add a branch to `_question_has_math` (the closure in `build_lesson_context`) for this type, scanning `stem` + every `DragZone.correct_label` + `distractors`. (The quiz path's `build_quiz_context` already sets `has_math = bool(questions)`, so it needs no change.)
- **Question-CT gate (lesson path only).** Add `DragToImageQuestionElement` to the `question_models`/`question_ct_ids` list backing `has_questions` in `build_lesson_context` (the quiz path hardcodes `True`).
- **Resume / JSON round-trip.** `quiz.rehydrate`, `quiz.answer_from_json`, `quiz.answer_to_json` all branch on `ChoiceQuestionElement` and fall through to a default that passes the list through unchanged — this type uses that default on **all three** (the token-text list is a plain `list`). A test pins it on the default path (a future refactor mustn't route it through the choice branch).
- **Results-page reveal (`quiz_results` / `_results_row`).** Works **generically**: the type implements `mark` (rebuilds the pool, returns the `{index, correct, accepted}` reveal tuple) and sets `REVEAL_TEMPLATE`, so `_results_row` needs **no new per-type branch** (the new `_reveal_dragimage.html` consumes the reveal tuple, no `choices`-style augmentation). The "accepted N+1" stance of `_results_row` extends unchanged (no prefetch added on the results path).

**Authoring (`courses/views_manage.py` / `courses/builder.py` / templates):**

- **Add-element menu.** `templates/courses/manage/editor/_add_menu.html` gains a button `data-add-type="dragtoimagequestion"` with an icon + i18n label.
- **`type_key` allowlists.** `views_manage.element_add` and `views_manage.element_save` each have a hard-coded allowlist tuple — add `"dragtoimagequestion"` to **both**, or open/save 400s with "bad type".
- **Host-form / formset render.** `_render_open_form`, the element-edit open path, and the 422 invalid-re-render path special-case the inline-formset types (`build_choice_formset` / `build_matchpair_formset`). Add `build_dragzone_formset` wired at **all three** points and rendered by the host-form template (the canvas JS attaches to it).
- **`builder.save_element` persist branch.** The `elif type_key` chain drives sub-row creation. Add a `dragtoimagequestion` branch mirroring the **formset-save** types (`choicequestion`/`matchpairquestion`): save the element, then save the `DragZone` formset (create/update/delete rows). Without it, the element saves with **zero zones**.
- **`FORM_FOR_TYPE`.** Register `"dragtoimagequestion": DragToImageQuestionElementForm` in `courses/element_forms.py`.

---

## 6. Authoring forms (`courses/element_forms.py`)

- **`DragToImageQuestionElementForm(_CourseScopedMediaForm, _MarkingFieldsMixin)`** with `media_kind = "image"` and fields `["media", "alt", "distractors"]` + the marking fields from the mixin. `_CourseScopedMediaForm` scopes the `media` queryset to the course's image assets and re-validates course+kind (reused verbatim from `ImageElementForm`); `media` is required.
- **`DragZone` inline formset** (`build_dragzone_formset`, sibling of `build_choice_formset`/`build_matchpair_formset`): fields `correct_label`, `x`, `y`, `w`, `h`, `order`; `extra=0`, `can_delete=True`, `min_num=1`, `validate_min=True` (≥1 zone). Per-row validation: `correct_label` non-blank; coords in range (mirrors `DragZone.clean`, so the friendly error shows on the form). The `x/y/w/h` fields are plain number inputs (the canvas writes into them; no-JS authoring uses them directly).
- The marking fields show only for quiz units and hide `max_marks`/`max_attempts` for `[N]`/`[R]` — inherited verbatim from `_MarkingFieldsMixin` (no new logic).

---

## 7. Invariants, edge cases & testing

### 7.1 Invariants
- **No-JS parity:** with JS off, the type is fully answerable (image + numbered badges + `<select>`s + submit) and fully **authorable** (numeric coord fields). Asserted by no-JS e2e.
- **No-leak (reused):** accepted labels reach the client only in a revealing state; the quiz withhold path is 2c's, untouched. Regression test: pre-reveal JS fragment and answered-not-correct resume render contain no expected-label text (scoped to the question wrapper, like 2c §5.1).
- **Server-authoritative marking:** submitted labels validated server-side for pool membership; forged/non-member labels score wrong, never error. The client cannot self-report correctness, and **forged coords cannot affect marking** (coords are authoring-only; marking is pure text vs `correct_label`).
- **Transport-agnostic:** dragged, tapped, and dropdown submissions are byte-identical to the server (asserted by submitting the same answer all three ways and comparing the recorded `Attempt`).
- **Positional integrity:** after JS enhancement, a submit yields a recorded answer whose per-zone values match the zones in document order (guards §3.1 against any JS DOM reordering).

### 7.2 Edge cases (handled explicitly)
- **Fractional coords scale:** the same stored zone renders correctly at any image display size (badge + drop target computed from fractions × rendered box).
- **Overlapping zones:** permitted (author's choice); drop/tap resolves to the topmost overlay (`z-index`/document order); marking is per-zone and unaffected. (Documented, not validated against.)
- **Degenerate zone (w or h = 0):** rejected at form/`clean` (undroppable).
- **Distractor-only label** never matches any zone; **reusable label** satisfies multiple zones sharing it; **normalize-equal labels** de-duplicate to one pool chip (both sides normalized at mark). All inherited from the substrate.
- **Partially-filled quiz submit** = real attempt with partial credit; **all-empty** = rejected without burning an attempt.
- **Author edits mid-quiz** (reorder zones / move rectangle / add-remove distractor) leave valid placements intact on resume; only deleting the exact chosen label drops a zone to unfilled.
- **KaTeX in a label** renders in chip, select option, and reveal (plain text + delimiters; never sanitised).
- **`media` is PROTECT-referenced:** deleting the asset while the question references it is blocked (mirrors `ImageElement`).

### 7.3 i18n
All new strings (validation messages, "— choose —" reuse, "Drag or tap a label here" / drop-target placeholder, "Draw a zone" / canvas hints, reveal labels, add-menu label) wrapped for EN/PL, matching the 2b/2c/2d-i passes.

### 7.4 Testing
- **Unit/integration (pytest + factory_boy, real PostgreSQL):** `DragZone` coord validation (in-range OK; out-of-range / `x+w>1` / `w=0` rejected); `build_pool`/`mark_slots` reuse for this type (full / partial / zero / reusable-label / distractor-picked / forged-non-member / **two raw-distinct-but-normalize-equal labels**); empty-answer guard (all-`""` empty, any label non-empty, incl. a label whose text is `"0"`); quiz scoring of a partial answer via the 2c `Decimal` boundary; `[N]` recorded-no-score (no reveal). **Re-mark stability** (stored answer re-marked after a fresh render yields the same `fraction`). **Edit-then-resume** (reorder zones / move rectangle / add distractor → placements rehydrate unchanged & re-mark identically; delete chosen label → that zone unfilled). **Resume routing** (`rehydrate`/`answer_from_json`/`answer_to_json` stay on the default branch). **Results-page reveal** (`_results_row` re-marks via `mark(answer_from_json(...))` for answered / partial / **unanswered** (`mark(build_answer(empty))`) rows). New `factory_boy` factories for the type + `DragZone`.
- **e2e (Playwright, JS + no-JS, + a touch/tap path):** author the type (pick image, draw ≥2 zones, label them, add distractors + marking) → student answers via **drag** (JS), **tap-to-assign** (the new touch path), and **`<select>`** (no-JS), submits, sees correct/partial feedback; in a quiz, exhausts attempts and sees reveal, asserts **no label leak** pre-reveal, asserts resume rehydrates placements after reload. **Slot-order integrity** after JS enhancement. **Tap == drag** payload equality.

### 7.5 Migration
One migration adds `DragToImageQuestionElement` + `DragZone`. No alteration to existing tables (the marking fields are already on the base from 2c's 0015). Passes the existing migration-consistency gate.
