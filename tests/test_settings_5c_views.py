import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.services import get_site_config
from courses import validators as cv
from institution.models import BrandColor
from institution.models import Institution
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.factories import make_pa


@pytest.mark.django_db
def test_institution_upload_field_defaults():
    inst = Institution.load()
    assert inst.allowed_image_extensions == list(cv.SAFE_IMAGE_EXTENSIONS)
    assert inst.allowed_video_extensions == list(cv.SAFE_VIDEO_EXTENSIONS)
    assert inst.max_image_mib == cv.MAX_IMAGE_MIB_CEILING
    assert inst.max_video_mib == cv.MAX_VIDEO_MIB_CEILING


@pytest.mark.django_db
def test_site_config_carries_upload_keys():
    cache.clear()
    cfg = get_site_config()
    assert "allowed_image_extensions" in cfg
    assert "max_video_mib" in cfg


@pytest.mark.django_db
def test_site_config_upload_keys_present_when_institution_absent():
    cache.clear()
    Institution.objects.all().delete()  # institution-absent path -> dict(_DEFAULTS)
    cfg = get_site_config()
    assert cfg["allowed_image_extensions"]  # key present, not KeyError downstream
    assert cfg["max_image_mib"]


def _png_upload(name="a.png", size_pad=0):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue() + b"\0" * size_pad, "image/png")


@pytest.mark.django_db
def test_mediaasset_clean_rejects_disabled_extension():
    inst = Institution.load()
    inst.allowed_image_extensions = ["jpg"]  # gif/png disabled
    inst.save()  # fires cache invalidation
    cache.clear()
    from courses.models import MediaAsset

    asset = MediaAsset(
        course=CourseFactory(),
        kind="image",
        file=_png_upload("x.png"),
        original_filename="x.png",
    )
    with pytest.raises(ValidationError):
        asset.clean()


@pytest.mark.django_db
def test_mediaasset_clean_accepts_within_limits():
    cache.clear()
    from courses.models import MediaAsset

    asset = MediaAsset(
        course=CourseFactory(),
        kind="image",
        file=_png_upload("x.png"),
        original_filename="x.png",
    )
    asset.clean()  # no raise — defaults allow png


@pytest.mark.django_db
def test_settings_index_pa_only(client):
    make_login(client, "plain")  # non-PA
    assert client.get(reverse("institution:settings")).status_code == 403


@pytest.mark.django_db
def test_settings_index_renders_for_pa(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings"))
    assert resp.status_code == 200
    assert "branding" in resp.context
    assert "access" in resp.context
    assert "uploads" in resp.context
    assert resp.context["active_tab"] == "branding"


@pytest.mark.django_db
def test_settings_index_unknown_tab_falls_back(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings") + "?tab=garbage")
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "branding"


def _branding_post(**over):
    data = {
        "name": "Greenfield",
        "enabled_languages": ["en", "pl"],
        "default_language": "en",
        "default_theme": "auto",
        "primary": "#123abc",
        "accent": "#abcdef",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_branding_post_saves_and_redirects(client):
    make_pa(client, "pa")
    resp = client.post(reverse("institution:settings_branding"), _branding_post())
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=branding")
    assert BrandColor.objects.get(key="primary").value == "#123abc"


@pytest.mark.django_db
def test_branding_invalid_post_rerenders_full_page(client):
    make_pa(client, "pa")
    resp = client.post(
        reverse("institution:settings_branding"), _branding_post(primary="nope")
    )
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "branding"
    assert resp.context["branding"].errors  # errored bound form
    assert resp.context["access"] is not None  # the other two present
    assert resp.context["uploads"] is not None


@pytest.mark.django_db
def test_action_view_get_redirects(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings_access"))
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=access")
