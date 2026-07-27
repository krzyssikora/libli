"""Where an internal link can live, and how to scan or rewrite one.

One registry, two consumers: the transfer link-rewrite and the delete-time inbound
count. Keeping it in one place is the point -- two overlapping guesses about "which
fields hold rich text" would drift.
"""

import re

from django.db.models import Q

from courses.models import CalloutElement
from courses.models import FillGateElement
from courses.models import GuessNumberElement
from courses.models import QuestionElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import TextElement

# Introspected, and safe ONLY here: every concrete question type inherits the same two
# fields from the same abstract QuestionElement.save(), so a new question type that
# subclasses QuestionElement DIRECTLY is covered automatically. __subclasses__() is
# NOT recursive -- a model subclassing a concrete question type (rather than
# QuestionElement itself) would be silently uncovered here. No such uniformity exists
# among the other element types, which are listed by hand below.
CONCRETE_QUESTION_MODELS = [
    m for m in QuestionElement.__subclasses__() if not m._meta.abstract
]

# 16 models / 27 fields. Each entry traced to an actual sanitize_html call site, not
# read off field names:
#   - body/success_message are sanitised in save()
#   - the three `stem`s are sanitised FORM-side and deliberately not in save(), because
#     sentinel-token stems must go sanitize_html -> strip_sentinel -> parse in order
#   - the question models inherit stem/explanation from QuestionElement.save()
# SwitchGridElement.lines[*].stem is deliberately absent -- see the module docstring in
# the spec: no authoring surface, and sanitize_cell destroys any anchor on import.
RICH_TEXT_FIELDS = [
    (TextElement, "body"),
    (SpoilerElement, "body"),
    (CalloutElement, "body"),
    (FillGateElement, "stem"),
    (GuessNumberElement, "stem"),
    (GuessNumberElement, "success_message"),
    (SwitchGateElement, "stem"),
] + [(m, f) for m in CONCRETE_QUESTION_MODELS for f in ("stem", "explanation")]

_FIELDS_BY_MODEL = {}
for _model, _field in RICH_TEXT_FIELDS:
    _FIELDS_BY_MODEL.setdefault(_model, []).append(_field)

# Anchored, matching part 1's dialog exactly. A prefix match would make the delete
# count and the rewrite disagree with the dialog about what an internal link is.
#
# Digit run capped at 12, mirroring transfer/schema.py's link_nodes key cap: CPython's
# int() raises ValueError past its 4300-digit conversion limit, and a stored body
# reaches this regex UNVALIDATED (sanitize_html allows a relative <a href>, so an
# author can store an arbitrarily long digit run through the editor's HTML source
# view). 10**12 exceeds any plausible pk, so real links are unaffected; a >12-digit
# href simply stops being treated as an internal link.
PERMALINK_PREFIX = "/courses/n/"
_PERMALINK = re.compile(r"^/courses/n/(\d{1,12})/$")


class _Unscannable(Exception):
    """The body met a fail-closed condition; return it byte-identical."""


_TAG_OPEN = re.compile(r"<a(?=[\s>])", re.I)
# (?<![\w-]) is the attribute-NAME boundary: without it, "href" matches as a
# substring of any longer attribute name ending in it (e.g. data-href="..."),
# so a hand-crafted attribute can spoof or displace the real href depending on
# scan order. Word/hyphen chars are exactly the characters an HTML attribute
# name is made of, so this is a name boundary, not a value boundary.
_HREF_ATTR = re.compile(r"(?<![\w-])href\s*=\s*", re.I)
_CLOSE_TAG = re.compile(r"</a\s*>", re.I)


def _scan_anchors(html):
    """Yield (tag_start, tag_end, href_span) for every <a> open tag.

    Attribute-aware on purpose. MEASURED: nh3 does NOT escape `>` inside attribute
    values, and `title` is an allowed <a> attribute, so `<a title="a > b" href=...>`
    is ordinary sanitised content. A naive `<a[^>]*>` matches `<a title="a >` -- a
    syntactically CLEAN match of the wrong span, which silently misses the href
    instead of failing. So consume quoted values until an UNQUOTED '>'.

    An unquoted href value (`<a href=/courses/n/12/>`) is also a fail-closed
    condition, not a silent miss: nh3's own output always quotes attribute
    values, so an unquoted href is reachable only via a hand-crafted archive
    that bypassed sanitize_html (see the FillGate/SwitchGate stem note on
    RICH_TEXT_FIELDS above) -- exactly the adversarial-input case this scanner
    exists to fail safely on, not to parse.
    """
    i = 0
    n = len(html)
    while True:
        m = _TAG_OPEN.search(html, i)
        if not m:
            return
        j = m.end()
        href = None
        while j < n:
            c = html[j]
            if c == ">":
                break
            if c in "\"'":
                quote = c
                k = html.find(quote, j + 1)
                if k == -1:
                    raise _Unscannable("unterminated quoted attribute value")
                j = k + 1
                continue
            am = _HREF_ATTR.match(html, j)
            if am:
                vs = am.end()
                if vs >= n or html[vs] not in "\"'":
                    raise _Unscannable("unquoted href attribute value")
                quote = html[vs]
                k = html.find(quote, vs + 1)
                if k == -1:
                    raise _Unscannable("unterminated quoted attribute value")
                if href is not None:
                    # A second href on one tag is reachable only via a hand-crafted
                    # archive (nh3 de-duplicates on the way in). Browsers keep the
                    # FIRST href; silently overwriting with the second would rewrite
                    # (or count) a target the browser never navigates to -- fail
                    # closed instead of guessing.
                    raise _Unscannable("duplicate href")
                href = (html[vs + 1 : k], vs, k + 1)
                j = k + 1
                continue
            j += 1
        else:
            raise _Unscannable("<a with no unquoted '>'")
        yield m.start(), j + 1, href
        i = j + 1


def find_link_targets(html):
    """Node pks referenced by an internal-link href. Never matches visible text."""
    if not html:
        return set()
    out = set()
    try:
        for _s, _e, href in _scan_anchors(html):
            if not href:
                continue
            mm = _PERMALINK.match(href[0])
            if mm:
                out.add(int(mm.group(1)))
    except _Unscannable:
        return set()
    return out


def rewrite_links(html, mapping, *, on_missing):
    """Remap internal-link hrefs. Returns (html, flattened_count).

    Only <a> href ATTRIBUTES are touched -- never text content. A bs4 round trip would
    re-escape entities (see the repo's recorded str(Tag) trap) and stored bodies carry
    \\(...\\) math whose escaping sanitize.py::_canon_math is precise about; a naive
    whole-document regex would rewrite a literal /courses/n/12/ that an author typed
    in prose. On any fail-closed condition the WHOLE body comes back byte-identical
    and contributes 0 -- never mangled markup.
    """
    if on_missing not in ("keep", "unwrap"):
        # Part 3 adds a third value ("defer"). A silent fall-through to keep-behaviour
        # on a typo is the wrong default when the vocabulary is about to grow.
        raise ValueError(f"unknown on_missing: {on_missing!r}")
    if not html:
        return html, 0
    try:
        anchors = list(_scan_anchors(html))
    except _Unscannable:
        return html, 0

    edits = []  # (start, end, replacement) on the ORIGINAL string
    flattened = 0
    for start, end, href in anchors:
        if not href:
            continue
        mm = _PERMALINK.match(href[0])
        if not mm:
            continue
        pk = int(mm.group(1))
        if pk in mapping:
            new = f"{PERMALINK_PREFIX}{mapping[pk]}/"
            edits.append((href[1], href[2], f'"{new}"'))
        elif on_missing == "unwrap":
            close = _CLOSE_TAG.search(html, end)
            if close is None:
                return html, 0  # fail closed: no matching </a>
            edits.append((start, end, ""))
            edits.append((close.start(), close.end(), ""))
            flattened += 1

    if not edits:
        return html, 0
    out = []
    cursor = 0
    for start, end, repl in sorted(edits):
        out.append(html[cursor:start])
        out.append(repl)
        cursor = end
    out.append(html[cursor:])
    return "".join(out), flattened


def iter_rich_text(instance):
    """Yield (field_name, value) for every registry field on one element instance."""
    for field in _FIELDS_BY_MODEL.get(type(instance), []):
        yield field, getattr(instance, field, "") or ""


def rewrite_instance(instance, mapping, *, on_missing):
    """Rewrite every registry field on one instance.

    Returns (changed field names, flattened count). The caller saves with
    update_fields=changed, so no caller has to know the registry's shape.
    """
    changed = []
    flattened = 0
    for field, value in iter_rich_text(instance):
        new, flat = rewrite_links(value, mapping, on_missing=on_missing)
        flattened += flat
        if new != value:
            setattr(instance, field, new)
            changed.append(field)
    return changed, flattened


def count_inbound_links(course, node):
    """Distinct Element join rows ELSEWHERE in `course` linking into `node`'s subtree.

    Elements, not anchors: two anchors in one body pointing at two doomed nodes count
    once, because the author's unit of repair is "this element needs editing". And
    outside the subtree, because a link INSIDE the doomed subtree dies with its target
    -- counting those would report a large number for a self-contained part whose
    lessons cross-link each other, the opposite of the warning's purpose.

    Query shape matters. Matching each subtree pk as its own LIKE would build one OR
    term per (pk x field) -- hundreds across 16 models for a big part. Instead: one
    course-scoped query per model on the CONSTANT substring, then intersect in Python
    on the few rows that hold any internal link at all.

    The `.exclude(elements__unit_id__in=subtree)` above is correct only because a
    content row has exactly one owning Element: if a row were reachable from more
    than one Element join, one join inside the subtree would exclude the whole row
    even when another join OUTSIDE the subtree also links to `node` -- silently
    undercounting.
    """
    subtree = set(node._subtree_node_ids())
    total = 0
    for model, fields in _FIELDS_BY_MODEL.items():
        predicate = Q()
        for field in fields:
            predicate |= Q(**{f"{field}__contains": PERMALINK_PREFIX})
        rows = (
            model.objects.filter(predicate)
            .filter(elements__unit__course=course)
            .exclude(elements__unit_id__in=subtree)
            .only(*fields)  # question models carry large blobs we never read
            .distinct()
        )
        for row in rows:
            targets = set()
            for _field, value in iter_rich_text(row):
                targets |= find_link_targets(value)
            if targets & subtree:
                total += 1
    return total
