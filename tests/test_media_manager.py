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
from tests.factories import make_image_asset
from tests.factories import make_pa
from tests.factories import make_teacher


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
    r = client.post(
        url, {"id": asset.pk, "name": "  Cover art  "}, HTTP_X_REQUESTED_WITH="fetch"
    )
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
    r = client.post(
        url, {"id": asset.pk, "name": "x" * 256}, HTTP_X_REQUESTED_WITH="fetch"
    )
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


# ---------------------------------------------------------------------------
# Filter + search tests (Task 5)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assets_with_usage_filters_by_kind_and_q():
    course = CourseFactory(slug="filtercourse")
    MediaAsset.objects.create(
        course=course,
        kind="image",
        file="a.png",
        original_filename="apple.png",
        name="Red apple",
    )
    MediaAsset.objects.create(
        course=course,
        kind="image",
        file="b.png",
        original_filename="banana.png",
        name="",
    )
    MediaAsset.objects.create(
        course=course,
        kind="video",
        file="c.mp4",
        original_filename="apple-clip.mp4",
        name="",
    )

    only_images = media_svc.assets_with_usage(course, kind="image")
    assert {a.original_filename for a in only_images} == {"apple.png", "banana.png"}

    apples = media_svc.assets_with_usage(course, q="apple")
    assert {a.original_filename for a in apples} == {"apple.png", "apple-clip.mp4"}

    empty_q = media_svc.assets_with_usage(course, q="   ")
    assert len(empty_q) == 3  # blank q = no filter


@pytest.mark.django_db
def test_picker_view_filters_by_q(client):
    # Set up a platform-admin user and log in
    pa = make_pa(client, "papicker")
    course = CourseFactory(owner=pa, slug="pickercourse")
    # Existing asset (the "x.png" asset)
    MediaAssetFactory(course=course, kind="image", original_filename="x.png")
    # Additional asset to search for
    MediaAsset.objects.create(
        course=course,
        kind="image",
        file="y.png",
        original_filename="yacht.png",
        name="Yacht",
    )
    url = reverse("courses:manage_media_picker", kwargs={"slug": course.slug})
    html = client.get(
        url + "?kind=image&q=yacht", HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    # The picker grid renders display_name (the asset's name, falling back to
    # original_filename), so the matched asset shows as "Yacht"; the q-filter
    # excludes the unrelated x.png asset entirely.
    assert "Yacht" in html and "x.png" not in html


@pytest.mark.django_db
def test_usage_count_includes_drag_to_image():
    # Regression: drag-to-image questions also FK a MediaAsset (PROTECT); usage_count
    # must count them or the asset would show "unused" with delete enabled.
    from tests.factories import DragToImageQuestionElementFactory

    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    add_element(unit, DragToImageQuestionElementFactory(media=asset))
    assert media_svc.usage_count(asset) == 1
    with pytest.raises(media_svc.AssetInUseError):
        media_svc.delete_asset(asset)


@pytest.mark.django_db
def test_assets_with_usage_lists_where_used():
    from tests.factories import DragToImageQuestionElementFactory

    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz", title="Cell quiz"
    )
    add_element(unit, DragToImageQuestionElementFactory(media=asset))
    row = next(a for a in media_svc.assets_with_usage(course) if a.pk == asset.pk)
    assert row.di_uses == 1
    assert len(row.usages) == 1
    u = row.usages[0]
    assert u["unit_pk"] == unit.pk
    assert u["unit_title"] == "Cell quiz"
    assert str(u["type_label"]) == "Drag to image"


@pytest.mark.django_db
def test_manager_page_links_where_used_to_editor(client):
    from tests.factories import DragToImageQuestionElementFactory

    pa = make_pa(client, "pa_wu")
    course = CourseFactory(owner=pa, slug="wu")
    asset = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz", title="Cell quiz"
    )
    add_element(unit, DragToImageQuestionElementFactory(media=asset))
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    editor_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    assert f'href="{editor_url}"' in body
    assert "Cell quiz" in body


@pytest.mark.django_db
def test_manager_page_links_to_builder(client):
    # The course name in the library header links back to the builder so the author
    # isn't forced through dashboard > Studio > All courses to get back.
    pa = make_pa(client, "pa_mb")
    course = CourseFactory(owner=pa, slug="mb")
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    builder_url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    assert f'href="{builder_url}"' in resp.content.decode()


# ---------------------------------------------------------------------------
# Replace endpoint
# ---------------------------------------------------------------------------


def _replace_url(course, asset):
    return reverse(
        "courses:manage_media_replace",
        kwargs={"slug": course.slug, "pk": asset.pk},
    )


def _upload_png(name="new.png"):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_replace_rejects_get_before_authentication(client, settings, tmp_path):
    """@require_POST sits ABOVE @login_required, so a non-POST is a 405 whether
    or not anyone is logged in. An ANONYMOUS get is the only case that can
    falsify the ordering -- a logged-in GET is 405 under either order."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="x.png")
    r = client.get(_replace_url(course, asset))
    assert r.status_code == 405  # NOT a 302 to the login page


@pytest.mark.django_db
def test_anonymous_post_redirects_to_login(client, settings, tmp_path):
    """@login_required sends an anonymous POST to the login page -- a 302, not a
    403. The 403 belongs to an AUTHENTICATED non-manager (next test)."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="x.png")
    r = client.post(_replace_url(course, asset), {"file": _upload_png()})
    assert r.status_code == 302
    assert "/accounts/login/" in r["Location"]


@pytest.mark.django_db
def test_replace_requires_manage_rights(client, settings, tmp_path):
    """The requester must be a TEACHER, not a Platform Admin.

    can_manage_course (courses/access.py:37-43) grants on ownership OR the
    `courses.change_course` model perm, and PLATFORM_ADMIN_PERMS splats in
    *COURSE_PERMS -- so a PA manages EVERY course and this test would get a 200
    on a correct build. CourseFactory() leaves owner NULL, so the ownership
    disjunct is skipped and only the perm decides. A Teacher holds
    grouping.view_collection and no course perms, so it is genuinely refused.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    make_teacher(client, "teacher-repl")
    course = CourseFactory()  # owner is NULL, and the teacher has no course perm
    asset = make_image_asset(course, filename="x.png")
    r = client.post(
        _replace_url(course, asset),
        {"file": _upload_png()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert r.status_code == 403  # PermissionDenied from _require_manage


@pytest.mark.django_db
def test_replace_with_a_zero_byte_upload_is_422(client, settings, tmp_path):
    """Pins the guard's HTTP behaviour rather than inferring it.

    The empty-file check exists specifically for this path -- MediaAsset.clean()
    has no lower size bound and only the upload FORM rejects an empty file. This
    also proves Django's multipart parser surfaces a 0-byte part in
    request.FILES at all, rather than dropping it (which would make the request
    a "no file key" 422 for an entirely different reason).
    """
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-empty")
    course = CourseFactory(owner=pa, slug="empty-repl")
    asset = make_image_asset(course, filename="old.png")

    r = client.post(
        _replace_url(course, asset),
        {"file": SimpleUploadedFile("e.png", b"", content_type="image/png")},
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert r.status_code == 422
    assert "empty" in r.content.decode().lower()
    asset.refresh_from_db()
    assert asset.original_filename == "old.png"


@pytest.mark.django_db
def test_replace_404s_for_an_asset_in_another_course(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-404")
    mine = CourseFactory(owner=pa, slug="mine-repl")
    theirs = CourseFactory(slug="theirs-repl")
    stranger = make_image_asset(theirs, filename="x.png")
    url = reverse(
        "courses:manage_media_replace",
        kwargs={"slug": mine.slug, "pk": stranger.pk},
    )
    r = client.post(url, {"file": _upload_png()}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 404


@pytest.mark.django_db
def test_replace_without_a_file_key_is_422_not_500(client, settings, tmp_path):
    """The guard tests the KEY, not request.FILES emptiness: a multipart POST
    under a different field name would pass an emptiness check and then raise
    MultiValueDictKeyError -- a 500 -- on the access."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-nofile")
    course = CourseFactory(owner=pa, slug="nofile-repl")
    asset = make_image_asset(course, filename="x.png")
    url = _replace_url(course, asset)

    assert client.post(url, {}, HTTP_X_REQUESTED_WITH="fetch").status_code == 422
    wrong_key = client.post(
        url, {"upload": _upload_png()}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert wrong_key.status_code == 422


@pytest.mark.django_db
def test_replace_returns_the_rerendered_cell(
    client, settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-ok")
    course = CourseFactory(owner=pa, slug="ok-repl")
    asset = make_image_asset(course, filename="old.png", name="Cover art")

    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(
            _replace_url(course, asset),
            {"file": _upload_png("brand-new.png")},
            HTTP_X_REQUESTED_WITH="fetch",
        )

    assert r.status_code == 200
    body = r.content.decode()
    assert "brand-new.png" in body  # original_filename followed the file
    assert "Cover art" in body  # the custom display name survived
    assert 'data-replace-url="' in body  # the cell can be replaced again


@pytest.mark.django_db
def test_replace_ignores_a_client_supplied_kind(
    client, settings, tmp_path, django_capture_on_commit_callbacks
):
    """The single reason the view does NOT reuse MediaAssetForm (fields are
    ["kind", "file"]). Without this test a future refactor could reintroduce a
    client-controlled kind -- flipping an in-use image asset to video and
    breaking limit_choices_to for three FK models -- with the suite green."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-kind")
    course = CourseFactory(owner=pa, slug="kind-repl")
    asset = make_image_asset(course, filename="old.png")

    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(
            _replace_url(course, asset),
            {"file": _upload_png(), "kind": "video"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

    assert r.status_code == 200
    asset.refresh_from_db()
    assert asset.kind == "image"


@pytest.mark.django_db
def test_replace_with_a_rejected_file_is_422_with_the_validator_message(
    client, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-bad")
    course = CourseFactory(owner=pa, slug="bad-repl")
    asset = make_image_asset(course, filename="old.png")
    mp4 = SimpleUploadedFile("v.mp4", b"\x00" * 256, content_type="video/mp4")

    r = client.post(
        _replace_url(course, asset), {"file": mp4}, HTTP_X_REQUESTED_WITH="fetch"
    )

    assert r.status_code == 422
    assert "mp4" in r.content.decode().lower()
    asset.refresh_from_db()
    assert asset.original_filename == "old.png"


@pytest.mark.django_db
def test_replace_without_the_fetch_header_redirects(
    client, settings, tmp_path, django_capture_on_commit_callbacks
):
    """The no-JS path. Every branch carries its own _wants_fragment check, so a
    header-less POST redirects whichever branch it lands in."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-nojs")
    course = CourseFactory(owner=pa, slug="nojs-repl")
    asset = make_image_asset(course, filename="old.png")
    target = reverse("courses:manage_media", kwargs={"slug": course.slug})

    with django_capture_on_commit_callbacks(execute=True):
        ok = client.post(_replace_url(course, asset), {"file": _upload_png()})
    assert ok.status_code == 302 and ok["Location"] == target

    missing = client.post(_replace_url(course, asset), {})
    assert missing.status_code == 302 and missing["Location"] == target
