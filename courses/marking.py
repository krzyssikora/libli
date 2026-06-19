from dataclasses import dataclass


@dataclass(frozen=True)
class MarkResult:
    """The normalized result every question type's mark() returns.

    `reveal` is a per-type, type-opaque presentation payload consumed by the
    feedback template. For ChoiceQuestionElement it is a frozenset[int] of the
    correct choice ids.
    """

    correct: bool
    fraction: float
    reveal: frozenset = frozenset()
