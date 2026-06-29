from pathlib import Path


def test_tags_css_has_palette_tokens():
    css = Path("tags/static/tags/css/tags.css").read_text(encoding="utf-8")
    for key in ("teal", "amber", "indigo", "rose", "green", "violet", "slate", "cyan"):
        assert f"tag-chip--{key}" in css


def test_tags_js_filters_and_recomputes():
    js = Path("tags/static/tags/js/tags.js").read_text(encoding="utf-8")
    assert "data-tags-filter" in js
    assert "pushState" in js
    assert "hidden" in js


def test_tags_js_wires_panel_fragments():
    js = Path("tags/static/tags/js/tags.js").read_text(encoding="utf-8")
    assert "X-Requested-With" in js  # panel add/remove fragment submission
    assert "unit-tags" in js


def test_tags_js_has_inline_delete_confirm_and_guards_i18n():
    js = Path("tags/static/tags/js/tags.js").read_text(encoding="utf-8")
    assert "tag-delete-confirm" in js  # inline My-tags delete confirm
    assert 'getElementById("tags-i18n")' in js  # null-guarded read (outline omits it)
