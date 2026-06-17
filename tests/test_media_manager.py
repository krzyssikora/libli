import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from courses import media as media_svc
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import add_element
from tests.factories import make_pa


@pytest.mark.django_db
def test_usage_count_counts_only_fk_references():
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    other = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, ImageElement.objects.create(media=asset, alt="a"))
    add_element(unit, ImageElement.objects.create(media=asset, alt="b"))
    assert media_svc.usage_count(asset) == 2
    assert media_svc.usage_count(other) == 0


@pytest.mark.django_db
def test_assets_with_usage_annotation_matches_usage_count():
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, ImageElement.objects.create(media=asset, alt="a"))
    add_element(unit, ImageElement.objects.create(media=asset, alt="b"))
    row = next(a for a in media_svc.assets_with_usage(course) if a.pk == asset.pk)
    assert row.img_uses + row.vid_uses == media_svc.usage_count(asset)


@pytest.mark.django_db
def test_delete_unused_succeeds_in_use_refused():
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    media_svc.delete_asset(asset)  # unused -> ok
    assert not MediaAsset.objects.filter(pk=asset.pk).exists()

    used = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, ImageElement.objects.create(media=used, alt="a"))
    with pytest.raises(media_svc.AssetInUseError):
        media_svc.delete_asset(used)


@pytest.mark.django_db
def test_manager_lists_only_this_courses_assets(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    MediaAssetFactory(course=course, original_filename="mine.png")
    MediaAssetFactory(course=CourseFactory(), original_filename="other.png")
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    assert resp.status_code == 200
    assert b"mine.png" in resp.content
    assert b"other.png" not in resp.content


@pytest.mark.django_db
def test_upload_then_delete_in_use_returns_409(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    png = SimpleUploadedFile(
        "p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, content_type="image/png"
    )
    up = client.post(
        reverse("courses:manage_media_upload", kwargs={"slug": course.slug}),
        {"kind": "image", "file": png},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert up.status_code == 200
    asset = MediaAsset.objects.get(course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, ImageElement.objects.create(media=asset, alt="a"))
    dele = client.post(
        reverse(
            "courses:manage_media_delete",
            kwargs={"slug": course.slug, "pk": asset.pk},
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert dele.status_code == 409


# ---------------------------------------------------------------------------
# Rename endpoint tests (Task 4)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rename_asset_trims_and_clears(client):
    pa = make_pa(client, "pamedia")
    course = CourseFactory(owner=pa, slug="mediacourse")
    asset = MediaAssetFactory(course=course, kind="image", original_filename="x.png")
    url = reverse("courses:manage_media_rename", kwargs={"slug": course.slug})
    r = client.post(url, {"id": asset.pk, "name": "  Cover art  "}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 200
    asset.refresh_from_db()
    assert asset.name == "Cover art"  # trimmed
    r = client.post(url, {"id": asset.pk, "name": "   "}, HTTP_X_REQUESTED_WITH="fetch")
    asset.refresh_from_db()
    assert asset.name == ""
    assert asset.display_name == asset.original_filename


@pytest.mark.django_db
def test_rename_over_length_is_422(client):
    pa = make_pa(client, "pamedia2")
    course = CourseFactory(owner=pa)
    asset = MediaAssetFactory(course=course, kind="image")
    url = reverse("courses:manage_media_rename", kwargs={"slug": course.slug})
    r = client.post(url, {"id": asset.pk, "name": "x" * 256}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 422


@pytest.mark.django_db
def test_rename_non_integer_id_is_404(client):
    pa = make_pa(client, "pamedia4")
    course = CourseFactory(owner=pa)
    url = reverse("courses:manage_media_rename", kwargs={"slug": course.slug})
    r = client.post(url, {"id": "abc", "name": "X"}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 404


@pytest.mark.django_db
def test_rename_cross_course_is_404(client):
    pa = make_pa(client, "pamedia3")
    course = CourseFactory(owner=pa)
    asset = MediaAssetFactory(course=course, kind="image")
    other_course = CourseFactory(owner=pa, slug="othercourse")
    url = reverse("courses:manage_media_rename", kwargs={"slug": other_course.slug})
    r = client.post(url, {"id": asset.pk, "name": "Hax"}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 404
