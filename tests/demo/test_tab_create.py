from django.conf import settings as django_settings
from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.utils import translation

from courses.models import ContentNode
from courses.models import Course
from demo import errors
from demo.constants import LABEL_MAX
from demo.constants import MAX_PUPILS
from demo.constants import MIN_PUPILS
from demo.models import DemoKit
from demo.warnings import DISPLAY
from institution import views_manage
from integrations.models import WebhookEndpoint
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import add_pending
from tests.demo.tab_helpers import create_data
from tests.demo.tab_helpers import create_url
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import pending_entry
from tests.demo.tab_helpers import row_ids
from tests.demo.tab_helpers import seed_the_view
from tests.demo.tab_helpers import session_store
from tests.demo.tab_helpers import soup
from tests.demo.tab_helpers import stored_session
from tests.demo.tab_helpers import write_stored_session
from tests.factories import make_teacher

KEY = "demo_kit_results"


def test_create_404s_on_a_school_box(pa_client):
    """P3, create half."""
    assert pa_client.post(create_url(), create_data(small_course())).status_code == 404
    assert not DemoKit.objects.exists()


def test_create_needs_change_institution(client, vendor):
    make_teacher(client)
    assert client.post(create_url(), create_data(small_course())).status_code == 403


def test_a_create_redirects_and_shows_the_credentials_once(
    pa_client, vendor, monkeypatch
):
    """P4."""
    course = small_course()
    seed_the_view(monkeypatch)

    response = pa_client.post(create_url(), create_data(course))

    assert response.status_code == 302
    assert response["Location"] == demo_tab_url()
    kit = DemoKit.objects.get()
    assert kit.created_by.username == "pa"
    entry = stored_session(pa_client)[KEY][0]

    first = pa_client.get(demo_tab_url())
    # Asserted INSIDE the card: the kit list prints the teacher username too.
    card = soup(first).select_one(f'[data-demo-card="{kit.pk}"]')
    assert card is not None
    card_text = card.get_text(" ")
    for shown in (
        kit.teacher.username,
        kit.student.username,
        entry["teacher_password"],
        entry["student_password"],
    ):
        assert shown in card_text
    assert "no-store" in first["Cache-Control"]
    teacher = authenticate(
        username=kit.teacher.username, password=entry["teacher_password"]
    )
    student = authenticate(
        username=kit.student.username, password=entry["student_password"]
    )
    assert teacher is not None and student is not None

    second_response = pa_client.get(demo_tab_url())
    second = second_response.content.decode()
    assert entry["teacher_password"] not in second
    assert entry["student_password"] not in second
    assert kit.pk in row_ids(second_response)  # the list still shows the kit
    assert KEY not in stored_session(pa_client)


def test_credentials_wait_while_another_tab_is_open(pa_client, vendor, monkeypatch):
    """P5: a dropped connection self-heals on the next Demo-tab GET."""
    seed_the_view(monkeypatch)
    pa_client.post(create_url(), create_data(small_course()))
    password = stored_session(pa_client)[KEY][0]["teacher_password"]

    branding = pa_client.get(demo_tab_url().replace("tab=demo", "tab=branding"))
    assert password not in branding.content.decode()
    assert KEY in stored_session(pa_client)

    assert password in pa_client.get(demo_tab_url()).content.decode()


def test_two_creates_before_any_get_both_show(pa_client, vendor, monkeypatch):
    """P7."""
    course = small_course()
    seed_the_view(monkeypatch)
    pa_client.post(create_url(), create_data(course, label="First school"))
    pa_client.post(create_url(), create_data(course, label="Second school"))

    entries = stored_session(pa_client)[KEY]
    assert len(entries) == 2
    body = pa_client.get(demo_tab_url()).content.decode()
    for entry in entries:
        assert entry["teacher_password"] in body


def test_the_form_holds_no_bounds_of_its_own(pa_client, vendor, monkeypatch):
    """P8. Field errors come from the SERVICE; the form holds no bound."""
    course = small_course()
    seed_the_view(monkeypatch)

    too_few = pa_client.post(create_url(), create_data(course, pupils=4))
    pupil_errors = " ".join(too_few.context["demo_form"].errors["pupils"])
    assert str(MIN_PUPILS) in pupil_errors and str(MAX_PUPILS) in pupil_errors
    assert not DemoKit.objects.exists()

    blank = pa_client.post(create_url(), create_data(course, label="   "))
    assert "label" in blank.context["demo_form"].errors

    empty = Course.objects.create(slug="empty", title="Empty", language="pl")
    no_units = pa_client.post(create_url(), create_data(empty))
    assert "This course cannot hold a demo." in str(
        no_units.context["demo_form"].non_field_errors()
    )

    # The bound moves with the service's constant, so the form cannot hold one.
    monkeypatch.setattr("demo.services.MIN_PUPILS", 3)
    pa_client.post(create_url(), create_data(course, pupils=4))
    assert DemoKit.objects.filter(pupil_count=4).exists()


def test_an_over_long_label_is_a_label_error_from_the_service(
    pa_client, vendor, monkeypatch
):
    """Spec §4.2's InvalidLabel row (P8's blank label never reaches the service)."""
    seed_the_view(monkeypatch)

    response = pa_client.post(
        create_url(), create_data(small_course(), label="x" * (LABEL_MAX + 1))
    )

    assert response.status_code == 200
    label_errors = " ".join(response.context["demo_form"].errors["label"])
    assert str(LABEL_MAX) in label_errors
    assert not response.context["demo_form"].non_field_errors()
    assert not DemoKit.objects.exists()


def test_a_service_message_is_escaped(pa_client, vendor, monkeypatch):
    """P8, escaping half."""

    def raises(*args, **kwargs):
        raise errors.EmptyCourse("<b>bold</b>")

    monkeypatch.setattr(views_manage, "provision_kit", raises)

    response = pa_client.post(create_url(), create_data(small_course()))

    html = str(response.context["demo_form"].non_field_errors())
    assert "<code>&lt;b&gt;bold&lt;/b&gt;</code>" in html
    assert "<b>bold</b>" not in html


def test_a_failed_create_leaves_pending_credentials_alone(
    pa_client, vendor, monkeypatch
):
    """P9. X's kit already holds the sp-12-* logins, and a blind scan turns the
    second "SP 12" create into the double-submit's UsernameCollision."""
    course = small_course()
    kit_x = provision_for_test(course, label="SP 12")
    add_pending(pa_client, pending_entry(kit_x))
    seed_the_view(monkeypatch)
    monkeypatch.setattr("demo.services._taken", lambda names: False)

    response = pa_client.post(create_url(), create_data(course, label="SP 12"))

    assert response.status_code == 200
    errors_html = str(response.context["demo_form"].non_field_errors())
    # The link is asserted INSIDE the errors: the tab nav carries ?tab=demo too.
    assert f'href="{demo_tab_url()}"' in errors_html
    assert "retry" not in errors_html.lower()
    assert [entry["kit_id"] for entry in stored_session(pa_client)[KEY]] == [kit_x.pk]
    assert f"TeacherPw{kit_x.pk}x" in pa_client.get(demo_tab_url()).content.decode()


def test_warnings_from_a_real_provision(pa_client, vendor, monkeypatch):
    """P10, provision half."""
    endpoint = WebhookEndpoint.load()
    endpoint.enabled = True
    endpoint.url = "https://sis.example.edu/libli-hook"
    endpoint.secret = "not-a-real-signing-key"  # noqa: S105
    endpoint.save()
    course = small_course(quiz_with_review_question=True)
    reviewed = ContentNode.objects.get(course=course, title="Reviewed quiz")
    seed_the_view(monkeypatch)

    response = pa_client.post(create_url(), create_data(course))
    # No other test provisions this fixture variant. A 200 here means the kit
    # rolled back (EmptyKit) and the form re-rendered — see Step 7's seed note —
    # rather than a confusing KeyError on the session below.
    assert response.status_code == 302

    summary = stored_session(pa_client)[KEY][0]["warnings"]
    assert reviewed.pk in summary["quiz_skipped"]["unit_ids"]
    assert summary["active_webhook_endpoint"]["detail"] == endpoint.url
    assert summary["quiz_skipped"]["detail"] is None

    wrapper = soup(pa_client.get(demo_tab_url())).select_one("[data-demo-warnings]")
    text = wrapper.get_text(" ")
    with translation.override("en"):
        skipped = str(DISPLAY["quiz_skipped"])
        webhook = str(DISPLAY["active_webhook_endpoint"])
    assert text.index(endpoint.url) < text.index(skipped)
    assert text.count(webhook) == 1
    assert "Reviewed quiz" in text
    assert "a REVIEW question cannot be answered" not in text
    assert "has no builder" not in text


def test_the_show_all_link_works_from_a_create_error_page(pa_client, vendor):
    """P11. The panel renders at .../demo/create/ too, so a relative href would
    lose all=1 through the create view's non-POST redirect."""
    response = pa_client.post(create_url(), create_data(small_course(), label=""))

    href = soup(response).select_one("a[data-demo-show-all]")["href"]
    assert href == demo_tab_url(show_all=True)
    followed = pa_client.get(href)
    assert followed.status_code == 200
    assert followed.context["demo_show_all"] is True


def test_the_write_goes_through_a_fresh_store(pa_client, vendor, monkeypatch):
    """P14. Other tabs save while the kit is being built."""
    course = small_course()
    other = provision_for_test(course, label="Other school")

    def other_tabs_save(result):
        store = session_store(pa_client)
        store["element_clip"] = "mid-provision"
        store[KEY] = [*store.get(KEY, []), pending_entry(other)]
        store.save()

    seed_the_view(monkeypatch, before_return=other_tabs_save)

    pa_client.post(create_url(), create_data(course))

    new_kit = DemoKit.objects.exclude(pk=other.pk).get()
    stored = stored_session(pa_client)
    assert [entry["kit_id"] for entry in stored[KEY]] == [other.pk, new_kit.pk]
    assert stored["element_clip"] == "mid-provision"


def test_an_ended_session_is_not_resurrected(pa_client, vendor, monkeypatch):
    """P16(a). A logout in another tab while the kit is being built."""
    key = pa_client.session.session_key
    seed_the_view(
        monkeypatch,
        before_return=lambda result: Session.objects.filter(session_key=key).delete(),
    )

    response = pa_client.post(create_url(), create_data(small_course()))

    assert response.status_code == 302
    assert response["Location"] == demo_tab_url()
    assert django_settings.SESSION_COOKIE_NAME not in response.cookies
    assert Session.objects.count() == 0
    assert DemoKit.objects.exists()


def test_a_row_deleted_after_the_read_leaves_no_orphan(pa_client, vendor, monkeypatch):
    """P16(b). The row vanishes right after the fresh store's first database read.
    The patch is started with monkeypatch INSIDE the wrapper and stays active for
    the rest of the request; a `with mock.patch` block would end when the wrapper
    returns, before the view's store reads."""
    from django.contrib.sessions.backends.db import SessionStore as DbSessionStore

    original = DbSessionStore._get_session_from_db
    fired = []

    def delete_after_first_read(store):
        found = original(store)
        if found is not None and not fired:
            fired.append(True)
            Session.objects.filter(session_key=store.session_key).delete()
        return found

    seed_the_view(
        monkeypatch,
        before_return=lambda result: monkeypatch.setattr(
            DbSessionStore, "_get_session_from_db", delete_after_first_read
        ),
    )

    response = pa_client.post(create_url(), create_data(small_course()))

    assert fired
    assert response.status_code == 302
    assert django_settings.SESSION_COOKIE_NAME not in response.cookies
    assert Session.objects.count() == 0


def test_a_middleware_modified_session_does_not_undo_the_write(
    pa_client, vendor, monkeypatch
):
    """P19(a)."""
    seed_the_view(monkeypatch)
    write_stored_session(pa_client, _language="de")

    pa_client.post(create_url(), create_data(small_course()))

    assert [entry["kit_id"] for entry in stored_session(pa_client)[KEY]] == [
        DemoKit.objects.get().pk
    ]
