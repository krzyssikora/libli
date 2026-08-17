"""Tests for the `media_img` template tag.

NARROWED SCOPE (PR 1 of 2): this branch ships `courses_media_extras.py` with
exactly one preset, `grid` (see the module docstring). The full brief covers
eleven presets across FIXED/FLUID/ORIGINAL strategies; PR 2 adds the rest
together with their measured `sizes` values. Tests below are narrowed to what
is actually reachable in this PR -- see the bottom of this file for a list of
what was dropped and why.
"""

import pytest
from django.template import Context
from django.template import Template

from courses import derivatives
from courses.templatetags import courses_media_extras
from tests.factories import CourseFactory
from tests.factories import make_image_asset
from tests.factories import make_video_asset


def render(**ctx):
    tpl = Template(
        "{% load courses_media_extras %}"
        "{% media_img asset preset=preset alt=alt css_class=css_class extra=extra %}"
    )
    ctx.setdefault("alt", "")
    ctx.setdefault("css_class", "")
    ctx.setdefault("extra", "")
    return tpl.render(Context(ctx))


@pytest.mark.django_db
def test_grid_uses_the_thumb_as_src_and_emits_no_srcset(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="grid")
    assert asset.thumb.url in html
    assert asset.file.url not in html
    assert "srcset" not in html


@pytest.mark.django_db
def test_blank_thumb_falls_back_to_the_original(course_with_image_media_root):
    """MUTANT: make the FIXED branch fall back to the (blank) thumb name
    instead of the original when no derivative exists. Blank must always be
    safe -- a pending/skipped/failed derivatives_state must never produce a
    broken src."""
    course = CourseFactory()
    asset = make_image_asset(course, "b.png", size=(2000, 1500))  # no derivatives=True
    assert asset.thumb.name == ""
    html = render(asset=asset, preset="grid")
    assert f'src="{asset.file.url}"' in html
    assert "srcset" not in html


@pytest.mark.django_db
def test_no_preset_emits_width_or_height(course_with_image_media_root):
    """Measured: with a binding max-height, a definite width makes the axes
    clamp independently and portrait images distort 100-260px; on the grid,
    attributes make the cell 130x841 instead of 130x98."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="grid")
    assert "width=" not in html and "height=" not in html


@pytest.mark.django_db
def test_degenerate_inputs_render_nothing(course_with_image_media_root):
    course = CourseFactory()
    assert render(asset=None, preset="grid").strip() == ""
    blank = make_image_asset(course, "b.png", size=(2000, 1500))
    blank.file.name = ""
    assert render(asset=blank, preset="grid").strip() == ""
    video = make_video_asset(course, "v.mp4")
    assert render(asset=video, preset="grid").strip() == ""


@pytest.mark.django_db
def test_unknown_preset_raises(course_with_image_media_root):
    """MUTANT: make an unknown preset return empty markup instead of raising.
    An unknown preset name is an authoring bug and must be a hard error, never
    silently-bad (or silently-missing) markup."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    with pytest.raises(ValueError):
        render(asset=asset, preset="nope")


@pytest.mark.django_db
def test_fluid_preset_with_no_sizes_raises(course_with_image_media_root, monkeypatch):
    """MUTANT: drop the `strategy == FLUID and sizes is None` guard. flatatt
    silently drops a None-valued attribute (Django, verified), so a FLUID
    preset that forgets `sizes` -- e.g. copy-pasted from `"grid": (FIXED,
    None)`, or a placeholder never filled in -- would otherwise render
    `srcset` with no `sizes`: a silent no-op, not a crash, and exactly the
    failure mode `sizes` exists to prevent. No FLUID preset ships in this PR
    (PRESETS has only `grid`), so a throwaway one is monkeypatched in to
    reach the branch; PR 2's real FLUID presets will exercise it for real."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    monkeypatch.setitem(
        courses_media_extras.PRESETS,
        "test-fluid-no-sizes",
        (courses_media_extras.FLUID, None),
    )
    with pytest.raises(ValueError):
        render(asset=asset, preset="test-fluid-no-sizes")


@pytest.mark.django_db
def test_loading_lazy_is_grid_only(course_with_image_media_root):
    """`grid` renders ~950 cells on the manager page, so it alone gets
    loading="lazy". (The brief's negative loop over el-full/cell-small/
    gallery/dragimage is dropped in this PR -- none of those presets exist
    yet; the assertion those presets never get lazy loading belongs with PR
    2, which introduces them.)"""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    assert 'loading="lazy"' in render(asset=asset, preset="grid")


@pytest.mark.django_db
def test_data_zoom_src_only_where_data_zoomable(course_with_image_media_root):
    """data-zoom-src is consumed only by imagezoom.js, armed off
    [data-zoomable]. Emitting a full media URL into each of ~950 grid cells
    would inflate the HTML payload this change makes a required
    before/after measurement, so the tag must only add it when explicitly
    asked."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    assert "data-zoom-src" not in render(asset=asset, preset="grid")
    html = render(asset=asset, preset="grid", extra="data-zoomable")
    assert f'data-zoom-src="{asset.file.url}"' in html


@pytest.mark.django_db
def test_extra_rejects_anything_outside_the_allow_list(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    with pytest.raises(ValueError):
        render(asset=asset, preset="grid", extra="onclick")
    with pytest.raises(ValueError):
        render(asset=asset, preset="grid", extra='data-x="1"')


@pytest.mark.django_db
def test_alt_round_trips_and_is_escaped(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="grid", alt='A "quoted" <diagram>')
    assert "&quot;quoted&quot;" in html or "&#x27;" in html or "&lt;diagram&gt;" in html
    assert 'alt=""' in render(asset=asset, preset="grid")


def test_thumb_and_web_widths_are_imported_not_hardcoded(monkeypatch):
    """MUTANT: re-type THUMB_WIDTH/WEB_WIDTH as literal 512/896 in the tag
    module instead of importing them from courses.derivatives. Today the
    values happen to be equal (512/896 either way), so a same-process equality
    check can't tell "imported" from "hardcoded to the current value" -- and
    the reachable strategy in this PR (FIXED) never even consults these
    constants in rendered output. Force a real behavioural difference
    instead: change courses.derivatives' constants, then reload the tag
    module. An import re-binds to the new value on reload; a re-typed literal
    does not move."""
    import importlib

    monkeypatch.setattr(derivatives, "THUMB_WIDTH", 4096)
    monkeypatch.setattr(derivatives, "WEB_WIDTH", 8192)
    try:
        reloaded = importlib.reload(courses_media_extras)
        assert reloaded.THUMB_WIDTH == 4096
        assert reloaded.WEB_WIDTH == 8192
    finally:
        importlib.reload(courses_media_extras)


# --- Dropped or narrowed relative to the brief, and why -------------------
#
# - test_an_80px_cell_loads_the_thumb_not_the_original: exercised
#   preset="cell-small", which does not exist in this PR. Its assertion (a
#   fixed-strategy preset loads the thumb, not the original) is already
#   covered by test_grid_uses_the_thumb_as_src_and_emits_no_srcset, the only
#   FIXED preset shipped here.
# - test_fluid_presets_emit_srcset_sizes_and_an_original_src: exercised
#   preset="el-full" (FLUID), not in PRESETS in this PR. Dropped entirely --
#   the FLUID branch is unreachable code until PR 2 adds a FLUID preset.
# - test_sizes_is_present_on_every_w_descriptor_preset: looped over
#   el-*/cell-large/gallery/dragimage, none of which exist here. Dropped;
#   revives in PR 2 once those presets land.
# - test_cell_full_emits_the_original_and_no_srcset: exercised
#   preset="cell-full" (ORIGINAL), not in PRESETS in this PR. Dropped.
# - test_omission_rule_fires_when_the_asset_is_narrower_than_the_declared_sizes
#   and test_omission_rule_fires_when_no_derivative_exists: both exercise the
#   FLUID branch's omission logic (el-full / cell-large), unreachable with
#   only `grid` in PRESETS. Dropped; the omission rule itself is untouched
#   code, just untestable from outside until a FLUID preset exists.
# - test_null_dimensions_suppress_srcset: exercised preset="el-full" (FLUID).
#   Dropped for the same reason.
# - test_every_stored_size_value_maps_to_a_preset_key: asserted every
#   `el-{Size}` / `cell-{CellImageSize}` key exists in PRESETS. Explicitly
#   told to drop -- PRESETS intentionally has only `grid` in this PR.
# - test_no_preset_emits_width_or_height: narrowed from a loop over all
#   eleven presets to just `grid`, the only preset that exists.
# - test_loading_lazy_is_grid_only: narrowed to the positive case only (grid
#   gets loading="lazy"); the negative loop over el-full/cell-small/gallery/
#   dragimage is dropped since none of those presets exist to assert against.
# - test_data_zoom_src_only_where_data_zoomable and
#   test_extra_rejects_anything_outside_the_allow_list and
#   test_alt_round_trips_and_is_escaped: kept, with every preset="el-full"
#   argument changed to preset="grid" (the only valid preset in this PR).
