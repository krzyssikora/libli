"""Light + dark capture of every surface the LaTeX-in-titles feature touches
(spec 2026-08-10, Task 11 Step 5a/5b).

Regeneration/verification tool, not CI. Run explicitly:

    uv run pytest tests/capture_title_math_screenshots.py -m e2e

Not `test_`-prefixed as a FILENAME, so `python_files=["test_*.py"]` never
auto-collects it; the `test_`-named function inside is collected only when
this path is passed explicitly. Mirrors tests/capture_publish_screenshots.py.

Why it exists: none of the surfaces the §3 CSS clamp claims to cover, or
claims need NO clamp, existed under the fixtures written for the earlier
tasks -- MATHS_TITLE is short, make_title_course has no long-title or
two-depth-analytics mode, and nothing seeds a `\\[...\\]`-only title or a
`[R]`-marked review question. This script builds one course that carries
every named surface at once and shoots it, so §3's claims are judged from a
real render instead of an assumption.

Dark is set through User.theme, NOT the libli_theme cookie: for an
authenticated user _resolve_theme_pref lets User.theme win outright, so a
cookie is silently ignored and the "dark" shot would come back light.

Output goes to SHOT_DIR (env) or ./.superpowers/shots/, both gitignored.
"""

import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from tags import services as tag_services
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import NoteFactory
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get("SHOT_DIR", Path(settings.BASE_DIR) / ".superpowers" / "shots")
)

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
# Same viewport test_e2e_unit_nav.py:311,355 uses for its drawer tests.
MOBILE_VIEWPORT = {"width": 390, "height": 780}

TITLES = {
    # (key, title) -- each one exists to exercise a specific §3 claim
    "inline": r"Rozwiaz \(x^2 + 2x + 1 = 0\) metoda delty",
    "display": r"Rozwiaz \[\int_0^1 x^2\,dx\] i zapisz wynik",  # .katex-display
    # (long) -- wraps past the 5-line group clamp and every single-line clip
    "long": r"Bardzo dlugi tytul lekcji z formula \(\sum_{i=1}^{n} a_i b_i\) na koncu",
    # (mixed_h1) -- the forced-inline decision AND the font-weight restoration
    "mixed_h1": r"Policz \(a_1\) oraz \[\frac{p}{q}\] i porownaj",
    "plain": "Lekcja bez matematyki",
}


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _build_course():
    """One course carrying every §3 surface at once. See module docstring.

    Shape (pre-order):
        Part A   (long)
          Chapter A1  (long)  -- the crumb LEAF for every lesson below it
            lesson_mixed  (mixed_h1)
            lesson_display  (display)
            lesson_long  (long)
            lesson_plain  (plain)
        Part B   (inline)
          lesson_b  (inline)   -- order 0, so lesson_plain's NEXT is inline-only
          quiz_b    (long)     -- order 1, carries the [R] question + submission
        Part C   ("Czesc bez matematyki") -- NOT part of the TITLES fixture.
          quiz_c  (plain title) -- exists ONLY to give rows 9/10 a maths-FREE
                                   row to measure against; §3's own pass
                                   criterion for those rows is "with AND
                                   without a maths title", and the two-part
                                   TITLES fixture alone never produces a
                                   plain quiz row to compare against.
    """
    owner = make_verified_user(
        username="titlemathowner",
        email="titlemathowner@t.example.com",
        password=TEST_PASSWORD,
    )
    course = CourseFactory(
        slug="title-math-shots", owner=owner, title="Title maths shots"
    )

    part_a = ContentNodeFactory(
        course=course,
        kind="part",
        parent=None,
        unit_type=None,
        order=0,
        title=TITLES["long"],
    )
    chapter_a1 = ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=part_a,
        unit_type=None,
        order=0,
        title=TITLES["long"],
    )
    lesson_mixed = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter_a1,
        order=0,
        title=TITLES["mixed_h1"],
    )
    lesson_display = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter_a1,
        order=1,
        title=TITLES["display"],
    )
    lesson_long = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter_a1,
        order=2,
        title=TITLES["long"],
    )
    lesson_plain = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter_a1,
        order=3,
        title=TITLES["plain"],
    )

    part_b = ContentNodeFactory(
        course=course,
        kind="part",
        parent=None,
        unit_type=None,
        order=1,
        title=TITLES["inline"],
    )
    # order 0/1 deliberately swapped from "quiz then lesson": lesson_plain's
    # course-order NEXT must be the inline-only title (row 1), and a SUBMITTED
    # quiz redirects its own unit page straight to quiz_results (courses/
    # views.py:1411-1417), so quiz_b can never be the page a nav-button shot
    # is taken FROM. Putting it last avoids that dead end.
    lesson_b = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part_b,
        order=0,
        title=TITLES["inline"],
    )
    quiz_b = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=part_b,
        order=1,
        title=TITLES["long"],
    )

    # The [R] question rows 9/13b need, or review_queue/review_submission
    # render nothing to shoot (courses/review.py::_awaiting_review requires
    # state["total"] > 0). Shape from tests/test_review_views.py:54-63.
    q = ExtendedResponseQuestionElement.objects.create(
        stem="<p>Explain plainly.</p>",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    Element.objects.create(unit=quiz_b, content_object=q)

    part_c = ContentNodeFactory(
        course=course,
        kind="part",
        parent=None,
        unit_type=None,
        order=2,
        title="Czesc bez matematyki",
    )
    quiz_c = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=part_c,
        order=0,
        title="Quiz bez matematyki",
    )

    student = make_verified_user(
        username="titlemathstudent",
        email="titlemathstudent@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)
    other = make_verified_user(
        username="titlemathother",
        email="titlemathother@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=other, course=course)

    # SUBMITTED + unreviewed -- rows 9 (awaiting), 10 (results row), 13b
    # (review submission), 13a (quiz_results, via the student login).
    QuizSubmission.objects.create(
        student=student,
        unit=quiz_b,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    # IN_PROGRESS on the maths-FREE quiz -- the comparison row for row 9.
    QuizSubmission.objects.create(
        student=other,
        unit=quiz_c,
        status=QuizSubmission.Status.IN_PROGRESS,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )

    # Tag + note, both authored by the enrolled student -- row 12. Without
    # the note, notes.services.course_notes omits units with no notes and
    # course_notes.html renders course-notes__empty; h2.course-notes__unit-
    # title (the row's own claim) never appears.
    tag_services.tag_unit(student, lesson_mixed, "matematyka")
    NoteFactory(author=student, unit=lesson_mixed, body="Notatka do wzoru.")

    return {
        "owner": owner,
        "student": student,
        "other": other,
        "course": course,
        "part_a": part_a,
        "chapter_a1": chapter_a1,
        "lesson_mixed": lesson_mixed,
        "lesson_display": lesson_display,
        "lesson_long": lesson_long,
        "lesson_plain": lesson_plain,
        "part_b": part_b,
        "lesson_b": lesson_b,
        "quiz_b": quiz_b,
        "part_c": part_c,
        "quiz_c": quiz_c,
    }


def test_capture(browser, live_server):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shots = []
    measurements = []

    def shoot(name, locator=None, *, page=None):
        path = OUT_DIR / f"{name}.png"
        if locator is not None:
            locator.screenshot(path=str(path))
        else:
            page.screenshot(path=str(path), full_page=True)
        shots.append(path)

    nodes = _build_course()
    course = nodes["course"]
    slug = course.slug

    def _url(name, **kwargs):
        return f"{live_server.url}{reverse(name, kwargs=kwargs)}"

    def unit_url(node):
        is_quiz = node.unit_type == "quiz"
        name = "courses:quiz_unit" if is_quiz else "courses:lesson_unit"
        return _url(name, slug=slug, node_pk=node.pk)

    def set_theme(user, theme):
        user.theme = theme
        user.save(update_fields=["theme"])

    # ------------------------------------------------------------------
    # STUDENT surfaces: desktop viewport, rows 1-5, 8, 10 (half), 12, 13a.
    # ------------------------------------------------------------------
    student = nodes["student"]
    ctx = browser.new_context(viewport=DESKTOP_VIEWPORT)
    page = ctx.new_page()
    try:
        _login(page, live_server, student.username)
        for theme in ("light", "dark"):
            set_theme(student, theme)
            page.goto(unit_url(nodes["lesson_plain"]))
            assert page.locator("html").get_attribute("data-theme") == theme

            # Row 1: prev/next buttons, INLINE maths title. lesson_plain's
            # NEXT is lesson_b (inline-only).
            page.wait_for_selector(".unit-foot__navtitle .katex")
            shoot(f"title-math-1-{theme}", page.locator(".unit-foot"))

            # Rows 2-5: lesson_display's page. Prev = lesson_mixed (carries
            # \[...\] -- the display-math nav-button case); next = lesson_long
            # (long title, single-line clip); the rail alongside it holds
            # BOTH the long unit row (row 3) and chapter A1's long GROUP
            # title (row 5); the breadcrumb leaf is chapter A1 (row 4).
            page.goto(unit_url(nodes["lesson_display"]))
            page.wait_for_selector(".unit-foot__navtitle .katex")
            shoot(f"title-math-2-{theme}", page.locator(".unit-foot"))
            shoot(f"title-math-3-{theme}", page.locator(".unit-tree"))
            shoot(f"title-math-4-{theme}", page.locator(".unit-crumbs"))
            shoot(f"title-math-5-{theme}", page.locator(".unit-tree"))

            # Row 8: the lesson <h1> carrying BOTH \(...\) and \[...\].
            page.goto(unit_url(nodes["lesson_mixed"]))
            page.wait_for_selector(".lesson-unit__title .katex")
            shoot(f"title-math-8-{theme}", page.locator(".lesson-unit__title"))

            # Row 10 (half): the outline row. Compare a maths-titled row
            # (lesson_mixed) against a maths-free one (lesson_plain), both
            # visible in the same tree.
            page.goto(_url("courses:course_outline", slug=slug))
            page.wait_for_selector(".outline-unit__title .katex")
            shoot(f"title-math-10-outline-{theme}", page.locator(".outline-tree"))
            with_math_h = page.locator(
                ".outline-unit:has(.outline-unit__title .katex) .outline-unit__title"
            ).first.bounding_box()["height"]
            # Per-row breakdown, not just one with/without pair: the clamp
            # normalises MOST maths titles back to the plain-row height (even
            # an inline \sum with limits), but a genuinely tall construct --
            # a fraction, or a \[...\] display integral -- still grows the
            # row. That is accepted elsewhere in §3 (the .katex-display and
            # 5-line-clamp cases both keep the formula intact rather than
            # forcing it into a single text line), so it is recorded here
            # rather than chased further.
            row_heights = page.evaluate(
                """() => {
                    const rows = document.querySelectorAll('.outline-unit__title');
                    return [...rows].map(el => ({
                        text: el.textContent.trim().slice(0, 24),
                        hasKatex: !!el.querySelector('.katex'),
                        height: el.getBoundingClientRect().height,
                    }));
                }"""
            )
            measurements.append(
                f"row10 [{theme}] per-row outline heights: {row_heights}"
            )
            no_math_sel = (
                ".outline-unit:not(:has(.outline-unit__title .katex)) "
                ".outline-unit__title"
            )
            without_math_h = page.locator(no_math_sel).first.bounding_box()["height"]
            measurements.append(
                f"row10 outline-unit__title height: with maths {with_math_h:.1f}px, "
                f"without {without_math_h:.1f}px"
            )

            # Row 10 (other half): the course-results row. quiz_b (maths,
            # awaiting review) vs quiz_c (plain, not started).
            page.goto(_url("courses:course_results", slug=slug))
            page.wait_for_selector(".result-row__title .katex")
            shoot(f"title-math-10-results-{theme}", page.locator(".result-list"))
            with_math_h = page.locator(
                ".result-row:has(.result-row__title .katex)"
            ).first.bounding_box()["height"]
            without_math_h = page.locator(
                ".result-row:not(:has(.result-row__title .katex))"
            ).first.bounding_box()["height"]
            measurements.append(
                f"row10 result-row height: with maths {with_math_h:.1f}px, "
                f"without {without_math_h:.1f}px"
            )

            # Row 13a: h1.result__title on the per-quiz quiz_results page.
            page.goto(
                _url("courses:quiz_results", slug=slug, node_pk=nodes["quiz_b"].pk)
            )
            page.wait_for_selector("h1.result__title .katex")
            shoot(f"title-math-13a-results-{theme}", page.locator("h1.result__title"))

            # Row 12a: notes page.
            page.goto(_url("notes:course_notes", slug=slug))
            page.wait_for_selector("h2.course-notes__unit-title .katex")
            shoot(f"title-math-12a-notes-{theme}", page.locator(".course-notes"))

            # Row 12b: tags hub.
            page.goto(f"{live_server.url}{reverse('tags:my_tags')}")
            page.wait_for_selector(".tag-section__units li a .katex")
            shoot(f"title-math-12b-taghub-{theme}", page.locator(".tag-section"))

            # Row 12c: tags panel (the no-JS 422 fragment page). Inject a
            # fresh form tags.js never binds to, so the browser follows a
            # real same-origin navigation instead of tags.js's fetch
            # interception -- {% static %} then resolves and KaTeX loads.
            page.goto(unit_url(nodes["lesson_mixed"]))
            tag_add_url = reverse(
                "tags:tag_add",
                kwargs={"slug": slug, "node_pk": nodes["lesson_mixed"].pk},
            )
            page.evaluate(
                """(addUrl) => {
                    const sel = '[name=csrfmiddlewaretoken]';
                    const tok = document.querySelector(sel).value;
                    const f = document.createElement('form');
                    f.method = 'post';
                    f.action = addUrl;
                    const tokInput = '<input name="csrfmiddlewaretoken" value="'
                        + tok + '">';
                    const nameInput = '<input name="name" value="">';
                    f.innerHTML = tokInput + nameInput;
                    document.body.appendChild(f);
                    f.submit();
                }""",
                tag_add_url,
            )
            page.wait_for_selector("h1 [data-math-title] .katex")
            shoot(f"title-math-12c-tagspanel-{theme}", page.locator("h1"))

            # Row 7: mobile drawer, long maths title. Separate context below
            # for the distinct viewport; captured inside the theme loop so
            # both themes are covered without a second full walk.
    finally:
        ctx.close()

    # ------------------------------------------------------------------
    # Row 7: mobile drawer -- its own viewport, own context.
    # ------------------------------------------------------------------
    ctx = browser.new_context(viewport=MOBILE_VIEWPORT)
    page = ctx.new_page()
    try:
        _login(page, live_server, student.username)
        for theme in ("light", "dark"):
            set_theme(student, theme)
            page.goto(unit_url(nodes["lesson_display"]))
            fab = page.locator("[data-unit-drawer-open]")
            fab.wait_for(state="visible")
            fab.click()
            drawer = page.locator("[data-unit-drawer]")
            drawer.wait_for(state="visible")
            page.wait_for_selector("[data-unit-drawer] .unit-tree__label .katex")
            shoot(f"title-math-7-{theme}", drawer)
            # Automated overlap check alongside the visual one: does any
            # .katex box in the drawer tree intrude on a SIBLING control's
            # box? Deliberately excludes the katex span's own ANCESTOR link
            # (every .unit-tree__unit / .unit-tree__group wraps its own
            # label) -- a descendant's rect always intersects its ancestor's,
            # so including it would make this trivially true on every build.
            overlap = page.evaluate(
                """() => {
                    const kx = [...document.querySelectorAll(
                        '[data-unit-drawer] .unit-tree__label .katex'
                    )];
                    const btns = [...document.querySelectorAll(
                        '[data-unit-drawer] .unit-drawer__close, '
                        + '[data-unit-drawer] .unit-tree__count, '
                        + '[data-unit-drawer] .unit-tree__groupcheck, '
                        + '[data-unit-drawer] .unit-tree__check, '
                        + '[data-unit-drawer] .unit-tree__chevron'
                    )];
                    const overlaps = (a, b) => !(
                        a.right < b.left || a.left > b.right ||
                        a.bottom < b.top || a.top > b.bottom
                    );
                    for (const k of kx) {
                        const kb = k.getBoundingClientRect();
                        for (const b of btns) {
                            const bb = b.getBoundingClientRect();
                            if (overlaps(kb, bb)) return true;
                        }
                    }
                    return false;
                }"""
            )
            measurements.append(
                f"row7 [{theme}] katex overlaps a drawer button: {overlap}"
            )
    finally:
        ctx.close()

    # ------------------------------------------------------------------
    # ADMIN (course-owner) surfaces: rows 6, 9, 11, 13b, 14.
    # ------------------------------------------------------------------
    owner = nodes["owner"]
    ctx = browser.new_context(viewport=DESKTOP_VIEWPORT)
    page = ctx.new_page()
    try:
        _login(page, live_server, owner.username)
        for theme in ("light", "dark"):
            set_theme(owner, theme)

            # Row 6: analytics matrix, maths at two nesting depths. Part B
            # must be EXPANDED via ?expand= or it renders as an unexpanded
            # leaf and analytics__group-title never appears.
            matrix_url = (
                _url("courses:manage_analytics", slug=slug)
                + f"?expand={nodes['part_b'].pk}"
            )
            page.goto(matrix_url)
            page.wait_for_selector(".analytics__group-title .katex")
            # .analytics__scroll has its own overflow-x -- the group header
            # (Part B) sits well past the first screenful of columns, so it
            # must be scrolled into view or the shot silently omits the one
            # surface this row exists to judge.
            group_katex = page.locator(".analytics__group-title .katex").first
            group_katex.scroll_into_view_if_needed()
            shoot(f"title-math-6-{theme}", page.locator(".analytics__scroll"))
            # Measure the DEPTH-2 leaf colheads (Part B's own children, in
            # the LAST header row, rowspan=1) against --ahead-h. Deliberately
            # NOT the first `.analytics__colhead:not(.analytics__group)`
            # match -- that is a SHALLOW top-level leaf (Part A, collapsed)
            # which legitimately carries rowspan=2 to align with the deeper
            # row beneath it, exactly like .analytics__rowhead ("Student"):
            # its 2x height is by design, not a maths overflow.
            cell_h = page.eval_on_selector(
                "thead tr:last-child .analytics__colhead:not(.analytics__group) .katex",
                "el => el.closest('th').getBoundingClientRect().height",
            )
            group_cell_h = page.eval_on_selector(
                ".analytics__group-title .katex",
                "el => el.closest('th').getBoundingClientRect().height",
            )
            shallow_leaf_h = page.eval_on_selector(
                "thead tr:first-child "
                ".analytics__colhead:not(.analytics__group) .katex",
                "el => el.closest('th').getBoundingClientRect().height",
            )
            ahead_h = page.eval_on_selector(
                ".analytics",
                "el => parseFloat(getComputedStyle(el).getPropertyValue('--ahead-h')) "
                "* parseFloat(getComputedStyle(document.documentElement).fontSize)",
            )
            measurements.append(
                f"row6 [{theme}] depth-2 leaf colhead height: {cell_h:.1f}px, "
                f"group colhead height: {group_cell_h:.1f}px, "
                f"shallow (rowspan=2) leaf colhead height: {shallow_leaf_h:.1f}px, "
                f"--ahead-h: {ahead_h:.1f}px"
            )

            # Row 9: review-queue rows, WITH (quiz_b, awaiting) and WITHOUT
            # (quiz_c, in-progress) a maths title.
            page.goto(_url("courses:manage_review_queue", slug=slug))
            page.wait_for_selector(".card-list__row [data-math-title] .katex")
            shoot(f"title-math-9-{theme}", page.locator(".card-list").first)
            with_math_h = page.locator(
                ".card-list__row:has([data-math-title] .katex)"
            ).first.bounding_box()["height"]
            without_math_h = page.locator(
                ".card-list__row:not(:has([data-math-title] .katex))"
            ).first.bounding_box()["height"]
            measurements.append(
                f"row9 [{theme}] card-list__row height: "
                f"with maths {with_math_h:.1f}px, without {without_math_h:.1f}px"
            )

            # Row 11: analytics breakdown, quiz + lesson rows.
            page.goto(
                _url(
                    "courses:manage_analytics_student",
                    slug=slug,
                    student_pk=student.pk,
                )
            )
            page.wait_for_selector(".breakdown-unit__title .katex")
            shoot(f"title-math-11-{theme}", page.locator(".breakdown__tree"))

            # Row 13b: h1.review-topbar__title on the review-submission page.
            sub = QuizSubmission.objects.get(unit=nodes["quiz_b"], student=student)
            page.goto(
                _url(
                    "courses:manage_review_submission",
                    slug=slug,
                    submission_pk=sub.pk,
                )
            )
            page.wait_for_selector("h1.review-topbar__title [data-math-title] .katex")
            shoot(
                f"title-math-13b-review-{theme}",
                page.locator("h1.review-topbar__title"),
            )

            # Row 14: the editor -- ancestor crumb, h1, and preview h2, all on
            # one page, all unconditional.
            editor_pk = nodes["lesson_mixed"].pk
            page.goto(_url("courses:manage_editor", slug=slug, pk=editor_pk))
            page.wait_for_selector(".editor-head__title .katex")
            shoot(f"title-math-14-crumb-{theme}", page.locator(".editor-crumb"))
            shoot(f"title-math-14-head-{theme}", page.locator(".editor-head"))
            preview = page.locator(".prev-unit-title")
            if preview.count():
                shoot(f"title-math-14-preview-{theme}", preview.first)
    finally:
        ctx.close()

    print(f"SCREENSHOTS ({len(shots)}): {OUT_DIR}")
    for line in measurements:
        print(f"[measure] {line}")
    assert len(shots) > 0
