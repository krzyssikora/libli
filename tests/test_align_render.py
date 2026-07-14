from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"


def test_global_align_utilities_exist():
    css = CSS.read_text(encoding="utf-8")
    for cls in [".ta-left", ".ta-center", ".ta-right"]:
        assert cls in css, f"missing alignment utility: {cls}"


@pytest.mark.django_db
def test_align_class_survives_model_save():
    from courses.models import CalloutElement
    from courses.models import SpoilerElement
    from courses.models import TextElement

    body = '<div class="ta-center">Centered</div>'
    for model in (TextElement, SpoilerElement, CalloutElement):
        el = model.objects.create(body=body)
        el.refresh_from_db()
        assert 'class="ta-center"' in el.body, f"{model.__name__}: {el.body!r}"
