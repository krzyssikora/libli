"""Playwright e2e for Phase 4a personal notes: add → see → edit → delete.

Real browser gestures only — no page.evaluate shortcuts (prior project lesson:
an e2e that bypasses the real gesture ships broken UX green).

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    # Selectors mirror the PROVEN helper in tests/test_e2e_courses.py (and the
    # other e2e suites): allauth's login field is `login` (username OR email),
    # and the form action contains "login". Username login works because the
    # project's existing e2e suites log in by username via this exact pattern.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_add_see_edit_delete_note_via_ui(page, live_server):
    from courses.models import ContentNode
    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from notes.models import Note
    from tests.factories import CourseFactory
    from tests.factories import ElementFactory
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug="e2e-notes")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Lesson",
    )
    ElementFactory(unit=unit)
    # make_verified_user creates a user with a verified primary email — mandatory
    # because allauth's AccountMiddleware redirects unverified users to confirm-email,
    # which would break the login flow.  (A bare UserFactory + force_login cannot be
    # used here because the real allauth login form is what the helper drives.)
    student = make_verified_user(
        username="e2e_note_student", email="e2e_note_student@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")

    _login(page, live_server, "e2e_note_student")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")

    # ── ADD ──────────────────────────────────────────────────────────────────
    # The .block-notes__handle is a <summary> element inside a <details
    # class="block-notes__panel">.  Clicking it opens the accordion, revealing
    # the .note-composer form with its .note-composer__input textarea.
    page.locator(".block-notes__handle").first.click()
    page.locator(".note-composer__input").first.fill("my e2e note")
    # The Save button is <button type="submit" class="btn btn--sm">Save</button>
    # inside the template-rendered .note-composer form.
    page.get_by_role("button", name="Save").first.click()

    # SEE: the JS appends the new .note-card to the list (fetch → 201 fragment).
    page.wait_for_selector("text=my e2e note")
    assert Note.objects.filter(author=student, body="my e2e note").exists()

    # Capture the pk now — needed to scope the EDIT and DELETE gestures.
    note = Note.objects.get(author=student, body="my e2e note")
    note_pk = note.pk

    # ── EDIT ─────────────────────────────────────────────────────────────────
    # Click the ✏️ edit action link (.note-action--edit) on the card.  The JS
    # (notes.js §2) replaces the card with an inline .note-composer--edit form
    # pre-filled with the old body.  No extra GET round-trip — body comes from DOM.
    page.locator(f"#note-{note_pk} .note-action--edit").click()

    # The inline form is now present; scope selectors to it to avoid ambiguity.
    edit_form = page.locator(".note-composer--edit")
    edit_form.locator("textarea[name='body']").fill("my e2e note edited")
    # The JS-built Save button: saveBtn.textContent = "Save" (notes.js §2).
    edit_form.get_by_role("button", name="Save").click()

    # After a 200 response, the JS replaces the inline form with the updated
    # .note-card fragment returned by the server (notes/_note_card.html).
    page.wait_for_selector("text=my e2e note edited")
    note.refresh_from_db()
    assert note.body == "my e2e note edited"

    # ── DELETE ────────────────────────────────────────────────────────────────
    # Click the 🗑 delete action link (.note-action--delete) on the card.  The
    # JS (notes.js §3) replaces the card with an inline .note-delete-confirm div
    # showing "Delete? [Yes] [No]".
    page.locator(f"#note-{note_pk} .note-action--delete").click()

    # The Yes button: yesBtn.textContent = "Yes" (notes.js §3).  Clicking it
    # POSTs to the delete URL; on resp.ok the JS calls confirm.remove().
    page.get_by_role("button", name="Yes").click()

    # Wait for the confirm div to be removed from the DOM.
    page.wait_for_selector(".note-delete-confirm", state="detached")

    # Assert the Note row no longer exists in the database.
    assert not Note.objects.filter(pk=note_pk).exists()


@pytest.mark.django_db(transaction=True)
def test_cancel_add_composer_closes_without_saving(page, live_server):
    # Regression: opening the add composer (e.g. by accident) must be dismissable.
    # The composer carries a Cancel button (JS-revealed) that collapses the panel
    # and discards the draft without creating a Note.
    from courses.models import ContentNode
    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from notes.models import Note
    from tests.factories import CourseFactory
    from tests.factories import ElementFactory
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug="e2e-notes-cancel")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Lesson",
    )
    ElementFactory(unit=unit)
    student = make_verified_user(
        username="e2e_cancel_student", email="e2e_cancel_student@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")

    _login(page, live_server, "e2e_cancel_student")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")

    # Open the composer and type a throwaway draft.
    page.locator(".block-notes__handle").first.click()
    composer_input = page.locator(".note-composer__input").first
    composer_input.wait_for(state="visible")
    composer_input.fill("draft I will discard")

    # Click the JS-revealed Cancel button scoped to the open panel.
    page.locator(".block-notes__panel[open] .note-composer__dismiss").click()

    # The panel collapses: no panel is open and the textarea is no longer visible.
    page.wait_for_selector(".block-notes__panel[open]", state="detached")
    composer_input.wait_for(state="hidden")

    # Nothing was persisted.
    assert not Note.objects.filter(author=student).exists()


@pytest.mark.django_db(transaction=True)
def test_existing_note_is_read_first(page, live_server):
    # When a block already has a note, opening it is read-first: the note shows,
    # the composer is hidden behind "Add another note" until that is clicked.
    from courses.models import ContentNode
    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from notes import services
    from notes.models import Note
    from tests.factories import CourseFactory
    from tests.factories import ElementFactory
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug="e2e-readfirst")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Lesson",
    )
    el = ElementFactory(unit=unit)
    student = make_verified_user(
        username="e2e_rf_student", email="e2e_rf_student@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    services.create_note(student, unit, el.pk, "Existing note")

    _login(page, live_server, "e2e_rf_student")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")

    # Open the panel: the existing note shows; the composer is hidden behind the
    # "Add another note" affordance.
    page.locator(".block-notes__handle").first.click()
    page.wait_for_selector("text=Existing note")
    add_more = page.get_by_role("button", name="Add another note")
    expect(add_more).to_be_visible()
    composer = page.locator(".block-notes__panel[open] .note-composer__input")
    expect(composer).to_be_hidden()

    # Reveal the composer and add a second note.
    add_more.click()
    expect(composer).to_be_visible()
    composer.fill("Second note via add-more")
    page.get_by_role("button", name="Save").first.click()
    page.wait_for_selector("text=Second note via add-more")
    assert Note.objects.filter(author=student, body="Second note via add-more").exists()
    # Back to read-first: the composer hides again after the add.
    expect(
        page.locator(".block-notes__panel[open] .note-composer__input")
    ).to_be_hidden()
