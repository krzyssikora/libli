"""The five PR 2 reveal types (spec 2026-09-25 §8 PR 2): one builder per type and
the parsers that read each part's paint out of rendered HTML.

Every builder returns a Kit whose `half` POST gets the FIRST part right and the
SECOND part wrong, so a painted render reads ["correct", "incorrect"]."""

import re
from dataclasses import dataclass

from django.http import QueryDict

from courses.fillblank import parse
from courses.models import ChoiceGridQuestionElement
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from tests.factories import MediaAssetFactory

DND_KINDS = ("dragfill", "matchpair", "dragimage")
GRID_KINDS = ("choicegrid", "multigrid")
KINDS = DND_KINDS + GRID_KINDS


@dataclass
class Kit:
    question: object
    half: dict
    right: dict
    empty: dict
    key: list
    leak: str
    key_text: str


def build(kind, **kw):
    kw.setdefault("max_attempts", 3)
    return _BUILDERS[kind](**kw)


def post(data):
    """A QueryDict for build_answer(); a list value becomes a repeated key."""
    qd = QueryDict(mutable=True)
    for k, v in data.items():
        qd.setlist(k, [str(x) for x in (v if isinstance(v, list) else [v])])
    return qd


def _dnd_kit(q):
    # Part 2's key token is "betakey"; the student's wrong pick is "gammadis".
    return Kit(
        question=q,
        half={"slot": ["alphakey", "gammadis"]},
        right={"slot": ["alphakey", "betakey"]},
        empty={"slot": ["", ""]},
        key=["alphakey", "betakey"],
        leak='value="betakey" selected',
        key_text="betakey",
    )


def _dragfill(**kw):
    q = DragFillBlankQuestionElement.objects.create(
        stem=parse("One {{alphakey}} two {{betakey}}.")[0],
        distractors="gammadis",
        **kw,
    )
    DragBlank.objects.create(question=q, order=0, correct_token="alphakey")
    DragBlank.objects.create(question=q, order=1, correct_token="betakey")
    return _dnd_kit(q)


def _matchpair(**kw):
    q = MatchPairQuestionElement.objects.create(
        stem="Match them.", distractors="gammadis", **kw
    )
    MatchPair.objects.create(question=q, order=0, left="Leftone", right="alphakey")
    MatchPair.objects.create(question=q, order=1, left="Lefttwo", right="betakey")
    return _dnd_kit(q)


def _dragimage(**kw):
    q = DragToImageQuestionElement.objects.create(
        stem="Label it.", media=MediaAssetFactory(), distractors="gammadis", **kw
    )
    DragZone.objects.create(
        question=q, order=0, correct_label="alphakey", x=0.1, y=0.1, w=0.2, h=0.2
    )
    DragZone.objects.create(
        question=q, order=1, correct_label="betakey", x=0.5, y=0.5, w=0.25, h=0.2
    )
    return _dnd_kit(q)


def _choicegrid(**kw):
    q = ChoiceGridQuestionElement.objects.create(stem="Grid?", **kw)
    yes = GridColumn.objects.create(question=q, order=0, label="Yescol")
    no = GridColumn.objects.create(question=q, order=1, label="Nocol")
    r1 = GridRow.objects.create(
        question=q, order=0, statement="Sone", correct_column=yes
    )
    r2 = GridRow.objects.create(
        question=q, order=1, statement="Stwo", correct_column=no
    )
    k1, k2 = f"row_{r1.pk}", f"row_{r2.pk}"
    return Kit(
        question=q,
        half={k1: yes.pk, k2: yes.pk},
        right={k1: yes.pk, k2: no.pk},
        empty={},
        key=[yes.pk, no.pk],
        leak=f'value="{no.pk}" checked',
        key_text="Nocol",
    )


def _multigrid(**kw):
    q = MultiGridQuestionElement.objects.create(stem="Tick?", **kw)
    a = MultiGridColumn.objects.create(question=q, order=0, label="Acol")
    b = MultiGridColumn.objects.create(question=q, order=1, label="Bcol")
    r1 = MultiGridRow.objects.create(question=q, order=0, statement="Sone")
    r1.correct_columns.set([a])
    r2 = MultiGridRow.objects.create(question=q, order=1, statement="Stwo")
    r2.correct_columns.set([a, b])
    k1, k2 = f"row_{r1.pk}", f"row_{r2.pk}"
    return Kit(
        question=q,
        half={k1: [a.pk], k2: [a.pk]},
        right={k1: [a.pk], k2: [a.pk, b.pk]},
        empty={},
        key=[[a.pk], sorted([a.pk, b.pk])],
        leak=f'value="{b.pk}" checked',
        key_text="Bcol",
    )


_BUILDERS = {
    "dragfill": _dragfill,
    "matchpair": _matchpair,
    "dragimage": _dragimage,
    "choicegrid": _choicegrid,
    "multigrid": _multigrid,
}

# A drag part = its <select> plus the .sr-only verdict right after it; a grid part =
# one <tbody> row (its statement cell holds the .sr-only verdict).
_SELECT_PART = re.compile(
    r'<select\b.*?</select>(?:<span class="sr-only">[^<]*</span>)?', re.S
)
_TBODY = re.compile(r"<tbody>(.*?)</tbody>", re.S)
_ROW = re.compile(r"<tr\b.*?</tr>", re.S)


def parts(kind, html):
    """Every part's full markup in `html`, in draw order."""
    if kind in DND_KINDS:
        return _SELECT_PART.findall(html)
    found = []
    for body in _TBODY.findall(html):
        found += _ROW.findall(body)
    return found


def paint(kind, html):
    """Per part: "correct" / "incorrect" / None, read from the part's OWN opening
    tag (the <select> / the <tr>), never from a descendant."""
    out = []
    for part in parts(kind, html):
        head = part.split(">", 1)[0]
        if "is-correct" in head:
            out.append("correct")
        elif "is-incorrect" in head:
            out.append("incorrect")
        else:
            out.append(None)
    return out


def yours(html):
    """The student's copy: from data-answer-yours up to whatever follows it."""
    part = html.split("data-answer-yours", 1)[1]
    for stop in (
        "data-answer-key",
        "data-answer-switch",
        'type="submit"',
        "data-question-feedback",
    ):
        part = part.split(stop, 1)[0]
    return part


def key(html):
    """The key copy: from data-answer-key up to the switch."""
    return html.split("data-answer-key", 1)[1].split("data-answer-switch", 1)[0]
