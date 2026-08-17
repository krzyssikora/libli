"""The single <img> emitter for MediaAsset images.

A simple_tag returning format_html, NOT an inclusion_tag: an inclusion_tag
performs a full template load-and-render per invocation, i.e. ~950 nested
renders on the manager grid where there are currently zero.

PARTIAL PRESET TABLE, ON PURPOSE. This is PR 1 of a two-PR split: PR 1 covers
only the media library grid and the picker (the `grid` preset). PR 2 adds the
fluid element/table/gallery/dragimage presets together with their measured
`sizes` strings, taken from
docs/superpowers/plans/2026-08-17-media-image-derivatives-measurements.md.
`FLUID` and `ORIGINAL` are kept as named strategies now, unused until PR 2
lands them, so that PR 2 is additive to this module rather than a rewrite.
`_DECLARED_MAX` is likewise kept as a named, documented empty dict rather than
removed.
"""

from django import template
from django.forms.utils import flatatt
from django.utils.html import format_html

from courses.derivatives import THUMB_WIDTH
from courses.derivatives import WEB_WIDTH

register = template.Library()

# Only boolean attribute NAMES. format_html escapes interpolated arguments, so
# a valued attribute would be escaped into visible text, and marking the
# argument safe would make this tag an HTML injection sink.
_ALLOWED_EXTRA = frozenset({"data-asset-preview", "data-zoomable"})

FIXED = "fixed"  # src = thumb, no srcset
FLUID = "fluid"  # src = original + w-descriptor srcset + sizes
ORIGINAL = "original"  # src = original, nothing else

# PR 1 ships exactly the `grid` preset (media library + picker). The fluid
# presets (cell-*, el-*, gallery, dragimage) arrive in PR 2 with their
# measured `sizes` strings -- do not invent values here.
PRESETS = {
    "grid": (FIXED, None),
}

# The largest width each fluid preset's `sizes` can resolve to at the
# measurement viewports -- the omission threshold used by the FLUID branch
# below. Empty in PR 1: no preset here is FLUID yet. PR 2 fills this from the
# measurements document alongside its new preset entries.
_DECLARED_MAX = {}


@register.simple_tag
def media_img(asset, preset, alt="", css_class="", extra=""):
    if preset not in PRESETS:
        raise ValueError(f"unknown media_img preset: {preset!r}")
    strategy, sizes = PRESETS[preset]

    if asset is None or not asset.file.name or asset.kind != "image":
        return ""

    names = [n for n in extra.split() if n]
    bad = [n for n in names if n not in _ALLOWED_EXTRA]
    if bad:
        raise ValueError(f"media_img extra must be boolean attribute names: {bad}")

    thumb = asset.thumb.url if asset.thumb.name else None
    web = asset.web.url if asset.web.name else None
    original = asset.file.url

    if strategy == FIXED:
        src = thumb or original
        srcset_value = ""
    elif strategy == ORIGINAL:
        src = original
        srcset_value = ""
    else:
        src = original
        candidates = []
        if thumb:
            candidates.append(f"{thumb} {THUMB_WIDTH}w")
        if web:
            candidates.append(f"{web} {WEB_WIDTH}w")
        # A w descriptor without a real pixel width is a lie the browser acts on.
        emit = bool(candidates) and asset.width is not None and asset.height is not None
        # The omission rule: the SOLE layout protection. Independent of the
        # no-derivative check above -- a preset's declared width can sit below
        # THUMB_WIDTH, so neither subsumes the other.
        declared = _DECLARED_MAX.get(preset)
        if declared is not None and asset.width is not None and asset.width <= declared:
            emit = False
        if emit:
            candidates.append(f"{original} {asset.width}w")
            srcset_value = ", ".join(candidates)
        else:
            srcset_value = ""

    attrs = {"class": css_class, "alt": alt, "src": src}
    if srcset_value:
        attrs["srcset"] = srcset_value
        attrs["sizes"] = sizes
    if preset == "grid":
        attrs["loading"] = "lazy"
    if "data-zoomable" in names:
        attrs["data-zoom-src"] = original
    for name in names:
        attrs[name] = True  # flatatt renders True as a bare attribute

    # flatatt, NOT a nested format_html over pre-formatted `name="value"`
    # strings: format_html conditional_escapes every argument, so those strings
    # come out as src=&quot;/media/…&quot; and NO image gets a usable src. flatatt
    # escapes the VALUES and leaves the attribute structure intact, which is the
    # contract needed here.
    return format_html("<img{}>", flatatt(attrs))
