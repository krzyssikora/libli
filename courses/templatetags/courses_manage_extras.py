import re
from html import unescape
from urllib.parse import urlsplit

from django import template
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _

from courses.models import ContentNode
from courses.ordering import PRIMARY_CHILD_KIND
from courses.ordering import legal_child_kinds as _legal_child_kinds

register = template.Library()

# model-name (from Element.content_type) -> short translatable tile tag.
# These are the BRIEF list labels; the full edit-header names live in
# views_manage._EDITOR_TYPE_LABELS. Single vs multiple choice is resolved in
# element_type_label() from the object's `multiple` flag (same model).
_ELEMENT_LABELS = {
    "textelement": _("Text"),
    "imageelement": _("Image"),
    "videoelement": _("Video"),
    "iframeelement": _("Embed"),
    "mathelement": _("Math"),
    "htmlelement": _("HTML"),
    "choicequestionelement": _("Choice"),
    "shorttextquestionelement": _("Short"),
    "shortnumericquestionelement": _("Numeric"),
    "fillblankquestionelement": _("Blanks"),
    "dragfillblankquestionelement": _("Drag"),
    "matchpairquestionelement": _("Match"),
    "dragtoimagequestionelement": _("Zones"),
}


@register.filter
def get_item(mapping, key):
    """Dict lookup by variable key (for children_map[node.pk] in templates)."""
    if mapping is None:
        return []
    return mapping.get(key, [])


@register.simple_tag
def element_type_label(content_type, obj=None):
    """Short tile tag for an element's type. Pass the concrete content object as
    `obj` to distinguish single- vs multiple-choice (single -> "Choice",
    multiple -> "MChoice"); without it, choice falls back to "Choice"."""
    model = content_type.model
    if model == "choicequestionelement" and getattr(obj, "multiple", False):
        return _("MChoice")
    return _ELEMENT_LABELS.get(model, model)


def _host(url):
    return urlsplit(url or "").hostname or ""


@register.filter
def element_summary(el):
    """Display label for an element row (DoD #1). el is the concrete content object."""
    name = el.__class__.__name__
    if name == "IframeElement":
        return el.title or _host(el.url) or "Iframe"
    if name == "ImageElement":
        return el.alt or (el.media.display_name if el.media_id else "") or "Image"
    if name == "VideoElement":
        if el.media_id:
            return el.media.display_name
        return _host(el.url) or "Video"
    if name == "TextElement":
        text = re.sub(r"\s+", " ", strip_tags(el.body)).strip()
        return Truncator(unescape(text)).chars(60) or "Text"
    if name == "MathElement":
        return Truncator(el.latex).chars(60) or "Math"
    if name == "HtmlElement":
        text = re.sub(r"\s+", " ", strip_tags(el.html)).strip()
        return Truncator(unescape(text)).chars(60) or "HTML"
    # All question types carry a `stem`; summarise it rather than showing the raw
    # class name. Drag-fill/fill-blank token-stems embed U+FFFF gap sentinels
    # (￿N￿) — render those as a blank marker.
    stem = getattr(el, "stem", None)
    if stem is not None:
        text = re.sub(r"￿\d+￿", "___", stem)
        text = re.sub(r"\s+", " ", strip_tags(text)).strip()
        return Truncator(unescape(text)).chars(60) or name
    return name


@register.simple_tag
def legal_child_kinds(parent_kind):
    """List of kind strings (RANK order) a `parent_kind` scope may add. None = top."""
    return _legal_child_kinds(parent_kind)


@register.simple_tag
def primary_child_kind(parent_kind):
    """The one-click primary "+" kind for a >=3-legal-kind scope, else None."""
    return PRIMARY_CHILD_KIND.get(parent_kind)


@register.simple_tag
def kind_label(kind):
    """Translated human label for a ContentNode kind string.

    Example: 'chapter' -> 'Chapter' (en) / 'Rozdział' (pl).
    """
    return ContentNode.Kind(kind).label
