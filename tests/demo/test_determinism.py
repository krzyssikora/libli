import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).with_name("golden_class.json")


def _projection(kit):
    """The generated values, EXCLUDING timestamps AND PRIMARY KEYS.

    Timestamps: every row keeps a wall-clock stamp (there is no back-dating), so
    a naive row comparison is red on correct code.

    ⚠️ PKS ARE THE BIGGER TRAP, and this repo has hit it four times. An earlier
    draft projected `r.element_id`, which broke BOTH tests below:
      * self-consistency built two separate courses and compared their element
        pks — never equal, whatever the generator does, so the test could not
        pass;
      * the golden file would have pinned absolute pks into a checked-in
        artefact. Postgres sequences are not reset by pytest-django's rollback,
        so those values depend on everything that ran earlier in the session —
        a different chunk under `-n`, a reordered run, or any new fixture
        anywhere in tests/ makes the file mismatch with NO change to the draw
        order. The one test that exists to pin the draw order would have been
        the flakiest in the suite.

    The stable key is POSITIONAL: (unit title, index of the question within its
    unit in the plan's own element order).
    """
    # One sorted block — I001 checks function-local imports too.
    from courses.models import QuestionResponse
    from courses.models import UnitProgress
    from courses.quiz import answer_to_json
    from demo.content import build_course_plan

    plan = build_course_plan(kit.course)
    # element pk -> ("Unit title", ordinal within the unit, {json -> slot label})
    key_of = {}
    for unit in plan.units:
        for i, q in enumerate(plan.questions.get(unit.pk, [])):
            # ⚠️ THE STORED PAYLOAD CARRIES PKS TOO. A choice answer is a set of
            # Choice pks; the grid builders store column pks. So dumping
            # latest_answer verbatim reintroduces exactly the trap the key above
            # removes. Instead, map each payload back to WHICH SLOT the generator
            # picked — "correct", "partial", or "wrong-N". That is precisely what
            # the draw order decides, and it is pk-free.
            slots = {repr(answer_to_json(q.answers.correct)): "correct"}
            if q.answers.partial is not None:
                slots[repr(answer_to_json(q.answers.partial))] = "partial"
            if not q.sentinel:
                for n, variant in enumerate(q.answers.wrong):
                    slots[repr(answer_to_json(variant))] = f"wrong-{n}"
            key_of[q.element_id] = (unit.title, i, slots)

    rows = []
    for pupil in kit.users.exclude(pk__in=[kit.teacher_id, kit.student_id]).order_by(
        "username"
    ):
        progress = sorted(
            UnitProgress.objects.filter(student=pupil, completed=True).values_list(
                "unit__title", flat=True
            )
        )
        answers = []
        for r in QuestionResponse.objects.filter(submission__student=pupil):
            title, ordinal, slots = key_of[r.element_id]
            slot = slots.get(repr(r.latest_answer))
            assert slot is not None, (
                f"stored answer matches no cached slot for {title}[{ordinal}] — "
                "the generator wrote something the content pass never validated"
            )
            answers.append([title, ordinal, str(r.fraction), slot])
        answers.sort()
        rows.append(
            {
                "username": pupil.username,
                "name": pupil.display_name,
                "progress": progress,
                "answers": answers,
            }
        )
    return rows


@pytest.mark.django_db
def test_the_same_seed_produces_the_same_class():
    """T7 — self-consistency. Its only honest mutant breaks determinism itself
    (reseed from secrets per run); a REORDERING mutant leaves it green, which is
    why those live on T7b."""
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    # ONE course, TWO kits. Building `small_course()` twice would compare two
    # disjoint sets of rows — and it also exercises the username disambiguator
    # for free, since the second kit takes the same label.
    course = small_course()
    first = _projection(provision_for_test(course, seed=2024))
    second = _projection(provision_for_test(course, seed=2024))

    # The usernames differ by design (sp-12-... vs sp-12-2-...), so compare
    # everything except that field. A `def`, not a lambda assignment — ruff's
    # E731 rejects the latter and tests/** does not ignore E.
    def without_username(rows):
        return [{k: v for k, v in row.items() if k != "username"} for row in rows]

    assert without_username(first) == without_username(second)
    assert first[0]["username"] != second[0]["username"], "the disambiguator ran"


@pytest.mark.django_db
def test_the_golden_class_is_unchanged():
    """T7b — the ONLY test that pins an absolute stream. Its mutants are each
    reordering the spec enumerates: swap the jitter draw ahead of the band
    shuffle; iterate questions in pk order; draw the partial only when the first
    draw said wrong; consume draws for an R3-skipped quiz.

    Landing a DELIBERATE order change means regenerating this file in the same
    commit — that is the point of it.

    The projection is pk-free (see _projection): the file records unit titles,
    question ordinals and slot labels, so it survives a different test order, a
    different xdist chunk and any new fixture elsewhere in tests/.
    """
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    actual = _projection(provision_for_test(small_course(), pupils=5, seed=777))

    # PRECONDITION FOR STEP 4's MUTANT, asserted rather than assumed. Moving the
    # partial draw only perturbs the stream if some pupil actually ANSWERS a
    # partial-capable question. If no recorded response belongs to the two-blank
    # question, the mutant is a no-op and the plan's headline draw-order defence
    # reports a false green. "Blanks quiz" lives in Part A precisely so this
    # holds for every band — see the fixture.
    # ⚠️ ANSWERED **CORRECTLY**, not merely answered. Step 4's mutant moves the
    # partial draw inside `if not correct_roll:`, so it only perturbs the stream
    # for a pupil whose first roll came out CORRECT (the draw then happens in the
    # unmutated build and not in the mutated one). A run where every pupil got
    # the two-blank question wrong draws identically either way.
    # ⚠️ (TITLE, ORDINAL), not the title alone. "Blanks quiz" holds TWO questions:
    # the two-blank fill-blank at ordinal 0 — the only partial-capable row in the
    # fixture — and a plain choice question at ordinal 1. Matching on the title
    # alone passes when a pupil answered the CHOICE question correctly, which
    # says nothing about the fill-blank, so the guard installed to prevent a
    # false green could itself be one.
    answered_correctly = {
        (row[0], row[1]) for r in actual for row in r["answers"] if row[3] == "correct"
    }
    assert ("Blanks quiz", 0) in answered_correctly, (
        "no pupil answered the two-blank fill-blank question CORRECTLY; Step 4's "
        "mutant would be a no-op and this test would not defend the draw order"
    )

    if not GOLDEN.exists():  # first run: record, then read the diff by eye
        GOLDEN.write_text(json.dumps(actual, indent=2, ensure_ascii=False), "utf-8")
        pytest.fail("golden file written — inspect it, then re-run")
    assert actual == json.loads(GOLDEN.read_text("utf-8"))
