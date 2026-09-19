"""Playwright e2e for cross-unit copy: mark in A, follow "Copy to another unit..."
to B, "Copy before" a middle row. The whole path crosses a full page navigation
AND a fragment swap, which no template or service test can see."""

import os

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

LONG_LABEL = "L" * 90  # >= 80 characters, forces the label to truncate


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


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


def _seed(owner):
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug="crossunit", owner=owner)
    # A LONG title with the maths at the END, so at 400px the "from" link truncates
    # with the maths in the clipped tail -- the only case where an escaped
    # .katex-mathml twin could widen the page (the containment mutant needs it).
    a = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Unit A with a deliberately long source title for truncation \\(x^2\\)",
    )
    b = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Unit B"
    )
    # Enough extra units to overflow the capped list; the last ones carry maths.
    for i in range(40):
        title = f"Filler {i} \\(y_{i}\\)" if i >= 35 else f"Filler {i}"
        ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=None, title=title
        )
    subject = Element.objects.create(
        unit=a,
        title=LONG_LABEL,
        content_object=TextElement.objects.create(body="<p>COPYMARKER</p>"),
    )
    # B must overflow .pane-body even with the list closed (1280x720 assertion).
    rows = [
        Element.objects.create(
            unit=b,
            content_object=TextElement.objects.create(body=f"<p>BROW-{i}</p>"),
        )
        for i in range(25)
    ]
    return course, a, b, subject, rows


def _editor(live_server, course, unit):
    return live_server.url + reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )


def _box(page, selector):
    return page.locator(selector).first.bounding_box()


def _inside(inner, outer, tol=1):
    return (
        inner["x"] >= outer["x"] - tol
        and inner["y"] >= outer["y"] - tol
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + tol
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + tol
    )


CLIP_BUTTON = "> .el-row__head .el-actions form[data-op='element-clip'] button"


@pytest.mark.django_db(transaction=True)
def test_a_copy_follows_the_author_to_another_unit(page, live_server):
    page.set_viewport_size({"width": 1280, "height": 720})
    user = _make_pa_user("pa")
    course, a, b, subject, rows = _seed(user)
    _login(page, live_server, "pa")
    page.goto(_editor(live_server, course, a))

    # 1. Mark in A through the real control.
    row = page.locator(f".el-row[data-element='{subject.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        row.locator(CLIP_BUTTON).click()
    expect(page.locator("#clip-banner")).to_be_visible()

    # 2. The pill lines up with the "Editor" heading (no full-bleed banner): the
    #    head's inline padding and the banner's inline margin are both --space-4.
    pill = _box(page, "#clip-banner .clip-banner__line")
    head = _box(page, "[data-scope='editor'] .pane-head h2")
    assert abs(pill["x"] - head["x"]) <= 1

    # 3. Open the list in A and check the link to B is really visible.
    page.locator("#clip-banner .clip-banner__units > summary").click()
    link = page.locator(f"#clip-banner a[href$='/unit/{b.pk}/edit/']")
    expect(link).to_be_visible()
    assert _inside(link.bounding_box(), _box(page, "#clip-banner"))
    last = page.locator("#clip-banner .clip-banner__units-list a").last
    last.scroll_into_view_if_needed()
    vb = {"x": 0, "y": 0, "width": 1280, "height": 720}
    assert _inside(last.bounding_box(), vb)
    # The cancel control stays on the pill with the list open.
    assert _inside(
        _box(page, "#clip-banner .clip-banner__line form button"),
        _box(page, "#clip-banner .clip-banner__line"),
    )

    # 4. Follow the link to B: the mark followed, copy controls only.
    link.click()
    page.wait_for_url(f"**/unit/{b.pk}/edit/")
    expect(page.locator("#clip-banner .clip-banner__from a")).to_be_visible()
    # Split width, long label: the "from" link keeps a real share of the pill.
    line = _box(page, "#clip-banner .clip-banner__line")
    frm = page.locator("#clip-banner .clip-banner__from a").bounding_box()
    assert frm["width"] > 0 and _inside(frm, line)

    # KaTeX containment at 1280x720, measured in B -- whose 25 rows overflow
    # .pane-body even with the list CLOSED, so its scrollHeight is content-bound and
    # must not change: the page is viewport-locked and the list scrolls inside
    # itself. .pane-body keeps at least ~40% of the pane.
    pane_body_h = (
        "document.querySelector('[data-scope=\"editor\"] .pane-body').scrollHeight"
    )
    doc_h = page.evaluate("document.documentElement.scrollHeight")
    body_h = page.evaluate(pane_body_h)
    page.locator("#clip-banner .clip-banner__units > summary").click()
    assert page.evaluate("document.documentElement.scrollHeight") == doc_h
    assert page.evaluate(pane_body_h) == body_h
    share = page.evaluate(
        "(() => { const p = document.querySelector('[data-scope=\"editor\"]');"
        " return p.querySelector('.pane-body').clientHeight / p.clientHeight; })()"
    )
    assert share >= 0.4, share
    page.locator("#clip-banner .clip-banner__units > summary").click()  # close it
    expect(
        page.locator("form[data-op='element-paste'] button[value='move']")
    ).to_have_count(0)

    # 5. Copy before the middle row, waiting on the REQUEST.
    anchor = rows[12]
    with page.expect_response(lambda r: "element/paste/" in r.url):
        page.locator(
            f".el-row[data-element='{anchor.pk}'] "
            "> .el-row__head .el-actions form[data-op='element-paste-before'] button"
        ).click()

    # Wait on a DOM condition first: the response can land before applyFragments
    # swaps the pane, and the order read below must see the NEW DOM.
    expect(page.locator('[data-scope="preview"]')).to_contain_text("COPYMARKER")
    order = page.eval_on_selector_all(
        '[data-scope="editor"] .element-list > .el-row[data-element]',
        "rows => rows.map(r => r.innerText)",
    )
    idx = next(
        i for i, t in enumerate(order) if "COPYMARKER" in t or LONG_LABEL[:20] in t
    )
    assert "BROW-12" in order[idx + 1]
    # The mark is kept (D8) and the swapped banner's maths is typeset.
    expect(page.locator("#clip-banner")).to_be_visible()
    expect(page.locator("#clip-banner .clip-banner__from a .katex")).to_have_count(1)
    page.locator("#clip-banner .clip-banner__units > summary").click()
    expect(
        page.locator("#clip-banner .clip-banner__units-list a .katex").first
    ).to_be_attached()


@pytest.mark.django_db(transaction=True)
def test_the_banner_survives_a_narrow_viewport(page, live_server):
    page.set_viewport_size({"width": 400, "height": 800})
    user = _make_pa_user("pa")
    course, a, b, subject, _rows = _seed(user)
    _login(page, live_server, "pa")
    # BASELINE: whatever horizontal overflow the unmarked editor page already has
    # at 400px is not the banner's doing; the banner must add none.
    page.goto(_editor(live_server, course, b))
    base_overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    page.goto(_editor(live_server, course, a))
    row = page.locator(f".el-row[data-element='{subject.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        row.locator(CLIP_BUTTON).click()
    page.goto(_editor(live_server, course, b))

    line = _box(page, "#clip-banner .clip-banner__line")
    frm = page.locator("#clip-banner .clip-banner__from a").bounding_box()
    assert frm["width"] > 0 and _inside(frm, line)
    assert _inside(_box(page, "#clip-banner .clip-banner__line form button"), line)
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= base_overflow, (overflow, base_overflow)

    banner_h = page.evaluate("document.querySelector('#clip-banner').offsetHeight")
    doc_h = page.evaluate("document.documentElement.scrollHeight")
    page.locator("#clip-banner .clip-banner__units > summary").click()
    grew_doc = page.evaluate("document.documentElement.scrollHeight") - doc_h
    grew_banner = (
        page.evaluate("document.querySelector('#clip-banner').offsetHeight") - banner_h
    )
    assert abs(grew_doc - grew_banner) <= 1  # escaped .katex-mathml would add more


@pytest.mark.django_db(transaction=True)
def test_the_cancel_stays_on_the_pill_when_nothing_fits(page, live_server):
    from courses.models import CalloutElement
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from tests.factories import make_quiz_unit

    page.set_viewport_size({"width": 1280, "height": 720})
    user = _make_pa_user("pa")
    course, a, _b, _subject, _rows = _seed(user)
    quiz = make_quiz_unit(course=course, parent=None, title="Quiz Q")
    box = Element.objects.create(
        unit=a, content_object=CalloutElement.objects.create(kind="example")
    )
    Element.objects.create(
        unit=a,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    _login(page, live_server, "pa")
    page.goto(_editor(live_server, course, a))
    # Mark through the row's own clip control, as in the first test.
    row = page.locator(f".el-row[data-element='{box.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        row.locator(CLIP_BUTTON).click()
    page.goto(_editor(live_server, course, quiz))

    expect(page.locator("#clip-banner .clip-banner__nothing")).to_be_visible()
    assert _inside(
        _box(page, "#clip-banner .clip-banner__line form button"),
        _box(page, "#clip-banner .clip-banner__line"),
    )
