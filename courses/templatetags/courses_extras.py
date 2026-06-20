from decimal import Decimal

from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

from courses.models import HtmlElement
from courses.models import QuestionElement
from courses.sanitize import sanitize_html

register = template.Library()


@register.simple_tag
def render_element(
    element,
    feedback_for_pk=None,
    selected_ids=frozenset(),
    submitted_values=None,
    mark_result=None,
    mode="lesson",
    action_url=None,
    feedback_partial="courses/elements/_question_feedback.html",
    quiz_submitted=False,
    locked=False,
    attempts_left=None,
    feedback_html="",
):
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        return mark_safe(obj.render(unit=element.unit, course=element.unit.course))  # noqa: S308
    if isinstance(obj, QuestionElement):
        return mark_safe(  # noqa: S308 — templates escape user text; correctness never leaks
            obj.render(
                element=element,
                feedback_for_pk=feedback_for_pk,
                selected_ids=selected_ids,
                submitted_values=submitted_values,
                mark_result=mark_result,
                mode=mode,
                action_url=action_url,
                feedback_partial=feedback_partial,
                quiz_submitted=quiz_submitted,
                locked=locked,
                attempts_left=attempts_left,
                feedback_html=feedback_html,
            )
        )
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields


@register.filter
def sanitize(value):
    """PRESERVED from the existing file — DO NOT drop it: `textelement.html` uses
    `{{ el.body|sanitize }}`. Re-sanitises stored rich text at render
    (defense-in-depth)."""
    return mark_safe(sanitize_html(value))  # noqa: S308 — output is sanitised


@register.simple_tag
def render_fill_blanks(el, submitted_values=None):
    """Render a fill-blank stem: text segments (sanitized HTML) interleaved with
    server-built <input name="blank"> elements (escaped values).

    See courses.fillblank."""
    from courses import fillblank

    return fillblank.render_inputs(el.stem, submitted_values)


@register.simple_tag
def render_drag_selects(el, submitted_values=None):
    """Render a drag-fill stem: text segments interleaved with server-built
    <select name="slot"> elements (escaped). See courses.dnd."""
    from courses import dnd

    return dnd.render_selects(el.stem, dnd.build_pool(el), submitted_values)


@register.simple_tag
def render_match_pairs(el, submitted_values=None):
    """Render a match-pairs widget: an <ol> of (left label, <select name="slot">)
    rows. See courses.dnd."""
    from courses import dnd

    return dnd.render_match_rows(list(el.pairs.all()), dnd.build_pool(el), submitted_values)


@register.filter(name="marks")
def marks_filter(value):
    """Format a marks Decimal for display: 2dp, trailing zeros + trailing '.' trimmed.

    NOT Decimal.normalize() — that yields scientific notation for whole tens
    (Decimal("10.00").normalize() == Decimal("1E+1")).
    """
    if value is None:
        return "—"
    s = f"{Decimal(value).quantize(Decimal('0.01')):f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


@register.filter
def dictkey(d, key):
    """Look up d[key] in a template (responses keyed by element pk)."""
    return (d or {}).get(key)


@register.filter
def quiz_answer_url(element):
    return reverse(
        "courses:quiz_answer",
        kwargs={
            "slug": element.unit.course.slug,
            "node_pk": element.unit_id,
            "element_pk": element.pk,
        },
    )
