import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


@pytest.mark.django_db
def test_add_menu_grouped_content_and_questions(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="U"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c1", "pk": unit.pk})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Content" in body and "Questions" in body  # group labels
    assert body.count('data-add-type="') == 15  # all 15 cards kept
    assert "data-type-menu" in body  # wrapper unmoved
    for key in ("text", "image", "video", "iframe", "math", "html"):
        assert f'data-add-type="{key}"' in body  # 6 content cards
    for key in (
        "choice-single",
        "choice-multi",
        "shorttextquestion",
        "shortnumericquestion",
        "fillblankquestion",
        "dragfillblankquestion",
        "matchpairquestion",
        "dragtoimagequestion",
        "extendedresponsequestion",
    ):
        assert f'data-add-type="{key}"' in body  # 9 question cards
