import re
from pathlib import Path

import pytest

from courses.element_forms import ImageElementForm
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

# Anchor for the CSS token test in Step 6. Same pattern Task 5 uses.
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def image_media():
    """A course-scoped image MediaAsset. Defined here, not in a conftest — see
    Global Constraints: courses/tests/ has none and this slice does not add one."""
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def test_form_accepts_the_size_field():
    assert "size" in ImageElementForm.Meta.fields


def test_form_saves_a_chosen_size(image_media):
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "a", "figcaption": "", "size": "medium"},
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert form.save().size == "medium"


def test_a_post_that_omits_size_is_rejected(image_media):
    """THE TRAP, stated as a fact rather than assumed: `size` is a required
    ChoiceField, so a POST without the key is INVALID — which is exactly why the
    template's `checked` attribute is load-bearing rather than cosmetic. The
    companion pin is test_editor_always_checks_exactly_one_radio below: together
    they say "a save without `size` fails" AND "the rendered form can never
    produce such a save"."""
    el = ImageElement.objects.create(media=image_media, alt="before", size="large")
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "after", "figcaption": ""},
        instance=el,
        course=image_media.course,
    )
    assert not form.is_valid()
    assert "size" in form.errors


def test_an_alt_only_edit_still_saves(image_media):
    """Spec row 16: with the rendered form's `size` present (as `checked` guarantees),
    an edit that changes only `alt` succeeds."""
    el = ImageElement.objects.create(media=image_media, alt="before", size="large")
    form = ImageElementForm(
        data={
            "media": image_media.pk,
            "alt": "after",
            "figcaption": "",
            "size": "large",
        },
        instance=el,
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.alt == "after"
    assert saved.size == "large"  # the untouched preset survives the edit


def _render_editor(instance=None):
    """The house partial-render pattern (tests/test_table_editor_partial.py:17-22)."""
    from django.template.loader import render_to_string

    form = ImageElementForm(instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_image.html", {"form": form, "type_key": "image"}
    )


def _radio_tag(html, value):
    """The single <input> tag whose value="<value>", so `checked` can be attributed to
    THAT radio rather than to `checked` appearing anywhere in the document."""
    m = re.search(r"<input[^>]*value=\"" + value + r"\"[^>]*>", html)
    assert m, f"no radio rendered for {value}"
    return m.group(0)


def test_editor_renders_four_radios_with_the_contract_attributes(image_media):
    # `image_el` is the ImageElement (what the form and both data-* hooks key on).
    # Its Element join row is a DIFFERENT object and is deliberately not needed here:
    # `unit`/`content_object` live on Element, `media`/`alt`/`size` on ImageElement.
    image_el = ImageElement.objects.create(media=image_media, alt="a", size="large")
    html = _render_editor(image_el)
    for value in ("small", "medium", "large", "full"):
        assert f'value="{value}"' in html
    assert "data-size-preset" in html
    assert f'data-for-element="{image_el.pk}"' in html
    assert "<legend>" in html


def test_editor_checks_the_stored_preset_and_only_that_one(image_media):
    """Spec row 15, first half."""
    image_el = ImageElement.objects.create(media=image_media, alt="a", size="large")
    html = _render_editor(image_el)
    assert " checked" in _radio_tag(html, "large")
    for other in ("small", "medium", "full"):
        assert " checked" not in _radio_tag(html, other)


def test_a_fresh_element_checks_full(image_media):
    """Spec row 15, second half — an UNBOUND form (the create flow) must still
    submit a `size`, so the default has to arrive pre-checked."""
    html = _render_editor()
    assert " checked" in _radio_tag(html, "full")
    for other in ("small", "medium", "large"):
        assert " checked" not in _radio_tag(html, other)


def test_the_create_flow_renders_an_empty_for_element(image_media):
    """Pins the default_if_none filter: an unsaved instance has pk None, which Django
    would otherwise render as the literal string "None"."""
    assert 'data-for-element=""' in _render_editor()


def test_size_preset_css_uses_only_declared_tokens():
    """An UNDEFINED custom property invalidates the whole declaration at
    computed-value time, so `var(--border)` would ship a borderless fieldset with
    nothing red anywhere."""
    app_css = (REPO / "core" / "static" / "core" / "css" / "app.css").read_text(
        encoding="utf-8"
    )
    tokens = (REPO / "core" / "static" / "core" / "css" / "tokens.css").read_text(
        encoding="utf-8"
    )
    # Brace-count from the first `.size-presets` to the last of its consecutive rules
    # (the Task 6 approach). Do NOT terminate on "the next line starting with a dot":
    # at the mandated insertion point the next such line is `.switchgrid` and the scan
    # would swallow the comment between them — and at EOF, or before an @media/#id
    # rule, it would match nothing and fail with a misleading "not found".
    start = app_css.find(".size-presets")
    assert start != -1, ".size-presets rules not found in app.css"
    end, depth, i = start, 0, start
    while i < len(app_css):
        if app_css[i] == "{":
            depth += 1
        elif app_css[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                nxt = app_css.find(".size-presets", end)
                if nxt == -1 or app_css[end:nxt].strip():
                    break  # next .size-presets rule is not adjacent — stop here
                i = nxt
                continue
        i += 1
    block = app_css[start:end]
    used = set(re.findall(r"var\((--[\w-]+)\)", block))
    assert used, "the block declares no tokens — did it hardcode a colour?"
    declared = set(re.findall(r"(--[\w-]+)\s*:", tokens))
    assert used <= declared, f"undeclared tokens: {sorted(used - declared)}"
