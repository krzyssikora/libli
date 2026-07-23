"""The migrate_course_content command: export a course's top-level parts to a
bundle, graft the bundle into an existing target course, verify the result."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError
from django.core.management import call_command

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import TextElement

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    # The import path writes real files through default_storage. Without this
    # redirect, tests pollute the repo's media/ dir -- the same guard
    # tests/test_transfer_subtree.py uses.
    settings.MEDIA_ROOT = tmp_path / "media"


def _mk_source(slug="src", parts=("P0", "P1")):
    """A parts->chapter->unit course with one text + one image per unit.

    Titles are deliberately plain except where a test overrides them; one part
    carries a __PLACEHOLDER-style chapter to pin verbatim title carry-over.
    """
    course = Course.objects.create(
        title="Source", slug=slug, uses_parts=True, uses_chapters=True
    )
    for i, title in enumerate(parts):
        part = ContentNode.objects.create(course=course, kind="part", title=title)
        chapter = ContentNode.objects.create(
            course=course,
            kind="chapter",
            title=f"__PLACEHOLDER chapter {i}__",
            parent=part,
        )
        unit = ContentNode.objects.create(
            course=course,
            kind="unit",
            title=f"U{i}",
            parent=chapter,
            unit_type="lesson",
        )
        asset = MediaAsset.objects.create(
            course=course,
            kind="image",
            file=SimpleUploadedFile(f"p{i}.png", b"\x89PNG fake"),
            original_filename=f"p{i}.png",
            name=f"Pic {i}",
        )
        Element.objects.create(
            unit=unit,
            title="T",
            content_object=TextElement.objects.create(body="<p>hi</p>"),
        )
        Element.objects.create(
            unit=unit,
            title="",
            content_object=ImageElement.objects.create(media=asset, alt="a"),
        )
    return course


def _mk_target(slug="dst"):
    """An EMPTY target that allows parts at top level, mirroring mat-pp."""
    return Course.objects.create(
        title="Target", slug=slug, uses_parts=True, uses_chapters=True
    )


def test_export_writes_one_archive_per_part_named_by_zero_based_order(tmp_path):
    _mk_source(parts=("Alpha", "Beta", "Gamma"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
    )
    names = sorted(p.name for p in bundle.glob("*.zip"))
    assert len(names) == 3
    # 0-based order, zero-padded, matching ContentNode.order.
    assert names[0].startswith("00-")
    assert names[1].startswith("01-")
    assert names[2].startswith("02-")


def test_export_writes_the_media_side_table_keyed_by_source_pk(tmp_path):
    course = _mk_source(parts=("Alpha", "Beta"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
    )
    table = json.loads((bundle / "media-parts.json").read_text(encoding="utf-8"))
    pks = {a.pk for a in MediaAsset.objects.filter(course=course)}
    # Every source asset appears, keyed by its own pk, mapped to part orders.
    assert {int(k) for k in table} == pks
    for parts in table.values():
        assert parts and all(isinstance(i, int) for i in parts)


def test_export_rejects_an_unknown_source_slug(tmp_path):
    with pytest.raises(CommandError, match="no course with slug"):
        call_command(
            "migrate_course_content",
            "export",
            "--source-slug",
            "nope",
            "--bundle-dir",
            str(tmp_path / "b"),
        )


def test_export_aborts_on_problems_and_allow_problems_overrides(tmp_path, monkeypatch):
    """The spec's central content-loss guard: build_export's 4th return value.

    Exporting 21 parts while silently accepting placeholdered media is the
    precise failure this whole effort exists to avoid, so the abort is default
    and the override must be explicit. build_export is monkeypatched because
    provoking a real `problems` entry depends on filesystem state; what is
    under test is the command's reaction, not the engine's detection.
    """
    from courses.management.commands import migrate_course_content as mod

    _mk_source(parts=("Only",))
    real = mod.build_export

    def fake(course, node=None, **kw):
        manifest, document, media_assets, _problems = real(course, node=node, **kw)
        return manifest, document, media_assets, ["missing media: x.png"]

    monkeypatch.setattr(mod, "build_export", fake)

    bundle = tmp_path / "bundle"
    with pytest.raises(CommandError, match="problem"):
        call_command(
            "migrate_course_content",
            "export",
            "--source-slug",
            "src",
            "--bundle-dir",
            str(bundle),
        )
    assert not list(bundle.glob("*.zip")) if bundle.exists() else True

    # The override lets the same export through.
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
        "--allow-problems",
    )
    assert len(list(bundle.glob("*.zip"))) == 1


def test_export_rerun_overwrites_rather_than_duplicating(tmp_path):
    _mk_source(parts=("Alpha", "Beta"))
    bundle = tmp_path / "bundle"
    for _ in range(2):
        call_command(
            "migrate_course_content",
            "export",
            "--source-slug",
            "src",
            "--bundle-dir",
            str(bundle),
        )
    # Deterministic names mean the second run replaces the first's archives.
    assert len(list(bundle.glob("*.zip"))) == 2


def test_export_refuses_import_only_flags(tmp_path):
    _mk_source()
    with pytest.raises(CommandError, match="not valid for"):
        call_command(
            "migrate_course_content",
            "export",
            "--source-slug",
            "src",
            "--bundle-dir",
            str(tmp_path / "b"),
            "--force",
        )


def _export_bundle(tmp_path, parts=("P0", "P1", "P2")):
    _mk_source(parts=parts)
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
    )
    return bundle


def _user(email="mig@example.com"):
    return get_user_model().objects.create_user(
        username="mig", email=email, password="x"
    )


def test_import_grafts_every_part_at_top_level_in_source_order(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    tops = list(
        ContentNode.objects.filter(course=target, parent__isnull=True)
        .order_by("order", "pk")
        .values_list("title", flat=True)
    )
    assert tops == ["P0", "P1", "P2"]


def test_import_carries_placeholder_titles_verbatim(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    assert ContentNode.objects.filter(
        course=target, title="__PLACEHOLDER chapter 0__"
    ).exists()


def test_import_stamps_uploaded_by_from_as_user(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    u = _user()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    assets = MediaAsset.objects.filter(course=target)
    assert assets.exists()
    assert all(a.uploaded_by_id == u.pk for a in assets)


def test_import_rejects_an_unknown_as_user(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    _mk_target()
    with pytest.raises(CommandError, match="no user with email"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "ghost@example.com",
        )


def test_import_refuses_a_non_empty_target_without_force(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    _user()
    ContentNode.objects.create(course=target, kind="part", title="Squatter")
    with pytest.raises(CommandError, match="already has"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
        )


def test_dry_run_validates_every_archive_and_writes_nothing(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--dry-run",
    )
    assert ContentNode.objects.filter(course=target).count() == 0
    assert MediaAsset.objects.filter(course=target).count() == 0


def test_start_at_grafts_only_the_remainder(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    # Simulate a run that already committed part 0.
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--start-at",
        "0",
    )
    # Now only parts 1..2 remain; resume from 1 would duplicate nothing.
    ContentNode.objects.filter(course=target, parent__isnull=True).exclude(
        title="P0"
    ).delete()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--start-at",
        "1",
    )
    tops = list(
        ContentNode.objects.filter(course=target, parent__isnull=True)
        .order_by("order", "pk")
        .values_list("title", flat=True)
    )
    assert tops == ["P0", "P1", "P2"]


@pytest.mark.parametrize("bad", [0, 2])
def test_start_at_aborts_when_the_target_node_count_disagrees(tmp_path, bad):
    """--start-at K requires exactly K top-level nodes already present.

    With one part committed, K=1 is the only legal resume point; K=0 and K=2
    are the off-by-one mistypes this invariant exists to catch.
    """
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--start-at",
        "0",
    )
    ContentNode.objects.filter(course=target, parent__isnull=True).exclude(
        title="P0"
    ).delete()
    with pytest.raises(CommandError, match="expects the target to hold"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
            "--start-at",
            str(bad),
        )


def test_html_element_attributes_survive_the_round_trip(tmp_path):
    """Regression guard on the not-sanitized policy.

    _build_html stores HtmlElement.html verbatim -- the sandboxed iframe is the
    security boundary, not sanitisation. If someone later adds sanitisation
    there, the binary decision tree's data-binary-choose hooks would be
    stripped and it would migrate as intact-looking dead markup.
    """
    from courses.models import HtmlElement

    course = _mk_source(parts=("Only",))
    unit = ContentNode.objects.get(course=course, title="U0")
    Element.objects.create(
        unit=unit,
        title="",
        content_object=HtmlElement.objects.create(
            html='<button data-binary-choose="1.1">Tak</button>'
        ),
    )
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
    )
    _mk_target()
    _user()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    htmls = [
        h.html for h in HtmlElement.objects.all() if "data-binary-choose" in h.html
    ]
    assert len(htmls) == 2  # source's and the target's copy
    assert all('data-binary-choose="1.1"' in h for h in htmls)


def test_a_corrupt_archive_is_named_in_the_error(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    _mk_target()
    _user()
    victim = next(bundle.glob("*.zip"))
    victim.write_bytes(b"not a zip at all")
    with pytest.raises(CommandError, match=victim.name):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
        )


def test_a_first_part_failure_reports_that_nothing_was_committed(tmp_path):
    """The degenerate K=0 boundary: no 'last part committed' exists to resume
    from, so the message must send the operator to a plain re-run."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    first = sorted(bundle.glob("*.zip"))[0]
    first.write_bytes(b"corrupt")
    with pytest.raises(CommandError, match="no parts committed"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
        )
    assert ContentNode.objects.filter(course=target).count() == 0


def test_force_lets_the_import_proceed_into_a_non_empty_target(tmp_path):
    """The refusal path is tested above; this pins that the override WORKS.

    A falsification proves the guard can fail; only this proves its bypass
    isn't inverted or ignored.
    """
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    _user()
    ContentNode.objects.create(course=target, kind="part", title="Squatter")
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--force",
    )
    tops = set(
        ContentNode.objects.filter(course=target, parent__isnull=True).values_list(
            "title", flat=True
        )
    )
    assert tops == {"Squatter", "Only"}


def test_import_rejects_an_empty_bundle_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _mk_target()
    _user()
    with pytest.raises(CommandError, match="no archives"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(empty),
            "--as-user",
            "mig@example.com",
        )
