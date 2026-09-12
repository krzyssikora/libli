import pytest


@pytest.mark.django_db
def test_a_candidate_exists_beyond_every_reachable_depth():
    """THE FIXTURE GUARD, and the reason "Late quiz" exists.

    `_usable_target` rejects any unit at `position <= depth`, and a pupil shallow
    enough to miss a quiz is handed it anyway by generate()'s reach-forward —
    which puts it in `submitted_unit_ids` and trips the second rejection. So if
    every candidate sits at or below the shallowest depth, `chosen` is ALWAYS
    empty, no IN_PROGRESS row is ever written, and T25 fails on correct code.
    That is exactly what the original fixture did. Pin it here, cheaply, rather
    than debugging it through a provisioning run.
    """
    from demo.constants import BANDS
    from demo.constants import JITTER
    from demo.constants import MIN_PUPILS
    from demo.constants import STRUGGLING
    from demo.content import build_course_plan
    from demo.generator import frontier_index
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)
    frontier = frontier_index(plan, None, course)
    # The shallowest depth any band can produce: the smallest multiplier at the
    # most negative jitter. Derived, never a literal.
    min_depth = round(frontier * BANDS[STRUGGLING]["depth"] * (1 - JITTER))

    positions = {u.pk: i for i, u in enumerate(plan.units)}
    reachable = [u for u in plan.in_progress_candidates if positions[u.pk] > min_depth]
    assert reachable, (
        "no in-progress candidate sits past the shallowest possible depth "
        f"({min_depth}); the review queue can never fill"
    )
    assert MIN_PUPILS >= 2


@pytest.mark.django_db
def test_a_one_question_quiz_is_never_an_in_progress_target():
    """randint(1, n-1) raises at n == 1, and a prefix must be strictly proper."""
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)
    one_question = [
        u
        for u in plan.units
        if u.unit_type == "quiz" and len(plan.questions.get(u.pk, [])) == 1
    ]
    assert one_question, "the fixture needs a single-question quiz"
    assert not {u.pk for u in one_question} & {
        u.pk for u in plan.in_progress_candidates
    }


@pytest.mark.django_db
def test_no_qualifying_pupil_is_reported_not_silently_swallowed():
    """Both shortfall branches tell the operator that §1's fourth requirement — a
    non-empty review queue — silently failed. Nothing else drives them: Task 15's
    DISPLAY test only proves the map is self-consistent, so without this they are
    dead code every test leaves green, and the
    f"{len(chosen)} of {IN_PROGRESS_PUPILS}" reason could be malformed forever.

    Driven directly rather than through a course shaped to fail: every pupil is
    handed a depth past the end of the outline, so _usable_target's
    `position <= depth` rejects every candidate."""
    import random

    from demo.content import build_course_plan
    from demo.generator import leave_in_progress
    from demo.warnings import KINDS
    from tests.demo.fixtures import small_course

    plan = build_course_plan(small_course())
    deep = len(plan.units) + 1
    warnings = leave_in_progress(
        random.Random(1),
        plan,
        pupils=[None, None],
        bands=["average"] * 2,
        depths=[deep, deep],
    )

    assert [w.kind for w in warnings] == ["no_qualifying_pupil"]
    assert warnings[0].kind in KINDS  # the closed-set guard actually fired
    assert warnings[0].reason
