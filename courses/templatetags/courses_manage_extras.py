import re
from html import unescape
from urllib.parse import urlsplit

from django import template
from django.utils.html import strip_tags
from django.utils.text import Truncator
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


def _host(url):
    return urlsplit(url or "").hostname or ""


@register.filter
def element_summary(el):
    """Display label for an element row (DoD #1). el is the concrete content object."""
    name = el.__class__.__name__
    if name == "IframeElement":
        return el.title or _host(el.url) or "Iframe"
    if name == "ImageElement":
        return el.alt or (el.media.original_filename if el.media_id else "") or "Image"
    if name == "VideoElement":
        if el.media_id:
            return el.media.original_filename
        return _host(el.url) or "Video"
    if name == "TextElement":
        text = re.sub(r"\s+", " ", strip_tags(el.body)).strip()
        return Truncator(unescape(text)).chars(60) or "Text"
    if name == "MathElement":
        return Truncator(el.latex).chars(60) or "Math"
    return name
