"""The caption is edited on the shared RTE surface, not a plain text input.

No JavaScript changes are needed for this: `initRte` in text_toolbar.js enhances
ANY `[data-rte-source]` textarea, and `wireRte` finds its toolbar through
`textarea.closest(".el-editor--text")` -- which is exactly why the caption block
is wrapped in that class, the same way every question stem is
(_edit_choicequestion.html:6-9).
"""

import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import ImageElementForm
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.sanitize import CAPTION_MAX_LENGTH
from courses.sanitize import CAPTION_TAGS
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

REPO = Path(__file__).resolve().parents[2]
TOOLBAR = REPO / "templates/courses/manage/editor/_rte_toolbar_caption.html"


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def _render_editor(instance=None):
    form = ImageElementForm(instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_image.html", {"form": form, "type_key": "image"}
    )


def _caption_block(html):
    """The `.el-editor--text` wrapper the caption lives in, from its opening tag
    to the caption textarea's close.

    Scoped rather than asserting against the whole partial, so a `data-cmd`
    somewhere else in the image editor could never satisfy these checks. The
    single-wrapper assertion is what keeps the slice honest: with two wrappers,
    the slice could span from one to the other's textarea and the scoping would
    be a fiction."""
    assert html.count('class="el-editor--text"') == 1, "expected one RTE wrapper"
    start = html.index('<div class="el-editor--text">')
    end = html.index("</textarea>", start) + len("</textarea>")
    block = html[start:end]
    assert 'name="figcaption"' in block, "the wrapper does not hold the caption"
    return block


def test_the_caption_is_a_textarea_the_rte_enhances(image_media):
    html = _render_editor()
    m = re.search(r'<textarea[^>]*name="figcaption"[^>]*>', html)
    assert m, "caption is not a textarea"
    assert "data-rte-source" in m.group(0)


def test_the_caption_is_no_longer_a_plain_text_input(image_media):
    """The mutant this kills: leaving the old <input> in place alongside the
    textarea. Two controls sharing name="figcaption" double-submit, and the
    browser sends the EMPTY one second -- blanking every caption on save."""
    html = _render_editor()
    assert not re.search(r'<input[^>]*name="figcaption"', html)


def test_the_caption_block_carries_the_class_wire_rte_looks_for(image_media):
    """`wireRte` locates the toolbar with closest(".el-editor--text"). Without
    this wrapper it falls back to textarea.parentNode, the toolbar is never
    found, and every button is silently inert -- the surface still mounts, so
    nothing looks broken until you click Bold."""
    assert 'class="el-editor--text"' in _render_editor()


def test_the_caption_toolbar_offers_a_link_button(image_media):
    assert 'data-cmd="link"' in _caption_block(_render_editor())


def test_the_caption_toolbar_offers_bold_italic_underline(image_media):
    block = _caption_block(_render_editor())
    for cmd in ("bold", "italic", "underline"):
        assert f'data-cmd="{cmd}"' in block, f"no {cmd} button"


def test_the_caption_toolbar_offers_nothing_the_sanitiser_would_strip():
    """Toolbar and CAPTION_TAGS must stay in step: a button whose output the
    sanitiser deletes is a control that silently does nothing."""
    markup = TOOLBAR.read_text(encoding="utf-8")
    offered = set(re.findall(r'data-cmd="([^"]+)"', markup))
    assert offered == {"bold", "italic", "underline", "link"}, offered
    # And the tag set has exactly what those four need, plus the <br> that
    # sanitize_caption substitutes for a block boundary.
    assert CAPTION_TAGS == {"a", "strong", "b", "em", "i", "u", "br"}


def test_the_stored_caption_is_the_textareas_content(image_media):
    el = ImageElement.objects.create(
        media=image_media, alt="a", figcaption='x <a href="https://e.example">y</a>'
    )
    html = _render_editor(el)
    m = re.search(
        r'<textarea[^>]*name="figcaption"[^>]*>(.*?)</textarea>', html, re.DOTALL
    )
    # Django escapes the value into the textarea; the browser decodes it back, and
    # the RTE surface is seeded from textarea.value. What must NOT happen is the
    # raw tag appearing unescaped, which would close the textarea early.
    assert "&lt;a href=&quot;https://e.example&quot;&gt;y&lt;/a&gt;" in m.group(1)


def test_the_form_rejects_a_caption_over_the_cap(image_media):
    """An error, not silent truncation. TextField carries no length validator of
    its own, so without this the old CharField(255) bound simply vanished."""
    form = ImageElementForm(
        data={
            "media": image_media.pk,
            "alt": "a",
            "figcaption": "x" * (CAPTION_MAX_LENGTH + 1),
            "size": "full",
        },
        course=image_media.course,
    )
    assert not form.is_valid()
    assert "figcaption" in form.errors


def test_the_cap_is_measured_against_what_will_be_stored(image_media):
    """Sanitising can only shrink, and it runs on save. Measuring the RAW input
    would reject a paste whose STORED form is well inside the cap -- the author
    would see a length error about characters they cannot see."""
    junk = "<h2 class='x' id='y' data-junk='zzzzzzzzzzzzzzzzzzzzzzzzzzzzzz'>ok</h2>"
    raw = junk * 40
    assert len(raw) > CAPTION_MAX_LENGTH
    form = ImageElementForm(
        data={
            "media": image_media.pk,
            "alt": "a",
            "figcaption": raw,
            "size": "full",
        },
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert len(form.cleaned_data["figcaption"]) <= CAPTION_MAX_LENGTH


def test_the_form_sanitises_before_the_model_does(image_media):
    """Belt and braces with ImageElement.save(): the form-level clean is what
    puts a safe value in cleaned_data for any caller that reads it without
    saving, and what lets a length error name the field."""
    form = ImageElementForm(
        data={
            "media": image_media.pk,
            "alt": "a",
            "figcaption": '<a href="javascript:alert(1)">x</a>',
            "size": "full",
        },
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert "javascript" not in form.cleaned_data["figcaption"]
