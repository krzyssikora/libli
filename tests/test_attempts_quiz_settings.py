"""Quiz-level attempts (spec 2026-10-20 §5.2)."""

import pytest
from django.urls import reverse

from courses import attempts as A
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _post(client, unit, *, follow=False, **over):
    data = {
        "node": unit.pk,
        "token": unit.updated.isoformat(),
        "has_settings": "1",
        "ctx": "editor",
        "title": unit.title,
        "html_seed_js": "",
    }
    data.update(over)
    return client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": unit.course.slug}),
        data,
        follow=follow,
    )


def _q(unit, *, marking="A", own=None):
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", marking_mode=marking, **(own or {})
    )
    add_element(unit, q)
    return q


def test_saves_quiz_limit(client):
    make_pa(client)
    unit = make_quiz_unit()
    assert (
        _post(client, unit, attempts_mode="limited", attempts_limit="3").status_code
        == 302
    )
    unit.refresh_from_db()
    assert (unit.attempts_mode, unit.attempts_limit) == ("limited", 3)


def test_hidden_junk_saves_null(client):
    make_pa(client)
    unit = make_quiz_unit()
    _post(client, unit, attempts_mode="unlimited", attempts_limit="abc")
    unit.refresh_from_db()
    assert (unit.attempts_mode, unit.attempts_limit) == ("unlimited", None)


@pytest.mark.parametrize(
    "mode,raw,message",
    [
        ("limited", "abc", A.MSG_ENTER),
        ("limited", "2.5", A.MSG_ENTER),
        ("limited", "", A.MSG_ENTER),
        ("limited", "0", A.ZERO_MESSAGES["course"]),
        ("limited", "40000", A.MSG_CAP),
        ("bogus", "3", A.MSG_CHOOSE),
    ],
)
def test_422_messages(client, mode, raw, message):
    make_pa(client)
    unit = make_quiz_unit()
    resp = _post(client, unit, attempts_mode=mode, attempts_limit=raw)
    assert resp.status_code == 422
    assert str(message).replace("'", "&#x27;") in resp.content.decode()


def test_422_keeps_every_posted_value(client):
    make_pa(client)
    unit = make_quiz_unit()
    _q(unit, own=attempts(4))  # makes the reset radios appear
    resp = _post(
        client,
        unit,
        title="New title",
        html_seed_js="{ seed: 42 }",
        attempts_mode="limited",
        attempts_limit="0",
        attempts_reset="reset",
    )
    html = resp.content.decode()
    assert resp.status_code == 422
    assert '<details class="unit-settings" open' in html
    assert "{ seed: 42 }" in html and 'value="New title"' in html
    assert '<option value="limited" selected' in html
    assert 'value="reset" checked' in html
    assert "Same as course (currently: 1)" in html


def test_overriding_quiz_label_shows_the_course_value(client):
    """Spec §4/§7.4: the quiz select resolves the COURSE, never the quiz itself."""
    make_pa(client)
    unit = make_quiz_unit(attempts_mode="limited", attempts_limit=3)
    url = reverse(
        "courses:manage_editor", kwargs={"slug": unit.course.slug, "pk": unit.pk}
    )
    html = client.get(url).content.decode()
    assert "Same as course (currently: 1)" in html
    assert "(currently: 3)" not in html


def test_lesson_settings_and_plain_rename_keep_dormant_override(client):
    make_pa(client)
    lesson = ContentNodeFactory(
        kind="unit", unit_type="lesson", attempts_mode="limited", attempts_limit=2
    )
    assert _post(client, lesson).status_code == 302  # no attempts keys
    lesson.refresh_from_db()
    url = reverse("courses:manage_node_rename", kwargs={"slug": lesson.course.slug})
    client.post(
        url, {"node": lesson.pk, "token": lesson.updated.isoformat(), "title": "T"}
    )
    lesson.refresh_from_db()
    assert (lesson.attempts_mode, lesson.attempts_limit) == ("limited", 2)


def test_crafted_attempts_post_against_a_lesson_is_rejected(client):
    make_pa(client)
    lesson = ContentNodeFactory(
        kind="unit", unit_type="lesson", attempts_mode="limited", attempts_limit=2
    )
    q = _q(lesson, own=attempts(5))
    resp = _post(client, lesson, attempts_mode="unlimited", attempts_reset="reset")
    assert resp.status_code == 422
    lesson.refresh_from_db()
    q.refresh_from_db()
    assert (lesson.attempts_limit, q.attempts_limit) == (2, 5)


def test_reset_clears_this_quiz_only_and_reports_the_auto_count(client):
    make_pa(client)
    unit = make_quiz_unit()
    other = make_quiz_unit(course=unit.course)
    a1, a2 = _q(unit, own=attempts(3)), _q(unit, own=attempts(None))
    n = _q(unit, marking="N", own=attempts(2))
    elsewhere = _q(other, own=attempts(5))
    resp = _post(
        client,
        unit,
        attempts_mode="limited",
        attempts_limit="4",
        attempts_reset="reset",
        follow=True,
    )
    for q in (a1, a2, n):
        q.refresh_from_db()
        assert q.attempts_mode == "inherit"
    elsewhere.refresh_from_db()
    assert elsewhere.attempts_limit == 5
    assert (
        "Settings saved. 2 questions now use the quiz setting." in resp.content.decode()
    )


def test_keep_changes_nothing_and_shows_no_message(client):
    make_pa(client)
    unit = make_quiz_unit()
    q = _q(unit, own=attempts(3))
    resp = _post(
        client,
        unit,
        attempts_mode="limited",
        attempts_limit="4",
        attempts_reset="keep",
        follow=True,
    )
    q.refresh_from_db()
    assert q.attempts_limit == 3
    assert "Settings saved" not in resp.content.decode()
