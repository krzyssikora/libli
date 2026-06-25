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
- `Choice` is a plain model (not an element / not in the GFK). Choice `text` is **plain text + math** (rich text per choice is out of scope): it is **never** run through `sanitize_html`; the templates render it with Django's default auto-escaping, and KaTeX auto-render then runs over the escaped label text. (A `max_length=500` truncation that splits a `\(…\)` pair leaves an unclosed delimiter; KaTeX renders such malformed math as literal text — benign, no extra handling.)
- **Choice ordering in 2a is not author-editable.** `Choice.order` is autonumbered by `OrderField` (scoped per question) on each `save()`: the first choice of a question takes `OrderField`'s empty-scope base value (per `courses/fields.py` — the plan verifies the exact base), each subsequent new (blank-order) row takes `max(order)+1` within its question; existing rows keep their value; a deletion leaves a gap, which is harmless because the effective sort is `(order, pk)`. `formset.save()` iterates child forms in form order, so display order follows authoring order. An explicit reorder UI is deferred, so `order` is omitted from the formset `fields` (see §3.1). Regression tests assert display order **(a)** after initial create of N choices and **(b)** after an edit that deletes a middle choice and adds a new one.
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
- `reveal` carries exactly what the feedback template needs to highlight correct answers; it is produced server-side and only travels to the client in the post-submit feedback response (never the initial render — see §4). The feedback render already has the question's `choices` queryset in context (loaded to re-show the form), so `reveal`'s id set is used purely to **mark** which of those choices are correct — no extra query, and no choice text duplicated into `reveal`.

### 2.4 Migration

One new migration creating `ChoiceQuestionElement` and `Choice`. Because `Element.content_type.limit_choices_to` references `ELEMENT_MODELS`, the same migration also emits an **`AlterField` on `Element.content_type`** (validation-only — no DDL or data change to the `Element` table), exactly as migration `0010` did when `htmlelement` was added; `makemigrations --check` expects it. All new fields blank-friendly; no data migration.

---

## 3. Authoring & consumption

### 3.1 Authoring forms (`element_forms.py`)

- **`ChoiceQuestionElementForm`** (ModelForm: `stem`, `explanation`, `multiple`). `stem`/`explanation` use the bespoke RTE widget (same as `TextElementForm`-family rich text). **`multiple` is enforced by the form's `__init__`:** on an **edit** (when `self.instance.pk` is set) it **removes `multiple` from `self.fields`**, so a bound POST cannot overwrite the stored value; on **create** the field is present (hidden) and seeded via `initial` (§3.2). This is the concrete mechanism behind the "pinned on edit" invariant — the ModelForm never writes `multiple` on edit because the field isn't there to bind.
- **`Choice` inline formset** — `inlineformset_factory(ChoiceQuestionElement, Choice, fields=["text", "is_correct"], extra=2, can_delete=True)`. `order` is **not** a formset field (autonumbered by `OrderField` in row order — §2.2). The editor partial renders the question form together with the choice formset (add/remove rows).
- **Validation — the formset's custom `clean()` is the single source of truth**, counting only non-deleted, non-empty forms (so it stays correct under dynamic add/remove rows). We do **not** use `min_num`/`validate_min`, which miscounts `DELETE`-marked / empty extra rows:
  - ≥ 2 choices.
  - ≥ 1 correct choice always.
  - For `multiple=False`: **exactly 1** correct choice.
  - Errors surface on the formset; the editor's existing 422 re-render path shows the bound form **and** formset (see §3.2).

### 3.2 Type-key dispatch (the one wrinkle)

The current edit path derives the type key from the model name:
`content_object.__class__.__name__.lower().replace("element", "")` → yields `"choicequestion"` for `ChoiceQuestionElement` (both single and multi, since they share one model).

- **`FORM_FOR_TYPE`** gains a single **`"choicequestion"`** entry → `ChoiceQuestionElementForm`. `multiple` is a form field but **rendered hidden**; its authority differs by path (see the `multiple` authority bullet below).
- **Add-menu → two cards, one model.** The add-menu offers **"Single choice"** and **"Multiple choice"** cards carrying add-keys `"choice-single"` / `"choice-multi"`. `element_add` is **render-only** (it builds an *unbound* form + an empty `Choice` formset and renders them, creating no row); it translates both add-keys → `type_key="choicequestion"` **before** the type allowlist check. Because `_render_open_form` constructs the unbound form itself, it gains an **`initial=None` parameter** that `element_add` populates with `{"multiple": False|True}`, so the seed reaches the form `_render_open_form` builds. The rendered host form's hidden **`type` field is `"choicequestion"`** (not the add-key), and the editor partial's hidden `multiple` field carries the seeded value.
- **`element_save` only ever sees `type="choicequestion"`.** The add-keys live solely on the `element_add` path; the saved POST carries `type="choicequestion"`, so `element_save`'s gate (extended to include `"choicequestion"`) handles both single and multi uniformly — the add-keys never reach `element_save`.
- **Authority of `multiple`.** On **create** (the `new` sentinel) `multiple` is read from POST (the hidden seed from the card); tampering only mis-shapes the author's own new question, and the choice-count validation applies consistently to whatever value is saved. On **edit** `multiple` is **pinned server-side** — `save_element` ignores POST `multiple` and retains the stored `instance.multiple` — so the "no single↔multi flip after authoring" invariant is *enforced*, not merely trusted (a hidden input is client-editable). §2.2/§3.1's "exactly 1 correct iff `multiple=False`" therefore always tests the authoritative value.
- **Allowlist tuples must admit the new key.** `element_add`/`element_save` currently hard-gate on a fixed type tuple (`text/image/video/iframe/math/html`) and return `400` otherwise; both gain `"choicequestion"` (and `element_add` also accepts the two add-keys, mapping them to `"choicequestion"` **ahead of** its gate). The model-name→type_key derivation (`__class__.__name__.lower().replace("element","")` → `"choicequestion"`) already routes the **edit / `element_form`** path once `FORM_FOR_TYPE` has the entry.
- **Two formset construction sites (not one shared helper).** Display side: **`_render_open_form` builds the formset internally** — when it constructs the form (`form is None and type_key=="choicequestion"`) it also builds the unbound/instance-bound `Choice` formset and puts it in the host-form context under `formset`; on the 422 path it instead receives an already-bound `formset=` from the caller (see below). (`ChoiceQuestionElementForm` takes **no** `course` extra, so this is wholly independent of the existing `extra={"course": …}` image/video branch.) Save side (separate): **`builder.save_element` (builder.py)** — which today builds the form internally from `FORM_FOR_TYPE` using `post_data`/`files` — additionally builds the `Choice` inline formset from `post_data`/`files`/`instance` when `type_key=="choicequestion"`, validates it alongside the form, and runs the save sequence. These are distinct construction sites, not one shared codepath.
- **Template wiring.** The editor partial `_edit_choicequestion.html` renders `{{ formset.management_form }}` (required for the formset to bind on POST — omitting it raises `ManagementForm data is missing`) + the per-row choice fields, and emits the hidden **`multiple`** input. The host-form template emits the hidden **`type`** field (set to `"choicequestion"`, as it already does for the add/save POST). Together these produce exactly the POST shape §3.2's wire rules assume.
- **Atomic create-on-first-save sequence** (inside `save_element`'s existing `@transaction.atomic` + optimistic-token lock): validate the form **and** the formset → either invalid raises `ElementFormInvalid` **carrying both**; `obj = form.save()`; `formset.instance = obj; formset.save()`; then create/attach the `Element` join-row (`new` sentinel = create). Question + choices commit together or not at all.
- **422 re-render threads the formset.** `ElementFormInvalid.__init__` changes from `(form)` to `(form, formset=None)`, so `e.formset` is `None` for the six existing element types. `_render_open_form` gains a `formset=None` parameter; `element_save`'s `except ElementFormInvalid` branch always passes `formset=e.formset` (harmlessly `None` for non-question types; the bound errored formset for `choicequestion`), so the editor partial re-renders the bound **pair** for questions and is unchanged for every other type. Without this, the existing single-form re-render path would silently drop the formset.
- This is the one place the current 1:1 `type_key ↔ model` assumption bends; the plan must pin the add-key→type_key translation, the allowlist additions, the two formset construction sites, the `multiple`-authority split, and the save/re-render sequences precisely.

### 3.3 Marking rules (2a)

`ChoiceQuestionElement.mark(answer)` — `answer` is an **already-validated** set of choice ids belonging to this question. The foreign/forged-id drop happens in `check_answer` *before* `mark()` is called (§3.5 step 2 / §4); `mark()` itself assumes clean ids and does no queryset validation:

- **Single (`multiple=False`):** marked by **set equality** against the (singleton) correct set — `correct`/`fraction=1.0` iff `answer == {the one correct id}`. A forged/replayed POST carrying *two* valid ids is therefore `correct=False` (a 2-element set ≠ the singleton). `fraction` ∈ {0.0, 1.0}. (Single and multi are thus one uniform rule: `answer == correct_id_set`.)
- **Multiple (`multiple=True`):** **all-or-nothing** — `correct`/`fraction=1.0` iff selected set == correct set, else `0.0`. *Partial credit is explicitly deferred to 2c.*
- **Empty `answer`** (nothing selected, or all ids dropped as foreign — the natural no-JS first interaction, since radios have no default): `correct=False, fraction=0.0` for both modes (single: vacuously wrong; multiple: the empty set ≠ the non-empty correct set, which validation guarantees).
- `reveal` = the correct choice ids (for the feedback render).

### 3.4 Initial render (security-critical)

`render_element` dispatches `ChoiceQuestionElement` to `templates/courses/elements/choicequestion.html`, which renders a real `<form>`:

- stem (sanitized HTML, KaTeX-rendered) + choices as `<input type="radio">` (single) or `<input type="checkbox">` (multi). **Single and multi use the same input `name="choice"`** with `value=<choice-pk>` (radio permits ≤1 selected; checkbox permits many) — so the server parses one POST key uniformly. Labels = choice text (auto-escaped, KaTeX-rendered).
- **`is_correct` is never serialized for any element except the one being answered.** On the **initial** render — and for every *other* question on a post-submit no-JS page — choices render by id + text only, with no correctness signal. Reveal data appears **only** for the single element matching `feedback_for_pk` (the question the student just submitted). Correctness otherwise exists only server-side. This is the core security invariant (the server is the marking boundary — §4).

### 3.5 The marking round-trip (one view, two transports)

**Submit endpoint** — new view `check_answer(request, slug, node_pk, element_pk)` (routed under the unit, so the unit's `node_pk` is in the URL — an `Element` pk is not a `ContentNode` pk, so `get_node_or_404` needs the unit pk explicitly):

1. Resolve the **unit** via `get_node_or_404(node_pk, slug, require_lesson=True)` — `require_lesson` (not merely `require_unit`) so a submit to a **quiz** unit 404s, mirroring the `seen`/`complete`/`lesson_unit` lesson contract. (A question authored into a quiz unit is inert in 2a — quiz units render no elements until 2c — so its submit endpoint 404s too.) Then `can_access_course`. Fetch the `Element` by `element_pk` **scoped to that unit** (`unit=node`) — 404 if it doesn't belong — and confirm its `content_object` is a `ChoiceQuestionElement`. **Bind `question = element.content_object`**: both step 2's `question_choice_ids` and the feedback render's choice queryset come from `question.choices.all()` on that concrete instance (the GFK indirection is the load-bearing wiring).
2. Read `request.POST.getlist("choice")`, coerce to ints, and **validate against this question's own `choices` queryset** → `answer = {id for id in submitted if id in question_choice_ids}` (foreign/forged ids dropped, treated as not-selected, never error-leaking).
3. Call `question.mark(answer)` → `MarkResult`. **Nothing is persisted.**
4. Render the feedback fragment `_question_feedback.html`: a verdict (i18n-wrapped **"Correct" / "Incorrect"** text — the ✓/✗ glyphs are decorative CSS, not load-bearing strings), the revealed correct choice(s), the explanation (if any), and the form re-shown for free retry.

   > **Revision (2026-06-26, follow-up PR off PR #32):** the per-item reveal (the `{% include reveal_template %}` block) is now **suppressed when the answer is fully correct**, across both the live-check fragment and the no-JS post-submit page — for **all** question types: revealed correct choice(s), accepted short-text/numeric answers, per-blank ✓ (fill-blank / drag), accepted drag-to-image labels, **and the extended-response per-keyword required-found / forbidden-avoided breakdown** (user-confirmed 2026-06-26: an all-positive breakdown on a correct long answer is itself a redundant check). A correct answer shows only the "Correct" verdict + the author explanation. Wrong/partial answers still reveal (they teach). This mirrors the quiz-feedback decision shipped in PR #32 for `_quiz_question_feedback.html`. The JS path also hides the "Check" button once correct (a stateless re-check is pointless). e2e impact: the §202 single-choice e2e asserts the suppressed reveal + hidden button on the correct retry; the extended-response lesson e2e (`test_e2e_questions_2diii.py`) switches to a **partial** answer so it still exercises the keyword-breakdown reveal branch.

**Transports (progressive enhancement)** — `check_answer` branches on the existing `_wants_fragment(request)` helper (the same discriminator the editor/builder views use): a **fragment** response for the JS path, the **full lesson-unit page** for no-JS.

- **JS path:** `question.js` intercepts submit → `fetch` POST with `X-CSRFToken` (mirrors `progress.js`/`builder.js`) → swaps the feedback fragment into the question's container. Per-question, no page reload. No `csrf_exempt`.
- **No-JS path:** the same `<form>` does a full POST to `check_answer`, which re-renders the **whole lesson unit** so every *other* element renders fresh. Mechanics:
  - **`render_element` forwards kwargs to `obj.render()` — it does not build the context itself.** The tag already forwards element-specific kwargs to the concrete object's `render()` (it special-cases `HtmlElement` → `obj.render(unit, course)`; `models.py:287`). It gains `render_element(element, feedback_for_pk=None, selected_ids=None)` and the lesson call site becomes `{% render_element el feedback_for_pk=feedback_for_pk selected_ids=selected_ids %}` (other call sites, e.g. the editor preview, keep the bare form — kwargs default to `None`). The values reach the template only via a new **`ChoiceQuestionElement.render(self, *, feedback_for_pk=None, selected_ids=None, mark_result=None)`** override (mirroring `HtmlElement.render`) that injects them — plus the answered question's `reveal`/`MarkResult` for the no-JS feedback include — into the `{"el": self, …}` context it renders. Without this override the base `ElementBase.render()` would emit only `{"el": self}` and the template's `feedback_for_pk` gate would never see the values.
  - **The question template gates on identity.** `choicequestion.html` repopulates its inputs from `selected_ids` and `{% include "courses/elements/_question_feedback.html" %}` **only when** `element.pk == feedback_for_pk`; otherwise it renders the fresh, feedback-free form. Both transports therefore render the **same** `_question_feedback.html` partial — the JS path swaps that partial in, the no-JS path includes it — so the two feedback surfaces cannot drift.
  - **Shared context helper.** `check_answer` and `lesson_unit` both call a new helper `build_lesson_context(node, user)` returning the full `elements`/`has_math`/`has_html`/`has_questions`/`progress`/seen-count context (the access check + the quiz-placeholder early return stay in each view). It **`prefetch_related`s each question's `choices`** (alongside the existing `content_object` prefetch) so the per-element math scan (§3.6) and the feedback render don't N+1 across questions. `check_answer` adds `feedback_for_pk`, `selected_ids`, **and the `MarkResult` (its `reveal` set)** on top — so the answered question's no-JS feedback uses the **same** `reveal` as the JS path, and the template never recomputes correct ids from `is_correct` (which would re-expose them to the render layer). The helper performs the same `UnitProgress.get_or_create` + seen-count as a normal lesson view, so the no-JS re-render shows an identical progress bar; **answering creates no progress side effect** beyond what a plain visit would (nothing about the answer itself is persisted). State lives entirely in the request.

### 3.6 Lesson view wiring & progress

- Add a `has_questions` flag to gate the `question.js` include: like `has_html`, it is a content-type **identity** check — `any(el.content_type_id in question_ct_ids ...)`, where `question_ct_ids` is the set of question element content-types (just `ChoiceQuestionElement` in 2a; **2b extends this set**, so `question.js` gating automatically covers future question types).
- **KaTeX gate (corrected mechanism).** The existing `has_math` is **not** a content scan — it is a content-type identity check (`has_math = any(el.content_type_id == math_ct_id ...)`), so a `ChoiceQuestionElement` carrying math in its stem/choices would otherwise never trip it. 2a adds a per-element text scan: reuse `courses.htmlsandbox.has_math_delimiters` over each question's `stem` + choice `text`, and OR the result into `has_math` (i.e. `has_math = (any MathElement) or (any ChoiceQuestionElement whose stem/choice text contains \(…\) / \[…\] delimiters)`). This is a new code path in `lesson_unit`, not a config tweak. The scan runs over the **stored** values (the sanitized `stem`, the plain `text`); consistent with `has_math_delimiters`, only `\(…\)` / `\[…\]` match (`$$…$$` is unsupported, matching existing `MathElement`/KaTeX behavior).
- **Progress:** a question element counts toward `UnitProgress.seen_element_ids` like any element (seen on scroll-into-view). **Answering is not required for unit completion** in 2a (formative). The `UnitProgress` completion contract is unchanged.

---

## 4. Security & validation invariants

- **No answer leakage:** choice `is_correct` never reaches a render except for the single element matching `feedback_for_pk` (§3.4). Tested two ways: (a) the **initial** lesson render contains no correctness signal for any question; (b) on a post-submit page, reveal data appears for the answered question **only** — every other question is still clean.
- **Server is the marking authority:** `mark()` runs only server-side; the client submits choice ids, never scores.
- **Forged / foreign choice ids:** `check_answer` validates submitted ids against the question's own `choices`; unknown ids are dropped, never error-leaking.
- **IDOR scoping:** the submit endpoint reuses `get_node_or_404` + `can_access_course` — the same 404-before-403 discipline as 1a/1b. A non-enrolled / wrong-course user cannot probe questions.
- **CSRF:** the fetch path sends `X-CSRFToken`; the no-JS path uses the standard `{% csrf_token %}`. No `csrf_exempt`.
- **Authoring validation:** ≥ 2 choices; ≥ 1 correct (exactly 1 if `multiple=False`); enforced in form/formset `clean()` and consistent with `mark()`'s assumptions.
- **i18n:** all new strings wrapped (`gettext` / `{% trans %}`) + Polish translations, per the established gate.

---

## 5. Testing & Definition of Done

- **Unit:**
  - `mark()` for single & multi (all-or-nothing; fraction values; **empty `answer` → incorrect**), fed **pre-validated** ids — the forged/foreign-id drop is tested at the `check_answer` layer, not `mark()`.
  - Form/formset validation (choice counts; correct-count by `multiple`).
  - `check_answer` view (correct / incorrect responses; **empty submission**; IDOR 404; **quiz-unit submit 404s** via `require_lesson`; foreign-id drop; CSRF present).
  - **No-leakage tests:** (a) initial render — no `is_correct` signal for any question; (b) post-submit render — reveal appears only for the answered (`feedback_for_pk`) question, others clean.
- **Authoring:** add single + multi via the editor; edit (type-key dispatch wrinkle; `multiple` pinned on edit so a tampered hidden value can't flip it); delete (reuse `builder.delete_element`); choice display order after initial create and after an edit that deletes a middle choice and adds one (§2.2).
- **Playwright e2e (`-m e2e`):** author a single-choice + a multi-choice question in a lesson → as a student, submit wrong (✗ + reveal + explanation), retry correct (✓) — in **both** the JS fragment-swap path and a **no-JS** full-POST path (the established two-path e2e pattern).
- **DoD gate:** default `pytest -q` (e2e excluded) + e2e green; `ruff check .` + `ruff format --check .`; `makemigrations --check` (one new migration); `manage.py check`; collectstatic; `compilemessages -l pl`.

---

## 6. Files (anticipated; the plan will finalize)

- `courses/models.py` — `QuestionElement` (abstract), `ChoiceQuestionElement` (incl. a `render(self, *, feedback_for_pk=None, selected_ids=None, mark_result=None)` override mirroring `HtmlElement.render`), `Choice`; `MarkResult` (here or a small `courses/marking.py`); `ELEMENT_MODELS += ["choicequestionelement"]`.
- `courses/migrations/00XX_*` — one new migration.
- `courses/element_forms.py` — `ChoiceQuestionElementForm` + `Choice` inline formset; `FORM_FOR_TYPE["choicequestion"]`.
- `courses/views_manage.py` — add-key→`type_key` translation + `"choicequestion"` added to the `element_add`/`element_save` type allowlist tuples; the formset-construction branch in `_render_open_form`/`element_form`; `ElementFormInvalid` extended to carry the formset.
- `courses/builder.py` — `ElementFormInvalid.__init__(form, formset=None)`; `save_element` gains the formset save sequence (validate form + formset; `obj=form.save()`; `formset.instance=obj`/`formset.save()`; join-row) inside the existing atomic/locked block.
- `courses/views.py` + `courses/urls.py` — `check_answer` view + route; the `build_lesson_context` helper; `has_questions` flag + KaTeX scan extension in `lesson_unit`.
- `courses/templatetags/courses_extras.py` — `render_element` gains `feedback_for_pk`/`selected_ids` kwargs, forwarded to the concrete `render()` (the `HtmlElement` forwarding precedent).
- `templates/courses/elements/choicequestion.html` — the question `<form>` (no correctness leak).
- `templates/courses/elements/_question_feedback.html` — feedback fragment.
- `templates/courses/manage/_edit_choicequestion.html` — editor partial (stem RTE, explanation RTE, choice formset); add-menu cards.
- `courses/static/courses/js/question.js` — submit interception + fragment swap.
- `courses/static/courses/css/...` — minimal question/feedback styles (token-driven).
- `locale/pl/LC_MESSAGES/django.po` — Polish strings.
- `tests/...` — unit + authoring + e2e per §5.
