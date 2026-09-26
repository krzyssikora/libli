# Quiz answer reveal — PR 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert multiple choice and extended response to the quiz answer reveal — choice marks the student's picks ✓/✗ from the first Check (＋ only once locked), both get Show answer and the results-page render — then delete the `_reveal_*.html` answer lists no path reaches any more.

**Architecture:** PR 1 (#348) and PR 2 (#349, master `b1dde810`) left the views flag-driven: `SUPPORTS_REVEAL` routes a type through `can_reveal`, the whole-element responses and `render(mode="results")`; `quiz_render_state` already calls `part_verdicts` for every answered AUTO question. Choice keeps its own `render()` and its combined ✓ ✗ ＋ view (D8): PR 3 gives it a `part_verdicts` pinned to the picked options only, teaches `choice_marks` to paint from those verdicts while unlocked, and adds the Show answer button and a results branch to its template. Extended response keeps its keyword block as its view (D7): it gains the flag, the button, a results branch, and one new helper (`courses.quiz.reveal_list_template`) so its keyword block survives the flag — in the live feedback and in the results feedback fragment. The clean-up deletes the nine answer lists of converted types and their `REVEAL_TEMPLATE` constants; `_reveal_extendedresponse.html` and `_reveal_button.html` stay.

**Tech Stack:** Django 5 templates, Python 3.13, PostgreSQL, vanilla JS (quiz.js, question.js, editor.js — no JS change is expected), pytest + pytest-django + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-quiz-answer-reveal-design.md` (owner decisions D1–D13 are VERBATIM intent — never reverse one). This plan is **PR 3 of 3** (spec §8 item 3). The PR 1 / PR 2 plans are history — where they and the code disagree, the code on master is what PR 3 builds on.

## Global Constraints

- Owner decisions D1–D13 in the spec are verbatim; a task that seems to need reversing one STOPS and asks. In particular: choice keeps its combined ✓ ✗ ＋ view with **no switch** (D8) and stays **all-or-nothing** (D9); extended response keeps its **keyword view** (D7); **lessons are unchanged** for both types (D11, §5a "Extended response and multiple choice are unchanged in lessons").
- **Scope = spec §8 PR 3:** `ChoiceQuestionElement` and `ExtendedResponseQuestionElement`, plus the `_reveal_*` template clean-up. After PR 3, `SUPPORTS_REVEAL = True` on all ten question types; `INLINE_LESSON_FEEDBACK` stays exactly as on master (every type except extended response).
- Both types keep `key_answer() = None` (base) — never a key copy, never a switch, never `CONTROLS_TEMPLATE` (spec §2.2). Extended response keeps `part_verdicts() = None` (base).
- **Choice's `part_verdicts` is pinned (spec §2.1):** one entry per option in option order — `True` / `False` for a PICKED option, `None` for an unpicked one. Before the lock, nothing on an unpicked option may differ from its pre-Check markup: no marker, no class, no attribute, no feedback text; `mark_result` stays `None` in an unlocked choice render's context. ＋ ("correct answer, not chosen") appears only once locked.
- `_reveal_button.html` is **not** an answer list and stays. `_reveal_extendedresponse.html` stays. Only these nine are deleted, each after its consumer grep is empty: `_reveal_choice.html`, `_reveal_shorttext.html`, `_reveal_shortnumeric.html`, `_reveal_fillblank.html`, `_reveal_dragfill.html`, `_reveal_matchpair.html`, `_reveal_choicegrid.html`, `_reveal_multigrid.html`, `_reveal_dragimage.html`.
- `SUPPORTS_REVEAL` stays a class flag with base `False`, and every code path for an unconverted type (the bare-fragment response, the old results list row in `quiz_results.html`, the ineligible reveal) is **kept**. No production type is unconverted after PR 3, so tests of those paths make one with `monkeypatch.setattr(ExtendedResponseQuestionElement, "SUPPORTS_REVEAL", False)` (extended response is the only type that still has a list to show).
- `views._results_row` keeps every key and every value analytics consumes (`reveal_result`, `marks`, `outcome`, `earned`, `answered`, … — spec §5). Its `reveal_template` / `show_reveal` read `question.REVEAL_TEMPLATE`, so after Task 4 they are `None` / `False` for the nine converted types; only `quiz_results.html`'s unconverted-list branch and (Task 3) the extended-response keyword block read them. New results-page data is built in `views._results_question_html` only.
- Check (choice) / Submit (extended response) is the **first** submit button in the form (spec §3.1); Show answer comes from the shared `_reveal_button.html`, after it.
- Tests: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait` first, then `uv run pytest …`. e2e needs `-m e2e`. **Never pass `-q`** (`addopts` has it). Never run two pytest processes at once. Scope runs to the files each task names; the whole-repo sweep is Task 7 only.
- Template comments: `{# #}` is single-line only; multi-line comments use `{% comment %}…{% endcomment %}`.
- CSS: no line-number citations in comments; never write `*/` mid-comment.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Lint before EVERY commit**, scoped to the files the task touched: `uv run ruff check --no-cache --fix <py files> && uv run ruff format --no-cache <py files> && uv run ruff check --no-cache <py files>`. isort is `force-single-line = true`; an assertion line still over 88 characters after `ruff format` gets `# noqa: E501`.
- Existing tests that PR 3 legitimately breaks are **rewritten, never loosened or deleted** (a test whose only subject is a deleted template is the one exception — see Task 4's table): each rewrite keeps the old assertion's substance and carries `# PR 3 (spec 2026-09-25 §…): replaces <old assertion>`. Reverting a mutant or a rewrite is done BY HAND — never `git checkout`/`git restore` on a file with uncommitted work.
- Polish UI/help wording: "W lekcji", never "Na lekcji".

## Review Focus

1. **A choice option the student picked is deleted (or a new correct option added) after they answered** — resume, the reveal response and the results page render without error; the stale pk simply has no row, the new option is unmarked before the lock and gets ＋ after it if correct. Test in Task 1 (`test_edited_options_after_answer_render`).
2. **Author per-option feedback before the lock** — the feedback on a missed correct option ("you missed Lyon") names the key; it must not appear while attempts remain, and appears once locked. Test in Task 1 (`test_option_feedback_waits_for_the_lock`).
3. **Extended-response text with HTML specials** (`<script>`, `&amp;`) — the new results branch prints the student's text; resume, the reveal response and the results page show it escaped. Test in Task 3 (`test_student_text_is_escaped_everywhere`).
4. **Extended response in a lesson after the form gains `data-question-inline`** — a lesson Check still answers with the feedback fragment, and question.js must still land it in the feedback box (its no-`<form>` fall-through), with no nested form. Tests in Task 3 (`test_lesson_check_is_unchanged`) and Task 5 (`test_extended_lesson_check_lands_in_the_box`).
5. **Single-choice (radio) question, wrong pick with attempts left** — only the picked radio is marked ✗; the correct option looks exactly as before the Check. Test in Task 1 (`test_unlocked_single_choice_marks_only_the_pick`).

---

## Plan-time decisions (the spec leaves these open; flag them in the PR description)

| # | Decision | Why |
|---|---|---|
| P1 | Choice adds **no `aria-invalid`**: its non-colour cue stays the visible ✓/✗/＋ glyph plus the existing `.sr-only` `MARK_GLYPHS` label on each marked option. | Spec §2.1 "Choice keeps its existing `MARK_GLYPHS` labels"; the glyph is already a non-colour cue. |
| P2 | Per-option author feedback shows only once the question is locked (unlocked, `mark_result` is `None`, so the template's `c.pk in mark_result.annotated` is False). | A missed correct option's feedback names the key (spec §2.1 no-leak). |
| P3 | An unlocked choice question with markers uses the inline "`--marked`" row layout (option text then marker); the picked-option tint (`--picked`) stays locked-only. | Unlocked inputs are live, so the native dot still shows the pick; the marker must sit on the option's line, not below it. |
| P4 | A locked choice whose **stored** answer was fully correct shows ✓ on every pick and **no ＋**, even if a later key edit makes the fresh mark disagree; ＋ appears only when the locked answer is not fully correct. | Spec §2.6 reverse case, applied to choice's parts. |
| P5 | Extended response's form carries `data-question-inline` **unconditionally**, like every other converted type. | The editor preview renders lesson markup even in a quiz unit, and the quiz try-it now answers with the whole element; lesson Checks (still fragments for this type) take the scripts' existing no-`<form>` branch. |
| P6 | One helper, `courses.quiz.reveal_list_template(question)`, returns `REVEAL_TEMPLATE` unless the type has an in-place view (`INLINE_QUIZ_REVEAL` or a `CONTROLS_TEMPLATE`), else `None`. It replaces the `INLINE_QUIZ_REVEAL or SUPPORTS_REVEAL` test in `quiz_feedback_context` and decides the results fragment's keyword block. | Spec §2.1 "`reveal_template = None` iff the type has an in-place view"; the flag test would drop extended response's keyword block the moment it is converted. |
| P7 | The results-page keyword block follows `_results_row`'s `show_reveal` (not shown on a fully correct row), as the live locked-correct panel already does. | Today's list page and the live panel agree on this; D10 "as it ended". |
| P8 | The CSS for the deleted lists' classes (`.question__reveal*`, `.question__tick`, `.question__nudge`, `.answer-correct/-wrong`) is left in place. | Spec §8 scopes the clean-up to templates; the unconverted-type list path is still reachable. Listed as a follow-up in the PR body. |

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/models.py` | `ChoiceQuestionElement`: `part_verdicts`, `choice_marks(..., verdicts=)`, `render()` passes verdicts + reveal keys, `SUPPORTS_REVEAL`; `ExtendedResponseQuestionElement`: `SUPPORTS_REVEAL`; nine `REVEAL_TEMPLATE` constants removed (Task 4) |
| `courses/quiz.py` | `reveal_list_template(question)`; `quiz_feedback_context` uses it |
| `courses/views.py` | `_results_question_html` passes `mark_result` and the keyword-block template; comment fixes |
| `templates/courses/elements/_choicequestion_options.html` (new) | the choice options `<ul>` (shared by the form and the results branch) |
| `templates/courses/elements/choicequestion.html` | results branch, Show answer button, options include |
| `templates/courses/elements/extendedresponsequestionelement.html` | results branch, Show answer button, `data-question-inline` |
| `templates/courses/elements/_results_question_feedback.html` | the keyword block for extended response |
| `templates/courses/elements/_reveal_{choice,shorttext,shortnumeric,fillblank,dragfill,matchpair,choicegrid,multigrid,dragimage}.html` | **deleted** (Task 4) |
| `tests/reveal_pr3_kit.py` (new) | choice / extended-response builders + option-marker parsers |
| `tests/test_quiz_reveal_pr3_choice.py`, `test_quiz_reveal_pr3_extended.py`, `test_quiz_reveal_pr3_cleanup.py`, `test_e2e_quiz_reveal_pr3.py` (new) | tests |
| `docs/help/course-admin/quiz-editors.md` + `.pl.md` | quiz behaviour of both types |

---

### Task 1: Choice paints its picks from the first Check

**Files:**
- Create: `tests/reveal_pr3_kit.py`, `templates/courses/elements/_choicequestion_options.html`
- Modify: `courses/models.py` (`ChoiceQuestionElement`), `templates/courses/elements/choicequestion.html`
- Test: `tests/test_quiz_reveal_pr3_choice.py` (new)
- Rewrite (allowed, Step 5): existing tests pinning "a choice quiz question with attempts left shows no marks"

**Interfaces:**
- Consumes (master): `courses.quiz.quiz_render_state` (already calls `question.part_verdicts(result, answer_from_json(question, latest_answer))` for every answered AUTO question and maps a stored-correct answer's non-None verdicts to `True`); `ChoiceQuestionElement.render()` (receives `verdicts`, `can_reveal`, `reveal_earned`, `revealed` and today ignores them); `MARK_GLYPHS`.
- Produces: `ChoiceQuestionElement.part_verdicts(mark_result, answer) -> list[bool | None]`; `ChoiceQuestionElement.choice_marks(choices, selected, mark_result, mode, locked, verdicts=None) -> dict`; the template context keys `marked_layout` (bool), `can_reveal`, `reveal_earned`, `revealed`; the include `courses/elements/_choicequestion_options.html` (reads `choices`, `marks`, `selected_ids`, `element`, `feedback_for_pk`, `quiz_submitted`, `locked`, `show_picks`, `marked_layout`, `mark_result`, `el`). The kit: `choice(multiple=True, **kw) -> ChoiceKit` (fields `question`, `a`, `b`, `c`, `half`, `right`), `option(html, text) -> str`, `markers(html) -> dict[str, str | None]`, `extended(**kw)`, `ER_WRONG`, `ER_HALF`, `ER_RIGHT`, `KEYWORDS`.

- [ ] **Step 1: Write the kit**

```python
# tests/reveal_pr3_kit.py
"""Multiple choice + extended response (spec 2026-09-25 §8 PR 3): builders and the
parsers that read a choice option's marker out of rendered HTML.

Choice kit (multiple): A and B are correct, C is wrong; `half` picks A + C, so a
painted render reads A ✓, B unmarked (the key -- must not leak before the lock),
C ✗. Single choice: A correct; `half` picks C; A is the option that must not leak.
B and C carry per-option feedback ("Betafb", "Gammafb")."""

import re
from dataclasses import dataclass

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ExtendedResponseQuestionElement

TEXTS = ("Alphaopt", "Betaopt", "Gammaopt")
KEYWORDS = "question__reveal-keywords"
ER_WRONG = {"answer": "nothing relevant"}  # 0 / 1
ER_HALF = {"answer": "alphakw only"}  # 0.5 / 1
ER_RIGHT = {"answer": "alphakw and betakw"}  # 1 / 1

_LI = re.compile(r'<li class="question__choice\b.*?</li>', re.S)
_MARK = re.compile(r"question__choice-marker--(correct|wrong|missed)")


@dataclass
class ChoiceKit:
    question: ChoiceQuestionElement
    a: Choice
    b: Choice
    c: Choice
    half: dict
    right: dict


def choice(multiple=True, **kw):
    kw.setdefault("max_attempts", 3)
    q = ChoiceQuestionElement.objects.create(stem="Pick them.", multiple=multiple, **kw)
    a = Choice.objects.create(question=q, text="Alphaopt", is_correct=True)
    b = Choice.objects.create(
        question=q, text="Betaopt", is_correct=multiple, feedback="Betafb"
    )
    c = Choice.objects.create(
        question=q, text="Gammaopt", is_correct=False, feedback="Gammafb"
    )
    if multiple:
        return ChoiceKit(q, a, b, c, {"choice": [a.pk, c.pk]}, {"choice": [a.pk, b.pk]})
    return ChoiceKit(q, a, b, c, {"choice": [c.pk]}, {"choice": [a.pk]})


def extended(**kw):
    kw.setdefault("max_attempts", 3)
    return ExtendedResponseQuestionElement.objects.create(
        stem="Explain it.",
        required_keywords="alphakw\nbetakw",
        forbidden_keywords="gammakw",
        **kw,
    )


def option(html, text):
    """The <li> of the option whose text is `text` (exactly one expected)."""
    found = [li for li in _LI.findall(html) if f">{text}<" in li]
    assert len(found) == 1, (text, len(found))
    return found[0]


def markers(html):
    """{option text: "correct" | "wrong" | "missed" | None} for the kit's options."""
    out = {}
    for text in TEXTS:
        m = _MARK.search(option(html, text))
        out[text] = m.group(1) if m else None
    return out
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_quiz_reveal_pr3_choice.py
"""Multiple choice in the quiz answer reveal (spec 2026-09-25 §1, §2.1, §2.6, §4, D8).

Task 1: picks painted from the first Check, nothing on an unpicked option before the
lock. Task 2 adds Show answer and the results page (same file)."""

import dataclasses
import re

import pytest
from django.test.signals import template_rendered
from django.urls import reverse

from courses.models import Choice
from courses.models import QuestionResponse
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.reveal_pr3_kit import choice
from tests.reveal_pr3_kit import markers
from tests.reveal_pr3_kit import option

UNMARKED = {"Alphaopt": None, "Betaopt": None, "Gammaopt": None}
HALF = {"Alphaopt": "correct", "Betaopt": None, "Gammaopt": "wrong"}
LOCKED_HALF = {"Alphaopt": "correct", "Betaopt": "missed", "Gammaopt": "wrong"}


def _quiz(client, username="stu"):
    user = make_login(client, username)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


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


# ── hooks ─────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_part_verdicts_one_entry_per_option_picked_only():
    kit = choice()
    q = kit.question
    result = q.mark({kit.a.pk, kit.c.pk})
    assert q.part_verdicts(result, {kit.a.pk, kit.c.pk}) == [True, None, False]
    assert q.part_verdicts(q.mark(set()), set()) == [None, None, None]
    single = choice(multiple=False)
    sq = single.question
    assert sq.part_verdicts(sq.mark({single.c.pk}), {single.c.pk}) == [None, None, False]


@pytest.mark.django_db
def test_choice_marks_unlocked_quiz_reads_verdicts_never_mark_result():
    kit = choice()
    q = kit.question
    choices = list(q.choices.all())
    picked = {kit.a.pk, kit.c.pk}
    full = q.mark(picked)  # carries the key: must be ignored while unlocked
    marks = q.choice_marks(choices, picked, full, "quiz", False, verdicts=[True, None, False])
    assert {pk: m["kind"] for pk, m in marks.items()} == {kit.a.pk: "correct", kit.c.pk: "wrong"}
    # Unlocked without verdicts: nothing, even when handed a mark_result.
    assert q.choice_marks(choices, picked, full, "quiz", False) == {}


@pytest.mark.django_db
def test_choice_marks_locked_adds_missed_unless_fully_correct():
    kit = choice()
    q = kit.question
    choices = list(q.choices.all())
    picked = {kit.a.pk, kit.c.pk}
    wrong = q.mark(picked)
    marks = q.choice_marks(choices, picked, wrong, "quiz", True, verdicts=[True, None, False])
    assert marks[kit.b.pk]["kind"] == "missed"
    # §2.6 reverse case (P4): a stored-correct answer shows no ＋ whatever the fresh key.
    # MarkResult is a frozen dataclass: build the stored-correct result with replace().
    stored_correct = dataclasses.replace(wrong, correct=True)
    marks = q.choice_marks(
        choices, picked, stored_correct, "quiz", True, verdicts=[True, None, True]
    )
    assert {m["kind"] for m in marks.values()} == {"correct"} and kit.b.pk not in marks
    # Analytics' call (no verdicts): picks from the key, as on master.
    marks = q.choice_marks(choices, picked, q.mark(picked), "quiz", True)
    assert {pk: m["kind"] for pk, m in marks.items()} == {
        kit.a.pk: "correct",
        kit.b.pk: "missed",
        kit.c.pk: "wrong",
    }


# ── quiz: before the lock ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_unlocked_wrong_check_marks_picks_and_leaks_nothing(client):
    # The PR 3 no-leak test (spec §2.1): an unlocked, wrong choice question's HTML
    # carries no marker, class or attribute on any unpicked option.
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    before = option(_page(client, unit), "Betaopt")
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert markers(body) == HALF
    assert option(body, "Betaopt") == before  # byte-identical to the pre-Check markup
    assert "question__choice--picked" not in body  # tint stays locked-only (P3)
    assert "question__choices--marked" in body  # markers sit inline (P3)
    assert "correct answer, not chosen" not in body and "Betafb" not in body
    assert "data-answer-key" not in body and "data-answer-switch" not in body


@pytest.mark.django_db
def test_unlocked_render_context_has_no_mark_result(client):
    # Spec §2.1: mark_result (whose reveal is the whole key) stays None in an
    # unlocked choice render's context.
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    seen = []

    def grab(sender, template, context, **kwargs):
        if template.name == "courses/elements/choicequestion.html":
            seen.append(context.get("mark_result"))

    template_rendered.connect(grab)
    try:
        _fetch(client, unit, el, kit.half)
        _page(client, unit)
    finally:
        template_rendered.disconnect(grab)
    assert seen and all(m is None for m in seen)


@pytest.mark.django_db
def test_unlocked_single_choice_marks_only_the_pick(client):
    unit = _quiz(client)
    kit = choice(multiple=False)
    el = add_element(unit, kit.question)
    before = option(_page(client, unit), "Alphaopt")
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert markers(body) == {"Alphaopt": None, "Betaopt": None, "Gammaopt": "wrong"}
    assert option(body, "Alphaopt") == before


@pytest.mark.django_db
def test_option_feedback_waits_for_the_lock(client):
    # P2: Gammafb (a wrong pick) and Betafb (a missed correct option -- names the
    # key) are both withheld until the question locks.
    unit = _quiz(client)
    kit = choice(max_attempts=2)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert "Gammafb" not in body and "Betafb" not in body
    body = _fetch(client, unit, el, kit.half).content.decode()  # last attempt: locked
    assert "Gammafb" in body and "Betafb" in body


@pytest.mark.django_db
def test_resume_nojs_previewer_and_editor_paint_the_same(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    assert markers(_page(client, unit)) == HALF  # resume
    unit2 = make_quiz_unit(course=unit.course)
    kit2 = choice()
    el2 = add_element(unit2, kit2.question)
    assert markers(client.post(_url(unit2, el2), kit2.half).content.decode()) == HALF  # no-JS
    client.logout()
    staff = make_login(client, "prev_staff")
    staff.is_staff = True  # staff + not enrolled = the previewer path
    staff.save()
    unit3 = make_quiz_unit()
    kit3 = choice()
    el3 = add_element(unit3, kit3.question)
    fetched = _fetch(client, unit3, el3, {**kit3.half, "attempt": "1"}).content.decode()
    assert markers(fetched) == HALF
    nojs = client.post(_url(unit3, el3), {**kit3.half, "attempt": "1"}).content.decode()
    assert markers(nojs) == HALF
    client.logout()
    pa = make_pa(client, "pa_choice")
    course = CourseFactory(owner=pa)
    qunit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    kit4 = choice()
    el4 = add_element(qunit, kit4.question)
    url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": el4.pk})
    body = client.post(
        url, {**kit4.half, "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert markers(body) == HALF


@pytest.mark.django_db
def test_locked_wrong_marks_all_three_with_no_switch(client):
    # D8: ✓ ✗ ＋ on the options, no switch, no key copy.
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert markers(body) == LOCKED_HALF
    assert "question__choice--picked" in body
    assert "data-answer-switch" not in body and "data-answer-key" not in body
    assert markers(_page(client, unit)) == LOCKED_HALF


@pytest.mark.django_db
def test_stored_correct_then_key_edited_shows_picks_correct_no_missed(client):
    # Spec §2.6 reverse case (P4).
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.right)
    Choice.objects.filter(pk=kit.b.pk).update(is_correct=False)
    Choice.objects.filter(pk=kit.c.pk).update(is_correct=True)
    page = _page(client, unit)
    assert markers(page) == {"Alphaopt": "correct", "Betaopt": "correct", "Gammaopt": None}


@pytest.mark.django_db
def test_edited_options_after_answer_render(client):
    # Review Focus 1: a picked option deleted, a new correct option added.
    unit = _quiz(client)
    kit = choice(max_attempts=2)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    kit.c.delete()
    Choice.objects.create(question=kit.question, text="Deltaopt", is_correct=True)
    page = _page(client, unit)
    assert "Gammaopt" not in page
    assert 'question__choice-marker--missed' not in page  # not locked yet
    body = _fetch(client, unit, el, {"choice": [kit.a.pk]}).content.decode()  # locks
    assert option(body, "Deltaopt").count("question__choice-marker--missed") == 1
    assert QuestionResponse.objects.get(element=el).locked
```

(`make_quiz_unit(course=...)` builds a second quiz unit in the same course, so the no-JS case gets a fresh question the student has not answered.)

- [ ] **Step 3: Run them to verify they fail**

Run: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait` then `uv run pytest tests/test_quiz_reveal_pr3_choice.py -p no:randomly`
Expected: FAIL — `part_verdicts` returns `None` (base), `choice_marks` has no `verdicts` parameter (`TypeError`), the unlocked Check shows no markers, and the stored-correct key-edit test shows ✗/＋. These PASS already and are guards for Step 4 (do not "fix" them into failing): `test_unlocked_render_context_has_no_mark_result`, `test_option_feedback_waits_for_the_lock`, `test_locked_wrong_marks_all_three_with_no_switch`, `test_edited_options_after_answer_render`.

- [ ] **Step 4: Implement**

In `courses/models.py`, `ChoiceQuestionElement`, add after `feedback_context`:

```python
    def part_verdicts(self, mark_result, answer):
        """One entry per option, in option order (spec 2026-09-25 §2.1, pinned):
        True / False for a PICKED option, None for an unpicked one. An unpicked
        option's correctness IS the key, so it never leaves the server before the
        lock; after it, choice_marks adds ＋ from mark_result."""
        correct = set(mark_result.reveal or ())
        picked = set(answer or ())
        return [
            (c.pk in correct) if c.pk in picked else None for c in self.choices.all()
        ]
```

Replace `choice_marks` (signature + docstring + body) with:

```python
    def choice_marks(self, choices, selected, mark_result, mode, locked, verdicts=None):
        """Per-option outcome markers: {choice pk: {"kind", "glyph", "label"}}.

        QUIZ / RESULTS — the picks are marked ✓ / ✗ from `verdicts` (part_verdicts:
        picked options only) from the first Check on (spec 2026-09-25 §1.2, D6),
        and never from mark_result while unlocked: an unlocked render's mark_result
        is None, and its reveal would be the whole key. Once LOCKED, a correct
        option the student did not pick gets ＋ -- unless the locked answer is fully
        correct (mark_result.correct; on stored paths the STORED correctness, so a
        later key edit cannot put ＋ beside a "Correct" line, spec §2.6). A locked
        call without verdicts (analytics' views._results_row) marks the picks from
        mark_result.reveal, as before.

        LESSON — unchanged from the per-option-feedback design (#132): only
        options the author wrote feedback for, and only where the selection state
        is wrong (mark_result.annotated). A lesson leaves its inputs live, so the
        radio dot still reads.
        """
        marks = {}
        if mode == "lesson":
            if mark_result is None:
                return {}
            for c in choices:
                if c.pk in mark_result.annotated:
                    marks[c.pk] = "wrong" if c.pk in selected else "missed"
        else:
            if verdicts is not None:
                for c, v in zip(choices, verdicts, strict=False):
                    if v is True:
                        marks[c.pk] = "correct"
                    elif v is False:
                        marks[c.pk] = "wrong"
            elif locked and mark_result is not None:
                correct = set(mark_result.reveal or ())
                for c in choices:
                    if c.pk in selected:
                        marks[c.pk] = "correct" if c.pk in correct else "wrong"
            if locked and mark_result is not None and not mark_result.correct:
                correct = set(mark_result.reveal or ())
                for c in choices:
                    if c.pk not in selected and c.pk in correct:
                        marks[c.pk] = "missed"
        return {
            pk: {
                "kind": kind,
                "glyph": self.MARK_GLYPHS[kind][0],
                "label": self.MARK_GLYPHS[kind][1],
            }
            for pk, kind in marks.items()
        }
```

(`strict=False`: `verdicts` and `choices` both come from `self.choices.all()` in the same request; a length mismatch cannot happen, and a zip error would 500 a quiz page.)

In `ChoiceQuestionElement.render()`: replace the comment block that says choice consumes the reveal keys "in PR 3" with `# verdicts / can_reveal / reveal_earned / revealed: quiz answer reveal (spec 2026-09-25 §2.1, §3).`; normalise and forward verdicts, and add the new context keys:

```python
        choices = list(self.choices.all())
        selected = set(selected_ids or ())
        # An unresolvable template variable (a quiz row with no st.verdicts) arrives
        # as ''. Normalise, as QuestionElement.render does.
        verdicts = verdicts or None
        marks = self.choice_marks(
            choices, selected, mark_result, mode, locked, verdicts=verdicts
        )
        show_picks = bool(mode != "lesson" and locked)
```

and in the `render_to_string` context replace `"show_picks": bool(mode != "lesson" and locked),` with `"show_picks": show_picks,` (keep its comment) and add, after it:

```python
                # Inline "option ✓" rows whenever a quiz / results list carries a
                # marker -- from the first Check on (P3), not only once locked.
                "marked_layout": bool(show_picks or (mode != "lesson" and marks)),
                "can_reveal": can_reveal,
                "reveal_earned": reveal_earned,
                "revealed": revealed,
```

Create `templates/courses/elements/_choicequestion_options.html` from the `<ul>…</ul>` block of `choicequestion.html`, with two changes: the `<ul>` class test reads `marked_layout` instead of `show_picks`, and the first comment is reworded:

```django
{% load courses_extras %}
{% comment %}The choice options list, shared by the question form and the results
branch. --marked switches the rows to an inline layout (option text then marker)
whenever a quiz or results list carries a marker (marked_layout, set in
ChoiceQuestionElement.render). A lesson list keeps app.css's `label { display: block }`
stacking, which its per-option feedback indent was tuned against.{% endcomment %}
<ul class="question__choices{% if marked_layout %} question__choices--marked{% endif %}">
  {% for c in choices %}
    {% comment %}`marks` (ChoiceQuestionElement.choice_marks) owns WHICH options
    carry a marker and why -- a quiz marks the picks from the first Check and adds ＋
    once locked, a lesson marks only the author-annotated ones. Keep that rule in
    Python; the template just paints what it is handed.{% endcomment %}
    {% with mk=marks|dictkey:c.pk %}
    <li class="question__choice{% if show_picks and c.pk in selected_ids %} question__choice--picked{% endif %}">
      <label>
        <input type="{% if el.multiple %}checkbox{% else %}radio{% endif %}"
               name="choice" value="{{ c.pk }}"
               {% if element.pk == feedback_for_pk and c.pk in selected_ids %}checked{% endif %}
               {% if quiz_submitted or locked %}disabled{% endif %}>
        <span class="question__choice-text">{{ c.text }}</span>
      </label>
      {% if mk %}
        <span class="question__choice-marker question__choice-marker--{{ mk.kind }}" aria-hidden="true">{{ mk.glyph }}</span>
        {% comment %}The glyph is aria-hidden, so this is the only thing a screen
        reader gets for the outcome. The `checked` state is announced by the input
        itself, but "checked" alone never says whether the pick was right.{% endcomment %}
        <span class="sr-only">{{ mk.label }}</span>
      {% endif %}
      {% comment %}Gated on `mk` AND mark_result: an unlocked quiz render has no
      mark_result, so author feedback (which can name a missed correct option) waits
      for the lock (P2). The quiz used to show this text in the bottom reveal list
      (question__nudge); that list is gone for this type.{% endcomment %}
      {% if mk and c.pk in mark_result.annotated %}
        <p class="question__choice-feedback">{{ c.feedback }}</p>
      {% endif %}
    </li>
    {% endwith %}
  {% endfor %}
</ul>
```

In `choicequestion.html`, replace the `{% comment %}--marked…{% endcomment %}` block and the whole `<ul>…</ul>` with `{% include "courses/elements/_choicequestion_options.html" %}`, and reduce the first line to `{% load i18n %}`.

- [ ] **Step 5: Run the new tests, then the suites that pin choice's old quiz behaviour; rewrite what D6 legitimately changes**

Run: `uv run pytest tests/test_quiz_reveal_pr3_choice.py -p no:randomly`
Expected: PASS.

Then run: `uv run pytest tests/test_quiz_choice_inline_marking.py tests/test_element_try.py tests/test_choice_nudge_paths.py tests/test_choice_inline_feedback.py tests/test_quiz_noleak.py tests/test_quiz_resume.py tests/test_quiz_previewer_answer.py tests/test_quiz_previewer_render.py tests/test_quiz_reveal_flow.py tests/test_quiz_reveal_hooks.py tests/test_answer_summary.py tests/test_analytics_student_quiz.py tests/test_questions_consumption.py tests/test_quiz_render.py courses/tests/test_nested_question_nojs_feedback.py courses/tests/test_question_restore.py -p no:randomly`

Expected RED only under these rules (each rewrite carries `# PR 3 (spec 2026-09-25 §…): replaces …`):

(a) an assertion that an unlocked (attempts-left) choice quiz question shows **no marker at all** — D6 / §2.1 now mark the picks: rewrite to "the picked options carry ✓/✗, every unpicked option is unmarked (no `question__choice-marker`, no `--missed`, no feedback text)". Keep every assertion about the key (no ＋, no `correct answer, not chosen`, no `data-answer-key`).

**Known at plan time (a catalogue of master `b1dde810`'s tests, 2026-09-26)** — expect exactly these:

| Test | Old assertion | Rule → rewrite to |
|---|---|---|
| `tests/test_quiz_choice_inline_marking.py::test_no_marking_while_attempts_remain` | `M_WRONG not in html` | (a) → `html.count(M_WRONG) == 1`; keep `M_CORRECT not in html` (the kit there picks only the wrong option), `M_MISSED not in html`, `PICKED not in html`; rename to `test_only_the_pick_is_marked_while_attempts_remain`. Reword the module docstring's "While attempts remain NOTHING is marked" to "While attempts remain only the picks are marked (✓/✗, spec 2026-09-25 §2.1) — never ＋, never the pick tint" |
| `tests/test_element_try.py::test_try_quiz_withholds_reveal_while_attempts_remain` | `b"question__choice-marker" not in resp.content` | (a) → `b"question__choice-marker--wrong" in resp.content` and `b"question__choice-marker--missed" not in resp.content`; keep its `answer-correct` / `data-quiz-locked` assertions |
| `tests/test_quiz_reveal_hooks.py::test_unconverted_type_hooks_are_none` | `part_verdicts(...) is None` on an unsaved `ChoiceQuestionElement()` (now a per-option list; an unsaved instance cannot read `self.choices` and raises `ValueError`) | retarget the instance to `ExtendedResponseQuestionElement()` — `part_verdicts(...) is None`, `key_answer() is None`, `SUPPORTS_REVEAL is False` (Task 3 flips that one line); choice's list is pinned by `test_part_verdicts_one_entry_per_option_picked_only` |

These must stay GREEN unedited — if one goes red, the code is wrong: `tests/test_choice_nudge_paths.py` (pre-lock `"NUDGE-B" not in body1`: `mark_result` stays None unlocked), `tests/test_quiz_choice_inline_marking.py`'s resume test (unlocked wrong: no ✓, no ＋), `tests/test_quiz_reveal_flow.py`'s choice validation-fragment and locked-choice tests, `courses/tests/test_nested_question_nojs_feedback.py` (a nested unanswered choice shows no marker), `tests/answer_summary_fixtures.py`'s positional `choice_marks(choices, picked, mark_result, "quiz", True)` call (hence `verdicts` is keyword-with-default). The e2e twins of rule (a) are rewritten in Task 5.

Anything RED outside (a) and the table is a bug in this task — fix the code.

- [ ] **Step 6: Lint and commit**

```bash
# <rewritten> = every existing test file this task rewrote (Step 5)
uv run ruff check --no-cache --fix courses/models.py tests/reveal_pr3_kit.py tests/test_quiz_reveal_pr3_choice.py <rewritten> && uv run ruff format --no-cache courses/models.py tests/reveal_pr3_kit.py tests/test_quiz_reveal_pr3_choice.py <rewritten> && uv run ruff check --no-cache courses/models.py tests/reveal_pr3_kit.py tests/test_quiz_reveal_pr3_choice.py <rewritten>
git add courses/models.py templates/courses/elements/choicequestion.html templates/courses/elements/_choicequestion_options.html tests/
git commit -m "feat(quiz-reveal): multiple choice marks its picks from the first Check"
```

---

### Task 2: Choice — Show answer and the results page

**Files:**
- Modify: `courses/models.py` (`ChoiceQuestionElement.SUPPORTS_REVEAL`), `templates/courses/elements/choicequestion.html`, `courses/views.py` (`_results_question_html`)
- Test: `tests/test_quiz_reveal_pr3_choice.py` (append)
- Rewrite (allowed, Step 5): tests using choice as the "unconverted type" example; tests pinning choice's old results list row

**Interfaces:**
- Consumes: Task 1 (`part_verdicts`, `choice_marks(verdicts=)`, `_choicequestion_options.html`, the `can_reveal` / `reveal_earned` context keys); master's `_reveal_button.html` (reads `mode`, `can_reveal`, `quiz_submitted`, `reveal_earned`, `el`); `views._results_row` (its `reveal_result` is a fresh `mark()` of the latest answer, or `mark(build_answer(QueryDict()))` for an unanswered AUTO row).
- Produces: `ChoiceQuestionElement.SUPPORTS_REVEAL = True`; `choicequestion.html`'s `mode == "results"` branch; `_results_question_html` passing `mark_result=` (Task 3 extends the same function).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_quiz_reveal_pr3_choice.py`)

```python
# ── Task 2: Show answer ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_show_answer_offered_after_a_wrong_check_check_first(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    assert 'name="reveal"' not in _page(client, unit)  # no button before a Check
    body = _fetch(client, unit, el, kit.half).content.decode()
    buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', body)
    assert 'name="reveal"' not in buttons[0]  # Check first (spec §3.1)
    assert sum('name="reveal"' in b for b in buttons) == 1
    assert "data-confirm" in body and "(0 of 1)" in body


@pytest.mark.django_db
def test_enrolled_reveal_locks_marks_missed_and_uses_no_attempt(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    # The posted answer is ignored (spec §3.2): the stored picks are shown.
    body = _fetch(client, unit, el, {"reveal": "1", "choice": [kit.b.pk]}).content.decode()
    assert markers(body) == LOCKED_HALF
    assert "answer shown" in body and 'name="reveal"' not in body
    assert "data-answer-switch" not in body  # D8
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.revealed_at is not None and r.attempt_count == 1
    assert markers(_page(client, unit)) == LOCKED_HALF


@pytest.mark.django_db
def test_nojs_reveal_rerenders_the_page_locked(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    client.post(_url(unit, el), kit.half)
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert markers(page) == LOCKED_HALF and "answer shown" in page


@pytest.mark.django_db
def test_previewer_and_editor_reveal_lock_ephemerally(client):
    staff = make_login(client, "prev_staff2")
    staff.is_staff = True
    staff.save()
    unit = make_quiz_unit()
    kit = choice()
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, {**kit.half, "reveal": "1", "attempt": "1"}).content.decode()
    assert markers(body) == LOCKED_HALF and "answer shown" in body
    client.logout()
    pa = make_pa(client, "pa_choice2")
    course = CourseFactory(owner=pa)
    qunit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    kit2 = choice()
    el2 = add_element(qunit, kit2.question)
    url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": el2.pk})
    body = client.post(
        url, {**kit2.half, "reveal": "1", "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert markers(body) == LOCKED_HALF and body.count("data-question-feedback") == 1
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_choice_never_reveal(client, mode):
    unit = _quiz(client)
    kit = choice(marking_mode=mode)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert 'name="reveal"' not in body
    assert "question__choice-marker" not in body  # N/R: never a verdict
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 409


# ── Task 2: results page ──────────────────────────────────────────────────────


def _rows(html):
    return html.split('class="quiz-results__item')[1:]


@pytest.mark.django_db
def test_results_choice_rows_as_they_ended(client):
    unit = _quiz(client)
    wrong, unanswered, right = choice(), choice(), choice()
    el_w = add_element(unit, wrong.question)
    add_element(unit, unanswered.question)
    el_r = add_element(unit, right.question)
    _fetch(client, unit, el_w, wrong.half)
    _fetch(client, unit, el_w, {"reveal": "1"})
    _fetch(client, unit, el_r, right.right)
    rows = _rows(_results(client, unit))
    assert markers(rows[0]) == LOCKED_HALF and "answer shown" in rows[0]
    # Spec §4 (PR 3): an unanswered choice row shows ＋ on the correct options.
    assert markers(rows[1]) == {"Alphaopt": "missed", "Betaopt": "missed", "Gammaopt": None}
    assert "Not answered" in rows[1]
    assert markers(rows[2]) == {"Alphaopt": "correct", "Betaopt": "correct", "Gammaopt": None}
    for row in rows:
        assert "<form" not in row and 'type="submit"' not in row
        assert "question__reveal" not in row  # the old list is gone
        assert "data-answer-switch" not in row  # D8
        inputs = re.findall(r"<input\b[^>]*>", row)
        assert inputs and all("disabled" in i for i in inputs)


@pytest.mark.django_db
def test_results_stored_correct_key_edited_choice_shows_picks_correct(client):
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.right)
    Choice.objects.filter(pk=kit.b.pk).update(is_correct=False)
    row = _rows(_results(client, unit))[0]
    assert markers(row) == {"Alphaopt": "correct", "Betaopt": "correct", "Gammaopt": None}
    assert "Correct" in row


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_results_nr_choice_rows_show_picks_without_verdicts(client, mode):
    unit = _quiz(client)
    kit = choice(marking_mode=mode)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    row = _rows(_results(client, unit))[0]
    assert markers(row) == UNMARKED
    assert row.count("question__choice--picked") == 2  # the picks are still legible


@pytest.mark.django_db
def test_results_auto_row_answered_while_not_marked_shows_the_key(client):
    # Answered while N (no stored fraction), switched to AUTO before Finish:
    # _results_row reads it "not_answered"; like any unanswered auto row it shows
    # the key (spec §4) -- ＋ on the correct options, the picks kept.
    unit = _quiz(client)
    kit = choice(marking_mode="N")
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    kit.question.marking_mode = "A"
    kit.question.save()
    row = _rows(_results(client, unit))[0]
    assert markers(row) == LOCKED_HALF and "Not answered" in row


@pytest.mark.django_db
def test_results_option_feedback_shows_on_marked_options(client):
    # The old list printed annotated feedback as question__nudge; the options now do.
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    row = _rows(_results(client, unit))[0]
    assert "Betafb" in option(row, "Betaopt") and "Gammafb" in option(row, "Gammaopt")


@pytest.mark.django_db
@pytest.mark.parametrize("answered", [True, False])
def test_analytics_still_shows_the_choice_key(client, answered):
    # Spec §5: _results_row keeps its keys; analytics shows the expected answer.
    user = make_login(client, "stu_an")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    if answered:
        _fetch(client, unit, el, kit.half)
    _results(client, unit)
    client.logout()
    make_pa(client, "pa_an")
    url = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": unit.course.slug, "student_pk": user.pk, "node_pk": unit.pk},
    )
    body = client.get(url).content.decode()
    assert "Alphaopt" in body and "Betaopt" in body
    # answer_summary._choice rows: a missed correct option is `is-missed` (B when
    # answered with A + C; A and B when unanswered), the key column is present.
    assert body.count("answers__option is-missed") == (1 if answered else 2)
    assert "Answer key" in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr3_choice.py -p no:randomly`
Expected: the Task 1 tests PASS; of the new Task 2 tests these FAIL — `test_show_answer_offered_after_a_wrong_check_check_first`, `test_enrolled_reveal_locks_marks_missed_and_uses_no_attempt`, `test_nojs_reveal_rerenders_the_page_locked`, `test_previewer_and_editor_reveal_lock_ephemerally` (no Show answer button, `SUPPORTS_REVEAL` is False; reveal POSTs get 409 / are processed as a Check), and the four `test_results_*` tests (the rows are the old `_reveal_choice.html` list: `question__reveal` present, no `<input>`). These PASS already and are guards: `test_analytics_still_shows_the_choice_key` (analytics must not change) and `test_not_marked_and_review_choice_never_reveal` (an N/R question locks on its first submit, so the enrolled reveal hits `_quiz_locked_response`'s 409 before `can_reveal`; `can_reveal`'s marking-mode check is pinned by the `("choice", "N", False)` parity case added in Step 5 and by the previewer leg below).

In `test_not_marked_and_review_choice_never_reveal`, add a previewer leg after the enrolled assertions so the refusal path itself is exercised: log in a staff previewer (`make_login(client, f"prev_{mode}")`, `is_staff = True`), build a fresh `choice(marking_mode=mode)` in a new `make_quiz_unit()`, POST `{**kit.half, "reveal": "1", "attempt": "1"}` with the fetch header, and assert `"answer shown" not in body` (an ineligible ephemeral reveal is processed as a normal Check, spec §3.3).

- [ ] **Step 3: Implement**

In `courses/models.py`, `ChoiceQuestionElement`, after `INLINE_LESSON_FEEDBACK = True`:

```python
    # Quiz answer reveal (spec 2026-09-25 §8 PR 3): Show answer + the results-page
    # render. Choice keeps its own in-place view (D8: ✓ ✗ ＋ on the options, no
    # switch, key_answer() stays None).
    SUPPORTS_REVEAL = True
```

`choicequestion.html` becomes:

```django
{% load i18n %}
<div class="el el--question" data-question>
  {% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}
  {% if mode == "results" %}
  {% comment %}Results (spec §4): read-only, no form, no buttons. The inputs are
  disabled through `locked` (views._results_question_html passes locked=True);
  the feedback box holds the results fragment.{% endcomment %}
  <div class="question__form">
    {% include "courses/elements/_choicequestion_options.html" %}
    <div class="question__feedback" data-question-feedback>{{ feedback_html|safe }}</div>
  </div>
  {% elif element %}
  <form class="question__form" method="post" data-question-inline
        action="{{ action_url }}">
    {% csrf_token %}
    {% include "courses/elements/_choicequestion_options.html" %}
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    {% include "courses/elements/_reveal_button.html" %}
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

In `courses/views.py::_results_question_html`, compute the mark result the in-place types without a key copy read (choice's ✓ ✗ ＋; the stored-answer rule of spec §2.6 for answered rows, today's "reveal all" `mark(build_answer(QueryDict()))` — already in `row["reveal_result"]` — for unanswered AUTO rows, spec §4):

```python
    answered = row["answered"]
    auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
    mark_result = None
    if answered and auto and response.fraction is not None:
        result = _stored_result(question, response)
        state = quiz_render_state(question, response, result)
        fully_correct = bool(result.correct)
        mark_result = result
    elif answered:
        # N/R (no verdicts, no key) -- or an AUTO question answered while it was
        # N/R (no stored fraction; _results_row reads it as not_answered): that one
        # shows its key like an unanswered auto row (spec §4, ＋ for choice).
        state = quiz_render_state(question, response, None)
        fully_correct = False
        if auto:
            mark_result = row["reveal_result"]
    else:
        # Unanswered: neutral controls, mark() NOT called here (spec §4). Types
        # with no key copy (choice) read row["reveal_result"] -- _results_row's
        # "reveal all" mark, which analytics needs anyway.
        state = dict(BLANK_QUIZ_STATE)
        fully_correct = False
        if auto:
            mark_result = row["reveal_result"]
```

and pass `mark_result=mark_result,` in the `question.render(...)` call (after `verdicts=state["verdicts"],`). Key-copy templates ignore `mark_result` in results mode (their results branches read `submitted_values` / `verdicts` / `key_copy_html` only — confirm with `grep -n "mark_result" templates/courses/elements/*questionelement.html`: only `fillblankquestionelement.html`'s quiz/lesson branch reads it). Also update `_results_row`'s comment that says "these _reveal_choice.html shows the answer KEY only" to: `# Per-option markers for analytics (answer_summary option_marks), same vocabulary the locked quiz page uses.` — keep the code.

- [ ] **Step 4: Run the file**

Run: `uv run pytest tests/test_quiz_reveal_pr3_choice.py -p no:randomly`
Expected: PASS.

- [ ] **Step 5: Run the suites that pin choice as unconverted / its old results row; rewrite what PR 3 legitimately changes**

Run: `uv run pytest tests/test_quiz_reveal_helpers.py tests/test_quiz_reveal_flow.py tests/test_quiz_lock_rule_parity.py tests/test_element_try.py tests/test_quiz_results_choice_reveal.py tests/test_analytics_student_quiz.py tests/test_quiz_reveal_result_line.py tests/test_choice_nudge_paths.py tests/test_quiz_results_render.py tests/test_quiz_reveal_results.py tests/test_title_math_assets.py tests/test_answer_summary.py tests/test_ephemeral_quiz_feedback.py -p no:randomly`

Expected RED only under these rules (each with the `# PR 3 …: replaces …` comment):

(b) a test that used `ChoiceQuestionElement` as its example of an **unconverted** type (reveal POST refused / no Show answer button / "keeps today's list" / fragment response) — switch the example to `ExtendedResponseQuestionElement` with `monkeypatch.setattr(ExtendedResponseQuestionElement, "SUPPORTS_REVEAL", False)` (the only unconverted shape left, Global Constraints), keeping the assertion; where the test's point was choice-specific, assert choice's NEW behaviour instead (the reveal is accepted and locks with ＋);
(c) the results page renders a choice row as the question (`row.rendered`: options list, inputs disabled, markers) instead of the `_reveal_choice.html` list (`question__reveal`, `question__reveal-mark--*`, `question__nudge`, `answer-correct`) — assert the same outcome through `markers(...)` / the `question__choice-marker--*` classes and `question__choice-feedback`.

**Known at plan time** — expect exactly these:

| Test | Old assertion | Rule → rewrite to |
|---|---|---|
| `tests/test_quiz_reveal_helpers.py::test_can_reveal_refuses_unconverted_type` | `can_reveal(ChoiceQuestionElement(...), attempts_made=3, locked=False) is False` | (b) → `monkeypatch.setattr(ExtendedResponseQuestionElement, "SUPPORTS_REVEAL", False)` and the same assertion on an `ExtendedResponseQuestionElement(...)` (the file already monkeypatches the flag this way) |
| `tests/test_quiz_reveal_flow.py::test_reveal_refused_for_not_marked_and_unconverted` | the choice half: `_fetch(client, unit, ch, {"reveal": "1"}).status_code == 409` | (b) → keep the N half unchanged; replace the choice half with an `extended()` question built the same way (a `QuestionResponse` with `attempt_count=1`, `latest_answer="x"`) under `monkeypatch.setattr(ExtendedResponseQuestionElement, "SUPPORTS_REVEAL", False)` → still 409 |
| `tests/test_quiz_lock_rule_parity.py` — the `("choice", "A", False)` case of the reveal-eligibility parametrisation | enrolled `status_code == 409`; `b"answer shown" not in ephemeral.content` | (b) → the case becomes `("choice", "A", True)` (eligible on both paths, choice's NEW behaviour); add `("choice", "N", False)` so choice keeps an ineligible leg |
| `tests/test_element_try.py::test_try_quiz_ineligible_reveal_is_a_plain_check[choice]` | `"answer shown" not in body`, `"2 attempts left" in body`, `"data-quiz-locked" not in body` | (b) → replace the `choice` param with an `extended` one (ER, `max_attempts=3`, a wrong `answer`) under the `SUPPORTS_REVEAL=False` monkeypatch, keeping the three assertions; choice's accepted editor reveal is pinned by `test_previewer_and_editor_reveal_lock_ephemerally` |
| `tests/test_quiz_results_choice_reveal.py` — its four `question__reveal-mark--*` tests | `M_CORRECT` / `M_WRONG` / `M_MISSED` = `question__reveal-mark--*` | (c) → the constants become `question__choice-marker--correct/--wrong/--missed`, every assertion kept, plus `"question__reveal" not in body` in each; rewrite the module docstring (it names `_reveal_choice.html`) and the stale docstring of its fifth test ("only choice relaxed the gate") |
| `tests/test_analytics_student_quiz.py::test_t19_student_results_page_shows_the_same_kinds` | `select("li.question__reveal-item")`, `.question__reveal-mark` | (c) → `li.question__choice`, `.question__choice-marker`, text from `.question__choice-text`; the same expected dict |
| `tests/test_quiz_choice_inline_marking.py::test_a_submitted_quiz_never_renders_its_options_again` (GREEN, docstring false) | its docstring says the results page "renders no options list at all" and names "_choice_marks" | docstring only → the results page now renders the options read-only (spec §4, via `render(mode="results")`); this test pins that the QUIZ page is never shown again for a submitted quiz (the redirect); the helper is `choice_marks` |
| `tests/test_quiz_reveal_result_line.py::test_incorrect_unconverted_type_gets_new_line_too` (GREEN, premise stale) | builds a choice as "unconverted" | rename to `test_incorrect_choice_gets_the_new_line`, fix its comment; assertions unchanged |

Anything RED outside (b), (c) and the table is a bug in this task — fix the code.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --no-cache --fix courses/models.py courses/views.py tests/test_quiz_reveal_pr3_choice.py <rewritten> && uv run ruff format --no-cache courses/models.py courses/views.py tests/test_quiz_reveal_pr3_choice.py <rewritten> && uv run ruff check --no-cache courses/models.py courses/views.py tests/test_quiz_reveal_pr3_choice.py <rewritten>
git add courses/models.py courses/views.py templates/courses/elements/choicequestion.html tests/
git commit -m "feat(quiz-reveal): multiple choice gets Show answer and the results-page render"
```

---

### Task 3: Extended response — Show answer and the results page

**Files:**
- Modify: `courses/quiz.py` (`reveal_list_template`, `quiz_feedback_context`), `courses/models.py` (`ExtendedResponseQuestionElement.SUPPORTS_REVEAL`), `courses/views.py` (`_results_question_html`), `templates/courses/elements/extendedresponsequestionelement.html`, `templates/courses/elements/_results_question_feedback.html`
- Test: `tests/test_quiz_reveal_pr3_extended.py` (new)
- Rewrite (allowed, Step 5): tests using extended response as the "unconverted type" example (incl. `tests/test_quiz_reveal_result_line.py`)

**Interfaces:**
- Consumes: Task 2's `_results_question_html` (with `mark_result`); master's `ExtendedResponseQuestionElement.feedback_context` (adds `answered=True`), `_reveal_extendedresponse.html` (reads `mark_result.reveal`, `answered`), `_results_row` (`reveal_template`, `reveal_result`, `answered`, `show_reveal`).
- Produces: `courses.quiz.reveal_list_template(question) -> str | None`; `ExtendedResponseQuestionElement.SUPPORTS_REVEAL = True`; `_results_question_feedback.html` reading an optional `reveal_template` context key (with `row`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_pr3_extended.py
"""Extended response in the quiz answer reveal (spec 2026-09-25 §1.4, §2.1, §4, D7):
Show answer reveals its keyword block; no switch, no key copy, lessons unchanged."""

import pytest
from django.urls import reverse

from courses.models import ChoiceQuestionElement
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionResponse
from courses.quiz import reveal_list_template
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr3_kit import ER_HALF
from tests.reveal_pr3_kit import ER_RIGHT
from tests.reveal_pr3_kit import ER_WRONG
from tests.reveal_pr3_kit import KEYWORDS
from tests.reveal_pr3_kit import extended


def _quiz(client, username="stu"):
    user = make_login(client, username)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


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


def _rows(html):
    return html.split('class="quiz-results__item')[1:]


def test_reveal_list_template_only_for_types_without_an_in_place_view():
    # P6: the keyword block is extended response's view; choice and every key-copy
    # type have an in-place view instead.
    assert reveal_list_template(ExtendedResponseQuestionElement()) == (
        "courses/elements/_reveal_extendedresponse.html"
    )
    assert reveal_list_template(ChoiceQuestionElement()) is None
    assert reveal_list_template(FillBlankQuestionElement()) is None


@pytest.mark.django_db
def test_check_answers_whole_element_with_show_answer_no_keywords(client):
    unit = _quiz(client)
    el = add_element(unit, extended())
    body = _fetch(client, unit, el, ER_HALF).content.decode()
    assert "<form" in body and "data-question-inline" in body
    assert "Partly correct" in body and "2 attempts left" in body
    assert KEYWORDS not in body and "betakw" not in body  # no key before the lock
    assert ">alphakw only</textarea>" in body  # the student's text survives the swap
    assert 'name="reveal"' in body and "data-confirm" in body


@pytest.mark.django_db
def test_reveal_shows_the_keyword_block_and_uses_no_attempt(client):
    unit = _quiz(client)
    el = add_element(unit, extended())
    _fetch(client, unit, el, ER_HALF)
    body = _fetch(client, unit, el, {"reveal": "1", "answer": "ignored"}).content.decode()
    assert KEYWORDS in body and "betakw" in body and "is-missing" in body
    assert "answer shown" in body and "Partly correct" in body
    assert ">alphakw only</textarea>" in body  # the stored answer, not the POST
    assert "data-answer-switch" not in body and "data-answer-key" not in body  # D7
    assert 'name="reveal"' not in body
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.revealed_at is not None and r.attempt_count == 1
    page = _page(client, unit)
    assert KEYWORDS in page and "answer shown" in page


@pytest.mark.django_db
def test_locked_on_last_attempt_shows_keywords_but_not_when_correct(client):
    unit = _quiz(client)
    wrong = add_element(unit, extended(max_attempts=1))
    right = add_element(unit, extended(max_attempts=1))
    assert KEYWORDS in _fetch(client, unit, wrong, ER_WRONG).content.decode()
    assert KEYWORDS not in _fetch(client, unit, right, ER_RIGHT).content.decode()


@pytest.mark.django_db
def test_nojs_reveal_and_previewer_and_editor(client):
    unit = _quiz(client)
    el = add_element(unit, extended())
    client.post(_url(unit, el), ER_WRONG)
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert KEYWORDS in page and "answer shown" in page
    client.logout()
    staff = make_login(client, "prev_er")
    staff.is_staff = True
    staff.save()
    punit = make_quiz_unit()
    pel = add_element(punit, extended())
    body = _fetch(client, punit, pel, {**ER_WRONG, "attempt": "1"}).content.decode()
    assert 'name="reveal"' in body and KEYWORDS not in body
    body = _fetch(client, punit, pel, {**ER_WRONG, "reveal": "1", "attempt": "1"}).content.decode()
    assert KEYWORDS in body and "answer shown" in body
    client.logout()
    pa = make_pa(client, "pa_er")
    course = CourseFactory(owner=pa)
    qunit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    qel = add_element(qunit, extended())
    url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": qel.pk})
    body = client.post(
        url, {**ER_WRONG, "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "<form" in body and 'name="reveal"' in body
    body = client.post(
        url, {**ER_WRONG, "reveal": "1", "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert KEYWORDS in body and body.count("data-question-feedback") == 1
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_never_offer_reveal_or_keywords(client, mode):
    unit = _quiz(client)
    el = add_element(unit, extended(marking_mode=mode))
    body = _fetch(client, unit, el, ER_WRONG).content.decode()
    assert 'name="reveal"' not in body and KEYWORDS not in body
    row = _rows(_results(client, unit))[0]
    assert KEYWORDS not in row and "question__reveal-guide" not in row


@pytest.mark.django_db
def test_results_extended_rows_as_they_ended(client):
    unit = _quiz(client)
    revealed = add_element(unit, extended())
    add_element(unit, extended())  # unanswered
    correct = add_element(unit, extended())
    _fetch(client, unit, revealed, ER_HALF)
    _fetch(client, unit, revealed, {"reveal": "1"})
    _fetch(client, unit, correct, ER_RIGHT)
    rows = _rows(_results(client, unit))
    assert KEYWORDS in rows[0] and "answer shown" in rows[0]
    assert ">alphakw only</textarea>" in rows[0]
    # Spec §4 (PR 3): an unanswered extended-response row shows its keywords.
    assert "question__reveal-guide" in rows[1] and "kw--expected" in rows[1]
    assert KEYWORDS not in rows[2] and "question__reveal-guide" not in rows[2]  # P7
    for row in rows:
        assert "<form" not in row and 'type="submit"' not in row
        assert "<textarea" in row and "disabled" in row.split("<textarea", 1)[1].split(">", 1)[0]


@pytest.mark.django_db
def test_student_text_is_escaped_everywhere(client):
    # Review Focus 3.
    unit = _quiz(client)
    el = add_element(unit, extended())
    raw = {"answer": "<script>x()</script> &amp; alphakw"}
    body = _fetch(client, unit, el, raw).content.decode()
    assert "<script>x()" not in body and "&lt;script&gt;x()" in body
    assert "<script>x()" not in _page(client, unit)
    _fetch(client, unit, el, {"reveal": "1"})
    row = _rows(_results(client, unit))[0]
    assert "<script>x()" not in row and "&lt;script&gt;x()" in row


@pytest.mark.django_db
def test_lesson_check_is_unchanged(client):
    # D11 / §5a: lessons unchanged for extended response -- the fragment, its
    # keyword block, no Show answer; the form now carries data-question-inline (P5).
    student = make_student(client, "ls_er")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    el = add_element(unit, extended())
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    body = client.post(url, ER_WRONG, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "<form" not in body and KEYWORDS in body and 'name="reveal"' not in body
    page = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "data-question-inline" in page and 'name="reveal"' not in page
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr3_extended.py -p no:randomly`
Expected: FAIL — `ImportError: cannot import name 'reveal_list_template'`.

- [ ] **Step 3: Implement**

In `courses/quiz.py`, add above `quiz_feedback_context`:

```python
def reveal_list_template(question):
    """The answer list a locked question shows under its result line, or None
    (spec 2026-09-25 §2.1: None iff the type has an in-place view). In-place views:
    choice's inline ✓ ✗ ＋ (INLINE_QUIZ_REVEAL) and every key-copy type (a
    CONTROLS_TEMPLATE). Extended response has neither -- its keyword block IS its
    view (D7), in the live panel and on the results page."""
    if question.INLINE_QUIZ_REVEAL or question.CONTROLS_TEMPLATE is not None:
        return None
    return question.REVEAL_TEMPLATE
```

In `quiz_feedback_context`, replace

```python
        ctx.update(question.feedback_context(result))
        if question.INLINE_QUIZ_REVEAL or question.SUPPORTS_REVEAL:
            # … (the whole comment)
            ctx["reveal_template"] = None
```

with

```python
        # Reuse the per-type feedback_context (choices, answered) for the reveal;
        # the list itself only for a type with no in-place view (P6).
        ctx.update(question.feedback_context(result))
        ctx["reveal_template"] = reveal_list_template(question)
```

In `courses/models.py`, `ExtendedResponseQuestionElement`, after `RESTORABLE_IN_LESSON = True`:

```python
    # Quiz answer reveal (spec 2026-09-25 §8 PR 3): Show answer + the results-page
    # render. No key copy, no switch: the keyword block stays its view (D7), and
    # lessons are unchanged (no INLINE_LESSON_FEEDBACK).
    SUPPORTS_REVEAL = True
```

`extendedresponsequestionelement.html` becomes:

```django
{% load i18n %}
{% comment %}data-question-inline is unconditional (P5), as on every converted type:
the editor preview renders lesson markup even in a quiz unit, and the quiz try-it
answers with the whole element. A lesson Check still answers with the feedback
fragment (no <form>), which question.js / editor.js land in the feedback box.{% endcomment %}
<div class="el el--question" data-question>
  {% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}
  {% if mode == "results" %}
  <div class="question__form">
    <textarea name="answer" class="question__text-input" rows="6" disabled>{{ submitted_values|default_if_none:'' }}</textarea>
    <div class="question__feedback" data-question-feedback>{{ feedback_html|safe }}</div>
  </div>
  {% elif element %}
  <form class="question__form" method="post" action="{{ action_url }}" data-question-inline>
    {% csrf_token %}
    <textarea name="answer" class="question__text-input" rows="6" maxlength="10000"
              autocomplete="off"
              {% if quiz_submitted or locked %}disabled{% endif %}>{% if element.pk == feedback_for_pk %}{{ submitted_values|default_if_none:'' }}{% endif %}</textarea>
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Submit" %}</button>
    {% include "courses/elements/_reveal_button.html" %}
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

In `courses/views.py::_results_question_html`, replace the `feedback_html = render_to_string(...)` call with:

```python
    feedback_html = render_to_string(
        "courses/elements/_results_question_feedback.html",
        {
            "row": row,
            # Extended response's keyword block (its view, D7), on the rows where
            # the old list page showed it (_results_row's show_reveal, P7).
            "reveal_template": (
                reveal_list_template(question) if row["show_reveal"] else None
            ),
        },
    )
```

and add `from courses.quiz import reveal_list_template` to the module's `courses.quiz` imports (one import per line, isort order).

In `_results_question_feedback.html`, insert directly before the `{% if row.question.explanation … %}` line:

```django
{% if reveal_template %}{% include reveal_template with el=row.question mark_result=row.reveal_result answered=row.answered %}{% endif %}
```

- [ ] **Step 4: Run the file**

Run: `uv run pytest tests/test_quiz_reveal_pr3_extended.py tests/test_quiz_reveal_pr3_choice.py -p no:randomly`
Expected: PASS.

- [ ] **Step 5: Run the suites that pin extended response as unconverted; rewrite**

Run: `uv run pytest tests/test_quiz_reveal_result_line.py tests/test_quiz_reveal_hooks.py tests/test_quiz_reveal_helpers.py tests/test_quiz_lock_rule_parity.py tests/test_element_try.py tests/test_questions_2diii_results.py tests/test_questions_2diii_quiz.py tests/test_questions_2diii_keywords.py tests/test_review_views.py tests/test_review_wording_pl.py tests/test_title_math_assets.py tests/test_quiz_results_render.py tests/test_ephemeral_quiz_feedback.py tests/test_analytics_student_quiz.py tests/test_answer_summary.py tests/test_quiz_reveal_flow.py tests/test_quiz_reveal_results.py -p no:randomly`

Expected RED only under:

(d) a test that used `ExtendedResponseQuestionElement` as its **unconverted** example (bare fragment response, no Show answer, reveal refused, "keeps today's list row") — add `monkeypatch.setattr(ExtendedResponseQuestionElement, "SUPPORTS_REVEAL", False)` at the top of the test (the test's subject is the unconverted-type path, which still exists), keeping every assertion; where the test's point was extended-response-specific (not "unconverted"), assert its NEW behaviour instead (whole element, Show answer, keyword block after reveal);
(e) the results page renders an extended-response row as the question (disabled `<textarea>` + the keyword block in the feedback box) instead of the list row — assert the same keywords / guide classes inside the row.

**Known at plan time** — expect exactly these:

| Test | Old assertion | Rule → rewrite to |
|---|---|---|
| `tests/test_quiz_reveal_result_line.py::test_incorrect_unconverted_non_inline_type_gets_new_line_too` | ER fetch: `"data-question-inline" not in body  # the fragment` | (d) → add `monkeypatch.setattr(ExtendedResponseQuestionElement, "SUPPORTS_REVEAL", False)` (the test's subject is the unconverted-type result line); every assertion kept. Add a sibling `test_incorrect_extended_response_whole_element_line` without the monkeypatch: `"<form" in body`, `'name="reveal"' in body`, `is-incorrect`, "0 / 1", "2 attempts left" |
| `tests/test_quiz_reveal_hooks.py::test_unconverted_type_hooks_are_none` (as rewritten in Task 1) | `ExtendedResponseQuestionElement.SUPPORTS_REVEAL is False` | rename to `test_extended_response_hooks_are_none`; assert `SUPPORTS_REVEAL is True`, keep `part_verdicts(...) is None` and `key_answer() is None` (D7) |

These must stay GREEN unedited: `tests/test_questions_2diii_results.py` (unanswered ER guide on results: `"banned" in body`, `"✓" not in body`; answered keyword block `"✓" in body`; the R badges), the R-mode review / wording / title-math suites (ER-R and choice results rows now go through `render(mode="results")` and `_results_question_feedback.html`). If one goes red on a badge or markup difference, the new results branch is wrong.

Anything RED outside (d), (e) and the table is a bug in this task — fix the code.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --no-cache --fix courses/quiz.py courses/models.py courses/views.py tests/test_quiz_reveal_pr3_extended.py <rewritten> && uv run ruff format --no-cache courses/quiz.py courses/models.py courses/views.py tests/test_quiz_reveal_pr3_extended.py <rewritten> && uv run ruff check --no-cache courses/quiz.py courses/models.py courses/views.py tests/test_quiz_reveal_pr3_extended.py <rewritten>
git add courses/quiz.py courses/models.py courses/views.py templates/courses/elements/extendedresponsequestionelement.html templates/courses/elements/_results_question_feedback.html tests/
git commit -m "feat(quiz-reveal): extended response gets Show answer; its keyword block stays its view"
```

---

### Task 4: Template clean-up — delete the answer lists no path reaches

**Files:**
- Delete: the nine `templates/courses/elements/_reveal_<type>.html` listed in Global Constraints
- Modify: `courses/models.py` (drop nine `REVEAL_TEMPLATE` constants, fix comments), `courses/views.py` (comments only), `templates/courses/elements/_quiz_question_feedback.html` (comment only)
- Test: `tests/test_quiz_reveal_pr3_cleanup.py` (new)
- Rewrite (allowed, Step 6): tests that reference a deleted template or a removed `REVEAL_TEMPLATE`

**Interfaces:**
- Consumes: Tasks 1–3 (all ten types `SUPPORTS_REVEAL`); `tests/reveal_pr2_kit.py` (`KINDS`, `build`), `tests/reveal_pr3_kit.py`.
- Produces: `QuestionElement.REVEAL_TEMPLATE` is `None` on every type except `ExtendedResponseQuestionElement`.

- [ ] **Step 1: Grep every consumer (spec §8: delete only after an empty grep)**

```bash
for t in choice shorttext shortnumeric fillblank dragfill matchpair choicegrid multigrid dragimage; do
  echo "== _reveal_$t.html"; git grep -n "_reveal_$t\b" -- ':!docs/superpowers' ':!.superpowers' || true
done
git grep -n "REVEAL_TEMPLATE\|reveal_template" -- courses templates ':!courses/tests' || true
```

Expected, per template: only its own `REVEAL_TEMPLATE = "…"` line in `courses/models.py`, comments (models.py `choice_marks` docstring is already gone after Task 1; `views.py` `_results_row` comments; `_reveal_choicegrid.html` / `_reveal_multigrid.html` referring to each other), and tests. The generic consumers (`reveal_template` in `QuestionElement.render`, `feedback_context`, `quiz_feedback_context`, `_question_feedback.html`, `_quiz_question_feedback.html`, `quiz_results.html`'s list branch, `_results_question_feedback.html`, `_results_row`) read the constant and stay. If any template-level `{% include "courses/elements/_reveal_<type>.html" %}` or a non-test Python string naming one shows up, STOP and report — the spec forbids deleting it.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_quiz_reveal_pr3_cleanup.py
"""Spec 2026-09-25 §8 PR 3 clean-up: every question type is converted, the answer
lists of the converted types are gone, and every type still renders a wrong lesson
Check and a wrong locked quiz Check without error."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr2_kit import KINDS as PR2_KINDS
from tests.reveal_pr2_kit import build as build_pr2
from tests.reveal_pr3_kit import ER_HALF
from tests.reveal_pr3_kit import choice
from tests.reveal_pr3_kit import extended

ELEMENTS = Path(settings.BASE_DIR) / "templates" / "courses" / "elements"
# The old list markup (every _reveal_* list's classes), minus extended response's
# keyword block and guide.
_LIST = re.compile(
    r"question__reveal(?!-keywords|-guide)[\w-]*|question__nudge|question__tick"
)


def _question_types():
    """Every concrete QuestionElement subclass -- DERIVED, never a pinned list."""
    out, todo = [], list(QuestionElement.__subclasses__())
    while todo:
        cls = todo.pop()
        todo += cls.__subclasses__()
        if not cls._meta.abstract:
            out.append(cls)
    return out


def test_every_question_type_is_converted():
    types = _question_types()
    assert len(types) >= 10
    assert [t.__name__ for t in types if not t.SUPPORTS_REVEAL] == []


def test_only_extended_response_keeps_an_answer_list():
    kept = {t.__name__: t.REVEAL_TEMPLATE for t in _question_types() if t.REVEAL_TEMPLATE}
    assert kept == {
        "ExtendedResponseQuestionElement": "courses/elements/_reveal_extendedresponse.html"
    }


def test_only_the_keyword_list_and_the_button_remain_on_disk():
    assert sorted(p.name for p in ELEMENTS.glob("_reveal_*.html")) == [
        "_reveal_button.html",
        "_reveal_extendedresponse.html",
    ]


def _simple(kind, **kw):
    """(question, wrong POST) for the five non-PR-2 types."""
    kw.setdefault("max_attempts", 1)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(stem=parse("{{11}} {{9}}")[0], **kw)
        Blank.objects.create(question=q, order=0, accepted="11")
        Blank.objects.create(question=q, order=1, accepted="9")
        return q, {"blank": ["11", "5"]}
    if kind == "shorttext":
        return ShortTextQuestionElement.objects.create(stem="?", accepted="Paris", **kw), {
            "answer": "Rome"
        }
    if kind == "shortnumeric":
        return ShortNumericQuestionElement.objects.create(stem="?", value="3.14", **kw), {
            "answer": "2"
        }
    if kind == "choice":
        kit = choice(**kw)
        return kit.question, kit.half
    return extended(**kw), ER_HALF


ALL_KINDS = PR2_KINDS + ("fillblank", "shorttext", "shortnumeric", "choice", "extended")


def _make(kind, **kw):
    if kind in PR2_KINDS:
        kw.setdefault("max_attempts", 1)
        kit = build_pr2(kind, **kw)
        return kit.question, kit.half
    return _simple(kind, **kw)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ALL_KINDS)
def test_wrong_locked_quiz_check_renders_without_a_list(client, kind):
    # Spec §8 PR 3 + §2.1: every type renders a wrong locked quiz Check, and no
    # _reveal_* markup except extended response's keyword block -- in the quiz and
    # on the results page.
    user = make_login(client, f"stu_{kind}")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q, wrong = _make(kind)
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, wrong, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-quiz-locked" in body
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    page = client.get(reverse("courses:quiz_unit", kwargs=kw)).content.decode()
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    results = client.get(reverse("courses:quiz_results", kwargs=kw))
    assert results.status_code == 200
    for html in (body, page, results.content.decode()):
        assert _LIST.findall(html) == []
    if kind == "extended":
        assert "question__reveal-keywords" in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ALL_KINDS)
def test_wrong_lesson_check_renders(client, kind):
    student = make_student(client, f"ls_{kind}")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    q, wrong = _make(kind, max_attempts=None)
    el = add_element(unit, q)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    fetched = client.post(url, wrong, HTTP_X_REQUESTED_WITH="fetch")
    nojs = client.post(url, wrong)
    assert fetched.status_code == 200 and nojs.status_code == 200
    for html in (fetched.content.decode(), nojs.content.decode()):
        assert _LIST.findall(html) == []
        assert 'name="reveal"' not in html  # D11
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr3_cleanup.py -p no:randomly`
Expected: FAIL — `test_only_extended_response_keeps_an_answer_list` (nine extra constants), `test_only_the_keyword_list_and_the_button_remain_on_disk` (nine extra files). `test_every_question_type_is_converted` and the two render tests PASS already (Tasks 1–3 converted everything; the lists are unreachable) — they guard Step 4.

- [ ] **Step 4: Delete**

```bash
git rm templates/courses/elements/_reveal_choice.html templates/courses/elements/_reveal_shorttext.html templates/courses/elements/_reveal_shortnumeric.html templates/courses/elements/_reveal_fillblank.html templates/courses/elements/_reveal_dragfill.html templates/courses/elements/_reveal_matchpair.html templates/courses/elements/_reveal_choicegrid.html templates/courses/elements/_reveal_multigrid.html templates/courses/elements/_reveal_dragimage.html
```

In `courses/models.py`, delete the `REVEAL_TEMPLATE = "courses/elements/_reveal_<type>.html"` line (and a blank line left orphaned by it) on `ChoiceQuestionElement`, `ShortTextQuestionElement`, `ShortNumericQuestionElement`, `FillBlankQuestionElement`, `DragFillBlankQuestionElement`, `MatchPairQuestionElement`, `ChoiceGridQuestionElement`, `MultiGridQuestionElement`, `DragToImageQuestionElement`. Change the base line to `REVEAL_TEMPLATE = None  # the answer list of a type with no in-place view (only extended response)`. In `ChoiceQuestionElement`: replace the comment above `INLINE_QUIZ_REVEAL = True` with `# A locked quiz marks its OPTIONS LIST inline (see choice_marks) -- its in-place view (courses.quiz.reveal_list_template).`; in `render()`, replace `"reveal_template": None if mode == "lesson" else self.REVEAL_TEMPLATE,` and its 3-line comment with `"reveal_template": None,  # no answer list: the options are marked in place`.

In `courses/views.py::_results_row`, replace the comment `# exists so the per-blank ✓/✗ in _reveal_fillblank reflects …` block with `# The student's answer is marked when one exists (analytics' per-part ✓/✗ reads it); an unanswered question marks an empty answer ("reveal all").` — code unchanged. In `check_answer`, the comment "render() sets reveal_template=None for lesson mode -> no bottom reveal list." stays true; leave it.

In `_quiz_question_feedback.html`, reword the list comment to: `{% comment %}Only a type with no in-place view has a list here (extended response's keyword block, courses.quiz.reveal_list_template), and only once locked.{% endcomment %}`.

- [ ] **Step 5: Run the clean-up file**

Run: `uv run pytest tests/test_quiz_reveal_pr3_cleanup.py -p no:randomly`
Expected: PASS.

- [ ] **Step 6: Run every suite that touches a deleted template or `REVEAL_TEMPLATE`; rewrite**

Run: `uv run pytest tests/test_render_choice_nudge.py tests/test_reveal_choicegrid.py tests/test_quiz_reveal_single_part.py tests/test_questions_2d_models.py tests/test_choice_nudge_paths.py tests/test_questions_2d_reveal.py tests/test_questions_2d_results.py tests/test_questions_2diii_results.py tests/test_quiz_results_choice_reveal.py tests/test_quiz_reveal_flow.py tests/test_quiz_reveal_results.py tests/test_quiz_reveal_pr2_flow.py tests/test_quiz_reveal_pr2_grids.py tests/test_choicegrid_styles.py tests/test_analytics_student_quiz.py -p no:randomly` (a file you delete in Step 6 drops out of the command)

Expected RED only under:

(f) a test that renders a deleted `_reveal_<type>.html` directly (`render_to_string` / `get_template`) or asserts a type's `REVEAL_TEMPLATE` value — when the test's subject is the deleted template itself, delete the test and name it in the commit message (the one allowed deletion); when it pins a behaviour the in-place view now carries, rewrite it to assert that behaviour through the question's render;
(g) a test that relied on a converted type's `REVEAL_TEMPLATE` to exercise the generic list path (`_question_feedback.html`, `quiz_results.html`'s `{% else %}` row) — switch it to extended response (with `SUPPORTS_REVEAL` monkeypatched `False` for the results list row).

**Known at plan time** — expect exactly these:

| Test | Old assertion | Rule → rewrite to |
|---|---|---|
| `tests/test_render_choice_nudge.py` (both tests) | `render_to_string("courses/elements/_reveal_choice.html", …)` | (f) → delete the file (its subject is the deleted template); the results-page nudge is pinned by `tests/test_choice_nudge_paths.py::test_choice_nudge_on_results_page` and `test_results_option_feedback_shows_on_marked_options` |
| `tests/test_reveal_choicegrid.py` (all three tests) | renders `_reveal_choicegrid.html` | (f) → delete the file; the grid's results row is pinned by PR 2's `tests/test_quiz_reveal_pr2_grids.py` |
| `tests/test_quiz_reveal_single_part.py::test_numeric_key_copy_tolerance_matches_old_reveal_in_pl` | renders `_reveal_shortnumeric.html` as `old` and compares | (f) → drop `old`; assert the key copy's tolerance text is exactly `"0.25"` under `translation.override("pl")` (the value the old template printed, unfiltered, spec §2.2); rename to `test_numeric_key_copy_tolerance_unfiltered_in_pl` |
| `tests/test_questions_2d_models.py` (the two `REVEAL_TEMPLATE ==` lines, dragfill + matchpair) | `q.REVEAL_TEMPLATE == "courses/elements/_reveal_dragfill.html"` / `_reveal_matchpair.html` | (f) → `q.REVEAL_TEMPLATE is None` (the in-place view replaced the list; `test_only_extended_response_keeps_an_answer_list` is the registry guard) |

`tests/test_choicegrid_styles.py`'s `".question__reveal--grid" in css` stays GREEN: the CSS is not pruned (P8). Name the two deleted files in the commit message.

Anything RED outside (f), (g) and the table is a bug — fix the code.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache --fix courses/models.py courses/views.py tests/test_quiz_reveal_pr3_cleanup.py <rewritten> && uv run ruff format --no-cache courses/models.py courses/views.py tests/test_quiz_reveal_pr3_cleanup.py <rewritten> && uv run ruff check --no-cache courses/models.py courses/views.py tests/test_quiz_reveal_pr3_cleanup.py <rewritten>
git add -A templates/courses/elements courses/models.py courses/views.py tests/
git commit -m "refactor(quiz-reveal): delete the nine answer lists no path reaches"
```

---

### Task 5: Browser checks — choice and extended response end to end

**Files:**
- Create: `tests/test_e2e_quiz_reveal_pr3.py`
- Modify (only if a test finds a real bug): `courses/static/courses/css/courses.css`, the two element templates
- Rewrite (allowed, Step 3): e2e tests pinning choice's "nothing marked while attempts remain" or extended response's fragment-only quiz response

**Interfaces:**
- Consumes: Tasks 1–4; `tests/test_e2e_quiz_reveal.py`'s helper pattern (`_student`, `_login`, `DJANGO_ALLOW_ASYNC_UNSAFE` fixture); PR 1's author helpers `tests/test_e2e_questions.py::_make_pa_user` and `_editor_url` (as `tests/test_e2e_quiz_reveal.py::test_editor_try_it_reveal_switch_survives_freeze` uses them).
- Produces: nothing later tasks consume.

- [ ] **Step 1: Write the e2e tests**

```python
# tests/test_e2e_quiz_reveal_pr3.py
"""Playwright: multiple choice and extended response in the quiz answer reveal
(spec 2026-09-25 §1, §3.1, §4, D7, D8)."""

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


def _seed(username, slug, maker, unit_type="quiz"):
    from django.contrib.auth import get_user_model

    from courses.models import Element
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug)
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="Q"
    )
    q = maker()
    Element.objects.create(unit=unit, content_object=q)
    return course, unit


def _url(live_server, course, unit, unit_type="quiz"):
    tail = "quiz/" if unit_type == "quiz" else ""
    return f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/{tail}"


def _check(q):
    q.locator("button[type='submit']:not([name='reveal'])").click()


def _reveal(page, q):
    # Register BEFORE the click: Playwright auto-dismisses a confirm (memory
    # playwright-auto-dismisses-confirm), which would silently cancel the reveal.
    page.once("dialog", lambda d: d.accept())
    q.locator("button[name='reveal']").click()


@pytest.mark.django_db(transaction=True)
def test_choice_marks_picks_then_show_answer_adds_missed(browser, live_server):
    from tests.reveal_pr3_kit import choice

    _student("c_stu")
    course, unit = _seed("c_stu", "e2e-pr3-choice", lambda: choice().question)
    page = browser.new_context().new_page()
    _login(page, live_server, "c_stu")
    page.goto(_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    q.get_by_label("Alphaopt").check()
    q.get_by_label("Gammaopt").check()
    _check(q)
    q.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    ok = q.locator(".question__choice-marker--correct")
    bad = q.locator(".question__choice-marker--wrong")
    assert ok.count() == 1 and bad.count() == 1
    assert q.locator(".question__choice-marker--missed").count() == 0
    colour = "el => getComputedStyle(el).color"
    assert ok.evaluate(colour) != bad.evaluate(colour)  # measured, not just classed
    # The marker sits on the option's own line (P3): same row as the option text.
    top = "el => Math.round(el.getBoundingClientRect().top)"
    text = q.locator(".question__choice", has=ok).locator(".question__choice-text")
    assert abs(ok.evaluate(top) - text.evaluate(top)) < 12
    # quiz.js keeps the client counter on [data-question] (set after a Check).
    assert q.get_attribute("data-attempts-made") == "1"
    _reveal(page, q)
    q.locator(".question__choice-marker--missed").wait_for(timeout=6000)
    assert q.locator(".question__choice-marker--missed").count() == 1
    assert "answer shown" in q.inner_text()
    assert q.get_attribute("data-attempts-made") == "1"  # a reveal is no attempt
    assert q.locator("[data-answer-switch]").count() == 0  # D8
    for box in q.locator("input[name='choice']").all():
        assert box.is_disabled()


@pytest.mark.django_db(transaction=True)
def test_extended_show_answer_reveals_keywords(browser, live_server):
    from tests.reveal_pr3_kit import extended

    _student("e_stu")
    course, unit = _seed("e_stu", "e2e-pr3-er", extended)
    page = browser.new_context().new_page()
    _login(page, live_server, "e_stu")
    page.goto(_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    q.locator("textarea[name='answer']").fill("alphakw only")
    _check(q)
    q.locator(".question__verdict.is-partial").wait_for(timeout=6000)
    assert q.locator(".question__reveal-keywords").count() == 0
    assert q.locator("form form").count() == 0
    _reveal(page, q)
    q.locator(".question__reveal-keywords").wait_for(timeout=6000)
    assert q.locator("textarea[name='answer']").is_disabled()
    assert q.locator("textarea[name='answer']").input_value() == "alphakw only"
    assert "answer shown" in q.inner_text()


@pytest.mark.django_db(transaction=True)
def test_extended_lesson_check_lands_in_the_box(browser, live_server):
    # Review Focus 4: data-question-inline + a fragment response (P5).
    from tests.reveal_pr3_kit import extended

    _student("el_stu")
    course, unit = _seed("el_stu", "e2e-pr3-erl", extended, unit_type="lesson")
    page = browser.new_context().new_page()
    _login(page, live_server, "el_stu")
    page.goto(_url(live_server, course, unit, unit_type="lesson"))
    q = page.locator("[data-question]").first
    q.locator("textarea[name='answer']").fill("nothing relevant")
    _check(q)
    box = q.locator("[data-question-feedback]")
    box.locator(".question__reveal-keywords").wait_for(timeout=6000)
    assert q.locator("form form").count() == 0
    assert q.locator("textarea[name='answer']").input_value() == "nothing relevant"


@pytest.mark.django_db(transaction=True)
def test_results_page_shows_choice_marks_and_keywords(browser, live_server):
    from courses.models import Element
    from tests.reveal_pr3_kit import choice
    from tests.reveal_pr3_kit import extended

    _student("r_stu")
    course, unit = _seed("r_stu", "e2e-pr3-res", lambda: choice(max_attempts=1).question)
    Element.objects.create(unit=unit, content_object=extended(max_attempts=1))
    page = browser.new_context().new_page()
    _login(page, live_server, "r_stu")
    page.goto(_url(live_server, course, unit))
    q1, q2 = page.locator("[data-question]").nth(0), page.locator("[data-question]").nth(1)
    q1.get_by_label("Gammaopt").check()
    _check(q1)
    q1.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    q2.locator("textarea[name='answer']").fill("nothing relevant")
    _check(q2)
    q2.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())  # Finish asks (data-confirm)
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=6000)
    assert page.locator(".quiz-results__item form").count() == 0
    assert page.locator(".question__choice-marker--missed").count() == 2
    assert page.locator(".question__reveal-keywords").count() == 1
    for box in page.locator(".quiz-results__item input, .quiz-results__item textarea").all():
        assert box.is_disabled()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("unit_type", ["quiz", "lesson"])
def test_editor_try_it_extended(browser, live_server, unit_type):
    # The editor preview renders lesson markup in both unit types (P5): the quiz
    # try-it answers with the whole element (swap + freeze), the lesson try-it with
    # the fragment (the no-<form> fall-through). Pattern: PR 1's
    # tests/test_e2e_quiz_reveal.py::test_editor_try_it_reveal_switch_survives_freeze.
    from courses.models import Element
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.reveal_pr3_kit import extended
    from tests.test_e2e_questions import _editor_url
    from tests.test_e2e_questions import _make_pa_user

    owner = _make_pa_user(f"er_author_{unit_type}")
    course = CourseFactory(slug=f"e2e-pr3-er-editor-{unit_type}", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="Q"
    )
    Element.objects.create(unit=unit, content_object=extended())
    page = browser.new_context().new_page()
    _login(page, live_server, f"er_author_{unit_type}")
    page.goto(_editor_url(live_server, unit))
    q = page.locator('[data-scope="preview"] [data-question]').first
    q.locator("textarea[name='answer']").fill("nothing relevant")
    _check(q)
    if unit_type == "lesson":
        q.locator("[data-question-feedback] .question__reveal-keywords").wait_for(
            timeout=6000
        )
        assert q.locator("form form").count() == 0
        assert q.locator("[data-reveal-btn]").count() == 0  # D11
        return
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)
    assert q.locator(".question__reveal-keywords").count() == 0  # not before the lock
    _reveal(page, q)
    q.locator(".question__reveal-keywords").wait_for(timeout=6000)
    assert q.locator("textarea[name='answer']").is_disabled()  # editor freeze
    assert q.locator("textarea[name='answer']").input_value() == "nothing relevant"
    assert q.locator("form form").count() == 0
    assert q.locator("[data-answer-switch]").count() == 0  # D7
    assert q.get_attribute("data-attempts-made") == "1"
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_e2e_quiz_reveal_pr3.py -m e2e -p no:randomly`
Expected: PASS. A failure here is a product bug unless it is a selector the notes above told you to verify — fix the product (template / CSS), never loosen a test assertion.

- [ ] **Step 3: Run the existing e2e suites for choice and extended response; rewrite**

Run: `uv run pytest tests/test_e2e_questions.py tests/test_e2e_quiz_choice_marking.py tests/test_e2e_choice_inline_feedback.py tests/test_e2e_questions_2diii.py tests/test_e2e_results.py tests/test_e2e_quiz_math.py tests/test_e2e_quiz_reveal.py tests/test_e2e_nested_question.py -m e2e -p no:randomly`

Expected RED only under rules (a)–(e) above (their e2e twins). Known at plan time:

| Test | Old assertion | Rule → rewrite to |
|---|---|---|
| `tests/test_e2e_questions.py::test_preview_quiz_gating_withholds_then_reveals` | `pq.locator(".question__choice-marker").count() == 0` after attempt 1; two bare `pq.locator("button[type='submit']").click()` (now a strict-mode violation: Show answer is a second submit button); after attempt 2 it waits for `--wrong`, which is already true after attempt 1 | (a) → after attempt 1: the picked option's `.question__choice-marker--wrong` count 1 and `.question__choice-marker--missed` count 0; both clicks use `button[type='submit']:not([name='reveal'])`; after attempt 2 wait for something NEW — `.question__choice-marker--missed` (or `[data-quiz-locked]`) — never for a condition already true (memory `tests-that-sample-race-windows`) |
| `tests/test_e2e_quiz_choice_marking.py::test_nothing_is_marked_while_attempts_remain` | `expect(page.locator(".question__choice-marker")).to_have_count(0)` | (a) → the picked option's `--wrong` count 1, `.question__choice-marker--missed` count 0, the unpicked options carry no marker; keep `--picked` count 0 and the inputs `to_be_enabled()`; rename to `test_only_the_pick_is_marked_while_attempts_remain` |

These must stay GREEN unedited: `tests/test_e2e_questions_2diii.py` (the keyword block `.kw--required` in the quiz feedback after the lock; no key on an R results row), `tests/test_e2e_quiz_math.py` (math in a results row now rendered through the element), `tests/test_e2e_choice_inline_feedback.py` and `tests/test_e2e_nested_question.py` (lessons unchanged).

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check --no-cache --fix tests/test_e2e_quiz_reveal_pr3.py <rewritten> && uv run ruff format --no-cache tests/test_e2e_quiz_reveal_pr3.py <rewritten> && uv run ruff check --no-cache tests/test_e2e_quiz_reveal_pr3.py <rewritten>
git add tests/ courses/static templates
git commit -m "test(quiz-reveal): choice and extended response end to end"
```

---

### Task 6: Translations check + author help

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `django.mo` (only if Step 1 finds a new msgid)
- Modify: `docs/help/course-admin/quiz-editors.md`, `docs/help/course-admin/quiz-editors.pl.md`

PR 3 is designed to add **no new UI string** (choice reuses `MARK_GLYPHS` and PR 1's button/line strings; extended response reuses its keyword strings) — but Task 4's deletions drop six msgids. Spec §8 requires the i18n step.

- [ ] **Step 1: Extract and verify**

```bash
uv run python manage.py makemessages -l pl --no-obsolete
git diff --stat locale/
git diff locale/pl/LC_MESSAGES/django.po | tr -d '\r' | grep -E '^[+-](msgid|msgstr|#, fuzzy)' || echo "no msgid changes"
```

Expected: no NEW msgid; the msgids that lived only in the deleted templates are dropped (`--no-obsolete`), known at plan time: `Correct token:`, `Correct label:`, `Correct match:`, `Correct answers:`, `Expected:`, `you chose`. `Correct answer:` must SURVIVE (`analytics_student_quiz.html` uses it). For every dropped msgid, `git grep -n "<msgid text>" -- templates courses` must come back empty; a dropped msgid still used somewhere is a bug. If a new msgid appeared, translate it (clear any `#, fuzzy` pre-fill — both the flag and its wrong msgstr) and list it in the PR description. Then `uv run python manage.py compilemessages -l pl`.

Two i18n tests list dropped msgids as parameters and go RED — rewrite (the msgid no longer exists, so the parameter is removed; the remaining parameters stay):

| Test | Change |
|---|---|
| `tests/test_i18n_questions_2b.py` (the translated-msgid parametrisation) | drop the `"Expected:"` parameter; `"Correct answer:"` stays |
| `tests/test_i18n_questions_2dii.py` (the translated-msgid parametrisation) | drop the `"Correct label:"` parameter |

`tests/test_i18n_po_health.py` (forbids obsolete entries) must be GREEN after the regeneration.

- [ ] **Step 2: Help text**

EN (`quiz-editors.md`):

1. In the quiz paragraph under the editor screenshot, after "…on the question itself." insert: "Multiple choice and extended response show the answer their own way — see their sections below."
2. In `{el:choice-single}{el:choice-multi}`, replace the whole "- In a **quiz**, the correct answers are always revealed …" bullet with:
   "- In a **quiz**, every Check marks the options the student ticked with ✓ (right) or ✗ (wrong); a correct option they did not tick is not pointed out while they can still try again. Once the question ends — a correct answer, the last attempt, or **Show answer** — the correct options they missed get ＋, and the results page shows the same marks. There is no Your answer / Correct answer switch for this type: the marks on the options are its answer view. Per-option feedback appears once the question has ended."
3. At the end of `{el:extended}`, add a paragraph:
   "In a **quiz**, an auto-marked extended response has **Show answer** too. It ends the question and shows the keyword list — which required keywords the answer contains and which forbidden ones it uses — instead of a Your answer / Correct answer switch. The same list appears when the question ends on its last attempt without full marks, and on the results page. In a **lesson** nothing changes."

PL (`quiz-editors.pl.md`), the same three places:

1. "Pytania wyboru i rozszerzona odpowiedź pokazują odpowiedź na swój sposób — zobacz ich sekcje poniżej."
2. "- W **quizie** każde sprawdzenie oznacza zaznaczone przez ucznia odpowiedzi znakiem ✓ (dobrze) lub ✗ (źle); poprawna odpowiedź, której nie zaznaczył, nie jest wskazywana, dopóki może jeszcze próbować. Gdy pytanie się zakończy — po poprawnej odpowiedzi, ostatniej próbie albo po **Pokaż odpowiedź** — pominięte poprawne odpowiedzi dostają znak ＋, a strona wyników pokazuje te same oznaczenia. Ten typ nie ma przełącznika Twoja odpowiedź / Poprawna odpowiedź: oznaczenia przy odpowiedziach są jego widokiem odpowiedzi. Informacja zwrotna dla opcji pojawia się po zakończeniu pytania."
3. "W **quizie** rozszerzona odpowiedź oceniana automatycznie również ma przycisk **Pokaż odpowiedź**. Kończy on pytanie i pokazuje listę słów kluczowych — które wymagane słowa odpowiedź zawiera, a których zabronionych używa — zamiast przełącznika Twoja odpowiedź / Poprawna odpowiedź. Ta sama lista pojawia się, gdy pytanie zakończy się na ostatniej próbie bez pełnej liczby punktów, oraz na stronie wyników. W **lekcji** nic się nie zmienia."

(Match the button label and switch labels to the ones the `.po` actually uses — `grep -n -A1 'msgid "Show answer"\|msgid "Your answer"\|msgid "Correct answer"' locale/pl/LC_MESSAGES/django.po` — and the bold style the surrounding help uses. "W lekcji", never "Na lekcji".) Flag the Polish text for the owner in the PR description.

- [ ] **Step 3: Run the help and i18n suites**

Run: `uv run pytest tests/test_i18n_quiz_reveal.py tests/test_i18n_quiz.py tests/test_i18n_results.py tests/test_i18n_questions_2b.py tests/test_i18n_questions_2dii.py tests/test_i18n_po_health.py tests/test_help.py tests/test_help_capture_isolation.py -p no:randomly`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
uv run ruff check --no-cache --fix tests/test_i18n_questions_2b.py tests/test_i18n_questions_2dii.py && uv run ruff format --no-cache tests/test_i18n_questions_2b.py tests/test_i18n_questions_2dii.py
git add locale docs/help tests/test_i18n_questions_2b.py tests/test_i18n_questions_2dii.py
git commit -m "docs(quiz-reveal): multiple choice and extended response in quizzes; drop the deleted lists' msgids"
```

---

### Task 7: Branch gate — mutants, screenshots, full sweep

**Files:** none new (fixes only, if the gate finds something).

- [ ] **Step 1: Mutants (each must turn a test RED; revert every mutant BY HAND, then `git diff` must be empty)**

| Mutant | Must fail |
|---|---|
| `ChoiceQuestionElement.part_verdicts`: `(c.pk in correct)` for EVERY option (drop the picked-only rule) | `test_part_verdicts_one_entry_per_option_picked_only`, `test_unlocked_wrong_check_marks_picks_and_leaks_nothing` |
| `choice_marks`: the `missed` loop without `locked and` | `test_choice_marks_unlocked_quiz_reads_verdicts_never_mark_result` (every unlocked view path passes `mark_result=None`, so only the direct call sees it) |
| `choice_marks`: drop `and not mark_result.correct` | `test_stored_correct_then_key_edited_shows_picks_correct_no_missed`, `test_results_stored_correct_key_edited_choice_shows_picks_correct` |
| `choice_marks`: ignore `verdicts` (always the `elif locked` branch) | `test_unlocked_wrong_check_marks_picks_and_leaks_nothing`, `test_resume_nojs_previewer_and_editor_paint_the_same` |
| `quiz_render_state`: `"mark_result": result` (drop `if locked`) | `test_unlocked_render_context_has_no_mark_result`, `test_option_feedback_waits_for_the_lock` |
| `ChoiceQuestionElement.render`: `marked_layout` back to `show_picks` | `test_unlocked_wrong_check_marks_picks_and_leaks_nothing`, `test_choice_marks_picks_then_show_answer_adds_missed` (layout) |
| `_choicequestion_options.html`: `--picked` when `c.pk in selected_ids` regardless of `show_picks` | `test_unlocked_wrong_check_marks_picks_and_leaks_nothing` |
| `ChoiceQuestionElement.SUPPORTS_REVEAL = False` | `test_show_answer_offered_after_a_wrong_check_check_first`, `test_results_choice_rows_as_they_ended` |
| `_results_question_html`: no `mark_result` for unanswered rows | `test_results_choice_rows_as_they_ended` (unanswered ＋) |
| `choicequestion.html`: add a `<button type="submit">` inside the results `<div>` | `test_results_choice_rows_as_they_ended` |
| `ExtendedResponseQuestionElement.SUPPORTS_REVEAL = False` | `test_check_answers_whole_element_with_show_answer_no_keywords`, `test_reveal_shows_the_keyword_block_and_uses_no_attempt` |
| `reveal_list_template`: return `None` always | `test_reveal_shows_the_keyword_block_and_uses_no_attempt`, `test_results_extended_rows_as_they_ended`, `test_reveal_list_template_only_for_types_without_an_in_place_view` |
| `quiz_feedback_context`: back to `if question.INLINE_QUIZ_REVEAL or question.SUPPORTS_REVEAL: ctx["reveal_template"] = None` | `test_reveal_shows_the_keyword_block_and_uses_no_attempt` |
| `_results_question_html`: `reveal_template` without the `show_reveal` gate | `test_results_extended_rows_as_they_ended` (correct row, P7) |
| `extendedresponsequestionelement.html`: drop `data-question-inline` | `test_check_answers_whole_element_with_show_answer_no_keywords`, `test_extended_show_answer_reveals_keywords` |
| `extendedresponsequestionelement.html` results branch: `{{ submitted_values|safe }}` | `test_student_text_is_escaped_everywhere` |
| `extendedresponsequestionelement.html` results branch: textarea without `disabled` | `test_results_extended_rows_as_they_ended`, `test_results_page_shows_choice_marks_and_keywords` |
| restore `templates/courses/elements/_reveal_choice.html` (any content) | `test_only_the_keyword_list_and_the_button_remain_on_disk` |
| `ShortTextQuestionElement.REVEAL_TEMPLATE = "courses/elements/_reveal_extendedresponse.html"` | `test_only_extended_response_keeps_an_answer_list` |
| `ShortTextQuestionElement.SUPPORTS_REVEAL = False` | `test_every_question_type_is_converted` |

Record each mutant's RED test name in the PR description; a survivor is either killed by a new test or listed with the reason.

- [ ] **Step 2: Screenshots**

Write a throwaway e2e in `tests/test_e2e_zz_shot_tmp.py` (set `DJANGO_ALLOW_ASYNC_UNSAFE`; set `user.theme` to `"light"` / `"dark"` — the cookie is not enough, memory `dialog-does-not-inherit-the-page-theme`) capturing: a multiple-choice question after a wrong Check with attempts left (✓/✗ inline, no ＋), the same after Show answer (✓ ✗ ＋ + tinted picks), a single-choice (radio) wrong Check, an extended response after Show answer, and the results page with a choice row (answered + unanswered) and an extended-response row. Read each PNG; judge dark mode separately (memory `verify-ui-with-screenshots`). Delete the file.

- [ ] **Step 3: Full sweep (the branch gate)**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run ruff check --no-cache . && uv run ruff format --check --no-cache .
uv run python manage.py makemigrations --check --dry-run
```

Run the non-e2e suite in ~4 chunks (one run at a time), then the e2e suite in chunks with `-m e2e`. Grep each run's summary line; do not trust the exit code alone (memories `pytest-exit-code-can-lie`, `full-suite-run-is-oom-killed`).

- [ ] **Step 4: Re-sync with master**

```bash
git fetch origin && git rebase origin/master
uv run python manage.py makemessages -l pl --no-obsolete && uv run python manage.py compilemessages -l pl
```

Regenerate the `.mo` rather than resolving a binary conflict. If `git status` then shows `locale/` changes, commit them (`git add locale && git commit -m "i18n: regenerate catalog after rebase"`). Re-run the four `tests/test_quiz_reveal_pr3_*.py` / `tests/test_e2e_quiz_reveal_pr3.py` files after the rebase.

- [ ] **Step 5: Commit gate fixes; stop before pushing**

Commit any fix. **Do not push or open the PR** until the owner has seen the screenshots and the plan-time decisions P1–P8. PR description then: summary, the D1–D13 reference, P1–P8, the mutant table, the deleted templates, screenshots note, the CSS follow-up (P8), "Please check the Polish help text".

---

## Self-review notes (for the executor)

- **Spec coverage (PR 3 scope):** §2.1 choice `part_verdicts` pinned + no-leak test + `mark_result` None unlocked → Task 1; choice `choice_marks` unlocked case → 1; `SUPPORTS_REVEAL` on both → 2, 3; `reveal_template = None` iff in-place view → 3 (P6); "no `_reveal_*` markup except extended response's keyword block, quiz and results" → 4; §2.2 `key_answer() = None` for both, no copy / switch → 1, 2, 3 (asserted); §2.4 whole-element responses (choice already; extended response now) + validation stays a fragment (master) → 3; §2.6 reverse case for choice → 1, 2 (P4); §3 Show answer (enrolled, no-JS, previewer, editor; N/R refused) → 2, 3; §4 results rows incl. unanswered choice ＋ and unanswered extended-response keywords → 2, 3; §5 analytics unchanged → 2 (+ the existing analytics suites in the run lists); §5a lessons unchanged for both → 3, 4; §7 e2e + mutants → 5, 7; §8 PR 3 clean-up (grep, delete, `_reveal_extendedresponse.html` stays, every-type lesson + locked-quiz render test) → 4; i18n + help → 6.
- **Out of PR 3 (do not do):** choice partial credit (D9), a switch for choice (D8), any lesson change for these two types (D11), removing the `SUPPORTS_REVEAL` flag or the unconverted-type code paths, deleting CSS (P8), folding `courses/fillblank.py::render_inputs` into `courses/verdicts.py` (not in spec §8).
- If a task's snippet disagrees with the file at execution time (drift, a renamed helper), the SPEC wins over the snippet; stop and report if they conflict on behaviour.
