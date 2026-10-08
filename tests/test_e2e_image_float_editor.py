import pytest

from tests.factories import add_element
from tests.image_float_kit import *

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _open_editor(page, live_server, unit, element):
    page.goto(editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f'.el-act-edit[data-element-id="{element.pk}"]').click()
    page.wait_for_selector("[data-edit-slot] [data-float-right]")


def test_preview_floats_live_and_size_change_unticks(page, live_server):
    owner = make_pa_user("pa-float-ed")
    course, unit = seed_unit(owner, "float-ed")
    img = image(course, float_right=False)
    join = add_element(unit, img)
    add_element(unit, text())
    login(page, live_server, "pa-float-ed")
    _open_editor(page, live_server, unit, join)
    fig = page.locator(f'.el--image[data-preview-el="{img.pk}"]')
    box = page.locator("[data-edit-slot] [data-float-right]")

    box.check()
    assert "el--image--float" in fig.get_attribute("class")  # no save needed
    page.locator("[data-edit-slot] [data-size-preset][value='medium']").check()
    assert box.is_disabled() and not box.is_checked()
    assert "el--image--float" not in fig.get_attribute("class")
    page.locator("[data-edit-slot] [data-size-preset][value='small']").check()
    assert box.is_enabled() and not box.is_checked()  # author re-ticks deliberately
    box.check()
    page.locator("[data-edit-slot] [data-size-preset][value='large']").check()
    assert box.is_disabled() and not box.is_checked()
    assert "el--image--float" not in fig.get_attribute("class")
    page.locator("[data-edit-slot] [data-size-preset][value='small']").check()
    box.check()
    # Wait on node IDENTITY (tests/test_e2e_image_size.py::_save_open_form): a 422
    # re-renders the same selector, so a selector wait would hang, not fail.
    old_fig = fig.element_handle()
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    page.wait_for_function("el => !el.isConnected", arg=old_fig)
    img.refresh_from_db()
    assert img.float_right is True and img.floats
