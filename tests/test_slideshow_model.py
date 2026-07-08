import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import ELEMENT_MODELS
from courses.models import SlideBreakElement


@pytest.mark.django_db
def test_slidebreakelement_registered_and_fieldless():
    assert "slidebreakelement" in ELEMENT_MODELS
    SlideBreakElement.objects.create()
    # No content fields beyond the pk + GenericRelation.
    concrete_fields = [f.name for f in SlideBreakElement._meta.fields]
    assert concrete_fields == ["id"]
    # A ContentType row exists (needed by the transfer + seen-exclusion paths).
    ct = ContentType.objects.get_for_model(SlideBreakElement)
    assert ct.app_label == "courses"
