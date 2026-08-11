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
- **The quiz-mode render seam is not fixed here.** It is documented in §6.6 as the
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
not passed explicitly. **Six** explicit statements — one per key in the dict below,
five conditional plus the context-only `feedback_ancestor_pks` — rather than a loop
or a helper, so each name stays greppable:

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
# Context-only, never a tag argument -- page-level by nature (§4.1).
feedback_ancestor_pks = context.get("feedback_ancestor_pks") or frozenset()
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
        "editor_preview": editor_preview,          # §5
        "feedback_ancestor_pks": feedback_ancestor_pks,   # §4.1
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

**`mark_result or None` is load-bearing, not tidiness.** On the quiz page
`st = render_states|dictkey:el.pk` is `None` for a container row, so
`st.mark_result` raises `VariableDoesNotExist` and Django resolves the tag argument
to `string_if_invalid`, i.e. `''`. An empty string is not `None`, so it would
survive into the child — and
`ChoiceQuestionElement.choice_marks` evaluates `set(mark_result.reveal or ())` after
its `None` and quiz-lock early returns but **before** the per-choice mode branch —
and that line is reachable precisely because a nested child always renders with
`mode="lesson"` (§3.1 keeps `mode` out of the dict), which slips past the
`mode != "lesson" and not locked` return. So `''.reveal` is an `AttributeError` and
the page 500s.
Coercing it to `None` at the point the dict is built removes the whole class rather
than one instance: for `mark_result`, `''` genuinely carries nothing.

**`submitted_values or None` is a different case and needs a narrower
justification.** Its `''` is not always a resolution failure: on the lesson no-JS
path a **blank** `short_text` / `short_numeric` answer legitimately produces
`ctx["submitted_values"] = ""` (`check_answer` keeps the non-set answer as-is, and
`build_answer` returns `post.get("answer", "")`). That is exactly the path seam
tests 7 and 8 drive, so the coercion fires on a real value and a nested child
receives `None` where its top-level twin receives `""`.

It is observationally inert **because both refill sites pipe through
`default_if_none:''`** — `shorttextquestionelement.html:9` and
`shortnumericquestionelement.html:9` — so `None` and `""` render identically. That
is a load-bearing template detail, not a coincidence, so §9.4 pins it: a blank
nested short-text answer and a blank top-level one must refill to the same empty
value. A future template dropping `default_if_none` would otherwise break nested
refill silently.

**`mode` is deliberately NOT in this dict, and must not be added.** Adding it would
make a question nested in a quiz container render in quiz mode — which is exactly
the half-built path §6.6 describes, and it would unblock that path silently, with
no gate tripping and no test failing. §3.4's rationale for a dict ("a fifth value
later means five more edits") invites precisely this mistake, so the exclusion is
recorded here, in §6.6, in §11, and pinned by a test asserting `"mode" not in page`.

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

### 4.1 The spoiler must re-open, or the fix is invisible

`spoilerelement.html:2` is a bare `<details class="spoiler">` with no `open`
attribute, and nothing re-opens it — the only `details.open` persistence in the
codebase is `editor.js`'s editor-tab state, which never touches a student page.

The no-JS path is a **full page re-render**. So a student opens a spoiler, answers
the question inside it, submits — and gets back a page where the spoiler is closed
again and the freshly rendered verdict is hidden inside it. Plumbing the values
through without this would leave the student in exactly the state §1a describes, for
the one container the nested-question capability was originally built for.

It also defeats the test: `assert VERDICT in body` is a raw-string check on the
response body and passes whether or not the markup is reachable — the same vacuity
shape as the `data-question` trap in §9.3.

**The rule: a spoiler renders `open` when the checked element is anywhere in its
subtree.** Ancestry, not direct childhood, so a question inside a callout inside a
spoiler opens the spoiler too.

The ancestor set is computed **once per page**, in `check_answer`, by walking
`element.parent` upward. `MAX_NEST_DEPTH` is 4 and a top-level element has depth 1,
so well-formed content has at most **three** ancestors and the walk always
terminates on `node is None`; the `hops` guard never fires on legal data and exists
purely as a corruption backstop, capping a cycle at `MAX_NEST_DEPTH` iterations.
`parent_id` is already on each row, so the cost is at most three extra fetches:

```python
ancestors, node, hops = set(), element.parent, 0
while node is not None and hops <= MAX_NEST_DEPTH:
    ancestors.add(node.pk)
    node = node.parent
    hops += 1
ctx["feedback_ancestor_pks"] = ancestors
```

**The counter must be a separate monotone `hops`, never `len(ancestors)`.** A set
stops growing on a cycle: for A→B→A it saturates at 2, the guard stays true forever,
and `node` never becomes `None` — an infinite loop with a DB fetch per iteration,
inside a student-facing POST. `builder.element_depth` (`builder.py:192-196`) and
`payloads.validate_nesting` (`payloads.py:897-908`) both use a separate counter for
exactly this reason; a size-bounded set is the inverted version of the same shape and
provides none of the safety.

**Falsifying this one needs care, because the mutant HANGS rather than fails.** A
pytest run against the size-bounded version loops forever with a DB fetch per
iteration — and in this repo a hung run also orphans the test DB for the next one.
So the walk is extracted as a pure helper — **`builder.ancestor_pks(element)`**,
which is where `element_depth` (the sibling walk cited above) already lives, so the
no-DB unit test imports from `courses.builder` and `check_answer` calls it — over
anything exposing `.pk` / `.parent`. The falsification is a **fast-failing bound
assertion**, not a behavioural one:
build an in-memory two-node cycle whose `parent` accessor raises after a threshold.

**Count the accesses before choosing the threshold — the obvious value has zero
margin.** With `MAX_NEST_DEPTH = 4`, correct code reads `.parent` exactly **six**
times on a cycle: once for the initializer (`node = element.parent`) plus five loop
iterations, since `hops <= MAX_NEST_DEPTH` admits `hops` = 0,1,2,3,4. So
`MAX_NEST_DEPTH + 2` is *also* 6, and a fixture written the natural way
(`if self._n >= MAX_NEST_DEPTH + 2: raise`) turns the falsification RED against the
**correct** implementation — whose likely fix is to tighten the production bound
rather than the fixture. Use `MAX_NEST_DEPTH * 3` (12), which is unambiguous, still
nowhere near a hang, and leaves the margin visible.

`render_element` reads `feedback_ancestor_pks` from context **only** — it is never
passed as a tag argument, because it is page-level by nature and no template needs
to forward it — and carries it in `page`.

`SpoilerElement.render` gains `eid`, written exactly as the three containers that
already carry one do (`models.py:1787` tabs, `:1899` two_column, `:598`
before/after — callout has none and needs none, so it is three of four, not all
four):

```python
"eid": element.pk if element is not None else 0,
```

The sentinel is not optional: §7 promises `render()` works when called directly with
no `element` (the `test_render_seam` CONCRETES shape), and a bare `element.pk` would
`AttributeError` there.

The template becomes:

```
<details class="spoiler"{% if feedback_ancestor_pks and eid in feedback_ancestor_pks %} open{% endif %}>
```

**The `feedback_ancestor_pks and` guard is required, and "the default is an empty
frozenset" is NOT the reason.** That default lives in `render_element`'s fallback.
On a direct `SpoilerElement.render(...)` **without `page`** — the shape
`test_render_seam`'s CONCRETES loop drives — the key is **absent from the template
context entirely**, not an empty set. A bare
`{% if eid in feedback_ancestor_pks %}` would then evaluate `0 in ''` and render
correctly only because Django's `smartif` swallows the `TypeError`. Relying on a
swallowed exception is not a mechanism. The `and` short-circuits on the missing or
empty value and never reaches the membership test.

Seeding `"feedback_ancestor_pks": frozenset()` in the container's own dict is the
wrong fix: container keys win over `page` (§3.2), so it would overwrite the real
value on every page render and disable the feature outright.

**Only the spoiler needs this.** Tabs server-renders every panel visible as its
documented no-JS fallback, before/after renders both slots with
`html:not(.ba-js)` revealing them, and callout and two_column are always visible.
The empty-set default means every other render path is untouched.

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

That call passes **no `action_url`**, so the fragment's `<form action=…>` reverses
the student `check_answer` URL.

**This is NOT a live bug, and the spec previously claimed it was.** `editor.js`
fetches `tryForm.getAttribute("action")` from the **live** form node (`:250`) and
the inline-choice branch does `tryForm.innerHTML = newForm.innerHTML` (`:272`) —
swapping the form's *body*, not the form, with an in-file comment saying exactly
that ("so the delegated handler and the form node survive"). The response's `action`
attribute is therefore **discarded**: the second Check reads the same attribute the
first did. No author can observe a wrong post, and there is no top-level bug here
either.

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

`element_try` has a **second** whole-element re-render — the quiz
`INLINE_QUIZ_REVEAL` branch at `views_manage.py:2393-2405`, which likewise passes no
`action_url`. It is deliberately **out of scope**: after §6 a nested question cannot
exist in a quiz at all, and `editor.js` discards the attribute either way. Recorded
so the asymmetry reads as a decision rather than a miss.

**Kept as defence-in-depth, and labelled as such**: a manage-gated fragment should
not carry a student endpoint in its markup, and the change is two lines. But it
fixes nothing observable today and must not be described as a bug fix — if the
implementation cost turns out to be more than trivial, dropping it is the correct
call, not a compromise. §9.7's assertion on it is a markup assertion with no
user-facing meaning.

### 5.2 Stated behaviour change

This fixes the live nested-`fill_blank` preview defect: an author who had learned to
expect the preview's Check button to misbehave will find it working. §5.1 changes
nothing observable — see there.

---

## 6. The widening, and the lesson-only rule

### 6.1 Allowlist

`NESTABLE_TYPE_KEYS` (`courses/builder.py:89`) gains the transfer keys `choice`,
`short_text`, `short_numeric`. `fill_blank` is already a member. The invariant
`NESTABLE_TYPE_KEYS <= set(transfer.export.SERIALIZERS)` continues to hold — all
three are registered serializers.

`_NESTABLE_FORM_KEY_ALIASES` (`:121`) gains the form→transfer mappings the add menu
posts:

| Key as `resolve_scope` receives it | Transfer key |
|---|---|
| `choicequestion` | `choice` |
| `shorttextquestion` | `short_text` |
| `shortnumericquestion` | `short_numeric` |

`fillblankquestion` → `fill_blank` already exists.

**The choice alias is `choicequestion`, NOT `choice-single`/`choice-multi`, and
getting this wrong breaks the widening's headline capability.** The add menu posts
`data-add-type="choice-single"` or `"choice-multi"`, but `element_add`
(`views_manage.py:2130-2134`) collapses both to `type_key = "choicequestion"`
**before** calling `resolve_scope` at `:2186`; `element_save` → `builder.save_element`
→ `resolve_scope` (`builder.py:1435`) likewise passes the POSTed `type`. So
`choice-single` never reaches the alias map. Aliased on the card names instead,
`child_key` stays `"choicequestion"`, which is not in `NESTABLE_TYPE_KEYS`, and
**every nested-choice add and save 400s** while the cards sit there inviting clicks.
`test_beforeafter_nesting.py:66` already documents this exact failure mode for
another type ("Without the alias the card is offered nested and every click 400s").

The single/multi split is resolved *inside* `element_add` (it becomes
`initial={"multiple": ...}`), so it is a form concern that never reaches the nesting
authority. The other three types post their form key unchanged and need no such
note.

**How much the drift test catches depends on how the mistake is made** — corrected
during implementation, where the mutant was actually run:

- An alias that **replaces** `choicequestion` with `choice-single` IS caught: the
  drift test indexes the map by the expected form key, so the missing key raises
  `KeyError`.
- An alias **added alongside** the correct one is NOT caught: `choice-single →
  choice` is perfectly well-formed and satisfies "every alias resolves into
  `NESTABLE_TYPE_KEYS`" — it is simply never consulted.

§9.5's `element_add` endpoint tests are what catch the second case, and they are the
reason those tests exist. (An earlier draft of this section claimed the drift test
caught neither; that was wrong, and the two test files must not repeat it.)

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
    # ContentType is NOT imported by builder.py today; add it at module level
    # (no cycle risk, unlike the courses.richtext hop).
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
gated `{% if nested and not unit_is_quiz %}`, holding five cards with **exactly
these `data-add-type` values**, identical to their top-level twins at
`_add_menu.html:60-64`:

| Card | `data-add-type` |
|---|---|
| Single choice | `choice-single` |
| Multiple choice | `choice-multi` |
| Short text | `shorttextquestion` |
| Short numeric | `shortnumericquestion` |
| Fill in the blanks | `fillblankquestion` |

**The two choice cards carry the card names, not `choicequestion`** — which is the
opposite of §6.1's alias table, and both are right. `element_add`
(`views_manage.py:2128-2134`) reads `data-add-type` to decide `multiple`
(`choice-single` → `False`, `choice-multi` → `True`) and *then* collapses both to
`type_key="choicequestion"` for the nesting check. So the card speaks one namespace
and `resolve_scope` speaks the other.

Emitting `data-add-type="choicequestion"` on both cards would **not** error:
`choicequestion` is in `element_add`'s allow-tuple, so both would 200 and both would
produce an identical **single**-choice element, silently. Nothing in the rest of the
plan catches it — §9.5's endpoint tests POST the form keys directly rather than
through the template, and a card *count* assertion is blind to the attribute's
value. §9.6 therefore pins the five `data-add-type` **strings**, not just the count.

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
key alone would pass with the generic fallback showing.

**The completeness assertion needs a mechanism, not just an intention.**
`paste_allowed` returns its reasons as inline string literals at eight `return
False, "…"` sites, so there is nothing to enumerate. Two tempting mechanisms both
fail:

- a **source regex** over `builder.py` would also sweep the docstring, which lists
  the reason names in prose — a trap this repo has already been bitten by;
- a **hand-maintained `PASTE_REASONS` frozenset** just moves the drift one file
  over: a future ninth `return False, "…"` added without touching the constant
  leaves the assertion green and the author back on the generic fallback, which is
  the failure this is supposed to close.

Use **`ast`**, restricted to `Return` nodes inside `paste_allowed`'s function body:
parse `builder.py`, find the `FunctionDef`, walk its `Return` nodes, collect the
second element of each returned tuple that is a string constant. That sees exactly
what the function can return, cannot see the docstring, and needs no second list to
maintain. Then assert:

```python
returned_reasons <= set(PASTE_REFUSAL_MESSAGES)
```

**Subset, never equality**: the map also holds `parent_gone`, which `paste_allowed`
never returns, so the relation is one-directional by design.

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
- sits **inside** the existing `if node.kind == ContentNode.Kind.UNIT:` block and
  **before** the `node.unit_type = unit_type` assignment at `:607`, or captures the
  old value into a local first. This ordering decides whether the authority works
  at all: read after the assignment, `node.unit_type != unit_type` is permanently
  False and the guard is dead code that no static reading reveals;
- fires only when the **new** value is `QUIZ` **and** differs from the **pre-assignment**
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

**Position: immediately after the existing `NESTABLE_TYPE_KEYS` clause**
(`payloads.py:922`), so "not nestable at all" still wins over "not nestable
*here*". `validate_nesting` runs its per-element checks in a fixed order and each
raises via `_err()`, so a document that is both too-deep and question-in-quiz
reports whichever clause comes first; §9.5 asserts that ordering rather than
leaving it to whoever writes the code.

The predicate is `el["type"] in NESTABLE_QUESTION_KEYS` and `unit_types[el["unit"]]
== "quiz"` — the **raw string**, since the archive's `unit_type` is validated at
`schema.py:281` against the literal pair `("lesson", "quiz")` and never becomes a
`ContentNode` instance.

**It is `el["unit"]`, deliberately, and not "the parent's unit".** The two are not
the same lookup: `validate_nesting` never checks that a nested element and its
parent share a unit, so a crafted archive can give the child `unit: U_lesson` and
the parent `unit: U_quiz`, and the two readings would gate opposite documents.
`el["unit"]` is the right one — it is the unit the row is actually created in, and
`schema.py:344-349` has already validated it points at a unit node. Refusing
cross-unit nesting outright is a separate concern and is **not** added here. The non-nestable question types need no mention: the
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

**5. The LAL loader (`courses/lal_loader/builders.py`) — ONE guard at the top of
`build_element`, NOT at the container branches.** This is a real,
currently-invisible authority: it builds nested `Element` rows directly, bypassing
`builder` entirely, and it built the 793-unit imported corpus §8 cites.

**It has TWO recursive nesting sites, not one**, and they are not equally guarded:

- `if etype == "spoiler":` (`:114-163`) gates children against its own allowlist
  `LAL_SPOILER_CHILD_TYPES` (`:55-72`), whose only question member is `fill_blank`;
- `if etype == "tabs":` (`:201-224`) creates the join row and recurses
  `build_element(..., parent=join, tab_id=t["id"])` for every child with **no
  allowlist and no unit-type check at all**.

The loader has `choice` (`:378`), `numeric` (`:400`), `shorttext` (`:425`) and
`fillblank` (`:237`) branches, every one reachable from that tabs recursion. So a
manifest with a quiz unit holding `tabs > choice` creates exactly the state this
authority exists to forbid — and a gate placed at the spoiler branch would never
run.

**Therefore the guard goes at the top of `build_element`, keyed on
`parent is not None`** (i.e. "this call is creating a nested row"), refusing a
question `etype` when `unit.unit_type` is `QUIZ` and raising `LoaderError`. One
site, covering both recursions and any container branch a future slice adds — which
is the point: two call-site guards would have to be remembered a third time.

It sits **after** the `flagged`-child exemption, which bypasses type handling
entirely and can only ever produce an `HtmlElement`, never a question.

**The tabs recursion's total absence of a type allowlist is a pre-existing
`NESTABLE_TYPE_KEYS` bypass and stays OUT of scope.** This spec adds a unit-type
refusal; it does not give the tabs path the allowlist the spoiler path has.
Recorded so the implementer neither widens it by accident nor reads the asymmetry
as an oversight.

**The gate is NOT `fill_blank`-only.** Via the spoiler path it is — that allowlist
admits no other question type. Via the tabs path any of the four is reachable. §9.5
therefore needs **two** loader cases, and the tabs one is the case a spoiler-only
gate leaves green.

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

### 6.5 `FORMAT_VERSION` must be bumped to 12

`courses/transfer/schema.py:14` holds `FORMAT_VERSION = 11`, and
`importer.py:193` refuses an archive whose `version > FORMAT_VERSION`.

This spec changes what an archive is *allowed to contain* — a nested `choice`,
`short_text` or `short_numeric` — without changing its shape. Left unbumped, an
archive exported from this branch imports into an older deployment, passes the
version check, and is then rejected by that deployment's `validate_nesting` with
"Element 'x' may not be nested" — a message that blames the author's content for
what is really version skew. Bumped, the old deployment refuses up front and says
so.

The repo has clear precedent for bumping on exactly this kind of
nesting-capability change: the tabs carousel took it to 8 and before/after to
10/11.

**Merge hazard.** Two branches bumping `FORMAT_VERSION` to the *same* number
produce no git conflict — the line is identical, so it merges silently and one
capability ships under a version that claims the other. Verified at spec time:
`gh pr list --state open` returns **no open PRs**, so nothing is in flight to
collide with. Re-check immediately before merge rather than trusting this line.

### 6.6 Why the lesson-only rule exists: the latent quiz-mode bug

`render_element`'s `mode` parameter defaults to `"lesson"`.
`_quiz_article.html:32` passes `mode="quiz"`, but only to **top-level** elements.
Containers drop it twice: their `render()` has no `mode` parameter, and the
template's bare `{% render_element child %}` restarts from the default.

So a question nested in a container inside a quiz renders as a **lesson** question —
and the result is not an ungraded-but-working question, it is a **dead** one.

Its Check button posts to `check_answer`, which opens with
`get_node_or_404(..., require_lesson=True)` and raises `Http404("not a lesson unit")`
(`access.py:128`) for any non-lesson unit. So the no-JS POST 404s and the
`question.js` fetch 404s: the student sees a question they cannot answer at all.
Compounding it, `render_states` (`courses/views.py`, the `build_quiz_context` loop)
is built only over top-level elements, so there is no `QuestionResponse` row, no
attempt cap, no lock, no question number and no marks even if the post did land.

Fixing that properly means giving nested questions the whole per-element quiz
plumbing (`render_states`, `action_url`, `locked`, `attempts_left`, `qnum`,
numbering across slides). That is a separate, larger piece of work. Until it is
done, the lesson-only rule is what keeps the bug unreachable — and today it is
*not* enforced: `resolve_scope` and `paste_allowed` never look at `unit.unit_type`,
so only the UI's card-hiding stands between an author and this state.

**This is why `mode` must stay out of the `page` dict** (§3.1). Adding it would
half-fix this path — correct rendering mode, still a 404 on submit, still no
`render_states`, still no marks — which is worse than leaving it visibly
unsupported.

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
  with no `page` — the shape `test_render_seam`'s CONCRETES loop drives
  (`obj.render(element=el, state={}, slug="x", node_pk=unit.pk)`: a real join row,
  **no `page`**). That missing-`page` half is what makes §4.1's
  `feedback_ancestor_pks and` guard necessary.
- **`element=None`.** A separate shape, and **not** one the CONCRETES loop covers —
  the only `element=None` call in `test_render_seam.py` uses `FillGateElement`, not
  a container. So nothing in the suite currently drives
  `SpoilerElement.render(element=None)`, and a bare `"eid": element.pk` would stay
  green everywhere. §9.4 adds that case explicitly.
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

**The second accepted cost is the try-URL / action-URL reversal, and it is NOT
preview-only.** `resolved_children()` does
`select_related("content_type").prefetch_related("content_object")` but **not**
`select_related("unit__course")`, so reading `element.unit.course.slug` costs up to
two extra queries per nested question. That happens on **both**:

- the editor preview, via §5's new `manage_element_try` branch, and
- the **student lesson page**, where `QuestionElement.render` already reverses
  `courses:check_answer` from `element.unit.course.slug` whenever `action_url is
  None` — which is exactly the nested case, and is live today for nested
  `fill_blank`.

So the student-page half is pre-existing, not introduced here; the widening
multiplies it by four types. Accepted rather than fixed, for the same reason as the
prefetch: closing it means adding `select_related("unit__course")` to five
`resolved_children()` methods on the student path, which is a broader change than
this spec's subject and should be measured before it is made. A comment at
`resolved_children()` records it so the next person to touch nesting performance
finds both halves in one place.

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
| | ↳ the **spoiler** case additionally asserts the verdict's ancestor `<details>` carries `open` (§4.1) — without it the test pins markup the student never sees. **Test 9 must carry the same assertion**: test 2 nests directly in the spoiler, so a direct-parent implementation that never walks would satisfy it and the ancestry rule would go unpinned | | |
| 6–8 | `test_nested_blank_answer_shows_feedback_by_type[choice\|short_text\|short_numeric]` | callout | type |
| 9 | `test_nested_blank_answer_shows_feedback_at_depth_2` | callout in spoiler | recursion — **also asserts the outer `<details>` carries `open`** |
| 10 | `test_only_the_checked_question_shows_a_verdict` | callout | the §2.2 invariants |

**Three** new types on the type axis, not four: `fill_blank` × callout is already
row 1, so listing it again would be a redundant cell.

Six **controls** carry over unchanged and must stay **green under every mutant** in
§9.3 — they pass on today's code and must keep passing:
`test_top_level_blank_answer_shows_feedback` (1) and
`test_nested_non_blank_answer_does_show_feedback[…]` (5, one per container).

§9.4's seven claim-tests also live in this file. File total: **23 tests** (11
existing + 5 new seam + 7 claim).

**Per-type structural guards — and there is no per-type class to use.** The
retained `el--fillblank` count-of-2 guard is fill-blank-specific and does not
transfer: `fill_blank` is the **only** one of the four with a type marker
(`fillblankquestionelement.html:13` renders `el el--question el--fillblank`).
`choicequestion.html:2`, `shorttextquestionelement.html:2` and
`shortnumericquestionelement.html:2` all render the byte-identical
`<div class="el el--question" data-question>` — short-text and short-numeric differ
only by `inputmode` on line 8. So `body.count("el--question")` can neither be
counted (the scene already carries the fill-blank pair) nor used to tell the nested
render from its top-level twin.

The guard is therefore **positional, not class-based**: slice the body to the
`callout__child` wrapper and assert **inside that slice**. Within it, per type:

| Type | Discriminator inside the `callout__child` slice |
|---|---|
| all four | the form `action` contains the **nested element's own pk** — unique on the page. This pins the **child-pk half** of §5's rule only; the `manage_element_try` half belongs to the editor-preview surface, which the seam tests never touch and §9.7 owns |
| `choice` | `name="choice"` and a known `value="{choice.pk}"` |
| `short_numeric` | `name="answer"` **plus `inputmode="text"` present** inside the slice |
| `short_text` | `name="answer"` **plus `inputmode` absent** — `shorttextquestionelement.html:8` renders no such attribute at all. This is an absence assertion, so it leans on the positive form-action discriminator in the row above rather than standing alone |

Adding a new per-type class instead would be a **production template change** and
would have to appear in §10; it is not proposed here.

**What "blank" is on the wire**, per type — this must be exact, or `answer_is_empty`
never fires and the test proves nothing:

| Type | `build_answer` | Blank POST |
|---|---|---|
| `fill_blank` | `post.getlist("blank")` | `{"blank": [""]}` — **one `""` per blank in the stem**; `answer_is_empty` recurses over the list, so a two-blank stem needs `["", ""]`. The scene fixture's stem (`"Cap is {{paris}}."`) has exactly one blank, and the retained `el--fillblank` guard does not constrain blank count |
| `choice` | `post.getlist("choice")` → set | **no `choice` key at all** |
| `short_text` | `post.get("answer", "")` | `{"answer": ""}` |
| `short_numeric` | `post.get("answer", "")` | `{"answer": ""}` |

### 9.3 Falsification — each test names its mutant

Per the house rule, tests must be shown RED, not merely run. "The ten" is §9.2's
enumerated set; "the six" are its controls.

| Mutant | Expected RED |
|---|---|
| Pass `page=` **unconditionally**, without the `CONTAINER_MODELS` gate | `courses/tests/test_render_seam.py` (13 concretes × 6 placements) — the whole-corpus break §3.1 describes |
| Delete the six context reads in `render_element` (five conditional fallbacks + `feedback_ancestor_pks`) | All ten; six controls stay green |
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
| Drop the `open` from `spoilerelement.html`'s `<details>` | The spoiler seam test's `open` assertion (§4.1) — the plain `VERDICT in body` half stays green, which is the point |
| Omit `feedback_ancestor_pks` from `check_answer`'s ctx, or from the `page` dict | The same spoiler `open` assertion — the view half of §4.1 needs its own named RED, or an implementer who plumbs only the template has nothing to expect |
| Alias `choice-single`/`choice-multi` instead of `choicequestion` | The **two choice** §9.5 endpoint tests, plus §9.6's rewritten `tests/test_twocolumn_registry.py` acceptance case. The short-text and short-numeric endpoint tests resolve through untouched aliases and stay **green** — an implementer seeing 2-of-4 must not go hunting for a bug that is not there. The drift test also stays green, which is exactly why the endpoint tests exist |
| Emit `data-add-type="choicequestion"` on both new choice cards | §9.6's `data-add-type` string assertions — both cards would otherwise 200 and silently produce single-choice elements (§6.2) |
| Replace §4.1's walk with `{element.parent_id}` (direct parent, no ancestry) | Seam test 9's `open` assertion — test 2 nests directly in the spoiler and stays green, which is why test 9 must carry the assertion too |
| Bound the ancestor walk with `len(ancestors)` instead of a monotone `hops` | The pure-helper tripwire test (§4.1) — **not** a behavioural test, which would hang rather than fail |
| Narrow `unit_has_nested_question` to `NESTABLE_QUESTION_KEYS` | The §9.5 wide-predicate case (nested `extended_response`) — the `fill_blank` case stays green, which is why the wide case must exist |

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

Seven claim-tests, covering seven claims — the quiz claim needs two assertions and
invariant A is seam test 10, already counted among the five new seam tests, so the
file arithmetic is 11 existing + 5 seam + 7 claim = 23. All live in
`courses/tests/test_nested_question_nojs_feedback.py` alongside the seam tests:

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
- **Restore and live routes agree** (§9.1) — stated as an executable comparison,
  since after the change the checked element no longer takes the restore route at
  all: **POST** a whitespace-bearing non-blank answer to the nested question (live
  route), then **GET** the lesson page, where `feedback_for_pk` is `None` so the
  same element re-renders through restore. Assert the verdict text and the refilled
  input value are byte-identical between the two responses.
- **`None` and `""` refill identically**: a blank nested `short_text` answer (which
  arrives as `None` after §3.1's coercion) and a blank top-level one (which arrives
  as `""`) produce the same empty input value — pinning the `default_if_none:''`
  the coercion's safety rests on.
- **Shadowing is impossible**, **parametrized over all five container models**: a
  `render()` called with a `page` dict carrying an `el` key still renders its own
  element. One container is not enough — the splat-order invariant would then be
  unpinned for four sites, including `TabsElement`, the very one §3.2 flags as the
  place an implementer copying the single-splat snippet goes wrong.
- **The spoiler `eid` sentinel holds**: `SpoilerElement.render(element=None)`
  returns without raising. Nothing in `test_render_seam.py` covers this today (its
  CONCRETES loop passes a real join row, and its only `element=None` case uses
  `FillGateElement`), so a bare `"eid": element.pk` would otherwise ship green.
- **`mode` is not forwarded** — and the mechanism matters, because `page` is a
  function-local that no public API returns. A source regex would sweep the
  comments that discuss `mode`, and a rendered-output assertion cannot tell "`mode`
  absent" from "`mode` present and equal to the default `"lesson"`" — which is
  exactly the mutant. So capture the kwarg:

  ```python
  captured = {}
  def capture(self, *, element=None, state=None, slug=None, node_pk=None, page=None):
      captured.update(page or {})
      return ""          # render_element mark_safe()s the result
  monkeypatch.setattr(CalloutElement, "render", capture)
  ```

  Both details are easy to get wrong first try: patched on the **class**, `capture`
  is an unbound descriptor and receives the instance as `self`; and it must return a
  string or the surrounding lesson render blows up. Then assert **the full key set**,
  not just the absence — `captured.keys() == {"feedback_for_pk", "selected_ids",
  "submitted_values", "mark_result", "editor_preview", "feedback_ancestor_pks"}` —
  because `"mode" not in captured` alone is green also when `page` never arrived at
  all. Pinning the key list makes the absence non-vacuous in one line. The mutant it must catch is adding `"mode": mode` to the
  dict.

### 9.5 Gate tests

One per authority: `resolve_scope` raises for a question into a quiz container;
`paste_allowed` returns `question_in_quiz`, returns it at the right point in the
precedence (a case that would also trip `too_deep` reports `question_in_quiz`),
still permits a **top-level** paste into a quiz, and — asserted on the endpoint, not
the function — surfaces its **own** `PASTE_REFUSAL_MESSAGES` string rather than the
generic fallback, plus a completeness assertion that every reason `paste_allowed`
can return has a map entry; `rename_node` refuses the lesson→quiz flip, leaves
`unit_type` unchanged, accepts the quiz→quiz no-op, and allows quiz→lesson;
`validate_nesting` rejects the archive, reports **the existing `NESTABLE_TYPE_KEYS`
clause's message** ("Element '%(el)s' may not be nested.", `payloads.py:921-922`)
ahead of the new clause for a document that trips both — `validate_nesting` raises
through `_err()` with translated messages and has no reason keys, so the assertion
matches on that msgid, not on a `paste_allowed` key — **and**
still accepts its 19 existing positional call sites; the LAL loader refuses a
a nested question child in a quiz unit — **two cases, one per recursion site**: a
`fill_blank` under a **spoiler** (the only question type that allowlist admits) and
a `choice` under a **tabs** element (the ungated path a spoiler-only gate leaves
green — see §6.3 authority 5) — **and** allows a manifest that flips a unit to quiz
while dropping its nested question in the same revision (the case that authority
exists to keep working).

**The `rename_node` case must use a type OUTSIDE the four keys.** If it nests a
`fill_blank` — the natural choice, matching every other fixture — then narrowing
`unit_has_nested_question` to `NESTABLE_QUESTION_KEYS`, the exact mutation its
docstring warns against, leaves the test green. So the gate adds a case that creates
a nested `extended_response` (or `drag_fill_blank`) via a direct
`Element.objects.create` — the crafted-POST shape the docstring describes — and
asserts the flip is still refused. The predicate's width is the whole justification
for a second source of truth; without this case it is the only claim in §6 with no
falsifying test.

**Four endpoint tests for the new form keys.** The drift test below is a pure set
assertion, and §9.6's rewritten `test_a_graded_question_is_still_refused_as_a_child`
calls `resolve_scope` directly — neither proves that POSTing
`data-add-type="choice-single"` with `parent` + `tab` to `element_add` actually
creates the right row. `choice-single` / `choice-multi` collapsing to one transfer
key is exactly where the form/transfer namespace split bites. One test per new form
key drives `element_add` on a **lesson** unit and asserts the created `Element`'s
concrete model, `parent`, `tab_id`, and — for the two choice keys — `multiple`
(`False` / `True`). A fifth asserts the same POST 400s on a **quiz** unit.

**One transfer round-trip.** Every other transfer assertion here is about rejection
or signature compatibility. Nothing yet proves a lesson containing a nested `choice`
survives `build_export` → `validate_document` → import with `parent`, `tab_id`,
concrete type and its `Choice` rows (`is_correct`, `feedback`) intact. That path is
not hypothetical: `duplicate_element` and the paste flow both go through the
transfer serializers, so duplicating the callout is the first thing an author does
after nesting a question. `choice` is the one that matters — it is the only newly
nestable type with child rows.

Plus the preview tests (§9.7) and a drift test extending
`courses/tests/test_nesting_rule.py`: `NESTABLE_QUESTION_KEYS <= NESTABLE_TYPE_KEYS`,
every member is in `transfer.export.SERIALIZERS`, and every new form-key alias
resolves into `NESTABLE_TYPE_KEYS`.

`CONTAINER_MODELS` needs **no** new agreement assertion:
`test_container_keys_agree_by_key_not_by_count` (`test_nesting_rule.py:322-330`)
already asserts `{model_to_key(m) for m in _CONTAINER_REGISTRY} ==
set(CONTAINER_TRANSFER_KEYS)`, and `CONTAINER_MODELS` is *defined* as
`frozenset(_CONTAINER_REGISTRY)`. The only incremental fact worth pinning is that
definition — that it is derived, not a hand-written second list — which one
assertion covers.

### 9.6 Existing tests that MUST go red, and their rewrites

Existing assertions in **eleven** files go RED. Their RED is expected, not a
regression, and an implementer must be told so up front — one of them names our
change as its mutant in its own docstring.

**On the sweep methodology, because the first two attempts were both incomplete.**
Grepping `resolve_scope(` for a literal question key misses
`test_spoiler_nesting.py:157`, where the key is a **loop variable**
(`for bad in ("choicequestion",)`). Grepping one namespace misses the other —
`test_beforeafter_nesting.py` passes the *transfer* key `"choice"`,
`test_twocolumn_registry.py` and `test_spoiler_nesting.py` pass the *form* key
`"choicequestion"`. And neither grep sees the endpoint-level or `FORMAT_VERSION`
assertions at all. The list below came from three orthogonal sweeps —
`grep -rn "choicequestion"`, `grep -rn "NESTABLE_TYPE_KEYS"`, and
`grep -rn "FORMAT_VERSION == 11"` across `courses/tests/` and `tests/` — and the
plan should re-run all three rather than trust this enumeration.

**Group A — nesting refusals that become acceptances (4 files).**

| File | Assertion | Rewrite |
|---|---|---|
| `courses/tests/test_beforeafter_nesting.py:52-62` | `resolve_scope(..., "choice")` raises; docstring says *"Mutant: add `choice` to NESTABLE_TYPE_KEYS -> accepted."* | Refusal in a **quiz** unit, acceptance in a lesson |
| `tests/test_twocolumn_registry.py:53` | `resolve_scope(..., "choicequestion")` raises — `# questions can't nest` | Same shape |
| `courses/tests/test_spoiler_nesting.py:157` | `for bad in ("choicequestion",)` … raises | Same shape |
| `tests/test_tabs_registry.py:74` | `element_add` with `{"type": "choicequestion"}` into a tab asserts **400** | Now 200 on a lesson; assert 400 on a **quiz** unit instead |

**Group B — add-menu absence assertions (1 file, 3 sites).**
`courses/tests/test_spoiler_nesting.py` asserts the new cards are absent from nested
menus at `:351-363` (`banned_question` loop), `:389`
(`isdisjoint({"choice-single", "shorttextquestion", "dragfillblankquestion"})`) and
`:444-448` (a second `banned_question` loop). The drag/grid/extended keys stay
banned; the four widened keys become expected-**present** in a lesson and
expected-**absent** in a quiz.

**Group C — the `FORMAT_VERSION` bump (7 files).** Every one of these hard-asserts
the literal and goes RED the moment §6.5's bump lands. The rewrite is mechanical —
`11` → `12` — but the list must be explicit, because §10 otherwise tells the
implementer that one of these files needs no edit:

`courses/tests/test_beforeafter_transfer.py:169`,
`courses/tests/test_image_size_transfer.py:44`,
`tests/test_link_transfer.py:54`, `tests/test_table_transfer.py:299`,
`tests/test_tabs_transfer.py:62`, `tests/test_transfer_schema.py:57`
(all `assert FORMAT_VERSION == 11`), and `tests/test_transfer_export.py:222`
(`assert manifest["format_version"] == 11`).

**Group D — the archive nesting rejection (1 file, already counted in C).**
`tests/test_tabs_transfer.py::test_nesting_validation_rejects` carries the
parametrized case `_els(_tabs_el(), _child(type_="choice"))  # non-nestable child`
(`:142`) inside `pytest.raises(TransferError)`. Once `choice` joins
`NESTABLE_TYPE_KEYS` that document validates cleanly — the fixture passes no
`unit_types`, so the new quiz clause is skipped by design — and the case fails. The
keyword-with-default protects the *signature*, not this *assertion*. Rewrite: swap
the subject for a still-non-nestable type (`extended_response` or
`drag_fill_blank`), and add a positive case asserting `choice` is now accepted
nested.

**Stays green but becomes a lie.** `courses/tests/test_spoiler_nesting.py:179-180`
asserts `"choicequestion" not in NESTABLE_TYPE_KEYS` under the comment
`# genuinely non-nestable`. It still passes — `choicequestion` is a *form* key and
only `choice` enters the set — but the comment becomes false, and a future reader
would take the green assertion as evidence that choice questions cannot nest, which
is exactly the namespace confusion §6.1 warns about. Drop `choicequestion` from that
tuple or reword the comment to "form keys never appear in the transfer-key set".

**The add-menu placement tests** §6.2 requires also live in
`test_spoiler_nesting.py`, since the silent-unreachable-group failure is invisible
to every other test: nested + lesson shows the five cards; nested + quiz shows none of
them; the top-level menu is unchanged. The nested-lesson assertion pins the five
`data-add-type` **strings**, not the card count — a count is blind to the
`choice-single` / `choice-multi` / `choicequestion` mix-up §6.2 describes.

**On the top-level card count, mind which fixture.**
`tests/test_manage_editor_menu.py` pins `body.count('data-add-type="') == 24`, and
24 is the count for a **quiz** unit — both its tests use `unit_type="quiz"`, where
the whole `Interactive` group is suppressed by `{% if not unit_is_quiz %}`. A
top-level **lesson** menu carries **33** cards and is not pinned anywhere — 33, not
the file's 34 `data-add-type=` occurrences, because line 54's fill-blank card is
`{% if nested %}`-gated and does not render at depth 0 (12 content + 9 interactive +
11 questions + 1 structure). Neither number moves, since the new group is gated
`nested and not unit_is_quiz`; both are recorded here so a lesson-menu assertion is
not misread as a regression.

### 9.7 Preview tests

A nested question's rendered form `action` is `manage_element_try` for **its own**
pk — asserted as three distinct facts, since two of them are the actual bug: not
`check_answer`, not the parent's pk, and equal to the child's own try URL.

Separately for §5.1: `element_try`'s choice re-render returns a fragment whose form
action is `manage_element_try`, not `check_answer`. This is a **markup** assertion —
`editor.js` discards that attribute, so nothing user-facing depends on it, and it
goes away if §5.1 is dropped.

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
| `courses/templatetags/courses_extras.py` | `render_element`: six context reads (five conditional fallbacks + the context-only `feedback_ancestor_pks`), `editor_preview=None` parameter, `page` dict **gated on `CONTAINER_MODELS`** with `or None` coercion, nested-preview try-URL branch |
| `courses/models.py` | `page=None` + splat-first on the five container `render()`s (`:454`, `:522`, `:591`, `:1780`, `:1892`); tabs keeps `display_settings()` last; `SpoilerElement.render` also gains `eid` (§4.1); comment at `resolved_children()` recording the action-URL query cost (§8) |
| `courses/builder.py` | `NESTABLE_TYPE_KEYS` += 3 keys; alias-comment update; `_NESTABLE_FORM_KEY_ALIASES` += **3** aliases (four *form keys* route through them — `choice-single`/`choice-multi` both collapse to `choicequestion` in `element_add` before the map is consulted); new `NESTABLE_QUESTION_KEYS`, `CONTAINER_MODELS` and `unit_has_nested_question`; `resolve_scope` clause; `paste_allowed` clause + reason; `rename_node` flip guard; new `ancestor_pks()` helper (§4.1), beside the existing `element_depth` |
| `courses/views_manage.py` | `element_try`'s choice branch passes `action_url` (§5.1); `PASTE_REFUSAL_MESSAGES["question_in_quiz"]`; **comment rewrite** at `:2179-2181`, which states `"choicequestion"` "is not in `NESTABLE_TYPE_KEYS`, so clause 1 rejects it" — false after §6.1, and it sits directly above the call site being edited |
| `courses/views.py` | `check_answer` calls `builder.ancestor_pks(element)` into `ctx["feedback_ancestor_pks"]` (§4.1). Also **comment only** — the `has_questions` comment ("Only fill_blank is nestable today") becomes false |
| `templates/courses/elements/spoilerelement.html` | `<details>` renders `open` when the checked element is in its subtree (§4.1) |
| `courses/transfer/payloads.py` | `validate_nesting` gains `unit_types=None`, rejects question-in-quiz nesting |
| `courses/transfer/schema.py` | `FORMAT_VERSION` 11 → 12 (§6.5); builds and passes the unit-type map (`:358`) — the one production `validate_nesting` call site that changes |
| `courses/lal_loader/builders.py` | Question child refused in a quiz unit — **one guard at the top of `build_element`** keyed on `parent is not None`, covering both the spoiler *and* the ungated tabs recursion (§6.3 authority 5) |
| `templates/courses/manage/editor/_add_menu.html` | Nested `Questions` group (sibling of the `{% if not nested %}` block); the `{% if nested %}` fill-blank card moved out of `Interactive`; top-level card untouched |
| `templates/courses/manage/editor/_preview.html` | `editor_preview=True` on the `render_element` call |
| `courses/tests/test_nested_question_nojs_feedback.py` | Cherry-picked from `06776cf4`, the parametrized assertion inverted + function renamed, twelve cases added (5 seam + 7 claim). **§9.4's bullet list is the checklist, not this count** — the shadowing claim-test is parametrized ×5, so the collected total is higher than the function count |
| `courses/tests/test_render_seam.py` | **The gate on §3.1's container check** — 13 concretes × 6 placements; no edit expected, but it is the test that catches an unconditional `page=` |
| `courses/tests/test_beforeafter_nesting.py` | **Expected RED** — rewrite the graded-question refusal as quiz-conditional (§9.6); it passes the *transfer* key `"choice"` |
| `tests/test_twocolumn_registry.py` | **Expected RED** — same rewrite; it passes the *form* key `"choicequestion"` (§9.6) |
| `courses/tests/test_spoiler_nesting.py` | **Expected RED** — three assertions rewritten; new home for the add-menu placement tests (§9.6) |
| `courses/tests/test_nesting_rule.py` | Drift assertions for `NESTABLE_QUESTION_KEYS`, the **three** new aliases (four nestable question form keys route through them), and `CONTAINER_MODELS` vs `CONTAINER_TRANSFER_KEYS` |
| `tests/test_manage_editor_menu.py` | Verify the top-level card count stays 24 (its fixture is a **quiz**; a lesson is 33 — §9.6) |
| Element-add endpoint tests (file per §9.5) | Four new form keys driven through `element_add` with `parent`+`tab`, plus the quiz-unit 400 |
| A transfer test file (per §9.5) | `choice` export→import round-trip preserving `parent`, `tab_id`, concrete type and `Choice` rows |
| Gate tests — `resolve_scope` + `paste_allowed` | The two builder clauses, the reason's **position** in the precedence, the top-level-paste-into-quiz allowance, the endpoint's `PASTE_REFUSAL_MESSAGES` string, and the `ast`-based completeness assertion (§6.3 authority 2) |
| Gate tests — `rename_node` | Flip refused, `unit_type` unchanged, quiz→quiz no-op accepted, quiz→lesson allowed, **plus the wide-predicate case** using a nested `extended_response` created directly (§9.5) |
| Gate tests — `validate_nesting` | The quiz clause, its position after `type_not_nestable`, and the 19 positional call sites still accepted |
| Gate tests — LAL loader | `fill_blank` child refused in a quiz unit; a manifest flipping to quiz while dropping its nested question still accepted |
| Ancestor-walk helper unit test | The fast-failing cycle tripwire (§4.1) — no database |
| `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ `.mo`) | New msgids; fuzzy pre-fills cleared |
| `tests/test_tabs_registry.py` | **Expected RED** — the `element_add` 400 case for `choicequestion` in a tab is now 200 on a lesson (§9.6 group A) |
| `tests/test_tabs_transfer.py` | **Expected RED, twice** — the `choice`-child rejection at `:142` (§9.6 group D) **and** `assert FORMAT_VERSION == 11` at `:62` |
| `courses/tests/test_beforeafter_transfer.py`, `courses/tests/test_image_size_transfer.py`, `tests/test_link_transfer.py`, `tests/test_table_transfer.py`, `tests/test_transfer_schema.py`, `tests/test_transfer_export.py` | **Expected RED** — each hard-asserts `FORMAT_VERSION == 11` (or the manifest value); bump each literal to 12 (§9.6 group C) |
| `courses/tests/test_callout_transfer.py`, `test_spoiler_transfer.py`, `tests/test_transfer_nesting_depth.py`, `tests/test_twocolumn_transfer.py` | No edit — they hold `validate_nesting` positional call sites but no `FORMAT_VERSION` or nestability assertion (§6.3 authority 4) |

No migration. No new model field. No JS change expected. **One archive-format
change** — `FORMAT_VERSION` 11 → 12 (§6.5).

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
  described in §6.6, which is worse than leaving it visibly unsupported.
- **`editor_preview`, defaulting to `None`** — `False` makes its own fallback dead
  code, and the bare name `preview` collides in meaning with the existing
  `previewing` student flag.
- **`selected_ids` resolves by truthiness** while the other four use `is None`,
  because its parameter default is `frozenset()` (§3.1), with the standing
  requirement in §4 that follows from it.
- **`unit_has_nested_question` is deliberately wider** than
  `NESTABLE_QUESTION_KEYS`.
- **The LAL loader's own allowlist is not merged** into `NESTABLE_TYPE_KEYS`; it is
  deliberately narrower. Its guard sits at the top of `build_element`, not at the
  container branches — the loader has **two** recursion sites and the tabs one is
  entirely ungated, so a per-branch guard would close only half of it.
- **The tabs recursion's missing type allowlist stays out of scope** — a
  pre-existing bypass this spec does not widen and does not close.
- **The non-blank nested path is rerouted** (restore → live), not untouched, and
  §9.4 pins that the two routes agree.
- **The spoiler re-opens on the no-JS re-render** (§4.1) — without it the fix is
  invisible in the one container the capability was built for, and the seam test
  would pass vacuously. The ancestor walk uses a **monotone hop counter**, not the
  size of the set it is filling.
- **The choice alias is `choicequestion`** (§6.1), the key `element_add` actually
  forwards — aliasing the card names `choice-single`/`choice-multi` would 400 every
  nested-choice add while the drift test stayed green.
- **The paste-reason completeness check uses `ast`**, not a hand-maintained
  constant and not a regex — the constant would move the drift rather than close
  it, and the regex would sweep the docstring.
- **`FORMAT_VERSION` bumps to 12** (§6.5), because the set of legal archive
  contents changed even though the shape did not.
- **Two accepted costs**, both in §8: the nested-choice prefetch N+1, and the
  action-URL reversal — which is **not** preview-only, and is pre-existing on the
  student page.
