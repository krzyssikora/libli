"""Category A/B/C classification for the spoiler body cleanup.

Measured on the real data: libli 1xA + 1xB + 0xC; libli_mat 0. The predicate is
written defensively for shapes NOT observed locally, because production has not yet
taken the mat-pp cutover.
"""

import pytest

from courses.migrations_support import body_is_empty_ish

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "body",
    [
        "<br>",  # the shape actually observed (pk 1395)
        "<p><br></p>",  # the RTE's normal "empty" output
        "<div><br></div>",
        "<div>&nbsp;</div>",
        "<p> </p>",  # decoded nbsp
        "   ",
    ],
)
def test_empty_ish_bodies_are_category_A(body):
    assert body_is_empty_ish(body) is True


@pytest.mark.parametrize("body", ["<p>real</p>", "<p>a &nbsp; b</p>", "<br>x"])
def test_real_content_is_not_category_A(body):
    assert body_is_empty_ish(body) is False


# Fill in from the `makemigrations --empty` output, e.g. "0053".
_MIGRATION_PREFIX = "0053"


def test_migration_clears_A_and_B_but_preserves_C():
    from importlib import import_module

    from django.apps import apps as live_apps

    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TextElement
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()

    def _sp(body, child_body=None):
        sp = SpoilerElement.objects.create(label="s", body=body)
        join = add_element(unit, sp)
        if child_body is not None:
            Element.objects.create(
                unit=unit,
                content_object=TextElement.objects.create(body=child_body),
                parent=join,
                tab_id=SpoilerElement.SLOT_ID,
            )
        return sp

    dup = "<p>identical</p>"
    a = _sp("<p><br></p>", "<p>c</p>")
    b = _sp(dup, dup)
    c = _sp("<p>GENUINELY STRANDED</p>", "<p>different</p>")
    childless_a = _sp("<div>&nbsp;</div>")

    # Invoke the migration function directly against the live app registry.
    mod = import_module(f"courses.migrations.{_MIGRATION_PREFIX}_spoiler_body_cleanup")
    mod.clear_unreachable_bodies(live_apps, None)

    a.refresh_from_db()
    b.refresh_from_db()
    c.refresh_from_db()
    childless_a.refresh_from_db()
    assert a.body == ""
    assert b.body == ""
    assert c.body == "<p>GENUINELY STRANDED</p>", "category C must be preserved"
    assert childless_a.body == "", "category A applies to childless spoilers too"
