import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import RevealGateElement
from courses.models import TextElement

pytestmark = pytest.mark.django_db


def test_render_button_hidden_with_marker():
    html = RevealGateElement.objects.create(label="").render()
    assert "data-reveal-gate" in html
    assert "hidden" in html
    assert "Show more" in html  # default label


def test_render_custom_label():
    html = RevealGateElement.objects.create(label="Reveal it").render()
    assert "Reveal it" in html


def lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def test_no_reveal_armed_no_hidden_blocks(client):
    """Fail-open guard: the ONLY thing that can hide a post-gate sibling is the
    `.reveal-armed ... :not(.reveal-shown)` CSS rule, and `.reveal-armed` is
    added to <html> exclusively by the inline prepaint <script> -- never
    baked into the server-rendered markup. So a client that never executes
    JS (no-JS browser, screen reader without JS, a fetch/curl, etc.) gets a
    response where:
      1. <html> never carries class="reveal-armed" in the initial markup.
      2. no lesson-block/tabs__child carries a `hidden` attribute or an
         inline `display:none` (the reveal-gate BUTTON itself may be
         `hidden` pending JS un-hiding it -- that's fine, it degrades to
         "no button" not "no content").
      3. every hiding rule emitted in the gated <style> block is scoped
         under the `.reveal-armed` selector, so it cannot match absent the
         class.
    i.e. without reveal-armed, nothing following the gate is display:none.
    """
    from tests.factories import make_course_with_unit
    from tests.factories import make_student

    make_student(client, "student")
    _course, unit = make_course_with_unit()
    join = Element.objects.create(
        unit=unit, content_object=RevealGateElement.objects.create(label="")
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="gated content"),
    )
    student = get_user_model().objects.get(username="student")
    Enrollment.objects.get_or_create(student=student, course=unit.course)

    html = client.get(lesson_url(unit)).content.decode()

    assert join.pk  # sanity: gate element was created

    # 1. <html ...> never ships class="reveal-armed" -- it's JS-only.
    html_tag = re.search(r"<html\b[^>]*>", html)
    assert html_tag is not None
    assert "reveal-armed" not in html_tag.group(0)

    # 2. no lesson-block / tabs__child in the body is server-side hidden.
    for block_html in re.findall(
        r'<section[^>]*class="lesson-block"[^>]*>', html
    ) + re.findall(r'class="[^"]*\btabs__child\b[^"]*"[^>]*>', html):
        assert "hidden" not in block_html
        assert "display:none" not in block_html.replace(" ", "")
        assert "display: none" not in block_html

    # 3. every hiding declaration is gated behind the .reveal-armed selector
    # (the pre-hide <style> block never emits a bare, unconditional rule).
    for style_block in re.findall(r"<style>(.*?)</style>", html, re.DOTALL):
        if "display: none" in style_block or "display:none" in style_block:
            for rule in style_block.split("{")[:-1]:
                selector = rule.rsplit("}", 1)[-1].strip()
                if not selector:
                    continue
                assert ".reveal-armed" in selector, (
                    f"unscoped hiding selector: {selector!r}"
                )
