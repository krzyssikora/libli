import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

EL_ICON_MAP = {
    "text": "el-text",
    "image": "el-image",
    "video": "el-video",
    "iframe": "el-iframe",
    "math": "el-math",
    "html": "el-html",
    "choice-single": "el-choice-single",
    "choice-multi": "el-choice-multi",
    "shorttextquestion": "el-shorttext",
    "shortnumericquestion": "el-shortnumeric",
    "fillblankquestion": "el-fillblank",
    "dragfillblankquestion": "el-dragwords",
    "matchpairquestion": "el-matchpairs",
    "dragtoimagequestion": "el-dragimage",
    "extendedresponsequestion": "el-extended",
}


@pytest.mark.django_db
def test_add_menu_icons_are_svg(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="U"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c1", "pk": unit.pk})
    )
    body = resp.content.decode()
    for sym in EL_ICON_MAP.values():
        assert f'<use href="#{sym}"' in body  # every card references its el-* symbol
        assert f'<symbol id="{sym}"' in body  # and the sprite defines it
    assert "📝" not in body and "🖼" not in body  # no emoji left in the menu


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
