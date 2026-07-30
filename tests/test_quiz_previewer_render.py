import pytest
from django.template.loader import render_to_string

from courses.models import QuizSubmission
from courses.views import build_quiz_context
from tests.factories import EnrollmentFactory
from tests.factories import ExtendedResponseQuestionElementFactory
from tests.factories import MatchPairFactory
from tests.factories import MatchPairQuestionElementFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _previewer(client):
    user = make_login(client, "prev")
    user.is_staff = True
    user.save()
    return user


def _quiz_url(unit):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"


@pytest.mark.django_db
def test_previewer_sees_banner_and_no_finish(client):
    _previewer(client)
    unit = make_quiz_unit()
    add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    )
    resp = client.get(_quiz_url(unit))
    assert resp.status_code == 200
    assert b"data-quiz-preview-notice" in resp.content
    assert b"Finish quiz" not in resp.content
    assert not QuizSubmission.objects.filter(unit=unit).exists()


@pytest.mark.django_db
def test_previewer_control_level_inputs_are_live(client):
    """Family 1: `disabled` sits on the <input>/<button> itself."""
    _previewer(client)
    unit = make_quiz_unit()
    add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    )
    body = client.get(_quiz_url(unit)).content.decode()
    field = body.split('name="answer"')[1][:200]
    assert "disabled" not in field


@pytest.mark.django_db
def test_previewer_fieldset_wrapped_inputs_are_live(client):
    """Family 2: `disabled` sits on a wrapping <fieldset>
    (matchpairquestionelement.html:7). A test that only checks the <input> is
    vacuous for every 2D/grid type.

    MatchPair is used rather than MultiGrid because there is no
    MultiGridQuestionElementFactory (verified); DragToImage would also work but
    drags in a MediaAsset via SubFactory."""
    _previewer(client)
    unit = make_quiz_unit()
    q = MatchPairQuestionElementFactory()
    MatchPairFactory(question=q)
    add_element(unit, q)
    body = client.get(_quiz_url(unit)).content.decode()
    fieldset = body.split("<fieldset")[1][:120]
    assert "disabled" not in fieldset


@pytest.mark.django_db
def test_previewer_bare_textarea_is_live(client):
    """Family 3: extended response has NO wrapping fieldset, so it is missed by
    both of the other checks."""
    _previewer(client)
    unit = make_quiz_unit()
    add_element(unit, ExtendedResponseQuestionElementFactory())
    body = client.get(_quiz_url(unit)).content.decode()
    textarea = body.split("<textarea")[1][:250]
    assert "disabled" not in textarea


@pytest.mark.django_db
def test_banner_renders_once_outside_every_slide(client):
    """slideshow.js shows one .slide at a time, so a banner inside the loop would
    render per-slide, and one inside the first slide would vanish on advance."""
    from courses.models import SlideBreakElement

    _previewer(client)
    unit = make_quiz_unit()
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q1?", accepted="a"))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q2?", accepted="b"))
    body = client.get(_quiz_url(unit)).content.decode()
    assert body.count("data-quiz-preview-notice") == 1
    assert body.index("data-quiz-preview-notice") < body.index('class="slide"')


@pytest.mark.django_db
def test_enrolled_student_sees_finish_and_no_banner(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    )
    resp = client.get(_quiz_url(unit))
    assert b"Finish quiz" in resp.content
    assert b"data-quiz-preview-notice" not in resp.content


@pytest.mark.django_db
def test_previewer_locked_question_freezes_inputs(client):
    """The MARKUP half of Task 2's st["locked"] fix. It lives here, not in Task 2:
    until line 12 passes quiz_submitted (not read_only), read_only=True disables a
    previewer's inputs regardless of st["locked"], so the assertion could not fail
    there. Now that inputs are live by default, `locked` is the only thing that can
    freeze them -- and it must, or a previewer resubmits an [N]/[R] question forever.
    """
    _previewer(client)
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(
        stem="Discuss", accepted="", marking_mode="N"
    )
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, {"answer": "whatever"})  # no fetch header -> full page
    body = resp.content.decode()
    assert "is-recorded" in body
    field = body.split('name="answer"')[1][:200]
    assert "disabled" in field


@pytest.mark.django_db
def test_submitted_quiz_still_freezes_inputs(client):
    """Rendered directly: quiz_unit redirects to results before rendering a
    SUBMITTED quiz (views.py:1224), so a GET would return 302 and assert nothing.

    Honest scope: read_only = quiz_submitted or previewing, so read_only superset
    quiz_submitted -- there is NO context state with quiz_submitted=True and
    read_only=False. This passes whether line 12 says `read_only` or
    `quiz_submitted`. It guards "a SUBMITTED quiz still freezes"; the test that
    actually falsifies the argument-source change is the previewer-liveness one
    above, since previewing=True is the only discriminating state.
    """
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    )
    QuizSubmission.objects.create(student=user, unit=unit, status="submitted")
    ctx = build_quiz_context(unit, user)
    body = render_to_string("courses/_quiz_article.html", ctx)
    field = body.split('name="answer"')[1][:200]
    assert "disabled" in field
