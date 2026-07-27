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


def test_internal_and_external_markers_exist():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert '.el a[href^="/courses/n/"]' in css
    assert '.el a[href^="http"]' in css


def test_css_prefix_matches_the_route():
    # The selector duplicates the route's literal path, which the route NAME does not
    # protect: changing path("courses/n/<int:node_pk>/", ...) keeps every reverse-based
    # test green while silently stripping the marker off every internal link.
    prefix = "/courses/n/"
    assert reverse("courses:node_permalink", kwargs={"node_pk": 1}).startswith(prefix)
    assert '.el a[href^="' + prefix + '"]' in COURSES_CSS.read_text(encoding="utf-8")
