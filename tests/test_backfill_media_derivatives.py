import pytest
from django.core.files.storage import default_storage
from django.core.management import call_command

from courses.models import DerivativesState
from courses.models import MediaAsset
from tests.factories import CourseFactory
from tests.factories import make_image_asset


@pytest.mark.django_db
def test_populates_pending_rows(course_with_image_media_root, capsys):
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug)
    a.refresh_from_db()
    assert a.derivatives_state == DerivativesState.OK
    assert a.thumb.name and a.web.name


@pytest.mark.django_db
def test_dry_run_writes_nothing_and_reports_counts(
    course_with_image_media_root, capsys
):
    """--dry-run cannot report per-row outcomes: whether a row would produce
    derivatives, be skipped, or fail is only knowable by DECODING it. So the
    report is counts per derivatives_state, and the test asserts the counts --
    not merely the absence of writes, which would leave the output undefined."""
    course = CourseFactory()
    make_image_asset(course, "a.png", size=(2000, 1500))
    make_image_asset(course, "b.png", size=(2000, 1500))

    call_command("backfill_media_derivatives", course=course.slug, dry_run=True)

    out = capsys.readouterr().out
    assert "would process 2" in out
    assert MediaAsset.objects.filter(derivatives_state="").count() == 2


@pytest.mark.django_db
def test_second_run_is_a_no_op(course_with_image_media_root):
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug)
    a.refresh_from_db()
    first = a.thumb.name
    call_command("backfill_media_derivatives", course=course.slug)
    a.refresh_from_db()
    assert a.thumb.name == first


@pytest.mark.django_db
def test_skipped_rows_are_not_retried_but_failed_rows_are(
    course_with_image_media_root, monkeypatch
):
    course = CourseFactory()
    skipped = make_image_asset(course, "tiny.png", size=(300, 200))
    failed = make_image_asset(course, "bad.png", raw=b"nope")
    call_command("backfill_media_derivatives", course=course.slug)
    skipped.refresh_from_db()
    failed.refresh_from_db()
    assert skipped.derivatives_state == DerivativesState.SKIPPED
    assert failed.derivatives_state == DerivativesState.FAILED

    # A second pass must RECONSIDER `failed` and LEAVE `skipped` alone. Asserting
    # the state again would pass either way -- re-running over a 300x200 asset
    # produces SKIPPED regardless of whether the filter excluded it. Count the
    # generate_derivatives calls instead, which is the observable that
    # discriminates.
    seen = []
    import courses.management.commands.backfill_media_derivatives as cmd

    real = cmd.generate_derivatives
    monkeypatch.setattr(
        cmd, "generate_derivatives", lambda a: (seen.append(a.pk), real(a))[1]
    )
    call_command("backfill_media_derivatives", course=course.slug)
    assert skipped.pk not in seen, "skipped rows must not be retried"
    assert failed.pk in seen, "failed rows must be reconsidered"


@pytest.mark.django_db
def test_force_regenerates_and_leaves_no_orphans(course_with_image_media_root):
    """FieldFile.save hands back a collision-suffixed name, the field repoints,
    and the previous file would be orphaned -- with repeated --force runs
    multiplying orphans and lengthening names against max_length=200."""
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500), derivatives=True)
    old_thumb = a.thumb.name

    call_command("backfill_media_derivatives", course=course.slug, force=True)

    a.refresh_from_db()
    # Unconditional: storage collision-suffixes because the old file still
    # exists, so the name MUST change. Guarding the assertion behind that
    # condition would let a build that stopped deleting superseded derivatives
    # pass silently.
    assert a.thumb.name != old_thumb
    assert not default_storage.exists(old_thumb)


@pytest.mark.django_db
def test_force_does_not_delete_when_the_name_is_reused(course_with_image_media_root):
    """The sibling test above only exercises the DELETE half of the `n != new`
    guard in the command's `stale` filter: FileSystemStorage collision-suffixes
    the regenerated name because the old derivative is still on disk, so
    `new != old` unconditionally there and removing the guard entirely
    (deleting old_thumb/old_web unconditionally) would still leave that test
    green.

    This test exercises the guard's PROTECTIVE half. `generate_derivatives`
    derives the candidate name from `asset.file.name` (the original), which
    --force never touches -- so deleting the old THUMB file alone (without
    touching the original) frees its exact name, and the regenerated thumb is
    written back under that SAME name. If the `n != new` guard were removed,
    the command would delete "whatever old_thumb was", which is now also the
    freshly-written file's name -- stranding the row it just produced.

    MUTANT: drop the `n != new` condition in the command's `stale` list
    comprehension (delete unconditionally). Must go red.
    """
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500), derivatives=True)
    old_thumb, old_web = a.thumb.name, a.web.name
    # Free the exact names so regeneration reuses them (same original file,
    # same derived stem).
    default_storage.delete(old_thumb)
    default_storage.delete(old_web)

    call_command("backfill_media_derivatives", course=course.slug, force=True)

    a.refresh_from_db()
    assert a.thumb.name == old_thumb
    assert a.web.name == old_web
    assert default_storage.exists(a.thumb.name), (
        "the file just written must not be deleted as if it were the stale one"
    )
    assert default_storage.exists(a.web.name), (
        "the file just written must not be deleted as if it were the stale one"
    )


@pytest.mark.django_db
def test_start_at_skips_lower_pks(course_with_image_media_root):
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500))
    b = make_image_asset(course, "b.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug, start_at=b.pk)
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.derivatives_state == ""
    assert b.derivatives_state == DerivativesState.OK


@pytest.mark.django_db
def test_one_corrupt_asset_does_not_abort_the_run(course_with_image_media_root):
    course = CourseFactory()
    make_image_asset(course, "bad.png", raw=b"nope")
    good = make_image_asset(course, "good.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug)
    good.refresh_from_db()
    assert good.derivatives_state == DerivativesState.OK


@pytest.mark.django_db
def test_final_tally_line_matches_actual_per_state_outcomes(
    course_with_image_media_root, capsys
):
    """Deferred Minor from Task 7's review: neither the final `"done: X
    generated, Y skipped, Z failed"` line nor the --dry-run `by_state`
    breakdown (companion test below) was asserted by any test, so a mutant
    that swaps which counter increments for which state -- or interpolates
    the right counters into the wrong slots of the message -- would go
    uncaught. This is the exact line an operator reads to judge whether the
    real ~953-image mat-pp run went well.

    Counts are deliberately DISTINCT per state (2 ok, 1 skipped, 3 failed),
    not symmetric: a mutant that swaps two counters produces an IDENTICAL
    string when the counts it swaps happen to be equal, so equal counts
    would let that mutant hide.
    """
    course = CourseFactory()
    make_image_asset(course, "ok_a.png", size=(2000, 1500))
    make_image_asset(course, "ok_b.png", size=(2000, 1500))
    make_image_asset(course, "tiny.png", size=(300, 200))
    make_image_asset(course, "bad_a.png", raw=b"nope")
    make_image_asset(course, "bad_b.png", raw=b"nope")
    make_image_asset(course, "bad_c.png", raw=b"nope")

    call_command("backfill_media_derivatives", course=course.slug)

    out = capsys.readouterr().out
    assert "done: 2 generated, 1 skipped, 3 failed" in out, out


@pytest.mark.django_db
def test_dry_run_by_state_breakdown_matches_actual_states(
    course_with_image_media_root, capsys
):
    """Companion to the tally test above, for --dry-run's `by_state` report.

    --force is required to see this: without it, the command's own `qs =
    qs.filter(derivatives_state__in=_PENDING)` guard (applied before the
    dry-run branch) restricts the report to blank/failed rows only, so ok/
    skipped would read 0 regardless of what a mislabeling mutant did to
    them -- this is the realistic "what would --force touch" scenario an
    operator runs before actually passing --force.

    Real per-state rows are produced by an actual (non-dry) run first;
    PENDING rows are added afterwards so all four buckets are non-empty.
    Counts are distinct per state (3 pending, 2 ok, 1 skipped, 4 failed) for
    the same reason as the tally test above.
    """
    course = CourseFactory()
    make_image_asset(course, "ok_a.png", size=(2000, 1500))
    make_image_asset(course, "ok_b.png", size=(2000, 1500))
    make_image_asset(course, "tiny.png", size=(300, 200))
    make_image_asset(course, "bad_a.png", raw=b"nope")
    make_image_asset(course, "bad_b.png", raw=b"nope")
    make_image_asset(course, "bad_c.png", raw=b"nope")
    make_image_asset(course, "bad_d.png", raw=b"nope")
    call_command("backfill_media_derivatives", course=course.slug)
    capsys.readouterr()  # discard the first (non-dry) run's own output

    make_image_asset(course, "pending_a.png", size=(2000, 1500))
    make_image_asset(course, "pending_b.png", size=(2000, 1500))
    make_image_asset(course, "pending_c.png", size=(2000, 1500))

    call_command(
        "backfill_media_derivatives", course=course.slug, dry_run=True, force=True
    )

    out = capsys.readouterr().out
    assert "would process 10 asset(s)" in out, out
    assert "'(pending)': 3" in out, out
    assert "DerivativesState.OK: 2" in out, out
    assert "DerivativesState.SKIPPED: 1" in out, out
    assert "DerivativesState.FAILED: 4" in out, out


@pytest.mark.django_db
def test_course_scoping_leaves_other_courses_pending(course_with_image_media_root):
    """None of the sibling tests create a second course, so a dropped
    `--course` filter would still pass every other assertion in this file --
    each of them only ever has one course's rows in play. This is the test
    that actually exercises the scope.

    MUTANT: drop the `if opts["course"]:` filter block so the command always
    processes every image regardless of `--course`. Must go red.
    """
    target = CourseFactory()
    other = CourseFactory()
    a = make_image_asset(target, "a.png", size=(2000, 1500))
    b = make_image_asset(other, "b.png", size=(2000, 1500))

    call_command("backfill_media_derivatives", course=target.slug)

    a.refresh_from_db()
    b.refresh_from_db()
    assert a.derivatives_state == DerivativesState.OK
    assert b.derivatives_state == "", (
        "an asset in an unscoped course must be left alone"
    )
