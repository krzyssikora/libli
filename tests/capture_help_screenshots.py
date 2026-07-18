"""Deterministic dual-locale help-screenshot capture (regeneration tool, not CI).

Regenerate committed help screenshots:

    uv run playwright install chromium   # first time only
    uv run python -m pytest tests/capture_help_screenshots.py

Not `test_`-prefixed as a filename -> not auto-collected by
`python_files=["test_*.py"]`; the single `test_`-named function is collected
only when the path is passed explicitly. Never marked `@pytest.mark.e2e`, so
the explicit run isn't deselected by `-m 'not e2e'`.
"""

import os

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time

# committed rows visible to the server
pytestmark = pytest.mark.django_db(transaction=True)

FREEZE_AT = "2026-07-18 12:00:00"
DEMO_PASSWORD = "demo-pass-123"  # mirrors the seed's DEMO_PASSWORD
OUT_DIR = settings.BASE_DIR / "core" / "static" / "core" / "img" / "help"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _u(name, **kwargs):
    """Resolve a namespaced URL from stable lookups at capture time (no literal pk)."""
    from django.contrib.auth import get_user_model

    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import QuizSubmission
    from grouping.models import Collection
    from grouping.models import Group

    User = get_user_model()
    course = Course.objects.get(slug="demo-course")

    def unit(title):
        return ContentNode.objects.get(course=course, title=title)

    if name == "settings":
        # settings tabs are one page with ?tab=; kwargs carries {"tab": ...}
        return reverse("institution:settings") + f"?tab={kwargs['tab']}"
    if name == "manage_builder":
        return reverse("courses:manage_builder", kwargs={"slug": "demo-course"})
    if name == "manage_editor":
        return reverse(
            "courses:manage_editor",
            kwargs={"slug": "demo-course", "pk": unit(kwargs["unit"]).pk},
        )
    if name == "lesson_unit":
        return reverse(
            "courses:lesson_unit",
            kwargs={"slug": "demo-course", "node_pk": unit(kwargs["unit"]).pk},
        )
    if name == "manage_media":
        return reverse("courses:manage_media", kwargs={"slug": "demo-course"})
    if name == "manage_analytics":
        return reverse("courses:manage_analytics", kwargs={"slug": "demo-course"})
    if name == "manage_analytics_student":
        pk = User.objects.get(username=kwargs["username"]).pk
        return reverse(
            "courses:manage_analytics_student",
            kwargs={"slug": "demo-course", "student_pk": pk},
        )
    if name == "manage_review_queue":
        return reverse("courses:manage_review_queue", kwargs={"slug": "demo-course"})
    if name == "manage_review_submission":
        # The REVIEW question + demo_student's unreviewed submission live on a
        # SEPARATE quiz ("Practice quiz") so "Demo quiz" stays AUTO-only and the
        # analytics/drill-down/gradebook shots show real graded cells (Task 2 fix).
        sub = QuizSubmission.objects.get(
            student__username="demo_student", unit=unit("Practice quiz")
        )
        return reverse(
            "courses:manage_review_submission",
            kwargs={"slug": "demo-course", "submission_pk": sub.pk},
        )
    if name == "my_groups":
        return reverse("grouping:my_groups")
    if name == "group_detail":
        pk = Group.objects.get(name="Demo Group", course=course).pk
        return reverse("grouping:group_detail", kwargs={"pk": pk})
    if name == "collection_detail":
        pk = Collection.objects.get(name="Demo Collection").pk
        return reverse("grouping:collection_detail", kwargs={"pk": pk})
    if name == "notes_overview":
        return reverse("notes:overview")
    if name == "my_tags":
        return reverse("tags:my_tags")
    if name == "manage_course_list":
        return reverse("courses:manage_course_list")
    if name == "manage_course_create":
        return reverse("courses:manage_course_create")
    if name == "manage_course_import":
        return reverse("courses:manage_course_import")
    if name == "people":
        return reverse("accounts:people")
    if name == "people_invitations":
        return reverse("accounts:people_invitations")
    if name == "manage_subject_list":
        return reverse("courses:manage_subject_list")
    if name == "cohort_list":
        return reverse("grouping:cohort_list")
    if name == "setup":
        return reverse("institution:setup")
    raise ValueError(f"unknown route key {name!r}")


# name, login_as, route-callable-args, wait_selector, clip_selector
SHOTS = [
    # --- course-admin (demo_teacher) ---
    (
        "builder-tree",
        "demo_teacher",
        ("manage_builder", {}),
        ".builder__tree",
        "section.builder",
    ),
    (
        "content-editor",
        "demo_teacher",
        ("manage_editor", {"unit": "Core lesson"}),
        ".editor-head__title",
        "section.editor",
    ),
    (
        "content-consume",
        "demo_teacher",
        ("lesson_unit", {"unit": "Core lesson"}),
        "article.lesson",
        "article.lesson",
    ),
    (
        "quiz-editor",
        "demo_teacher",
        ("manage_editor", {"unit": "Demo quiz"}),
        ".editor-head__title",
        "section.editor",
    ),
    (
        "interactive",
        "demo_teacher",
        ("lesson_unit", {"unit": "Bonus lesson"}),
        "article.lesson",
        "article.lesson",
    ),
    (
        "media-manager",
        "demo_teacher",
        ("manage_media", {}),
        ".media-manager",
        "section.media-manager",
    ),
    # --- teacher (demo_teacher) ---
    (
        "analytics-matrix",
        "demo_teacher",
        ("manage_analytics", {}),
        ".analytics__matrix",
        "section.manage",
    ),
    (
        "drill-down",
        "demo_teacher",
        ("manage_analytics_student", {"username": "demo_s1"}),
        ".breakdown__tree",
        "section.manage",
    ),
    (
        "review-queue",
        "demo_teacher",
        ("manage_review_queue", {}),
        "section.manage",
        "section.manage",
    ),
    (
        "review-submission",
        "demo_teacher",
        ("manage_review_submission", {}),
        ".review-topbar__title",
        ".review-shell",
    ),
    ("groups", "demo_teacher", ("my_groups", {}), ".dash-cards", "section.manage"),
    (
        "group-detail",
        "demo_teacher",
        ("group_detail", {}),
        ".manage__title",
        "section.manage",
    ),
    (
        "collection-detail",
        "demo_teacher",
        ("collection_detail", {}),
        ".manage__title",
        "section.manage",
    ),
    (
        "roster",
        "demo_teacher",
        ("group_detail", {}),
        "ul.course-list",
        "ul.course-list",
    ),
    (
        "gradebook-export",
        "demo_teacher",
        ("manage_analytics", {}),
        ".analytics__export",
        "details.analytics__export",
    ),
    (
        "notes-hub",
        "demo_teacher",
        ("notes_overview", {}),
        "section.tnhub",
        "section.tnhub",
    ),
    ("my-tags", "demo_teacher", ("my_tags", {}), "section.my-tags", "section.my-tags"),
    # --- platform-admin (demo_admin) ---
    (
        "course-list",
        "demo_admin",
        ("manage_course_list", {}),
        ".course-list",
        "section.manage",
    ),
    (
        "course-create",
        "demo_admin",
        ("manage_course_create", {}),
        "form.form",
        "section.manage",
    ),
    (
        "import",
        "demo_admin",
        ("manage_course_import", {}),
        ".dropzone",
        "section.manage",
    ),
    ("people", "demo_admin", ("people", {}), ".people-table", "section.manage"),
    (
        "invitations",
        "demo_admin",
        ("people_invitations", {}),
        ".invite-form",
        "section.manage",
    ),
    (
        "branding",
        "demo_admin",
        ("settings", {"tab": "branding"}),
        ".settings__tabs",
        "section.settings",
    ),
    (
        "sso",
        "demo_admin",
        ("settings", {"tab": "sso"}),
        ".settings__tabs",
        "section.settings",
    ),
    (
        "integrations",
        "demo_admin",
        ("settings", {"tab": "integrations"}),
        ".settings__tabs",
        "section.settings",
    ),
    (
        "subjects",
        "demo_admin",
        ("manage_subject_list", {}),
        ".card-list",
        "section.manage",
    ),
    ("cohorts", "demo_admin", ("cohort_list", {}), ".card-list", "main.app-main"),
    (
        "notifications",
        "demo_admin",
        ("settings", {"tab": "notifications"}),
        ".settings__tabs",
        "section.settings",
    ),
    ("wizard", "demo_admin", ("setup", {}), ".setup__panel", "section.setup"),
]

# Which topic doc(s) each shot belongs to (for the coverage-gate cross-check in Task 7).
TOPIC_SHOTS = {
    "builder": ["builder-tree"],
    "content-editors": ["content-editor", "content-consume"],
    "quiz-editors": ["quiz-editor"],
    "interactive-elements": ["interactive"],
    "media-manager": ["media-manager"],
    "analytics": ["analytics-matrix"],
    "drill-down": ["drill-down"],
    "quiz-review": ["review-queue", "review-submission"],
    "groups-collections": ["groups", "group-detail", "collection-detail"],
    "roster": ["roster"],
    "gradebook-export": ["gradebook-export"],
    "notes-tags": ["notes-hub", "my-tags"],
    "create-a-course": ["course-list", "course-create"],
    "export-import": ["import"],
    "users-roles": ["people"],
    "invitations": ["invitations"],
    "branding-settings": ["branding"],
    "sso": ["sso"],
    "integrations": ["integrations"],
    "subjects": ["subjects"],
    "cohorts": ["cohorts"],
    "notifications": ["notifications"],
    "first-run-wizard": ["wizard"],
}


def test_shots_cover_every_topic():
    """Self-check: every registered help topic has at least one shot mapped."""
    from core.help import TOPICS

    shot_names = {s[0] for s in SHOTS}
    for names in TOPIC_SHOTS.values():
        for n in names:
            assert n in shot_names, f"TOPIC_SHOTS references unknown shot {n!r}"
    topic_slugs = {t.slug for t in TOPICS}
    assert set(TOPIC_SHOTS) == topic_slugs, (
        f"TOPIC_SHOTS/TOPICS mismatch: {set(TOPIC_SHOTS) ^ topic_slugs}"
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(DEMO_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state("networkidle")


def _set_language(locale):
    from django.contrib.auth import get_user_model

    get_user_model().objects.filter(username__in=["demo_teacher", "demo_admin"]).update(
        language=locale
    )


def _capture_gradebook_export(page, clip_sel, out_path):
    """.analytics__export-form is position:absolute, so it does NOT expand the
    <details>'s own box even with open=true — an element screenshot of the
    details tag alone would only ever show the closed-height "Export" toggle.
    Union both boxes and take a page-level clip instead."""
    toggle_box = page.locator(clip_sel).first.bounding_box()
    form_box = page.locator(".analytics__export-form").first.bounding_box()
    x0 = min(toggle_box["x"], form_box["x"])
    y0 = min(toggle_box["y"], form_box["y"])
    x1 = max(toggle_box["x"] + toggle_box["width"], form_box["x"] + form_box["width"])
    y1 = max(toggle_box["y"] + toggle_box["height"], form_box["y"] + form_box["height"])
    page.screenshot(
        path=out_path,
        clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
    )


@override_settings(ROOT_URLCONF="tests.capture_urls", MEDIA_URL="/media/")
def test_capture_help_screenshots(live_server, browser):
    with freeze_time(FREEZE_AT):
        call_command("seed_demo_course")  # once, before the locale loop
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        for locale in ("en", "pl"):
            _set_language(locale)  # login signal seeds session _language from this
            for persona in ("demo_teacher", "demo_admin"):
                persona_shots = [s for s in SHOTS if s[1] == persona]
                if not persona_shots:
                    continue
                # Fresh context => fresh session (correct user/locale) + re-applied
                # viewport/media, matching the repo's browser.new_context() idiom.
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    color_scheme="light",
                    reduced_motion="reduce",
                )
                page = ctx.new_page()
                # ONE response listener per context over a stable list, cleared before
                # each shot. Avoids per-shot add/remove (Playwright Page has no public
                # `listeners()` accessor) and the late-binding-closure trap. Invariant:
                # a >=400 /media/ image request fails that shot. `bad_images=bad_images`
                # binds the current list as a default arg (not a closure lookup at call
                # time), satisfying B023 and staying correct across contexts.
                bad_images = []
                page.on(
                    "response",
                    lambda r, bad_images=bad_images: (
                        bad_images.append((r.url, r.status))
                        if r.request.resource_type == "image"
                        and r.status >= 400
                        and "/media/" in r.url
                        else None
                    ),
                )
                _login(page, live_server, persona)

                for name, _who, (route, args), wait_sel, clip_sel in persona_shots:
                    bad_images.clear()  # reset the tripwire per shot
                    page.goto(live_server.url + _u(route, **args))
                    page.locator(wait_sel).first.wait_for(state="visible")
                    if name == "gradebook-export":
                        # The export panel is a native <details>, closed by default —
                        # force it open so the shot documents the format/options
                        # form, not just the collapsed "Export" toggle.
                        page.locator("details.analytics__export").evaluate(
                            "el => { el.open = true; }"
                        )
                    # Bounded idle wait: "Core lesson" embeds YouTube + GeoGebra
                    # iframes whose third-party requests can hang offline; never
                    # block the run on them. First-party content (incl. demo.png)
                    # settles well within 5s.
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:  # noqa: S110 - bounded, third-party-only wait
                        pass
                    if locale == "pl":
                        assert 'lang="pl"' in page.content(), (
                            f"{name}: expected PL chrome (lang=pl) but page "
                            "is not Polish"
                        )
                    assert not bad_images, (
                        f"{name}: broken MEDIA image(s): {bad_images}"
                    )
                    out_path = str(OUT_DIR / f"{name}.{locale}.png")
                    if name == "gradebook-export":
                        _capture_gradebook_export(page, clip_sel, out_path)
                    else:
                        page.locator(clip_sel).first.screenshot(path=out_path)

                ctx.close()
