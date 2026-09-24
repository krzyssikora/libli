import pytest

from courses.quiz import answer_to_json


def _fixtures():
    """One row of every registry type. Kept here (not in tests/factories.py) so
    the builder contract and its fixtures move together."""
    from decimal import Decimal

    from courses.models import Blank
    from courses.models import Choice
    from courses.models import ChoiceGridQuestionElement
    from courses.models import ChoiceQuestionElement
    from courses.models import FillBlankQuestionElement
    from courses.models import GridColumn
    from courses.models import GridRow
    from courses.models import MatchPair
    from courses.models import MatchPairQuestionElement
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow
    from courses.models import QuestionElement
    from courses.models import ShortNumericQuestionElement
    from courses.models import ShortTextQuestionElement

    made = []

    choice = ChoiceQuestionElement.objects.create(
        stem="Which are prime?",
        multiple=True,
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    for text, ok in (("2", True), ("3", True), ("4", False), ("6", False)):
        Choice.objects.create(question=choice, text=text, is_correct=ok)
    made.append(choice)

    made.append(
        ShortNumericQuestionElement.objects.create(
            stem="2+2?",
            value="4",
            tolerance="0",
            marking_mode=QuestionElement.MarkingMode.AUTO,
            max_marks=Decimal("1"),
        )
    )
    made.append(
        ShortTextQuestionElement.objects.create(
            stem="Capital of Poland?",
            accepted="Warszawa\nWarsaw",
            marking_mode=QuestionElement.MarkingMode.AUTO,
            max_marks=Decimal("1"),
        )
    )

    fb = FillBlankQuestionElement.objects.create(
        stem="2 + {{2}} = {{4}}",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    Blank.objects.create(question=fb, accepted="2")
    Blank.objects.create(question=fb, accepted="4")
    made.append(fb)

    mp = MatchPairQuestionElement.objects.create(
        stem="Match",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    for left, right in (("a", "1"), ("b", "2"), ("c", "3")):
        MatchPair.objects.create(question=mp, left=left, right=right)
    made.append(mp)

    cg = ChoiceGridQuestionElement.objects.create(
        stem="Grid",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    cols = [GridColumn.objects.create(question=cg, label=lbl) for lbl in ("yes", "no")]
    for text in ("r1", "r2"):
        # ⚠️ ROWS USE `statement`, COLUMNS USE `label`. GridRow and MultiGridRow
        # (both courses/models.py) declare `statement`; only the *Column models
        # have `label`. Passing label= is a TypeError that kills the whole module
        # before a single assertion runs.
        GridRow.objects.create(question=cg, statement=text, correct_column=cols[0])
    made.append(cg)

    mg = MultiGridQuestionElement.objects.create(
        stem="MultiGrid",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    # `label`, not `l`: ruff selects E, and E741 rejects `l` as a binding name.
    # tests/** only ignores S105/S106/S107.
    mcols = [
        MultiGridColumn.objects.create(question=mg, label=label)
        for label in ("a", "b", "c")
    ]
    for text in ("r1", "r2"):
        row = MultiGridRow.objects.create(question=mg, statement=text)  # not label
        row.correct_columns.set(mcols[:2])
    made.append(mg)

    return made


@pytest.mark.django_db
def test_every_registry_type_has_a_fixture_and_an_honest_builder():
    """T1b — the highest-value test here. Without it the derived-score rule is
    tautological: it defines `fraction` as mark()'s own output, so a builder
    returning a WRONG 'correct' answer is invisible."""
    from demo import builders
    from demo.constants import WRONG_VARIANTS

    by_type = {type(q): q for q in _fixtures()}
    assert set(by_type) == set(builders.REGISTRY), "every registry type needs a fixture"

    for model, question in by_type.items():
        answers = builders.build(question)
        assert answers is not None, model
        assert question.mark(answers.correct).fraction == 1.0, model

        assert answers.wrong is not builders.NO_WRONG_ANSWER, model
        # From demo.constants, NOT through demo.builders. The builders module only
        # re-exports it incidentally via its header import; moving that import into
        # a function body (which this plan does elsewhere) would break this line
        # with an AttributeError that reads as a test bug.
        assert 1 <= len(answers.wrong) <= WRONG_VARIANTS, model
        serialised = [answer_to_json(v) for v in answers.wrong]
        assert len(serialised) == len({repr(s) for s in serialised}), model
        for variant in answers.wrong:
            # == 0.0, not < 1.0: the wrong slot must SCORE ZERO, or the
            # wrong-vs-partly-right split means nothing.
            assert question.mark(variant).fraction == 0.0, (model, variant)

        if answers.partial is not None:
            f = question.mark(answers.partial).fraction
            assert 0 < f < 1, (model, f)


def test_the_wrong_text_pool_covers_the_variant_count():  # no django_db: constants
    """WRONG_TEXTS is the pool _shorttext and _fillblank draw from, and
    WRONG_VARIANTS is how many variants every builder may return. Today both are
    3 and the relationship is only a COMMENT — raise WRONG_VARIANTS to 4 and
    every text-shaped question silently caps at three with no warning. Same shape
    as the MAX_PUPILS / name-pool coupling; derived, never a `== 3` pin."""
    from demo.constants import WRONG_TEXTS
    from demo.constants import WRONG_VARIANTS

    assert len(WRONG_TEXTS) >= WRONG_VARIANTS
    assert len(set(WRONG_TEXTS)) == len(WRONG_TEXTS)


def test_every_question_type_is_classified():
    """T6 — derived, never a len(...) == N pin. A new question type fails until
    someone puts it in the registry or in UNANSWERABLE_QUESTION_TYPES.

    No `django_db`: this walks `__subclasses__` and touches no row. Same rule as
    Task 6 Step 4a's warning-kind test — don't pay for a database you never use."""
    from courses.models import QuestionElement
    from demo import builders

    def concrete_subclasses(cls):
        for sub in cls.__subclasses__():
            if not sub._meta.abstract:
                yield sub
            yield from concrete_subclasses(sub)

    every = set(concrete_subclasses(QuestionElement))
    classified = set(builders.REGISTRY) | set(builders.UNANSWERABLE_QUESTION_TYPES)
    assert every - classified == set(), "unclassified question types"
    assert classified - every == set(), "classified a type that no longer exists"


@pytest.mark.django_db
def test_numeric_wrong_answers_are_decimal_text_not_fractions():
    """A pupil types "5.5", never "11/2". parse_numeric_value returns a Fraction
    and canonical_numeric_text deliberately PRESERVES fraction form, so the naive
    str()/canonicalise route stores "11/2" for every non-integer row — which is
    most of mat-pp."""
    from decimal import Decimal

    from courses.models import QuestionElement
    from courses.models import ShortNumericQuestionElement
    from demo import builders

    q = ShortNumericQuestionElement.objects.create(
        stem="half?",
        value="4.5",
        tolerance="0",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    answers = builders.build(q)
    assert answers.correct == "4.5"
    for variant in answers.wrong:
        assert "/" not in variant, variant
        assert q.mark(variant).fraction == 0.0


@pytest.mark.django_db
def test_a_choice_with_no_correct_option_is_unanswerable():
    """mark() is `set(answer) == correct_set` with no n>0 guard, so an empty pick
    would mark 1.0 — the row is excluded here rather than 'failing validation'."""
    from decimal import Decimal

    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import QuestionElement
    from demo import builders

    q = ChoiceQuestionElement.objects.create(
        stem="broken",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    Choice.objects.create(question=q, text="a", is_correct=False)
    assert builders.build(q) is None
