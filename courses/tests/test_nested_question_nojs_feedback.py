"""No-JS feedback for a question nested in a container, across all five containers.

THE CONTRACT: a question nested inside any of the five containers gets the same
no-JS verdict its top-level twin gets, including for a BLANK answer.

check_answer's no-JS path re-renders the whole lesson with a page-level
`feedback_for_pk` / `mark_result`, and _lesson_article.html:39 hands those to every
TOP-LEVEL element. Reaching a nested one used to be impossible, because THREE layers
each dropped the values: render_element's non-question branch called the container's
`render()` with only (element, state, slug, node_pk); the container's `render()`
builds a FRESH context dict (a container render is a CONTEXT BARRIER); and the
container template's bare `{% render_element child %}` reads nothing the barrier did
not re-emit. Forwarding at the template layer ALONE is a proven no-op, verified by
mutation -- which is why the fix re-emits a `page` dict at the barrier instead.

Before the fix, a nested question showed feedback only via the practice-state RESTORE
branch (courses_extras.py:55-85), which needs a STORED answer -- and a blank answer
stores nothing (views.py:1059-1060 clears the key instead). That is why the BLANK
case is the one that proves the fix: the non-blank case below was already green
through the restore branch and proves nothing about the seam.

Falsification history: replacing `answer_is_empty(answer)` at views.py:1060 with
`False` (so a blank answer is stored) made the old absence test RED for every
container, pinning the mechanism rather than the symptom -- and is exactly the
one-liner the spec rejects, since storing a deliberately blanked answer would make
it come back as "Incorrect" after reload for TOP-LEVEL questions too. An earlier
draft asserted `data-question="{pk}"` and passed vacuously -- that attribute is bare
and carries no pk -- which is why the structural guards below assert the nested
question really rendered.
"""

import re

import pytest
from django.urls import reverse

from courses.models import BeforeAfterElement
from courses.models import Blank
from courses.models import CalloutElement
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillBlankQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TwoColumnElement
from courses.views import build_quiz_context
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_quiz_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db

VERDICT = "question__verdict"


def _fill_blank():
    q = FillBlankQuestionElement.objects.create(stem="Cap is {{paris}}.")
    Blank.objects.create(question=q, order=1, accepted="paris")
    return q


# name -> (build_container() -> (concrete, slot_id), child wrapper class).
# The wrapper class is the structural guard: it proves the container rendered the
# child at all, so `VERDICT not in body` cannot pass because nothing was there.
def _callout():
    return CalloutElement.objects.create(kind="example"), CalloutElement.SLOT_ID


def _spoiler():
    return SpoilerElement.objects.create(label="s"), SpoilerElement.SLOT_ID


def _tabs():
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    return obj, obj.data["tabs"][0]["id"]


def _two_column():
    obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    return obj, obj.data["columns"][0]["id"]


def _before_after():
    # AFTER slot deliberately: resolved_slots() APPENDS a child with an unrecognised
    # tab_id to the `before` bucket, so a before-slot fixture would still render even
    # if the slot id were wrong -- the after slot is the one that proves the wiring.
    return BeforeAfterElement.objects.create(), BeforeAfterElement.AFTER_SLOT_ID


CONTAINERS = [
    pytest.param(_callout, "callout__child", id="callout"),
    pytest.param(_spoiler, "spoiler__child", id="spoiler"),
    pytest.param(_tabs, "tabs__child", id="tabs"),
    pytest.param(_two_column, "twocolumn__child", id="two_column"),
    pytest.param(_before_after, "ba__child", id="before_after"),
]


def _choice(feedback=""):
    q = ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False)
    right = Choice.objects.create(
        question=q, text="right", is_correct=True, feedback=feedback
    )
    Choice.objects.create(question=q, text="wrong", is_correct=False, feedback=feedback)
    # Read by the type-axis discriminator below: `name="choice"` alone is satisfied by
    # ANY choice question on the page, so the correct option's pk is what makes the
    # assertion non-vacuous. `feedback` defaults to "" so the factory stays a
    # zero-argument callable for TYPES; the invariant-B test passes a real string,
    # because `mark_result.annotated` only ever holds options that carry feedback.
    q._correct_pk = right.pk
    return q


def _short_text():
    return ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")


def _short_numeric():
    return ShortNumericQuestionElement.objects.create(
        stem="2+2?", value="4", tolerance="0"
    )


# (factory, blank POST, present-substrings, absent-substrings).
#
# The blank POST must be EXACT or answer_is_empty never fires and the test proves
# nothing:  choice -> post.getlist("choice"), so NO "choice" key at all;
# short_text/short_numeric -> post.get("answer", ""), so {"answer": ""}.
#
# The discriminators prove the right WIDGET rendered -- without them the three
# parametrized cases are indistinguishable from one another, because choice,
# short_text and short_numeric all render the byte-identical wrapper
# `<div class="el el--question" data-question>` and only fill_blank has a type class.
# shortnumericquestionelement.html:8 renders inputmode="text";
# shorttextquestionelement.html:8 renders no inputmode at all -- hence one
# present-assertion and one absent-assertion.
TYPES = [
    pytest.param(_choice, {}, ['name="choice"', "VALUE_PK"], [], id="choice"),
    pytest.param(
        _short_text, {"answer": ""}, ['name="answer"'], ["inputmode"], id="short_text"
    ),
    pytest.param(
        _short_numeric,
        {"answer": ""},
        ['name="answer"', 'inputmode="text"'],
        [],
        id="short_numeric",
    ),
]


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _child_slice(body, wrapper_class, index=0):
    """The markup inside ONE container child wrapper, tag-depth matched.

    The three widened types render byte-identical markup
    (`<div class="el el--question" data-question>`) -- only fill_blank has a type
    class -- so the nested render is identified by POSITION, not by class.

    A naive `body.index("</div>", start)` is WRONG and silently guts every
    assertion built on it: each question template opens
    `<div class="el el--question" data-question>` and then
    `<div class="question__stem">`, so the first closing tag belongs to the STEM.
    The slice would end mid-question, containing no <form>, no inputs and no
    verdict -- and every `... in slice_` assertion would fail against a CORRECT
    implementation.

    `index` picks the Nth wrapper of that class in document order; the default 0 is
    the FIRST, which is why every test that slices a callout creates the question it
    checks first (lowest order/pk). The invariant-B test is the only caller that
    needs index=1, to reach the unchecked sibling.
    """
    open_tag = f'<div class="{wrapper_class}">'
    start = -1
    for _ in range(index + 1):
        start = body.index(open_tag, start + 1)
    i, depth = start + len(open_tag), 1
    while depth:
        nxt_open = body.find("<div", i)
        nxt_close = body.index("</div>", i)
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            i = nxt_open + len("<div")
        else:
            depth -= 1
            i = nxt_close + len("</div>")
    return body[start:i]


def _form_slice(body, action_url):
    """The one <form> whose action is `action_url`, from the attribute to </form>.

    Locates a question's own markup by its FULL reversed action URL rather than by
    a bare pk substring: the action carries BOTH node_pk and element_pk, and
    Element/ContentNode draw from independent Postgres sequences, so a bare
    f"/{pk}/" could match the node segment (the trap test_render_seam.py:88
    documents).
    """
    start = body.index(f'action="{action_url}"')
    return body[start : body.index("</form>", start)]


def _answer_value(form_html):
    """The `value` the server refilled into a short-text/short-numeric input."""
    m = re.search(r'name="answer"[^>]*\svalue="([^"]*)"', form_html)
    assert m is not None, "no name=answer input in the form slice"
    return m.group(1)


def _verdict_block(form_html):
    """The whole `question__verdict` div, class attribute included."""
    m = re.search(r'<div class="question__verdict[^"]*">.*?</div>', form_html, re.S)
    assert m is not None, "no verdict block in the form slice"
    return m.group(0)


@pytest.fixture
def scene(client):
    """A lesson with the SAME question type at top level and inside a container.

    Same type on both sides deliberately: the only difference under test is the
    nesting, so a type-specific render quirk cannot be mistaken for the seam.
    Returns a builder so each parametrized case picks its own container.
    """
    student = make_student(client, "njs")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    top_row = add_element(unit, _fill_blank())

    def build(make_container, make_question=_fill_blank):
        # `make_question` defaults to _fill_blank so the five container cases above
        # are untouched; the type axis passes its own factory.
        concrete, slot_id = make_container()
        container_row = add_element(unit, concrete)
        nested_row = Element.objects.create(
            unit=unit,
            content_object=make_question(),
            parent=container_row,
            tab_id=slot_id,
        )
        return nested_row

    return student, unit, top_row, build


def test_top_level_blank_answer_shows_feedback(scene, client):
    """The control: no-JS + blank answer at TOP level does render a verdict."""
    _student, unit, top_row, _build = scene
    body = client.post(_check_url(unit, top_row.pk), {"blank": [""]}).content.decode()
    assert VERDICT in body


@pytest.mark.parametrize(("make_container", "child_class"), CONTAINERS)
def test_nested_blank_answer_shows_feedback(scene, client, make_container, child_class):
    """The contract: the same blank answer, nested, renders its verdict too.

    The guard assertions are kept from the absence-era version: they prove the nested
    question really rendered, so a 404, a redirect, or a container that never rendered
    its child cannot be mistaken for a working seam.
    """
    _student, unit, _top, build = scene
    nested_row = build(make_container)

    resp = client.post(_check_url(unit, nested_row.pk), {"blank": [""]})
    assert resp.status_code == 200
    body = resp.content.decode()
    # BOTH questions really are on the page -- the nested one rendered, and now it
    # renders WITH its result.
    assert body.count("el--fillblank") == 2
    assert child_class in body
    assert VERDICT in body
    if child_class == "spoiler__child":
        # The no-JS path re-renders the whole page; a closed <details> would hide
        # the verdict we just asserted is present.
        assert '<details class="spoiler" open>' in body


@pytest.mark.parametrize(("make_container", "child_class"), CONTAINERS)
def test_nested_non_blank_answer_does_show_feedback(
    scene, client, make_container, child_class
):
    """The mechanism: a NON-blank nested answer gets a verdict -- but only because
    check_answer persisted it first and the restore branch re-marked it, not because
    the container forwarded the live result."""
    _student, unit, _top, build = scene
    nested_row = build(make_container)

    body = client.post(
        _check_url(unit, nested_row.pk), {"blank": ["paris"]}
    ).content.decode()
    assert child_class in body
    assert VERDICT in body


# ---------------------------------------------------------------------------
# Seam tests 6-10: the type axis, depth-2 recursion, and invariant A.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("make_question", "blank_post", "present", "absent"), TYPES)
def test_nested_blank_answer_shows_feedback_by_type(
    scene, client, make_question, blank_post, present, absent
):
    """Three NEW types, not four: fill_blank x callout is already the container axis."""
    _student, unit, _top, build = scene
    nested_row = build(_callout, make_question)

    resp = client.post(_check_url(unit, nested_row.pk), blank_post)
    assert resp.status_code == 200
    body = resp.content.decode()
    slice_ = _child_slice(body, "callout__child")
    # The FULL reversed URL, not a bare pk substring: the action carries BOTH
    # node_pk and element_pk, and Element/ContentNode draw from independent
    # Postgres sequences, so `nested_row.pk == unit.pk` is reachable and a bare
    # f"/{pk}/" would match the node segment. (Same trap test_render_seam.py:88
    # documents.)
    assert _check_url(unit, nested_row.pk) in slice_
    for needle in present:
        # "VALUE_PK" is the placeholder for the choice case's correct-option pk,
        # which is only known after the question is built.
        if needle == "VALUE_PK":
            needle = f'value="{nested_row.content_object._correct_pk}"'
        assert needle in slice_
    for needle in absent:
        assert needle not in slice_
    assert VERDICT in slice_


def test_nested_blank_answer_shows_feedback_at_depth_2(scene, client):
    """A question in a callout in a spoiler. Pins that the recursion RE-EMITS
    rather than forwarding one level, AND that ancestry (not direct childhood)
    drives the spoiler's `open` -- seam test 2 nests directly in the spoiler, so a
    direct-parent implementation (`ancestors = {element.parent_id}`) would satisfy
    it and leave the rule unpinned. Spec section 9.3 names this test as that
    mutant's sole RED."""
    _student, unit, _top, _build = scene
    spoiler_row = add_element(unit, SpoilerElement.objects.create(label="s"))
    callout_row = Element.objects.create(
        unit=unit,
        content_object=CalloutElement.objects.create(kind="example"),
        parent=spoiler_row,
        tab_id=SpoilerElement.SLOT_ID,
    )
    nested_row = Element.objects.create(
        unit=unit,
        content_object=_fill_blank(),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    body = client.post(
        _check_url(unit, nested_row.pk), {"blank": [""]}
    ).content.decode()
    assert VERDICT in body
    assert '<details class="spoiler" open>' in body


def test_only_the_checked_question_shows_a_verdict(scene, client):
    """Invariant A. Without this, every flipped assertion would pass just as well
    if the fix leaked a verdict onto EVERY question on the page.

    The CHECKED question is created FIRST (lowest order/pk) inside the callout:
    _child_slice slices the FIRST `callout__child`, so checking the second child
    would fail the containment assertion against a correct implementation.
    """
    _student, unit, _top, _build = scene
    callout_row = add_element(unit, CalloutElement.objects.create(kind="example"))
    checked_row = Element.objects.create(
        unit=unit,
        content_object=_fill_blank(),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )
    Element.objects.create(
        unit=unit,
        content_object=_fill_blank(),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    body = client.post(
        _check_url(unit, checked_row.pk), {"blank": [""]}
    ).content.decode()
    # Three questions on the page (one top level, two nested) and exactly one
    # verdict, inside the checked child's own wrapper.
    assert body.count(VERDICT) == 1
    assert VERDICT in _child_slice(body, "callout__child")


# ---------------------------------------------------------------------------
# The seven claim tests (spec section 9.4).
# ---------------------------------------------------------------------------


def test_a_sibling_choice_question_renders_no_option_markers(scene, client):
    """Invariant B: Choice-pk disjointness, which invariant A does NOT cover.

    choicequestion.html gates its per-option marker and its per-option author
    feedback on `mk`, which comes from ChoiceQuestionElement.choice_marks -- a
    method that never receives feedback_for_pk at all. What keeps the sibling clean
    is only that its lesson branch tests `c.pk in mark_result.annotated`, and
    `annotated` holds Choice pks belonging to the CHECKED question. Seam test 10
    cannot catch a regression here: the marker path emits no verdict block to count.

    BOTH questions carry option feedback, or the sibling's zero would be vacuous --
    annotated only ever holds options that have feedback text.
    """
    _student, unit, _top, _build = scene
    callout_row = add_element(unit, CalloutElement.objects.create(kind="example"))
    checked_row = Element.objects.create(
        unit=unit,
        content_object=_choice(feedback="Think again."),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )
    Element.objects.create(
        unit=unit,
        content_object=_choice(feedback="Think again."),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    body = client.post(_check_url(unit, checked_row.pk), {}).content.decode()
    checked_slice = _child_slice(body, "callout__child", 0)
    sibling_slice = _child_slice(body, "callout__child", 1)
    # Non-vacuity: the checked question really does grow markers on a blank answer
    # (its correct option is "missed" and carries feedback).
    assert checked_slice.count("question__choice-marker") >= 1
    assert checked_slice.count("question__choice-feedback") >= 1
    assert sibling_slice.count("question__choice-marker") == 0
    assert sibling_slice.count("question__choice-feedback") == 0


def test_a_quiz_page_with_a_nested_choice_child_still_renders(scene, client):
    """The quiz page gains a NEW forwarding path (spec section 4) and must stay inert.

    The child is a CHOICE question deliberately: it is the type that would
    AttributeError on a forwarded '' (`set(mark_result.reveal or ())` runs before
    choice_marks' per-choice mode branch), so dropping the `or None` coercion turns
    this test from an assertion into a 500.

    Built with a direct Element.objects.create: spec section 6 forbids AUTHORING
    this, and the point is that legacy content must not 500.
    """
    student, unit, _top, _build = scene
    course = unit.course
    quiz = make_quiz_unit(course=course)
    callout_row = add_element(quiz, CalloutElement.objects.create(kind="example"))
    Element.objects.create(
        unit=quiz,
        content_object=_choice(),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    resp = client.get(
        reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    # The nested child really rendered, and it rendered clean.
    assert 'name="choice"' in _child_slice(body, "callout__child")
    assert VERDICT not in body
    assert "question__choice-marker" not in body
    # Spec section 4's standing requirement: no quiz page context may introduce a
    # top-level `selected_ids`, or render_element's truthiness fallback would
    # substitute it into EVERY unanswered top-level quiz question.
    assert "selected_ids" not in build_quiz_context(quiz, student)


def test_restore_and_live_routes_render_the_same_feedback(scene, client):
    """After the fix the checked element takes the LIVE route, not restore -- so the
    two routes have to be compared executably rather than against pre-change code.

    A whitespace-bearing answer is the value where they could plausibly diverge: the
    restore route reads it back through a JSON round-trip, the live route straight
    off the POST.
    """
    _student, unit, _top, build = scene
    nested_row = build(_callout, _short_text)
    url = _check_url(unit, nested_row.pk)

    live = client.post(url, {"answer": "  Paris  "}).content.decode()
    lesson_url = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    # feedback_for_pk is None on a plain GET, so the same element re-renders through
    # the practice-state restore branch instead.
    restored = client.get(lesson_url).content.decode()

    live_form = _form_slice(live, url)
    restored_form = _form_slice(restored, url)
    assert _verdict_block(live_form) == _verdict_block(restored_form)
    assert _answer_value(live_form) == _answer_value(restored_form) == "  Paris  "


def test_none_and_empty_string_refill_identically(scene, client):
    """The `submitted_values or None` coercion is observationally inert ONLY because
    both refill sites pipe through `default_if_none:''`. A nested blank short-text
    answer arrives as None; its top-level twin arrives as "". Pin that they render
    the same empty input, or a future template dropping the filter breaks nested
    refill silently.
    """
    _student, unit, _top, build = scene
    top_row = add_element(unit, _short_text())
    nested_row = build(_callout, _short_text)
    top_url = _check_url(unit, top_row.pk)
    nested_url = _check_url(unit, nested_row.pk)

    top_body = client.post(top_url, {"answer": ""}).content.decode()
    nested_body = client.post(nested_url, {"answer": ""}).content.decode()

    # Both are the CHECKED element in their own response, so both pass the
    # `element.pk == feedback_for_pk` gate and really do render the refill branch.
    assert VERDICT in _form_slice(top_body, top_url)
    assert VERDICT in _form_slice(nested_body, nested_url)
    assert (
        _answer_value(_form_slice(nested_body, nested_url))
        == _answer_value(_form_slice(top_body, top_url))
        == ""
    )


# Every key the five container render()s own, all poisoned at once. `page` is
# splatted FIRST, so none of these may survive into the rendered markup -- and for
# TabsElement, whose dict has TWO splats, `display`/`label_pos` must lose to
# display_settings() at the end as well.
HIJACK = {
    "el": "HIJACKED",
    "children": "HIJACKED",
    "tabs": "HIJACKED",
    "columns": "HIJACKED",
    "slots": "HIJACKED",
    "eid": "HIJACKED",
    "element_state": "HIJACKED",
    "slug": "HIJACKED",
    "node_pk": "HIJACKED",
    "display": "HIJACKED",
    "label_pos": "HIJACKED",
}


def _hijack_callout():
    return CalloutElement.objects.create(kind="tip", heading="REALHEAD"), [
        "callout--tip",
        "REALHEAD",
    ]


def _hijack_spoiler():
    return SpoilerElement.objects.create(label="REALLABEL"), ["REALLABEL"]


def _hijack_tabs():
    return TabsElement.objects.create(data=TabsElement.default_data()), [
        "data-tab-panel",
        'data-tabs-eid="0"',
    ]


def _hijack_two_column():
    return TwoColumnElement.objects.create(data=TwoColumnElement.default_data()), [
        "twocolumn__column",
        'data-twocolumn-eid="0"',
    ]


def _hijack_before_after():
    return BeforeAfterElement.objects.create(button_label="REALBTN"), [
        "REALBTN",
        'data-ba-side="after"',
    ]


@pytest.mark.parametrize(
    "make_container",
    [
        pytest.param(_hijack_callout, id="callout"),
        pytest.param(_hijack_spoiler, id="spoiler"),
        pytest.param(_hijack_tabs, id="tabs"),
        pytest.param(_hijack_two_column, id="two_column"),
        pytest.param(_hijack_before_after, id="before_after"),
    ],
)
def test_page_can_never_shadow_a_containers_own_keys(make_container):
    """All FIVE containers, not one: the splat-order invariant would otherwise be
    unpinned for four sites -- including TabsElement, the one the spec flags as the
    place an implementer copying the single-splat snippet goes wrong."""
    concrete, markers = make_container()
    html = concrete.render(page=dict(HIJACK))
    assert "HIJACKED" not in html
    for marker in markers:
        assert marker in html


def test_spoiler_renders_with_no_element_join_row():
    """The `eid` sentinel. Nothing in test_render_seam.py covers this: its CONCRETES
    loop passes a real join row, and its only element=None case uses FillGateElement.
    A bare `"eid": element.pk` would AttributeError here and ship green there."""
    html = SpoilerElement.objects.create(label="s").render()
    assert '<details class="spoiler">' in html


def test_mode_is_not_forwarded_to_a_nested_child(monkeypatch, scene, client):
    """`mode` must stay OUT of the page dict: forwarding it would make a question
    nested in a QUIZ container render in quiz mode -- the half-built path spec
    section 6.6 describes -- silently, with no gate tripping.

    A source regex would sweep the comments that discuss `mode`, and a
    rendered-output assertion cannot tell "mode absent" from "mode present and equal
    to the default 'lesson'" -- which is exactly the mutant. So capture the kwarg.
    """
    captured = {}

    def capture(self, *, element=None, state=None, slug=None, node_pk=None, page=None):
        # Patched on the CLASS, so `capture` is an unbound descriptor and receives
        # the instance as `self`; it must return a string, because render_element
        # mark_safe()s the result straight into the page.
        captured.update(page or {})
        return ""

    monkeypatch.setattr(CalloutElement, "render", capture)
    _student, unit, top_row, build = scene
    build(_callout)

    resp = client.post(_check_url(unit, top_row.pk), {"blank": [""]})
    assert resp.status_code == 200
    # The FULL key set, not just the absence: `"mode" not in captured` is green
    # when `page` never arrived at all.
    assert captured.keys() == {
        "feedback_for_pk",
        "selected_ids",
        "submitted_values",
        "mark_result",
        "editor_preview",
        "feedback_ancestor_pks",
    }
