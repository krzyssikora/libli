"""The single channel for everything the generator has to report.

A closed set of machine keys plus a translated display map, split the way the
DemoKit.status_key property is: the command prints keys, PR 3's tab renders the
map. `unit_id` is optional — two kinds have no unit.

Named DemoWarning, NOT Warning: the bare name shadows the builtin exception
base, and all three consumers spell it the same way here rather than two of them
aliasing it on import.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class DemoWarning:
    """⚠️ A frozen dataclass, NOT a NamedTuple.

    `typing.NamedTuple` lists `__new__` in its `_prohibited` set, so defining one
    raises `AttributeError: Cannot overwrite NamedTuple attribute __new__` at
    CLASS-CREATION time — `import demo.warnings` fails, and with it every module
    from Task 6 onward. (Verified under this repo's interpreter.) A frozen
    dataclass validates in `__post_init__` instead, and the consumers only ever
    use attribute access (`w.kind`, `w.unit_id`, `w.reason`) plus equality, all
    of which it provides.
    """

    kind: str
    unit_id: int | None  # `X | None`, never Optional[X]: ruff UP045 at py313
    reason: str

    def __post_init__(self):
        # THIS is what makes KINDS a closed set. Without it
        # `DemoWarning("quiz_skiped", ...)` is accepted everywhere, survives
        # Task 15's `set(DISPLAY) == KINDS` test (which only compares the map
        # with itself), and surfaces as a KeyError in PR 3's template months
        # later.
        if self.kind not in KINDS:
            raise ValueError(f"unknown warning kind {self.kind!r}; add it to DISPLAY")


DISPLAY = {
    "quiz_skipped": _("Quiz skipped: it holds a question the demo cannot answer."),
    "question_dropped": _("An unmarked question was left unanswered."),
    "variant_dropped": _("A wrong-answer variant failed validation."),
    "sentinel_answered": _(
        "A question has no usable wrong answer; all pupils answer it correctly."
    ),
    "partial_fallback": _(
        "A partial answer failed validation; the wrong answer is used."
    ),
    "fewer_in_progress_than_target": _("Fewer unfinished quizzes than intended."),
    "no_qualifying_pupil": _(
        "No pupil could be left with an unfinished quiz; the review queue will be "
        "empty."
    ),
    "active_webhook_endpoint": _(
        "A webhook endpoint is enabled: demo data will be sent to it."
    ),
    "no_gradeable_question": _(
        "Quiz skipped: it holds no question the demo can grade."
    ),
    "correct_answer_rejected": _(
        "A question's own correct answer did not mark full marks; the quiz was skipped."
    ),
}

KINDS = frozenset(DISPLAY)
