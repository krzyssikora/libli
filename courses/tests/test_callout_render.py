import pytest

from courses.models import CalloutElement

pytestmark = pytest.mark.django_db

# The task-kind pencil icon's body path (barrel/tip outline), pinned in full so a
# truncation anywhere in the ~128-char `d` value -- not just past a short prefix --
# turns test_task_render_emits_pencil_icon RED.
TASK_ICON_BODY_PATH = (
    "M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83"
    "l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"
)


def test_render_carries_kind_modifier_class_and_heading_default():
    html = CalloutElement(kind="warning", body="<p>hi</p>").render()
    assert "callout--warning" in html
    assert "Important" in html  # default heading
    assert "hi" in html


def test_render_uses_heading_override():
    html = CalloutElement(kind="tip", heading="Pro tip", body="").render()
    assert "Pro tip" in html
    assert "callout--tip" in html


def test_render_selects_correct_icon_per_kind():
    # The five kinds emit five distinct icon markers; assert the book-open path
    # (Example) is present only for example, and the triangle (warning) for warning.
    example = CalloutElement(kind="example", body="").render()
    warning = CalloutElement(kind="warning", body="").render()
    assert "callout__icon" in example
    # book-open has a distinctive M12 7v14 spine; warning has the triangle path.
    assert "M12 7v14" in example
    assert "M12 7v14" not in warning


def test_render_sanitizes_body_on_output():
    el = CalloutElement.objects.create(kind="note", body="<script>x</script><p>ok</p>")
    html = el.render()
    assert "<script>" not in html
    assert "ok" in html


def test_persisted_task_callout_renders_kind_class():
    # No django_db decorator needed: this module already sets
    # `pytestmark = pytest.mark.django_db` at :5. (test_callout_transfer.py is the
    # one callout module that marks per-test -- see Task 6.)
    #
    # PERSISTED deliberately: the template interpolates el.kind directly, so an
    # unsaved instance renders callout--task even with the enum member absent.
    # Only save()'s coercion (task -> example) makes the mutant bite.
    el = CalloutElement.objects.create(kind="task", body="<p>hi</p>")
    html = el.render()
    assert "callout--task" in html


def test_task_render_emits_pencil_icon():
    html = CalloutElement(kind="task", body="").render()
    # The path is the pencil's distinguishing geometry...
    assert "m15 5 4 4" in html
    # ...and the pencil's body (the barrel/tip outline), not just the nib stroke --
    # a truncated or garbled body path would leave a lone diagonal tick on screen.
    # The FULL body path is pinned (not a prefix), so a truncation anywhere in the
    # `d` value -- including past the curve back and the closing z -- goes RED.
    assert TASK_ICON_BODY_PATH in html
    # ...and the chip must still be styled and hidden from assistive tech.
    # NOTE: these two do NOT fall to the delete-the-elif mutant -- the {% else %}
    # book-open SVG carries the identical class and aria-hidden. They have their
    # own mutant in Task 8 Step 4 ("strip aria-hidden in the task branch only").
    assert 'class="callout__icon"' in html
    assert 'aria-hidden="true"' in html


def test_example_render_does_not_emit_pencil_icon():
    # Guards against putting the pencil in the {% else %} fallback, which serves
    # `example` -- that mistake leaves the previous test green.
    html = CalloutElement(kind="example", body="").render()
    assert "m15 5 4 4" not in html


def _summary_soup(**fields):
    from bs4 import BeautifulSoup

    # PERSISTED: save() must keep "summary" (the enum member exists), and the
    # render reads the stored kind.
    el = CalloutElement.objects.create(kind="summary", **fields)
    html = el.render()
    return html, BeautifulSoup(html, "html.parser")


def test_summary_renders_an_h3_title_and_no_eyebrow():
    """T5. Mutant: render summary through the generic branch -> a callout__header
    with an icon and an eyebrow, and no h3."""
    html, soup = _summary_soup(heading="Funkcja liniowa", body="<p>x</p>")
    aside = soup.find("aside")
    assert "callout--summary" in aside["class"]
    first = aside.find(True, recursive=False)  # first ELEMENT child, not whitespace
    assert first.name == "h3"
    assert first["class"] == ["callout__title"]
    assert first.get_text() == "Funkcja liniowa"
    assert "callout__header" not in html
    assert "callout__icon" not in html
    assert "callout__heading" not in html


def test_an_empty_heading_summary_titles_itself_key_facts():
    """Review Focus 2 (D2 fallback, rendered). Mutant: `{{ el.heading }}` in the h3
    -> an empty title."""
    _html, soup = _summary_soup(heading="", body="<p>x</p>")
    title = soup.find("h3", class_="callout__title")
    assert title is not None
    assert title.get_text() == "Key facts"


def test_the_summary_title_escapes_the_heading():
    """Mutant: `{{ el.display_heading|safe }}` -> raw markup in the h3."""
    html, _soup = _summary_soup(heading="a < b & c", body="")
    assert '<h3 class="callout__title">a &lt; b &amp; c</h3>' in html
