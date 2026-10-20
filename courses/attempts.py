"""Attempts settings (spec 2026-10-20): the ONE home of input parsing, the
author-facing wording, override counting and the bulk reset, shared by the
question form, the quiz settings save (builder.rename_node) and CourseForm."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from courses.models import MAX_ATTEMPTS_LIMIT
from courses.models import AttemptsMode
from courses.models import ContentNode
from courses.models import Element
from courses.models import QuestionElement

QUESTION_MODES = ("inherit", "limited", "unlimited")
UNIT_MODES = QUESTION_MODES
COURSE_MODES = ("limited", "unlimited")  # P2: the course has no level above

MSG_CHOOSE = _("Choose one of the attempts options.")
MSG_ENTER = _("Enter a number of attempts, or choose another option.")
MSG_CAP = _("At most 32767 attempts. For no limit, choose 'Unlimited'.")
# D9: the 0 message names the option actually on screen.
ZERO_MESSAGES = {
    "quiz": _("0 isn't a limit. To use the quiz's setting, choose 'Same as quiz'."),
    "course": _(
        "0 isn't a limit. To use the course's setting, choose 'Same as course'."
    ),
    "course_level": _("0 isn't a limit. Choose 'Unlimited' or a number from 1."),
}


def parse_attempts(mode, raw_limit, *, allowed_modes, zero_message):
    """(mode, limit) from posted strings (spec §5.1/§5.2). limit is None unless the
    mode is limited, so a hidden-but-posted number is dropped, never validated.
    Raises ValidationError ONLY -- no int() on unchecked input can escape."""
    if not isinstance(mode, str) or mode not in allowed_modes:
        raise ValidationError(MSG_CHOOSE, code="attempts_mode")
    if mode != AttemptsMode.LIMITED:
        return mode, None
    text = raw_limit.strip() if isinstance(raw_limit, str) else ""
    if not text.isdecimal():  # "", "abc", "2.5", "-1"
        raise ValidationError(MSG_ENTER, code="attempts_limit")
    # Length first: int() of a huge digit string is slow and capped by CPython.
    if len(text) > len(str(MAX_ATTEMPTS_LIMIT)) or int(text) > MAX_ATTEMPTS_LIMIT:
        raise ValidationError(MSG_CAP, code="attempts_limit")
    limit = int(text)
    if limit == 0:
        raise ValidationError(zero_message, code="attempts_limit")
    return mode, limit


def inherit_label(source, value):
    """The *inherit* option label, showing the value it resolves to (P7)."""
    shown = str(value) if value is not None else gettext("unlimited")
    if source == "quiz":
        return gettext("Same as quiz (currently: %(value)s)") % {"value": shown}
    return gettext("Same as course (currently: %(value)s)") % {"value": shown}


def _question_models():
    # Derived, never hand-written: a new question type is covered automatically.
    from courses.richtext import CONCRETE_QUESTION_MODELS

    return CONCRETE_QUESTION_MODELS


def _questions_in(model, unit_pks):
    # Question rows reach their unit only through the generic Element join.
    ct = ContentType.objects.get_for_model(model)
    return model.objects.filter(
        pk__in=Element.objects.filter(unit_id__in=unit_pks, content_type=ct).values(
            "object_id"
        )
    )


def count_question_overrides(unit_pks):
    """[A] questions with their own setting -- the only ones attempts affect (P3)."""
    return sum(
        _questions_in(model, unit_pks)
        .filter(marking_mode=QuestionElement.MarkingMode.AUTO)
        .exclude(attempts_mode=AttemptsMode.INHERIT)
        .count()
        for model in _question_models()
    )


def reset_question_rows(unit_pks):
    """Set every non-inherit question row in `unit_pks` to inherit ([N]/[R]
    included -- harmless). Returns the pks of units that had one (spec §5.4)."""
    touched = set()
    for model in _question_models():
        ct = ContentType.objects.get_for_model(model)
        ids = list(
            _questions_in(model, unit_pks)
            .exclude(attempts_mode=AttemptsMode.INHERIT)
            .values_list("pk", flat=True)
        )
        if not ids:
            continue
        touched |= set(
            Element.objects.filter(
                unit_id__in=unit_pks, content_type=ct, object_id__in=ids
            ).values_list("unit_id", flat=True)
        )
        model.objects.filter(pk__in=ids).update(
            attempts_mode=AttemptsMode.INHERIT, attempts_limit=None
        )
    return touched


def reset_quiz_overrides(unit):
    """Quiz-level reset. The caller (rename_node) holds the unit's row lock and its
    save(update_fields=[..., "updated"]) bumps the unit, so no bump here."""
    count = count_question_overrides([unit.pk])
    reset_question_rows([unit.pk])
    return count


def _quiz_units(course):
    return ContentNode.objects.filter(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.QUIZ,
    )


def course_override_counts(course):
    """(quizzes, questions) with their own setting, for the reset choice (no locks)."""
    pks = list(_quiz_units(course).values_list("pk", flat=True))
    quizzes = _quiz_units(course).exclude(attempts_mode=AttemptsMode.INHERIT).count()
    return quizzes, count_question_overrides(pks)


def reset_course_overrides(course):
    """Course-level reset (spec §5.3/§5.4). The caller holds a transaction and must
    write the Course row AFTER this returns: the global lock order is quiz units
    (pk order), then course -- the order builder ops already use. Every later
    query scopes by the pks the locking SELECT returned, never a fresh
    unit_type filter, so a concurrent lesson -> quiz toggle cannot slip in."""
    units = list(
        _quiz_units(course)
        .select_for_update()
        .order_by("pk")
        .only("pk", "attempts_mode")
    )
    pks = [u.pk for u in units]
    overriding = [u.pk for u in units if u.attempts_mode != AttemptsMode.INHERIT]
    questions = count_question_overrides(pks)
    touched = reset_question_rows(pks) | set(overriding)
    if overriding:
        ContentNode.objects.filter(pk__in=overriding).update(
            attempts_mode=AttemptsMode.INHERIT, attempts_limit=None
        )
    if touched:
        # Explicit: `updated` is auto_now and QuerySet.update() never applies it.
        # The bump turns an open editor's next save into the stale-token
        # "changed elsewhere" response instead of silently undoing the reset.
        ContentNode.objects.filter(pk__in=touched).update(updated=timezone.now())
    return len(overriding), questions


def _what(quizzes, questions):
    """'2 quizzes and 41 questions'; a zero part is omitted (spec §5.4)."""
    parts = []
    if quizzes:
        parts.append(ngettext("%(n)d quiz", "%(n)d quizzes", quizzes) % {"n": quizzes})
    if questions:
        parts.append(
            ngettext("%(n)d question", "%(n)d questions", questions) % {"n": questions}
        )
    return gettext(" and ").join(parts)


def course_keep_label(quizzes, questions):
    return ngettext(
        "Keep specific settings (%(what)s has its own)",
        "Keep specific settings (%(what)s have their own)",
        quizzes + questions,
    ) % {"what": _what(quizzes, questions)}


def quiz_keep_label(n):
    return ngettext(
        "Keep questions' own settings (%(n)d question)",
        "Keep questions' own settings (%(n)d questions)",
        n,
    ) % {"n": n}


def course_reset_message(quizzes, questions):
    if not quizzes and not questions:
        return gettext("Settings saved.")
    return ngettext(
        "Settings saved. %(what)s now uses the course setting.",
        "Settings saved. %(what)s now use the course setting.",
        quizzes + questions,
    ) % {"what": _what(quizzes, questions)}


def quiz_reset_message(n):
    if not n:
        return gettext("Settings saved.")
    return ngettext(
        "Settings saved. %(n)d question now uses the quiz setting.",
        "Settings saved. %(n)d questions now use the quiz setting.",
        n,
    ) % {"n": n}
