import pytest

from courses.models import GalleryElement
from courses.models import TextElement

pytestmark = pytest.mark.django_db


def test_elementbase_render_accepts_context_kwargs():
    # A plain content element (TextElement) must accept the new kwargs and ignore them.
    el = TextElement.objects.create(body="hi")
    html = el.render(checklist={}, slug="x", node_pk=1)
    assert "hi" in html


def test_zero_arg_override_absorbs_kwargs():
    # GalleryElement overrides render(self); it must not TypeError on the new kwargs.
    g = GalleryElement.objects.create()
    g.render(checklist={}, slug="x", node_pk=1)  # no TypeError
