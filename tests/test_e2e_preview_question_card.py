"""e2e: a question renders as the same card in the editor preview as on the lesson.

The card (padding, background, border, radius) is a CSS descendant rule. The student
page reaches it through `.lesson`; the editor preview has no `.lesson` ancestor, so
before the fix every question there -- top-level or nested in a callout -- rendered
flat, contradicting the pane's "as students see it" label. The server HTML is
identical either way, so only computed style can pin this.
"""

import os

import pytest

from tests.test_e2e_callout_container import _lesson_url
from tests.test_e2e_callout_container import _login
from tests.test_e2e_callout_container import _seed_unit
from tests.test_e2e_tabs import _editor_url

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


_CARD_JS = """(el) => {
  const s = getComputedStyle(el);
  return [s.paddingTop, s.paddingLeft, s.borderTopWidth, s.borderTopStyle,
          s.backgroundColor, s.borderTopLeftRadius];
}"""


def _seed_choice(stem):
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem=stem)
    Choice.objects.create(question=q, text="yes", is_correct=True)
    Choice.objects.create(question=q, text="no")
    return q


def test_question_card_matches_between_preview_and_lesson(page, live_server):
    from courses.models import CalloutElement
    from courses.models import Element
    from tests.factories import add_element

    user, course, unit = _seed_unit("pa_qcard")
    add_element(unit, _seed_choice("<p>TOP</p>"))
    callout = CalloutElement.objects.create(kind="example", body="<p>intro</p>")
    join = add_element(unit, callout)
    Element.objects.create(
        unit=unit,
        content_object=_seed_choice("<p>NESTED</p>"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    _login(page, live_server, user.username)

    page.goto(_lesson_url(live_server, unit))
    lesson = [
        page.locator(".el--question", has_text=t).first.evaluate(_CARD_JS)
        for t in ("TOP", "NESTED")
    ]
    # Non-vacuity: the lesson side must actually BE a card, or equality below
    # would also hold for two flat renders.
    assert lesson[0][0] != "0px" and lesson[0][2] != "0px", lesson[0]

    page.goto(_editor_url(live_server, course, unit))
    prev = page.locator('[data-scope="preview"]')
    preview = [
        prev.locator(".el--question", has_text=t).first.evaluate(_CARD_JS)
        for t in ("TOP", "NESTED")
    ]
    assert preview == lesson
