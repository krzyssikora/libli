"""Light + dark capture of every surface the publish-state UI added.

Regeneration/verification tool, not CI. Run explicitly:

    uv run pytest tests/capture_publish_screenshots.py -m e2e

Not `test_`-prefixed as a FILENAME, so `python_files=["test_*.py"]` never
auto-collects it; the `test_`-named function inside is collected only when this
path is passed explicitly. Mirrors tests/capture_help_screenshots.py.

Why it exists: final-review I3/I4 were rendering defects that shipped because
nobody ever looked at the feature -- an entire new UI family with zero CSS and
an inert-glyph fallback painting a solid box on every quiz row. Source-level
guards (tests/test_publish_styles.py) prove a rule EXISTS; only a render proves
it looks right, and dark has to be judged on its own merits.

Dark is set through User.theme, NOT the libli_theme cookie: for an authenticated
user _resolve_theme_pref lets User.theme win outright, so a cookie is silently
ignored and the "dark" shot would come back light.

Output goes to SHOT_DIR (env) or ./.superpowers/shots/, both gitignored.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from courses.models import QuizSubmission
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get("SHOT_DIR", Path(settings.BASE_DIR) / ".superpowers" / "shots")
)


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def test_capture(page, live_server):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shots = []

    def shoot(name):
        path = OUT_DIR / f"{name}.png"
        page.screenshot(path=str(path), full_page=True)
        shots.append(path)

    owner = _make_pa_user("shotpa")
    course = CourseFactory(slug="shots", owner=owner, title="Publish shots")

    # A MIXED container: one live unit, one draft -> the confirm strip's
    # "N are live, M are drafts." counts line and both action buttons.
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part One"
    )
    live_unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        published=True,
        title="A published lesson",
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        published=False,
        title="A drafted lesson",
    )
    # A quiz-only container: exercises the zero-lessons inert control (I4).
    quizzes = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Quizzes only"
    )
    loud_quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=quizzes,
        published=True,
        title="Loud quiz",
    )
    quiet_quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=quizzes,
        published=True,
        title="Quiet quiz",
    )

    # LOUD: two submitters in a live group + one in-flight attempt.
    live_group = GroupFactory(course=course, archived=False)
    for _ in range(2):
        st = UserFactory()
        GroupMembershipFactory(group=live_group, student=st)
        QuizSubmissionFactory(
            unit=loud_quiz, student=st, status=QuizSubmission.Status.SUBMITTED
        )
    inflight = UserFactory()
    GroupMembershipFactory(group=live_group, student=inflight)
    QuizSubmissionFactory(
        unit=loud_quiz, student=inflight, status=QuizSubmission.Status.IN_PROGRESS
    )

    # QUIET: every submitter is in an ARCHIVED group -- plus one live in-flight
    # attempt, the I2 case: the render stays quiet and must still name it.
    archived_group = GroupFactory(course=course, archived=True)
    for _ in range(3):
        st = UserFactory()
        GroupMembershipFactory(group=archived_group, student=st)
        QuizSubmissionFactory(
            unit=quiet_quiz, student=st, status=QuizSubmission.Status.SUBMITTED
        )
    q_inflight = UserFactory()
    GroupMembershipFactory(group=live_group, student=q_inflight)
    QuizSubmissionFactory(
        unit=quiet_quiz, student=q_inflight, status=QuizSubmission.Status.IN_PROGRESS
    )

    _login(page, live_server, "shotpa")
    page.set_viewport_size({"width": 1280, "height": 900})
    builder = reverse("courses:manage_builder", kwargs={"slug": "shots"})

    for theme in ("light", "dark"):
        # User.theme, never the libli_theme cookie: for an authenticated user
        # _resolve_theme_pref lets User.theme win outright, so a cookie is
        # silently ignored and the "dark" pass would come back light.
        owner.theme = theme
        owner.save(update_fields=["theme"])
        page.goto(f"{live_server.url}{builder}?open={part.pk},{quizzes.pk}")
        assert page.locator("html").get_attribute("data-theme") == theme

        # (1) The tree itself: the legend, a quiz row's inert obligatory control
        # (I4), and the draft strike-through.
        page.wait_for_selector(".flag-legend")
        shoot(f"tree-and-legend-{theme}")

        # (2) The in-row confirm strip on a MIXED container.
        page.click(
            f'li.tree__row[data-node="{part.pk}"] > .tree__rowhead '
            'a[data-flag-confirm][data-flag="published"]'
        )
        strip = page.locator(f'[data-flag-strip="{part.pk}"]')
        strip.wait_for(state="visible")
        shoot(f"strip-mixed-container-{theme}")

        # (3) The strip's quiz warning, LOUD.
        page.click(
            f'li.tree__row[data-node="{loud_quiz.pk}"] > .tree__rowhead '
            'a[data-flag-confirm][data-flag="published"]'
        )
        page.locator(f'[data-flag-strip="{loud_quiz.pk}"]').wait_for(state="visible")
        page.wait_for_selector(".flag-strip__quiz-warning")
        shoot(f"strip-quiz-warning-loud-{theme}")

        # (4) The same warning, QUIET (archived groups only).
        page.click(
            f'li.tree__row[data-node="{quiet_quiz.pk}"] > .tree__rowhead '
            'a[data-flag-confirm][data-flag="published"]'
        )
        page.locator(f'[data-flag-strip="{quiet_quiz.pk}"]').wait_for(state="visible")
        page.wait_for_selector(".flag-strip__quiz-warning--quiet")
        shoot(f"strip-quiz-warning-quiet-{theme}")

        # (5) The no-JS interstitial: base stylesheets ONLY, so it is the one
        # surface that proves the app.css half of the split.
        flag_url = reverse("courses:manage_node_flag", kwargs={"slug": "shots"})
        page.goto(
            f"{live_server.url}{flag_url}?node={loud_quiz.pk}&flag=published&scope=node"
        )
        page.wait_for_selector(".flag-strip__quiz-warning")
        shoot(f"interstitial-no-js-{theme}")

        # (6) The editor's submission banner, loud and quiet.
        for label, node in (("loud", loud_quiz), ("quiet", quiet_quiz)):
            page.goto(
                f"{live_server.url}"
                + reverse(
                    "courses:manage_editor", kwargs={"slug": "shots", "pk": node.pk}
                )
            )
            page.wait_for_selector(".quiz-submission-banner")
            shoot(f"editor-submission-banner-{label}-{theme}")

        # (7) The DRAFT banner on the editor page and on the student-facing
        # lesson render (author view) -- different stylesheets on each.
        live_unit.published = False
        live_unit.save(update_fields=["published"])
        page.goto(
            f"{live_server.url}"
            + reverse(
                "courses:manage_editor", kwargs={"slug": "shots", "pk": live_unit.pk}
            )
        )
        page.wait_for_selector(".draft-banner")
        shoot(f"draft-banner-editor-{theme}")

        page.goto(f"{live_server.url}/courses/n/{live_unit.pk}/")
        page.wait_for_selector(".draft-banner")
        shoot(f"draft-banner-lesson-{theme}")
        live_unit.published = True
        live_unit.save(update_fields=["published"])

    print(f"SCREENSHOTS ({len(shots)}): {OUT_DIR}")
    assert len(shots) == 18
