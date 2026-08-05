"""Template helpers for the course-management and builder UI."""

import re
from html import unescape
from urllib.parse import urlsplit

from django import template
from django.utils.html import strip_tags
from django.utils.http import urlencode
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from courses import builder
from courses.models import ContentNode
from courses.models import FillTableElement
from courses.models import GalleryElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TwoColumnElement
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
    "twocolumnelement": _("Columns"),
    "choicequestionelement": _("Choice"),
    "shorttextquestionelement": _("Short"),
    "shortnumericquestionelement": _("Numeric"),
    "fillblankquestionelement": _("Blanks"),
    "dragfillblankquestionelement": _("Drag"),
    "matchpairquestionelement": _("Match"),
    "choicegridquestionelement": _("Matrix"),
    "multigridquestionelement": _("Multi-select grid"),
    "dragtoimagequestionelement": _("Zones"),
    "extendedresponsequestionelement": _("Essay"),
    "slidebreakelement": _("Slide break"),
    "revealgateelement": _("Show more"),
    "spoilerelement": _("Spoiler"),
    "fillgateelement": _("Fill in & confirm"),
    "switchgateelement": _("Choose & confirm"),
    "switchgridelement": _("Switch grid"),
    "filltableelement": _("Fill-in table"),
    "calloutelement": _("Callout"),
    "stepperelement": _("Steps"),
    "markdoneelement": _("Checklist"),
    "guessnumberelement": _("Guess the number"),
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
    if name == "SpoilerElement":
        return el.label or _("Reveal")
    if name == "CalloutElement":
        return el.display_heading
    if name == "TableElement":
        d = TableElement.normalize_data(el.data)
        rows, cols = len(d["cells"]), len(d["cells"][0])
        # Translatable per the Global Constraints. `_` here is gettext_lazy; the
        # % forces evaluation at request time, so it is locale-aware. Under the
        # EN catalog this renders "2×3 table" (matching the test).
        return _("%(rows)d×%(cols)d table") % {"rows": rows, "cols": cols}
    if name == "FillTableElement":
        d = FillTableElement.normalize_data(el.data)
        n_ans = sum(1 for row in d["cells"] for c in row if c["kind"] == "answer")
        rows, cols = len(d["cells"]), len(d["cells"][0])
        return _("%(rows)d×%(cols)d fill-in table, %(n)d answer(s)") % {
            "rows": rows,
            "cols": cols,
            "n": n_ans,
        }
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
    if name == "TwoColumnElement":
        n = len(TwoColumnElement.normalize_ids(el.data)["columns"])
        # ngettext (not the lazy `_`) so the plural form is chosen against the
        # request's active locale at render time.
        return ngettext("%(n)d column", "%(n)d columns", n) % {"n": n}
    if isinstance(el, SwitchGridElement):
        # No top-level `stem` (multi-line grid) -- fall back to the instruction
        # prompt, or the type label if the author left it blank.
        text = re.sub(r"\s+", " ", strip_tags(el.prompt or "")).strip()
        return Truncator(text).chars(60) or name
    if name == "StepperElement":
        first = el.steps.first()
        text = el.prompt or (first.content if first else "")
        text = re.sub(r"\s+", " ", strip_tags(text)).strip()
        return Truncator(unescape(text)).chars(60) or _("Step-by-step")
    if name == "MarkDoneElement":
        first = el.items.first()
        text = el.prompt or (first.content if first else "")
        text = re.sub(r"\s+", " ", strip_tags(text)).strip()
        return Truncator(unescape(text)).chars(60) or _("Checklist")
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
    """Bounds the tabs label editor renders into data-* attributes, plus the two
    display-setting enums as ordered (value, label) pairs. Sourced from the model
    constants so the template never hardcodes a member or a label."""
    return {
        "min": TabsElement.MIN_TABS,
        "max": TabsElement.MAX_TABS,
        "label_max": TabsElement.LABEL_MAX,
        "displays": TabsElement.DISPLAY_CHOICES,
        "label_positions": TabsElement.LABEL_POS_CHOICES,
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


@register.filter
def in_set(value, container):
    """`{% include ... with is_open=node.pk|in_set:open_ids %}`.

    A filter, because an {% include %} `with` argument cannot contain an `in`
    expression. Django's smartif swallows errors in `{% if x in y %}`, so a
    missing container renders silently-collapsed rather than loudly -- this
    filter fails the same way by design, matching the template's behaviour.
    """
    try:
        return value in (container or ())
    except TypeError:
        return False


@register.filter
def slot_key(parent_pk, tab_id):
    """Template-side twin of builder.slot_key, registered as a FILTER because the
    <details> open test builds its key from two values inside an expression,
    where an inclusion tag cannot be used:

        {% if el.pk|slot_key:tab.id|in_set:open_slots %}

    Delegates rather than re-deriving, so the key shape has exactly one
    definition.
    """
    return builder.slot_key(parent_pk, tab_id)


@register.simple_tag(takes_context=True)
def toggle_href(context, node, is_open):
    """The no-JS expand/collapse link for one container row.

    takes_context because open_descendants is a pk-keyed dict, which a
    template cannot index by a variable -- the lookup has to happen here.
    """
    ids = set(context.get("open_ids") or ())
    if is_open:
        # Subtract on the ID SET, never by string replacement: comma-joined
        # pks are prefix-colliding ("1,120,12".replace(",12","") corrupts it).
        # Descendants go too, so a collapse forgets them exactly as the JS
        # path does by removing the subtree.
        drop = {node.pk} | set((context.get("open_descendants") or {}).get(node.pk, ()))
        ids -= drop
        joined = ",".join(str(p) for p in sorted(ids))
    else:
        # Fast path: the precomputed join plus one pk.
        base = context.get("open_joined") or ""
        joined = f"{base},{node.pk}" if base else str(node.pk)
    params = {"open": joined}
    q = context.get("q") or ""
    if q:
        # omitted entirely when blank -- one saved parameter on every
        # container toggle href
        params["q"] = q
    query = urlencode(params)
    return f"{context.get('builder_url', '')}?{query}#node-{node.pk}"


@register.inclusion_tag("courses/manage/editor/_paste_buttons.html", takes_context=True)
def paste_buttons(context, parent="", tab=""):
    """Render the paste controls for ONE slot, if the rule allows them.

    The template never re-derives the rule: it tests this slot's key against the
    two precomputed sets the view built by calling paste_allowed per slot per mode.

    takes_context so it can read `unit` and the sets off the ambient context. Note
    there is no `slug` key in the editor context -- the templates all spell it
    `unit.course.slug`, and so does the form action. NOT for CSRF: Django's
    InclusionNode.render copies csrf_token into the fresh context unconditionally.

    `parent` is "" for the synthetic top-level slot. The None test is explicit for
    the same reason builder.slot_key's is -- `parent or None` would collapse a pk
    of 0 onto the top-level key.
    """
    parent_pk = None if parent == "" or parent is None else parent
    key = builder.slot_key(parent_pk, tab or "")
    return {
        "unit": context.get("unit"),
        "parent": parent if parent_pk is not None else "",
        "tab": tab or "",
        "show_move": key in (context.get("move_slots") or set()),
        "show_copy": key in (context.get("copy_slots") or set()),
    }
