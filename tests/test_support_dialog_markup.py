"""Server-rendered markup for the report dialog."""

import pytest
from django.urls import reverse

from support.constants import DESCRIPTION_MAX_LENGTH
from support.models import SupportSettings
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _set_audience(value):
    row = SupportSettings.load()
    row.audience = value
    row.save()


def test_a_permitted_reporter_gets_the_trigger_and_the_dialog(client):
    _set_audience(SupportSettings.Audience.ALL)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    assert "data-report-trigger" in body
    assert 'id="report-dialog"' in body


def test_a_user_outside_the_audience_gets_neither(client):
    _set_audience(SupportSettings.Audience.ADMINS)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    assert "data-report-trigger" not in body
    assert 'id="report-dialog"' not in body


def test_the_textarea_carries_a_server_rendered_maxlength(client):
    """Mutant: apply maxlength from JS only — the returned HTML then has none."""
    _set_audience(SupportSettings.Audience.ALL)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    assert f'maxlength="{DESCRIPTION_MAX_LENGTH}"' in body


def test_the_dialog_is_not_inside_a_hidden_menu_panel(client):
    """showModal() on a <dialog> inside a hidden subtree does not reliably work,
    and the account-menu panel carries the hidden attribute."""
    _set_audience(SupportSettings.Audience.ALL)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    dialog_at = body.index('id="report-dialog"')
    panel_at = body.index("account-menu")
    # The dialog must come AFTER the whole header block, at body level.
    assert dialog_at > panel_at
    assert "</header>" in body[:dialog_at]


def test_the_dialog_assets_are_outside_the_overridable_blocks(client):
    """Child templates override extra_css/extra_js; assets placed there would be
    dropped on most pages, giving an inert dialog on some routes only.

    Before running this, confirm the page chosen for the JS half really does
    override {% block extra_js %}; if it does not, pick one that does — an
    assertion on a page with no such block cannot fail.
    """
    _set_audience(SupportSettings.Audience.ALL)
    # core/user_settings.html overrides extra_css ONLY — it has no extra_js block,
    # so asserting the script here would pass even with the <script> moved inside
    # {% block extra_js %}, which is the mutant this test exists for.
    make_student(client)
    css_page = client.get(reverse("core:user_settings")).content.decode()
    assert "support/css/support.css" in css_page


def test_the_dialog_script_survives_a_template_that_overrides_extra_js(client):
    """The JS half of the pair above.

    templates/courses/catalog.html really does override {% block extra_js %} —
    institution/manage/settings.html does NOT (it overrides only extra_css), so
    pointing this at the settings page would pass even with the <script> moved
    inside the block, which is the mutant this test exists to kill. Verify the
    chosen template still has the block before relying on this assertion.
    """
    _set_audience(SupportSettings.Audience.ALL)
    make_student(client)
    js_page = client.get(reverse("courses:catalog")).content.decode()
    assert "support/js/report_dialog.js" in js_page
