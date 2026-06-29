import pytest

from courses import validators as cv
from institution.models import Institution


@pytest.mark.django_db
def test_institution_upload_field_defaults():
    inst = Institution.load()
    assert inst.allowed_image_extensions == list(cv.SAFE_IMAGE_EXTENSIONS)
    assert inst.allowed_video_extensions == list(cv.SAFE_VIDEO_EXTENSIONS)
    assert inst.max_image_mib == cv.MAX_IMAGE_MIB_CEILING
    assert inst.max_video_mib == cv.MAX_VIDEO_MIB_CEILING
