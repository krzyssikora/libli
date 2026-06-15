from django import template
from django.utils.translation import gettext_lazy as _

register = template.Library()

# model-name (from Element.content_type) -> translatable label
_ELEMENT_LABELS = {
    "textelement": _("Text"),
    "imageelement": _("Image"),
    "videoelement": _("Video"),
    "iframeelement": _("Embed"),
    "mathelement": _("Math"),
}


@register.filter
def get_item(mapping, key):
    """Dict lookup by variable key (for children_map[node.pk] in templates)."""
    if mapping is None:
        return []
    return mapping.get(key, [])


@register.simple_tag
def element_type_label(content_type):
    return _ELEMENT_LABELS.get(content_type.model, content_type.model)
