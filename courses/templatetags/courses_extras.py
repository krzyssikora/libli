from django import template
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
            )
        )
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields


@register.filter
def sanitize(value):
    """PRESERVED from the existing file — DO NOT drop it: `textelement.html` uses
    `{{ el.body|sanitize }}`. Re-sanitises stored rich text at render
    (defense-in-depth)."""
    return mark_safe(sanitize_html(value))  # noqa: S308 — output is sanitised
