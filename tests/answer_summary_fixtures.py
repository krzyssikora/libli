"""One question of every concrete type, for answer_summary and query-budget tests.

Shapes mirror tests/demo/test_builders.py::_fixtures. GridRow/MultiGridRow use
`statement`; only the *Column models have `label`."""

from decimal import Decimal
from types import SimpleNamespace

from django.http import QueryDict

from courses.fillblank import SENTINEL
from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import ExtendedResponseQuestionElement
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
from courses.quiz import answer_from_json
from courses.quiz import selected_ids
from tests.factories import MediaAssetFactory

AUTO = QuestionElement.MarkingMode.AUTO
# Built from the constant: the raw U+FFFF sentinel is never pasted into a file
# (file tools corrupt it; see tests/conftest.py's switchgate fixture).
TOKEN0 = f"{SENTINEL}0{SENTINEL}"
TOKEN1 = f"{SENTINEL}1{SENTINEL}"


def build_all_types(mode=AUTO):
    common = {"marking_mode": mode, "max_marks": Decimal("1")}
    made = {}

    choice = ChoiceQuestionElement.objects.create(
        stem="Primes?", multiple=True, **common
    )
    for order, (text, ok) in enumerate((("2", True), ("3", True), ("4", False))):
        Choice.objects.create(question=choice, text=text, is_correct=ok, order=order)
    made["choice"] = choice

    made["shorttext"] = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Warszawa\nWarsaw", **common
    )
    made["shortnumeric"] = ShortNumericQuestionElement.objects.create(
        stem="Half?", value="1/2", tolerance="", **common
    )
    made["extendedresponse"] = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.",
        required_keywords="alpha\nbeta",
        forbidden_keywords="gamma",
        **common,
    )

    fb = FillBlankQuestionElement.objects.create(
        stem=f"2 + {TOKEN0} = {TOKEN1}", **common
    )
    Blank.objects.create(question=fb, accepted="2", order=0)
    Blank.objects.create(question=fb, accepted="4", order=1)
    made["fillblank"] = fb

    df = DragFillBlankQuestionElement.objects.create(
        stem=f"{TOKEN0} and {TOKEN1}", distractors="x", **common
    )
    DragBlank.objects.create(question=df, correct_token="cat", order=0)
    DragBlank.objects.create(question=df, correct_token="dog", order=1)
    made["dragfill"] = df

    di = DragToImageQuestionElement.objects.create(
        stem="", media=MediaAssetFactory(), alt="A heart", distractors="", **common
    )
    DragZone.objects.create(
        question=di, correct_label="Heart", x=0.1, y=0.1, w=0.2, h=0.2, order=0
    )
    DragZone.objects.create(
        question=di, correct_label="Liver", x=0.5, y=0.5, w=0.2, h=0.2, order=1
    )
    made["dragimage"] = di

    mp = MatchPairQuestionElement.objects.create(stem="Match", distractors="", **common)
    for order, (left, right) in enumerate((("a", "1"), ("b", "2"), ("c", "3"))):
        MatchPair.objects.create(question=mp, left=left, right=right, order=order)
    made["matchpair"] = mp

    cg = ChoiceGridQuestionElement.objects.create(stem="Grid", **common)
    yes = GridColumn.objects.create(question=cg, label="yes", order=0)
    no = GridColumn.objects.create(question=cg, label="no", order=1)
    GridRow.objects.create(question=cg, statement="r1", correct_column=yes, order=0)
    GridRow.objects.create(question=cg, statement="r2", correct_column=no, order=1)
    made["choicegrid"] = cg

    mg = MultiGridQuestionElement.objects.create(stem="MultiGrid", **common)
    cols = [
        MultiGridColumn.objects.create(question=mg, label=label, order=i)
        for i, label in enumerate(("a", "b", "c"))
    ]
    r1 = MultiGridRow.objects.create(question=mg, statement="r1", order=0)
    r1.correct_columns.set(cols[:2])
    r2 = MultiGridRow.objects.create(question=mg, statement="r2", order=1)
    r2.correct_columns.set(cols[2:])
    made["multigrid"] = mg

    return made


def summarise_stored(question, stored, *, unanswered=False):
    """summarise() fed exactly as views._results_row + _quiz_answer_rows feed it:
    for a choice question that includes the choice_marks dict the view computes
    (spec §5.1). Every question type's builder tests go through here."""
    from courses.answer_summary import summarise

    response = None if unanswered else SimpleNamespace(latest_answer=stored)
    if question.marking_mode != AUTO:
        mark_result = None
    elif response is None or stored is None:
        mark_result = question.mark(question.build_answer(QueryDict()))
    else:
        mark_result = question.mark(answer_from_json(question, stored))
    if not isinstance(question, ChoiceQuestionElement):
        return summarise(question, response, mark_result)
    marks = None
    if mark_result is not None:
        picked = (
            selected_ids(answer_from_json(question, stored))
            if response is not None and stored is not None
            else set()
        )
        marks = question.choice_marks(
            list(question.choices.all()), picked, mark_result, "quiz", True
        )
    return summarise(question, response, mark_result, option_marks=marks or {})
