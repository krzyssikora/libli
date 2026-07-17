import pytest
from django.urls import reverse

from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_lesson_includes_markdone_js_when_present(client):
    course, unit = make_course_with_unit()
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    MarkDoneItem.objects.create(element=el, content="a")

    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)

    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "courses/js/markdone.js" in body


def test_lesson_omits_markdone_js_when_absent(client):
    course, unit = make_course_with_unit()

    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)

    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "courses/js/markdone.js" not in body


def test_markdone_js_posts_the_state_envelope_and_guards_the_race():
    from pathlib import Path

    src = Path("courses/static/courses/js/markdone.js").read_text(encoding="utf-8")
    # The envelope changed: {element, state:{items}} -- not the old {element, items}.
    # NB each assertion is separate and non-vacuous. An earlier draft wrote
    #   assert "state:" in src and '"items"' in src or "items:" in src
    # which Python reads as (A and B) or C -- and C ("items:" in src) is TRUE of the
    # UNMODIFIED file, so it passed before the change was made and tested nothing.
    assert "state: { items: items }" in src
    # window.libliInitMarkDone must survive with the same name AND arity: editor.js:83
    # calls it over the preview pane after every fragment swap.
    assert "window.libliInitMarkDone = initMarkDone;" in src
    # Last-write-wins: adoption without a sequence guard unticks a box the student
    # just ticked (tick A -> tick B -> A's echo re-renders the widget from
    # {"items":[A]}). This is a regression adoption INTRODUCES -- the old client
    # ignored the response body entirely.
    assert "var mine = ++seq;" in src
    # BOTH paths must be guarded — the success path (adopt) and the failure path
    # (revert). `in` would only prove the guard occurs AT LEAST ONCE, and the string is
    # byte-identical at both call sites, so dropping it from the .catch handler alone
    # would leave this assertion green. Count instead: the claim is "both", so pin two.
    assert src.count("if (mine !== seq) return;") == 2
