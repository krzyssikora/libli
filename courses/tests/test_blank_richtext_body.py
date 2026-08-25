"""A rich-text body that carries no visible content must be stored as "".

The trigger is Ctrl+A + Delete in the RTE surface: MEASURED in headless Chromium,
contenteditable leaves `<p><br></p>` behind (backspacing every character instead
leaves ""). `sanitize_html` preserves that markup verbatim -- both `p` and `br` are
in ALLOWED_TAGS -- so `body` stays TRUTHY and every consumer that guards on a bare
`{% if el.body %}` fires: the student page renders an empty `.callout__body`
paragraph (a blank line), and the editor row claims the callout "has text".

Migration 0053 cleared exactly this shape once, for spoilers only, as a one-shot
data pass. It left the WRITE path unguarded, so the defect re-appears on the next
save, and callouts were never covered at all. These tests pin the guard at the
model-save choke point, which every writer goes through (form, importer, LAL
loader, transfer).
"""

import pytest

from courses.models import CalloutElement
from courses.models import SpoilerElement
from courses.models import TextElement

pytestmark = pytest.mark.django_db

# Every shape the RTE can leave behind, plus the hand-authored equivalents.
# `<p><br></p>` is the MEASURED Ctrl+A/Delete output; `<div><br></div>` is what the
# same gesture yields once defaultParagraphSeparator has been set to "div"
# (text_toolbar.js:200), and a bare `<br>` is Firefox's.
BLANK_BODIES = ["<p><br></p>", "<div><br></div>", "<br>", "<p>&nbsp;</p>", "   "]

# Bodies that DO carry content and must survive untouched. The last one is the
# over-normalisation guard: a trailing blank paragraph after real text is the
# author's deliberate spacing, not an empty body.
KEPT_BODIES = [
    "<p>Hello</p>",
    "<p>\(x^2\)</p>",
    "<p>Hello</p><p><br></p>",
]

MODELS = [CalloutElement, SpoilerElement, TextElement]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("body", BLANK_BODIES)
def test_blank_body_is_stored_as_empty_string(model, body):
    obj = model.objects.create(body=body)
    obj.refresh_from_db()
    assert obj.body == ""


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("body", KEPT_BODIES)
def test_a_body_with_visible_content_is_left_alone(model, body):
    obj = model.objects.create(body=body)
    obj.refresh_from_db()
    # Compared against the SANITISED input, not the raw input: sanitize_html runs
    # first and is the reason a raw comparison would be a different assertion.
    from courses.sanitize import sanitize_html

    assert obj.body == sanitize_html(body)
    assert obj.body != ""


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_clearing_an_existing_body_stores_empty_string(model):
    """The reported gesture: type text, save, select-all + delete, save again.
    An UPDATE, not a create -- `save()` is the same choke point but a guard put in
    a form's clean_body (or in a create-only path) would pass the create test and
    fail this one."""
    obj = model.objects.create(body="<p>Something</p>")
    obj.body = "<p><br></p>"
    obj.save()
    obj.refresh_from_db()
    assert obj.body == ""
