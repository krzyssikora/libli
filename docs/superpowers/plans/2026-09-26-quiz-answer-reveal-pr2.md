# Quiz answer reveal — PR 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert drag the words, match pairs, drag onto image, choice grid ("matrix") and multi grid to the quiz answer reveal built in PR 1 — parts painted from the first Check, Show answer, key copy + Your/Correct switch, results page — and, in the same PR, to in-place lesson feedback (D13).

**Architecture:** PR 1 (#348, master `0b7ca465`) built every shared piece and made the views flag-driven: `SUPPORTS_REVEAL` routes a type through the whole-element responses, `can_reveal`, `key_view`, the results renderer; `INLINE_LESSON_FEEDBACK` routes lessons through the whole-element response and `render()`'s own verdict computation; `CONTROLS_TEMPLATE` + `render_key_copy` + `courses.keycopy.neutralise_key_copy` draw the key copy (the `data-slot` rename for dnd selects is already there). So PR 2 is per-type work only: two hooks (`part_verdicts`, `key_answer`) per type, verdict painting in the Python builders (`courses/dnd.py`, the grid tags), one controls include + a restructured template per type (the dnd root `data-dnd` moves INTO the include, one per copy), three flags per type, and the client side: dnd.js builds an inert UI for disabled / key-copy blocks and carries the verdict class onto its slots, and the three swap sites re-run `libliEnhanceDnd`. **No view, `courses/quiz.py`, `courses/keycopy.py` or migration change is expected** — if a task seems to need one, stop and report.

**Tech Stack:** Django 5 templates, Python 3.13, PostgreSQL, vanilla JS (dnd.js, quiz.js, question.js, editor.js), BeautifulSoup4, pytest + pytest-django + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-quiz-answer-reveal-design.md` (owner decisions D1–D13 are VERBATIM intent — never reverse one). This plan is **PR 2 of 3** (spec §8). PR 1's plan (`docs/superpowers/plans/2026-09-25-quiz-answer-reveal-pr1.md`) is history — where it and the code disagree, the code on master is what PR 2 builds on.

## Global Constraints

- Owner decisions D1–D13 in the spec are verbatim; a task that seems to need reversing one STOPS and asks.
- **Scope = spec §8 PR 2, exactly five types:** `DragFillBlankQuestionElement` (drag the words), `MatchPairQuestionElement`, `DragToImageQuestionElement`, `ChoiceGridQuestionElement` (the "matrix question"; there is no `MatrixElement`), `MultiGridQuestionElement` (the "multi-select grid"; its help heading shares the `{el:switchgrid}` icon with the matrix question). **`SwitchGridElement` is NOT a question** (a lesson-only widget) and is out of scope. `ChoiceQuestionElement` and `ExtendedResponseQuestionElement` stay unconverted (PR 3): no flag, no hook, no template change on them.
- After PR 2, `SUPPORTS_REVEAL` and `INLINE_LESSON_FEEDBACK` are `True` on exactly: fill in the blanks, short text, number (PR 1) + the five above. `INLINE_LESSON_FEEDBACK` is also `True` on choice (pre-existing). Nothing else.
- Lessons never render the key copy, the switch, or the Show answer button (D11). A correct lesson answer keeps today's behaviour for the five types: Check hidden by question.js, controls **stay editable** — no `data-lock-on-correct` (spec §5a).
- Before the lock only per-part **booleans** reach the page (spec §2.1): no `data-answer-key`, no `_reveal_*` list, and no control shows a key value the student did not pick.
- **Unpainted output is byte-identical to today's.** Every builder change adds markup only when a verdict is True/False (or `copy="key"`); with `verdicts=None` the HTML must equal master's, so the existing render suites (`tests/test_dnd_render.py`, `tests/test_render_choicegrid.py`, `tests/test_render_multigrid.py`) stay green unedited.
- Colour is never the only cue (spec §2.1): every painted part carries a `.sr-only` "correct"/"incorrect" (`pgettext("answer part verdict", …)`, msgids that already exist) and a wrong part carries `aria-invalid="true"` — on the `<select>` for drag types, on every `<input>` of the row for grids (a `<tr>` has no role that supports `aria-invalid`). Use the global `.sr-only`, NOT `.visually-hidden`.
- The key copy: rendered only through `render_key_copy` (PR 1), so every control is `disabled`, nameless, and a dnd `<select>` carries `data-slot`. Every part of the key copy is painted correct (`copy == "key"`).
- `data-dnd`, `[data-dnd-pool]` and `[data-dragimage-stage]` live ONLY inside the per-type controls include — once per copy — and never on the outer `<div … data-question>` (spec §2.4).
- Check is the **first** submit button in every question form (spec §3.1); the Show answer button comes from the shared `_reveal_button.html`, placed after Check.
- Tests: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait` first, then `uv run pytest …`. e2e needs `-m e2e`. **Never pass `-q`** (`addopts` has it). Never run two pytest processes at once. Scope runs to the files each task names; the whole-repo sweep is Task 7 only.
- Template comments: `{# #}` is single-line only; multi-line comments use `{% comment %}…{% endcomment %}`.
- CSS: no line-number citations in comments (a lint forbids them); never write a comment containing `*/` mid-text (it ends the comment and eats the next rule).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Lint before EVERY commit**, scoped to the files the task touched: `uv run ruff check --no-cache --fix <py files> && uv run ruff format --no-cache <py files> && uv run ruff check --no-cache <py files>`. isort is `force-single-line = true` (combined in-function imports get split by `--fix`); an assertion line still over 88 characters after `ruff format` gets `# noqa: E501`.
- Existing tests that the D13 / reveal change legitimately breaks are **rewritten, never loosened or deleted**: each rewrite keeps the old assertion's substance and carries a comment `# PR 2 (spec 2026-09-25 §…): replaces <old assertion>`. Reverting a mutant or a rewrite is done BY HAND — never `git checkout`/`git restore` on a file with uncommitted work.

## Review Focus

1. **A stored drag answer whose token the author has since deleted** (a distractor removed after the student picked it) — resume and results must render without error, the select falls back to its placeholder (`_render_select`'s non-member branch) and the part is painted wrong. Test in Task 3 (`test_deleted_distractor_after_answer_renders_wrong`).
2. **A grid row added after the student answered** — the stored list is one short; resume and results render, the new row is painted wrong (`mark()` pads with `""` / `[]`). Test in Task 4 (`test_grid_row_added_after_answer`).
3. **Drag tokens with HTML / LaTeX specials** (`a<b`, `\(x^2\)`) — the key copy shows them escaped in `value=` and option text, never as markup, and keeps the backslashes. Test in Task 3 (`test_key_copy_escapes_and_keeps_latex_tokens`).
4. **Two correct tokens that normalise alike** (`paris` for gap 1, `Paris` for gap 2 — the pool keeps one) — the key copy's second select must still preselect the surviving option. Test in Task 3 (`test_key_copy_preselects_normalised_duplicate`).
5. **A Polish-locale drag-onto-image key copy** — the second stage's badges keep `.`-decimal `data-x/y/w/h` (a `,` collapses the overlay targets to 0 size); and **two drag questions on one quiz page**: a Check on one must not rebuild the other's chips. Tests in Task 3 (`test_dragimage_key_copy_geometry_unlocalized_in_pl`) and Task 5 (`test_check_on_one_drag_question_leaves_the_other_alone`).

---

## Plan-time decisions (the spec leaves these open; flag them in the PR description)

| # | Decision | Why |
|---|---|---|
| P1 | A grid "part" is a **row**: the `<tr>` gets `is-correct` / `is-incorrect`, its statement cell is tinted (success/danger-subtle + a 3px inset bar on the left) and holds the `.sr-only` verdict; every input of a wrong row gets `aria-invalid="true"`. | D6 says "grid row"; the statement cell is the one cell every row has whatever was picked (a wrong row with nothing picked must still read red). |
| P2 | A drag part is painted on its `<select>` (the no-JS control) and dnd.js copies `is-correct` / `is-incorrect` onto the slot / overlay target it builds for that select; for drag onto image (whose rows dnd.js hides) it also places a copy of the `.sr-only` verdict right after the target. The numbered image badges are not painted. | One server-side source of truth; the JS never decides a verdict. |
| P3 | `key_answer()` returns `None` when the whole key is empty: no gaps / pairs / zones / rows, or (drag types) every expected token empty, or (multi grid) no row has any correct column. A multi-grid row whose correct set is empty inside a non-empty key is a real "tick nothing" answer and stays `[]`. | Spec §2.2 "empty keys", mirroring fill in the blanks' `any(...)` rule. |
| P4 | The drag key copy keeps its chip pool, built display-only (chips `disabled`, not draggable). | Spec §2.2 literally ("chips `disabled`"); both copies look alike. |
| P5 | The key-copy wrapper for the drag types is `<div class="answer-key" data-answer-key>` (drag the words: `class="question__stem answer-key"` with `style="margin:0;"`), matching the "yours" fieldset's zero margin so the switch does not move on toggle. | PR 1's V1b rule (the switch must not jump). |

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/models.py` | the five types: `part_verdicts`, `key_answer` (Task 1); `SUPPORTS_REVEAL`, `INLINE_LESSON_FEEDBACK`, `CONTROLS_TEMPLATE` (Tasks 3, 4) |
| `courses/verdicts.py` (new) | `state_class(verdict)`, `invalid_attr(verdict)`, `sr_verdict(verdict)`, `part_verdict(verdicts, i, key)` — verdict → markup for the PR 2 builders (drag selects, grid rows). `courses/fillblank.py::render_inputs` keeps its own inline copy of the same logic: it is not touched in PR 2 (its byte-identity is pinned by PR 1's suites); folding it in is a PR 3 clean-up candidate |
| `courses/dnd.py` | `_render_select(…, verdict=)`; `render_selects` / `render_match_rows` / `render_zone_selects` gain `verdicts=`, `key=` |
| `courses/templatetags/courses_extras.py` | `render_drag_selects` / `render_match_pairs` / `render_image_selects` / `render_choice_grid` / `render_multigrid` gain `verdicts=`, `copy=`; grid row / cell builders paint |
| `templates/courses/elements/_dragfillblankquestionelement_controls.html` (new) | dnd root + selects in the stem + pool |
| `templates/courses/elements/_matchpairquestionelement_controls.html` (new) | dnd root + rows + pool |
| `templates/courses/elements/_dragtoimagequestionelement_controls.html` (new) | dnd root + stage + zone rows + pool |
| `templates/courses/elements/_choicegridquestionelement_controls.html` (new) | scroll wrappers + table |
| `templates/courses/elements/_multigridquestionelement_controls.html` (new) | scroll wrappers + table |
| `templates/courses/elements/{dragfillblank,matchpair,dragtoimage,choicegrid,multigrid}questionelement.html` | results branch, `data-answer-scope`, `data-answer-yours`, key copy + switch, Show answer button, `data-question-inline`; `data-dnd` off the outer div |
| `courses/static/courses/js/dnd.js` | `select[data-slot]`, inert UI, verdict class onto slots / targets |
| `courses/static/courses/js/quiz.js`, `question.js`, `editor.js` | `libliEnhanceDnd(form)` + `libliInitScrollAffordance(form)` (grid `.scroll-x` wrappers) after each form-body swap |
| `templates/courses/quiz_results.html` | loads dnd.js |
| `courses/static/courses/css/courses.css` | drag + grid verdict colours |
| `tests/reveal_pr2_kit.py` (new) | builders + HTML part parsers shared by every PR 2 test |
| `tests/test_quiz_reveal_pr2_hooks.py`, `test_quiz_reveal_pr2_paint.py`, `test_quiz_reveal_pr2_flow.py`, `test_quiz_reveal_pr2_grids.py`, `test_e2e_quiz_reveal_pr2.py` (new) | tests |
| `docs/help/course-admin/quiz-editors.md` + `.pl.md` | lesson behaviour of the five types |

---

### Task 1: Test kit + per-type hooks

**Files:**
- Create: `tests/reveal_pr2_kit.py`
- Modify: `courses/models.py` (`DragFillBlankQuestionElement`, `MatchPairQuestionElement`, `DragToImageQuestionElement`, `ChoiceGridQuestionElement`, `MultiGridQuestionElement`)
- Test: `tests/test_quiz_reveal_pr2_hooks.py` (new)

**Interfaces:**
- Consumes (PR 1, on master): `QuestionElement.part_verdicts(mark_result, answer)` / `key_answer()` base hooks returning `None`; `views._stored_result(question, response) -> MarkResult` (fresh `reveal`); `courses.quiz.answer_to_json` / `rehydrate`.
- Produces: on each of the five types `part_verdicts(mark_result, answer) -> list[bool]` (one per part, draw order) and `key_answer() -> list | None` in exactly `build_answer()`'s shape. The kit: `KINDS`, `DND_KINDS`, `GRID_KINDS`, `build(kind, **question_kwargs) -> Kit`, `post(dict) -> QueryDict`, `parts(kind, html) -> list[str]`, `paint(kind, html) -> list["correct"|"incorrect"|None]`, `yours(html) -> str`, `key(html) -> str`. `Kit` fields: `question`, `half` (POST: part 1 right, part 2 wrong), `right` (POST: all right), `empty` (POST: nothing chosen), `key` (expected `key_answer()`), `leak` (a substring present only where part 2 shows the KEY's value as chosen), `key_text` (part 2's correct label as plain text).

- [ ] **Step 1: Write the kit**

```python
# tests/reveal_pr2_kit.py
"""The five PR 2 reveal types (spec 2026-09-25 §8 PR 2): one builder per type and
the parsers that read each part's paint out of rendered HTML.

Every builder returns a Kit whose `half` POST gets the FIRST part right and the
SECOND part wrong, so a painted render reads ["correct", "incorrect"]."""

import re
from dataclasses import dataclass

from django.http import QueryDict

from courses.fillblank import parse
from courses.models import ChoiceGridQuestionElement
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from tests.factories import MediaAssetFactory

DND_KINDS = ("dragfill", "matchpair", "dragimage")
GRID_KINDS = ("choicegrid", "multigrid")
KINDS = DND_KINDS + GRID_KINDS


@dataclass
class Kit:
    question: object
    half: dict
    right: dict
    empty: dict
    key: list
    leak: str
    key_text: str


def build(kind, **kw):
    kw.setdefault("max_attempts", 3)
    return _BUILDERS[kind](**kw)


def post(data):
    """A QueryDict for build_answer(); a list value becomes a repeated key."""
    qd = QueryDict(mutable=True)
    for k, v in data.items():
        qd.setlist(k, [str(x) for x in (v if isinstance(v, list) else [v])])
    return qd


def _dnd_kit(q):
    # Part 2's key token is "betakey"; the student's wrong pick is "gammadis".
    return Kit(
        question=q,
        half={"slot": ["alphakey", "gammadis"]},
        right={"slot": ["alphakey", "betakey"]},
        empty={"slot": ["", ""]},
        key=["alphakey", "betakey"],
        leak='value="betakey" selected',
        key_text="betakey",
    )


def _dragfill(**kw):
    q = DragFillBlankQuestionElement.objects.create(
        stem=parse("One {{alphakey}} two {{betakey}}.")[0],
        distractors="gammadis",
        **kw,
    )
    DragBlank.objects.create(question=q, order=0, correct_token="alphakey")
    DragBlank.objects.create(question=q, order=1, correct_token="betakey")
    return _dnd_kit(q)


def _matchpair(**kw):
    q = MatchPairQuestionElement.objects.create(
        stem="Match them.", distractors="gammadis", **kw
    )
    MatchPair.objects.create(question=q, order=0, left="Leftone", right="alphakey")
    MatchPair.objects.create(question=q, order=1, left="Lefttwo", right="betakey")
    return _dnd_kit(q)


def _dragimage(**kw):
    q = DragToImageQuestionElement.objects.create(
        stem="Label it.", media=MediaAssetFactory(), distractors="gammadis", **kw
    )
    DragZone.objects.create(
        question=q, order=0, correct_label="alphakey", x=0.1, y=0.1, w=0.2, h=0.2
    )
    DragZone.objects.create(
        question=q, order=1, correct_label="betakey", x=0.5, y=0.5, w=0.25, h=0.2
    )
    return _dnd_kit(q)


def _choicegrid(**kw):
    q = ChoiceGridQuestionElement.objects.create(stem="Grid?", **kw)
    yes = GridColumn.objects.create(question=q, order=0, label="Yescol")
    no = GridColumn.objects.create(question=q, order=1, label="Nocol")
    r1 = GridRow.objects.create(question=q, order=0, statement="Sone", correct_column=yes)
    r2 = GridRow.objects.create(question=q, order=1, statement="Stwo", correct_column=no)
    k1, k2 = f"row_{r1.pk}", f"row_{r2.pk}"
    return Kit(
        question=q,
        half={k1: yes.pk, k2: yes.pk},
        right={k1: yes.pk, k2: no.pk},
        empty={},
        key=[yes.pk, no.pk],
        leak=f'value="{no.pk}" checked',
        key_text="Nocol",
    )


def _multigrid(**kw):
    q = MultiGridQuestionElement.objects.create(stem="Tick?", **kw)
    a = MultiGridColumn.objects.create(question=q, order=0, label="Acol")
    b = MultiGridColumn.objects.create(question=q, order=1, label="Bcol")
    r1 = MultiGridRow.objects.create(question=q, order=0, statement="Sone")
    r1.correct_columns.set([a])
    r2 = MultiGridRow.objects.create(question=q, order=1, statement="Stwo")
    r2.correct_columns.set([a, b])
    k1, k2 = f"row_{r1.pk}", f"row_{r2.pk}"
    return Kit(
        question=q,
        half={k1: [a.pk], k2: [a.pk]},
        right={k1: [a.pk], k2: [a.pk, b.pk]},
        empty={},
        key=[[a.pk], sorted([a.pk, b.pk])],
        leak=f'value="{b.pk}" checked',
        key_text="Bcol",
    )


_BUILDERS = {
    "dragfill": _dragfill,
    "matchpair": _matchpair,
    "dragimage": _dragimage,
    "choicegrid": _choicegrid,
    "multigrid": _multigrid,
}

# A drag part = its <select> plus the .sr-only verdict right after it; a grid part =
# one <tbody> row (its statement cell holds the .sr-only verdict).
_SELECT_PART = re.compile(
    r'<select\b.*?</select>(?:<span class="sr-only">[^<]*</span>)?', re.S
)
_TBODY = re.compile(r"<tbody>(.*?)</tbody>", re.S)
_ROW = re.compile(r"<tr\b.*?</tr>", re.S)


def parts(kind, html):
    """Every part's full markup in `html`, in draw order."""
    if kind in DND_KINDS:
        return _SELECT_PART.findall(html)
    found = []
    for body in _TBODY.findall(html):
        found += _ROW.findall(body)
    return found


def paint(kind, html):
    """Per part: "correct" / "incorrect" / None, read from the part's OWN opening
    tag (the <select> / the <tr>), never from a descendant."""
    out = []
    for part in parts(kind, html):
        head = part.split(">", 1)[0]
        if "is-correct" in head:
            out.append("correct")
        elif "is-incorrect" in head:
            out.append("incorrect")
        else:
            out.append(None)
    return out


def yours(html):
    """The student's copy: from data-answer-yours up to whatever follows it."""
    part = html.split("data-answer-yours", 1)[1]
    for stop in (
        "data-answer-key",
        "data-answer-switch",
        'type="submit"',
        "data-question-feedback",
    ):
        part = part.split(stop, 1)[0]
    return part


def key(html):
    """The key copy: from data-answer-key up to the switch."""
    return html.split("data-answer-key", 1)[1].split("data-answer-switch", 1)[0]
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_quiz_reveal_pr2_hooks.py
"""Per-type reveal hooks for the five PR 2 types (spec 2026-09-25 §2.1, §2.2, §2.6)."""

from decimal import Decimal

import pytest

from courses.models import ChoiceGridQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import GridRow
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.quiz import answer_to_json
from courses.quiz import rehydrate
from courses.views import _stored_result
from tests.factories import MediaAssetFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_quiz_unit
from tests.reveal_pr2_kit import KINDS
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import post


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS)
def test_part_verdicts_one_bool_per_part(kind):
    kit = build(kind)
    q = kit.question
    answer = q.build_answer(post(kit.half))
    assert q.part_verdicts(q.mark(answer), answer) == [True, False]
    right = q.build_answer(post(kit.right))
    assert q.part_verdicts(q.mark(right), right) == [True, True]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS)
def test_key_answer_is_build_answer_of_the_right_post(kind):
    # Spec §2.2: the key is in EXACTLY build_answer()'s shape, so the same
    # render / rehydrate path draws both copies.
    kit = build(kind)
    q = kit.question
    assert q.key_answer() == kit.key
    assert q.build_answer(post(kit.right)) == kit.key
    assert rehydrate(q, answer_to_json(q.key_answer()))[1] == kit.key


@pytest.mark.django_db
def test_empty_keys_are_none():
    # P3: no parts at all -> no key copy, no switch.
    assert DragFillBlankQuestionElement.objects.create(stem="x").key_answer() is None
    assert MatchPairQuestionElement.objects.create(stem="x").key_answer() is None
    assert (
        DragToImageQuestionElement.objects.create(
            media=MediaAssetFactory()
        ).key_answer()
        is None
    )
    assert ChoiceGridQuestionElement.objects.create(stem="x").key_answer() is None
    mg = MultiGridQuestionElement.objects.create(stem="x")
    assert mg.key_answer() is None
    MultiGridRow.objects.create(question=mg, order=0, statement="s")
    assert mg.key_answer() is None  # a row, but nothing is correct anywhere


@pytest.mark.django_db
def test_multigrid_empty_row_inside_a_real_key_stays():
    # P3: a "tick nothing" row inside a non-empty key is a real answer.
    kit = build("multigrid")
    q = kit.question
    MultiGridRow.objects.create(question=q, order=2, statement="none apply")
    assert q.key_answer() == kit.key + [[]]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS)
def test_stored_path_verdicts_follow_the_current_key(kind):
    # Spec §2.6: colours come from a FRESH mark() of the stored answer.
    kit = build(kind)
    q = kit.question
    unit = make_quiz_unit()
    el = add_element(unit, q)
    sub = QuizSubmission.objects.create(student=UserFactory(), unit=unit)
    stored = answer_to_json(q.build_answer(post(kit.half)))
    r = QuestionResponse.objects.create(
        submission=sub,
        element=el,
        attempt_count=1,
        latest_answer=stored,
        fraction=Decimal("0.5000"),
    )
    assert q.part_verdicts(_stored_result(q, r), stored) == [True, False]


@pytest.mark.django_db
def test_grid_key_edit_repaints_on_the_stored_path():
    kit = build("choicegrid")
    q = kit.question
    unit = make_quiz_unit()
    el = add_element(unit, q)
    sub = QuizSubmission.objects.create(student=UserFactory(), unit=unit)
    stored = answer_to_json(q.build_answer(post(kit.half)))
    r = QuestionResponse.objects.create(
        submission=sub,
        element=el,
        attempt_count=1,
        latest_answer=stored,
        fraction=Decimal("0.5000"),
    )
    row2 = GridRow.objects.filter(question=q).order_by("order")[1]
    row2.correct_column = q.columns.order_by("order")[0]  # the student's pick
    row2.save()
    assert q.part_verdicts(_stored_result(q, r), stored) == [True, True]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr2_hooks.py -p no:randomly`
Expected: FAIL — `part_verdicts` returns `None` (base hook), `key_answer()` returns `None`.

- [ ] **Step 4: Implement the hooks**

Each type reads its **own** reveal key (spec §2.1: no shared base implementation). In `courses/models.py`, directly after each type's `mark()`:

`DragFillBlankQuestionElement`:

```python
    def part_verdicts(self, mark_result, answer):
        # dnd.mark_slots: one {"index", "correct", "accepted"} per gap, gap order.
        return [bool(item["correct"]) for item in mark_result.reveal]

    def key_answer(self):
        # build_answer's shape: one slot value per gap (spec §2.2); None when the
        # whole key is empty (P3).
        tokens = self.expected_tokens()
        return tokens if any(tokens) else None
```

`MatchPairQuestionElement` and `DragToImageQuestionElement`: the same two methods, with the comments `# dnd.mark_slots: one entry per left item, pairs order.` / `# dnd.mark_slots: one entry per zone, zones order.` and `# build_answer's shape: one slot value per left item / per zone (spec §2.2)`.

`ChoiceGridQuestionElement`:

```python
    def part_verdicts(self, mark_result, answer):
        # mark(): one {"statement", ..., "is_correct"} per row, rows order.
        return [bool(item["is_correct"]) for item in mark_result.reveal]

    def key_answer(self):
        # build_answer's shape: one column pk per row (spec §2.2). correct_column is
        # a required FK, so a key exists as soon as a row does.
        return [row.correct_column_id for row in self.rows.all()] or None
```

`MultiGridQuestionElement`:

```python
    def part_verdicts(self, mark_result, answer):
        # mark(): one {"statement", ..., "is_correct"} per row, rows order.
        return [bool(item["is_correct"]) for item in mark_result.reveal]

    def key_answer(self):
        # build_answer's shape: a SORTED column-pk list per row (spec §2.2). A row
        # with no correct column is a real "tick nothing" answer; only a key with
        # nothing correct anywhere is empty (P3).
        key = [
            sorted(c.pk for c in row.correct_columns.all()) for row in self.rows.all()
        ]
        return key if any(key) else None
```

Do **not** set `SUPPORTS_REVEAL` / `INLINE_LESSON_FEEDBACK` / `CONTROLS_TEMPLATE` here — Tasks 3 and 4 do, together with the templates, so no commit leaves a flagged type without its template.

- [ ] **Step 5: Run the tests to verify they pass, plus the marking suites**

Run: `uv run pytest tests/test_quiz_reveal_pr2_hooks.py tests/test_quiz_reveal_hooks.py tests/test_questions_2d_dragfill_mark.py tests/test_questions_2d_matchpair_mark.py tests/test_questions_2dii_mark.py tests/test_marking_choicegrid.py tests/test_marking_multigrid.py -p no:randomly`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --no-cache --fix courses/models.py tests/reveal_pr2_kit.py tests/test_quiz_reveal_pr2_hooks.py && uv run ruff format --no-cache courses/models.py tests/reveal_pr2_kit.py tests/test_quiz_reveal_pr2_hooks.py && uv run ruff check --no-cache courses/models.py tests/reveal_pr2_kit.py tests/test_quiz_reveal_pr2_hooks.py
git add courses/models.py tests/reveal_pr2_kit.py tests/test_quiz_reveal_pr2_hooks.py
git commit -m "feat(quiz-reveal): part_verdicts + key_answer for drag, match, image and grid types"
```

---

### Task 2: Verdict painting in the Python-built controls

**Files:**
- Create: `courses/verdicts.py`
- Modify: `courses/dnd.py` (`_render_select`, `render_selects`, `render_match_rows`, `render_zone_selects`)
- Modify: `courses/templatetags/courses_extras.py` (`render_drag_selects`, `render_match_pairs`, `render_image_selects`, `render_choice_grid`, `_grid_row_cells`, `render_multigrid`, `_multigrid_row_cells`)
- Test: `tests/test_quiz_reveal_pr2_paint.py` (new)

**Interfaces:**
- Consumes: Task 1's test kit (`tests/reveal_pr2_kit.py`) in the tests; the production builders take plain verdict lists.
- Produces: `courses.verdicts.part_verdict(verdicts, i, key) -> bool | None`, `state_class(verdict) -> str` (`" is-correct"` / `" is-incorrect"` / `""`), `invalid_attr(verdict) -> SafeString`, `sr_verdict(verdict) -> SafeString`. `dnd.render_selects(token_stem, pool, chosen=None, verdicts=None, key=False)`, same two kwargs on `render_match_rows` and `render_zone_selects`; `dnd._render_select(pool, chosen, verdict=None)`. Template tags `render_drag_selects / render_match_pairs / render_image_selects / render_choice_grid / render_multigrid (el, submitted_values=None, verdicts=None, copy="")` — `copy == "key"` paints every part correct. Grid markup: a painted row is `<tr class="is-correct">` / `<tr class="is-incorrect">`, the verdict span is the last child of the statement cell, and each input of a wrong row carries `aria-invalid="true"` as its LAST attribute (after `checked`) — existing tests pin the substrings `value="<pk>" checked` and `name="row_<pk>" value="<pk>" checked` (`courses/tests/test_question_restore.py`), and a lesson restore of a wrong grid now paints, so nothing may be inserted between `name`, `value` and `checked`. Likewise on a drag `<select>` the state class goes INSIDE the existing `class` attribute and `aria-invalid` after it: `<select name="slot"` stays the tag's prefix (`_slot_options()` in the same file splits on it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_pr2_paint.py
"""Verdict painting in the Python-built drag / grid controls (spec 2026-09-25 §2.1)."""

import re

import pytest

from courses import dnd
from courses.fillblank import parse
from courses.templatetags.courses_extras import render_choice_grid
from courses.templatetags.courses_extras import render_drag_selects
from courses.templatetags.courses_extras import render_multigrid
from courses.verdicts import part_verdict
from tests.reveal_pr2_kit import GRID_KINDS
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import paint
from tests.reveal_pr2_kit import parts
from tests.reveal_pr2_kit import post

_SR_OK = '<span class="sr-only">correct</span>'
_SR_BAD = '<span class="sr-only">incorrect</span>'


def test_part_verdict_rules():
    assert part_verdict([True, False], 1, key=False) is False
    assert part_verdict([True], 3, key=False) is None  # shorter list: unpainted
    assert part_verdict(None, 0, key=False) is None
    assert part_verdict(None, 5, key=True) is True  # the key copy: all correct


def test_unpainted_select_is_byte_identical():
    # Master's markup, literally (the option label is translatable, so only the
    # structure around it is pinned). The existing render suites guard the rest.
    plain = str(dnd._render_select(["a", "b"], "a"))
    assert plain.startswith('<select name="slot" class="dnd__select"><option value="">')
    assert plain.endswith(
        '<option value="a" selected>a</option><option value="b">b</option></select>'
    )


def test_render_selects_paints_each_gap_with_both_cues():
    stem = parse("x {{a}} y {{b}}")[0]
    html = str(dnd.render_selects(stem, ["a", "b", "c"], ["a", "c"], verdicts=[True, False]))
    right, wrong = parts("dragfill", html)
    assert paint("dragfill", html) == ["correct", "incorrect"]
    assert "aria-invalid" not in right and right.endswith(_SR_OK)
    assert 'aria-invalid="true"' in wrong.split(">", 1)[0] and wrong.endswith(_SR_BAD)


def test_key_paints_every_gap_correct():
    stem = parse("x {{a}} y {{b}}")[0]
    html = str(dnd.render_selects(stem, ["a", "b"], ["a", "b"], key=True))
    assert paint("dragfill", html) == ["correct", "correct"]


def test_match_and_zone_rows_paint():
    class P:  # render_match_rows reads only .left
        def __init__(self, left):
            self.left = left

    rows = str(dnd.render_match_rows([P("L1"), P("L2")], ["a", "b"], ["a", "b"], verdicts=[False, None]))
    assert paint("matchpair", rows) == ["incorrect", None]
    zones = str(dnd.render_zone_selects([object(), object()], ["a"], ["a", ""], verdicts=[True, False]))
    assert paint("dragimage", zones) == ["correct", "incorrect"]


@pytest.mark.django_db
def test_drag_tag_forwards_verdicts_and_copy():
    kit = build("dragfill")
    q = kit.question
    assert paint("dragfill", str(render_drag_selects(q, ["alphakey", "gammadis"], verdicts=[True, False]))) == ["correct", "incorrect"]
    assert paint("dragfill", str(render_drag_selects(q, kit.key, copy="key"))) == ["correct", "correct"]
    assert paint("dragfill", str(render_drag_selects(q))) == [None, None]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", GRID_KINDS)
def test_grid_rows_paint_with_both_cues(kind):
    kit = build(kind)
    q = kit.question
    tag = render_choice_grid if kind == "choicegrid" else render_multigrid
    values = q.build_answer(post(kit.half))
    html = str(tag(q, values, verdicts=[True, False]))
    right, wrong = parts(kind, html)
    assert paint(kind, html) == ["correct", "incorrect"]
    assert _SR_OK in right and "aria-invalid" not in right
    assert _SR_BAD in wrong
    inputs = [c for c in wrong.split("<input")[1:]]
    assert inputs and all('aria-invalid="true"' in c.split(">", 1)[0] for c in inputs)
    # aria-invalid goes LAST, so the pinned `value="<pk>" checked` substring survives.
    assert re.search(r'value="\d+" checked aria-invalid="true">', wrong)
    assert paint(kind, str(tag(q, kit.key, copy="key"))) == ["correct", "correct"]


def test_painted_select_keeps_its_name_prefix():
    # courses/tests/test_question_restore.py::_slot_options splits on this literal.
    html = str(dnd._render_select(["a"], "a", verdict=False))
    assert html.startswith('<select name="slot" class="dnd__select is-incorrect" aria-invalid="true">')


@pytest.mark.django_db
@pytest.mark.parametrize("kind", GRID_KINDS)
def test_unpainted_grid_row_markup_unchanged(kind):
    kit = build(kind)
    tag = render_choice_grid if kind == "choicegrid" else render_multigrid
    html = str(tag(kit.question, None))
    assert "<tr>" in html and "is-" not in html and "sr-only" not in html
    assert "aria-invalid" not in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr2_paint.py -p no:randomly`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.verdicts'`.

- [ ] **Step 3: Write `courses/verdicts.py`**

```python
"""One verdict -> markup for the Python-built answer controls (spec 2026-09-25 §2.1).

Colour is never the only cue: a painted part gets a state class, a wrong one
aria-invalid, and both a .sr-only "correct"/"incorrect" (the global utility, NOT
the notes/tags .visually-hidden). A verdict of None paints NOTHING, so an unpainted
render stays byte-identical to the pre-reveal markup."""

from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import pgettext


def part_verdict(verdicts, i, key):
    """Part i's verdict: every part is correct in the key copy; a list shorter
    than the parts (a part added after the answer) leaves the rest unpainted."""
    if key:
        return True
    marks = verdicts or ()
    return marks[i] if 0 <= i < len(marks) else None


def state_class(verdict):
    return {True: " is-correct", False: " is-incorrect"}.get(verdict, "")


def invalid_attr(verdict):
    return mark_safe(' aria-invalid="true"') if verdict is False else ""  # noqa: S308 — constant


def sr_verdict(verdict):
    if verdict is None:
        return ""
    return format_html(
        '<span class="sr-only">{}</span>',
        pgettext("answer part verdict", "correct")
        if verdict
        else pgettext("answer part verdict", "incorrect"),
    )
```

- [ ] **Step 4: Paint the drag selects (`courses/dnd.py`)**

Add `from courses.verdicts import invalid_attr, part_verdict, sr_verdict, state_class` (ruff splits it). Change `_render_select`'s signature to `_render_select(pool, chosen, verdict=None)`, add to its docstring "`verdict` paints the select (spec 2026-09-25 §2.1); None leaves the markup unchanged.", and replace its `return format_html(...)` with:

```python
    return format_html(
        '<select name="slot" class="dnd__select{}"{}>{}</select>{}',
        state_class(verdict),
        invalid_attr(verdict),
        mark_safe("".join(opts)),  # noqa: S308 — options built via format_html; join is safe
        sr_verdict(verdict),
    )
```

`render_selects(token_stem, pool, chosen=None, verdicts=None, key=False)`: in the odd-part branch, `out.append(str(_render_select(pool, val, part_verdict(verdicts, n, key))))` (`n` is the gap index already computed there).

`render_match_rows(pairs, pool, chosen=None, verdicts=None, key=False)` and `render_zone_selects(zones, pool, chosen=None, verdicts=None, key=False)`: pass `part_verdict(verdicts, i, key)` as `_render_select`'s third argument. Add one docstring sentence to each: "`verdicts` / `key` paint the selects (spec 2026-09-25 §2.1)."

- [ ] **Step 5: Forward through the tags and paint the grids (`courses/templatetags/courses_extras.py`)**

Add `from courses.verdicts import invalid_attr, part_verdict, sr_verdict, state_class`.

```python
@register.simple_tag
def render_drag_selects(el, submitted_values=None, verdicts=None, copy=""):
    """Render a drag-fill stem: text segments interleaved with server-built
    <select name="slot"> elements (escaped). `verdicts` / copy="key" paint the gaps
    (spec 2026-09-25 §2.1). See courses.dnd."""
    from courses import dnd

    return dnd.render_selects(
        el.stem,
        dnd.build_pool(el),
        submitted_values or None,
        verdicts=verdicts or None,
        key=copy == "key",
    )
```

`render_match_pairs` and `render_image_selects` get the same two kwargs and forward `verdicts=verdicts or None, key=copy == "key"` to `render_match_rows` / `render_zone_selects`. (`submitted_values or None`: an unresolved template variable arrives as `''`.)

`render_choice_grid(el, submitted_values=None, verdicts=None, copy="")` — replace the `body = format_html_join(...)` block with:

```python
    key = copy == "key"
    body = format_html_join(
        "",
        '<tr{}><td class="choicegrid__stmt">{}{}</td>{}</tr>',
        (
            (
                _row_class(part_verdict(verdicts, i, key)),
                row.statement,
                sr_verdict(part_verdict(verdicts, i, key)),
                _grid_row_cells(
                    row,
                    cols,
                    sv[i] if i < len(sv) else "",
                    invalid_attr(part_verdict(verdicts, i, key)),
                ),
            )
            for i, row in enumerate(rows)
        ),
    )
```

and add, directly above `_grid_row_cells`:

```python
def _row_class(verdict):
    # A grid part is a ROW (spec 2026-09-25 D6, plan P1). No attribute at all when
    # unpainted, so an unpainted grid stays byte-identical.
    state = state_class(verdict).strip()
    return format_html(' class="{}"', state) if state else ""
```

`_grid_row_cells(row, cols, chosen, invalid="")`: both `format_html` templates gain a `{}` for `invalid` as the LAST thing in the tag — `'<td><label><input type="radio" name="row_{}" value="{}" checked{}></label></td>'` and `'<td><label><input type="radio" name="row_{}" value="{}"{}></label></td>'` — passing `invalid` as the third argument. With `invalid=""` the output is unchanged, and the pinned `value="<pk>" checked` substring survives a painted row.

`render_multigrid` and `_multigrid_row_cells` get exactly the same change (`multigrid__stmt`, checkboxes, `sv[i] if i < len(sv) else []`).

- [ ] **Step 6: Run the new tests plus the unchanged render suites**

Run: `uv run pytest tests/test_quiz_reveal_pr2_paint.py tests/test_dnd_render.py tests/test_render_choicegrid.py tests/test_render_multigrid.py tests/test_questions_2dii_render.py tests/test_quiz_reveal_fillblank_render.py -p no:randomly`
Expected: PASS, with the five existing suites **unedited** (the byte-identity constraint). A failure in them means an unpainted path changed — fix the code, not the test.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache --fix courses/verdicts.py courses/dnd.py courses/templatetags/courses_extras.py tests/test_quiz_reveal_pr2_paint.py && uv run ruff format --no-cache courses/verdicts.py courses/dnd.py courses/templatetags/courses_extras.py tests/test_quiz_reveal_pr2_paint.py && uv run ruff check --no-cache courses/verdicts.py courses/dnd.py courses/templatetags/courses_extras.py tests/test_quiz_reveal_pr2_paint.py
git add courses/verdicts.py courses/dnd.py courses/templatetags/courses_extras.py tests/test_quiz_reveal_pr2_paint.py
git commit -m "feat(quiz-reveal): paint drag selects and grid rows from verdicts (both cues)"
```

---

### Task 3: Drag the words, match pairs, drag onto image — quiz, results, lessons

**Files:**
- Create: `templates/courses/elements/_dragfillblankquestionelement_controls.html`, `_matchpairquestionelement_controls.html`, `_dragtoimagequestionelement_controls.html`
- Modify: `templates/courses/elements/dragfillblankquestionelement.html`, `matchpairquestionelement.html`, `dragtoimagequestionelement.html`
- Modify: `courses/models.py` (flags on the three drag types)
- Test: `tests/test_quiz_reveal_pr2_flow.py` (new)
- Rewrite (allowed, see Step 5): existing tests pinning the old drag markup / lists

**Interfaces:**
- Consumes: Task 1 hooks and kit; Task 2 tags (`verdicts=`, `copy=`); PR 1's `render()` (its template context: `submitted_values`, `verdicts`, `locked`, `key_copy_html`, `can_reveal`, `reveal_earned`, `revealed`, `mode`, `feedback_for_pk`, `feedback_html`); the controls include instead receives `values`, `verdicts`, `copy` — from the type template's `{% include … with values=… %}` or from `render_key_copy` (`values=key_values`, `verdicts=None`, `copy="key"`); `_answer_switch.html`, `_reveal_button.html`.
- Produces: the three types with `SUPPORTS_REVEAL = True`, `INLINE_LESSON_FEEDBACK = True`, `CONTROLS_TEMPLATE` set; each copy wrapped in its own `<div data-dnd>` root; the module constant `KINDS_UNDER_TEST` in `tests/test_quiz_reveal_pr2_flow.py` (Task 4 widens it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_pr2_flow.py
"""The PR 2 types through every quiz, results and lesson path (spec 2026-09-25 §2,
§4, §5, §5a). Task 3 converts the drag types; Task 4 widens KINDS_UNDER_TEST."""

import re

import pytest
from django.urls import reverse
from django.utils import translation

from courses.models import DragBlank
from courses.models import Enrollment
from courses.models import QuestionResponse
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr2_kit import DND_KINDS
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import key
from tests.reveal_pr2_kit import paint
from tests.reveal_pr2_kit import parts
from tests.reveal_pr2_kit import yours

# Task 4 widens this to DND_KINDS + GRID_KINDS.
KINDS_UNDER_TEST = DND_KINDS

_CONTROL = re.compile(r"<(?:input|select)\b[^>]*>")
_SR_OK = '<span class="sr-only">correct</span>'
_SR_BAD = '<span class="sr-only">incorrect</span>'


def _quiz(client, username="stu"):
    user = make_login(client, username)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


def _add(unit, kind, **kw):
    kit = build(kind, **kw)
    return kit, add_element(unit, kit.question)


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _fetch(client, unit, el, data):
    return client.post(_url(unit, el), data, HTTP_X_REQUESTED_WITH="fetch")


def _page(client, unit):
    return client.get(
        reverse("courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    ).content.decode()


def _results(client, unit):
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    return client.get(reverse("courses:quiz_results", kwargs=kw)).content.decode()


def _no_answers(kit, html):
    """Lesson / pre-lock invariant: no list, no copy, no switch, no Show answer."""
    assert "question__reveal" not in html
    assert "data-answer-key" not in html and "data-answer-switch" not in html
    assert 'name="reveal"' not in html
    assert kit.leak not in html


# ── quiz: before the lock ─────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_check_answers_whole_element_painted_no_key(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert "data-question-inline" in body and "<form" in body
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    assert "data-answer-key" not in body and "question__reveal" not in body
    assert kit.leak not in body  # only booleans before the lock (spec §2.1)
    assert 'name="reveal"' in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_empty_check_is_a_bare_validation_fragment(client, kind):
    # Spec §2.4: validation responses stay the feedback fragment (no swap), use no
    # attempt, and leave the earlier paint in place on resume.
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    _fetch(client, unit, el, kit.half)
    body = _fetch(client, unit, el, kit.empty).content.decode()
    assert "<form" not in body and "is-validation" in body
    assert QuestionResponse.objects.get(element=el).attempt_count == 1
    assert paint(kind, yours(_page(client, unit))) == ["correct", "incorrect"]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_cues_on_every_painted_part(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    right, wrong = parts(kind, yours(_fetch(client, unit, el, kit.half).content.decode()))
    assert _SR_OK in right and "aria-invalid" not in right
    assert _SR_BAD in wrong and 'aria-invalid="true"' in wrong


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_one_feedback_box_check_first_at_most_one_reveal(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    for body in (
        _fetch(client, unit, el, kit.half).content.decode(),
        _page(client, unit),
    ):
        # Only THIS question's form: the full page has other submit buttons.
        body = re.search(r"<form[^>]*data-answer-scope.*?</form>", body, re.S).group(0)
        assert body.count("data-question-feedback") == 1
        buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', body)
        assert 'name="reveal"' not in buttons[0]  # Check first (spec §3.1)
        assert sum('name="reveal"' in b for b in buttons) == 1


# ── quiz: locked ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_locked_wrong_shows_a_neutralised_painted_key_copy(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind, max_attempts=1)
    body = _fetch(client, unit, el, kit.half).content.decode()
    k = key(body)
    assert kit.leak in k and kit.leak not in yours(body)
    assert paint(kind, k) == ["correct", "correct"]
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    controls = _CONTROL.findall(k)
    assert controls and all("name=" not in c and "disabled" in c for c in controls)
    if kind in DND_KINDS:
        assert all("data-slot" in s for s in re.findall(r"<select\b[^>]*>", k))
    assert body.count("data-answer-switch") == 1
    assert "question__reveal" not in body
    assert 'name="reveal"' not in body  # locked: no Show answer


@pytest.mark.django_db
@pytest.mark.parametrize("kind", DND_KINDS)
def test_each_copy_is_its_own_dnd_root(client, kind):
    # Spec §2.4: data-dnd / the pool / the stage live inside the controls include,
    # once per copy -- never on the outer [data-question] div.
    unit = _quiz(client)
    kit, el = _add(unit, kind, max_attempts=1)
    kit2, el2 = _add(unit, kind)  # max_attempts=3: stays open after one Check
    root = re.compile(r"\bdata-dnd(?=[\s=>])")
    open_body = _fetch(client, unit, el2, kit2.half).content.decode()
    assert len(root.findall(open_body)) == 1
    body = _fetch(client, unit, el, kit.half).content.decode()
    outer = re.search(r"<div[^>]*\bel--question\b[^>]*>", body).group(0)
    assert "data-dnd" not in outer and "data-question" in outer
    assert len(root.findall(yours(body))) == 1 and len(root.findall(key(body))) == 1
    assert body.count("data-dnd-pool") == 2
    if kind == "dragimage":
        assert body.count("data-dragimage-stage") == 2


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_never_show_the_key(client, kind, mode):
    unit = _quiz(client)
    kit, el = _add(unit, kind, marking_mode=mode)
    body = _fetch(client, unit, el, kit.half).content.decode()
    for html in (body, _page(client, unit), _results(client, unit)):
        assert "data-answer-key" not in html and "data-answer-switch" not in html


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_resume_paints_then_reveal_shows_the_key(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    _fetch(client, unit, el, kit.half)
    page = _page(client, unit)
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    assert 'name="reveal"' in page and "data-answer-key" not in page
    revealed = _fetch(client, unit, el, {"reveal": "1"}).content.decode()
    assert "data-answer-key" in revealed and "answer shown" in revealed
    assert QuestionResponse.objects.get(element=el).attempt_count == 1
    page = _page(client, unit)
    assert kit.leak in key(page) and "answer shown" in page


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_nojs_check_and_reveal_paint_the_full_page(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    page = client.post(_url(unit, el), kit.half).content.decode()
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert kit.leak in key(page)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_nojs_previewer_check_paints_and_offers_reveal(client, kind):
    user = make_login(client, "prev_staff")
    user.is_staff = True  # staff + not enrolled = the previewer path
    user.save()
    unit = make_quiz_unit()
    kit, el = _add(unit, kind)
    page = client.post(_url(unit, el), {**kit.half, "attempt": "1"}).content.decode()
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    assert 'name="reveal"' in page
    page = client.post(_url(unit, el), {**kit.half, "reveal": "1"}).content.decode()
    assert kit.leak in key(page)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_editor_try_it_quiz_reveal(client, kind):
    pa = make_pa(client, f"pa_{kind}")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    kit, el = _add(unit, kind)
    url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk})
    body = client.post(url, {**kit.half, "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert paint(kind, yours(body)) == ["correct", "incorrect"] and 'name="reveal"' in body
    body = client.post(
        url, {**kit.half, "reveal": "1", "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert kit.leak in key(body) and "answer shown" in body
    assert body.count("data-question-feedback") == 1 and 'name="reveal"' not in body
    assert QuestionResponse.objects.count() == 0


# ── results page + analytics ─────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_results_render_each_question_read_only(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    _un_kit, _un_el = _add(unit, kind)  # left unanswered
    _fetch(client, unit, el, kit.half)
    _fetch(client, unit, el, {"reveal": "1"})
    body = _results(client, unit)
    answered, unanswered = body.split('class="quiz-results__item')[1:3]
    for row in (answered, unanswered):
        assert "data-answer-scope" in row and "<form" not in row
        assert 'type="submit"' not in row and "question__reveal" not in row
        assert "data-answer-switch" in row
        assert re.search(r"<fieldset[^>]*data-answer-yours[^>]*\bdisabled", row)
        assert all("disabled" in c for c in _CONTROL.findall(key(row)))
    assert paint(kind, yours(answered)) == ["correct", "incorrect"]
    assert paint(kind, yours(unanswered)) == [None, None]
    assert "answer shown" in answered


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_results_helper_never_marks_an_unanswered_row(monkeypatch, kind):
    from courses import views

    unit = make_quiz_unit()
    kit, el = _add(unit, kind)
    row = views._results_row(kit.question, None)

    def _boom(*args, **kwargs):
        raise AssertionError("mark() called for an unanswered results row")

    monkeypatch.setattr(type(kit.question), "mark", _boom)
    html = str(views._results_question_html(el, kit.question, None, row))
    assert kit.leak in key(html) and paint(kind, yours(html)) == [None, None]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
@pytest.mark.parametrize("answered", [True, False])
def test_analytics_still_shows_the_expected_answer(client, kind, answered):
    # Spec §5: _results_row keeps its keys; analytics shows the expected answer.
    user = make_login(client, "stu_an")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    kit, el = _add(unit, kind, max_attempts=1)
    if answered:
        _fetch(client, unit, el, kit.half)
    _results(client, unit)
    client.logout()
    make_pa(client, "pa_an")
    url = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": unit.course.slug, "student_pk": user.pk, "node_pk": unit.pk},
    )
    assert kit.key_text in client.get(url).content.decode()


# ── lessons (D13, spec §5a) ──────────────────────────────────────────────────


def _lesson(client, kind, username="ls"):
    student = make_student(client, username)
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    kit = build(kind)
    el = add_element(unit, kit.question)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    return kit, unit, el, url


def _lesson_page(client, unit):
    return client.get(
        reverse("courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    ).content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_lesson_fetch_check_paints_in_place_no_list(client, kind):
    kit, _unit, _el, url = _lesson(client, kind)
    body = client.post(url, kit.half, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "data-question-inline" in body and "<form" in body
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    right, wrong = parts(kind, yours(body))
    assert _SR_BAD in wrong and 'aria-invalid="true"' in wrong
    assert _SR_OK in right and "aria-invalid" not in right
    _no_answers(kit, body)
    assert "Correct answer" not in body and "Correct token" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_lesson_nojs_restore_and_editor_try_paint(client, kind):
    kit, unit, _el, url = _lesson(client, kind)
    page = client.post(url, kit.half).content.decode()  # no-JS re-render
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    _no_answers(kit, page)
    page = _lesson_page(client, unit)  # practice-state restore
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    _no_answers(kit, page)
    pa = make_pa(client, f"pa_ls_{kind}")
    course = CourseFactory(owner=pa)
    lu = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    kit2, el2 = _add(lu, kind)
    try_url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": el2.pk})
    body = client.post(try_url, kit2.half, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    _no_answers(kit2, body)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_lesson_correct_answer_keeps_controls_editable(client, kind):
    kit, _unit, _el, url = _lesson(client, kind)
    body = client.post(url, kit.right, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert paint(kind, yours(body)) == ["correct", "correct"]
    assert "disabled" not in yours(body) and "data-lock-on-correct" not in body


# ── Review Focus (plan) ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_deleted_distractor_after_answer_renders_wrong(client):
    unit = _quiz(client)
    kit, el = _add(unit, "matchpair", max_attempts=1)
    _fetch(client, unit, el, kit.half)  # picked "gammadis" for part 2
    q = kit.question
    q.distractors = ""
    q.save()
    page = _page(client, unit)
    assert paint("matchpair", yours(page)) == ["correct", "incorrect"]
    wrong = parts("matchpair", yours(page))[1]
    assert '<option value="" selected>' in wrong  # placeholder: not in the pool
    assert "data-answer-key" in page
    assert '<option value="gammadis"' not in _results(client, unit).split("quiz-results__item")[1]


@pytest.mark.django_db
def test_key_copy_escapes_and_keeps_latex_tokens(client):
    unit = _quiz(client)
    kit, el = _add(unit, "dragfill", max_attempts=1)
    DragBlank.objects.filter(question=kit.question, order=1).update(correct_token="a<b")
    DragBlank.objects.filter(question=kit.question, order=0).update(correct_token=r"\(x^2\)")
    body = _fetch(client, unit, el, {"slot": ["nope", "nope"]}).content.decode()
    k = key(body)
    assert 'value="a&lt;b" selected' in k and "<b" not in k.replace("&lt;b", "")
    assert 'value="\\(x^2\\)" selected' in k


@pytest.mark.django_db
def test_key_copy_preselects_normalised_duplicate(client):
    unit = _quiz(client)
    kit, el = _add(unit, "dragfill", max_attempts=1)
    DragBlank.objects.filter(question=kit.question, order=0).update(correct_token="paris")
    DragBlank.objects.filter(question=kit.question, order=1).update(correct_token="Paris")
    body = _fetch(client, unit, el, {"slot": ["gammadis", "gammadis"]}).content.decode()
    second = parts("dragfill", key(body))[1]
    assert 'value="paris" selected' in second  # the pool's surviving raw form


@pytest.mark.django_db
def test_dragimage_key_copy_geometry_unlocalized_in_pl():
    # Rendered directly: through a view, LocaleMiddleware would pick the language
    # from the request and override translation.override().
    unit = make_quiz_unit()
    kit, el = _add(unit, "dragimage", max_attempts=1)
    q = kit.question
    with translation.override("pl"):
        body = q.render(
            element=el,
            mode="quiz",
            action_url="/x/",
            feedback_for_pk=el.pk,
            submitted_values=["alphakey", "gammadis"],
            verdicts=[True, False],
            key_values=q.key_answer(),
            locked=True,
        )
    assert body.count('data-x="0.5"') == 2 and 'data-w="0.25"' in key(body)
    assert "0,5" not in body and "0,25" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_formless_render_keeps_its_controls(kind):
    # The `{% else %}` branch (no join row) renders through the same include.
    kit = build(kind)
    html = kit.question.render()
    assert len(parts(kind, html)) == 2
    if kind in DND_KINDS:
        assert re.search(r"\bdata-dnd(?=[\s=>])", html)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr2_flow.py -p no:randomly`
Expected: FAIL — the fetch Check returns the feedback fragment (no `<form`), no `data-answer-yours`, the lesson returns `_question_feedback.html` with the `question__reveal` list. `test_formless_render_keeps_its_controls` and `test_analytics_still_shows_the_expected_answer` may already pass (regression guards).

- [ ] **Step 3: Write the three controls includes**

`_dragfillblankquestionelement_controls.html`:

```django
{% load courses_extras %}<div data-dnd>{% render_drag_selects el values verdicts=verdicts copy=copy %}{% include "courses/elements/_dnd_pool.html" %}</div>
```

`_matchpairquestionelement_controls.html`:

```django
{% load courses_extras %}<div data-dnd>{% render_match_pairs el values verdicts=verdicts copy=copy %}{% include "courses/elements/_dnd_pool.html" %}</div>
```

`_dragtoimagequestionelement_controls.html` (the stage moves here from the type template, keeping its `unlocalize` rule):

```django
{% load l10n courses_extras %}{% comment %}One dnd root per copy (spec 2026-09-25 §2.4): the stage, the zone
selects and the pool travel together, so dnd.js pairs each copy's selects with its
OWN badges. unlocalize: dnd.js parseFloat() needs a '.' decimal; a localized ','
(e.g. Polish) parses to 0 and collapses the overlay targets to 0 size.{% endcomment %}<div data-dnd>
  <div class="dragimage__stage" data-dragimage-stage>
    <img class="dragimage__img" src="{{ el.media.file.url }}" alt="{{ el.alt }}">
    {% for z in el.zones.all %}
      <span class="dragimage__badge" data-zone="{{ forloop.counter0 }}"
            data-x="{{ z.x|unlocalize }}" data-y="{{ z.y|unlocalize }}" data-w="{{ z.w|unlocalize }}" data-h="{{ z.h|unlocalize }}"
            style="left:{% widthratio z.x 1 100 %}%; top:{% widthratio z.y 1 100 %}%;">{{ forloop.counter }}</span>
    {% endfor %}
  </div>
  {% render_image_selects el values verdicts=verdicts copy=copy %}{% include "courses/elements/_dnd_pool.html" %}
</div>
```

(`values` / `verdicts` / `copy` are unset in some callers; the tags normalise `''` to `None` — Task 2.)

- [ ] **Step 4: Restructure the three type templates + set the flags**

`dragfillblankquestionelement.html` (the stem prose IS the controls, so the whole stem is inside the copy — spec §2.2 table):

```django
{% load i18n courses_extras %}
{% comment %}Quiz answer reveal PR 2 (spec 2026-09-25 §2.2-§2.4, §4, §5a): the
controls include holds the dnd root, so each copy (the student's, the key) is its
own data-dnd block; data-answer-scope on the form (quiz / lesson) or the results
div; the switch outside every fieldset. data-question-inline is unconditional: it
tells quiz.js / question.js / editor.js to swap the form body, in lessons (D13) and
quizzes alike.{% endcomment %}
<div class="el el--question el--dragfill" data-question>
  {% if mode == "results" %}
  <div class="question__form" data-answer-scope>
    <fieldset class="question__stem" data-answer-yours disabled style="border:0;padding:0;margin:0;">
      {% include "courses/elements/_dragfillblankquestionelement_controls.html" with values=submitted_values %}
    </fieldset>
    {% if key_copy_html %}<div class="question__stem answer-key" data-answer-key style="margin:0;">{{ key_copy_html }}</div>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <div class="question__feedback" data-question-feedback>{{ feedback_html|safe }}</div>
  </div>
  {% elif element %}
  <form class="question__form" method="post" action="{{ action_url }}" data-question-inline data-answer-scope>
    {% csrf_token %}
    <fieldset class="question__stem" data-answer-yours {% if quiz_submitted or locked %}disabled{% endif %}
              style="border:0;padding:0;margin:0;">
      {% if element.pk == feedback_for_pk %}
        {% include "courses/elements/_dragfillblankquestionelement_controls.html" with values=submitted_values %}
      {% else %}
        {% include "courses/elements/_dragfillblankquestionelement_controls.html" with values=None verdicts=None %}
      {% endif %}
    </fieldset>
    {% if key_copy_html %}<div class="question__stem answer-key" data-answer-key style="margin:0;">{{ key_copy_html }}</div>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    {% include "courses/elements/_reveal_button.html" %}
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% else %}
    <div class="question__stem">{% include "courses/elements/_dragfillblankquestionelement_controls.html" with values=None verdicts=None %}</div>
  {% endif %}
</div>
```

`matchpairquestionelement.html` and `dragtoimagequestionelement.html`: the same skeleton with these differences — the stem stays outside, once, above the answer scope (`{% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}` directly inside the outer div, before `{% if mode == "results" %}`); the fieldset has **no** `question__stem` class (`<fieldset data-answer-yours … style="border:0;padding:0;margin:0;">`); the key-copy wrapper is `<div class="answer-key" data-answer-key>` (P5); the include paths are `_matchpairquestionelement_controls.html` / `_dragtoimagequestionelement_controls.html`; the form-less branch is `<div>{% include "…_controls.html" with values=None verdicts=None %}</div>`; the outer div is `<div class="el el--question el--matchpair" data-question>` / `el--dragimage`, with the `{% load i18n l10n courses_extras %}` of the image template reduced to `{% load i18n %}` (the include loads what it needs). Delete the old inline stage and its two `unlocalize` comments from `dragtoimagequestionelement.html` — they now live in the include.

In `courses/models.py`, on each of `DragFillBlankQuestionElement`, `MatchPairQuestionElement`, `DragToImageQuestionElement`, directly after `RESTORABLE_IN_LESSON = True`:

```python
    # Lesson (spec 2026-09-25 §5a, D13): parts painted in place; the list is gone.
    INLINE_LESSON_FEEDBACK = True

    SUPPORTS_REVEAL = True
    CONTROLS_TEMPLATE = "courses/elements/_dragfillblankquestionelement_controls.html"
```

(`_matchpairquestionelement_controls.html` / `_dragtoimagequestionelement_controls.html` on the other two.)

- [ ] **Step 5: Run the new tests, then the suites that pin the old drag behaviour; rewrite what D13 / the reveal legitimately changes**

Run: `uv run pytest tests/test_quiz_reveal_pr2_flow.py -p no:randomly`
Expected: PASS.

Then run: `uv run pytest tests/test_questions_2d_consumption.py tests/test_questions_2d_quiz_noleak.py tests/test_questions_2d_quiz_routing.py tests/test_questions_2d_results.py tests/test_questions_2d_reveal.py tests/test_questions_2d_views_touchpoints.py tests/test_questions_2dii_consumption.py tests/test_questions_2dii_render.py tests/test_dnd_render.py tests/test_quiz_noleak.py tests/test_quiz_resume.py tests/test_quiz_previewer_answer.py tests/test_quiz_previewer_render.py tests/test_quiz_reveal_flow.py tests/test_quiz_reveal_results.py tests/test_quiz_reveal_result_line.py tests/test_analytics_student_quiz.py tests/test_answer_summary.py tests/test_imagezoom_render.py tests/test_media_img_tag.py courses/tests/test_question_restore.py -p no:randomly`

Expected RED, and the ONLY allowed rewrites (each with the `# PR 2 (spec …): replaces …` comment):

(a) a drag-type fetch Check / lesson Check / lesson editor try-it now answers with the whole element (`<form`, `data-question-inline`), not the feedback fragment;
(b) a wrong drag-type LESSON Check no longer prints the `_reveal_dragfill` / `_reveal_matchpair` / `_reveal_dragimage` list ("Correct token:" etc.) — assert the painted parts instead (`paint(...) == [...]`, `aria-invalid`), D13;
(c) a locked wrong drag-type QUIZ question (fetch, resume, no-JS, previewer, editor) shows the key copy + switch instead of the list — assert `data-answer-key` + the key's token selected in the key copy;
(d) the results page renders a drag-type row as the question (`row.rendered`) instead of the list row;
(e) `data-dnd` / `data-dnd-pool` / `data-dragimage-stage` moved from the outer div into the include — assert them inside the form instead;
(f) a no-leak assertion that forbade correctness markers (`is-correct` / `is-incorrect`) on drag controls before the lock — D6 now requires them; keep every assertion about KEY TEXT (no key token selected, no list, no `data-answer-key`);
(g) a PR 1 test that used a drag type as its example of an UNCONVERTED type (e.g. "keeps today's list", "reveal POST is refused") — switch that example to `ChoiceQuestionElement` or `ExtendedResponseQuestionElement` (still unconverted until PR 3), keeping the assertion.

**Known at plan time (a catalogue of master's tests, 2026-09-26)** — expect exactly these, each under the rule shown:

| Test | Old assertion | Rule → rewrite to |
|---|---|---|
| `tests/test_quiz_reveal_result_line.py::test_incorrect_unconverted_non_inline_type_gets_new_line_too` | builds a DragFill; `"data-question-inline" not in body` | (g) → build an `ExtendedResponseQuestionElementFactory(required_keywords="alpha", max_attempts=3)` answered with POST `{"answer": "beta"}` (`ExtendedResponseQuestionElement.build_answer` reads `answer`); keep every assertion (the fragment, "Incorrect", "0 / 1", "2 attempts left") |
| `tests/test_questions_2d_quiz_noleak.py::test_dragfill_quiz_withholds_reveal_then_reveals_on_last_attempt` | `"Correct token:" in body2 and "Paris" in body2` | (c) → `"data-answer-key" in body2` and the key copy has `value="Paris" selected` (`"Paris" in body` alone is vacuous: every select lists the whole pool) |
| `tests/test_questions_2d_quiz_noleak.py::test_matchpair_quiz_withholds_then_reveals` | `"Correct match:" in body2 and "Paris" in body2` | (c) → the same key-copy form |
| `tests/test_questions_2d_results.py::test_results_reveals_dragfill_tokens_including_unanswered` | `"Paris" not in body` (plus the vacuous `"Madrid" in body and "Lisbon" in body`) | (d) → the fully-correct row has no `data-answer-switch`; the unanswered row's key copy has `value="Madrid" selected` / `value="Lisbon" selected` |
| `tests/test_questions_2d_results.py::test_results_matchpair_row_shows_left_label` | `"France" in body and "Paris" in body` (now vacuous) | (d) → the row's key copy pairs `France` with `value="Paris" selected` |
| `tests/test_questions_2d_reveal.py::test_dragfill_reveal_shows_correct_token_on_wrong_answer` (still GREEN but vacuous) | lesson `"Paris" in body  # … correct token shown` | (b) → the wrong select carries `is-incorrect` + `aria-invalid`, `question__reveal` absent, and no option `value="Paris" selected` |
| `tests/test_questions_2d_reveal.py::test_matchpair_reveal_lists_left_labels` (GREEN, vacuous) | `"France" in body and "Paris" in body` | (b) → painted selects; no list |
| `tests/test_quiz_previewer_answer.py::test_previewer_dragfill_no_leak_while_attempts_remain` (GREEN) | its comments claim the withhold branch never renders the stem | fix the comments only (the whole element now comes back); give the stem a gap marker so a real drag render is exercised |
| `tests/test_quiz_previewer_render.py::test_previewer_fieldset_wrapped_inputs_are_live` (probably GREEN) | reads the FIRST `<fieldset`; docstring cites `matchpairquestionelement.html:7` | make the split target `data-answer-yours`, drop the line citation |
| `tests/test_imagezoom_render.py` `NEVER_ARMED` | lists `dragtoimagequestionelement.html` — the stage `<img>` moved out of it | ADD `"courses/elements/_dragtoimagequestionelement_controls.html"` to `NEVER_ARMED` (keep the old entry); this is a guard widening, not a rewrite |

Every file named in this table is in the run command above — keep it that way if a row is added. e2e tests with the same cause are rewritten in Task 5 (they need the JS). Anything RED outside (a)–(g) and this table is a bug in this task — fix the code. Re-run the command above until it is green.

- [ ] **Step 6: Lint and commit**

```bash
# <rewritten> = every existing test file this task rewrote (Step 5)
uv run ruff check --no-cache --fix courses/models.py tests/test_quiz_reveal_pr2_flow.py <rewritten> && uv run ruff format --no-cache courses/models.py tests/test_quiz_reveal_pr2_flow.py <rewritten> && uv run ruff check --no-cache courses/models.py tests/test_quiz_reveal_pr2_flow.py <rewritten>
git add courses/models.py templates/courses/elements tests/
git commit -m "feat(quiz-reveal): drag the words, match pairs, drag onto image converted (quiz, results, lessons)"
```

---

### Task 4: Choice grid and multi grid — quiz, results, lessons

**Files:**
- Create: `templates/courses/elements/_choicegridquestionelement_controls.html`, `_multigridquestionelement_controls.html`
- Modify: `templates/courses/elements/choicegridquestionelement.html`, `multigridquestionelement.html`
- Modify: `courses/models.py` (flags on both grids)
- Modify: `tests/test_quiz_reveal_pr2_flow.py` (widen `KINDS_UNDER_TEST`)
- Test: `tests/test_quiz_reveal_pr2_grids.py` (new)
- Rewrite (allowed, see Step 5): existing tests pinning the old grid lists

**Interfaces:**
- Consumes: Tasks 1–3 (kit, hooks, painted grid tags, the flow module).
- Produces: both grids with `SUPPORTS_REVEAL = True`, `INLINE_LESSON_FEEDBACK = True`, `CONTROLS_TEMPLATE` set.

Before touching grids read `[[matrix-question-in-callout-status]]` in memory: "matrix" = `choice_grid`; grids NEST in lesson containers (callouts, tabs, …) through `builder.NESTABLE_TYPE_KEYS` AND `NESTABLE_QUESTION_KEYS` (the lesson-only rule lives in the second set — never edit one set without the other). This task changes neither set; it only relies on nested grids rendering through `render_element`'s generic question branch.

- [ ] **Step 1: Widen the flow module and write the grid-only tests**

In `tests/test_quiz_reveal_pr2_flow.py` change

```python
# Task 4 widens this to DND_KINDS + GRID_KINDS.
KINDS_UNDER_TEST = DND_KINDS
```

to

```python
KINDS_UNDER_TEST = DND_KINDS + GRID_KINDS
```

and add `from tests.reveal_pr2_kit import GRID_KINDS` to its imports.

```python
# tests/test_quiz_reveal_pr2_grids.py
"""Grid-only reveal behaviour (spec 2026-09-25 §2.2 grid radios, §5a nested)."""

import re

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import GridRow
from courses.models import UnitProgress
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import key
from tests.reveal_pr2_kit import paint
from tests.reveal_pr2_kit import parts
from tests.reveal_pr2_kit import post
from tests.reveal_pr2_kit import yours


def _quiz(client):
    user = make_login(client, "gstu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


def _fetch(client, unit, el, data):
    return client.post(
        f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/",
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _page(client, unit):
    return client.get(
        reverse("courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    ).content.decode()


@pytest.mark.django_db
def test_key_copy_radios_are_nameless_and_the_students_pick_stays_checked(client):
    # Spec §2.2: a key-copy radio still named row_<pk> would join the student's
    # radio group in the same form and uncheck the student's pick.
    unit = _quiz(client)
    kit = build("choicegrid", max_attempts=1)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    student_radios = re.findall(r"<input[^>]*type=\"radio\"[^>]*>", yours(body))
    checked = [r for r in student_radios if "checked" in r]
    assert len(checked) == 2 and all('name="row_' in r for r in checked)
    key_radios = re.findall(r"<input[^>]*type=\"radio\"[^>]*>", key(body))
    assert key_radios and all("name=" not in r and "disabled" in r for r in key_radios)
    assert sum("checked" in r for r in key_radios) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["choicegrid", "multigrid"])
def test_grid_row_added_after_answer(client, kind):
    unit = _quiz(client)
    kit = build(kind, max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    q = kit.question
    if kind == "choicegrid":
        GridRow.objects.create(question=q, order=2, statement="Sthree", correct_column=q.columns.first())
    else:
        row = q.rows.create(order=2, statement="Sthree")
        row.correct_columns.set([q.columns.first()])
    page = _page(client, unit)
    assert paint(kind, yours(page)) == ["correct", "incorrect", "incorrect"]
    assert len(parts(kind, key(page))) == 3
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    assert client.get(reverse("courses:quiz_results", kwargs=kw)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["choicegrid", "multigrid"])
def test_lesson_grid_nested_in_callout_paints_on_nojs_and_restore(client, kind):
    student = make_student(client, f"nest_{kind}")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    callout_row = add_element(unit, CalloutElement.objects.create(kind="example"))
    kit = build(kind)
    nested = Element.objects.create(
        unit=unit, content_object=kit.question, parent=callout_row, tab_id=CalloutElement.SLOT_ID
    )
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": nested.pk},
    )
    body = client.post(url, kit.half).content.decode()  # no-JS
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    page = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert paint(kind, yours(page)) == ["correct", "incorrect"]  # restore
    assert "question__reveal" not in page and "data-answer-key" not in page


@pytest.mark.django_db
@pytest.mark.parametrize(("checked", "sibling"), [("dragfill", "choicegrid"), ("choicegrid", "dragfill")])
def test_nojs_lesson_check_leaves_a_sibling_of_another_type_unpainted(client, checked, sibling):
    # The render() feedback_for_pk guard: the no-JS lesson re-render hands ONE
    # page-level mark_result to every question; a grid reading a dnd reveal (or
    # the reverse) would mis-paint or raise.
    student = make_student(client, f"sib_{checked}")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    kit = build(checked)
    el = add_element(unit, kit.question)
    other = build(sibling)
    add_element(unit, other.question)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, kit.half)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert paint(checked, yours(html)).count("incorrect") == 1
    sibling_html = html.split("data-answer-yours")[2]
    assert paint(sibling, sibling_html)[:2] == [None, None]


@pytest.mark.django_db
def test_lesson_restore_of_a_grid_uses_the_stored_answer(client):
    student = make_student(client, "gres")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    kit = build("multigrid")
    el = add_element(unit, kit.question)
    stored = kit.question.build_answer(post(kit.half))
    UnitProgress.objects.update_or_create(
        student=student, unit=unit, defaults={"element_state": {str(el.pk): {"answer": stored}}}
    )
    page = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert paint("multigrid", yours(page)) == ["correct", "incorrect"]
```

(`test_nojs_lesson_check_leaves_a_sibling_of_another_type_unpainted` finds the sibling as the SECOND `data-answer-yours` on the page — the checked question is added first, so it renders first.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr2_grids.py tests/test_quiz_reveal_pr2_flow.py -p no:randomly`
Expected: FAIL for every grid parametrization (no `data-answer-yours`, fragment responses, the `_reveal_choicegrid` list in lessons); the drag parametrizations still PASS.

- [ ] **Step 3: Write the two controls includes**

`_choicegridquestionelement_controls.html`:

```django
{% load courses_extras %}<div class="scroll-x" data-scroll-x><div class="choicegrid-scroll">{% render_choice_grid el values verdicts=verdicts copy=copy %}</div></div>
```

`_multigridquestionelement_controls.html`:

```django
{% load courses_extras %}<div class="scroll-x" data-scroll-x><div class="multigrid-scroll">{% render_multigrid el values verdicts=verdicts copy=copy %}</div></div>
```

- [ ] **Step 4: Restructure both grid templates + set the flags**

`choicegridquestionelement.html`:

```django
{% load i18n %}
{% comment %}Quiz answer reveal PR 2 (spec 2026-09-25 §2.2-§2.4, §4, §5a): the
controls include (scroll wrappers + table) renders once per copy; the key copy's
radios lose their row_<pk> names in the keycopy pass, so they never join the
student's radio group. data-question-inline is unconditional (lesson D13 + quiz).{% endcomment %}
<div class="el el--question el--choicegrid" data-question>
  {% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}
  {% if mode == "results" %}
  <div class="question__form" data-answer-scope>
    <fieldset data-answer-yours disabled style="border:0;padding:0;margin:0;">
      {% include "courses/elements/_choicegridquestionelement_controls.html" with values=submitted_values %}
    </fieldset>
    {% if key_copy_html %}<div class="answer-key" data-answer-key>{{ key_copy_html }}</div>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <div class="question__feedback" data-question-feedback>{{ feedback_html|safe }}</div>
  </div>
  {% elif element %}
  <form class="question__form" method="post" action="{{ action_url }}" data-question-inline data-answer-scope>
    {% csrf_token %}
    <fieldset data-answer-yours {% if quiz_submitted or locked %}disabled{% endif %}
              style="border:0;padding:0;margin:0;">
      {% if element.pk == feedback_for_pk %}
        {% include "courses/elements/_choicegridquestionelement_controls.html" with values=submitted_values %}
      {% else %}
        {% include "courses/elements/_choicegridquestionelement_controls.html" with values=None verdicts=None %}
      {% endif %}
    </fieldset>
    {% if key_copy_html %}<div class="answer-key" data-answer-key>{{ key_copy_html }}</div>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    {% include "courses/elements/_reveal_button.html" %}
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% else %}
    {% include "courses/elements/_choicegridquestionelement_controls.html" with values=None verdicts=None %}
  {% endif %}
</div>
```

`multigridquestionelement.html`: identical but for `el--multigrid` and the `_multigridquestionelement_controls.html` include.

In `courses/models.py`, on both grids, directly after `RESTORABLE_IN_LESSON = True`:

```python
    # Lesson (spec 2026-09-25 §5a, D13): rows painted in place; the list is gone.
    INLINE_LESSON_FEEDBACK = True

    SUPPORTS_REVEAL = True
    CONTROLS_TEMPLATE = "courses/elements/_choicegridquestionelement_controls.html"
```

(`_multigridquestionelement_controls.html` on `MultiGridQuestionElement`.)

- [ ] **Step 5: Run the new tests, then the suites that pin the old grid behaviour; rewrite under the same rules**

Run: `uv run pytest tests/test_quiz_reveal_pr2_grids.py tests/test_quiz_reveal_pr2_flow.py -p no:randomly`
Expected: PASS.

Then run: `uv run pytest tests/test_reveal_choicegrid.py tests/test_render_choicegrid.py tests/test_render_multigrid.py tests/test_context_choicegrid.py tests/test_context_multigrid.py tests/test_choicegrid_styles.py tests/test_grid_questions_nesting.py tests/test_quiz_noleak.py tests/test_quiz_resume.py tests/test_quiz_reveal_flow.py tests/test_quiz_reveal_results.py tests/test_analytics_student_quiz.py tests/test_answer_summary.py courses/tests/test_nested_question_gates.py courses/tests/test_question_restore.py courses/tests/test_spoiler_nesting.py -p no:randomly`

Expected RED only under Task 3 Step 5's rules (a)–(d), (f), (g) applied to the grids (`_reveal_choicegrid` / `_reveal_multigrid` instead of the drag lists; `row.rendered` for results); rule (e) does not apply to grids. Rewrite each with the `# PR 2 (spec …): replaces …` comment; anything else RED is a bug here. The plan-time catalogue found NO non-e2e grid test that breaks (the grid e2e ones are Task 5's); `courses/tests/test_question_restore.py`'s radio pins (`value="<pk>" checked`) must stay green UNEDITED — if one goes RED, the `aria-invalid` placement from Task 2 is wrong. `tests/test_reveal_choicegrid.py` renders `_reveal_choicegrid.html` directly and stays as it is (the template is deleted, if at all, in PR 3).

- [ ] **Step 6: Lint and commit**

```bash
# <rewritten> = every existing test file this task rewrote (Step 5)
uv run ruff check --no-cache --fix courses/models.py tests/test_quiz_reveal_pr2_flow.py tests/test_quiz_reveal_pr2_grids.py <rewritten> && uv run ruff format --no-cache courses/models.py tests/test_quiz_reveal_pr2_flow.py tests/test_quiz_reveal_pr2_grids.py <rewritten> && uv run ruff check --no-cache courses/models.py tests/test_quiz_reveal_pr2_flow.py tests/test_quiz_reveal_pr2_grids.py <rewritten>
git add courses/models.py templates/courses/elements tests/
git commit -m "feat(quiz-reveal): choice grid + multi grid converted (quiz, results, lessons)"
```

---

### Task 5: The client side — dnd.js, the three swap sites, the results page, verdict CSS

**Files:**
- Modify: `courses/static/courses/js/dnd.js`
- Modify: `courses/static/courses/js/quiz.js`, `question.js`, `editor.js`
- Modify: `templates/courses/quiz_results.html`
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_e2e_quiz_reveal_pr2.py` (new)

**Interfaces:**
- Consumes: Tasks 3–4 markup: one `[data-dnd]` root per copy inside the form / results scope; key-copy selects nameless, `disabled`, with `data-slot`; the student's locked controls disabled through their fieldset; painted selects / rows carry `is-correct` / `is-incorrect`.
- Produces: `window.libliEnhanceDnd(root)` (unchanged name) builds, per root: live chips + targets when the root's selects are enabled; an **inert** display-only UI when any of them matches `:disabled` or the root sits inside `[data-answer-key]`; slots / overlay targets copy their select's verdict class. quiz.js / question.js / editor.js (try-it) call `libliEnhanceDnd` and `libliInitScrollAffordance` on the swapped form.

- [ ] **Step 1: Write the failing e2e tests**

```python
# tests/test_e2e_quiz_reveal_pr2.py
"""Playwright: the PR 2 types in the browser (spec 2026-09-25 §2.2 inert drag UI,
§2.4 re-enhancing after a swap, §4 results, §5a lessons)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug, kinds, unit_type="quiz", max_attempts=2):
    from django.contrib.auth import get_user_model

    from courses.models import Element
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.reveal_pr2_kit import build

    user = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug)
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type, parent=None, title="Q")
    kits = []
    for kind in kinds:
        kit = build(kind, max_attempts=max_attempts)
        Element.objects.create(unit=unit, content_object=kit.question)
        kits.append(kit)
    return course, unit, kits


def _quiz_url(live_server, course, unit):
    return f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"


def _size_stages(page):
    """MediaAssetFactory's file is not served, so the stage <img> collapses to 0px
    and every overlay target sits at one point (tests/test_e2e_questions_2dii.py
    explains the same trap). A page-level stylesheet sizes EVERY stage -- the one
    a Check swaps in and the key copy's second stage included -- so, unlike a
    one-off inline-style fix, it survives each form swap. Presentation only."""
    page.add_style_tag(
        content="[data-dragimage-stage]{display:block!important;width:400px!important;"
        "height:300px!important}[data-dragimage-stage] .dragimage__img"
        "{width:400px!important;height:300px!important}"
    )


def _drag(q, token, slot_index):
    """Tap-assign: arm the chip, then tap the n-th live slot / target."""
    q.locator("[data-answer-yours] .dnd__chip", has_text=token).first.click()
    q.locator("[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target").nth(slot_index).click()


def _check(q):
    q.locator("button[type='submit']:not([name='reveal'])").click()


def _drop(target, token="gammadis"):
    """A synthetic drop straight onto a slot / overlay target (spec §2.2: "tapping
    / dragging a chip ... leaves every select unchanged"). Dispatched in the page,
    so none of Playwright's pointer-event traps apply."""
    target.evaluate(
        """(el, tok) => {
            const dt = new DataTransfer();
            dt.setData("text/plain", tok);
            el.dispatchEvent(new DragEvent("drop", {dataTransfer: dt, bubbles: true, cancelable: true}));
        }""",
        token,
    )


def _select_values(q, scope):
    return q.locator(f"{scope} select").evaluate_all("els => els.map(e => e.value)")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["dragfill", "matchpair", "dragimage"])
def test_drag_quiz_check_reveal_inert_copies(browser, live_server, kind):
    _student(f"d_{kind}")
    course, unit, _ = _seed(f"d_{kind}", f"e2e-d-{kind}", [kind])
    page = browser.new_context().new_page()
    _login(page, live_server, f"d_{kind}")
    page.goto(_quiz_url(live_server, course, unit))
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-question]").first
    _drag(q, "alphakey", 0)
    _drag(q, "gammadis", 1)
    _check(q)
    q.locator(".question__verdict.is-partial").wait_for(timeout=6000)
    # Spec §2.4: the swapped form is a NEW dnd root -- chips must be rebuilt.
    assert q.locator("[data-answer-yours] .dnd__chip").count() >= 3
    targets = q.locator("[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target")
    assert "is-correct" in targets.nth(0).get_attribute("class")
    assert "is-incorrect" in targets.nth(1).get_attribute("class")
    paint = "el => getComputedStyle(el).backgroundColor"
    assert targets.nth(0).evaluate(paint) != targets.nth(1).evaluate(paint)
    # Spec §1.2: the colour stays until the NEXT Check -- re-filling the green part
    # (here with the wrong chip, then back) does not repaint it.
    _drag(q, "gammadis", 0)
    assert _select_values(q, "[data-answer-yours]")[0] == "gammadis"  # the rebuilt UI is LIVE
    assert "is-correct" in targets.nth(0).get_attribute("class")
    _drag(q, "alphakey", 0)
    assert _select_values(q, "[data-answer-yours]")[0] == "alphakey"
    if kind == "dragimage":
        # dnd.js hides the zone rows (and their .sr-only verdicts): each painted
        # overlay target must carry its own non-colour cue (spec §2.1).
        after = "t => (t.nextElementSibling || {}).textContent"
        assert targets.nth(1).evaluate(after) == "incorrect"
        assert targets.nth(1).inner_text().strip() == "gammadis"  # text unchanged
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    # Locked "Your answer": tapping a chip then a filled target changes nothing.
    before = _select_values(q, "[data-answer-yours]")
    q.locator("[data-answer-yours] .dnd__chip").first.click(force=True)
    q.locator("[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target").nth(0).click(force=True)
    _drop(q.locator("[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target").nth(0))
    assert _select_values(q, "[data-answer-yours]") == before
    # The key copy: built by dnd.js (select[data-slot]), inert, showing the key.
    q.locator("label:has([data-answer-view='key'])").click()
    key_targets = q.locator("[data-answer-key] .dnd__slot, [data-answer-key] .dragimage__target")
    assert key_targets.nth(1).inner_text().strip() == "betakey"
    key_chips = q.locator("[data-answer-key] .dnd__chip")
    assert key_chips.count() >= 3  # [].every() is true: prove the pool was built
    assert key_chips.evaluate_all("cs => cs.every(c => c.disabled)")
    key_before = _select_values(q, "[data-answer-key]")
    key_targets.nth(1).click(force=True)
    _drop(key_targets.nth(1), "alphakey")
    assert _select_values(q, "[data-answer-key]") == key_before == ["alphakey", "betakey"]
    # Spec §2.2: a locked "Your answer" on RESUME is inert too -- no script froze it,
    # only the server's disabled fieldset does.
    page.reload()
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-question]").first
    before = _select_values(q, "[data-answer-yours]")
    live = q.locator("[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target").nth(0)
    live.click(force=True)
    _drop(live)
    assert _select_values(q, "[data-answer-yours]") == before


@pytest.mark.django_db(transaction=True)
def test_multi_paragraph_drag_stem_keeps_its_spacing_in_both_copies(browser, live_server):
    # The stem's <p>s now sit under .question__stem > [data-dnd]; the prose-rhythm
    # rule must reach through that root, in "Your answer" and in the key copy.
    from courses.fillblank import parse

    _student("d_par")
    course, unit, (kit,) = _seed("d_par", "e2e-d-par", ["dragfill"], max_attempts=1)
    q_model = kit.question
    q_model.stem = parse("<p>One {{alphakey}}.</p><p>Two {{betakey}}.</p>")[0]
    q_model.save()
    page = browser.new_context().new_page()
    _login(page, live_server, "d_par")
    page.goto(_quiz_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    _drag(q, "gammadis", 1)
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)  # 1 attempt: locked
    gap = "p => getComputedStyle(p).marginTop"
    assert q.locator("[data-answer-yours] [data-dnd] > p").nth(1).evaluate(gap) != "0px"
    q.locator("label:has([data-answer-view='key'])").click()
    assert q.locator("[data-answer-key] [data-dnd] > p").nth(1).evaluate(gap) != "0px"


@pytest.mark.django_db(transaction=True)
def test_check_on_one_drag_question_leaves_the_other_alone(browser, live_server):
    _student("d_two")
    course, unit, _ = _seed("d_two", "e2e-d-two", ["dragfill", "matchpair"])
    page = browser.new_context().new_page()
    _login(page, live_server, "d_two")
    page.goto(_quiz_url(live_server, course, unit))
    first, second = page.locator("[data-question]").nth(0), page.locator("[data-question]").nth(1)
    chips_before = second.locator(".dnd__chip").count()
    slots_before = second.locator(".dnd__slot").count()
    _drag(first, "alphakey", 0)
    _check(first)
    first.locator("[data-question-feedback] .question__verdict").wait_for(timeout=6000)
    assert second.locator(".dnd__chip").count() == chips_before
    assert second.locator(".dnd__slot").count() == slots_before


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["choicegrid", "multigrid"])
def test_grid_lock_keeps_the_students_pick_and_paints_rows(browser, live_server, kind):
    _student(f"g_{kind}")
    course, unit, (kit,) = _seed(f"g_{kind}", f"e2e-g-{kind}", [kind], max_attempts=1)
    page = browser.new_context().new_page()
    _login(page, live_server, f"g_{kind}")
    page.goto(_quiz_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    rows = q.locator("[data-answer-yours] tbody tr")
    rows.nth(0).locator("input").nth(0).check()
    rows.nth(1).locator("input").nth(0).check()  # wrong for row 2 in both kits
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)  # 1 attempt: locked
    rows = q.locator("[data-answer-yours] tbody tr")
    assert rows.nth(1).locator("input").nth(0).is_checked()  # the key copy did not steal it
    # The swapped-in scroll wrapper is wired again (scroll_affordance.js marks it).
    wrap = q.locator("[data-answer-yours] [data-scroll-x]")
    assert wrap.get_attribute("data-scroll-x-ready") == "1"
    stmt = "tr => getComputedStyle(tr.querySelector('td')).backgroundColor"
    assert rows.nth(0).evaluate(stmt) != rows.nth(1).evaluate(stmt)
    q.locator("label:has([data-answer-view='key'])").click()
    key_row2 = q.locator("[data-answer-key] tbody tr").nth(1)
    assert key_row2.locator("input").nth(1).is_checked()
    assert q.locator("[data-answer-view='yours']").is_enabled()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["dragfill", "matchpair", "dragimage", "choicegrid", "multigrid"])
def test_lesson_check_repaints_and_rebuilds(browser, live_server, kind):
    # Spec §2.4 / §5a: question.js re-enhances every drag type after its swap
    # (drag onto image goes through the separate overlay builder).
    _student(f"l_{kind}")
    course, unit, _ = _seed(f"l_{kind}", f"e2e-l-{kind}", [kind], unit_type="lesson")
    page = browser.new_context().new_page()
    _login(page, live_server, f"l_{kind}")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-question]").first
    if kind in ("choicegrid", "multigrid"):
        q.locator("tbody tr").nth(0).locator("input").nth(0).check()
        q.locator("tbody tr").nth(1).locator("input").nth(0).check()
    else:
        _drag(q, "alphakey", 0)
        _drag(q, "gammadis", 1)
    _check(q)
    q.locator(".question__verdict").wait_for(timeout=6000)
    if kind in ("choicegrid", "multigrid"):
        assert "is-incorrect" in q.locator("tbody tr").nth(1).get_attribute("class")
        # question.js re-wired the swapped-in scroll wrapper.
        assert q.locator("[data-scroll-x]").get_attribute("data-scroll-x-ready") == "1"
    else:
        assert q.locator(".dnd__chip").count() >= 3  # question.js re-enhanced
        targets = q.locator(".dnd__slot, .dragimage__target")
        assert "is-incorrect" in targets.nth(1).get_attribute("class")
        if kind == "dragimage":
            after = "t => (t.nextElementSibling || {}).textContent"
            assert targets.nth(1).evaluate(after) == "incorrect"
    assert q.locator("[data-answer-key], [data-answer-switch], [data-reveal-btn]").count() == 0


@pytest.mark.django_db(transaction=True)
def test_results_page_drag_ui_is_inert(browser, live_server):
    _student("d_res")
    course, unit, _ = _seed("d_res", "e2e-d-res", ["dragfill"], max_attempts=1)
    page = browser.new_context().new_page()
    _login(page, live_server, "d_res")
    page.goto(_quiz_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    _drag(q, "gammadis", 1)
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/results/**")
    row = page.locator(".quiz-results__item").first
    assert row.locator("[data-answer-yours] .dnd__slot").count() == 2  # dnd.js loaded
    before = _select_values(row, "[data-answer-yours]")
    row.locator("[data-answer-yours] .dnd__slot").nth(1).click(force=True)
    _drop(row.locator("[data-answer-yours] .dnd__slot").nth(1), "alphakey")
    assert _select_values(row, "[data-answer-yours]") == before
    switch = row.locator("[data-answer-switch]")
    pos = switch.bounding_box()
    row.locator("label:has([data-answer-view='key'])").click()
    assert row.locator("[data-answer-key] .dnd__slot").nth(1).inner_text().strip() == "betakey"
    after = switch.bounding_box()
    assert (after["x"], after["y"]) == (pos["x"], pos["y"])  # P5: the switch stays


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("unit_type", ["quiz", "lesson"])
@pytest.mark.parametrize("kind", ["dragfill", "matchpair", "dragimage", "choicegrid"])
def test_editor_try_it_rebuilds_the_controls(browser, live_server, kind, unit_type):
    # Spec §2.4: editor.js's try-it branch re-enhances drag roots and re-wires grid
    # scroll wrappers after its swap, in quiz and lesson mode.
    from courses.models import Element
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.reveal_pr2_kit import build
    from tests.test_e2e_questions import _editor_url
    from tests.test_e2e_questions import _make_pa_user

    user = f"pa_{kind}_{unit_type}"
    owner = _make_pa_user(user)
    course = CourseFactory(owner=owner, slug=f"e2e-ed-{kind}-{unit_type}")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type, parent=None, title="E")
    kit = build(kind, max_attempts=2)
    Element.objects.create(unit=unit, content_object=kit.question)
    page = browser.new_context().new_page()
    _login(page, live_server, user)
    page.goto(_editor_url(live_server, unit))
    if kind == "dragimage":
        _size_stages(page)
    q = page.locator("[data-scope='preview'] [data-question]").first
    if kind == "choicegrid":
        q.locator("tbody tr").nth(0).locator("input").nth(0).check()
        q.locator("tbody tr").nth(1).locator("input").nth(0).check()
    else:
        _drag(q, "alphakey", 0)
        _drag(q, "gammadis", 1)
    _check(q)
    q.locator(".question__verdict").wait_for(timeout=6000)
    if kind == "choicegrid":
        wrap = q.locator("[data-answer-yours] [data-scroll-x]")
        assert wrap.get_attribute("data-scroll-x-ready") == "1"  # editor.js re-wired
        assert "is-incorrect" in q.locator("[data-answer-yours] tbody tr").nth(1).get_attribute("class")
    else:
        assert q.locator("[data-answer-yours] .dnd__chip").count() >= 3  # re-enhanced
        targets = q.locator("[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target")
        assert "is-incorrect" in targets.nth(1).get_attribute("class")
        if kind == "dragimage":
            after = "t => (t.nextElementSibling || {}).textContent"
            assert targets.nth(1).evaluate(after) == "incorrect"
    if unit_type == "quiz":
        page.once("dialog", lambda d: d.accept())
        q.locator("[data-reveal-btn]").click()
        q.locator("[data-answer-switch]").wait_for(timeout=6000)
        assert q.locator("[data-answer-view='key']").is_enabled()
        if kind != "choicegrid":
            before = _select_values(q, "[data-answer-yours]")
            targets = q.locator("[data-answer-yours] .dnd__slot, [data-answer-yours] .dragimage__target")
            targets.nth(0).click(force=True)
            _drop(targets.nth(0))
            assert _select_values(q, "[data-answer-yours]") == before
```

**Step 1 notes for the executor.** Every drag-onto-image e2e calls `_size_stages(page)` right after `page.goto` — without it the unserved factory image collapses the stage and the target taps time out on a CORRECT build; do not read that timeout as a product bug. The editor test reuses PR 1's author helpers (`tests/test_e2e_questions.py::_make_pa_user`, `_editor_url`), exactly as `tests/test_e2e_quiz_reveal.py::test_editor_try_it_reveal_switch_survives_freeze` does. The lesson URL is `courses:lesson_unit` = `/courses/<slug>/u/<pk>/`. `_drag` taps the chip then the target (dnd.js's tap-assign path) — no pointer drag, see memory `playwright-pointer-event-traps`. The quiz test's dialog handler is registered BEFORE the click (Playwright auto-dismisses a `confirm`, memory `playwright-auto-dismisses-confirm`).

- [ ] **Step 2: Run the e2e tests to verify they fail**

Run: `uv run pytest tests/test_e2e_quiz_reveal_pr2.py -m e2e -p no:randomly`
Expected: FAIL — after the Check the live copy has no `.dnd__chip` (nobody re-enhanced the new root); the locked tap clears a select; the key copy has no slots (`select[name="slot"]` misses `data-slot`); the results page has no slots (dnd.js not loaded); no verdict class on slots.

- [ ] **Step 3: dnd.js**

In `enhance(block)`:

```js
    // The key copy's selects are nameless (spec 2026-09-25 §2.2): data-slot marks them.
    var selects = Array.prototype.slice.call(
      block.querySelectorAll('select[name="slot"], select[data-slot]')
    );
    if (!selects.length) return;
    var pool = block.querySelector("[data-dnd-pool]");
    if (!pool) return;
    // Display-only when the controls are disabled (a locked "Your answer" -- its
    // fieldset is disabled, which `.disabled` does NOT report but :disabled does)
    // or this block is the key copy. No drag, no tap-assign, no keyboard re-show:
    // nothing may change a select (spec §2.2, §4).
    var inert =
      !!block.closest("[data-answer-key]") ||
      selects.some(function (s) { return s.matches(":disabled"); });
```

When `inert`, add `block.classList.add("dnd--inert");` (the CSS hook for the default cursor, Step 5). In the chip loop: when `inert`, set `chip.disabled = true; chip.draggable = false;` and attach **no** listeners (wrap the `dragstart` / `click` listener block in `if (!inert) { … }`).

Pass `inert` into both builders — `buildOverlayTargets(block, stage, selects, tapTarget, inert)` and `buildInlineSlots(selects, tapTarget, inert)` — and in each, when `inert`: set `tabIndex = -1` instead of `0`, and skip the `dragover` / `drop` / `click` / `keydown` listeners (the `change` listener that repaints is harmless; keep it). In both builders, right after the slot / target element is created, copy the select's verdict (plan P2):

```js
      // The verdict is server-rendered on the select (spec §2.1); the visible
      // slot / target wears it too. It stays until the next Check replaces the
      // element (spec §1.2), so it is copied once, never recomputed here.
      ["is-correct", "is-incorrect"].forEach(function (c) {
        if (sel.classList.contains(c)) target.classList.add(c);  // `slot` in buildInlineSlots
      });
```

In `buildOverlayTargets`, directly after `stage.appendChild(target);`, give the target its own non-colour cue — the zone rows holding the select's `.sr-only` verdict are hidden under JS, which removes them from the accessibility tree (spec §2.1):

```js
      // The rows (and the select's .sr-only verdict) are hidden under JS, so the
      // verdict text follows the target. A sibling, never a child: paint() resets
      // the target's textContent, and tests read that text exactly.
      var sr = sel.nextElementSibling;
      if (sr && sr.classList.contains("sr-only")) stage.appendChild(sr.cloneNode(true));
```

Update the file's closing comment above `window.libliEnhanceDnd = init;`: "Exposed so every form-body swap (quiz.js, question.js, editor.js try-it) and the editor's pane swap can enhance the NEW dnd roots a response brings (spec §2.4). enhance() is idempotent via data-dndReady."

- [ ] **Step 4: The three swap sites + the results page**

`quiz.js`, inside `if (newForm) { … }` right after `form.innerHTML = newForm.innerHTML;`:

```js
          // The swap brought NEW dnd roots (spec §2.4). A locked root is inert
          // because the SERVER rendered its fieldset disabled; enhancing before the
          // freeze below means dnd.js's :disabled test reads that server markup, not
          // the freeze's. The grids' new .scroll-x wrappers are wired again too.
          if (window.libliEnhanceDnd) window.libliEnhanceDnd(form);
          if (window.libliInitScrollAffordance) window.libliInitScrollAffordance(form);
```

`question.js`, inside `if (newForm) { … }` right after `form.innerHTML = newForm.innerHTML;`:

```js
              if (window.libliEnhanceDnd) window.libliEnhanceDnd(form);  // spec §5a
              if (window.libliInitScrollAffordance) window.libliInitScrollAffordance(form);
```

`editor.js` try-it branch, inside `if (newForm) { … }` right after `tryForm.innerHTML = newForm.innerHTML;`:

```js
            // New dnd roots / grid scroll wrappers from the swap (spec §2.4);
            // before the freeze below.
            if (window.libliEnhanceDnd) window.libliEnhanceDnd(tryForm);
            if (window.libliInitScrollAffordance) window.libliInitScrollAffordance(tryForm);
```

`templates/courses/quiz_results.html`, in `{% block extra_js %}` after the `{% endif %}` of the `has_math` block:

```django
  {% comment %}Drag types render their (inert) drag UI on the results page (spec §4);
  dnd.js is a no-op on a page without [data-dnd].{% endcomment %}
  <script src="{% static 'courses/js/dnd.js' %}" defer></script>
```

- [ ] **Step 5: Verdict CSS (`courses/static/courses/css/courses.css`)**

Directly after the `.dragimage__target--filled` rule (the end of the drag-to-image block) — NOT next to PR 1's text-input verdicts: `.dragimage__target:hover, .dragimage__target:focus` is (0,2,0) like `.dragimage__target.is-correct`, so the verdict rule must come LATER in the file to keep its border on hover / focus:

```css
/* Drag + grid verdicts (spec 2026-09-25 §2.1, D6; plan P1/P2): the fill-table
   colours on the part itself. Drag: the no-JS select and the dnd.js slot / image
   target (which copies its select's class). Grid: the row's statement cell, with
   an inset bar so a row with nothing picked still reads. Placed after the drag
   blocks: the target's hover / focus border rule has the same specificity and
   loses only by source order; the other bases (select.dnd__select,
   .dragimage__target--filled, the grids' even-row stripe) are out-ranked. */
select.dnd__select.is-correct,
.dnd__slot.is-correct,
.dragimage__target.is-correct { border-color: var(--success); background: var(--success-subtle); }
select.dnd__select.is-incorrect,
.dnd__slot.is-incorrect,
.dragimage__target.is-incorrect { border-color: var(--danger); background: var(--danger-subtle); }
.choicegrid tbody tr.is-correct td.choicegrid__stmt,
.multigrid tbody tr.is-correct td.multigrid__stmt { background: var(--success-subtle); box-shadow: inset 3px 0 0 var(--success); }
.choicegrid tbody tr.is-incorrect td.choicegrid__stmt,
.multigrid tbody tr.is-incorrect td.multigrid__stmt { background: var(--danger-subtle); box-shadow: inset 3px 0 0 var(--danger); }
/* An inert chip / slot / target (locked copy, key copy, results) must not look
   grabbable or tappable; dnd.js adds dnd--inert to the root when inert. */
.dnd__chip:disabled { cursor: default; opacity: .7; }
.dnd--inert .dnd__slot,
.dnd--inert .dragimage__target { cursor: default; }
.dnd__chip:disabled:hover { border-color: var(--border-strong); color: var(--text-primary); }
```

Also extend the **prose-rhythm rule near the top of `courses.css`** (the one whose comment begins "Prose rhythm, applied to the contenteditable…"). Its stem branch is a DIRECT-child selector, and Task 3 moved the drag-the-words stem's `<p>` blocks one level down, under `.question__stem > div[data-dnd]` — without this, a multi-paragraph drag stem loses its paragraph spacing in every copy. Change

```css
.question__stem
  > :is(p, h2, h3, h4, ul, ol, pre, blockquote)
  + :is(p, h2, h3, h4, ul, ol, pre, blockquote) { margin-top: var(--space-3); }
```

to

```css
.question__stem
  > :is(p, h2, h3, h4, ul, ol, pre, blockquote)
  + :is(p, h2, h3, h4, ul, ol, pre, blockquote),
.question__stem > [data-dnd]
  > :is(p, h2, h3, h4, ul, ol, pre, blockquote)
  + :is(p, h2, h3, h4, ul, ol, pre, blockquote) { margin-top: var(--space-3); }
```

and append one sentence to that comment: "A drag-the-words stem sits one level down, inside its per-copy [data-dnd] root (quiz answer reveal PR 2), so the stem branch reaches through it." Do NOT put `question__stem` on the `[data-dnd]` div instead: `.el--question .question__stem`'s margin-bottom would then land inside the fieldset and move the switch (P5).

- [ ] **Step 6: Run the e2e tests + PR 1's e2e + the dnd / grid e2e suites**

Run: `uv run pytest tests/test_e2e_quiz_reveal_pr2.py tests/test_e2e_quiz_reveal.py tests/test_e2e_questions_2d.py tests/test_e2e_questions_2dii.py tests/test_e2e_questions_2diii.py tests/test_e2e_matchpair_rows.py tests/test_e2e_choicegrid.py tests/test_e2e_multigrid.py tests/test_e2e_widget_restore.py tests/test_e2e_uniform_block_width.py tests/test_e2e_scroll_affordance.py tests/test_e2e_wide_content_scroll.py -m e2e -p no:randomly`
Expected: PASS after these known rewrites (Task 3 Step 5's rules, with the comment):

| Test | Old assertion | Rule → rewrite to |
|---|---|---|
| `test_e2e_questions_2d.py::test_dragfill_quiz_withhold_reveal_resume_js` | feedback `to_contain_text("Correct token:")` | (c) → `[data-answer-switch]` appears; after clicking the "Correct answer" label the key copy's second `.dnd__slot` has the key token |
| `test_e2e_questions_2dii.py::test_dragimage_quiz_withhold_then_reveal_js` | `"Correct label:" in revealed` (+ vacuous `"Heart" in revealed and "Lung" in revealed`) | (c) → the key copy's `.dragimage__target`s read `Heart` / `Lung` |
| `test_e2e_questions_2dii.py::test_dragimage_katex_in_chip_and_reveal` | `.question__reveal .katex` exists | (c) → after selecting "Correct answer", `[data-answer-key] .dragimage__target .katex` count ≥ 1 |
| `test_e2e_choicegrid.py::test_matrix_lesson_immediate_feedback` | `.question__reveal--grid` with `.answer-correct` / `.answer-wrong` / `"False"` | (b) → `tbody tr` 1 has `is-correct`, row 2 `is-incorrect`; no `.question__reveal` |
| `test_e2e_choicegrid.py::test_matrix_quiz_withhold_then_results` | results `.question__reveal--grid`, `"True"` / `"False"`, 2 × `.answer-wrong` | (d) → the results row has `[data-answer-switch]`; both `tbody tr` of `[data-answer-yours]` are `is-incorrect`; the key copy's checked radios are the correct columns |
| `test_e2e_multigrid.py::test_multigrid_lesson_immediate_feedback` | `.question__reveal--grid` counts, `"B" in reveal` | (b) → row classes as for the matrix |

Then the non-e2e CSS guards over this task's `courses.css` edit (a stray `*/` in a comment silently eats the next rule): `uv run pytest tests/test_css_comments_are_terminated_once.py tests/test_css_citations_are_durable.py tests/test_choicegrid_styles.py tests/test_text_colour_css.py tests/test_border_contrast_css.py -p no:randomly` — PASS.

Also — still GREEN but now vacuous, because a painted select / slot / target also carries `is-correct` (P2): `tests/test_e2e_questions_2d.py` lines ~112, 132, 292, 309 and `tests/test_e2e_questions_2dii.py` lines ~205, 280, 359 assert `page.locator(".is-correct").count() >= 1` (or `result_page.…`). Scope each to `.question__verdict.is-correct` (find them with `grep -n '"\.is-correct"' tests/test_e2e_questions_2d*.py`), with the replaces-comment.

Update the stale module / helper docstrings of `test_e2e_choicegrid.py` and `test_e2e_multigrid.py` that describe the list. `test_e2e_widget_restore.py`'s `to_have_text("Heart")` etc. must stay green unedited (the `.sr-only` verdict sits AFTER the select, never inside a slot / target). If a Playwright test fails as a TIMEOUT, first rule out a stale service worker and parallel load (memory: `stale-service-worker-serves-old-static`, `e2e-flakes-under-parallel-load`).

- [ ] **Step 7: Commit**

```bash
# <rewritten> = every existing e2e file Step 6 rewrote
uv run ruff check --no-cache --fix tests/test_e2e_quiz_reveal_pr2.py <rewritten> && uv run ruff format --no-cache tests/test_e2e_quiz_reveal_pr2.py <rewritten> && uv run ruff check --no-cache tests/test_e2e_quiz_reveal_pr2.py <rewritten>
git add courses/static/courses/js courses/static/courses/css/courses.css templates/courses/quiz_results.html tests/
git commit -m "feat(quiz-reveal): inert drag UI, re-enhance after every swap, drag + grid verdict colours"
```

---

### Task 6: Translations check + author help

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `django.mo` (only if Step 1 finds a new msgid)
- Modify: `docs/help/course-admin/quiz-editors.md`, `docs/help/course-admin/quiz-editors.pl.md`

PR 2 adds **no new UI string** by design (the verdict text reuses PR 1's `pgettext("answer part verdict", …)`). Spec §8 still requires the i18n step, so it is run to prove that.

- [ ] **Step 1: Extract and verify**

```bash
uv run python manage.py makemessages -l pl --no-obsolete
git diff --stat locale/
git diff locale/pl/LC_MESSAGES/django.po | tr -d '\r' | grep -E '^[+-](msgid|msgstr|#, fuzzy)' || echo "no msgid changes"
```

Expected: `no msgid changes` (only `#:` reference lines moved). If a new msgid did appear, translate it (clear any `#, fuzzy` pre-fill — both the flag and its wrong msgstr), run `uv run python manage.py compilemessages -l pl`, and list it in the PR description. Keep the `.po` reference-line drift in the commit either way.

- [ ] **Step 2: Help text**

In BOTH help files, append one paragraph at the end of each of these five sections (locate with `grep -n "^## {el:" docs/help/course-admin/quiz-editors*.md`): `{el:dragwords}` (Drag the words / Przeciągnij słowa), `{el:matchpairs}` (Match pairs / Dopasuj pary), the first `{el:switchgrid}` (Matrix question / Pytanie macierzowe), the second `{el:switchgrid}` (Multi-select grid / Siatka wielokrotnego wyboru), `{el:dragimage}` (Drag to image / Przeciągnij na obraz):

- EN, drag the words / drag to image: "In a **lesson**, checking an answer turns each gap green (right) or red (wrong) in place; the correct answers are not shown." (drag to image: "each zone" for "each gap")
- EN, match pairs: "In a **lesson**, checking an answer turns each pair green (right) or red (wrong) in place; the correct answers are not shown."
- EN, both grids: "In a **lesson**, checking an answer turns each row green (right) or red (wrong) in place; the correct answers are not shown."
- PL, luki: "W **lekcji** po sprawdzeniu odpowiedzi każda luka zmienia kolor na zielony (dobrze) lub czerwony (źle); poprawne odpowiedzi nie są pokazywane." (obraz: "każde pole", pary: "każda para", siatki: "każdy wiersz")
- Every paragraph above then ends with fill in the blanks' authoring tip (D11: "an author can add a spoiler"), verbatim from its master paragraph — EN: "If you want students to be able to look them up, put them in a Spoiler under the question."; PL: "Jeśli uczniowie mają móc je podejrzeć, umieść je w elemencie Rozwijana treść pod pytaniem."

The quiz behaviour needs no per-type text: PR 1's type-agnostic "In a **quiz**, …" paragraph above the first question section already covers it (spec §8). Flag the Polish help text for the owner's review in the PR description.

- [ ] **Step 3: Run the help and i18n suites**

Run: `uv run pytest tests/test_i18n_quiz_reveal.py tests/test_help.py tests/test_help_capture_isolation.py -p no:randomly`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add locale docs/help
git commit -m "docs(quiz-reveal): lesson in-place feedback for drag, match, image and grid types"
```

---

### Task 7: Branch gate — mutants, screenshots, full sweep

**Files:** none new (fixes only, if the gate finds something).

- [ ] **Step 1: Mutants (each must turn a test RED; revert every mutant BY HAND, then `git diff` must be empty)**

| Mutant | Must fail |
|---|---|
| `dnd.js`: selector back to `select[name="slot"]` only | `test_drag_quiz_check_reveal_inert_copies` (key copy has no slots), `test_results_page_drag_ui_is_inert` |
| `dnd.js`: `inert = false` always | `test_drag_quiz_check_reveal_inert_copies` (locked tap clears a select), `test_results_page_drag_ui_is_inert`, `test_editor_try_it_rebuilds_the_controls` (every drag kind, quiz) |
| `dnd.js`: inert test `s.disabled` instead of `s.matches(":disabled")` | `test_drag_quiz_check_reveal_inert_copies` (the fieldset-disabled "Your answer" goes live) |
| `dnd.js`: drop the verdict-class copy | `test_drag_quiz_check_reveal_inert_copies`, `test_lesson_check_repaints_and_rebuilds[matchpair]` |
| `quiz.js`: drop the `libliEnhanceDnd(form)` call | `test_drag_quiz_check_reveal_inert_copies` |
| `question.js`: drop the `libliEnhanceDnd(form)` call | `test_lesson_check_repaints_and_rebuilds` (every drag kind) |
| `editor.js`: drop the try-it `libliEnhanceDnd(tryForm)` call | `test_editor_try_it_rebuilds_the_controls` |
| `quiz.js`: drop the `libliInitScrollAffordance(form)` call | `test_grid_lock_keeps_the_students_pick_and_paints_rows` |
| `dnd.js`: drop the overlay target's `.sr-only` clone | `test_drag_quiz_check_reveal_inert_copies[dragimage]` |
| COMBINED: `quiz.js` calls `window.libliEnhanceDnd()` (whole document) AND `enhance()` loses its `dndReady` guard | `test_check_on_one_drag_question_leaves_the_other_alone` (the second question's chips double); either change alone is masked by the other |
| `courses.css`: drop the drag + grid verdict colour block | `test_drag_quiz_check_reveal_inert_copies` (computed background), `test_grid_lock_keeps_the_students_pick_and_paints_rows` |
| `courses.css`: drop the new `.question__stem > [data-dnd] > …` prose-rhythm branch | `test_multi_paragraph_drag_stem_keeps_its_spacing_in_both_copies` |
| `dragfillblankquestionelement.html`: drop `style="margin:0;"` from the key-copy wrapper (both occurrences) | `test_results_page_drag_ui_is_inert` (the switch moves on toggle); if it survives, fix that test before recording the mutant |
| `quiz_results.html`: drop the dnd.js script | `test_results_page_drag_ui_is_inert` |
| `dragfillblankquestionelement.html`: put `data-dnd` back on the outer div as well | `test_each_copy_is_its_own_dnd_root` |
| `courses/verdicts.py`: `part_verdict` ignores `key` | `test_key_paints_every_gap_correct`, `test_locked_wrong_shows_a_neutralised_painted_key_copy` |
| `courses/verdicts.py`: `invalid_attr` returns `""` | `test_render_selects_paints_each_gap_with_both_cues`, `test_grid_rows_paint_with_both_cues`, `test_cues_on_every_painted_part` |
| `_grid_row_cells`: drop the `invalid` placeholder (grid inputs lose aria-invalid) | `test_grid_rows_paint_with_both_cues[choicegrid]` |
| `_multigrid_row_cells`: drop the `invalid` placeholder | `test_grid_rows_paint_with_both_cues[multigrid]` |
| `dnd.js`: inert builders keep the `drop` listener (only `click` skipped) | `test_drag_quiz_check_reveal_inert_copies`, `test_results_page_drag_ui_is_inert` |
| `editor.js`: drop the try-it `libliInitScrollAffordance(tryForm)` call | `test_editor_try_it_rebuilds_the_controls` (choicegrid, both unit types) |
| `question.js`: drop the `libliInitScrollAffordance(form)` call | `test_lesson_check_repaints_and_rebuilds[choicegrid]` |
| `MatchPairQuestionElement`: `SUPPORTS_REVEAL = False` | `test_check_answers_whole_element_painted_no_key[matchpair]`, `test_locked_wrong_shows_a_neutralised_painted_key_copy[matchpair]` |
| `ChoiceGridQuestionElement`: `INLINE_LESSON_FEEDBACK = False` | `test_lesson_fetch_check_paints_in_place_no_list[choicegrid]` |
| `ChoiceGridQuestionElement.key_answer`: `return None` | `test_key_answer_is_build_answer_of_the_right_post[choicegrid]`, `test_locked_wrong_shows_a_neutralised_painted_key_copy[choicegrid]` |
| `dragtoimagequestionelement.html` results branch: fieldset without `disabled` | `test_results_render_each_question_read_only[dragimage]` |
| `render()` (models.py): drop the `element.pk == feedback_for_pk` guard | `test_nojs_lesson_check_leaves_a_sibling_of_another_type_unpainted` (a 500 or a painted sibling) |

Record each mutant's RED test name in the PR description; a survivor is either killed by a new test or listed with the reason.

- [ ] **Step 2: Screenshots**

Write a throwaway e2e in `tests/test_e2e_zz_shot_tmp.py` (set `DJANGO_ALLOW_ASYNC_UNSAFE`; set `user.theme` to `"light"`/`"dark"` — the cookie is not enough, memory `dialog-does-not-inherit-the-page-theme`) capturing, for one drag type AND one grid: the partial Check (painted), the locked state on "Your answer", on "Correct answer", a lesson wrong Check, and the results row — with the drag-the-words question's stem set to TWO paragraphs (the kit's stem is one sentence and would hide a spacing regression). Plus drag onto image locked on both switch sides. Read each PNG; judge dark mode separately (memory `verify-ui-with-screenshots`). Delete the file.

- [ ] **Step 3: Full sweep (the branch gate)**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run ruff check --no-cache . && uv run ruff format --check --no-cache .
uv run python manage.py makemigrations --check --dry-run
```

Run the non-e2e suite in ~4 chunks (one run at a time), then the e2e suite in chunks with `-m e2e`. Grep each run's summary line; do not trust the exit code alone (memory `pytest-exit-code-can-lie`, `full-suite-run-is-oom-killed`).

- [ ] **Step 4: Re-sync with master**

```bash
git fetch origin && git rebase origin/master
uv run python manage.py makemessages -l pl --no-obsolete && uv run python manage.py compilemessages -l pl
```

Regenerate the `.mo` rather than resolving a binary conflict. If `git status` then shows `locale/` changes, commit them (`git add locale && git commit -m "i18n: regenerate catalog after rebase"`). Re-run the four `tests/test_quiz_reveal_pr2_*.py` files after the rebase, plus `uv run pytest tests/test_e2e_quiz_reveal_pr2.py -m e2e -p no:randomly` (the JS / CSS this PR edits are the likeliest silent merges), plus Task 5 Step 6's CSS guard suites if the rebase touched `courses.css`.

- [ ] **Step 5: Commit gate fixes; stop before pushing**

Commit any fix. **Do not push or open the PR** until the owner has seen the screenshots and the plan-time decisions P1–P5. PR description then: summary, the D1–D13 reference, P1–P5, the mutant table, screenshots note, "Please check the Polish help text".

---

## Self-review notes (for the executor)

- **Spec coverage (PR 2 scope):** §2.1 part verdicts + both cues → Tasks 1, 2 (+ grid P1); §2.2 key answers → 1, key copy (nameless, disabled, `data-slot`, grid radios `row_<pk>` stripped) → 3, 4 via PR 1's `render_key_copy`; empty keys → 1; inert drag UI → 5; §2.3 switch → 3, 4 (PR 1 partial); §2.4 whole-element responses → 3, 4 (flag-driven views), dnd roots per copy → 3, the three swap sites → 5, resume / no-JS / previewer / editor → 3; §2.6 stored vs fresh → 1, 4; §3 Show answer → 3 (flag-driven); §4 results page read-only + dnd.js → 3, 4, 5; §5 analytics → 3; §5a lessons (flag, `data-question-inline`, question.js re-enhance, nested grids, sibling guard) → 3, 4, 5; §7 no-leak / verdicts on every path / e2e / mutants → 3, 4, 5, 7; §8 PR 2 i18n + help → 6.
- **Out of PR 2 (do not do):** choice / extended response conversion, deleting any `_reveal_*.html` (PR 3's clean-up — analytics still includes them), help screenshots.
- If a task's snippet disagrees with the file at execution time (drift, a renamed helper), the SPEC wins over the snippet; stop and report if they conflict on behaviour.
