"""Export: serialize a course/subtree content graph to the archive format (§2)."""

from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.transfer.schema import TransferError


class MediaIdMap:
    """Stable asset-pk -> internal id ("m1", "m2", …) in first-reference order."""

    def __init__(self):
        self._by_pk = {}
        self._assets = []

    def register(self, asset):
        if asset.pk not in self._by_pk:
            self._by_pk[asset.pk] = f"m{len(self._assets) + 1}"
            self._assets.append(asset)
        return self._by_pk[asset.pk]

    def items(self):
        return [(self._by_pk[a.pk], a) for a in self._assets]


def _question_fields(q):
    return {
        "stem": q.stem,
        "explanation": q.explanation,
        "marking_mode": q.marking_mode,
        "max_attempts": q.max_attempts,
        "max_marks": str(q.max_marks),
    }


def _ser_text(el, ids):
    return {"body": el.body}


def _ser_image(el, ids):
    return {"media": ids.register(el.media), "alt": el.alt, "figcaption": el.figcaption}


def _ser_video(el, ids):
    if el.media_id is not None:
        return {"url": None, "media": ids.register(el.media)}
    return {"url": el.url, "media": None}


def _ser_iframe(el, ids):
    return {"url": el.url, "title": el.title}


def _ser_math(el, ids):
    return {"latex": el.latex}


def _ser_html(el, ids):
    return {"html": el.html}


def _ser_choice(el, ids):
    return {
        **_question_fields(el),
        "multiple": el.multiple,
        "choices": [
            {"text": c.text, "is_correct": c.is_correct} for c in el.choices.all()
        ],
    }


def _ser_short_text(el, ids):
    return {
        **_question_fields(el),
        "accepted": el.accepted,
        "case_sensitive": el.case_sensitive,
    }


def _ser_extended(el, ids):
    return {
        **_question_fields(el),
        "required_keywords": el.required_keywords,
        "forbidden_keywords": el.forbidden_keywords,
    }


def _ser_numeric(el, ids):
    return {
        **_question_fields(el),
        "value": str(el.value),
        "tolerance": str(el.tolerance),
    }


def _ser_fill_blank(el, ids):
    return {
        **_question_fields(el),
        "blanks": [
            {"accepted": b.accepted, "case_sensitive": b.case_sensitive}
            for b in el.blanks.all()
        ],
    }


def _ser_drag_fill(el, ids):
    return {
        **_question_fields(el),
        "distractors": el.distractors,
        "blanks": [{"correct_token": b.correct_token} for b in el.dragblanks.all()],
    }


def _ser_match_pair(el, ids):
    return {
        **_question_fields(el),
        "distractors": el.distractors,
        "pairs": [{"left": p.left, "right": p.right} for p in el.pairs.all()],
    }


def _ser_drag_to_image(el, ids):
    return {
        **_question_fields(el),
        "media": ids.register(el.media),
        "alt": el.alt,
        "distractors": el.distractors,
        "zones": [
            {"correct_label": z.correct_label, "x": z.x, "y": z.y, "w": z.w, "h": z.h}
            for z in el.zones.all()
        ],
    }


# type_key -> (model, serializer). The 14-entry registry; Task 6's importer-side
# registry in schema.py mirrors these keys — keep both in lockstep.
SERIALIZERS = {
    "text": (TextElement, _ser_text),
    "image": (ImageElement, _ser_image),
    "video": (VideoElement, _ser_video),
    "iframe": (IframeElement, _ser_iframe),
    "math": (MathElement, _ser_math),
    "html": (HtmlElement, _ser_html),
    "choice": (ChoiceQuestionElement, _ser_choice),
    "short_text": (ShortTextQuestionElement, _ser_short_text),
    "extended_response": (ExtendedResponseQuestionElement, _ser_extended),
    "short_numeric": (ShortNumericQuestionElement, _ser_numeric),
    "fill_blank": (FillBlankQuestionElement, _ser_fill_blank),
    "drag_fill_blank": (DragFillBlankQuestionElement, _ser_drag_fill),
    "match_pair": (MatchPairQuestionElement, _ser_match_pair),
    "drag_to_image": (DragToImageQuestionElement, _ser_drag_to_image),
}

_MODEL_TO_KEY = {model: key for key, (model, _fn) in SERIALIZERS.items()}


def serialize_element_data(concrete, media_ids):
    key = _MODEL_TO_KEY.get(type(concrete))
    if key is None:  # pragma: no cover — every ElementBase subclass is registered
        raise TransferError(f"Unserializable element model: {type(concrete).__name__}")
    _model, fn = SERIALIZERS[key]
    return key, fn(concrete, media_ids)
