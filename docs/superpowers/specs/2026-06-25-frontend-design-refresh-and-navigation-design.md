# Frontend design refresh + unit navigation, quiz-review roster, code-editor fields

**Date:** 2026-06-25
**Status:** Design (brainstormed, mockups accepted)
**Accepted mockups:** `docs/mockups/unit-nav-desktop.html`, `unit-footer-progress.html`,
`code-editor-field.html`, `quiz-review-roster.html` (mobile drawer + force-submit
behaviour described in this spec).

## 1. Goal & context

Many libli pages have not kept pace with the design language established in recent
phases (the catalog "shelf", the outline "syllabus", the manage "control desk", the
grouping pages, the mobile nav). Rather than restyle pages piecemeal, this effort
applies the **existing** token-driven warm-teal language consistently across the
remaining in-scope pages **and** adds three navigation/interaction improvements the
user asked for.

This is **not a reskin** — the visual identity (warm teal `#147E78` + amber accent,
Inter, warm off-white surfaces, soft shadows, the established `.btn`/`.badge`/`.card`/
`.outline-*`/`.manage`/`.catalog__*` vocabulary in `core/static/core/css/app.css`,
`tokens.css`, `courses.css`) stays. The work is **extension + consistency + three
features**.

### In scope (page areas, confirmed)
- **Student consumption:** `core/home.html`, `courses/my_courses.html`,
  `courses/quiz_results.html`, `courses/course_results.html`, the question
  **feedback/reveal** partials.
- **Element display polish:** the 9 question-type widgets + math/image/video/iframe/
  html element rendering — spacing, states, focus, dark-mode consistency.
- **Authoring UI:** course builder, element editor, marking fields, media manager
  (heaviest surface — the final, lighter batch).
- **Three features:** unit-page navigation; quiz-review roster; code-editor author
  fields.

### Out of scope
- **Account & system pages** (login/signup/password flows, accept-invite, user &
  institution settings, 403/404/500) — styled recently, excluded by the user.
- **Django admin** — separate, untouched.
- **Syntax highlighting** for the code-editor fields (no vendored editor library now;
  plain monospace only).
- Any change to sandbox execution, scoring, enrollment, or review *semantics* beyond
  the new force-submit-all action.

## 2. Structure — one spec, five sequenced batches

Approach 1 (foundation-first). One spec; the implementation plan splits into ordered,
independently shippable batches, each its own branch/PR:

1. **Design foundation + consistency pass** — extract the shared primitives that are
   independently testable now (a `code-field` style, **results/stat** components) and
   restyle the static student pages (`home`, `my_courses`, `quiz_results`,
   `course_results`) + element/feedback polish. **No behaviour change.** (The two-column
   **unit shell** primitive is built in **batch 2** — see below — because a CSS-only
   primitive with no consumer can't be verified in isolation.)
2. **Unit-page navigation feature** — tree sidebar + Prev/Next + footer progress +
   mobile drawer.
3. **Quiz-review roster feature** — sibling list + Force-submit-all.
4. **Code-editor author fields.**
5. **Authoring UI (editor/builder) restyle** — lighter pass, last.

Batches 2–4 build on primitives defined in batch 1 (the `code-field` CSS and the
results/stat components). The collapsible two-column **unit shell** (including its
left-rail collapse CSS) is built in **batch 2** as its first task — the tree/footer give
it a real consumer and test there — and its CSS lives in shared `courses.css` so that
**batch 3** (the review roster) reuses the same shell classes rather than depending on
batch 2's templates. Each batch
lands green (full suite + ruff + e2e) before the next starts.

## 3. Feature: unit-page navigation

### 3.1 Layout — the "unit shell"
A two-column wrapper shared by `lesson_unit.html` and `quiz_unit.html`:
- **Left:** the course tree (collapsible).
- **Right:** the unit content (existing `<article class="lesson">` / `.quiz`).
- **Footer:** a bar spanning the content column with Prev/Next + progress
  (mockup `unit-nav-desktop.html` option A + `unit-footer-progress.html` option B).

Implemented as a new partial (e.g. `courses/_unit_shell.html`) that both unit
templates include, plus CSS in `courses.css`.

### 3.2 Data — `build_unit_nav(course, user, current_node)`
A new **pure** service (mirrors the `build_lesson_context` pattern, lives alongside
the outline rollups) returning:
```
{ tree, prev, next, part_progress, course_progress }
```
- `tree` — reuses `rollups.build_outline(course, user)`, which returns a **list** of
  top-level part dicts (each with `completed` + required/additional rollups), not a
  single root object. No new query cost.
- `prev` / `next` — neighbours from `units_in_order(course)` (see 3.4).
- `part_progress` / `course_progress` — see 3.5. `build_unit_nav` exposes the
  course-level aggregate (summed across the `build_outline` list — see 3.5), since no
  course-wide root total exists on the list itself.

`current_node` is the `ContentNode` model instance (the `unit` already in both views'
context); the current unit's **top-level part** (§3.5) is resolved by following the
`parent_id` chain up to the depth-1 ancestor. Both unit views call it and add its result
to the template context so the two cannot drift. Untracked previewers (not enrolled)
still get a tree; completion is simply all-false.

### 3.3 The tree (`courses/_unit_tree.html`)
- Renders the **full** structure (parts → chapters → sections → units), adapting the
  existing `_outline_node.html` visual vocabulary (`.outline-node--{kind}`).
- Current unit highlighted teal with `aria-current="page"`; completed units carry the
  `✓` badge; the current unit is **auto-scrolled into view** on load (JS
  `scrollIntoView({block:"center"})`, guarded for reduced motion). Auto-scroll runs
  **only when the tree is expanded** and **after** the collapse-state restore — it is
  suppressed in the rail (collapsed) state, where labels are hidden.
- Wrapped in a `<nav aria-label="Course contents">` landmark.
- **Desktop:** visible by default; a `‹` toggle in the tree's header strip collapses it
  to a thin rail (content widens). The collapsed/expanded choice is **desktop-only**
  state persisted in `localStorage` (key `libli_unit_tree_collapsed`). To avoid a flash,
  a **new** small pre-paint inline script reads that key (inside a `try/catch` —
  `localStorage` can throw in private/sandboxed modes; default to expanded on failure)
  and sets the collapse class on the **root `<html>` element** (which already exists when
  a `<head>` script runs — the
  body shell wrapper does **not** yet, so the class cannot target it directly). The unit
  CSS scopes the collapsed-rail state from `html.<collapse-class> .unit-shell …`. (Note:
  the existing pre-paint theme script reads a **cookie**, not `localStorage`, and also
  writes to `<html>` — this is a *separate* script that follows the same
  run-before-paint-on-`<html>` pattern, not the same storage mechanism.)
- **Mobile (≤640px):** the inline tree is hidden; a teal round button fixed in the
  **bottom-right** corner opens a bottom **drawer** containing the same tree, scrolled
  to the active unit. Drawer: dimmed scrim, `‹`/✕ close, closes on scrim tap **and**
  Esc, focus-trapped while open, `prefers-reduced-motion` aware. The collapse toggle
  sits in the tree's own header strip so it never overlaps content. The tree button
  takes the bottom-right corner **unconditionally**: today the only nearby control, the
  `Finish quiz` button on `quiz_unit.html`, is an in-flow form button (not fixed), so
  there is no conflict. Rule for the future: any new *fixed* bottom-right control must
  offset above the tree button rather than overlap it.
- **Responsive boundary:** the mobile drawer always loads **closed** and its open/closed
  state is independent of the desktop `localStorage` collapse key (the key governs only
  the desktop rail). If the viewport crosses 640px while the drawer is open, the drawer
  closes (the desktop inline tree takes over); there is no shared open state to carry.

### 3.4 Prev / Next — `units_in_order(course)`
- A new helper returning the **flat list of all leaf units in outline order**
  (depth-first over `course.nodes` by `order`, units only), crossing chapter/part
  boundaries. To make divergence **structurally impossible**, introduce one shared
  private generator `_walk_preorder(course)` that yields nodes in `(parent_id, order)`
  **pre-order** (a single pass over `course.nodes`): `build_outline` folds it into its
  nested-dict tree, the new `units_in_order` filters the yield to `is_unit` leaves, and
  the **existing `quiz_units_in_order`** (today a parallel walk in `rollups.py`) is
  rewritten as `units_in_order` filtered to quiz units. Inside `build_unit_nav`, Prev/Next
  are taken from the `is_unit` leaves of the **already-computed** `build_outline` result
  (no extra query) — identical order to `units_in_order` because both originate from
  `_walk_preorder`. `units_in_order` collects
  **every** node where `is_unit` is true — both lessons **and** quizzes — independent of
  the `required_*` rollups (quizzes have `required_total == 0` but are still navigable
  units; an implementer must not drop them). The §8 mixed lesson/quiz ordering test
  pins this.
- `prev`/`next` are the immediate neighbours of `current_node` in that list, located by
  **`node.pk == current_node.pk`** (not object identity — the walk builds its own
  instances from `course.nodes`, distinct from the view's `current_node`). First unit has
  no `prev`; last has no `next` (button rendered disabled/absent). A unit test asserts
  Prev/Next resolve for a `current_node` fetched independently of the walk's queryset.
- Each button shows the neighbour's **title** (mockup), `lang={{ course.language }}`
  on the title since it is author content.
- A quiz unit's Prev/Next navigate to sibling **units** (lessons or quizzes) — quizzes
  are single units; there is no intra-quiz prev/next.

### 3.5 Footer progress (accepted option B)
- **Course hairline** (3px along the footer's top edge): completed required units ÷
  total required units. `build_outline` returns a **list** of top-level parts with no
  course-wide root, so this ratio is computed by **summing** `required_done` and
  `required_total` across that list (done once in `build_unit_nav`). Invariant: the node
  tree is a partition — each required unit is counted in exactly one top-level part's
  `required_total` — so summing across the list yields the course total with no
  double-counting. The §8 quiz-only / 0-required tests cover the boundaries.
- **Part chip** ("PART d/t" + short amber bar): the same ratio for the current unit's
  **top-level part** (the depth-1 ancestor of `current_node`). If `current_node` is itself
  a depth-1 child of the course root (no enclosing part), the part chip is **hidden** —
  the course hairline already represents it.
- Reuses existing rollup numbers exactly (cheap, as desired).
- **Edge cases:** hide the part chip when the part has `required_total == 0`; hide the
  hairline when the course has `required_total == 0` (e.g. quiz-only courses). Quiz
  units count toward neither (quizzes are excluded from `required_*` by existing
  rollup rules) — this is intentional and consistent with the outline page.

### 3.6 Accessibility
- Tree is a labelled `nav`; active unit `aria-current="page"`.
- Mobile drawer: `role="dialog"`, `aria-modal="true"`, focus trap, Esc + scrim close,
  focus returned to the trigger on close. The focus trap must be **built new** — the
  Phase-3b catalog modal (`courses/static/courses/js/catalog_modal.js`) has **no** focus
  trap, `role`, or `aria-modal` (only Escape + click-outside close), so there is nothing
  to reuse. Build a small self-contained trap for the drawer (Tab/Shift-Tab cycle within
  the drawer, restore focus to the trigger on close); retrofitting the catalog modal is
  out of scope here. The e2e drawer test must exercise the trap.
- Prev/Next are real `<a>` links; disabled ends are non-focusable.

## 4. Feature: quiz-review roster

### 4.1 Layout
The `courses/manage/review_submission.html` page gains the same collapsible left roster (reusing the
unit-shell CSS), with the review cards on the right (mockup `quiz-review-roster.html`).
The roster lives in its own header strip ("Submissions" + `‹` toggle) so the toggle
never overlaps a group count.

### 4.2 Data — sibling submissions for the same unit
A new pure per-unit service `roster_for_unit(reviewer, submission)` — **distinct from**
the course-wide `pending_reviews_for` (review.py), which is left unchanged — gathers, for
`submission.unit`, every student in `scoping.reviewable_students(reviewer, course)`,
grouped. The shared `state["total"] > 0 and not state["fully_reviewed"]` predicate is
factored into one helper that both this service and `pending_reviews_for` call, so the
two groupings cannot drift:
- **To review** — a `QuizSubmission` with `status == SUBMITTED`, the unit has **≥1 [R]
  element** (`state["total"] > 0`), and it is **not** fully reviewed.
  `submission_review_state(sub)` returns a **dict**, so the service tests
  `state["total"] > 0 and not state["fully_reviewed"]` (Python key access, not attribute
  access).
- **In progress** — a submission with `status == IN_PROGRESS` (started, not submitted).
  Each row carries an individual **Force-submit**. Students who never opened the quiz
  (no submission row) do **not** appear — there is nothing to submit.
- **Reviewed** — every other SUBMITTED submission: those that are fully reviewed
  (showing earned/max **review** marks — computed exactly as `_review_rows` does: iterate
  the unit's elements, resolve `el.content_object` to the `QuestionElement` and gate on
  `marking_mode == REVIEW`, then sum the response's `earned_marks` and the question's
  `max_marks` (`q.max_marks`, off the resolved question, **not** a field on the `Element`
  through-model), reusing the same prefetch to avoid N+1), **and** any whose unit has
  **zero [R] elements** (`state["total"] == 0`,
  e.g. an auto-only quiz). `submission_review_state` reports `fully_reviewed == False`
  when `total == 0`, so the zero-[R] case must be routed here explicitly — it must never
  land in "To review", where it could never be cleared. A zero-[R] Reviewed row shows a
  neutral **"Auto-marked"** label — **no** review marks and **no** numeric score (the
  roster service does not reach into the auto-scoring layer, keeping it simple); the §8
  auto-only roster test asserts this label. Note `total` is **per-unit** (identical for all submissions of a unit),
  so this case is really "the whole quiz has no [R] elements." Add a test for an
  auto-only submission's roster group.

**Roster order** is a single **flat sequence** with the **total, stable** sort key
`(lower(display_name or username), pk)` — the `pk` tie-breaks equal or blank display
names so the order is fully reproducible (the existing review code sorts by `username`;
this extends it). The sort is performed **in Python over the materialized list** (so the
`display_name or username` falsy-coalesce works; it is not a DB `.order_by`, where `or`
would not translate to SQL coalescing). It is independent of the visual grouping (groups are a display concern
only); Prev/Next in §4.3 traverse this flat sequence, so neighbours are deterministic
regardless of which group a row is shown in. The **current submission is highlighted**
in whichever group it falls into — **To review** or **Reviewed**, the latter including
the **zero-[R] auto-only** case (the §4.4 guard admits any SUBMITTED submission, so an
auto-only one opens and is highlighted in Reviewed); never **In progress**, which the
guard excludes. Scope is enforced via
`reviewable_students` exactly as `_resolve_for_review` already does — no new IDOR
surface.

### 4.3 Footer navigation
- **Prev** — previous submission in the flat roster order (§4.2; any group).
- **Next to review** — the next **To review** submission *other than the current one*,
  after it in roster order; disabled when no other pending submission remains.
- The top-bar "N to review" badge counts **all** "To review" submissions (§4.2),
  **including** the current one if it is itself still pending (so the badge and the
  "Next to review" target can legitimately differ by one).
- Both are links to the `courses:manage_review_submission` route for the target
  submission. The disabled-Prev/Next ends and the "Next to review" both resolve to that
  same route.

### 4.4 Force-submit-all (new)
- A new `@require_POST` endpoint `force_submit_all`, URL name
  `courses:manage_review_force_submit_all`, path
  `manage/courses/<slug:slug>/review/unit/<int:unit_pk>/force-submit-all/` (the existing
  review routes all live under `manage/courses/<slug>/review/…` keyed on
  `submission_pk`; this new per-unit route slots in alongside them keyed on `unit_pk`),
  that force-submits **every**
  in-progress submission for that unit within `reviewable_students`, reusing the
  existing `review_svc.force_submit_quiz(submission, by=request.user)` per row. It must
  first **verify `unit_pk` belongs to `slug`'s course** (404 otherwise), mirroring
  `_resolve_for_review`'s course-binding check, and gate on `can_review_course`.
  `force_submit_quiz` is already race-safe: it re-locks the row with
  `select_for_update()` and **no-ops unless** the status is `IN_PROGRESS`. The endpoint
  must **re-query the in-progress set inside the request** (it does not trust the `N`
  rendered on the page), so a student who submits normally between page-render and POST
  is simply skipped.
- **Empty set** (no in-progress submissions remain at POST time): a harmless **no-op** —
  302 redirect back to the review page with a neutral info message (e.g. "All quizzes
  already submitted."), never an error. Covered by a test.
- Triggered from a top-bar **"Force-submit all (N)"** button with N = the render-time
  in-progress count, behind a JS confirm (`data-confirm`, matching the quiz-finish
  pattern). The button is **not rendered at all when N == 0** at render time (so there is
  never a "Force-submit all (0)"); the confirm text and "(N)" reflect the render-time
  count, while the server re-query remains the source of truth for the actual effect.
- Redirects (302) back to the **review page** (`courses:manage_review_submission`) for
  the current submission. This is safe because the review view **resolves only
  `SUBMITTED` submissions** — opening an `IN_PROGRESS` `submission_pk` is rejected (404). `_resolve_for_review` must add this
  status guard (it does not check status today), with a test that an `IN_PROGRESS`
  submission cannot be opened for review. Given that guard, the current submission is
  never in the in-progress set this action touches; the page simply re-renders with the
  former in-progress students now moved into the **To review** group.
- The **existing** individual `force_submit` endpoint stays, and **keeps its success
  message** (`"Quiz submitted for <student>."`). Only its redirect target becomes
  context-dependent and **server-computed**: the discriminator is a hidden `review_pk`
  form field — if present and it resolves to a `SUBMITTED` submission within
  `reviewable_students`, redirect to that submission's review page
  (`courses:manage_review_submission`); otherwise fall back to the queue
  (`courses:manage_review_queue`, the legacy behaviour). It must **not** honour a
  free-form `next`/referrer (avoids open-redirect and referrer unreliability). Tests pin
  the redirect target for both the roster-context call and the legacy queue-context
  call, and assert the success message persists in both.

## 5. Feature: code-editor author fields (accepted: theme-following, plain monospace)

Progressive enhancement of the existing textareas — **no editor library, no syntax
highlighting**:
- A styled container: theme-following surfaces (warm in light, inverts in dark),
  monospace font, a header strip label, and a **line-number gutter** synced to the
  textarea's line count and scroll. The textarea uses **no soft-wrap**
  (`white-space: pre; overflow-x: auto`), so gutter numbers map 1:1 to logical lines; an
  empty field shows line "1". The e2e gutter-sync check targets this 1:1 mapping.
- **Tab** inserts indentation (and does not move focus) while the textarea is focused;
  Shift-Tab outdent is optional (plan decides).
- Applies to these specific fields (enumerated to avoid an inconsistent subset):
  the element HTML/CSS/JS field in
  `templates/courses/manage/editor/_edit_html.html` (`{{ form.html }}`, model
  `HtmlElement.html`), the **course-wide CSS** (`Course.html_css`), the **course-wide
  JS** (`Course.html_js`), and the **unit seed JS** (`ContentNode.html_seed_js`). All
  four code inputs get the same treatment.
- **No-JS fallback:** the field is still a styled monospace textarea (gutter/Tab are
  enhancements). Sandbox execution and help text unchanged.
- Lives as a small `code-field` CSS block + a focused JS module; opt-in via a class/
  `data-` attribute on the widget so it does not affect other textareas. The `code-field`
  **CSS** is the batch-1 primitive (§2); the **JS** module ships in batch 4.

## 6. Consistency pass (batch 1) — page-by-page intent

Apply the established vocabulary; introduce small **results/stat** components where the
results pages need them. No behaviour change.
- `core/home.html` — landing/dashboard surfaces to the app shell + card vocabulary.
- `courses/my_courses.html` — the enrolled-courses dashboard as a card/list consistent
  with the catalog & outline language.
- `courses/quiz_results.html`, `courses/course_results.html` — results/stat components
  (score headline, per-quiz/per-unit breakdown, awaiting-review state) using badges +
  tabular-nums, consistent with the manage "spec strip" idiom.
- Question **feedback/reveal** partials + the 9 question widgets + media elements —
  spacing, focus rings, correct/incorrect/locked states, dark-mode parity.

## 7. Authoring UI (batch 5)

A lighter restyle of `builder.html`, `editor/*`, marking fields, and `media/manager.html`
to the shared vocabulary (buttons, badges, surfaces, dark-mode parity). No structural
rework of the authoring flows.

## 8. Testing & Definition of Done

Per project norms (TDD; `uv run` for tooling; bash `ruff`/`pytest`/`python` are NOT on
PATH).

**Features (batches 2–4):**
- Unit tests: `units_in_order` ordering (nested, mixed lesson/quiz, edges);
  `build_unit_nav` (prev/next neighbours, part/course progress, edge cases — first/last
  unit, 0-required part, quiz-only course, and a depth-1 unit with no enclosing part);
  Prev/Next resolution by `pk` for an independently-fetched `current_node`; roster
  grouping + scope (incl. the zero-[R] auto-only row → Reviewed); force-submit-all scope +
  idempotency + redirect, the **render-N > server-N race** (a student submits between
  render and POST), and the **empty-set no-op** (302 + neutral message).
- Template-render tests for the unit shell, tree partial, roster.
- **e2e Playwright driving real gestures** (per `e2e-must-drive-real-ui`): desktop tree
  collapse/restore + persistence, mobile drawer open + close-on-scrim + Esc, Prev/Next
  traversal, auto-scroll-to-active, roster student switch + Next-to-review, Force-submit-
  all confirm + effect, code-field Tab-indent + gutter sync.

**Consistency pass (batches 1, 5):** mostly visual — throwaway Playwright screenshots
**light + dark**, self-critique, delete-after (per `verify-ui-with-screenshots`); plus
assertions that no template breaks render.

**Every batch:** full suite + `ruff check` + `ruff format --check` green; `.mo`
compiled if new i18n strings; new `{% trans %}` strings get PL translations (watch the
makemessages fuzzy-flag gotcha).

## 9. Risks & notes
- The unit shell changes the page structure of the two highest-traffic student pages —
  keep the existing JS hooks intact. Specifically, `progress.js` binds to
  `.lesson[data-seen-url]`, so the `<article class="lesson" data-seen-url=…>` element
  (and the quiz `.quiz` article) must remain the **direct content node** the JS queries:
  the two-column shell wraps **around** that article, never between it and its element
  `<section>`s. Quiz units have **no** seen-tracking (no `data-seen-url`); do not add a
  seen hook to the quiz column.
- `localStorage` tree-collapse state must restore before paint via a **new** pre-paint
  inline script that sets the collapse class on the root `<html>` element (the body
  shell wrapper isn't parsed yet); CSS scopes the rail state from `<html>`. This follows
  the same run-before-paint-on-`<html>` pattern as the theme script but uses a
  **different** storage mechanism (the theme script reads a cookie; this reads
  `localStorage`) — they are separate scripts.
- Force-submit-all is the only new **mutating** behaviour — gate it carefully on
  `can_review_course` + `reviewable_students`, require POST + confirm.
- i18n: every new visible string is `{% trans %}` with a PL translation.
```
