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


def _delete_url(course, asset):
    return reverse(
        "courses:manage_media_delete",
        kwargs={"slug": course.slug, "pk": asset.pk},
    )


@pytest.mark.django_db
def test_delete_rejects_get_before_authentication(client):
    """@require_POST sits ABOVE @login_required, so a non-POST is a 405 whether
    or not anyone is logged in. An ANONYMOUS get is the only case that can
    falsify the ordering -- a logged-in GET is 405 under either order."""
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    r = client.get(_delete_url(course, asset))
    assert r.status_code == 405  # NOT a 302 to the login page
    assert MediaAsset.objects.filter(pk=asset.pk).exists()


@pytest.mark.django_db
def test_delete_rejects_get_as_manager(client):
    pa = make_pa(client, "pa-del-get")
    course = CourseFactory(owner=pa)
    asset = MediaAssetFactory(course=course, kind="image")
    r = client.get(_delete_url(course, asset))
    assert r.status_code == 405
    assert MediaAsset.objects.filter(pk=asset.pk).exists()


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


@pytest.mark.django_db
def test_replace_control_is_enabled_even_when_the_asset_is_in_use(
    client, settings, tmp_path
):
    """The likeliest implementation slip: the trash button in the SAME
    {% with uses %} block is `{% if uses %}disabled{% endif %}`, and copying
    that line would disable replace on exactly the assets it exists for."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-inuse")
    course = CourseFactory(owner=pa, slug="inuse-repl")
    asset = make_image_asset(course, filename="x.png")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, ImageElement.objects.create(media=asset, alt="a"))

    body = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()

    # Scope to the ELEMENT, not a byte window: a window would sit the delete
    # button's `disabled` just outside it by a margin made of the course slug's
    # length, the CSRF token and the implementer's line wrapping -- so a reformat
    # would red a correct build.
    import re

    open_tag = re.search(r"<button[^>]*data-replace-asset[^>]*>", body)
    assert open_tag, "the replace button is missing"
    assert "disabled" not in open_tag.group(0)  # replace stays live...
    assert "In use — cannot delete" in body  # ...while delete is refused


@pytest.mark.django_db
def test_cell_carries_di_uses_for_the_drag_warning(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-di")
    course = CourseFactory(owner=pa, slug="di-repl")
    plain = make_image_asset(course, filename="plain.png")
    dragged = make_image_asset(course, filename="dragged.png")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    from courses.models import DragToImageQuestionElement

    add_element(
        unit,
        DragToImageQuestionElement.objects.create(
            media=dragged, alt="Diagram", distractors=""
        ),
    )

    body = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()

    # Same regex-on-the-open-tag technique as the sibling test: a byte window
    # is fragile against slug length and the implementer's line wrapping.
    import re

    for pk, expected in ((dragged.pk, "1"), (plain.pk, "0")):
        tag = re.search(
            rf'<div class="asset-cell"[^>]*data-asset-id="{pk}"[^>]*>', body
        )
        assert tag, pk
        assert f'data-di-uses="{expected}"' in tag.group(0), pk


@pytest.mark.django_db
def test_manager_renders_all_six_replace_message_attributes(client, settings, tmp_path):
    """The ONLY assertion that can fail if manager.html is never touched.
    msg(host, key, fallback) returns the English fallback when an attribute is
    missing, and the suite runs in English -- so every other test in this plan,
    including the e2e ones, passes byte-identically against a manager.html that
    was never edited, and the Polish translations would ship dead."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-msgs")
    course = CourseFactory(owner=pa, slug="msgs-repl")
    make_image_asset(course, filename="x.png")

    body = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()

    for key in (
        "replace-confirm",
        "replace-drag-warning",
        "replace-commit",
        "replace-cancel",
        "replace-failed",
        "replace-aria",
    ):
        marker = f'data-msg-{key}="'
        assert marker in body, key
        value = body[body.index(marker) + len(marker) :]
        assert value[: value.index('"')].strip(), f"{key} is empty"


@pytest.mark.django_db
def test_no_template_comment_leaks_into_the_asset_cell(client, settings, tmp_path):
    """Django's lexer matches {#...#} WITHOUT re.DOTALL, so a hash comment that
    spans lines never matches and its source renders verbatim into the page.
    _asset_cell.html shipped exactly that -- eleven lines of prose above every
    thumbnail -- and no assertion here noticed, because every replace test
    matches on tags and attributes. Only the e2e screenshots showed it."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-comment")
    course = CourseFactory(owner=pa, slug="comment-repl")
    make_image_asset(course, filename="x.png")

    body = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()

    # The delimiters themselves, not any one comment's wording: a future
    # multi-line hash comment anywhere in the manager's templates leaks the same
    # way, and this catches it whatever it says.
    assert "{#" not in body and "#}" not in body
    assert "{%" not in body and "%}" not in body


@pytest.mark.django_db
def test_asset_cell_title_carries_the_untruncated_name(client, settings, tmp_path):
    """The visible name is truncated; the tooltip must be a SUPERSET of it."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "title-pa")
    course = CourseFactory(owner=pa, slug="cell-title")
    long_name = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    make_image_asset(course, filename=long_name)
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert f'title="{long_name}"' in body  # full, in the attribute
    assert f">{long_name}<" not in body  # truncated, in the body
    assert "…" in body


@pytest.mark.django_db
def test_asset_fname_is_suppressed_when_it_equals_the_display_name(
    client, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "fname-off-pa")
    course = CourseFactory(owner=pa, slug="cell-fname-off")
    make_image_asset(course, filename="plain.png")  # no custom name
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    assert 'class="asset-fname"' not in resp.content.decode()


@pytest.mark.django_db
def test_asset_fname_renders_with_its_own_title_when_it_differs(
    client, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "fname-on-pa")
    course = CourseFactory(owner=pa, slug="cell-fname-on")
    asset = make_image_asset(course, filename="original.png")
    asset.name = "Custom name"
    asset.save()
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert 'class="asset-fname"' in body
    assert 'title="original.png"' in body


@pytest.mark.django_db
def test_preview_hook_is_on_image_thumbs_only(client, settings, tmp_path):
    """Seeding BOTH kinds is the point: with only an image asset, `count == 1`
    would be true whether or not the video branch carried the hook."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "hook-pa")
    course = CourseFactory(owner=pa, slug="cell-hook")
    make_image_asset(course, filename="pic.png")
    MediaAsset.objects.create(
        course=course, kind="video", original_filename="clip.mp4", file="clip.mp4"
    )
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert "asset-thumb--video" in body  # the video cell DID render
    assert body.count("data-asset-preview") == 1  # ...and carries no hook


@pytest.mark.django_db
def test_a_markup_bearing_name_is_escaped_in_body_and_title(client, settings, tmp_path):
    """original_filename comes from an uploaded file name. If middle_truncate is
    ever mark_safe()d, this is the test that goes red instead of shipping XSS."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "xss-pa")
    course = CourseFactory(owner=pa, slug="cell-xss")
    make_image_asset(course, filename="<img src=x onerror=1>.png")
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert "<img src=x onerror=1>" not in body
    assert "&lt;img src=x onerror=1&gt;" in body


@pytest.mark.django_db
def test_manager_grid_renders_the_thumb_and_keeps_its_hooks(client, settings, tmp_path):
    """A forgotten template must be RED, not invisible: the tag's own unit
    tests (tests/test_media_img_tag.py) and any geometry test pass trivially
    if a template was never converted to call media_img -- they never render
    _asset_cell.html at all. This test is the one that actually renders the
    manager page and inspects the served markup.

    Also guards the hover-preview ordering constraint: media_preview.js
    (Task 9) reads data-url off the CELL, not the thumb's own src, so that
    hover keeps previewing the full-resolution original once the cell's own
    <img> starts pointing at the (smaller) thumb.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "grid-pa")
    course = CourseFactory(owner=pa, slug="grid-course")
    asset = make_image_asset(
        course, filename="w.png", size=(2000, 1500), derivatives=True
    )
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    html = resp.content.decode()
    assert asset.thumb.url in html
    assert 'class="asset-thumb"' in html
    assert "data-asset-preview" in html  # media_preview.js is armed off this
    assert 'loading="lazy"' in html
    # The hover-preview hook: data-url on the CELL must still be the original,
    # even though the <img> itself now serves the thumb.
    assert f'data-url="{asset.file.url}"' in html


@pytest.mark.django_db
def test_picker_grid_renders_the_thumb_and_does_not_arm_the_preview(
    client, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pick-grid-pa")
    course = CourseFactory(owner=pa, slug="pick-grid-course")
    asset = make_image_asset(
        course, filename="w.png", size=(2000, 1500), derivatives=True
    )
    url = reverse("courses:manage_media_picker", kwargs={"slug": course.slug})
    resp = client.get(url + "?kind=image&grid=1", HTTP_X_REQUESTED_WITH="fetch")
    html = resp.content.decode()
    assert asset.thumb.url in html
    assert 'class="asset-thumb"' in html
    assert "data-asset-preview" not in html
    # The picker's own hover-preview hook: data-url on the button must still
    # be the original.
    assert f'data-url="{asset.file.url}"' in html
