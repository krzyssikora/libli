import pytest
from django.utils import translation

from demo.services import revoke_kit
from demo.warnings import DISPLAY
from demo.warnings import KINDS
from institution import views_manage
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import add_pending
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import pending_entry
from tests.demo.tab_helpers import session_store
from tests.demo.tab_helpers import soup
from tests.demo.tab_helpers import stored_session
from tests.demo.tab_helpers import write_stored_session

KEY = "demo_kit_results"


def test_a_card_is_shown_once_with_no_store(pa_client, vendor):
    """P4, read half (Task 6 drives the real create)."""
    kit = provision_for_test(small_course())
    entry = pending_entry(kit)
    add_pending(pa_client, entry)

    first = pa_client.get(demo_tab_url())
    body = first.content.decode()
    assert entry["teacher_password"] in body and entry["student_password"] in body
    assert "no-store" in first["Cache-Control"]

    second = pa_client.get(demo_tab_url()).content.decode()
    assert entry["teacher_password"] not in second
    assert KEY not in stored_session(pa_client)


def test_an_entry_past_the_ttl_becomes_a_notice(pa_client, vendor):
    """P6."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit, age_seconds=16 * 60))

    body = pa_client.get(demo_tab_url()).content.decode()

    assert f"TeacherPw{kit.pk}x" not in body
    assert f"Credentials for kit #{kit.pk} were never displayed" in body
    assert "was closed before its credentials were displayed" not in body
    assert KEY not in stored_session(pa_client)


def test_a_card_for_a_closed_kit_becomes_a_notice(pa_client, vendor):
    """P17."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))
    revoke_kit(kit)

    body = pa_client.get(demo_tab_url()).content.decode()

    assert f"Kit #{kit.pk} was closed before its credentials were displayed." in body
    assert f"TeacherPw{kit.pk}x" not in body


def test_only_a_real_get_takes_credentials(pa_client, vendor):
    """P15."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))

    pa_client.head(demo_tab_url())
    assert KEY in stored_session(pa_client)

    speculative = pa_client.get(demo_tab_url(), HTTP_SEC_PURPOSE="prefetch;prerender")
    speculative_body = speculative.content.decode()
    assert KEY in stored_session(pa_client)
    assert f"TeacherPw{kit.pk}x" not in speculative_body
    assert "Credentials are waiting — reload this page." in speculative_body

    assert f"TeacherPw{kit.pk}x" in pa_client.get(demo_tab_url()).content.decode()


def test_every_warning_kind_renders_inside_the_wrapper(pa_client, vendor):
    """P10, all-kinds half. Asserted on text inside data-demo-warnings — never "a
    200": a missing template key renders an empty string, not an error."""
    kit = provision_for_test(small_course())
    summary = {kind: {"count": 1, "unit_ids": [], "detail": None} for kind in KINDS}
    add_pending(pa_client, pending_entry(kit, warnings=summary))

    wrapper = soup(pa_client.get(demo_tab_url())).select_one("[data-demo-warnings]")
    text = wrapper.get_text(" ")

    with translation.override("en"):
        for kind in KINDS:
            assert str(DISPLAY[kind]) in text, kind
        assert text.count(str(DISPLAY["active_webhook_endpoint"])) == 1


def test_taking_credentials_writes_nothing_else(pa_client, vendor, monkeypatch):
    """P18. Another tab saves mid-render — an unrelated key, and a kit that
    finished meanwhile. The discard must remove only what this page showed."""
    course = small_course()
    shown = provision_for_test(course, label="Shown")
    late = provision_for_test(course, label="Late")
    add_pending(pa_client, pending_entry(shown))

    original = views_manage._settings_context

    def another_tab_saves(*args, **kwargs):
        store = session_store(pa_client)
        store["element_clip"] = "mid-render"
        store[KEY] = [*store.get(KEY, []), pending_entry(late)]
        store.save()
        return original(*args, **kwargs)

    monkeypatch.setattr(views_manage, "_settings_context", another_tab_saves)

    body = pa_client.get(demo_tab_url()).content.decode()

    assert f"TeacherPw{shown.pk}x" in body
    stored = stored_session(pa_client)
    assert [entry["kit_id"] for entry in stored[KEY]] == [late.pk]
    assert stored["element_clip"] == "mid-render"


def test_a_middleware_modified_session_does_not_resurrect_a_shown_entry(
    pa_client, vendor
):
    """P19(b). A stored language outside enabled_languages (default ["en", "pl"])
    makes LanguageSeederMiddleware modify request.session on this request."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))
    write_stored_session(pa_client, _language="de")

    assert f"TeacherPw{kit.pk}x" in pa_client.get(demo_tab_url()).content.decode()

    assert KEY not in stored_session(pa_client)
    write_stored_session(pa_client, _language="de")
    assert f"TeacherPw{kit.pk}x" not in pa_client.get(demo_tab_url()).content.decode()


def test_a_render_failure_keeps_the_credentials(pa_client, vendor, monkeypatch):
    """P20."""
    kit = provision_for_test(small_course())
    add_pending(pa_client, pending_entry(kit))

    def broken(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(views_manage, "_settings_context", broken)
    with pytest.raises(RuntimeError):
        pa_client.get(demo_tab_url())

    assert KEY in stored_session(pa_client)
    monkeypatch.undo()
    assert f"TeacherPw{kit.pk}x" in pa_client.get(demo_tab_url()).content.decode()
