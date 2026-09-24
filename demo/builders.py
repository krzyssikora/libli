"""Per-type answer builders.

Contract: a builder takes the concrete question object and returns `Answers`,
or None when the ROW is unanswerable (so R3 skips its unit). Builders are PURE
functions of the row and consume NO RNG draw — the fixed draw order in the spec
lists none, so a builder that took one would invalidate it silently.

The wrong slot is a LIST of up to WRONG_VARIANTS deterministic answers, because
PR 5's per-question view renders each pupil's stored answer: one wrong answer
per question shows twenty pupils who all chose option C.
"""

from decimal import Decimal
from fractions import Fraction
from typing import NamedTuple

# ⚠️ ALPHABETICAL: courses.marking BEFORE courses.models. I001 checks ordering,
# not only splitting, and an earlier draft had marking stranded below models.
#
# ⚠️ courses/numeric.py DOES NOT EXIST. The parser lives in courses/marking.py,
# and it is the same one ShortNumericQuestionElement.mark uses
# (courses/models.py) — which is the only reason our "correct" answer marks
# 1.0. (canonical_numeric_text is deliberately NOT imported: it preserves
# fraction form rather than converting it — see _decimal_text below.)
from courses.marking import parse_numeric_value
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import _accepted_lines
from courses.quiz import answer_to_json
from demo.constants import WRONG_TEXTS
from demo.constants import WRONG_VARIANTS


class _NoWrongAnswer:
    """Distinct from None, which already means 'no partial' in slot 3."""

    def __repr__(self):
        return "NO_WRONG_ANSWER"


NO_WRONG_ANSWER = _NoWrongAnswer()


class Answers(NamedTuple):
    correct: object
    wrong: object  # list[answer] (non-empty) OR NO_WRONG_ANSWER — never []
    partial: object  # an answer, or None


def _choice(q):
    choices = sorted(q.choices.all(), key=lambda c: (c.order, c.pk))
    correct = {c.pk for c in choices if c.is_correct}
    if not correct:
        return None  # an empty pick would mark 1.0; the row is unanswerable
    wrong = [{c.pk} for c in choices if c.pk not in correct][:WRONG_VARIANTS]
    if not wrong:
        return Answers(correct, NO_WRONG_ANSWER, None)
    # All-or-nothing for both `multiple` values (fraction = 1.0 or 0.0), so
    # there is no partial band to aim at. Permanent, not "unverified".
    return Answers(correct, wrong, None)


def _shortnumeric(q):
    want = parse_numeric_value(q.value)
    if want is None:
        return None  # a hand-edited row: every answer marks 0.0
    tol = parse_numeric_value(q.tolerance)
    # Explicit `is None`, NOT `... or Fraction(0)`: Fraction(0) is falsy, so the
    # `or` form is right only by accident. ShortNumericQuestionElement.mark
    # (courses/models.py) carries this exact comment about this exact
    # expression — do not reintroduce the form it rejects.
    if tol is None:
        tol = Fraction(0)
    upper = want + tol  # mark() is abs(got - want) <= tol — ABSOLUTE tolerance
    # DECIMAL TEXT, never str(Fraction): a row with value="4.5" would otherwise
    # store every pupil's answer as "9/2" — it marks correct, but PR 5's
    # per-question view shows the rep an answer no pupil would type.
    # ⚠️ canonical_numeric_text DOES NOT DO THIS FOR YOU. It deliberately
    # PRESERVES structural form and does not reduce fractions
    # (courses/marking.py:178-181: "an author who writes 6/4 reopens the editor
    # and sees 6/4"), so canonical_numeric_text("9/2") is "9/2". Divide through
    # Decimal first; that is what actually produces decimal text.
    wrong = [_decimal_text(upper + n) for n in (1, 2, 3)][:WRONG_VARIANTS]
    return Answers(q.value, wrong, None)


_DECIMAL_PLACES = Decimal("0.0001")


def _decimal_text(value):
    """A Fraction as the decimal a pupil would type. `format(..., "f")` avoids
    scientific notation; normalize() trims the trailing zeros Decimal division
    leaves behind.

    ⚠️ QUANTIZED. `courses/marking.py` deliberately preserves fraction form
    (authors write `6/4`), so a real mat-pp row can hold `value="1/3"` — and the
    bare division would then produce "1.333333333333333333333333333" under
    Decimal's default 28-digit context. That is exactly the unreadable answer
    this function exists to prevent, reached by a different route, and nothing
    would go red: the variant still marks 0.0, so only the mat-pp eyeball would
    ever show it.

    Four places is safe against the margin: these variants are `upper + 1/2/3`,
    so rounding by <= 0.00005 cannot pull one back inside an absolute tolerance.
    """
    quotient = Decimal(value.numerator) / Decimal(value.denominator)
    return format(quotient.quantize(_DECIMAL_PLACES).normalize(), "f")


def _shorttext(q):
    lines = _accepted_lines(q.accepted)
    if not lines:
        return None
    wrong = [t for t in WRONG_TEXTS if q.mark(t).fraction == 0.0][:WRONG_VARIANTS]
    if not wrong:
        return Answers(lines[0], NO_WRONG_ANSWER, None)  # a row accepting all
    return Answers(lines[0], wrong, None)


def _fillblank(q):
    blanks = list(q.blanks.all())
    if not blanks:
        return None
    correct = []
    for blank in blanks:
        lines = _accepted_lines(blank.accepted)
        if not lines:
            return None  # an unfillable blank: no correct answer exists
        correct.append(lines[0])
    # WRONG scores ZERO: every blank spoiled. Spoiling only the first would earn
    # partial credit and collapse the wrong/partial distinction.
    wrong = [[text] * len(blanks) for text in WRONG_TEXTS][:WRONG_VARIANTS]
    partial = None
    if len(blanks) >= 2:
        partial = [WRONG_TEXTS[0]] + correct[1:]
    return Answers(correct, wrong, partial)


def _matchpair(q):
    expected = [p.right for p in q.pairs.all()]
    n = len(expected)
    if n == 0:
        return None
    wrong = []
    for shift in (1, 2, 3):
        if shift % n == 0:
            continue  # the identity
        rotated = expected[shift % n :] + expected[: shift % n]
        # A repeated right-hand token leaves positions matching under rotation,
        # which scores a strict PARTIAL. Keep only rotations that score zero.
        if q.mark(rotated).fraction == 0.0:
            wrong.append(rotated)
    partial = None
    if n >= 3:
        partial = [expected[1], expected[0]] + expected[2:]
    if not wrong:
        return Answers(expected, NO_WRONG_ANSWER, partial)
    return Answers(expected, wrong[:WRONG_VARIANTS], partial)


def _choicegrid(q):
    rows = list(q.rows.all())
    columns = sorted(q.columns.all(), key=lambda c: (c.order, c.pk))
    if not rows or len(columns) < 2:
        return (
            None
            if not rows
            else Answers([r.correct_column_id for r in rows], NO_WRONG_ANSWER, None)
        )
    correct = [r.correct_column_id for r in rows]
    wrong = []
    for nth in range(WRONG_VARIANTS):
        variant = []
        for row in rows:
            others = [c.pk for c in columns if c.pk != row.correct_column_id]
            variant.append(others[min(nth, len(others) - 1)])
        wrong.append(variant)
    partial = None
    if len(rows) >= 2:
        first_others = [c.pk for c in columns if c.pk != rows[0].correct_column_id]
        partial = [first_others[0]] + correct[1:]
    return Answers(correct, wrong, partial)


def _multigrid(q):
    rows = list(q.rows.all())
    columns = sorted(q.columns.all(), key=lambda c: (c.order, c.pk))
    if not rows or len(columns) < 2:
        return None
    correct = [sorted(c.pk for c in r.correct_columns.all()) for r in rows]
    if any(not sets for sets in correct):
        return None
    wrong = []
    for nth in range(WRONG_VARIANTS):
        variant = []
        for row_correct in correct:
            others = [c.pk for c in columns if c.pk not in row_correct]
            if not others:
                return Answers(correct, NO_WRONG_ANSWER, None)
            variant.append([others[min(nth, len(others) - 1)]])
        wrong.append(variant)
    partial = None
    # No `len(correct[0]) >= 1` conjunct: the `any(not sets ...)` guard above
    # already returned None for an empty row, so it is always true. What actually
    # decides between the two constructions below is whether row 0 has >= 2
    # correct columns (drop one) or exactly 1 (swap in a wrong one).
    if len(rows) >= 2:
        partial = [correct[0][1:]] + correct[1:]
        if not correct[0][1:]:
            others = [c.pk for c in columns if c.pk not in correct[0]]
            partial = [[others[0]]] + correct[1:] if others else None
    return Answers(correct, wrong, partial)


REGISTRY = {
    ChoiceQuestionElement: _choice,
    ShortNumericQuestionElement: _shortnumeric,
    ShortTextQuestionElement: _shorttext,
    FillBlankQuestionElement: _fillblank,
    MatchPairQuestionElement: _matchpair,
    ChoiceGridQuestionElement: _choicegrid,
    MultiGridQuestionElement: _multigrid,
}

# Keyed on the model CLASS, never a string, so a key cannot drift from a name.
# extendedresponse cannot be answered meaningfully; the two drag types look easy
# on paper but have never been exercised against a real row and appear in no
# published mat-pp quiz, so the safe default is to skip rather than guess.
UNANSWERABLE_QUESTION_TYPES = frozenset(
    {
        ExtendedResponseQuestionElement,
        DragFillBlankQuestionElement,
        DragToImageQuestionElement,
    }
)


def build(question):
    """Registry lookup + the shared post-processing every builder shares.

    De-duplication lives HERE, not in each builder: builders stay pure functions
    of the row and never touch serialisation, while a duplicate variant would
    consume a pick draw to store an identical answer.
    """
    builder = REGISTRY.get(type(question))
    if builder is None:
        return None
    answers = builder(question)
    if answers is None:
        return None
    if answers.wrong is NO_WRONG_ANSWER:
        # A sentinel forces the partial slot empty: the question is answered
        # correctly and consumes no draw, so a partial beside it would tempt an
        # implementer into the always-two-draws rule.
        return Answers(answers.correct, NO_WRONG_ANSWER, None)
    seen, unique = set(), []
    for variant in answers.wrong:
        key = repr(answer_to_json(variant))
        if key not in seen:
            seen.add(key)
            unique.append(variant)
    if not unique:
        return Answers(answers.correct, NO_WRONG_ANSWER, None)
    return Answers(answers.correct, unique[:WRONG_VARIANTS], answers.partial)
