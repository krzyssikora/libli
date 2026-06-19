# Phase 2a — Question foundations (formative MCQ in lessons) — Design

**Status:** spec (brainstormed 2026-06-19)
**Slice:** Phase 2a — the keystone slice of the Phase 2 quiz engine. Establishes the question-element abstraction, the server-side auto-marking interface, and the answer→submit→feedback loop, proven end-to-end on single/multi-choice MCQ, **shippable as formative questions inside lesson units**.
**Predecessors:** 1a (content model, Element GFK pattern, element renderers, vendored KaTeX, `UnitProgress`), 1b-i (course builder), 1b-ii (per-unit editor｜preview page, `FORM_FOR_TYPE` dispatch, bespoke RTE, optimistic `unit.updated` token), 1b-iii (HTML element — established the "server is the boundary" discipline).

---

## 1. Purpose & scope

### 1.1 Phase 2 decomposition (context)

Phase 2 (quiz engine & results) is the roadmap's single largest subsystem and is explicitly flagged to be sub-split. It is decomposed into five slices, each its own spec → plan → build cycle:

- **2a — Question foundations (this slice):** the `QuestionElement` abstraction + server-side auto-marking interface + answer→submit→feedback loop, proven on single/multi MCQ, formative in lessons. No persistence.
- **2b — Auto-markable type expansion:** fill-blanks, short text (normalized match), short numeric (answer + tolerance), drag-fill-blanks. New element types plugging into 2a's marking interface.
- **2c — Quiz units:** makes `unit_type=quiz` live — quiz-unit rendering (+ optional slideshow), quiz-level submission, **the Response/Attempt persistence model**, max attempts, max marks, **[N] not-marked / [R] requires-review** marking modes, attempt recording.
- **2d — Rich interactive + review types:** match pairs, drag-to-image (pointer DnD), extended response (required/forbidden keywords); the [R] human-review path.
- **2e — Results & metrics:** scores per question/unit/course, the [R] flag surfaced, student quiz summary.

### 1.2 Foundational architecture decision (locked in brainstorming)

**Questions are new Element types**, not a separate parallel model tree. They live in the existing `Element` GFK join-row + concrete-per-type-model pattern. Consequences:

- Questions reuse the entire 1b authoring stack (per-unit editor, `FORM_FOR_TYPE` dispatch, add-menu, reorder, `render_element` dispatch, optimistic-token concurrency).
- Questions can appear **formatively inside lesson units**, not only in quiz units — matching the 1b-iii deferral note ("question types deferred to Phase 2, reused formatively in lessons") and the author's real openEdX content (interactive questions inline in lesson pages).
- A separate response/marking/attempts layer is added **on top** (in 2c), independent of the element/content layer.

### 1.3 What this slice is

A new question element type, **`ChoiceQuestionElement`** (single + multiple choice MCQ), authored through the existing per-unit editor and rendered into lesson units. A student answers it and receives **server-marked feedback** — correct/incorrect, the revealed correct choice(s), and an optional author explanation — and may retry freely. The slice also lands the **abstract `QuestionElement` base** and the **`mark()` marking interface** that 2b/2c/2d question types subclass.

### 1.4 What this slice is NOT (scope boundaries — deferred to later slices)

- **No response persistence.** A formative answer in a lesson is **ephemeral practice**: the server marks it and returns feedback; nothing is stored or graded. The Response/Attempt model, attempt limits, and scoring all land in **2c**. Trade-off accepted: a student's formative answer is not remembered across page reloads.
- **No quiz-unit behavior.** `unit_type=quiz` stays inert (its 1a placeholder branch is untouched). Quiz rendering, slideshow, quiz-level submission → **2c**.
- **No marking modes.** MCQ is auto-markable, so 2a questions are implicitly **[A] auto**. The marking-mode field and **[N]/[R]** → **2c**.
- **No max-marks / max-attempts fields.** `mark()` returns a normalized fraction (0.0–1.0); 2c multiplies by per-question max-marks and enforces attempt caps.
- **No partial credit.** Multi-choice marking is all-or-nothing in 2a (see §3.3); partial-credit scoring is a 2c decision.
- **No other question types.** Only `ChoiceQuestionElement` (single + multi). The remaining question types (fill-blanks, short text, short numeric, drag-fill-blanks → 2b; match pairs, drag-to-image, extended response → 2d) are out of scope here.
- **No results/metrics surfaces.** → 2e.

### 1.5 Non-goals

- No new dependency. Reuses Django, the existing `sanitize_html` RTE, vendored KaTeX, and the established `fetch`+`X-CSRFToken` transport.
- No change to the `UnitProgress` completion contract (see §3.6).
- No per-choice feedback authoring (considered and deferred — heaviest authoring burden; could land in a later slice).

---

## 2. Data model

### 2.1 The question abstraction

A new abstract base extends the existing `ElementBase` (which provides the by-convention `render()`):

```
QuestionElement(ElementBase)              # abstract
  stem         TextField(blank=True)      # the prompt — rich text, sanitize_html on save
  explanation  TextField(blank=True)      # shown in feedback — rich text, sanitize_html on save
  # contract (not a DB field):
  def mark(self, answer) -> MarkResult     # abstract; each concrete type implements
```

- `stem` and `explanation` are sanitized via `courses.sanitize.sanitize_html` on `save()` (same `ALLOWED_TAGS` set as `TextElement`), and may contain KaTeX math delimiters (rendered client-side).
- `QuestionElement` is `abstract = True`; it owns no table. Concrete subclasses each get their own table and their own GFK content-type, per the established element pattern.

### 2.2 The first concrete type

```
ChoiceQuestionElement(QuestionElement)
  multiple   BooleanField(default=False)   # False = single-choice / true-false; True = multi-select
  choices    -> related Choice rows (related_name="choices")
  elements   GenericRelation(Element)      # join-row back-reference (cascade-delete)

Choice(models.Model)
  question    FK -> ChoiceQuestionElement (related_name="choices", on_delete=CASCADE)
  text        CharField(max_length=500)    # plain text + KaTeX math delimiters
  is_correct  BooleanField(default=False)
  order       OrderField(for_fields=["question"], blank=True)

  class Meta:
      ordering = ["order", "pk"]
```

- **Single vs multi is the `multiple` flag on one model**, not two models. True/false is just a single-choice question authored with two choices — no separate type.
- `Choice` is a plain model (not an element / not in the GFK). Choice `text` is **plain text + math** (rich text per choice is out of scope): it is **never** run through `sanitize_html`; the templates render it with Django's default auto-escaping, and KaTeX auto-render then runs over the escaped label text.
- **Choice ordering in 2a is not author-editable.** `Choice.order` is autonumbered by `OrderField` (scoped per question) in form-row creation order; choices display in that order. An explicit reorder UI is deferred to a later slice, so `order` is omitted from the formset `fields` (see §3.1).
- `ELEMENT_MODELS` gains `"choicequestionelement"` (the GFK `content_type` allowlist in `Element.content_type.limit_choices_to`).

### 2.3 `MarkResult` — the marking contract

A small immutable value object (e.g. a frozen `dataclass`) returned by `mark()`. This is the normalized interface every present and future question type produces, and that 2c will consume:

```
MarkResult
  correct:  bool            # the verdict (the formative ✓/✗)
  fraction: float           # 0.0–1.0 score fraction; 2c multiplies by per-question max-marks
  reveal:   <opaque>        # per-type presentation payload, type-opaque to the marking core
                            # (each question type documents its own shape).
                            # ChoiceQuestionElement: a frozenset[int] of correct choice ids.
```

- 2a has **no** `max_marks`; the fraction is the whole score signal. This keeps the interface from prematurely encoding quiz-scoring concerns.
- `reveal` carries exactly what the feedback template needs to highlight correct answers; it is produced server-side and only travels to the client in the post-submit feedback response (never the initial render — see §4).

### 2.4 Migration

One new migration creating `ChoiceQuestionElement` and `Choice`, plus the `ELEMENT_MODELS` addition. All fields blank-friendly; no data migration. No change to existing tables.

---

## 3. Authoring & consumption

### 3.1 Authoring forms (`element_forms.py`)

- **`ChoiceQuestionElementForm`** (ModelForm: `stem`, `explanation`, `multiple`). `stem`/`explanation` use the bespoke RTE widget (same as `TextElementForm`-family rich text).
- **`Choice` inline formset** — `inlineformset_factory(ChoiceQuestionElement, Choice, fields=["text", "is_correct"], extra=2, can_delete=True)`. `order` is **not** a formset field (autonumbered by `OrderField` in row order — §2.2). The editor partial renders the question form together with the choice formset (add/remove rows).
- **Validation — the formset's custom `clean()` is the single source of truth**, counting only non-deleted, non-empty forms (so it stays correct under dynamic add/remove rows). We do **not** use `min_num`/`validate_min`, which miscounts `DELETE`-marked / empty extra rows:
  - ≥ 2 choices.
  - ≥ 1 correct choice always.
  - For `multiple=False`: **exactly 1** correct choice.
  - Errors surface on the formset; the editor's existing 422 re-render path shows the bound form **and** formset (see §3.2).

### 3.2 Type-key dispatch (the one wrinkle)

The current edit path derives the type key from the model name:
`content_object.__class__.__name__.lower().replace("element", "")` → yields `"choicequestion"` for `ChoiceQuestionElement` (both single and multi, since they share one model).

- **`FORM_FOR_TYPE`** gains a single **`"choicequestion"`** entry → `ChoiceQuestionElementForm` (the form reads/writes `multiple`).
- **Add-menu → two cards, one model.** The add-menu offers **"Single choice"** and **"Multiple choice"** cards carrying add-keys `"choice-single"` / `"choice-multi"`. `element_add` (which is **render-only** — it builds an *unbound* form and renders it, creating no row) translates both add-keys → `type_key="choicequestion"` **before** the type allowlist check, and seeds the unbound form with `initial={"multiple": False|True}`. The `multiple` field renders in the form (a hidden input) so its value **round-trips through the POST** like any other field — there is no server-side force, and on a later edit `element_save` simply reads `multiple` from POST. (The 2a editor offers no single↔multi flip; the value is fixed by the card used to add.)
- **Allowlist tuples must admit the new keys.** `element_add` and `element_save` currently hard-gate on a fixed type tuple (`text/image/video/iframe/math/html`) and return `400` otherwise. Both gates must add `"choicequestion"`; `element_add` additionally accepts the two add-keys and maps them down to `"choicequestion"` **ahead of** its gate. The model-name→type_key derivation (`__class__.__name__.lower().replace("element","")` → `"choicequestion"`) already routes the **edit / `element_form`** path correctly once `FORM_FOR_TYPE` has the entry.
- **The formset threads through the single-form codepath.** The existing `save_element` / `_render_open_form` / `element_form` build one form via a shared path that has no concept of a formset (it special-cases only `course=` for image/video). 2a adds a parallel construction branch keyed on `type_key=="choicequestion"` that also builds the `Choice` inline formset with the same `data`/`files`/`prefix`/`instance`. For the 422 re-render, `ElementFormInvalid` is extended to carry **both** the form and the formset so the editor re-renders the bound pair.
- **Atomic create-on-first-save sequence.** Inside the existing `@transaction.atomic` (with the optimistic-token lock), `element_save` for a `choicequestion`: validate the form **and** the formset (either invalid → raise `ElementFormInvalid` carrying both); `obj = form.save()`; `formset.instance = obj; formset.save()`; then create/attach the `Element` join-row (`new` sentinel = create). Question and choices commit together or not at all.
- This is the one place the current 1:1 `type_key ↔ model` assumption bends; the plan must pin the add-key→type_key translation, the allowlist additions, the formset-construction branch, and the save sequence precisely.

### 3.3 Marking rules (2a)

`ChoiceQuestionElement.mark(answer)` — `answer` is an **already-validated** set of choice ids belonging to this question. The foreign/forged-id drop happens in `check_answer` *before* `mark()` is called (§3.5 step 2 / §4); `mark()` itself assumes clean ids and does no queryset validation:

- **Single (`multiple=False`):** `correct` iff the one selected choice is the correct one; `fraction` ∈ {0.0, 1.0}.
- **Multiple (`multiple=True`):** **all-or-nothing** — `correct`/`fraction=1.0` iff selected set == correct set, else `0.0`. *Partial credit is explicitly deferred to 2c.*
- `reveal` = the correct choice ids (for the feedback render).

### 3.4 Initial render (security-critical)

`render_element` dispatches `ChoiceQuestionElement` to `templates/courses/elements/choicequestion.html`, which renders a real `<form>`:

- stem (sanitized HTML, KaTeX-rendered) + choices as `<input type="radio">` (single) or `<input type="checkbox">` (multi). **Single and multi use the same input `name="choice"`** with `value=<choice-pk>` (radio permits ≤1 selected; checkbox permits many) — so the server parses one POST key uniformly. Labels = choice text (auto-escaped, KaTeX-rendered).
- **`is_correct` is NEVER serialized to the initial page.** Choices render by id + text only. Correctness exists only server-side until a submit returns. This is the core security invariant (the server is the marking boundary — §4).

### 3.5 The marking round-trip (one view, two transports)

**Submit endpoint** — new view `check_answer(request, slug, element_pk)`:

1. Resolve the `Element` join-row IDOR-safely — reuse the 1a `get_node_or_404` on the unit + `can_access_course`; confirm the `content_object` is a `ChoiceQuestionElement`.
2. Read `request.POST.getlist("choice")`, coerce to ints, and **validate against this question's own `choices` queryset** → `answer = {id for id in submitted if id in question_choice_ids}` (foreign/forged ids dropped, treated as not-selected, never error-leaking).
3. Call `question.mark(answer)` → `MarkResult`. **Nothing is persisted.**
4. Render the feedback fragment `_question_feedback.html`: a verdict (i18n-wrapped **"Correct" / "Incorrect"** text — the ✓/✗ glyphs are decorative CSS, not load-bearing strings), the revealed correct choice(s), the explanation (if any), and the form re-shown for free retry.

**Transports (progressive enhancement):**

- **JS path:** `question.js` intercepts submit → `fetch` POST with `X-CSRFToken` (mirrors `progress.js`/`builder.js`) → swaps the feedback fragment into the question's container. Per-question, no page reload. No `csrf_exempt`.
- **No-JS path:** the same `<form>` does a full POST to `check_answer`. The view re-renders the **whole lesson unit** (reusing `lesson_unit`'s context-building so every *other* element renders fresh), passing two extra context values: `feedback_for_pk` (this element's pk) and `selected_ids` (the echoed POST selection). The `render_element` templatetag forwards these into the question template, which shows its feedback block + repopulates its inputs **only** when its own pk == `feedback_for_pk`; all other questions render normally. Nothing is persisted; state lives entirely in the request. To avoid duplicating the unit-render context, `check_answer` delegates to a shared helper extracted from `lesson_unit` (so both paths build identical element/`has_*` context).

### 3.6 Lesson view wiring & progress

- Add a `has_questions` flag (parallel to `has_math`/`has_html`) to gate the `question.js` include.
- **KaTeX gate (corrected mechanism).** The existing `has_math` is **not** a content scan — it is a content-type identity check (`has_math = any(el.content_type_id == math_ct_id ...)`), so a `ChoiceQuestionElement` carrying math in its stem/choices would otherwise never trip it. 2a adds a per-element text scan: reuse `courses.htmlsandbox.has_math_delimiters` over each question's `stem` + choice `text`, and OR the result into `has_math` (i.e. `has_math = (any MathElement) or (any ChoiceQuestionElement whose stem/choice text contains \(…\) / \[…\] delimiters)`). This is a new code path in `lesson_unit`, not a config tweak.
- **Progress:** a question element counts toward `UnitProgress.seen_element_ids` like any element (seen on scroll-into-view). **Answering is not required for unit completion** in 2a (formative). The `UnitProgress` completion contract is unchanged.

---

## 4. Security & validation invariants

- **No answer leakage:** choice `is_correct` never reaches the initial page render (§3.4). Asserted by an explicit test that the rendered question HTML contains no correctness signal.
- **Server is the marking authority:** `mark()` runs only server-side; the client submits choice ids, never scores.
- **Forged / foreign choice ids:** `check_answer` validates submitted ids against the question's own `choices`; unknown ids are dropped, never error-leaking.
- **IDOR scoping:** the submit endpoint reuses `get_node_or_404` + `can_access_course` — the same 404-before-403 discipline as 1a/1b. A non-enrolled / wrong-course user cannot probe questions.
- **CSRF:** the fetch path sends `X-CSRFToken`; the no-JS path uses the standard `{% csrf_token %}`. No `csrf_exempt`.
- **Authoring validation:** ≥ 2 choices; ≥ 1 correct (exactly 1 if `multiple=False`); enforced in form/formset `clean()` and consistent with `mark()`'s assumptions.
- **i18n:** all new strings wrapped (`gettext` / `{% trans %}`) + Polish translations, per the established gate.

---

## 5. Testing & Definition of Done

- **Unit:**
  - `mark()` for single & multi (all-or-nothing; fraction values), fed **pre-validated** ids — the forged/foreign-id drop is tested at the `check_answer` layer, not `mark()`.
  - Form/formset validation (choice counts; correct-count by `multiple`).
  - `check_answer` view (correct / incorrect responses; IDOR 404; foreign-id drop; CSRF present).
  - **No-leakage render test** (initial HTML has no `is_correct` signal).
- **Authoring:** add single + multi via the editor; edit (type-key dispatch wrinkle); delete (reuse `builder.delete_element`).
- **Playwright e2e (`-m e2e`):** author a single-choice + a multi-choice question in a lesson → as a student, submit wrong (✗ + reveal + explanation), retry correct (✓) — in **both** the JS fragment-swap path and a **no-JS** full-POST path (the established two-path e2e pattern).
- **DoD gate:** default `pytest -q` (e2e excluded) + e2e green; `ruff check .` + `ruff format --check .`; `makemigrations --check` (one new migration); `manage.py check`; collectstatic; `compilemessages -l pl`.

---

## 6. Files (anticipated; the plan will finalize)

- `courses/models.py` — `QuestionElement` (abstract), `ChoiceQuestionElement`, `Choice`; `MarkResult` (here or a small `courses/marking.py`); `ELEMENT_MODELS += ["choicequestionelement"]`.
- `courses/migrations/00XX_*` — one new migration.
- `courses/element_forms.py` — `ChoiceQuestionElementForm` + `Choice` inline formset; `FORM_FOR_TYPE["choicequestion"]`.
- `courses/views_manage.py` — add-key→`type_key` translation + `"choicequestion"` added to the `element_add`/`element_save` type allowlist tuples; the formset-construction branch in `_render_open_form`/`element_form`; `ElementFormInvalid` extended to carry the formset.
- `courses/builder.py` — `save_element` gains the formset save sequence (validate form + formset; `obj=form.save()`; `formset.instance=obj`/`formset.save()`; join-row) inside the existing atomic/locked block.
- `courses/views.py` + `courses/urls.py` — `check_answer` view + route; `has_questions` flag + KaTeX scan extension in `lesson_unit`.
- `templates/courses/elements/choicequestion.html` — the question `<form>` (no correctness leak).
- `templates/courses/elements/_question_feedback.html` — feedback fragment.
- `templates/courses/manage/_edit_choicequestion.html` — editor partial (stem RTE, explanation RTE, choice formset); add-menu cards.
- `courses/static/courses/js/question.js` — submit interception + fragment swap.
- `courses/static/courses/css/...` — minimal question/feedback styles (token-driven).
- `locale/pl/LC_MESSAGES/django.po` — Polish strings.
- `tests/...` — unit + authoring + e2e per §5.
