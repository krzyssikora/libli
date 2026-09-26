"""One verdict -> markup for the Python-built answer controls (spec 2026-09-25 §2.1).

Colour is never the only cue: a painted part gets a state class, a wrong one
aria-invalid, and both a .sr-only "correct"/"incorrect" (the global utility, NOT
the notes/tags .visually-hidden). A verdict of None paints NOTHING, so an unpainted
render stays byte-identical to the pre-reveal markup."""

from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import pgettext


def part_verdict(verdicts, i, key):
    """Part i's verdict: every part is correct in the key copy; a list shorter
    than the parts (a part added after the answer) leaves the rest unpainted."""
    if key:
        return True
    marks = verdicts or ()
    return marks[i] if 0 <= i < len(marks) else None


def state_class(verdict):
    return {True: " is-correct", False: " is-incorrect"}.get(verdict, "")


def invalid_attr(verdict):
    return mark_safe(' aria-invalid="true"') if verdict is False else ""  # noqa: S308 — constant


def sr_verdict(verdict):
    if verdict is None:
        return ""
    return format_html(
        '<span class="sr-only">{}</span>',
        pgettext("answer part verdict", "correct")
        if verdict
        else pgettext("answer part verdict", "incorrect"),
    )
