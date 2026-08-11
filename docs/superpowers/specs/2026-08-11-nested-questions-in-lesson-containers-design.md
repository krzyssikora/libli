# Nested questions in lesson containers

*Drafted 2026-08-11. Repairs the container render seam that drops a nested
question's no-JS feedback, then widens `NESTABLE_TYPE_KEYS` so four question types
(not one, by accident) may live inside a container — in **lesson units only**.*

Anchors in this document were verified against `origin/master` at `d5b20dbd`.
Symbol names are the durable reference; line numbers are a convenience and will
drift.

---

## 1. Purpose

Two things ship together, in this order, because the second is unsafe without the
first.

**1a — the defect.** With JS off, an enrolled student who submits a **blank**
answer to a question nested inside a container gets **no verdict at all**. The
identical question at top level gets one. Reproduced on all five containers
(callout, spoiler, tabs, two_column, before_after). It is live today because
`fill_blank` is nestable, so it is reachable in production content, not
hypothetical.

**1b — the widening.** `choice`, `short_text` and `short_numeric` join `fill_blank`
in `NESTABLE_TYPE_KEYS`, so an author can put an ordinary question inside a
callout, a spoiler, a tab, a column or a before/after slot. `fill_blank` is
nestable today **by accident, not by design** — it entered via the
interactive-in-spoiler work (`docs/superpowers/specs/2026-07-21-interactive-in-spoiler-design.md`),
which needed a fillblank inside a `<details>` spoiler and accepted the tabs/columns
consequence as an "unavoidable side effect". This spec makes the capability
deliberate and bounds it.

The ordering is load-bearing: widening the allowlist without 1a would multiply a
known broken path by four.

### Non-goals

- **Questions in quizzes-inside-containers stays unsupported**, and is now
  *enforced* rather than merely un-offered. See §6.
- **`extended_response` is deliberately excluded** from the widening. It is a
  long-form textarea that reads badly in a narrow column or a callout, and its
  keyword marking is the weakest fit for inline practice. It stays top-level-only.
- **The three drag types and the two grid types are excluded.** The drag types
  (`drag_fill_blank`, `match_pair`, `drag_to_image`) measure DOM geometry, which is
  zero inside a closed `<details>` or an inactive tab panel; the grid types
  (`choice_grid`, `multi_grid`) are wide tables that squeeze badly in a column.
  Both groups are deferrable and would each need their own e2e coverage per
  container.
- **The quiz-mode render seam is not fixed here.** It is documented in §6.5 as the
  reason the lesson-only rule exists.

---

## 2. Background: why the feedback is dropped

Verified by mutation in the pinning tests (see §9.1), not by reading.

`check_answer`'s no-JS path (`courses/views.py::check_answer`, the branch below
`_wants_fragment`) re-renders the **whole lesson unit** with a single page-level
`feedback_for_pk` / `mark_result` / `selected_ids` / `submitted_values` in the
context. `templates/courses/_lesson_article.html:39` hands those four to every
**top-level** element:

```
{% render_element el feedback_for_pk=feedback_for_pk selected_ids=selected_ids
                     submitted_values=submitted_values mark_result=mark_result %}
```

They cannot reach a nested element, because **three layers each drop them**:

1. `courses/templatetags/courses_extras.py::render_element`, non-question branch
   (lines 102–109), calls the container's `render()` with only
   `(element, state, slug, node_pk)`. The four question values are simply absent
   from that call.
2. The container's `render()` — e.g. `CalloutElement.render` at
   `courses/models.py:522` — cannot accept what layer 1 does not send, **and** its
   body calls `render_to_string(template, {...})` with a **freshly built dict**, so
   the page context is not inherited. **This is the root: a container render is a
   CONTEXT BARRIER**, and anything crossing it must be re-emitted by hand.
3. The container template's bare `{% render_element child %}`
   (`calloutelement.html:23`, `spoilerelement.html:31`, `tabselement.html:41`,
   `twocolumnelement.html:14`, `beforeafterelement.html:28`).

**Forwarding at layer 3 alone is a proven NO-OP.** Mutating `calloutelement.html:23`
to pass all four kwargs left every test green, because the values are not in the
container's context at all. Layer 3 is the layer that matters least, and it is the
one an author reaches for first — which is why the chosen design does not use it.

Nested feedback therefore works today **only** via the practice-state RESTORE
branch (`render_element`, lines 55–85), which needs a **stored** answer — and a
blank answer *clears* the key instead of storing it
(`courses/views.py:1059-1060`, "Empty answer clears any prior stored answer"). That
is the whole of the divergence, and it is why the blank-answer case is the one that
proves the fix.

### 2.1 The precedent to follow

Crossing the barrier is already a solved problem in this codebase, once
(`courses/models.py:530`):

```python
# `element_state`, NOT `state`: courses_extras.render_element reads
# context.get("element_state") for the recursive child render.
"element_state": state,
```

Page-level state reaches a nested child by being **re-emitted into the child's
context dict under the exact name `render_element` reads from context**. This
design generalises that mechanism rather than inventing a second one.

### 2.2 Why forwarding one result to every question is safe

The page hands ONE `mark_result` to EVERY element. **Two different invariants** keep
a non-checked question clean, and both must be understood — conflating them is how a
regression would slip through.

**Invariant A — the `feedback_for_pk` gate** covers the verdict block, the refilled
values and the lock. Every question template gates those on
`element.pk == feedback_for_pk`, and it is documented as load-bearing in
`templates/courses/elements/fillblankquestionelement.html:2-8`:

> the no-JS re-render hands ONE page-level mark_result to EVERY element (see
> `_lesson_article.html`), so a bare `mark_result.correct` would lock every other
> fill-blank on the unit.

Present in all four widened types (`choicequestion.html:23,49`,
`shorttextquestionelement.html:9,14`, `shortnumericquestionelement.html:9,14`,
`fillblankquestionelement.html:19,26,28`).

**Invariant B — Choice-pk disjointness** covers `choice`'s per-option markers, which
invariant A does **not** touch. `choicequestion.html:27` (the marker glyph +
`sr-only` label) and `:39` (per-option author feedback) gate on `mk`, which comes
from `ChoiceQuestionElement.choice_marks(choices, selected, mark_result, mode,
locked)` — a method that never receives `feedback_for_pk` at all. What keeps a
sibling unmarked is that its lesson branch tests `c.pk in mark_result.annotated`,
and `annotated` holds `Choice` pks belonging to the **checked** question, which are
globally unique and therefore disjoint from the sibling's. The same holds for
`mark_result.reveal` on the quiz branch.

Invariant B is real but incidental — nothing in `choice_marks` enforces it — so
§9.4 pins it directly: a nested sibling choice question renders **zero**
`question__choice-marker` and `question__choice-feedback` nodes when its neighbour
is checked. Seam test 10 alone cannot catch a regression here, because it counts
verdict blocks and the marker path emits none.

### 2.3 The rejected one-liner

Storing the blank answer at `courses/views.py:1060` makes the symptom vanish — it is
exactly the falsification mutation the pinning tests use. It must **not** be the
fix: clearing on blank is deliberate, and storing it would make a deliberately
blanked answer come back as "Incorrect" after reload, **for top-level questions
too**. It trades a nested-only gap for a site-wide behaviour change.

---

## 3. Architecture: the `page` dict

One dict crosses the barrier, carrying the values a child render needs from the
page.

### 3.1 `render_element` resolves, then forwards

At the top of `render_element`, each value falls back to the context when it was
not passed explicitly. **Five** explicit statements — one per key in the dict
below — rather than a loop or a helper, so each name stays greppable:

```python
if feedback_for_pk is None:
    feedback_for_pk = context.get("feedback_for_pk")
if not selected_ids:
    selected_ids = context.get("selected_ids") or frozenset()
if submitted_values is None:
    submitted_values = context.get("submitted_values")
if mark_result is None:
    mark_result = context.get("mark_result")
if editor_preview is None:
    editor_preview = bool(context.get("editor_preview"))
```

**`editor_preview` defaults to `None`, not `False`.** A `False` default can never
satisfy `is None`, which would make its fallback dead code and silently no-op the
whole of §5. The parameter is therefore tri-state on the wire (`None` = unset) and
coerced to a bool exactly once, at the fallback.

**The name is `editor_preview`, not `preview`.** `build_quiz_context` already ships
a `previewing` flag (`views.py:1394`, consumed by `_quiz_article.html:6`) meaning
"a non-enrolled **student** is viewing this quiz" — the opposite audience. Two
flags one suffix apart, one of which routes forms at a manage-gated endpoint, is a
conflation waiting to happen. Both the fallback and the `_preview.html` call site
carry a comment naming `previewing` as the thing this is not.

**`selected_ids` is the one key resolved by truthiness, not `is None`** — and that
asymmetry is deliberate, not an oversight. Its parameter default is `frozenset()`,
not `None`, so `is None` would never fire; and an empty selection and an unset
selection render identically, so replacing a falsy explicit value with the context
value is a no-op by construction. The consequence is that the fallback fires on
paths the other four skip — see §4, which spells out where.

The non-question branch then passes the **resolved** values down as one dict — but
**only to containers**:

```python
# Function-local, matching builder's own transfer-import convention
# (builder.py:437-441): a module-level import risks a cycle.
from courses.builder import CONTAINER_MODELS

extra = {}
if type(obj) in CONTAINER_MODELS:
    extra["page"] = {
        "feedback_for_pk": feedback_for_pk,
        "selected_ids": selected_ids,
        # `or None`: see below -- an empty STRING must never reach a child.
        "submitted_values": submitted_values or None,
        "mark_result": mark_result or None,
        "editor_preview": editor_preview,   # §5
    }
obj.render(
    element=element,
    state=context.get("element_state"),
    slug=context.get("slug"),
    node_pk=context.get("node_pk"),
    **extra,
)
```

**The container gate is not optional, and getting it wrong breaks every lesson.**
This branch is reached by *every* non-question, non-`HtmlElement` type — all
thirteen `render()` sites in `models.py`, of which eight are leaves. An
unconditional `page=` raises
`TypeError: render() got an unexpected keyword argument 'page'` on each of those
eight, i.e. on essentially every lesson in the corpus.
`courses/tests/test_render_seam.py` exists for exactly this class of break; its own
comment records it as one "plan-review and code-review both caught on the mark-done
build", so this is a repeat failure mode in this codebase, not a hypothetical.

`CONTAINER_MODELS` is a new public name in `builder.py`, **derived** from the
existing registry so it cannot drift:

```python
# The five container model classes, derived from _CONTAINER_REGISTRY so there is
# exactly one place that decides what a container is. Read by
# courses_extras.render_element to decide whether a render() accepts `page=`.
CONTAINER_MODELS = frozenset(_CONTAINER_REGISTRY)
```

**`submitted_values or None` and `mark_result or None` are load-bearing, not
tidiness.** On the quiz page `st = render_states|dictkey:el.pk` is `None` for a
container row, so `st.mark_result` raises `VariableDoesNotExist` and Django
resolves the tag argument to `string_if_invalid`, i.e. `''`. An empty string is not
`None`, so it would survive into the child — and
`ChoiceQuestionElement.choice_marks` evaluates `set(mark_result.reveal or ())`
**before** its mode branch, so `''.reveal` is an `AttributeError` and the page 500s.
Coercing both to `None` at the point the dict is built removes the whole class
rather than one instance; an empty string carries no information for either key.

**`mode` is deliberately NOT in this dict, and must not be added.** Adding it would
make a question nested in a quiz container render in quiz mode — which is exactly
the half-built path §6.5 describes, and it would unblock that path silently, with
no gate tripping and no test failing. §3.4's rationale for a dict ("a fifth value
later means five more edits") invites precisely this mistake, so the exclusion is
recorded here, in §6.5, in §11, and pinned by a test asserting `"mode" not in page`.

**Why the resolved values and not the raw arguments.** At the **top level**
`_lesson_article.html:39` does pass kwargs, so the dict must be built after the
fallback rather than from the raw parameters. At **depth ≥ 2** the inner
`{% render_element child %}` passes no kwargs at all, so raw and resolved coincide
there and it is the inner container's own context fallback that supplies the
values.

### 3.2 Containers splat it first

Each of the five containers gains `page=None` and splats it **first**:

```python
def render(self, *, element=None, state=None, slug=None, node_pk=None, page=None):
    return render_to_string(
        "courses/elements/calloutelement.html",
        {
            **(page or {}),        # FIRST: the container's own keys must win
            "el": self,
            "children": self.resolved_children(),
            "element_state": state,
            "slug": slug,
            "node_pk": node_pk,
        },
    )
```

The invariant is precisely **"`page` is the lowest-precedence source"**, not merely
"`page` comes first". Stated that way because `TabsElement.render`
(`models.py:1780`) already ends its dict with `**self.display_settings()` and will
therefore have **two** splats: `page` goes first of all, `display_settings()` stays
last, and everything the container owns still wins. An implementer copying the
single-splat snippet above verbatim at the tabs site would miss that.

Splatting first makes it impossible for the dict to shadow `el`, `children`,
`element_state`, `eid`, `tabs`, `columns` or `slots`, however the dict later grows.

The five sites are `SpoilerElement.render` (`models.py:454`),
`CalloutElement.render` (`:522`), `BeforeAfterElement.render` (`:591`),
`TabsElement.render` (`:1780`), `TwoColumnElement.render` (`:1892`).

### 3.3 The signature divergence is deliberate

`def render(self, *, element=None, state=None, slug=None, node_pk=None)` appears
**13 times** in `courses/models.py` — it is the shared house render contract for
every element type, **not** a container-specific one. Only the five containers gain
`page`; the other eight keep the four-argument contract. Each of the five carries a
comment stating the reason: containers are the only element types that recursively
render children, so they are the only ones that need to re-emit page context.

Widening all 13 was rejected: eight of them would carry a parameter they can never
use, and the shared contract would stop meaning "a leaf render". That choice is
what forces the call-site gate in §3.1 — the two are a pair, and implementing one
without the other is the `TypeError` described there.

### 3.4 Why one dict, not four keyword arguments

Four named kwargs on five signatures is 20 parameter declarations that must not
drift, and a fifth value later means five more edits. This codebase's recurring
failure mode is one rule living in several structures and drifting —
`courses/tests/test_nesting_rule.py` exists solely to police one such set. One dict
turns five drift-prone sites into one, and the key list lives next to the
parameters it is built from.

---

## 4. Data flow

**Top level (unchanged, bit-identical).** `_lesson_article.html:39` passes the four
page-context values explicitly; the §3.1 fallback would read the same values from
the same context, so it is a no-op there. This is the property that keeps the
existing top-level render byte-for-byte unchanged.

**Quiz page — a NEW forwarding path, inert by construction.** The honest statement
is not "unchanged": `_quiz_article.html:32` passes `feedback_for_pk=el.pk`,
`selected_ids=st.selected_ids`, `submitted_values=st.submitted_values` and
`mark_result=st.mark_result` to **every** top-level element, containers included.
Under §3.1 the non-question branch builds `page` from those resolved values, so a
container in a quiz will now hand them down to its children — a data flow that does
not exist today.

It is inert for three independent reasons, and the third must not be relied on
alone:

1. `st = render_states|dictkey:el.pk` is **`None` for a container row** — the
   `render_states` loop skips every element whose `content_object` is not a
   `QuestionElement` — so `st.submitted_values` and `st.mark_result` raise
   `VariableDoesNotExist` and resolve to `string_if_invalid` (`''`), and
   `feedback_for_pk` is the *container's* pk. §3.1's `or None` coercion is what
   makes those two safe to forward; **without it a quiz containing a container with
   a nested choice question would 500**, not render inertly. `selected_ids` is
   falsy and so is *replaced* by `context.get("selected_ids")` per §3.1's
   truthiness rule, which on the quiz page is absent and yields `frozenset()`.
2. No child's `element.pk` can equal the container's own pk, so §2.2's invariant A
   renders every nested child fresh regardless.
3. After §6, a quiz container cannot legally hold a question at all.

**A standing requirement follows from reason 1.** No quiz page context may ever
introduce a top-level `selected_ids` key: if one appeared, it would be substituted
into every falsy `selected_ids` on that page — including **top-level** quiz
questions, since `build_quiz_context` seeds `"selected_ids": frozenset()` for every
unanswered question (`views.py:1328`). §9.4's quiz test pins the current behaviour
so that introduction would fail loudly.

Because this is a new flow on the one page the lesson-only rule exists to protect,
§9.4 pins it with a test that a quiz page carrying a container with a non-question
child renders identically before and after.

**Editor preview.** `_preview.html:16` renders top-level elements with an explicit
`action_url=try_url`. See §5.

**One level deep.**

```
check_answer (no-JS)
  └─ lesson_unit.html → _lesson_article.html
       └─ render_element(callout_row, feedback_for_pk=42, mark_result=R, …)
            └─ CalloutElement.render(page={feedback_for_pk: 42, mark_result: R, …})
                 └─ calloutelement.html   (context now carries the five names)
                      └─ {% render_element child %}
                           └─ fallback reads feedback_for_pk=42, mark_result=R
                                └─ FillBlankQuestionElement.render(...)
                                     └─ template: element.pk == 42 → verdict renders
```

**Two levels deep** works by the same path with no extra code: the spoiler's
template context carries the five names, its `{% render_element child %}` resolves
them from context, and the inner callout re-emits them again.

**Sibling questions are unaffected**, at any depth — by invariant A for the verdict
and by invariant B for choice markers. §9.4 tests both.

---

## 5. The editor-preview `action_url` gap

`templates/courses/manage/editor/_preview.html:16` renders each **top-level**
element with `action_url=try_url`, reversed against that element's pk and pointing
at the manage-gated, non-persisting `courses:manage_element_try` endpoint. That
kwarg dies at the same barrier, so a nested question renders in the preview with
`action_url=None` and falls back to `QuestionElement.render`'s default — reversing
the **student** `courses:check_answer` endpoint. An author clicking Check in their
own preview hits the student path and persists practice state against their own
account.

This is live today for nested `fill_blank`; the widening makes it the normal
authoring experience, so it is in scope.

**Forwarding `action_url` itself would be wrong** — `try_url` is reversed against
the *parent's* pk, so a forwarded URL would post the child's answer to the parent's
endpoint. What crosses the barrier is a flag, not a URL:

- `_preview.html` adds `editor_preview=True` alongside its existing
  `action_url=try_url`.
- `render_element` gains an `editor_preview=None` parameter (see §3.1 for the
  default and the name), resolves it from context, and carries it in the `page`
  dict.
- In the question branch, when `action_url` is `None` **and** `editor_preview` is
  true, `render_element` reverses `courses:manage_element_try` for **its own**
  element before calling `render()`.

Top-level preview elements keep their explicitly passed `try_url` and are untouched:
the new branch fires only where `action_url` is absent, which today means exactly
"nested". This confines the change to the currently-broken case.

### 5.1 The second Check: `element_try`'s choice branch

Fixing the first render is not enough for `choice`, one of the three newly nestable
types. `courses/views_manage.py::element_try` answers a choice question by
re-rendering the **whole element** so inline per-option feedback lands in the
choices list:

```python
if isinstance(question, ChoiceQuestionElement):
    return HttpResponse(question.render(element=el, mode="lesson", ...))
```

That call passes **no `action_url`**, so the swapped-in form's action falls back to
the student `check_answer` URL — and `editor.js` swaps that form body into the live
DOM. The author's first Check would post correctly (§5's fix) and every subsequent
Check would post to the student endpoint.

`element_try` must therefore pass:

```python
action_url=reverse(
    "courses:manage_element_try",
    kwargs={"slug": el.unit.course.slug, "pk": el.pk},
)
```

`reverse()` takes `kwargs=`, not loose keyword arguments — the loose form raises
`TypeError`. This mirrors how `QuestionElement.render` builds its own fallback URL.
`element_try` already fetches `el` with `select_related("unit__course")`, so the
slug costs no extra query.

This is not a nesting-aware change: the same fix is correct for a top-level choice
question, where the bug is equally live today.

### 5.2 Accepted preview-only query cost

`render_element`'s new branch reads `element.unit.course.slug` to reverse the try
URL. The containers' `resolved_children()` does
`select_related("content_type").prefetch_related("content_object")` but **not**
`select_related("unit__course")`, so this costs up to two extra queries per nested
question — in the **editor preview only**, never on a student page. Accepted rather
than fixed: the preview renders one unit for one author, and widening
`resolved_children()`'s select_related would change five methods used on the
student path too. Recorded here so §8's enumeration of accepted costs is complete.

### 5.3 Stated behaviour change

This also fixes the live nested-`fill_blank` preview defect, and (via §5.1) the
top-level choice re-render. An author who had learned to expect the preview's Check
button to misbehave will find it working.

---

## 6. The widening, and the lesson-only rule

### 6.1 Allowlist

`NESTABLE_TYPE_KEYS` (`courses/builder.py:89`) gains the transfer keys `choice`,
`short_text`, `short_numeric`. `fill_blank` is already a member. The invariant
`NESTABLE_TYPE_KEYS <= set(transfer.export.SERIALIZERS)` continues to hold — all
three are registered serializers.

`_NESTABLE_FORM_KEY_ALIASES` (`:121`) gains the form→transfer mappings the add menu
posts:

| Form key (`data-add-type`) | Transfer key |
|---|---|
| `choice-single` | `choice` |
| `choice-multi` | `choice` |
| `shorttextquestion` | `short_text` |
| `shortnumericquestion` | `short_numeric` |

`fillblankquestion` → `fill_blank` already exists. Note that `choice` takes **two**
form keys — the single/multi distinction is a form concern, not a type concern.

The prose comment above `NESTABLE_TYPE_KEYS` (`builder.py:85-88`) enumerates the
types whose form key differs from their transfer key. It must gain the new entries,
or it becomes an incomplete list sitting directly above the dict it describes.

A new module constant is the single source of truth for "which nestable keys are
questions":

```python
# The nestable QUESTION keys, as transfer keys. Read by the three authorities that
# decide whether a NEW nesting may be created: resolve_scope, paste_allowed, and
# transfer.payloads.validate_nesting. (The LAL loader keeps its own, narrower
# allowlist -- see below.)
#
# The two authorities that decide whether an EXISTING nesting may be preserved
# across a unit_type flip do NOT read this set -- they go through the deliberately
# WIDER unit_has_nested_question(), which spans every QuestionElement subclass.
NESTABLE_QUESTION_KEYS = frozenset({"choice", "short_text", "short_numeric", "fill_blank"})
```

`NESTABLE_QUESTION_KEYS <= NESTABLE_TYPE_KEYS` is an invariant a drift test asserts.

The wider predicate is the second single source of truth:

```python
def unit_has_nested_question(unit):
    """True iff `unit` holds a question inside a container (parent is not null).

    Scoped by content type over ALL QuestionElement subclasses, deliberately WIDER
    than NESTABLE_QUESTION_KEYS: a nested extended_response or drag type can exist
    via a crafted POST or a hand-built archive, and such a unit must still be
    refused the flip to quiz rather than waved through because its type is not on
    the four-key list. Narrowing this to NESTABLE_QUESTION_KEYS reopens that hole.
    """
    # Function-local, matching this module's transfer-import convention
    # (builder.py:437-441). CONCRETE_QUESTION_MODELS is the SAME source §6.4's
    # pre-flight uses -- two lists of ten would drift.
    from courses.richtext import CONCRETE_QUESTION_MODELS

    ct_ids = {
        ContentType.objects.get_for_model(m).id for m in CONCRETE_QUESTION_MODELS
    }
    return Element.objects.filter(
        unit=unit, parent__isnull=False, content_type_id__in=ct_ids
    ).exists()
```

**One hazard to check during implementation, not to assume away.** This runs inside
`rename_node`'s `@transaction.atomic` + `select_for_update` block, and
`ContentType.objects.get_for_model` issues extra SELECTs on a cold cache.
`build_lesson_context` already documents rejecting exactly this pattern because
"cold-cache CT SELECTs break `tests/test_html_element.py`'s query-count assertion".
No existing `assertNumQueries` is known to cover the rename path — the plan must
confirm that rather than trust it, and fall back to an `app_label` +
`model__in=[...]` filter (the shape `has_stateful_elements` uses) if one does.

### 6.2 Add menu

`templates/courses/manage/editor/_add_menu.html` grows a nested `Questions` group
gated `{% if nested and not unit_is_quiz %}`, holding five cards: Single choice,
Multiple choice, Short text, Short numeric, Fill in the blanks.

**Placement is load-bearing.** The existing `Questions` and `Structure` groups sit
inside one `{% if not nested %}` block (`_add_menu.html:57-76`). The new group must
be a **sibling** of that block, not inside it — a `{% if nested %}` group nested
inside `{% if not nested %}` is unreachable, and that failure is *silent*: every
server gate test still passes and the author simply never sees the cards. §9.6
pins it.

The new group takes **no `depth` gate**, unlike the container cards. Questions are
leaves: added from a menu at depth `d` they land at depth `d+1`, and `resolve_scope`
clause 3 accepts a leaf up to `MAX_NEST_DEPTH`. The container cards need
`depth < max_nest_depth|add:-1` only because a container child must itself still
have room for children. This reasoning goes in the template comment, matching how
the file already documents the container gate.

**Which fill-blank card moves.** The file has **two** `data-add-type="fillblankquestion"`
cards. Only the `{% if nested %}`-gated one inside `Interactive` (line 54) moves
into the new group; the top-level `Questions` card (line 64) stays exactly where it
is, or quizzes and top-level lessons lose their fill-blank card. The moved card's
observable availability is unchanged (still hidden in quizzes, still offered nested
in lessons); it simply stops being an oddity in a group of ungraded widgets.

The **top-level** `Questions` group keeps its `{% if not nested %}` gate with **no**
quiz condition. Quizzes must keep offering top-level questions; only the nested
group is quiz-gated.

Hiding cards is courtesy only — the server enforces the rules below on every
add/save/paste regardless.

### 6.3 Lesson-only: five authorities

A question may be nested **only in a lesson unit**. Five write paths can create or
preserve such a nesting, and all five must enforce it.

**1. `builder.resolve_scope` (`builder.py:262`).** New clause immediately after
clause 1 — the `NESTABLE_TYPE_KEYS` membership check at `builder.py:284-285`, which
raises `NestingError(f"{type_key} may not be nested")` and has no reason key of its
own:

```python
if child_key in NESTABLE_QUESTION_KEYS and unit.unit_type == ContentNode.UnitType.QUIZ:
    raise NestingError("questions may not be nested in a quiz")
```

`unit` is already the first parameter.

**2. `builder.paste_allowed` (`builder.py:372`).** New reason key
`question_in_quiz`, checked immediately after the existing `type_not_nestable`
clause (`builder.py:441-444`) and using the same function-local `model_to_key` hop:

```python
if (model_to_key(type(marked_join.content_object)) in NESTABLE_QUESTION_KEYS
        and unit.unit_type == ContentNode.UnitType.QUIZ):
    return False, "question_in_quiz"
```

The clause lives **inside the `dest_parent is not None` branch**, alongside
`type_not_nestable`. This is load-bearing: pasting a question to **top level** in a
quiz must stay legal, and the `dest_parent is None` branch must not see this check.

Reason precedence is documented in `paste_allowed`'s docstring and depended on by
tests; the new key lands as: `wrong_unit`, `into_own_subtree`, `not_a_container`,
`unknown_slot`, `type_not_nestable`, **`question_in_quiz`**, `too_deep`,
`own_slot`.

**A reason key without a message is a silent half-fix.** The paste endpoint does not
render the key — it looks it up in `PASTE_REFUSAL_MESSAGES`
(`views_manage.py:1558-1567`, a `gettext_lazy` map that today has eight entries) and
falls back at `:1757` to a generic string. That map's own comment says it exists
precisely so the author "sees why nothing moved" instead of a generic "that did not
work". So `PASTE_REFUSAL_MESSAGES["question_in_quiz"]` must land with the clause,
and §9.5's gate test must assert the **message**, not only the key — asserting the
key alone would pass with the generic fallback showing. Better still, a completeness
assertion that every reason `paste_allowed` can return has a map entry, so the next
reason key cannot land message-less either.

**Known narrowness, accepted and documented.** Clause 2 checks the **root** of the
pasted subtree only, on the stated grounds that every descendant passed nestability
when it was created. The new clause inherits that narrowness: pasting a *container*
that already holds a question would not re-check the descendant. This is sound
given authority 3 (a unit cannot become a quiz while such content exists) and
clause 0 (`wrong_unit` — cross-unit pastes are impossible), so the only way to
reach the hole is pre-existing malformed content. Documented at the clause rather
than closed.

**3. `builder.rename_node` (`builder.py:589`).** This is the function that mutates
`unit_type` — there is no `update_node` in this repo. Its `unit_type is not _UNSET`
branch is at `builder.py:606-608`. The guard:

- runs **after** `_check_token` (`:600`), so a stale-token request fails on the
  token, not on content — the token is the concurrency contract and must win;
- fires only when the **new** value is `QUIZ` **and** differs from the current
  `node.unit_type`, so a no-op resubmit of `unit_type=quiz` on an already-quiz unit
  is accepted rather than refused;
- is unconditional in the other direction — quiz→lesson is always allowed, since it
  only ever makes nested questions *more* correct;
- uses `unit_has_nested_question(node)` (§6.1), not `NESTABLE_QUESTION_KEYS`;
- raises `ValidationError` naming the fix ("move the question out of the container
  first"), matching `set_node_flag`'s existing refusal style for `obligatory` on a
  quiz.

**4. `transfer.payloads.validate_nesting` (`payloads.py:858`).** Rejects an archive
that nests a question inside a container in a quiz unit.

The predicate is `el["type"] in NESTABLE_QUESTION_KEYS` and the parent unit's type
`== "quiz"` — the **raw string**, since the archive's `unit_type` is validated at
`schema.py:281` against the literal pair `("lesson", "quiz")` and never becomes a
`ContentNode` instance. The non-nestable question types need no mention: the
existing `NESTABLE_TYPE_KEYS` clause (`payloads.py:922`) already refuses them
outright.

The new parameter is **keyword-with-default** (`unit_types=None`), and the quiz
check is skipped when it is `None`. This is required, not a convenience: there are
**19 positional test call sites across six files** —
`courses/tests/test_beforeafter_transfer.py`, `courses/tests/test_callout_transfer.py`,
`courses/tests/test_spoiler_transfer.py`, `tests/test_tabs_transfer.py`,
`tests/test_transfer_nesting_depth.py`, `tests/test_twocolumn_transfer.py` — all
exercising other clauses, and all of which must keep working untouched.

The **one** call site that changes is the production caller,
`courses/transfer/schema.py:358`, which gains `unit_types=`. The map is buildable in
the node loop that already validates `nd["unit_type"]`: `{node_id: unit_type}` for
nodes of kind `unit`. `validate_nesting` looks up `el["unit"]`, which every element
already carries and which the element loop has already validated points at a unit
node.

**5. The LAL loader (`courses/lal_loader/builders.py`) — ONE gate, at child
creation.** This is a real, currently-invisible authority: it builds nested
`Element` rows directly, bypassing `builder` entirely, and it built the 793-unit
imported corpus §8 cites. Its nesting surface is **spoiler-only** (the nested branch
lives under `if etype == "spoiler"`), and it gates children against its own
allowlist `LAL_SPOILER_CHILD_TYPES` (`:55-72`), which already contains `fill_blank`
and never consults `NESTABLE_TYPE_KEYS` or `unit.unit_type`. It gains the quiz
refusal at that same site — alongside the allowlist test and **after** the
`flagged`-child exemption, which bypasses the allowlist entirely and can only ever
produce an `HtmlElement`, never a question — raising `LoaderError`.

**The gate is `fill_blank`-only in practice.** `LAL_SPOILER_CHILD_TYPES`'s sole
question member is `fill_blank`; `choice`, `short_text` and `short_numeric` are
absent and deliberately stay absent, since the two allowlists are not merged. So
§9.5's loader test must use `fill_blank` — with any other type the allowlist refuses
first and the new clause is never reached, making the test assert nothing.

**A guard on `tree.upsert_node`'s unit_type re-sync is deliberately NOT added**, and
the ordering is why. In `courses/management/commands/import_lal_content.py`,
`upsert_node` runs at `:61` and `rebuild_unit_elements` at `:71` — and the rebuild
**deletes every element of the unit** before rebuilding from the manifest. A guard
inside `upsert_node` would therefore inspect the *previous* run's content and refuse
a manifest revision that legitimately flips a unit to quiz **and** drops its nested
question in the same revision.

The child-creation gate needs no such stale read and is sufficient on its own,
because the flip lands first: by the time `rebuild_unit_elements` creates children,
`unit.unit_type` already holds the **new** value, so a question child in a
now-quiz unit is refused at creation. The whole command runs inside
`transaction.atomic()` (`import_lal_content.py:50`), so that `LoaderError` rolls the
unit_type flip back with it — no partial state where a unit is flipped and emptied.

Note the loader's own allowlist is deliberately **not** merged into
`NESTABLE_TYPE_KEYS`. It is narrower on purpose (it describes what the LAL corpus
may contain, not what an author may build), and merging them would widen the
importer as a side effect of widening the editor.

### 6.4 Pre-existing content

The UI has never offered a question card in a nested menu inside a quiz, so
reaching this state requires a crafted POST, a hand-built archive, or the LAL path
in §6.3. Existing affected content is expected to be **none**, and the plan
verifies rather than assumes it with a read-only pre-flight:

```python
from courses.richtext import CONCRETE_QUESTION_MODELS

question_ct_ids = {
    ContentType.objects.get_for_model(m).id for m in CONCRETE_QUESTION_MODELS
}
Element.objects.filter(
    parent__isnull=False,
    content_type_id__in=question_ct_ids,
    unit__unit_type=ContentNode.UnitType.QUIZ,
).count()
```

`courses.richtext.CONCRETE_QUESTION_MODELS` is the importable ten-model list (its
length is asserted at 10 by `tests/test_richtext.py:273`). `build_lesson_context`'s
`question_models` is **function-local and lowercase** — it is not importable and
must not be referenced here. The set is all ten types, not the four widened ones:
the point is to find anything at all, including a type that could only have arrived
irregularly.

Run against the **local development database** (the real mat-pp copy). A non-zero
count halts the run and is reported; it is not auto-repaired, because the right
remedy (un-nest, delete, or convert the unit) is an editorial decision.

### 6.5 Why the lesson-only rule exists: the latent quiz-mode bug

`render_element`'s `mode` parameter defaults to `"lesson"`.
`_quiz_article.html:32` passes `mode="quiz"`, but only to **top-level** elements.
Containers drop it twice: their `render()` has no `mode` parameter, and the
template's bare `{% render_element child %}` restarts from the default.

So a question nested in a container inside a quiz renders as a **lesson** question:
a Check button posting to `check_answer` instead of `quiz_answer`, no attempt cap,
no lock after submit, no question number — and because `render_states`
(`courses/views.py`, the `build_quiz_context` loop) is built only over top-level
elements, no `QuizResponse` row and no marks. An ungraded question hidden inside a
graded quiz, invisible to analytics.

Fixing that properly means giving nested questions the whole per-element quiz
plumbing (`render_states`, `action_url`, `locked`, `attempts_left`, `qnum`,
numbering across slides). That is a separate, larger piece of work. Until it is
done, the lesson-only rule is what keeps the bug unreachable — and today it is
*not* enforced: `resolve_scope` and `paste_allowed` never look at `unit.unit_type`,
so only the UI's card-hiding stands between an author and this state.

**This is why `mode` must stay out of the `page` dict** (§3.1). Adding it would
half-fix this path — correct rendering mode, still no `render_states`, still no
marks — which is worse than leaving it visibly unsupported.

---

## 7. Error handling

- **`render_element` fallback.** `context.get` on a missing key returns `None`,
  which is the same value the parameters default to, so a call site that supplies
  nothing behaves exactly as today. The fallback itself cannot raise — but what it
  forwards can: an unresolvable template variable arrives as `''`, not `None`, and
  `''` reaching `choice_marks` is an `AttributeError`. §3.1's `or None` coercion is
  the guard, and it is the reason this bullet does not simply read "no branch can
  raise".
- **Non-container leaves.** `page` is passed only to the five containers (§3.1); the
  other eight `render()` signatures never see it and cannot `TypeError` on it.
- **`page=None`.** `**(page or {})` handles a container `render()` called directly
  with no `page` — the shape used by unit tests and by `test_render_seam`'s
  CONCRETES loop, which passes no `element` either.
- **Shadowing.** Structurally impossible: `page` is the lowest-precedence source, so
  any collision resolves in favour of the container's own key. §9.4 pins this by
  passing a `page` dict containing an `el` key and asserting the container still
  renders its own element.
- **Nesting violations** raise `NestingError`, which the element add/save views
  already turn into a 400; `paste_allowed` returns `(False, reason)` which the paste
  endpoint already turns into a 422 with the reason. Both are existing machinery —
  the new clauses add a case, not a new failure mode.
- **`rename_node` refusal** raises `ValidationError`; see §6.3 authority 3 for the
  exact ordering and no-op semantics.
- **Import rejection** uses `validate_nesting`'s existing `_err()` helper, so it
  reports like every other nesting violation and is translatable.
- **LAL loader refusal** raises `LoaderError` (defined in `lal_loader/builders.py`,
  the fail-loud convention `lal_loader/guards.py` already uses), not `NestingError`
  — the loader reports against source files, not HTTP requests, and its messages are
  operator-facing rather than translated. The command's `transaction.atomic()` makes
  the refusal a clean rollback.

**Translations.** The `NestingError`, `ValidationError`, `_err()` and
`PASTE_REFUSAL_MESSAGES["question_in_quiz"]` messages are new user-facing msgids
(the loader's `LoaderError` is not — see above).
`makemessages` must be re-run and `locale/en/LC_MESSAGES/django.po` +
`locale/pl/LC_MESSAGES/django.po` updated, with any fuzzy pre-fill cleared —
`makemessages` fuzzy-fills a *wrong* Polish string from a similar msgid, and a fuzzy
entry is not used at runtime, so it reads as "translation missing" in production.
Recompile before the PR, and rebase-then-regenerate if the branch goes stale, since
`.mo` is binary and conflicts badly.

---

## 8. Performance

`build_lesson_context` prefetches `choices` / `blanks` only for **top-level**
questions — its `elements` list is `parent__isnull=True`. A nested `choice`
question therefore re-queries `choices.all()` on each render.

**Accepted and documented, not fixed.** It matches the "ACCEPTED LIMITATION"
already recorded a few lines above it for nested checklist items, the cost is
bounded (per-unit question counts are small; the largest imported course averages
~25 elements per unit), and closing it would cost an extra flat query on **every**
lesson render including the vast majority with no nesting. A comment at the
prefetch block records the trade-off so it is a decision rather than an oversight.

Note this is a *pre-existing* shape, not a regression: nested `fill_blank`'s
`blanks` is un-prefetched today for the same reason.

The second accepted cost is the editor preview's try-URL reversal — see §5.2.

---

## 9. Testing

### 9.1 RED first, from tests that already exist

`courses/tests/test_nested_question_nojs_feedback.py` exists on branch
`test/nested-question-nojs-feedback` at commit `06776cf4` — 11 tests, ruff clean,
tests only, never pushed. It **pins the defect**: five parametrized assertions read
`assert VERDICT not in body`.

That is **one parametrized assertion line**, covering five cases. It is **inverted**
to `assert VERDICT in body`, which fails on today's code before any production
change; the function is **renamed** from `test_nested_blank_answer_shows_no_feedback`
to `test_nested_blank_answer_shows_feedback` in the same edit (§9.2 and §9.3 refer
to it by the new name); and the module docstring is rewritten from "here is the
divergence" to "here is the contract", keeping the falsification history.

The commit rebases cleanly (`master..test/nested-question-nojs-feedback` contains
only it).

**The blank-answer case is the discriminator.** Nothing is stored for a blank
answer, so a verdict can only arrive via the live forwarding path.

**The non-blank case is REROUTED by this change, not merely unchanged.** Today a
nested child reaches `render_element` with `feedback_for_pk=None`, so the restore
branch's `element.pk != feedback_for_pk` guard holds even for the element just
checked, and its verdict comes from `rehydrate` + re-`mark` of the **stored** answer
— a JSON round-trip. After the §3.1 fallback, `feedback_for_pk` resolves to the
checked pk, the guard fails, restore is skipped, and the verdict comes from the
**live** `mark_result` / `submitted_values` straight off the POST.

The rendered output should be identical, but it is produced by a different code path
from a different data source, so "control that passes either way" understates it.
The six controls stay in place, and §9.4 adds an equivalence test exercising a value
where the two routes could plausibly diverge — leading/trailing whitespace, which
the JSON round-trip preserves and the raw POST may not.

The existing structural guards are retained verbatim, because the flipped tests
still need them: `status_code == 200`, `body.count("el--fillblank") == 2`, and each
container's **own** child wrapper class (`callout__child` / `spoiler__child` /
`tabs__child` / `twocolumn__child` / `ba__child` — without that last one the
parametrization would be five copies of the callout assertion).

The before/after fixture must keep nesting into the **AFTER** slot:
`resolved_slots()` appends a child with an unrecognised `tab_id` to the `before`
bucket, so a before-slot fixture would render even with a wrong slot id and prove
nothing.

### 9.2 The ten seam tests, enumerated

"The seam tests" is a fixed, named set — §9.3's mutant table is stated over it, so
it cannot be left implicit. Every one submits a **blank** answer and asserts a
verdict renders. All live in
`courses/tests/test_nested_question_nojs_feedback.py`:

| # | Test | Nests in | Axis |
|---|---|---|---|
| 1–5 | `test_nested_blank_answer_shows_feedback[callout\|spoiler\|tabs\|two_column\|before_after]` | each container | container (fill_blank) |
| 6–8 | `test_nested_blank_answer_shows_feedback_by_type[choice\|short_text\|short_numeric]` | callout | type |
| 9 | `test_nested_blank_answer_shows_feedback_at_depth_2` | callout in spoiler | recursion |
| 10 | `test_only_the_checked_question_shows_a_verdict` | callout | the §2.2 invariants |

**Three** new types on the type axis, not four: `fill_blank` × callout is already
row 1, so listing it again would be a redundant cell.

Six **controls** carry over unchanged and must stay **green under every mutant** in
§9.3 — they pass on today's code and must keep passing:
`test_top_level_blank_answer_shows_feedback` (1) and
`test_nested_non_blank_answer_does_show_feedback[…]` (5, one per container).

§9.4's six claim-tests also live in this file. File total: **22 tests** (11
existing + 5 new seam + 6 claim).

**Per-type structural guards.** The retained `el--fillblank` count-of-2 guard is
fill-blank-specific and does not transfer. Each type-axis case asserts its own
wrapper class is present (`el--question` plus the type's own marker as rendered by
its template) **and** `callout__child`, so an absent nested render cannot be
mistaken for a passing test. The scene fixture grows a same-type top-level twin per
type so a count-of-2 assertion stays available on that axis too.

**What "blank" is on the wire**, per type — this must be exact, or `answer_is_empty`
never fires and the test proves nothing:

| Type | `build_answer` | Blank POST |
|---|---|---|
| `fill_blank` | `post.getlist("blank")` | `{"blank": [""]}` |
| `choice` | `post.getlist("choice")` → set | **no `choice` key at all** |
| `short_text` | `post.get("answer", "")` | `{"answer": ""}` |
| `short_numeric` | `post.get("answer", "")` | `{"answer": ""}` |

### 9.3 Falsification — each test names its mutant

Per the house rule, tests must be shown RED, not merely run. "The ten" is §9.2's
enumerated set; "the six" are its controls.

| Mutant | Expected RED |
|---|---|
| Pass `page=` **unconditionally**, without the `CONTAINER_MODELS` gate | `courses/tests/test_render_seam.py` (13 concretes × 6 placements) — the whole-corpus break §3.1 describes |
| Delete the five `context.get` fallback statements in `render_element` | All ten; six controls stay green |
| Drop the `or None` coercion on `mark_result` / `submitted_values` | The §9.4 quiz-page test (nested choice in a quiz 500s on `''.reveal`) |
| Drop the `page=` argument at the `render_element` call site | All ten; six controls stay green |
| Delete `**(page or {})` from **callout**'s `render()` | Tests 1, 6, 7, 8, 9, 10 |
| Delete `**(page or {})` from **spoiler**'s `render()` | Tests 2 and 9 |
| Delete `**(page or {})` from **tabs** / **two_column** / **before_after** | Test 3 / 4 / 5 respectively — one each |
| Move the splat from first to last in one container | The §9.4 shadowing test |
| Default `editor_preview` to `False` instead of `None` | The §9.7 preview tests (this is the §3.1 trap, pinned) |
| Widen `resolve_scope`'s new clause to accept quizzes | The `resolve_scope` gate test |
| Drop the `dest_parent is not None` scoping on `paste_allowed`'s clause | The top-level-paste-into-quiz test |
| Move the new add-menu group inside the `{% if not nested %}` block | The §9.6 nested-lesson menu test |

**Per-container blast radius is deliberately uneven**, and the table states it
rather than leaving an implementer to read the extra REDs as a broken test: tests
6–10 all nest in a callout and test 9 nests in a callout inside a spoiler. Only
tabs, two_column and before_after give one-test isolation — they are the containers
that actually prove the parametrization is not five copies of one assertion.

The historical falsification is recorded too: mutating `courses/views.py:1060`
(`answer_is_empty(answer)` → `False`) turned all five absence cases RED while the
other six stayed green, which is what pinned the mechanism originally.

**A vacuity warning worth preserving.** The first draft of the absence test asserted
`data-question="{pk}"` and passed for the wrong reason — `data-question` is a
**bare attribute carrying no pk**. Any new assertion on question markup must be
checked against that trap.

### 9.4 Tests for the design's own claims

Five claims this spec leans on are asserted directly rather than trusted. All live
in `courses/tests/test_nested_question_nojs_feedback.py` alongside the seam tests:

- **Invariant A** (seam test 10): with two questions nested in the same container
  and one checked, `body.count(VERDICT) == 1`, and the verdict falls inside the
  checked child's own wrapper — not the sibling's, not the container's body.
  Without this, every flipped assertion would pass just as well if the fix leaked a
  verdict onto every question on the page.
- **Invariant B**: with two `choice` questions nested in the same container and one
  checked, the sibling renders **zero** `question__choice-marker` and
  `question__choice-feedback` nodes. Seam test 10 cannot catch this — the marker
  path emits no verdict block to count.
- **The quiz page still renders** — two executable assertions, since a test cannot
  compare against pre-change code: (1) a quiz containing a container with a nested
  child returns **200** and that child renders with no `question__verdict` and no
  `question__choice-marker`; the child is a **`choice`** question, because that is
  the type that would `AttributeError` on a forwarded `''` (§3.1). Reaching that
  state needs a direct `Element.objects.create`, since §6 forbids authoring it —
  which is the point: legacy content must not 500. (2) `"selected_ids" not in
  build_quiz_context(...)`, so §4's standing requirement fails loudly if a future
  change introduces one.
- **Restore and live routes agree** (§9.1): a non-blank nested answer whose value
  has leading and trailing whitespace yields the same verdict and the same refilled
  value as the stored-answer route did.
- **Shadowing is impossible**: a container `render()` called with a `page` dict
  carrying an `el` key still renders its own element.
- **`mode` is not forwarded**: the dict `render_element` builds has no `mode` key.

### 9.5 Gate tests

One per authority: `resolve_scope` raises for a question into a quiz container;
`paste_allowed` returns `question_in_quiz`, returns it at the right point in the
precedence (a case that would also trip `too_deep` reports `question_in_quiz`),
still permits a **top-level** paste into a quiz, and — asserted on the endpoint, not
the function — surfaces its **own** `PASTE_REFUSAL_MESSAGES` string rather than the
generic fallback, plus a completeness assertion that every reason `paste_allowed`
can return has a map entry; `rename_node` refuses the lesson→quiz flip, leaves
`unit_type` unchanged, accepts the quiz→quiz no-op, and allows quiz→lesson;
`validate_nesting` rejects the archive **and** still accepts its 19 existing
positional call sites; the LAL loader refuses a **`fill_blank`** child in a quiz unit
(the only type that reaches the clause — see §6.3 authority 5) **and** allows a
manifest that flips a unit to quiz while dropping its nested question in the same
revision (the case that authority exists to keep working).

Plus the preview tests (§9.7) and a drift test extending
`courses/tests/test_nesting_rule.py`: `NESTABLE_QUESTION_KEYS <= NESTABLE_TYPE_KEYS`,
every member is in `transfer.export.SERIALIZERS`, and every new form-key alias
resolves into `NESTABLE_TYPE_KEYS`.

### 9.6 Existing tests that MUST go red, and their rewrites

Existing tests in **three** files assert the exact behaviour this spec changes.
Their RED is expected, not a regression, and an implementer must be told so up front
— one of them names our change as its mutant in its own docstring.

**`courses/tests/test_beforeafter_nesting.py::test_a_graded_question_is_still_refused_as_a_child`**
calls `resolve_scope(unit, …, "choice")` inside `pytest.raises(NestingError)` on a
**lesson** unit, with the docstring *"Mutant: add `choice` to NESTABLE_TYPE_KEYS ->
accepted."* After the widening it passes rather than raises. Rewrite: the refusal is
now conditional on `unit.unit_type`, so assert refusal in a **quiz** unit and
acceptance in a lesson.

**`courses/tests/test_spoiler_nesting.py`** asserts the new cards are absent from
nested menus in three places — the `banned_question` loop at `:351-363`, the
`isdisjoint({"choice-single", "shorttextquestion", "dragfillblankquestion"})`
assertion at `:389`, and the `banned_question` loop at `:444-448`. Rewrite: the
drag/grid/extended keys stay banned nested; the four widened keys become
expected-**present** in a lesson and expected-**absent** in a quiz.

**`tests/test_tabs_transfer.py::test_nesting_validation_rejects`** carries the
parametrized case `_els(_tabs_el(), _child(type_="choice"))  # non-nestable child`
(`:142`) inside `pytest.raises(TransferError)`. Once `choice` joins
`NESTABLE_TYPE_KEYS` that document validates cleanly — the fixture passes no
`unit_types`, so the new quiz clause is skipped by design — and the case fails. The
keyword-with-default protects the *signature*, not this *assertion*. Rewrite: swap
the subject for a still-non-nestable type (`extended_response` or
`drag_fill_blank`), and add a positive case asserting `choice` is now accepted
nested.

`test_spoiler_nesting.py` is also the natural home for the **add-menu placement
tests** §6.2 requires, since the silent-unreachable-group failure is invisible to
every other test: nested + lesson shows the five cards; nested + quiz shows none of
them; the top-level menu is unchanged.

**On that last one, mind which fixture.**
`tests/test_manage_editor_menu.py` pins `body.count('data-add-type="') == 24`, and
24 is the count for a **quiz** unit — both its tests use `unit_type="quiz"`, where
the whole `Interactive` group is suppressed by `{% if not unit_is_quiz %}`. A
top-level **lesson** menu carries 34 cards and is not pinned anywhere. Neither
number moves, since the new group is gated `nested and not unit_is_quiz`; the
numbers are recorded here so a lesson-menu assertion is not misread as a
regression.

### 9.7 Preview tests

A nested question's rendered form `action` is `manage_element_try` for **its own**
pk — asserted as three distinct facts, since two of them are the actual bug: not
`check_answer`, not the parent's pk, and equal to the child's own try URL.

Separately for §5.1: `element_try`'s choice re-render returns a form whose action is
`manage_element_try`, not `check_answer` — asserted for a top-level choice question
too, where the bug is equally live today.

### 9.8 e2e

A nested `choice` question inside a **closed** `<details>` spoiler and inside an
**inactive** tab panel still checks and shows inline feedback with JS on.

Two known traps to design around:

- Playwright reports a `.visually-hidden` element as **visible** (1×1 + `clip` has a
  non-empty box) — assert on `bounding_box()`, not `is_visible()`.
- A closed `<details>` hides its content via `content-visibility`, so use
  `checkVisibility()` rather than `is_visible()`.

`question.js` binds to `[data-question]` document-wide with no depth assumption, so
no JS change is expected; the e2e exists to prove that rather than assume it.

### 9.9 Visual verification

Light **and** dark screenshots of a question inside each of the five containers,
with dark judged on its own rather than as "light but inverted".

If any CSS turns out to be needed for nested-question spacing, it gets an **A/B**
with the rule removed — measuring with the rule present proves nothing about
whether the rule does anything.

### 9.10 Test-run mechanics

- Start the test-DB container **before** any pytest run; if it is down the suite
  looks hung for ~4m21s.
- `uv run` for pytest/ruff/python — none are on PATH.
- e2e needs `-m e2e` explicitly or it silently deselects (exit 5).
- Scope runs narrowly per task; the whole-repo sweep is a branch gate, not a task
  step.

---

## 10. Files touched

| File | Change |
|---|---|
| `courses/templatetags/courses_extras.py` | `render_element`: five context fallbacks, `editor_preview=None` parameter, `page` dict **gated on `CONTAINER_MODELS`** with `or None` coercion, nested-preview try-URL branch |
| `courses/models.py` | `page=None` + splat-first on the five container `render()`s (`:454`, `:522`, `:591`, `:1780`, `:1892`); tabs keeps `display_settings()` last |
| `courses/builder.py` | `NESTABLE_TYPE_KEYS` += 3 keys; alias-comment update; `_NESTABLE_FORM_KEY_ALIASES` += 4 aliases; new `NESTABLE_QUESTION_KEYS`, `CONTAINER_MODELS` and `unit_has_nested_question`; `resolve_scope` clause; `paste_allowed` clause + reason; `rename_node` flip guard |
| `courses/views_manage.py` | `element_try`'s choice branch passes `action_url` (§5.1); `PASTE_REFUSAL_MESSAGES["question_in_quiz"]` |
| `courses/views.py` | **Comment only** — the `has_questions` comment ("Only fill_blank is nestable today") becomes false |
| `courses/transfer/payloads.py` | `validate_nesting` gains `unit_types=None`, rejects question-in-quiz nesting |
| `courses/transfer/schema.py` | Builds and passes the unit-type map (`:358`) — the one production call site that changes |
| `courses/lal_loader/builders.py` | Question child refused in a quiz unit (the single loader gate) |
| `templates/courses/manage/editor/_add_menu.html` | Nested `Questions` group (sibling of the `{% if not nested %}` block); the `{% if nested %}` fill-blank card moved out of `Interactive`; top-level card untouched |
| `templates/courses/manage/editor/_preview.html` | `editor_preview=True` on the `render_element` call |
| `courses/tests/test_nested_question_nojs_feedback.py` | Cherry-picked from `06776cf4`, the parametrized assertion inverted + function renamed, eleven cases added (5 seam + 6 claim) |
| `courses/tests/test_render_seam.py` | **The gate on §3.1's container check** — 13 concretes × 6 placements; no edit expected, but it is the test that catches an unconditional `page=` |
| `courses/tests/test_beforeafter_nesting.py` | **Expected RED** — rewrite the graded-question refusal as quiz-conditional (§9.6) |
| `courses/tests/test_spoiler_nesting.py` | **Expected RED** — three assertions rewritten; new home for the add-menu placement tests (§9.6) |
| `courses/tests/test_nesting_rule.py` | Drift assertions for `NESTABLE_QUESTION_KEYS` |
| `tests/test_manage_editor_menu.py` | Verify the top-level card count stays 24 |
| `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ `.mo`) | New msgids; fuzzy pre-fills cleared |
| `tests/test_tabs_transfer.py` | **Expected RED** — the `choice`-child rejection case at `:142` must change subject (§9.6) |
| `courses/tests/test_beforeafter_transfer.py`, `test_callout_transfer.py`, `test_spoiler_transfer.py`, `tests/test_transfer_nesting_depth.py`, `tests/test_twocolumn_transfer.py` | No **signature** edit — the 19 positional `validate_nesting` call sites are exactly what the keyword-with-default protects (§6.3 authority 4). Note `test_tabs_transfer.py` shares that protection but still needs the assertion change above |

No migration. No new model field. No JS change expected.

---

## 11. Open decisions already made

Recorded so they are not re-litigated:

- **Five form-only types, not ten** — drag and grid types excluded (§1 non-goals).
- **`extended_response` excluded**, leaving four nestable question types.
- **Lesson-only**, enforced at **five** authorities rather than left to the UI —
  including the LAL loader, which bypasses `builder` entirely.
- **Block the lesson→quiz flip** (in `rename_node`, not the non-existent
  `update_node`) rather than un-nesting the author's questions silently or leaving
  the unit broken.
- **The LAL guard sits at child creation, not on `upsert_node`** — the rebuild
  deletes and re-creates elements after the flip, so a guard on the flip would read
  the previous run's content and refuse a legal manifest revision.
- **One `page` dict**, not four kwargs and not template-level forwarding — passed
  **only to containers**, gated on `CONTAINER_MODELS`. The eight leaf `render()`s
  share the generic branch and would `TypeError` on an unconditional `page=`.
- **`mark_result` and `submitted_values` are coerced with `or None`** when the dict
  is built, because an unresolvable template variable arrives as `''`, and `''`
  reaching `choice_marks` is an `AttributeError`, not an inert value.
- **`mode` stays OUT of the `page` dict** — adding it would half-fix the quiz path
  described in §6.5, which is worse than leaving it visibly unsupported.
- **`editor_preview`, defaulting to `None`** — `False` makes its own fallback dead
  code, and the bare name `preview` collides in meaning with the existing
  `previewing` student flag.
- **`selected_ids` resolves by truthiness** while the other four use `is None`,
  because its parameter default is `frozenset()` (§3.1), with the standing
  requirement in §4 that follows from it.
- **`unit_has_nested_question` is deliberately wider** than
  `NESTABLE_QUESTION_KEYS`.
- **The LAL loader's own allowlist is not merged** into `NESTABLE_TYPE_KEYS`; it is
  deliberately narrower.
- **The non-blank nested path is rerouted** (restore → live), not untouched, and
  §9.4 pins that the two routes agree.
- **Two accepted costs**: the nested-choice prefetch N+1 (§8) and the preview
  try-URL reversal (§5.2).
