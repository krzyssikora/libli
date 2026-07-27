from pathlib import Path

from django.urls import reverse

COURSES_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "courses.css"
)


# Each literal below is anchored to a rule OPENING (leading "\n", trailing "{\n"), not
# just a selector fragment. A bare '.el a[href^="/courses/n/"]' is a substring of BOTH
# the base rule and its "::before" compound selector -- the same vacuous-match trap the
# plan calls out elsewhere ('.outline-node {' also matching
# '.outline-tree > ul > .outline-node {'). The space before "{" in INTERNAL_BASE_RULE is
# what excludes the "::before" variant, which has no space there.
INTERNAL_BASE_RULE = '\n.el a[href^="/courses/n/"] {\n'
INTERNAL_GLYPH_RULE = '\n.el a[href^="/courses/n/"]::before {\n'
EXTERNAL_GLYPH_RULE = '\n.el a[href^="http"]::after {\n'


def test_internal_link_base_rule_exists():
    # The colour/underline affordance. Deleting only this rule (leaving the ::before
    # glyph rule intact) must fail this test -- see falsification in the task report.
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert INTERNAL_BASE_RULE in css


def test_internal_link_glyph_rule_exists():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert INTERNAL_GLYPH_RULE in css


def test_external_link_glyph_rule_exists():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert EXTERNAL_GLYPH_RULE in css


def test_css_prefix_matches_the_route():
    # The selector duplicates the route's literal path, which the route NAME does not
    # protect: changing path("courses/n/<int:node_pk>/", ...) keeps every reverse-based
    # test green while silently stripping the marker off every internal link.
    prefix = "/courses/n/"
    assert reverse("courses:node_permalink", kwargs={"node_pk": 1}).startswith(prefix)
    assert INTERNAL_BASE_RULE in COURSES_CSS.read_text(encoding="utf-8")
