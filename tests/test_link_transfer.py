import pytest

from courses.models import TextElement
from courses.transfer.export import build_export
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from courses.transfer.schema import validate_document
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element


def _text(body):
    """A saved TextElement. There is no TextElementFactory; this is the repo's idiom
    (see tests/test_guessnumber_endpoint.py). Note save() sanitises the body -- a
    relative href passes through untouched, which is the whole premise."""
    obj = TextElement(body=body)
    obj.save()
    return obj


pytestmark = pytest.mark.django_db


def _course_with_link():
    course = CourseFactory()
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    el = _text(f'<a href="/courses/n/{chapter.pk}/">ch</a>')
    add_element(unit, el)
    return course, chapter, unit


def test_export_records_in_scope_link_targets():
    course, chapter, _unit = _course_with_link()
    _manifest, document, _assets, _problems = build_export(course)
    assert str(chapter.pk) in document["link_nodes"]
    assert document["link_nodes"][str(chapter.pk)].startswith("n")


def test_export_leaves_bodies_byte_identical():
    course, chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    bodies = [e["data"]["body"] for e in document["elements"] if e["type"] == "text"]
    assert bodies == [f'<a href="/courses/n/{chapter.pk}/">ch</a>']


def test_format_version_is_6():
    assert FORMAT_VERSION == 6


def test_subtree_documents_carry_link_nodes_too():
    course, chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course, node=chapter)
    assert "link_nodes" in document
    # target_allowed_kinds is REQUIRED for kind="subtree": validate_document computes
    # `allowed = list(target_allowed_kinds or [])`, so omitting it rejects every node
    # ("The archive contains a 'chapter' node, which this structure does not allow").
    # Matches how importer.py:392 and tests/test_transfer_validation.py:63 call it.
    validate_document(
        document, kind="subtree", target_allowed_kinds=["chapter", "unit"]
    )


def test_v5_document_without_link_nodes_still_validates():
    # setdefault BEFORE _exact_keys is what makes the key optional in both directions:
    # without it a v5 doc fails "missing the key", and a new doc fails "unknown key".
    course, _chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    del document["link_nodes"]
    validate_document(document, kind="course")  # must not raise


@pytest.mark.parametrize(
    "bad",
    [
        [],  # not a dict
        {"abc": "n1"},  # non-decimal key
        {"1": 2},  # non-string value
        {"1" * 20: "n1"},  # over-long key
    ],
)
def test_malformed_link_nodes_is_a_transfer_error(bad):
    course, _chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    document["link_nodes"] = bad
    with pytest.raises(TransferError):
        validate_document(document, kind="course")


# --- Task 4: import-side rewrite ---------------------------------------------


def _round_trip(course, user, report, *, document_hook=None):
    """Export to a buffer and import it back as a new course.

    import_course takes (zf, manifest, document, media_entries, user) -- it is NOT a
    file-taking helper. This mirrors tests/test_transfer_import.py::_import_zip.
    """
    import io

    from courses.transfer.export import build_export
    from courses.transfer.export import write_archive_from
    from courses.transfer.importer import import_course
    from courses.transfer.importer import open_archive
    from courses.transfer.importer import validate_archive_document

    manifest, document, assets, _problems = build_export(course)
    if document_hook:
        document_hook(document)
    buf = io.BytesIO()
    write_archive_from(manifest, document, assets, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="course")
        return import_course(zf, mani, doc, media, user, report=report)


def test_round_trip_rewrites_to_the_new_pk():
    course, chapter, _unit = _course_with_link()
    report = {}
    new_course = _round_trip(course, course.owner, report)

    from courses.models import ContentNode
    from courses.models import TextElement

    new_chapter = ContentNode.objects.get(course=new_course, title="Ch")
    body = TextElement.objects.filter(elements__unit__course=new_course).first().body
    assert f"/courses/n/{new_chapter.pk}/" in body
    assert f"/courses/n/{chapter.pk}/" not in body  # NOT the original
    assert report["flattened_links"] == 0


def test_unmapped_link_is_flattened_and_counted():
    course, _chapter, _unit = _course_with_link()
    report = {}
    # Simulate a target outside the exported set (what a subtree export produces).
    new_course = _round_trip(
        course,
        course.owner,
        report,
        document_hook=lambda doc: doc.__setitem__("link_nodes", {}),
    )

    from courses.models import TextElement

    body = TextElement.objects.filter(elements__unit__course=new_course).first().body
    assert "<a" not in body
    assert "ch" in body
    assert report["flattened_links"] == 1


def test_v5_archive_import_course_still_succeeds():
    # A v5 archive predates link_nodes entirely. It stays importable because
    # validate_document does doc.setdefault("link_nodes", {}) IN PLACE (Task 3,
    # courses/transfer/schema.py) and _round_trip always calls validate_archive_document
    # before import_course -- so document["link_nodes"] is already populated by the
    # time _rewrite_links runs. (_rewrite_links's own `.get(...) or {}` is only
    # belt-and-braces for a caller that skips validation; it is not what makes THIS
    # test pass -- falsified by temporarily bare-indexing document["link_nodes"] there
    # and confirming this test stayed green.)
    course, _chapter, _unit = _course_with_link()
    report = {}
    new_course = _round_trip(
        course,
        course.owner,
        report,
        document_hook=lambda doc: doc.pop("link_nodes"),
    )

    from courses.models import TextElement

    body = TextElement.objects.filter(elements__unit__course=new_course).first().body
    assert "<a" not in body  # unresolvable target (no map at all) -> unwrap+count
    assert "ch" in body
    assert report["flattened_links"] == 1


def test_duplicate_unit_keeps_an_out_of_scope_link():
    # The case the naive rule gets wrong: those pks still resolve in this install, so
    # flattening a working link would be a regression.
    from courses import builder as builder_svc

    course, chapter, unit = _course_with_link()
    # duplicate_unit returns a ContentNode, NOT a pk (courses/builder.py:352).
    copy_node = builder_svc.duplicate_unit(
        course, unit.pk, token=unit.updated.isoformat()
    )
    copied = TextElement.objects.filter(elements__unit_id=copy_node.pk).first()
    assert f"/courses/n/{chapter.pk}/" in copied.body  # unchanged


def test_duplicate_unit_rewrites_a_self_link():
    # The only in-scope rewrite this path can exercise: duplicate_unit raises for
    # anything that is not a unit, so the exported document always holds one node.
    from courses import builder as builder_svc

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    add_element(unit, _text(f'<a href="/courses/n/{unit.pk}/">self</a>'))
    copy_node = builder_svc.duplicate_unit(
        course, unit.pk, token=unit.updated.isoformat()
    )
    copied = TextElement.objects.filter(elements__unit_id=copy_node.pk).first()
    assert f"/courses/n/{copy_node.pk}/" in copied.body


# --- Task 4: view-level warning -----------------------------------------------


@pytest.fixture(autouse=True)
def _staging_tmp(settings, tmp_path):
    # Task 12's import views write real staged zips through courses.transfer.staging
    # unless redirected -- without this, they'd land in BASE_DIR/transfer_staging/.
    settings.TRANSFER_STAGING_DIR = tmp_path / "staging"


def _add_course_perm(user):
    from django.contrib.auth.models import Permission

    user.user_permissions.add(
        Permission.objects.get(codename="add_course", content_type__app_label="courses")
    )


def _upload_and_confirm(client, course, *, drop_link_nodes=False):
    """Copies the upload -> confirm sequence from tests/test_transfer_views.py, but
    builds the archive via build_export + write_archive_from (not write_archive) so
    link_nodes can be emptied before writing -- mirrors _round_trip's document_hook.
    """
    import io

    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse

    from courses.transfer.export import build_export
    from courses.transfer.export import write_archive_from
    from tests.factories import TEST_PASSWORD

    # create_user (not UserFactory/make_verified_user): mirrors the `owner` fixture
    # in tests/test_transfer_views.py -- no email, so allauth's mandatory-verification
    # AccountMiddleware never intercepts the session with a verify-email redirect.
    User = get_user_model()
    owner = User.objects.create_user(
        f"owner{User.objects.count()}", password=TEST_PASSWORD
    )
    _add_course_perm(owner)  # import_course_view/confirm require courses.add_course
    manifest, document, assets, _problems = build_export(course)
    if drop_link_nodes:
        document["link_nodes"] = {}
    buf = io.BytesIO()
    write_archive_from(manifest, document, assets, buf)
    client.force_login(owner)
    upload = SimpleUploadedFile("x.zip", buf.getvalue(), content_type="application/zip")
    preview = client.post(reverse("courses:manage_course_import"), {"archive": upload})
    token = preview.context["token"]
    return client.post(
        reverse("courses:manage_course_import_confirm"), {"token": token}
    )


def _upload_and_confirm_subtree(client, course, *, node, drop_link_nodes=False):
    """Same shape as `_upload_and_confirm`, against manage_import_content /
    manage_import_content_confirm (tests/test_transfer_views.py::
    test_subtree_confirm_top_level is the sequence copied here): exports a SUBTREE
    (`build_export(course, node=...)`) into a purpose-built target course and posts
    a top-level `insertion` choice.
    """
    import io

    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse

    from courses.models import Course
    from courses.transfer.export import build_export
    from courses.transfer.export import write_archive_from
    from tests.factories import TEST_PASSWORD

    User = get_user_model()
    owner = User.objects.create_user(
        f"owner{User.objects.count()}", password=TEST_PASSWORD
    )
    target = Course.objects.create(
        title="Target",
        slug=f"target-{course.pk}-{node.pk}",
        owner=owner,  # import_content_view/confirm require can_manage_course
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    manifest, document, assets, _problems = build_export(course, node=node)
    if drop_link_nodes:
        document["link_nodes"] = {}
    buf = io.BytesIO()
    write_archive_from(manifest, document, assets, buf)
    client.force_login(owner)
    upload = SimpleUploadedFile("x.zip", buf.getvalue(), content_type="application/zip")
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": upload},
    )
    token = preview.context["token"]
    return client.post(
        reverse("courses:manage_import_content_confirm", args=[target.slug]),
        {"token": token, "insertion": ""},
    )


def test_the_course_confirm_view_warns_about_flattened_links(client):
    from django.contrib.messages import get_messages

    course, _chapter, _unit = _course_with_link()
    resp = _upload_and_confirm(client, course, drop_link_nodes=True)
    texts = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("plain text" in t for t in texts), texts


def test_the_subtree_confirm_view_warns_too(client):
    # BOTH branches, not one. Step 6 flags that _warn_flattened placed after the
    # redirect is dead code -- and that hazard is per-branch, so a test covering only
    # the course path leaves half the new view code unguarded.
    from django.contrib.messages import get_messages

    course, chapter, _unit = _course_with_link()
    resp = _upload_and_confirm_subtree(
        client, course, node=chapter, drop_link_nodes=True
    )
    texts = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("plain text" in t for t in texts), texts
