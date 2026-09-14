"""prefetch_question_children loads every child row mark()/the templates read,
so touching them afterwards issues ZERO queries (spec §3.3, §5.1)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.views import prefetch_question_children
from tests.factories import DragBlankFactory
from tests.factories import DragZoneFactory
from tests.factories import MatchPairFactory

pytestmark = pytest.mark.django_db


def _questions():
    """One question of each child-bearing type (self-contained on purpose:
    the answer_summary fixtures arrive in a later task)."""
    choice = ChoiceQuestionElement.objects.create(stem="c")
    Choice.objects.create(question=choice, text="a", is_correct=True)
    fb = FillBlankQuestionElement.objects.create(stem="x")
    Blank.objects.create(question=fb, accepted="1")
    cg = ChoiceGridQuestionElement.objects.create(stem="g")
    col = GridColumn.objects.create(question=cg, label="y")
    GridRow.objects.create(question=cg, statement="r", correct_column=col)
    mg = MultiGridQuestionElement.objects.create(stem="m")
    mcol = MultiGridColumn.objects.create(question=mg, label="a")
    MultiGridRow.objects.create(question=mg, statement="r").correct_columns.set([mcol])
    return [
        choice,
        fb,
        DragBlankFactory().question,
        DragZoneFactory().question,
        MatchPairFactory().question,
        cg,
        mg,
    ]


def _touch(q):
    if isinstance(q, ChoiceQuestionElement):
        list(q.choices.all())
    elif isinstance(q, FillBlankQuestionElement):
        list(q.blanks.all())
    elif isinstance(q, DragFillBlankQuestionElement):
        list(q.dragblanks.all())
    elif isinstance(q, MatchPairQuestionElement):
        list(q.pairs.all())
    elif isinstance(q, DragToImageQuestionElement):
        list(q.zones.all())
        _ = q.media.file.name
    elif isinstance(q, ChoiceGridQuestionElement):
        list(q.columns.all())
        list(q.rows.all())
    elif isinstance(q, MultiGridQuestionElement):
        list(q.columns.all())
        for row in q.rows.all():
            list(row.correct_columns.all())


def test_children_and_media_need_no_query_after_prefetch():
    # Fresh instances: the builders' own objects may carry caches.
    fresh = [type(q).objects.get(pk=q.pk) for q in _questions()]
    prefetch_question_children(fresh)
    with CaptureQueriesContext(connection) as captured:
        for q in fresh:
            _touch(q)
    assert len(captured) == 0, [c["sql"] for c in captured]
