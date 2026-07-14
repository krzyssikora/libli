"""The editor pane's element count must use Polish plural forms, not one fixed
string. Polish has three: 1 -> element, 2-4 -> elementy, 5+/0 -> elementów.

Two guards:
- the render test proves `_editor_scope.html` routes the count through
  `{% blocktranslate count %}` (a regression to `{% trans "elements" %}` would
  render the single "elementy" form for every count and fail here);
- the catalog test proves the Polish plural forms for this msgid exist.
"""

import pytest
from django.urls import reverse
from django.utils import translation

from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa


@pytest.mark.django_db
def test_editor_count_renders_polish_plural(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    for i in range(5):
        add_element(unit, TextElement.objects.create(body=f"<p>e{i}</p>"))
    # LocaleMiddleware re-activates the language per request from the session;
    # translation.override() alone does not control what the test client renders.
    # Mirror the proven pattern in tests/test_i18n_catalog.py.
    session = client.session
    session["_language"] = "pl"
    session.save()
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    html = client.get(url, HTTP_ACCEPT_LANGUAGE="pl").content.decode()
    assert "5 elementów" in html  # correct "many" form
    assert "5 elementy" not in html  # the old fixed-form bug
    assert "5 elements" not in html  # untranslated


def _count(n):
    return translation.ngettext("%(n)s element", "%(n)s elements", n) % {"n": n}


def test_polish_element_count_uses_all_three_plural_forms():
    with translation.override("pl"):
        assert _count(1) == "1 element"  # singular
        assert _count(2) == "2 elementy"  # few (2-4)
        assert _count(5) == "5 elementów"  # many (5+)
        assert _count(22) == "22 elementy"  # few (n%10 in 2-4, n%100 not 12-14)
        assert _count(0) == "0 elementów"  # many
