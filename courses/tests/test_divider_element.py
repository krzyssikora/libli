import pytest


@pytest.mark.django_db
def test_render_emits_a_horizontal_rule():
    """The student-facing render is a bare <hr> -- the element has no fields."""
    from courses.models import DividerElement

    html = DividerElement.objects.create().render()
    assert "<hr" in html


@pytest.mark.django_db
def test_renders_through_the_tag_in_quiz_mode(client):
    """The Add menu's Content group is NOT gated on `unit_is_quiz`, so a divider is
    authorable in a quiz -- and the quiz page renders EVERY element in a slide, not
    just questions. render_element hands non-container leaves exactly
    ElementBase.render's four kwargs (`page` goes only to CONTAINER_MODELS), so this
    proves the leaf survives the quiz call path rather than 500ing on an unexpected
    kwarg."""
    from django.template import Context
    from django.template import Template

    from courses.models import DividerElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    course = CourseFactory()
    quiz = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    join = add_element(quiz, DividerElement.objects.create())

    rendered = Template(
        '{% load courses_extras %}{% render_element el mode="quiz" %}'
    ).render(Context({"el": join}))

    assert "<hr" in rendered


def test_registered_in_every_transfer_registry_and_nestable():
    """A type missing from any one of these vanishes silently on export/import."""
    from courses.builder import NESTABLE_TYPE_KEYS
    from courses.transfer.export import SERIALIZERS
    from courses.transfer.importer import BUILDERS
    from courses.transfer.payloads import VALIDATORS

    assert "divider" in SERIALIZERS
    assert "divider" in VALIDATORS
    assert "divider" in BUILDERS
    assert "divider" in NESTABLE_TYPE_KEYS
    # the standing invariant: a nestable key with no serializer breaks paste
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_transfer_round_trip():
    from courses.models import DividerElement
    from courses.transfer.export import SERIALIZERS
    from courses.transfer.importer import BUILDERS
    from courses.transfer.payloads import VALIDATORS

    model, ser = SERIALIZERS["divider"]
    assert model is DividerElement
    payload = ser(DividerElement.objects.create(), {})
    assert payload == {}
    # The validator is the hop between export and import: a key the importer knows
    # but the validator does not raises TransferError on a real import, which the
    # serializer/builder pair alone would never show.
    VALIDATORS["divider"](payload, "e1", set())
    built, media = BUILDERS["divider"](payload, {})
    assert isinstance(built, DividerElement) and built.pk is not None
    assert media == ()


def test_form_key_matches_the_transfer_key():
    """No _NESTABLE_FORM_KEY_ALIASES entry is needed -- resolve_scope looks the
    incoming form key up directly. If the keys ever diverge, the alias is required
    and a nested divider starts 400ing."""
    from courses.element_forms import FORM_FOR_TYPE
    from courses.transfer.export import SERIALIZERS

    assert "divider" in FORM_FOR_TYPE
    assert "divider" in SERIALIZERS


def _lesson_unit(course):
    from tests.factories import ContentNodeFactory

    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _save(client, course, unit, **extra):
    from django.urls import reverse

    return client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "divider",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            **extra,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )


@pytest.mark.django_db
def test_save_creates_a_top_level_divider(client):
    from courses.models import DividerElement
    from courses.models import Element
    from tests.factories import CourseFactory
    from tests.factories import make_pa

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)

    assert _save(client, course, unit).status_code == 200

    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, DividerElement)
    assert el.parent is None


@pytest.mark.django_db
def test_save_creates_a_divider_nested_in_a_callout(client):
    """The case the element was added for -- a rule between a callout's children."""
    from courses.models import CalloutElement
    from courses.models import DividerElement
    from courses.models import Element
    from tests.factories import CourseFactory
    from tests.factories import add_element
    from tests.factories import make_pa

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    callout_join = add_element(unit, CalloutElement.objects.create(kind="example"))
    unit.refresh_from_db()

    resp = _save(
        client,
        course,
        unit,
        parent=str(callout_join.pk),
        tab=CalloutElement.SLOT_ID,
    )
    assert resp.status_code == 200

    el = Element.objects.get(unit=unit, parent=callout_join)
    assert isinstance(el.content_object, DividerElement)
    assert el.tab_id == CalloutElement.SLOT_ID


def _add_menu(**ctx):
    from django.template.loader import render_to_string

    return render_to_string(
        "courses/manage/editor/_add_menu.html",
        {"depth": 1, "max_nest_depth": 4, "parent": 7, "tab": "body", **ctx},
    )


def test_add_menu_offers_the_divider_inside_a_container():
    """The Structure group lives inside `{% if not nested %}`, so a Divider card
    placed there would render at top level and NEVER inside a callout -- the one
    case the element exists for. It belongs in the Content group instead."""
    assert 'data-add-type="divider"' in _add_menu(nested=True)


def test_add_menu_offers_the_divider_at_top_level():
    assert 'data-add-type="divider"' in _add_menu(nested=False)


@pytest.mark.django_db
def test_editor_row_shows_a_divider_with_no_edit_button(client):
    """Field-less: the row is a labelled rule, and offering an Edit button would
    open a form with nothing in it."""
    from django.urls import reverse

    from courses.models import DividerElement
    from tests.factories import CourseFactory
    from tests.factories import add_element
    from tests.factories import make_pa

    pa = make_pa(client, "pa")
    course = CourseFactory(slug="c1", owner=pa)
    unit = _lesson_unit(course)
    join = add_element(unit, DividerElement.objects.create())

    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c1", "pk": unit.pk})
    )
    body = resp.content.decode()

    assert "element-row--divider" in body
    row = body.split(f'data-element="{join.pk}"', 1)[1].split("</li>", 1)[0]
    assert "el-act-edit" not in row  # the pencil that opens the (empty) form
