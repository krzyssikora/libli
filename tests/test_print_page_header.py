"""Running print header (spec 2026-10-11-print-layout-for-units §1, test 2)."""

import pytest
from django.urls import reverse

from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login

HOSTILE = 'Funkcja \\(f(x)\\) "x" </style>'
HOSTILE_EXPECTED = 'content: "libli · Funkcja f(x) \\22 x\\22  \\3c /style\\3e ";'
EN_COUNTER = 'content: "Page " counter(page) " / " counter(pages);'
PL_COUNTER = 'content: "Strona " counter(page) " / " counter(pages);'


def _block(html):
    """From <style data-print-page> to the FIRST following </style>."""
    assert html.count("<style data-print-page>") == 1, "partial missing or doubled"
    return html.split("<style data-print-page>", 1)[1].split("</style>", 1)[0]


def _unit(kind, title):
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=kind, title=title)
    if kind == "lesson":
        add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    else:
        add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    return course, unit


def _get(client, kind, title, *, submitted=False, polish=False):
    user = make_login(client, "printer")
    course, unit = _unit(kind, title)
    EnrollmentFactory(course=course, student=user)
    if polish:
        client.post(reverse("core:set_ui_language"), {"language": "pl", "next": "/"})
    name = {"lesson": "courses:lesson_unit", "quiz": "courses:quiz_unit"}[kind]
    if submitted:
        QuizSubmission.objects.create(
            student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED
        )
        name = "courses:quiz_results"
    resp = client.get(reverse(name, kwargs={"slug": course.slug, "node_pk": unit.pk}))
    assert resp.status_code == 200
    return resp.content.decode()


PAGES = [("lesson", False), ("quiz", False), ("quiz", True)]


@pytest.mark.django_db
@pytest.mark.parametrize(("kind", "submitted"), PAGES)
def test_hostile_title_is_escaped_and_block_is_intact(client, kind, submitted):
    block = _block(_get(client, kind, HOSTILE, submitted=submitted))
    # If </style> leaked unescaped, the slice would end early and BOTH would be missing.
    assert HOSTILE_EXPECTED in block
    assert EN_COUNTER in block


@pytest.mark.django_db
@pytest.mark.parametrize(("kind", "submitted"), PAGES)
def test_polish_ui_label(client, kind, submitted):
    block = _block(_get(client, kind, "Lekcja", submitted=submitted, polish=True))
    assert PL_COUNTER in block


@pytest.mark.django_db
def test_long_title_truncated_to_70(client):
    title = ("abcdefghij " * 19)[:200]  # letters and spaces only: nothing escapes
    block = _block(_get(client, "lesson", title))
    line = next(ln for ln in block.splitlines() if 'content: "libli · ' in ln)
    shown = line.split('content: "libli · ', 1)[1].rsplit('";', 1)[0]
    assert len(shown) <= 70
    assert shown.endswith("…")


@pytest.mark.django_db
def test_header_uses_literal_typography(client):
    block = _block(_get(client, "lesson", "T"))
    assert "var(" not in block
    assert "#5A544A" in block
    assert (
        '"Inter", "libli-dice", -apple-system, BlinkMacSystemFont, '
        '"Segoe UI", sans-serif'
    ) in block


@pytest.mark.django_db
def test_flash_messages_carry_marker_class():
    """RENDER the flash loop: a source grep passes even in a dead branch."""
    from django.contrib.messages import constants
    from django.contrib.messages.storage.base import Message
    from django.template.loader import render_to_string

    html = render_to_string("base.html", {"messages": [Message(constants.INFO, "Hi")]})
    assert 'class="alert alert--flash alert--info">Hi</div>' in html
