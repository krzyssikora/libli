"""Teacher-side display of one pupil's stored quiz answer (spec §4).

Side-effect free: no writes, no RNG. Reads only the child rows
courses.views.prefetch_question_children loads. `mark_result` is always the
caller's (views._results_row's reveal_result) -- `ok` is read from it, never
re-derived. No catch-all fail-open: an unregistered type raises KeyError.
"""

from dataclasses import dataclass

from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from courses.fillblank import _TOKEN_RE
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement

ANSWER = "answer"
KEYWORD = "keyword"


@dataclass(frozen=True)
class Part:
    kind: str
    label_is_content: bool
    label: str | None
    given: str | None
    expected: str | None
    ok: bool | None

    @property
    def mark(self):
        """The ✓/✗ glyph AND its sr-only label, as one unit (spec §5.1)."""
        if self.ok is None:
            return None
        if self.ok and self.kind == ANSWER and self.given is None:
            return None
        return "correct" if self.ok else "incorrect"


def _is_auto(question):
    return question.marking_mode == QuestionElement.MarkingMode.AUTO


def _answered(response):
    return response is not None and response.latest_answer is not None


def _text_or_none(value):
    """A string part is empty iff blank after strip (spec §4.2 rule 4)."""
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _answer_part(*, given, expected, ok, label=None, label_is_content=False):
    return Part(
        kind=ANSWER,
        label_is_content=label_is_content,
        label=label,
        given=given,
        # rule 2: the hint only where the part is not right
        expected=None if ok is True else expected,
        ok=ok,
    )


def _single(question, response, given, expected_when_auto, correct):
    """One answer part for a single-part type, applying rules 1-3."""
    if not _is_auto(question):
        return [_answer_part(given=given, expected=None, ok=None)]
    ok = bool(correct) if _answered(response) else False
    return [_answer_part(given=given, expected=expected_when_auto, ok=ok)]


def _choice(question, response, mark_result):
    choices = list(question.choices.all())
    given = None
    if _answered(response):
        picked = set(response.latest_answer or [])
        live = {c.pk for c in choices}
        texts = [c.text for c in choices if c.pk in picked]
        texts += [_("(removed option)")] * len(picked - live)
        given = ", ".join(texts) or None
    expected = None
    correct = None
    if _is_auto(question):
        correct_set = set(mark_result.reveal or ())
        expected = ", ".join(c.text for c in choices if c.pk in correct_set) or _(
            "(none)"
        )
        correct = mark_result.correct
    return _single(question, response, given, expected, correct)


def _shorttext(question, response, mark_result):
    given = _text_or_none(response.latest_answer) if _answered(response) else None
    if not _is_auto(question):
        return _single(question, response, given, None, None)
    return _single(question, response, given, mark_result.reveal, mark_result.correct)


def _shortnumeric(question, response, mark_result):
    given = _text_or_none(response.latest_answer) if _answered(response) else None
    if not _is_auto(question):
        return _single(question, response, given, None, None)
    reveal = mark_result.reveal
    expected = reveal["value"]
    if reveal["tolerance"]:
        expected = f"{expected} ± {reveal['tolerance']}"
    return _single(question, response, given, expected, mark_result.correct)


def _extendedresponse(question, response, mark_result):
    answered = _answered(response)
    given = _text_or_none(response.latest_answer) if answered else None
    if not _is_auto(question):
        # keyword parts are AUTO-only: stale keywords on a REVIEW row are ignored
        return [_answer_part(given=given, expected=None, ok=None)]
    parts = [
        _answer_part(
            given=given,
            expected=None,
            ok=bool(mark_result.correct) if answered else False,
        )
    ]
    for item in mark_result.reveal:
        required = item["kind"] == "required"
        prefix = _("Required") if required else _("Avoid")
        if not answered:
            ok = None
        else:
            ok = item["found"] if required else not item["found"]
        parts.append(
            Part(
                kind=KEYWORD,
                label_is_content=False,
                label=f"{prefix}: {item['keyword']}",
                given=None,
                expected=None,
                ok=ok,
            )
        )
    return parts


def _padded(stored, count, empty):
    """Pad/truncate a stored positional answer to the question's CURRENT part
    count, exactly as each mark() does, so parts and reveal align by index."""
    values = list(stored) if isinstance(stored, (list, tuple)) else []
    return (values + [empty] * count)[:count]


def _multi(
    question,
    response,
    mark_result,
    *,
    labels,
    content_labels,
    convert,
    empty,
    expected_of,
    ok_of,
):
    """One answer part per child row. Labels and the part count come from the
    CURRENT child rows in every mode; reveal[i] is read only for AUTO."""
    count = len(labels)
    answered = _answered(response)
    values = _padded(response.latest_answer if answered else None, count, empty)
    auto = _is_auto(question)
    parts = []
    for i, label in enumerate(labels):
        given = convert(values[i]) if answered else None
        if not auto:
            expected, ok = None, None
        else:
            item = mark_result.reveal[i]
            expected = expected_of(item)
            ok = bool(ok_of(item)) if answered else False
        parts.append(
            _answer_part(
                label=label,
                label_is_content=content_labels,
                given=given,
                expected=expected,
                ok=ok,
            )
        )
    return parts


def _numbered(label, count):
    return [label % {"n": i + 1} for i in range(count)]


def _fillblank(question, response, mark_result):
    return _multi(
        question,
        response,
        mark_result,
        labels=_numbered(_("Gap %(n)s"), len(question.blanks.all())),
        content_labels=False,
        convert=_text_or_none,
        empty=None,
        expected_of=lambda item: item["accepted"],
        ok_of=lambda item: item["correct"],
    )


def _dragfill(question, response, mark_result):
    return _multi(
        question,
        response,
        mark_result,
        labels=_numbered(_("Gap %(n)s"), len(question.dragblanks.all())),
        content_labels=False,
        convert=_text_or_none,
        empty=None,
        expected_of=lambda item: item["accepted"],
        ok_of=lambda item: item["correct"],
    )


def _dragimage(question, response, mark_result):
    return _multi(
        question,
        response,
        mark_result,
        labels=_numbered(_("Zone %(n)s"), len(question.zones.all())),
        content_labels=False,
        convert=_text_or_none,
        empty=None,
        expected_of=lambda item: item["accepted"],
        ok_of=lambda item: item["correct"],
    )


def _matchpair(question, response, mark_result):
    return _multi(
        question,
        response,
        mark_result,
        labels=[pair.left for pair in question.pairs.all()],
        content_labels=True,
        convert=_text_or_none,
        empty=None,
        expected_of=lambda item: item["accepted"],
        ok_of=lambda item: item["correct"],
    )


def _choicegrid(question, response, mark_result):
    by_pk = {c.pk: c.label for c in question.columns.all()}

    def convert(value):
        if value in ("", None):
            return None
        return by_pk.get(value, _("(removed option)"))

    return _multi(
        question,
        response,
        mark_result,
        labels=[row.statement for row in question.rows.all()],
        content_labels=True,
        convert=convert,
        empty="",
        expected_of=lambda item: item["correct_label"],
        ok_of=lambda item: item["is_correct"],
    )


def _multigrid(question, response, mark_result):
    columns = list(question.columns.all())
    live = {c.pk for c in columns}

    def convert(value):
        chosen = set(value) if isinstance(value, (list, tuple)) else set()
        if not chosen:
            return None
        texts = [c.label for c in columns if c.pk in chosen]
        texts += [_("(removed option)")] * len(chosen - live)
        return ", ".join(texts)

    return _multi(
        question,
        response,
        mark_result,
        labels=[row.statement for row in question.rows.all()],
        content_labels=True,
        convert=convert,
        empty=[],
        expected_of=lambda item: ", ".join(item["correct_labels"]) or _("(none)"),
        ok_of=lambda item: item["is_correct"],
    )


def gap_marked_stem(question):
    """A fillblank/dragfill TOKEN stem with each U+FFFF n U+FFFF token replaced by a
    visible [n+1] marker, numbered like the "Gap i" part labels (spec §5.1)."""

    def _swap(match):
        return str(
            format_html(
                '<span class="answers__gap">[{}]</span>', int(match.group(1)) + 1
            )
        )

    # The stem was sanitised on save; the inserted markup is digits only.
    return mark_safe(_TOKEN_RE.sub(_swap, question.stem or ""))  # noqa: S308


_TOKEN_STEM_TYPES = (FillBlankQuestionElement, DragFillBlankQuestionElement)


def stem_html(question):
    """The stem as the page renders it: gap-marked for token types, else as-is
    (sanitised on save, rendered |safe exactly as quiz_results does)."""
    if isinstance(question, _TOKEN_STEM_TYPES):
        return gap_marked_stem(question)
    return mark_safe(question.stem)  # noqa: S308


_ADAPTERS = {
    ChoiceQuestionElement: _choice,
    ShortTextQuestionElement: _shorttext,
    ShortNumericQuestionElement: _shortnumeric,
    ExtendedResponseQuestionElement: _extendedresponse,
    FillBlankQuestionElement: _fillblank,
    DragFillBlankQuestionElement: _dragfill,
    DragToImageQuestionElement: _dragimage,
    MatchPairQuestionElement: _matchpair,
    ChoiceGridQuestionElement: _choicegrid,
    MultiGridQuestionElement: _multigrid,
}


def summarise(question, response, mark_result):
    """Display parts for one question's stored answer (spec §4.1)."""
    return _ADAPTERS[type(question)](question, response, mark_result)
