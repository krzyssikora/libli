"""Template helpers for the course-management and builder UI."""

import re
from html import unescape
from urllib.parse import urlsplit

from django import template
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from courses.models import ContentNode
from courses.models import GalleryElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.ordering import legal_child_kinds as _legal_child_kinds
from courses.ordering import primary_child_kind as _primary_child_kind

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
    "tableelement": _("Table"),
    "galleryelement": _("Gallery"),
    "tabselement": _("Tabs"),
    "choicequestionelement": _("Choice"),
    "shorttextquestionelement": _("Short"),
    "shortnumericquestionelement": _("Numeric"),
    "fillblankquestionelement": _("Blanks"),
    "dragfillblankquestionelement": _("Drag"),
    "matchpairquestionelement": _("Match"),
    "dragtoimagequestionelement": _("Zones"),
    "extendedresponsequestionelement": _("Essay"),
    "slidebreakelement": _("Slide break"),
    "revealgateelement": _("Show more"),
    "fillgateelement": _("Fill in & confirm"),
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
    if name == "SlideBreakElement":
        # Field-less delimiter: no content to summarise (type tag already
        # says "Slide break" via element_type_label — avoid repeating it).
        return "—"
    if name == "RevealGateElement":
        return el.label or _("Show more")
    if name == "TableElement":
        d = TableElement.normalize_data(el.data)
        rows, cols = len(d["cells"]), len(d["cells"][0])
        # Translatable per the Global Constraints. `_` here is gettext_lazy; the
        # % forces evaluation at request time, so it is locale-aware. Under the
        # EN catalog this renders "2×3 table" (matching the test).
        return _("%(rows)d×%(cols)d table") % {"rows": rows, "cols": cols}
    if name == "GalleryElement":
        n = len(GalleryElement.normalize_data(el.data)["images"])
        # ngettext (not the lazy `_`) so the plural form is chosen against the
        # request's active locale at render time.
        return ngettext("%(n)d image", "%(n)d images", n) % {"n": n}
    if name == "TabsElement":
        n = len(TabsElement.normalize_labels_and_ids(el.data)["tabs"])
        # ngettext (not the lazy `_`) so the plural form is chosen against the
        # request's active locale at render time. Polish has three plural forms.
        return ngettext("%(n)d tab", "%(n)d tabs", n) % {"n": n}
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
def tabs_bounds():
    """Bounds the tabs label editor renders into data-* attributes: the min/max tab
    counts tabs_editor.js reads to gate the add/remove buttons, and the per-label
    maxlength. Sourced from the model constants so the template never hardcodes them."""
    return {
        "min": TabsElement.MIN_TABS,
        "max": TabsElement.MAX_TABS,
        "label_max": TabsElement.LABEL_MAX,
    }


@register.simple_tag
def legal_child_kinds(parent_kind, allowed_kinds):
    """Kind strings (RANK order) a `parent_kind` scope may add within this
    course's `allowed_kinds`. None = top scope."""
    return _legal_child_kinds(parent_kind, allowed_kinds)


@register.simple_tag
def primary_child_kind(parent_kind, allowed_kinds):
    """The one-click primary "+" kind for a >=3-legal-kind scope, else None."""
    return _primary_child_kind(parent_kind, allowed_kinds)


@register.simple_tag
def kind_label(kind):
    """Translated human label for a ContentNode kind string.

    Example: 'chapter' -> 'Chapter' (en) / 'Rozdział' (pl).
    """
    return ContentNode.Kind(kind).label
