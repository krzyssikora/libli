from django import template
from django.utils.safestring import mark_safe

from courses.models import HtmlElement
from courses.sanitize import sanitize_html

register = template.Library()


@register.simple_tag
def render_element(element):
    """Render one Element's concrete payload.

    Returns empty string if the target was deleted.
    """
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        # HtmlElement needs course-wide CSS/JS + the unit seed, resolved from
        # the join-row (element.unit -> unit.course). The template escapes srcdoc.
        return mark_safe(obj.render(unit=element.unit, course=element.unit.course))  # noqa: S308
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields


@register.filter
def sanitize(value):
    """Re-sanitise stored rich text at render (defense-in-depth) and mark safe."""
    return mark_safe(sanitize_html(value))  # noqa: S308 — output is sanitised
