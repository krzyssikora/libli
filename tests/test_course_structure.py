import pytest
from django.template import Context  # noqa: E402
from django.template import Template  # noqa: E402

from courses.models import ContentNode
from courses.models import Course
from courses.structure_backfill import backfill_structure_flags

pytestmark = pytest.mark.django_db


def _add(course, kind, parent=None):
    extra = {"unit_type": "lesson"} if kind == "unit" else {}
    return ContentNode.objects.create(
        course=course, kind=kind, title=kind, parent=parent, **extra
    )


def test_allowed_kinds_full_default():
    c = Course.objects.create(title="C", slug="c-full")
    assert c.allowed_kinds == ["part", "chapter", "section", "unit"]


def test_allowed_kinds_flat():
    c = Course.objects.create(
        title="C",
        slug="c-flat",
        uses_parts=False,
        uses_chapters=False,
        uses_sections=False,
    )
    assert c.allowed_kinds == ["unit"]


def test_allowed_kinds_chapters():
    c = Course.objects.create(
        title="C",
        slug="c-ch",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    assert c.allowed_kinds == ["chapter", "unit"]


def test_backfill_units_only_to_flat():
    c = Course.objects.create(title="C", slug="c1")
    _add(c, "unit")
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (False, False, False)


def test_backfill_chapters_only():
    c = Course.objects.create(title="C", slug="c2")
    ch = _add(c, "chapter")
    _add(c, "unit", parent=ch)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (False, True, False)


def test_backfill_parts_chapters():
    c = Course.objects.create(title="C", slug="c3")
    p = _add(c, "part")
    ch = _add(c, "chapter", parent=p)
    _add(c, "unit", parent=ch)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, False)


def test_backfill_mixed_custom():
    c = Course.objects.create(title="C", slug="c5")
    p = _add(c, "part")
    s = _add(c, "section", parent=p)
    _add(c, "unit", parent=s)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, False, True)


def test_backfill_empty_course_keeps_full():
    c = Course.objects.create(title="C", slug="c4")
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, True)


def _render_affordance(course, parent_kind):
    tpl = Template("{% include 'courses/manage/_add_affordance.html' %}")
    return tpl.render(
        Context(
            {
                "course": course,
                "parent_kind": parent_kind,
                "scope_id": "top",
                "scope_updated": "x",
            }
        )
    )


def test_affordance_flat_course_only_unit_chips():
    c = Course.objects.create(
        title="C",
        slug="c-aff-flat",
        uses_parts=False,
        uses_chapters=False,
        uses_sections=False,
    )
    html = _render_affordance(c, None)
    assert 'data-add-kind="lesson"' in html
    assert 'data-add-kind="quiz"' in html
    assert 'data-add-kind="chapter"' not in html
    assert 'data-add-kind="part"' not in html


def test_affordance_full_course_offers_part_and_chapter():
    c = Course.objects.create(title="C", slug="c-aff-full")
    html = _render_affordance(c, None)
    assert 'data-add-kind="chapter"' in html
    assert 'data-add-kind="part"' in html


from courses.forms import CourseForm  # noqa: E402


def _form_data(**over):
    data = {"title": "C", "slug": "", "language": "en", "visibility": "assigned"}
    data.update(over)
    return data


def test_create_form_writes_chapters_preset():
    form = CourseForm(data=_form_data(slug="new-ch", structure="chapters"))
    assert form.is_valid(), form.errors
    course = form.save(commit=False)
    course.save()
    assert (course.uses_parts, course.uses_chapters, course.uses_sections) == (
        False,
        True,
        False,
    )


def test_create_form_requires_structure():
    form = CourseForm(data=_form_data(slug="no-struct"))  # no structure
    assert not form.is_valid()
    assert "structure" in form.errors


def test_settings_save_without_preset_preserves_flags():
    c = Course.objects.create(
        title="C",
        slug="c-keep",
        uses_parts=True,
        uses_chapters=False,
        uses_sections=True,  # Custom
    )
    form = CourseForm(data=_form_data(slug="c-keep"), instance=c)  # no structure
    assert form.is_valid(), form.errors
    form.save()
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, False, True)


def test_narrowing_guard_blocks_in_use_level():
    c = Course.objects.create(title="C", slug="c-narrow")  # Full
    ContentNode.objects.create(course=c, kind="chapter", title="Ch")
    form = CourseForm(data=_form_data(slug="c-narrow", structure="flat"), instance=c)
    assert not form.is_valid()
    assert "level" in str(form.errors).lower()


def test_widening_always_allowed():
    c = Course.objects.create(
        title="C",
        slug="c-widen",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    form = CourseForm(data=_form_data(slug="c-widen", structure="full"), instance=c)
    assert form.is_valid(), form.errors
    form.save()
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, True)


from django.urls import reverse  # noqa: E402

from tests.factories import CourseFactory  # noqa: E402
from tests.factories import make_login  # noqa: E402

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def test_node_add_rejects_excluded_kind(client):
    owner = make_login(client, "structowner")
    course = CourseFactory(
        slug="c-guard",
        owner=owner,
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,  # Chapters
    )
    url = reverse("courses:manage_node_add", kwargs={"slug": "c-guard"})
    bad = client.post(
        url,
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "part",
            "title": "P",
        },
        **FETCH,
    )
    assert bad.status_code == 422
    assert not ContentNode.objects.filter(course=course, kind="part").exists()

    ok = client.post(
        url,
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "chapter",
            "title": "Ch",
        },
        **FETCH,
    )
    assert ok.status_code == 200
    assert ContentNode.objects.filter(course=course, kind="chapter").exists()


from django.utils import translation  # noqa: E402


def _render_legend(course):
    tpl = Template("{% include 'courses/manage/_structure_legend.html' %}")
    return tpl.render(Context({"course": course}))


def test_structure_legend_renders_configured_chain():
    c = Course.objects.create(
        title="C",
        slug="c-leg",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    html = _render_legend(c)
    assert "Chapter" in html
    assert "Unit" in html
    assert "Part" not in html


def test_structure_legend_polish_kind_labels():
    c = Course.objects.create(title="C", slug="c-leg-pl")  # Full
    with translation.override("pl"):
        html = _render_legend(c)
    assert "Rozdział" in html  # "Chapter" in PL (existing translation)


def test_structure_label_polish():
    c = Course.objects.create(title="C", slug="c-leg-pl2")
    with translation.override("pl"):
        html = _render_legend(c)
    assert "Struktura" in html


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "slug",
        "subjects",
        "language",
        "overview",
        "visibility",
        "self_enroll_cohorts",
        "owner",
        "html_css",
        "html_js",
    ],
)
def test_course_form_labels_translated_to_pl(field):
    # Regression: the CourseForm fields render English auto-derived labels under
    # the Polish locale because the model fields have no translatable verbose_name
    # and the form set no labels. Every visible field label must differ EN vs PL.
    from courses.forms import CourseForm

    with translation.override("en"):
        en = str(CourseForm().fields[field].label)
    with translation.override("pl"):
        pl = str(CourseForm().fields[field].label)
    assert pl and pl != en, f"{field} label not translated to PL (EN={en!r}, PL={pl!r})"


_NOTE_FRAGMENT = "Removing a level is only possible"


@pytest.mark.django_db
def test_depth_note_shown_when_editing():
    from accounts.models import User
    from courses.forms import CourseForm
    from courses.models import Course
    from tests.factories import TEST_PASSWORD

    owner = User.objects.create_user(username="own", password=TEST_PASSWORD)
    course = Course.objects.create(title="C", slug="c", owner=owner)
    form = CourseForm(instance=course)
    assert _NOTE_FRAGMENT in str(form.fields["structure"].help_text)


@pytest.mark.django_db
def test_depth_note_absent_when_creating():
    from courses.forms import CourseForm

    form = CourseForm()
    assert _NOTE_FRAGMENT not in str(form.fields["structure"].help_text)
