"""The migrate_course_content command: export a course's top-level parts to a
bundle, graft the bundle into an existing target course, verify the result."""

import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError
from django.core.management import call_command

from courses.management.commands.migrate_course_content import BASELINE_NAME
from courses.management.commands.migrate_course_content import MANIFEST_NAME
from courses.management.commands.migrate_course_content import Command
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


def _read_manifest(bundle):
    return json.loads((bundle / MANIFEST_NAME).read_text(encoding="utf-8"))


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


def test_export_writes_a_bundle_manifest_with_source_tallies(tmp_path):
    _mk_source(parts=("Alpha", "Beta"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
    )
    manifest = _read_manifest(bundle)
    assert manifest["source_slug"] == "src"
    assert manifest["part_count"] == 2
    tallies = manifest["tallies"]
    # 2 parts * (1 part + 1 chapter + 1 unit) = 6 nodes; 2 elements per unit.
    assert tallies["total_nodes"] == 6
    assert tallies["node_kind_counts"] == {"part": 2, "chapter": 2, "unit": 2}
    assert tallies["total_elements"] == 4
    assert tallies["media_count"] == 2


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
    table = _read_manifest(bundle)["media_parts"]
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


def test_export_refuses_a_rerun_without_clean(tmp_path):
    """A bundle is never silently merged into: a stale archive left behind by
    an aborted or superseded export must not survive into a later import
    unnoticed. Re-running export without --clean is refused outright."""
    _mk_source(parts=("Alpha", "Beta"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
    )
    with pytest.raises(CommandError, match="already holds"):
        call_command(
            "migrate_course_content",
            "export",
            "--source-slug",
            "src",
            "--bundle-dir",
            str(bundle),
        )
    # Nothing about the first export was disturbed by the refused re-run.
    assert len(list(bundle.glob("*.zip"))) == 2


def test_export_with_clean_replaces_a_stale_bundle_rather_than_merging(tmp_path):
    """The Frankenstein-bundle scenario this whole flag exists to prevent:
    without --clean, a smaller re-export would leave the LARGER prior
    export's extra archive(s) behind, silently mixed with the new ones."""
    course = _mk_source(parts=("Alpha", "Beta", "Gamma"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
    )
    assert len(list(bundle.glob("*.zip"))) == 3

    # Shrink the source to 2 top-level parts and re-export with --clean.
    ContentNode.objects.filter(course=course, kind="part", title="Gamma").delete()
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
        "--clean",
    )
    names = sorted(p.name for p in bundle.glob("*.zip"))
    assert len(names) == 2  # the stale 3rd archive is GONE, not left behind
    assert _read_manifest(bundle)["part_count"] == 2


def test_export_aborts_on_a_top_level_order_collision(tmp_path):
    """OrderField's docstring states order is NOT database-unique. Two
    top-level nodes sharing an order would otherwise produce the same
    archive filename and the second write would silently clobber the first,
    with the command printing success for both."""
    course = _mk_source(parts=("Alpha", "Beta"))
    ContentNode.objects.filter(course=course, kind="part").update(order=0)
    bundle = tmp_path / "bundle"
    with pytest.raises(CommandError, match="order=0"):
        call_command(
            "migrate_course_content",
            "export",
            "--source-slug",
            "src",
            "--bundle-dir",
            str(bundle),
        )


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


def _export_bundle(tmp_path, parts=("P0", "P1", "P2"), source_slug="src"):
    _mk_source(slug=source_slug, parts=parts)
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        source_slug,
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
    assert not (bundle / BASELINE_NAME).exists()


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


def test_start_at_recovers_after_force_and_a_mid_run_failure(tmp_path):
    """The scenario that breaks a baseline-naive --start-at invariant:
    --force onto a target holding pre-existing (non-migration) top-level
    nodes, a mid-run failure, then a resume via the EXACT hint the command
    printed. The invariant and the hint must agree with each other."""
    bundle = _export_bundle(tmp_path, parts=("P0", "P1", "P2"))
    target = _mk_target()
    _user()
    ContentNode.objects.create(course=target, kind="part", title="Squatter1")
    ContentNode.objects.create(course=target, kind="part", title="Squatter2")

    archives = sorted(bundle.glob("*.zip"))
    archives[1].write_bytes(b"corrupt")  # part 1 fails
    with pytest.raises(CommandError, match="resume with --start-at 1"):
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
    # 2 pre-existing squatters + part 0 committed = 3 top-level nodes.
    assert ContentNode.objects.filter(course=target, parent__isnull=True).count() == 3

    # Repair the bundle (re-export overwrites via --clean) and resume exactly
    # as hinted -- the invariant must accept the hint it just printed.
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
        "--clean",
    )
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
    tops = set(
        ContentNode.objects.filter(course=target, parent__isnull=True).values_list(
            "title", flat=True
        )
    )
    assert tops == {"Squatter1", "Squatter2", "P0", "P1", "P2"}


def test_start_at_beyond_all_parts_reports_nothing_to_do(tmp_path):
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
    buf = io.StringIO()
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
        "3",
        stdout=buf,
    )  # must not raise, and must not duplicate anything
    assert "nothing to do" in buf.getvalue()
    assert ContentNode.objects.filter(course=target, parent__isnull=True).count() == 3


def test_import_refuses_a_bundle_with_no_manifest(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    _mk_target()
    _user()
    (bundle / MANIFEST_NAME).unlink()
    with pytest.raises(CommandError, match="is missing from"):
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


def test_import_refuses_a_bundle_whose_archive_count_disagrees_with_the_manifest(
    tmp_path,
):
    """The Frankenstein-bundle scenario: a bundle whose archives on disk no
    longer match its own manifest's declared part_count must be refused
    BEFORE anything is written, not grafted and blessed by `verify` after."""
    bundle = _export_bundle(tmp_path, parts=("P0", "P1", "P2"))
    target = _mk_target()
    _user()
    archives = sorted(bundle.glob("*.zip"))
    archives[-1].unlink()
    with pytest.raises(CommandError, match="declares 3 part"):
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


def test_verify_passes_after_a_complete_import(tmp_path):
    bundle = _export_bundle(tmp_path)
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
    call_command(
        "migrate_course_content",
        "verify",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
    )  # must not raise


def test_verify_fails_when_a_part_is_missing(tmp_path):
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
    ContentNode.objects.filter(course=target, parent__isnull=True, title="P2").delete()
    with pytest.raises(CommandError, match="node count mismatch"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_refuses_a_bundle_with_no_manifest(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    (bundle / MANIFEST_NAME).unlink()
    with pytest.raises(CommandError, match="is missing from"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_refuses_when_import_was_never_run(tmp_path):
    """No BASELINE_NAME means no import has established the pre-migration
    baseline yet; a delta computed against an unknown baseline is
    uninterpretable, the same reasoning that already gates on MANIFEST_NAME."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    with pytest.raises(CommandError, match="is missing from"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_wraps_a_malformed_manifest_as_a_command_error(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    (bundle / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(CommandError, match="not valid JSON"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_wraps_a_corrupt_archive_as_a_command_error(tmp_path):
    bundle = _export_bundle(tmp_path)
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
    victim = sorted(bundle.glob("*.zip"))[0]
    victim.write_bytes(b"not a zip at all")
    with pytest.raises(CommandError, match=victim.name):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_checks_element_tallies(tmp_path):
    """~20,054 of the ~21,000 objects a real migration moves are elements;
    the old check only ever looked at a bare total-node count."""
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
    Element.objects.filter(unit__course=target).first().delete()
    with pytest.raises(CommandError, match="element count mismatch"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_checks_per_kind_node_tallies(tmp_path):
    """A node miscounted by kind but not by total (e.g. a unit relabelled as
    a section) must still be caught -- the bare total-node check alone
    cannot see it."""
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
    unit = ContentNode.objects.filter(course=target, kind="unit").first()
    unit.kind = "section"
    unit.save()
    with pytest.raises(CommandError, match="node count mismatch for kind"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_fails_when_an_imported_media_asset_is_deleted(tmp_path):
    """Media must reconcile EXACTLY, not merely sit above a floor.

    With NO cross-part sharing, floor == ceiling, so a floor-only check would
    happen to still catch a single lost asset -- that would be a false sense
    of security. This uses a SHARED asset (floor < ceiling, mirroring
    test_shared_media_duplicates_and_is_accounted_for) so losing one of the
    re-materialised rows lands the count strictly BETWEEN floor and ceiling:
    a floor-only check (`floor <= actual <= expected_max`) would pass this
    silently; only an EXACT count catches it.
    """
    from courses.models import ImageElement

    course = _mk_source(parts=("P0", "P1"))
    shared = MediaAsset.objects.filter(course=course).first()
    other_unit = ContentNode.objects.get(course=course, title="U1")
    Element.objects.create(
        unit=other_unit,
        title="",
        content_object=ImageElement.objects.create(media=shared, alt="shared"),
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
    assert MediaAsset.objects.filter(course=target).count() == 3  # ceiling

    # MediaAsset.media is PROTECT-ed, and ImageElement's GenericRelation
    # cascades to its Element join -- deleting the referencing ImageElement
    # would also drop an element, muddying which check caught the loss.
    # Re-point the reference at a sibling asset first, so only the media
    # count moves, mirroring how a real "lost asset" bug would surface (a
    # row simply absent, everything else untouched).
    img = ImageElement.objects.filter(media__course=target).first()
    victim = img.media
    img.media = MediaAsset.objects.filter(course=target).exclude(pk=victim.pk).first()
    img.save()
    victim.delete()
    assert MediaAsset.objects.filter(course=target).count() == 2  # still >= floor (2)

    with pytest.raises(CommandError, match="media count mismatch"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_shared_media_duplicates_and_is_accounted_for(tmp_path):
    """An asset referenced from two parts is exported into both archives and
    re-materialised twice, so the target's media count legitimately EXCEEDS the
    source's. The manifest's media table is what distinguishes that from a
    fault."""
    course = _mk_source(parts=("P0", "P1"))
    shared = MediaAsset.objects.filter(course=course).first()
    # Reference P0's asset from P1's unit too.
    other_unit = ContentNode.objects.get(course=course, title="U1")
    Element.objects.create(
        unit=other_unit,
        title="",
        content_object=ImageElement.objects.create(media=shared, alt="shared"),
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
    table = _read_manifest(bundle)["media_parts"]
    assert sorted(table[str(shared.pk)]) == [0, 1]  # in BOTH parts

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
    # Verify accepts the surplus because the table explains it.
    call_command(
        "migrate_course_content",
        "verify",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
    )


# --- _bundle_archives: filename parsing, in isolation --------------------
#
# These exercise the private helper directly rather than via a real course
# with >=100 top-level nodes, which would make the test suite slow for no
# extra coverage: the bug is purely in filename parsing.


def test_bundle_archives_orders_by_parsed_integer_not_lexicographically(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in ["10-x.zip", "100-x.zip", "2-x.zip", "20-x.zip", "0-x.zip"]:
        (bundle / name).write_bytes(b"")
    ordered = [p.name for p in Command()._bundle_archives(bundle)]
    assert ordered == ["0-x.zip", "2-x.zip", "10-x.zip", "20-x.zip", "100-x.zip"]


def test_bundle_archives_rejects_a_misnamed_archive(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "00-x.zip").write_bytes(b"")
    (bundle / "notes.zip").write_bytes(b"")
    with pytest.raises(CommandError, match="notes.zip"):
        Command()._bundle_archives(bundle)
