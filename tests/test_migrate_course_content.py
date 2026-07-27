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
from courses.management.commands.migrate_course_content import LINK_STATE_NAME
from courses.management.commands.migrate_course_content import MANIFEST_NAME
from courses.management.commands.migrate_course_content import Command
from courses.management.commands.migrate_course_content import _build_mapping
from courses.management.commands.migrate_course_content import _fresh_state
from courses.management.commands.migrate_course_content import _invert_node_index
from courses.management.commands.migrate_course_content import _is_fail_closed
from courses.management.commands.migrate_course_content import _live_pks
from courses.management.commands.migrate_course_content import _merge_rewrite
from courses.management.commands.migrate_course_content import _read_state
from courses.management.commands.migrate_course_content import _write_state
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


def test_export_writes_a_node_index_covering_every_node(tmp_path):
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
    index = _read_manifest(bundle)["node_index"]
    # Every node in the COURSE, not just link targets and not just one part.
    all_pks = set(
        ContentNode.objects.filter(course=course).values_list("pk", flat=True)
    )
    assert {int(k) for k in index} == all_pks
    # Shape: {"<pk>": [order, "nN"]}, the pair in that order. JSON has no tuple
    # type, so it round-trips as a 2-element list.
    order, export_id = index[str(sorted(all_pks)[0])]
    assert isinstance(order, int)
    assert export_id.startswith("n")
    # Export ids restart at n1 in EVERY archive -- the part order is what
    # disambiguates them, and keying the two phases differently would make
    # every lookup miss silently.
    per_order = {}
    for o, eid in index.values():
        per_order.setdefault(o, set()).add(eid)
    assert all("n1" in ids for ids in per_order.values())


def test_export_node_index_round_trips_through_invert_node_index(tmp_path):
    """The format-level proof: what `_export` writes is exactly what
    `_invert_node_index` (Task 3's reader) expects to read back, per part
    order, for a genuinely multi-part course exported through the real,
    un-mocked `build_export` path."""
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
    node_index = _read_manifest(bundle)["node_index"]

    parts = list(
        ContentNode.objects.filter(course=course, parent__isnull=True).order_by(
            "order", "pk"
        )
    )
    assert len(parts) == 3  # a genuine multi-part fixture, not a single-part one

    def _subtree_pks(root):
        pks = {root.pk}
        frontier = [root.pk]
        while frontier:
            children = list(
                ContentNode.objects.filter(parent_id__in=frontier).values_list(
                    "pk", flat=True
                )
            )
            pks.update(children)
            frontier = children
        return pks

    seen_pks = []  # a list, not a set: duplicates across parts must be caught
    for part in parts:
        inverted = _invert_node_index(node_index, part.order)
        # Every export id in this part's own inversion resolves back to a
        # source pk that both exists and belongs to THIS part's own subtree
        # (never a sibling part's), and export ids restart at n1 per part, so
        # this could only line up if the (order, export_id) pair round-trips
        # exactly as written.
        assert inverted, f"part {part.order} inverted to nothing"
        subtree = _subtree_pks(part)
        for eid, pk in inverted.items():
            assert eid.startswith("n")
            assert isinstance(pk, int)
            assert pk in subtree, (
                f"part {part.order}'s inversion resolved {eid!r} to pk {pk}, "
                f"which is not in that part's own subtree"
            )
        seen_pks.extend(inverted.values())
    # The union across all per-order inversions recovers the whole course
    # exactly once per node -- no loss, no cross-part duplication.
    all_pks = set(
        ContentNode.objects.filter(course=course).values_list("pk", flat=True)
    )
    assert len(seen_pks) == len(set(seen_pks)) == len(all_pks)
    assert set(seen_pks) == all_pks


def test_export_node_index_survives_allow_problems(tmp_path, monkeypatch):
    """--allow-problems must not cost the operator the node index."""
    from courses.management.commands import migrate_course_content as mod

    _mk_source(parts=("Alpha",))
    bundle = tmp_path / "bundle"
    real = mod.build_export

    def fake(course, node=None, **kw):
        manifest, document, media, _p = real(course, node=node, **kw)
        return manifest, document, media, ["synthetic problem"]

    monkeypatch.setattr(mod, "build_export", fake)
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
        "--allow-problems",
    )
    assert _read_manifest(bundle)["node_index"]


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


@pytest.mark.parametrize(
    "flag, value",
    [("--force", None), ("--resolve-rewrite", "applied")],
)
def test_export_refuses_import_only_flags(tmp_path, flag, value):
    """Extended (not duplicated) for --resolve-rewrite per the flag-matrix
    trap: omitting the flag from _ACTION_FLAGS would let this slip through
    silently, so the same refusal test must cover it too."""
    _mk_source()
    args = [
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(tmp_path / "b"),
        flag,
    ]
    if value is not None:
        args.append(value)
    with pytest.raises(CommandError, match="not valid for"):
        call_command(*args)


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


def test_import_no_longer_flattens_cross_part_links_but_defers_them(tmp_path):
    # SUPERSEDES part 2's behaviour: this command moves content ONE TOP-LEVEL
    # PART AT A TIME, so build_export(course, node=part) only ever emits
    # link_nodes for targets INSIDE that part -- a cross-part link is
    # unmappable from any single part's own node_map. Part 2's command called
    # import_subtree with the on_missing="unwrap" default, so such a link was
    # flattened to plain text immediately. Part 3's graft loop now passes
    # on_missing="defer" (Task 5), which skips _rewrite_links entirely -- the
    # link is left pending until both parts are grafted, and Task 8's site 2
    # then runs the deferred pass automatically at the end of THIS `import`
    # invocation, resolving it to the target's new pk rather than flattening it.
    course = _mk_source(parts=("P0", "P1"))
    unit0 = ContentNode.objects.get(course=course, kind="unit", title="U0")
    unit1 = ContentNode.objects.get(course=course, kind="unit", title="U1")
    el = Element.objects.get(unit=unit0, title="T")
    text = el.content_object
    text.body = f'<p><a href="/courses/n/{unit1.pk}/">x</a></p>'
    text.save(update_fields=["body"])

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
        stdout=buf,
    )
    out = buf.getvalue()
    assert "00-src.zip" in out
    # Resolved by the deferred pass, not flattened: the rewrite summary's own
    # "0 link(s) flattened" line contains the substring "flattened", so the
    # actual claim is the count, not the word.
    state = _read_state_raw(bundle)
    assert state["rewrite"]["flattened"] == 0
    # Both parts committed, and the pass has now run over both.
    assert [e["order"] for e in state["parts"]] == [0, 1]
    assert all(e["rewritten"] is True for e in state["parts"])
    # End-to-end: the href now names the target's NEW pk, not the source pk.
    new_unit1 = ContentNode.objects.get(course=target, title="U1")
    body = TextElement.objects.get(
        elements__unit__course=target, elements__unit__title="U0"
    ).body
    assert f"/courses/n/{new_unit1.pk}/" in body


def test_import_reports_nothing_when_every_link_resolves_within_its_part(tmp_path):
    # The counterpart to the flattened-link warning: an in-part link is now
    # correctly remapped by Task 8's deferred pass (which fires automatically
    # at the end of this `import`), so it must not be COUNTED as flattened.
    # The rewrite summary line always contains the literal word "flattened"
    # (e.g. "0 link(s) flattened"), so the claim under test is the count, not
    # the word's presence in stdout.
    course = _mk_source(parts=("P0", "P1"))
    unit0 = ContentNode.objects.get(course=course, kind="unit", title="U0")
    el = Element.objects.get(unit=unit0, title="T")
    text = el.content_object
    text.body = f'<p><a href="/courses/n/{unit0.pk}/">x</a></p>'
    text.save(update_fields=["body"])

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
        stdout=buf,
    )
    state = _read_state_raw(bundle)
    assert state["rewrite"]["flattened"] == 0
    new_unit0 = ContentNode.objects.get(course=target, title="U0")
    body = TextElement.objects.get(
        elements__unit__course=target, elements__unit__title="U0"
    ).body
    assert f"/courses/n/{new_unit0.pk}/" in body


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


def test_verify_refuses_when_the_link_state_is_missing(tmp_path):
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
    (bundle / LINK_STATE_NAME).unlink()
    with pytest.raises(CommandError, match=LINK_STATE_NAME):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_refuses_a_state_file_that_is_not_applied(tmp_path):
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
    st = _read_state_raw(bundle)
    st["status"] = "collecting"
    _write_state(bundle, st)
    with pytest.raises(CommandError, match="deferred link rewrite never ran"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_refuses_an_in_progress_state_file(tmp_path):
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
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    _write_state(bundle, st)
    with pytest.raises(CommandError, match="in_progress") as exc:
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )
    # The probe reading, not a bare refusal (Task 11 supplies it).
    assert "in the pending scope" in str(exc.value)


def test_verify_refuses_the_wrong_target_rather_than_passing_trivially(tmp_path):
    """Without the identity check the scope is empty, so total_elements == 0
    and the reconciliation succeeds having checked nothing."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    Course.objects.create(title="Other", slug="other", uses_parts=True)
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
    # match= is mandatory: verifying "other" also trips the pre-existing node
    # tally ("node count mismatch"), so a bare raises() passes with the identity
    # check deleted and the falsification below could never go RED.
    with pytest.raises(CommandError, match="Refusing to mix targets"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "other",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_raises_on_a_dangling_internal_href(tmp_path):
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
    # MUTATE an existing body -- do NOT add an Element. The pinned gate order
    # puts the four tally checks before the reconciliation, so an extra join
    # raises "element count mismatch: expected 6, target 'dst' holds 7" and the
    # match= never fires. (Measured: sanitize_html leaves this markup
    # byte-identical, so .update() and .save() both work.)
    TextElement.objects.filter(elements__unit__course=target).update(
        body='<p><a href="/courses/n/999999/">x</a></p>'
    )
    with pytest.raises(CommandError, match="dangling"):
        call_command(
            "migrate_course_content",
            "verify",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
        )


def test_verify_passes_on_a_clean_migration(tmp_path):
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
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
    out = io.StringIO()
    call_command(
        "migrate_course_content",
        "verify",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        stdout=out,
    )
    assert "OK" in out.getvalue()


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


# --- link-state file: constants and pure helpers --------------------------


def _read_state_raw(bundle):
    return json.loads((bundle / LINK_STATE_NAME).read_text(encoding="utf-8"))


def test_invert_node_index_parses_string_pks_to_ints():
    """The `src` guard is a fatal equality test and node_index keys are decimal
    STRINGS. Without int() the comparison is False on every part of every run."""
    ni = {"1234": [0, "n1"], "1235": [0, "n2"], "9001": [1, "n1"]}
    assert _invert_node_index(ni, 0) == {"n1": 1234, "n2": 1235}
    assert _invert_node_index(ni, 1) == {"n1": 9001}
    assert _invert_node_index(ni, 7) == {}


def test_invert_node_index_survives_a_json_round_trip():
    """JSON has no tuple type: [order, export_id] comes back as a 2-element list."""
    ni = json.loads(json.dumps({"1234": (0, "n1")}))
    assert _invert_node_index(ni, 0) == {"n1": 1234}


def test_write_state_is_atomic_and_leaves_no_tmp_file(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    _write_state(bundle, {"version": 1, "parts": []})
    assert _read_state_raw(bundle) == {"version": 1, "parts": []}
    assert not (bundle / (LINK_STATE_NAME + ".tmp")).exists()


def test_read_state_validating_rejects_torn_json_and_a_wrong_version(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    with pytest.raises(CommandError, match="not valid JSON"):
        _read_state(bundle, validate=True)
    (bundle / LINK_STATE_NAME).write_text('{"version": 2}', encoding="utf-8")
    with pytest.raises(CommandError, match="version"):
        _read_state(bundle, validate=True)


def test_read_state_non_validating_swallows_a_torn_file(tmp_path):
    """The `start_at is None` branch discards the file wholesale, so validating
    it there could only manufacture a dead end with no documented remedy."""
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    assert _read_state(bundle, validate=False) is None


def test_read_state_returns_none_when_absent(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    assert _read_state(bundle, validate=True) is None


def test_fresh_state_carries_all_five_top_level_keys():
    target = _mk_target()
    st = _fresh_state(target)
    assert set(st) == {"version", "status", "target_slug", "target_pk", "parts"}
    assert st["status"] == "collecting"
    assert st["target_pk"] == target.pk
    assert st["parts"] == []


def test_live_pks_filters_to_rows_in_the_given_course():
    """course=target is not decoration: a bare pk__in would call a node in some
    OTHER course 'resolved', which is the mis-point this design guards against."""
    target = _mk_target()
    other = Course.objects.create(title="Other", slug="other")
    a = ContentNode.objects.create(course=target, kind="part", title="A")
    b = ContentNode.objects.create(course=other, kind="part", title="B")
    entries = [{"order": 0, "node_map": {"n1": a.pk, "n2": b.pk, "n3": 10**9}}]
    assert _live_pks(entries, target) == {a.pk}


# --- the deferred pass: mapping, fatal skips, fail-closed probe -----------


def test_is_fail_closed_separates_the_three_cases():
    """The naive `not changed` rule is catastrophically wrong: a body with NO
    links returns exactly the same signal as a fail-closed one, so it would
    record nearly every element and make verify's reconciliation vacuous."""
    plain = TextElement(body="<p>no links here</p>")
    good = TextElement(body='<p><a href="/courses/n/7/">x</a></p>')
    torn = TextElement(body='<p><a href="/courses/n/7/">x</p>')  # no </a>
    assert _is_fail_closed(plain) is False
    assert _is_fail_closed(good) is False
    assert _is_fail_closed(torn) is True


def test_is_fail_closed_recognizes_a_saved_fill_gate_fixture():
    """FillGateElement -- unlike TextElement -- has no save() override, so a
    torn anchor stored in `stem` is not closed by sanitize_html. Measured
    through a real save()+reload, not just an in-memory instance: this is one
    of the two end-to-end vehicles the FAIL-CLOSED FIXTURES preamble names for
    Tasks 7 and 12 (SwitchGateElement is the other; TextElement can never
    carry one at all, since its save() closes the anchor)."""
    from courses.models import FillGateElement

    fixture = FillGateElement.objects.create(
        # SINGLE torn anchor, UNMAPPABLE target, no </a> anywhere after it.
        stem='<p><a href="/courses/n/999999/">torn</p>',
        answers=[["x"]],
    )
    fixture.refresh_from_db()
    assert fixture.stem == '<p><a href="/courses/n/999999/">torn</p>'
    assert _is_fail_closed(fixture) is True


def test_build_mapping_covers_every_order_but_scopes_to_pending():
    """Two sets, never one. The rewrite's SCOPE is pending-only; the mapping's
    LIVENESS filter is every recorded order, because a pending part's links may
    point into an already-rewritten one."""
    target = _mk_target()
    nodes = [
        ContentNode.objects.create(course=target, kind="part", title=f"N{i}")
        for i in range(3)
    ]
    state = _fresh_state(target)
    state["parts"] = [
        {
            "order": 0,
            "node_map": {"n1": nodes[0].pk, "n2": nodes[1].pk},
            "src": {},
            "rewritten": True,
        },
        {"order": 1, "node_map": {"n1": nodes[2].pk}, "src": {}, "rewritten": False},
    ]
    node_index = {"1234": [0, "n1"], "1235": [0, "n2"], "9001": [1, "n1"]}
    mapping, scope_pks, _attr, scanned = _build_mapping(state, node_index, target)
    assert mapping == {1234: nodes[0].pk, 1235: nodes[1].pk, 9001: nodes[2].pk}
    assert scope_pks == {nodes[2].pk}  # pending only
    assert scanned == {1}


def test_build_mapping_is_fatal_when_a_recorded_pk_is_not_live():
    """Not a warning. Under on_missing='unwrap' an entry that contributes no
    mapping is not inert -- every href to it is flattened irreversibly."""
    target = _mk_target()
    state = _fresh_state(target)
    state["parts"] = [
        {"order": 0, "node_map": {"n1": 10**9}, "src": {}, "rewritten": False}
    ]
    # Match the VALUE, not the label: the message interpolates all three labels
    # unconditionally, so match="skipped_dead" is satisfied by any of the three.
    with pytest.raises(CommandError, match=r"skipped_dead=\[1000000000\]"):
        _build_mapping(state, {"1": [0, "n1"]}, target)


def test_build_mapping_is_fatal_on_an_unrecorded_order_or_export_id():
    target = _mk_target()
    node = ContentNode.objects.create(course=target, kind="part", title="N")
    state = _fresh_state(target)
    state["parts"] = [
        {"order": 0, "node_map": {"n1": node.pk}, "src": {}, "rewritten": False}
    ]
    with pytest.raises(CommandError, match=r"skipped_parts=\[5\]"):
        _build_mapping(state, {"1": [5, "n1"]}, target)
    with pytest.raises(CommandError, match=r"skipped_ids=\[\(0, 'nZZ'\)\]"):
        _build_mapping(state, {"1": [0, "nZZ"]}, target)


# --- _merge_rewrite: accumulation across passes ----------------------------


def test_merge_rewrite_first_pass_writes_full_rows_and_a_summed_total():
    per_order = {0: {"elements_touched": 3, "flattened": 1}}
    merged = _merge_rewrite(None, per_order, [], {0})
    assert merged == {
        "parts": [{"order": 0, "elements_touched": 3, "flattened": 1}],
        "elements_touched": 3,
        "flattened": 1,
        "fail_closed_elements": [],
    }


def test_merge_rewrite_carries_forward_unscanned_orders_with_null_counts():
    """A pass scanning only order 1 must not clobber order 0's earlier row, and
    must not claim a whole-migration total it never measured."""
    prior = {
        "parts": [{"order": 0, "elements_touched": 5, "flattened": 0}],
        "elements_touched": 5,
        "flattened": 0,
        "fail_closed_elements": [],
    }
    per_order = {1: {"elements_touched": 2, "flattened": 0}}
    merged = _merge_rewrite(prior, per_order, [], {0, 1})
    assert merged["parts"] == [
        {"order": 0, "elements_touched": 5, "flattened": 0},
        {"order": 1, "elements_touched": 2, "flattened": 0},
    ]
    # Order 0 was carried forward with a known count, order 1 is freshly
    # measured -- both known, so the total IS summed here. Nullness is only
    # forced when a carried-forward row's count was never known (see below).
    assert merged["elements_touched"] == 7
    assert merged["flattened"] == 0


def test_merge_rewrite_nulls_totals_when_a_carried_forward_row_is_unknown():
    """`resolved_by_operator` carries no per-order counts, so a later pass's
    carried-forward row for the resolved order is {elements_touched: None,
    flattened: None} -- and the top-level totals must not silently sum None."""
    prior = {"resolved_by_operator": True, "parts": []}
    per_order = {1: {"elements_touched": 2, "flattened": 0}}
    merged = _merge_rewrite(prior, per_order, [], {0, 1})
    rows = {r["order"]: r for r in merged["parts"]}
    assert rows[0] == {"order": 0, "elements_touched": None, "flattened": None}
    assert rows[1] == {"order": 1, "elements_touched": 2, "flattened": 0}
    assert merged["elements_touched"] is None
    assert merged["flattened"] is None


def _mk_bare_element(target):
    """One real Element join row on a throwaway unit -- _merge_rewrite queries
    Element.objects.filter(pk__in=...) to drop dead pks, so these tests need a
    genuine row, not a synthetic pk."""
    unit = ContentNode.objects.create(
        course=target, kind="unit", title="U", unit_type="lesson"
    )
    return Element.objects.create(
        unit=unit, title="", content_object=TextElement.objects.create(body="<p>x</p>")
    )


def test_merge_rewrite_unions_fail_closed_only_when_the_key_was_present():
    """An incomplete list is worse than an absent one: verify RECOMPUTES on
    absence but TRUSTS a present list, so a pass that has no fail_closed_elements
    to carry forward must not fabricate one from just its own findings."""
    target = _mk_target()
    el = _mk_bare_element(target)
    prior_with_key = {"parts": [], "fail_closed_elements": [el.pk]}
    merged = _merge_rewrite(prior_with_key, {}, [999999], {0})
    assert merged["fail_closed_elements"] == sorted({el.pk})  # 999999 not live

    prior_without_key = {"resolved_by_operator": True, "parts": []}
    merged2 = _merge_rewrite(prior_without_key, {}, [el.pk], {0})
    assert "fail_closed_elements" not in merged2  # NOT just [el.pk]


def test_merge_rewrite_drops_fail_closed_pks_whose_element_row_is_gone():
    target = _mk_target()
    el = _mk_bare_element(target)
    dead_pk = el.pk + 10**6
    merged = _merge_rewrite(None, {}, [el.pk, dead_pk], {0})
    assert merged["fail_closed_elements"] == [el.pk]


# --- Command._run_link_pass: the single rewrite pass, end to end ----------


def test_run_link_pass_rewrites_maps_and_flattens_and_records_fail_closed(
    tmp_path, monkeypatch
):
    """Direct call. The trigger sites now fire the pass automatically at the
    end of `import` (Task 8), so the setup `import` below suppresses it via
    monkeypatch to keep exact control over timing: a FillGateElement fixture
    is added target-side, AFTER the import but BEFORE the pass runs, and it
    must be in scope for the same pass that resolves the pre-import links --
    something an already-`applied` state would foreclose. Exercises, in one
    real `import`ed target: a cross-part link that resolves to a live pk
    (rewritten, counted), a link to nowhere (flattened, counted), a SECOND
    cross-part link in the OTHER direction so the counts genuinely split
    across two parts (not just two elements in one part -- see the per-part
    attribution note below), and the FillGateElement fail-closed fixture
    (recorded, but its OTHER field still gets rewritten)."""
    from courses.models import FillGateElement

    course = _mk_source(parts=("P0", "P1"))
    unit0 = ContentNode.objects.get(course=course, kind="unit", title="U0")
    unit1 = ContentNode.objects.get(course=course, kind="unit", title="U1")
    el0 = Element.objects.get(unit=unit0, title="T")
    text0 = el0.content_object
    text0.body = f'<p><a href="/courses/n/{unit1.pk}/">x</a></p>'
    text0.save(update_fields=["body"])
    Element.objects.create(
        unit=unit0,
        title="L",
        content_object=TextElement.objects.create(
            body='<p><a href="/courses/n/999999/">gone</a></p>'
        ),
    )
    # A link the OTHER way (part 1 -> part 0), so a rewritten element exists
    # under BOTH parts. `order_by_new_pk` is per-caller keyed by unit pk, not
    # by which side of the fixture happened to be touched first -- without
    # this second, cross-part-in-the-opposite-direction element, every
    # rewritten/flattened element in this test lives under part 0, so
    # misattributing every count to a single (recorded, pending) order would
    # leave rw["elements_touched"]/rw["flattened"] unchanged and ship green.
    Element.objects.create(
        unit=unit1,
        title="L2",
        content_object=TextElement.objects.create(
            body=f'<p><a href="/courses/n/{unit0.pk}/">y</a></p>'
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
    target = _mk_target()
    _user()
    monkeypatch.setattr(Command, "_run_link_pass", lambda *a, **k: None)
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
    monkeypatch.undo()  # this test drives the real pass by hand, below
    node_index = _read_manifest(bundle)["node_index"]
    state = _read_state_raw(bundle)
    assert state["status"] == "collecting"  # the pass has not fired yet

    # A fail-closed fixture, built target-side (its unmappable target is never
    # in the map, so it needs no import round trip either way).
    new_u0 = ContentNode.objects.get(course=target, title="U0")
    Element.objects.create(
        unit=new_u0,
        title="torn",
        content_object=FillGateElement.objects.create(
            stem='<p><a href="/courses/n/999999/">torn</p>',
            answers=[["x"]],
        ),
    )

    buf = io.StringIO()
    cmd = Command()
    cmd.stdout = buf
    cmd._run_link_pass(bundle, state, node_index, target)

    assert state["status"] == "applied"
    assert all(e["rewritten"] is True for e in state["parts"])

    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = list(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert any(f"/courses/n/{new_u1.pk}/" in b for b in bodies)  # rewritten (P0->P1)
    assert any(f"/courses/n/{new_u0.pk}/" in b for b in bodies)  # rewritten (P1->P0)
    assert not any("/courses/n/999999/" in b for b in bodies)  # flattened
    assert any("gone" in b for b in bodies)  # unwrapped to plain text

    fixture = FillGateElement.objects.get()
    assert fixture.stem == '<p><a href="/courses/n/999999/">torn</p>'  # untouched

    rw = state["rewrite"]
    # Exactly three rewritten elements (el0's cross-part link, the flattened
    # "gone" link, and L2's cross-part link back the other way) and one
    # flatten. Everything else in scope -- both ImageElements, unit1's
    # original plain-text element, and the fail-closed fixture -- contributes
    # neither.
    assert rw["flattened"] == 1
    assert rw["elements_touched"] == 3
    # PER-PART attribution, not just the totals: el0 and L live under part 0
    # (order 0), L2 lives under part 1 (order 1). A bug that attributes every
    # element to a single order -- e.g. `order_by_new_pk[join.unit_id]`
    # replaced by a constant -- leaves the totals above unchanged (3 touched,
    # 1 flattened, summed over whichever bucket) but reports the wrong split
    # here, which is exactly what `verify`'s per-part table would print.
    assert rw["parts"] == [
        {"order": 0, "elements_touched": 2, "flattened": 1},
        {"order": 1, "elements_touched": 1, "flattened": 0},
    ]
    fixture_el = Element.objects.get(content_type__model="fillgateelement")
    assert rw["fail_closed_elements"] == [fixture_el.pk]

    out = buf.getvalue()
    assert "deferred link rewrite applied" in out
    assert "flattened" in out

    # Persisted, not just mutated in memory.
    on_disk = _read_state_raw(bundle)
    assert on_disk["status"] == "applied"
    assert on_disk["rewrite"]["fail_closed_elements"] == [fixture_el.pk]


# --- import: graft under an outer atomic, record the link state -----------


def test_import_refuses_a_bundle_with_no_node_index(tmp_path):
    """A pre-feature bundle: fatal BEFORE anything is grafted. The tolerant
    fall-through would not mean 'no rewrites' -- with an empty map and
    on_missing='unwrap' it means every internal link in the course is destroyed
    inside a committed transaction, with the count arriving afterwards."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    manifest = _read_manifest(bundle)
    del manifest["node_index"]
    (bundle / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CommandError, match="predates internal-link support"):
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


def test_import_records_one_state_entry_per_grafted_part(tmp_path):
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
    state = _read_state_raw(bundle)
    assert state["version"] == 1
    assert state["target_pk"] == target.pk
    assert [e["order"] for e in state["parts"]] == [0, 1, 2]
    index = _read_manifest(bundle)["node_index"]
    for entry in state["parts"]:
        # node_map values are real pks in the target.
        assert all(
            ContentNode.objects.filter(pk=pk, course=target).exists()
            for pk in entry["node_map"].values()
        )
        # src is the manifest's inversion for that order -- int-valued.
        assert entry["src"] == _invert_node_index(index, entry["order"])
        # Site 2 fires on this full import, and the pass flips every flag.
        assert entry["rewritten"] is True


# --- import: the deferred link rewrite fires automatically ----------------


def _link_between(course, from_title, to_title):
    """Give the unit under `from_title` a text element linking to `to_title`'s
    unit. Returns the target node's pk."""
    src_unit = ContentNode.objects.get(course=course, title=f"U{from_title[-1]}")
    dst_unit = ContentNode.objects.get(course=course, title=f"U{to_title[-1]}")
    Element.objects.create(
        unit=src_unit,
        title="L",
        content_object=TextElement.objects.create(
            body=f'<p><a href="/courses/n/{dst_unit.pk}/">go</a></p>'
        ),
    )
    return dst_unit.pk


def test_a_full_import_rewrites_cross_part_and_intra_part_links(tmp_path):
    """The headline case. The intra-part link is NOT padding: it is what catches
    a rewrite-per-part-then-finish design, under which the final old-pk-keyed
    pass would flatten every within-part link in the course. A cross-part-only
    fixture passes that broken design.

    This is also site 2's falsification: add `not todo` to site 2 and this goes
    RED, because the loop never empties `todo`."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")  # cross-part
    _link_between(course, "P0", "P0")  # intra-part
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

    new_u0 = ContentNode.objects.get(course=target, title="U0")
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies  # cross-part -> NEW pk
    assert f"/courses/n/{new_u0.pk}/" in bodies  # intra-part -> NEW pk
    assert _read_state_raw(bundle)["status"] == "applied"


def test_the_pass_survives_an_interrupted_import_resumed_with_start_at(tmp_path):
    """What pins the state to a file rather than memory."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
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
    args = (
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    # A GENUINE interruption -- do NOT graft everything and wind the state back
    # by hand. `--start-at 0` grafts BOTH parts and site 2 applies the pass, so
    # P0's href already holds a TARGET pk; re-running the pass over it with a
    # SOURCE-keyed mapping unwrap-FLATTENS it (measured), which is the exact
    # double-apply the per-order `rewritten` flags exist to prevent.
    archives = sorted(bundle.glob("*.zip"))
    good = archives[1].read_bytes()
    archives[1].write_bytes(b"corrupt")
    with pytest.raises(CommandError):
        call_command("migrate_course_content", "import", *args)
    assert _read_state_raw(bundle)["status"] == "collecting"  # pass never fired
    archives[1].write_bytes(good)
    # A second process. The map for part 0 must have survived on disk.
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies


def test_the_skipped_pass_window_still_applies_on_a_start_at_resume(
    tmp_path, monkeypatch
):
    """A run that dies after the last part commits, resumed with
    --start-at part_count, must still rewrite. Site 1 is the only place that
    can fire here, because the loop body never runs."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
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
    args = (
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    # Genuine "parts committed, pass never ran": suppress the pass for the
    # setup invocation. Winding an APPLIED state back by hand would leave the
    # bodies holding TARGET pks, and the re-run's SOURCE-keyed mapping would
    # unwrap-flatten them -- a status-only assertion cannot tell that apart from
    # a correct rewrite.
    import courses.management.commands.migrate_course_content as mod

    monkeypatch.setattr(mod.Command, "_run_link_pass", lambda *a, **k: None)
    call_command("migrate_course_content", "import", *args, "--start-at", "0")
    monkeypatch.undo()
    assert _read_state_raw(bundle)["status"] == "collecting"

    call_command("migrate_course_content", "import", *args, "--start-at", "2")
    assert _read_state_raw(bundle)["status"] == "applied"
    # Site 1's ONLY firing-and-rewriting coverage -- assert the rewrite, not
    # just the marker.
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies


def test_a_completed_migration_re_invoked_does_not_re_run_the_pass(tmp_path):
    """The once-only guard, and the existing 'nothing to do' line must survive."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")  # so the body half is not vacuous
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
    args = (
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    call_command("migrate_course_content", "import", *args)
    before = _read_state_raw(bundle)["rewrite"]
    bodies_before = sorted(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    out = io.StringIO()
    # --start-at must equal the PART COUNT of this fixture (2), not 3: the
    # invariant is `baseline["top_nodes"] + start_at == existing`, so
    # --start-at 3 against a two-part source raises "expects the target to
    # hold exactly 3 top-level node(s) ... but it holds 2" and never reaches
    # any assertion below.
    call_command(
        "migrate_course_content", "import", *args, "--start-at", "2", stdout=out
    )
    assert _read_state_raw(bundle)["rewrite"] == before
    assert (
        sorted(
            TextElement.objects.filter(elements__unit__course=target).values_list(
                "body", flat=True
            )
        )
        == bodies_before
    )  # and no body was re-edited
    assert "already complete" in out.getvalue()


def test_a_link_with_no_target_in_any_part_is_flattened_and_counted(tmp_path):
    course = _mk_source(parts=("P0",))
    unit = ContentNode.objects.get(course=course, title="U0")
    Element.objects.create(
        unit=unit,
        title="L",
        content_object=TextElement.objects.create(
            body='<p><a href="/courses/n/999999/">gone</a></p>'
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
    target = _mk_target()
    _user()
    out = io.StringIO()
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        stdout=out,
    )
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert "/courses/n/999999/" not in bodies
    assert "gone" in bodies  # unwrapped to plain text
    assert _read_state_raw(bundle)["rewrite"]["flattened"] >= 1
    assert "flattened" in out.getvalue()


def test_a_regraft_replaces_the_entry_rather_than_duplicating(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    args = (
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    call_command("migrate_course_content", "import", *args, "--start-at", "0")
    first = _read_state_raw(bundle)
    ContentNode.objects.filter(
        course=Course.objects.get(slug="dst"), parent__isnull=True
    ).exclude(title="P0").delete()
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    second = _read_state_raw(bundle)
    assert [e["order"] for e in second["parts"]] == [0, 1, 2]  # not 0,1,2,1,2
    assert second["parts"][1]["node_map"] != first["parts"][1]["node_map"]


# --- import: the ordered branch and the five resume gates -----------------


def _seed_state(bundle, target, orders, *, status="collecting", rewritten=False):
    """Hand-write a state file AND the world it describes.

    Three things must line up or the test measures the wrong gate:

    1. `BASELINE_NAME` must exist. Without it the resume path re-captures the
       baseline NOW (`:419-427`), so `baseline["top_nodes"] == existing` and
       `:433` raises for EVERY `--start-at K > 0` -- before any gate under test.
       Seeded here as an all-zero baseline, matching an empty target.
    2. The target must hold exactly `len(orders)` top-level nodes, or `:433`
       raises anyway.
    3. `node_map` values must be REAL live pks in `target`. Synthetic pks make
       `_build_mapping`'s `skipped_dead` non-empty, so any seeded test that
       reaches the pass dies on the fatal-skip CommandError instead.

    Every seeded test must also pass `match=` to `pytest.raises`, or it can pass
    on `:433`'s message and prove nothing.
    """
    index = _read_manifest(bundle)["node_index"]
    (bundle / BASELINE_NAME).write_text(
        json.dumps(
            {
                "top_nodes": 0,
                "all_nodes": 0,
                "kind_counts": {},
                "elements": 0,
                "media": 0,
            }
        ),
        encoding="utf-8",
    )
    state = _fresh_state(target)
    state["status"] = status
    for o in orders:
        src = _invert_node_index(index, o)
        # One real node per export id, so _live_pks finds every recorded pk.
        top = ContentNode.objects.create(course=target, kind="part", title=f"S{o}")
        node_map = {}
        for i, eid in enumerate(src):
            node_map[eid] = (
                top.pk
                if i == 0
                else ContentNode.objects.create(
                    course=target, kind="chapter", title=f"S{o}c{i}", parent=top
                ).pk
            )
        state["parts"].append(
            {
                "order": o,
                "node_map": node_map,
                "src": src,
                "rewritten": rewritten,
            }
        )
    _write_state(bundle, state)
    return state


def test_resume_refuses_a_state_file_missing_target_pk(tmp_path):
    """The gate that stops a wrong-target resume writing itself a matching
    identity. Adopting the resolved target instead would defeat it."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    st = _seed_state(bundle, target, [0])
    del st["target_pk"]
    _write_state(bundle, st)
    with pytest.raises(CommandError, match="pre-feature import"):
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


def test_resume_refuses_a_state_file_for_a_different_target(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    other = Course.objects.create(title="Other", slug="other", uses_parts=True)
    _user()
    st = _seed_state(bundle, target, [0])
    st["target_pk"] = other.pk
    _write_state(bundle, st)
    # match= is mandatory: :433's own message contains "target", so a bare
    # pytest.raises(CommandError) would pass on the wrong gate.
    with pytest.raises(CommandError, match="Refusing to mix targets"):
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


def test_a_renamed_course_is_a_note_not_an_error(tmp_path, capsys):
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
    target.slug = "dst-renamed"
    target.save(update_fields=["slug"])
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst-renamed",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--start-at",
        "3",
    )
    assert "renamed" in capsys.readouterr().out


def test_resume_refuses_when_a_committed_order_is_missing_from_the_state(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    # Two orders' worth of nodes, but only order 0 recorded.
    _seed_state(bundle, target, [0])
    ContentNode.objects.create(course=target, kind="part", title="extra")
    with pytest.raises(CommandError, match="does not record them"):
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
            "2",
        )


def test_the_subset_guard_is_not_lexicographic(tmp_path):
    """JSON coerces int object keys to strings and max() over them is
    lexicographic: max(['0','9','10']) == '9'. With mat-pp's 21 parts a
    max()-based guard is wrong from part 10 onward. Hand-write the state and
    seed the nodes rather than running a real ten-part import."""
    bundle = _export_bundle(tmp_path, parts=tuple(f"P{i}" for i in range(11)))
    target = _mk_target()
    _user()
    # rewritten=True: this test asserts the GUARD accepts. After the loop grafts
    # part 10, recorded == on_disk == {0..10} and site 2 DOES fire -- seeding the
    # orders as already-rewritten keeps the pass's scope to order 10 alone,
    # rather than dragging ten seeded parts into it as a second subject.
    _seed_state(bundle, target, list(range(10)), rewritten=True)
    # Accepted: every archive order below 10 is recorded. A lexicographic-max
    # implementation computes max(["0".."9"]) == "9" and rejects this.
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
        "10",
    )
    assert ContentNode.objects.filter(course=target, title="P10").exists()


def test_resume_refuses_when_the_state_records_orders_no_longer_on_disk(tmp_path):
    """recorded > on_disk. Without this the trigger's set equality is merely
    False and `import` exits 0 having rewritten nothing."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0, 1, 2], rewritten=True)
    (sorted(bundle.glob("*.zip"))[-1]).unlink()
    manifest = _read_manifest(bundle)
    manifest["part_count"] = 2
    (bundle / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CommandError, match="no longer holds their archive"):
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
        )


def test_a_missing_state_file_with_start_at_above_zero_refuses(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    # A baseline plus one committed part, but NO state file -- the pre-feature
    # import shape. Without the baseline, :433 would raise first.
    (bundle / BASELINE_NAME).write_text(
        json.dumps(
            {
                "top_nodes": 0,
                "all_nodes": 0,
                "kind_counts": {},
                "elements": 0,
                "media": 0,
            }
        ),
        encoding="utf-8",
    )
    ContentNode.objects.create(course=target, kind="part", title="P0")
    with pytest.raises(CommandError, match="cannot be reconstructed"):
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


def test_a_torn_state_file_is_tolerated_on_the_discard_branch(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    call_command(  # no --start-at: discards it
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    assert _read_state_raw(bundle)["version"] == 1


def test_a_torn_state_file_refuses_on_the_resume_branch(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0])  # baseline + one committed part
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    with pytest.raises(CommandError, match="not valid JSON"):
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


def test_src_drift_refuses_after_a_re_export_from_an_edited_source(tmp_path):
    """A sibling REORDER inside an ALREADY-RECORDED part. Export ids are
    per-archive positional, so editing an ungrafted part leaves every recorded
    part's src byte-identical and the guard correctly does not fire -- which
    would make this test vacuous. Reordering top-level parts changes archive
    names, not intra-part export ids, so that would be vacuous too."""
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
        "--start-at",
        "0",
    )
    src = Course.objects.get(slug="src")
    p0 = ContentNode.objects.get(course=src, title="P0")
    ContentNode.objects.create(course=src, kind="chapter", title="extra", parent=p0)
    call_command(
        "migrate_course_content",
        "export",
        "--source-slug",
        "src",
        "--bundle-dir",
        str(bundle),
        "--clean",
    )
    with pytest.raises(CommandError, match="re-exported"):
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
        )


def test_dry_run_leaves_an_existing_state_file_byte_identical(tmp_path):
    """--force names step 3's write path. A bare `import --dry-run` over a
    bundle whose parts are committed hits :401 first (which fires regardless of
    dry_run, since :408's gate is downstream) and would pass on the wrong error."""
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
    before = (bundle / LINK_STATE_NAME).read_bytes()
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
        "--force",
    )
    assert (bundle / LINK_STATE_NAME).read_bytes() == before


# --- --resolve-rewrite: the operator's manual exit from an in_progress ----


def test_resolve_rewrite_not_applied_runs_the_pass_in_one_invocation(
    tmp_path, monkeypatch
):
    """ONE invocation, not two: no --start-at value both clears :433 and empties
    todo under non-contiguous orders, so a flip-then-resume form has no working
    argument."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
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
    # Suppress the pass for the first invocation so the bodies still hold SOURCE
    # pks, then forge the crash window on top of that genuine pre-pass state.
    import courses.management.commands.migrate_course_content as mod

    monkeypatch.setattr(mod.Command, "_run_link_pass", lambda *a, **k: None)
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
    monkeypatch.undo()
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"  # marker set, pass never committed
    _write_state(bundle, st)

    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--resolve-rewrite",
        "not-applied",
    )
    assert _read_state_raw(bundle)["status"] == "applied"
    # i5: the pass really rewrote, not merely flipped the marker.
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies


def test_resolve_rewrite_applied_sets_every_per_entry_flag(tmp_path):
    """status == 'applied' <=> no entry has rewritten == false. Flipping only
    status leaves every entry false, and the documented repair resume then makes
    pending == every order, re-applying an old-source-pk map over hrefs that
    already hold target pks."""
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
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    # The completed pass already set every flag True, so leaving them would make
    # the assertion below hold whether or not the `applied` arm sets them --
    # i.e. the falsification could not go RED. The spec's scenario is precisely
    # "flipping only status leaves every entry FALSE".
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)
    call_command(
        "migrate_course_content",
        "import",
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
        "--resolve-rewrite",
        "applied",
    )
    after = _read_state_raw(bundle)
    assert after["status"] == "applied"
    assert all(e["rewritten"] for e in after["parts"])
    assert after["rewrite"]["resolved_by_operator"] is True


def test_resolve_rewrite_applied_then_a_repair_resume_leaves_bodies_alone(tmp_path):
    """The consequence the per-entry flags exist to prevent: with only `status`
    flipped, a repair resume makes pending == every order and the pass re-applies
    an old-SOURCE-pk map over hrefs that already hold TARGET pks."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P0")
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
    args = (
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    call_command("migrate_course_content", "import", *args)
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)
    call_command(
        "migrate_course_content", "import", *args, "--resolve-rewrite", "applied"
    )
    p0_before = sorted(
        TextElement.objects.filter(
            elements__unit__parent__parent__title="P0",
            elements__unit__course=target,
        ).values_list("body", flat=True)
    )
    ContentNode.objects.filter(course=target, parent__isnull=True, title="P1").delete()
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    assert (
        sorted(
            TextElement.objects.filter(
                elements__unit__parent__parent__title="P0",
                elements__unit__course=target,
            ).values_list("body", flat=True)
        )
        == p0_before
    )


def test_resolve_rewrite_refuses_a_wrong_target_before_mutating(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    Course.objects.create(title="Other", slug="other", uses_parts=True)
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
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    _write_state(bundle, st)
    before = (bundle / LINK_STATE_NAME).read_bytes()
    with pytest.raises(CommandError, match="Refusing to mix targets"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "other",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
            "--resolve-rewrite",
            "applied",
        )
    assert (bundle / LINK_STATE_NAME).read_bytes() == before


def test_resolve_rewrite_applied_refuses_a_collecting_file(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0, 1, 2])
    with pytest.raises(CommandError, match="only meaningful on an in_progress"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
            "--resolve-rewrite",
            "applied",
        )


def test_resolve_rewrite_requires_as_user(tmp_path):
    """Pins the documented invocation against the real required-argument gate
    rather than the spec's prose: --as-user is checked unconditionally at :371,
    before the pinned handling point."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    with pytest.raises(CommandError, match="requires --as-user"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--resolve-rewrite",
            "not-applied",
        )


@pytest.mark.parametrize("extra", [("--start-at", "0"), ("--force",), ("--dry-run",)])
def test_resolve_rewrite_refuses_conflicting_flags(tmp_path, extra):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0, 1, 2], status="in_progress")
    with pytest.raises(CommandError, match="cannot be combined with"):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
            "--resolve-rewrite",
            "not-applied",
            *extra,
        )


def test_resolve_rewrite_not_applied_accepts_a_complete_collecting_file(
    tmp_path, monkeypatch
):
    """The second disjunct of the acceptance rule, and the ONLY test of it.

    It exists because site 1 is provably unreachable under non-contiguous orders
    -- there is no --start-at value that both clears :433 and empties todo -- so
    without this arm such a bundle can never reach the pass. Falsify by deleting
    the `collecting` disjunct: this goes RED while every other test stays green.
    """
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
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
    args = (
        "--target-slug",
        "dst",
        "--bundle-dir",
        str(bundle),
        "--as-user",
        "mig@example.com",
    )
    # Produce the genuine "all parts committed, pass never ran" shape by
    # suppressing the pass for the first invocation only. Winding an APPLIED
    # state back by hand would leave the bodies already rewritten to target pks,
    # and the re-run would flatten them (measured) -- the test would assert a
    # link the code under test destroys.
    import courses.management.commands.migrate_course_content as mod

    monkeypatch.setattr(mod.Command, "_run_link_pass", lambda *a, **k: None)
    call_command("migrate_course_content", "import", *args)
    monkeypatch.undo()
    assert _read_state_raw(bundle)["status"] == "collecting"

    call_command(
        "migrate_course_content", "import", *args, "--resolve-rewrite", "not-applied"
    )
    assert _read_state_raw(bundle)["status"] == "applied"
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies


@pytest.mark.parametrize("arm", ["applied", "not-applied"])
@pytest.mark.parametrize(
    "raw, match",
    [('{"version": 1, "par', "not valid JSON"), ('{"version": 2}', "version")],
)
def test_resolve_rewrite_validates_the_state_file(tmp_path, arm, raw, match):
    """Step 1's validate expression is `not (start_at is None and resolve is
    None)`, not a plain `start_at is None`. --start-at is fatal alongside
    --resolve-rewrite, so start_at is ALWAYS None here -- a naive exemption
    would skip validation on every resolve invocation, and step 2 returns before
    step 3 ever discards anything. Falsify by simplifying the expression: all
    four of these go RED."""
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
    (bundle / LINK_STATE_NAME).write_text(raw, encoding="utf-8")
    with pytest.raises(CommandError, match=match):
        call_command(
            "migrate_course_content",
            "import",
            "--target-slug",
            "dst",
            "--bundle-dir",
            str(bundle),
            "--as-user",
            "mig@example.com",
            "--resolve-rewrite",
            arm,
        )


def test_verify_does_not_keyerror_on_the_new_flag(tmp_path):
    """_FLAG_UNSET lookup happens for EVERY foreign flag on every action."""
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
    )
