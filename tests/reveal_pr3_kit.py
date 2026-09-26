"""Multiple choice + extended response (spec 2026-09-25 §8 PR 3): builders and the
parsers that read a choice option's marker out of rendered HTML.

Choice kit (multiple): A and B are correct, C is wrong; `half` picks A + C, so a
painted render reads A ✓, B unmarked (the key -- must not leak before the lock),
C ✗. Single choice: A correct; `half` picks C; A is the option that must not leak.
B and C carry per-option feedback ("Betafb", "Gammafb")."""

import re
from dataclasses import dataclass

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ExtendedResponseQuestionElement

TEXTS = ("Alphaopt", "Betaopt", "Gammaopt")
KEYWORDS = "question__reveal-keywords"
ER_WRONG = {"answer": "nothing relevant"}  # 0 / 1
ER_HALF = {"answer": "alphakw only"}  # 0.5 / 1
ER_RIGHT = {"answer": "alphakw and betakw"}  # 1 / 1

_LI = re.compile(r'<li class="question__choice\b.*?</li>', re.S)
_MARK = re.compile(r"question__choice-marker--(correct|wrong|missed)")


@dataclass
class ChoiceKit:
    question: ChoiceQuestionElement
    a: Choice
    b: Choice
    c: Choice
    half: dict
    right: dict


def choice(multiple=True, **kw):
    kw.setdefault("max_attempts", 3)
    q = ChoiceQuestionElement.objects.create(stem="Pick them.", multiple=multiple, **kw)
    a = Choice.objects.create(question=q, text="Alphaopt", is_correct=True)
    b = Choice.objects.create(
        question=q, text="Betaopt", is_correct=multiple, feedback="Betafb"
    )
    c = Choice.objects.create(
        question=q, text="Gammaopt", is_correct=False, feedback="Gammafb"
    )
    if multiple:
        return ChoiceKit(q, a, b, c, {"choice": [a.pk, c.pk]}, {"choice": [a.pk, b.pk]})
    return ChoiceKit(q, a, b, c, {"choice": [c.pk]}, {"choice": [a.pk]})


def extended(**kw):
    kw.setdefault("max_attempts", 3)
    return ExtendedResponseQuestionElement.objects.create(
        stem="Explain it.",
        required_keywords="alphakw\nbetakw",
        forbidden_keywords="gammakw",
        **kw,
    )


def option(html, text):
    """The <li> of the option whose text is `text` (exactly one expected)."""
    found = [li for li in _LI.findall(html) if f">{text}<" in li]
    assert len(found) == 1, (text, len(found))
    return found[0]


def markers(html):
    """{option text: "correct" | "wrong" | "missed" | None} for the kit's options."""
    out = {}
    for text in TEXTS:
        m = _MARK.search(option(html, text))
        out[text] = m.group(1) if m else None
    return out
