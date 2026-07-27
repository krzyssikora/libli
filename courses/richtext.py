"""Where an internal link can live, and how to scan or rewrite one.

One registry, two consumers: the transfer link-rewrite and the delete-time inbound
count. Keeping it in one place is the point -- two overlapping guesses about "which
fields hold rich text" would drift.
"""

import re

from courses.models import CalloutElement
from courses.models import FillGateElement
from courses.models import GuessNumberElement
from courses.models import QuestionElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import TextElement

# Introspected, and safe ONLY here: every concrete question type inherits the same two
# fields from the same abstract QuestionElement.save(), so a new question type is
# covered automatically. No such uniformity exists among the other element types, which
# are listed by hand below.
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
PERMALINK_PREFIX = "/courses/n/"
_PERMALINK = re.compile(r"^/courses/n/(\d+)/$")


class _Unscannable(Exception):
    """The body met a fail-closed condition; return it byte-identical."""


def _scan_anchors(html):
    """Yield (tag_start, tag_end, href_span) for every <a> open tag.

    Attribute-aware on purpose. MEASURED: nh3 does NOT escape `>` inside attribute
    values, and `title` is an allowed <a> attribute, so `<a title="a > b" href=...>`
    is ordinary sanitised content. A naive `<a[^>]*>` matches `<a title="a >` -- a
    syntactically CLEAN match of the wrong span, which silently misses the href
    instead of failing. So consume quoted values until an UNQUOTED '>'.
    """
    i = 0
    n = len(html)
    while True:
        m = re.compile(r"<a(?=[\s>])", re.I).search(html, i)
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
            am = re.compile(r"href\s*=\s*(\"([^\"]*)\"|'([^']*)')", re.I).match(html, j)
            if am:
                href = (
                    am.group(2) if am.group(2) is not None else am.group(3),
                    am.start(1),
                    am.end(1),
                )
                j = am.end()
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
            close = re.compile(r"</a\s*>", re.I).search(html, end)
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
