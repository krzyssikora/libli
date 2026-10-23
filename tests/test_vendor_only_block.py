"""{libli:vendor_only} ... {libli:end_vendor_only} -- a span of markdown shown on
the vendor box only, so libli.pl-specific text can live in the shared files
instead of in a per-box PublicPage override that shadows every later edit."""

from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from core.public_pages import BLOCK_TOKENS
from core.public_pages import INLINE_TOKENS
from tests.test_public_pages import render

SOURCE = (
    "Before.\n\n"
    "{libli:vendor_only}\n\n"
    "### Vendor heading\n\n"
    "Vendor text.\n\n"
    "{libli:end_vendor_only}\n\n"
    "After.\n"
)


def test_markers_are_neither_block_nor_inline_tokens():
    # Registered as either, the substitution passes would treat a marker as a
    # value of its own and the span between them would never be seen as a span.
    for name in ("vendor_only", "end_vendor_only"):
        assert name not in BLOCK_TOKENS
        assert name not in INLINE_TOKENS


@override_settings(VENDOR_INSTANCE=False)
def test_the_span_is_dropped_off_vendor():
    assert render(SOURCE) == "<p>Before.</p>\n<p>After.</p>"


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_span_is_kept_and_the_markers_removed_on_the_vendor_box():
    html = render(SOURCE)
    assert "<h3>Vendor heading</h3>" in html
    assert "<p>Vendor text.</p>" in html
    assert "{libli:" not in html
    assert "<p></p>" not in html


@override_settings(VENDOR_INSTANCE=False)
def test_every_span_is_dropped_not_only_the_first():
    html = render(SOURCE + "\n" + SOURCE.replace("Vendor", "Second"))
    assert "Vendor" not in html
    assert "Second" not in html
    assert html.count("After.") == 2


@override_settings(VENDOR_INSTANCE=False)
def test_an_unclosed_span_fails_closed_off_vendor():
    """An admin-typed override can lose its end marker. Rendering the rest as
    ordinary text would leak libli.pl-only content onto a school's box, so the
    unclosed span runs to the end of the page instead."""
    html = render("Before.\n\n{libli:vendor_only}\n\nVendor text.\n")
    assert html == "<p>Before.</p>"


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_stray_marker_never_renders_as_literal_text_on_the_vendor_box():
    html = render("Before.\n\n{libli:vendor_only}\n\nVendor text.\n")
    assert html == "<p>Before.</p>\n<p>Vendor text.</p>"
    assert render("A.\n\n{libli:end_vendor_only}\n\nB.\n") == "<p>A.</p>\n<p>B.</p>"


ROOT = Path(settings.BASE_DIR, "docs", "public")


@pytest.mark.parametrize("path", sorted(ROOT.glob("*.md")), ids=lambda p: p.name)
def test_shipped_markers_are_balanced_and_stand_alone(path):
    """Each marker on its own line (the regex matches a whole <p>), paired, not
    nested, and with no heading directly above an opening marker -- off-vendor
    that heading would be orphaned above nothing."""
    lines = path.read_text(encoding="utf-8").splitlines()
    depth = 0
    for i, line in enumerate(lines):
        if "{libli:vendor_only}" in line or "{libli:end_vendor_only}" in line:
            assert line.strip() in ("{libli:vendor_only}", "{libli:end_vendor_only}")
        if line.strip() == "{libli:vendor_only}":
            assert depth == 0, f"{path.name}:{i + 1}: nested vendor_only"
            above = [x for x in lines[:i] if x.strip()]
            assert not (above and above[-1].lstrip().startswith("#")), (
                f"{path.name}:{i + 1}: heading immediately above vendor_only"
            )
            depth = 1
        elif line.strip() == "{libli:end_vendor_only}":
            assert depth == 1, f"{path.name}:{i + 1}: end without vendor_only"
            depth = 0
    assert depth == 0, f"{path.name}: unclosed vendor_only"
