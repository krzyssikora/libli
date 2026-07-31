"""Refuse to colour any source fragment whose colour would land in a protected region.

Detection is an explicit text-offset pass, not a lookup: the interval test needs
global offsets into the fragment's text, and it also needs to know where the ELEMENT
boundaries fall, because a region containing one already round-trips lossily through
sanitize_cell. Both come out of one walk over the parsed tree.
"""

import re

from bs4 import NavigableString

from courses.colour import slot_for_style
from courses.fillblank import SENTINEL

# Balanced \(...\) (inline) or \[...\] (display), non-greedy, no nesting. IMPORTED
# from the sanitiser, never re-declared: the guard and the sanitiser must agree about
# what a region IS, and a copied pattern agrees only by comment -- if the sanitiser's
# pattern ever moves, a duplicate here silently disagrees about region boundaries and
# the D8 refusal starts protecting the wrong span. This repo guards that class of
# drift with tests elsewhere (test_colour_map_drift, the #169 twin guard); importing
# removes the possibility instead of testing for it.
from courses.sanitize import _MATH_SPAN

# Anything delimiter-shaped that survived the region scan means an unclosed or
# unbalanced delimiter: fail closed rather than guess where the region ends.
_LOOSE_DELIM = re.compile(r"\\[()\[\]]")
# The source-side blank marker. NOT `{{...}}`: measured over all 835 corpus files,
# `{{` occurs ZERO times, because the loader feeds sanitize_stem_segments, which
# splits on this token, not on author braces. SENTINEL is imported rather than
# written as an escape -- it is U+FFFF, and the visually similar U+FFFD (the
# replacement character) would make every test here vacuous.
_SENTINEL_TOKEN = re.compile(SENTINEL + r"\d+" + SENTINEL)


def _walk(parsed):
    """(full text, [(start, end) per text node], [(start, end) per coloured tag]).

    A coloured tag's extent is the offset range of the text it contains. An empty
    element has no extent and cannot intersect anything, so it is skipped.
    """
    text_parts = []
    node_spans = []
    tag_spans = []
    cursor = 0

    def visit(node):
        nonlocal cursor
        if isinstance(node, NavigableString):
            s = str(node)
            text_parts.append(s)
            node_spans.append((cursor, cursor + len(s)))
            cursor += len(s)
            return
        if node.name is None:
            return
        start = cursor
        for child in node.children:
            visit(child)
        if slot_for_style(node.get("style")) and cursor > start:
            tag_spans.append((start, cursor))

    for child in parsed.children:
        visit(child)
    return "".join(text_parts), node_spans, tag_spans


def _in_one_text_node(span, node_spans):
    lo, hi = span
    return any(ns <= lo and hi <= ne for ns, ne in node_spans)


def region_verdict(html, *, sentinel_tokens):
    """A short refusal reason, or None when colouring this fragment is safe.

    `sentinel_tokens` is True only for the sanitize_stem_segments field shapes,
    whose segments are sanitised independently.
    """
    from courses.recolour.colouriser import soup

    parsed = soup(html)
    text, node_spans, tag_spans = _walk(parsed)
    if not tag_spans:
        return None

    regions = [(m.start(), m.end(), "maths") for m in _MATH_SPAN.finditer(text)]
    residue = _MATH_SPAN.sub("", text)
    if _LOOSE_DELIM.search(residue):
        return "unbalanced maths delimiter"
    if sentinel_tokens:
        regions += [
            (m.start(), m.end(), "blank") for m in _SENTINEL_TOKEN.finditer(text)
        ]

    for ts, te in tag_spans:
        for rs, re_, kind in regions:
            if te <= rs or re_ <= ts:
                continue  # disjoint -- the only safe relation for a blank token
            if kind == "blank":
                # NO enclosure carve-out here, and that asymmetry is load-bearing.
                # The maths carve-out works because a span enclosing \(...\) wraps
                # the delimiters and sanitize_cell stashes the region intact. A
                # blank token is the opposite: sanitize_stem_segments SPLITS the
                # stem on the token and sanitises each segment INDEPENDENTLY, so an
                # enclosing span is auto-closed by nh3 in the leading segment and
                # the trailing segment silently loses its colour. MEASURED against
                # the real sanitiser while this plan was written.
                return "colour touches a blank-marker token"
            if ts <= rs and re_ <= te:
                # Strictly enclosing a maths region: allowed only when the region
                # carries no element boundary, i.e. it lies inside a single text
                # node. A region that does already round-trips lossily through
                # sanitize_cell regardless of colour.
                if _in_one_text_node((rs, re_), node_spans):
                    continue
                return "colour encloses a maths region containing an element boundary"
            return "colour intersects a maths region"
    return None
