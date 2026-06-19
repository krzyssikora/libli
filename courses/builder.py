from django.db import transaction
from django.utils.dateparse import parse_datetime

from courses import ordering
from courses.models import ContentNode
from courses.models import Element

_UNSET = object()


class ConflictError(Exception):
    """Optimistic-concurrency conflict → HTTP 409."""


def _check_token(current_dt, token):
    expected = parse_datetime(token) if token else None
    if expected is None or expected != current_dt:
        raise ConflictError()


@transaction.atomic
def add_node(course, parent_ref, kind, title, unit_type, parent_token):
    if parent_ref in (None, "", "top"):
        parent = None
        # No token check for the `top` destination. The course is the destination and
        # always exists (loaded by the view), so there's no "destination gone" case to
        # guard; `parent_token` here was only a concurrent-top-add nicety. The top-level
        # add form lives OUTSIDE the swapped `[data-scope="top"]` <ol>, so a fragment
        # swap can't refresh its token — after the first top add bumps course.updated a
        # strict check would 409 every later top add until a full reload. Top adds are
        # non-conflicting appends, so we skip the check (mirrors the reparent
        # destination-token decision). Node-level ops keep their token guard (their
        # forms ARE refreshed by the swap).
    else:
        try:
            parent = ContentNode.objects.select_for_update().get(
                pk=parent_ref, course=course
            )
        except ContentNode.DoesNotExist:
            raise ConflictError() from None
        _check_token(parent.updated, parent_token)
    node = ContentNode(
        course=course,
        parent=parent,
        kind=kind,
        title=title,
        unit_type=(unit_type or None),
    )
    # `order` is None until OrderField.pre_save assigns it during save(); exclude it
    # so validation doesn't trip on the not-yet-assigned non-null field.
    node.full_clean(exclude=["order"])  # ValidationError -> 422
    node.save()  # OrderField assigns end-of-scope order
    if parent is None:
        course.save(update_fields=["updated"])
    return node


@transaction.atomic
def rename_node(
    course,
    node_pk,
    title,
    token,
    unit_type=_UNSET,
    obligatory=_UNSET,
    html_seed_js=_UNSET,
):
    node = _locked_node(course, node_pk)
    _check_token(node.updated, token)
    node.title = title
    fields = ["title", "updated"]
    if node.kind == ContentNode.Kind.UNIT:
        if unit_type is not _UNSET:
            node.unit_type = unit_type
            fields.append("unit_type")
        if obligatory is not _UNSET:
            node.obligatory = obligatory
            fields.append("obligatory")
        if html_seed_js is not _UNSET:
            node.html_seed_js = html_seed_js
            fields.append("html_seed_js")
    node.full_clean()
    node.save(update_fields=fields)  # cannot clobber a concurrent order
    return node


@transaction.atomic
def reorder_node(course, node_pk, direction, token):
    node = _locked_node(course, node_pk)
    _check_token(node.updated, token)
    siblings = list(
        ContentNode.objects.select_for_update()
        .filter(course=course, parent=node.parent)
        .order_by("order", "pk")
    )
    moved = ordering.move_in_list(siblings, node, direction)
    if moved is None:
        return node, False  # boundary no-op: no save, no token bump
    ordering.assign_orders_nodes(moved)
    # Guarantee the moved node's own token advances on an applied reorder — even in the
    # equal-`order` tie case where its numeric order is unchanged (only a neighbour's
    # changed) and assign_orders_nodes therefore didn't re-save it. The spec's
    # applied-vs-boundary-no-op distinction relies on the moved node's `updated`.
    node.save(update_fields=["updated"])
    if node.parent_id is None:
        course.save(update_fields=["updated"])
    return node, True


@transaction.atomic
def reparent_node(course, node_pk, new_parent_ref, position, node_token, parent_token):
    node = _locked_node(course, node_pk)
    _check_token(node.updated, node_token)
    old_parent_id = node.parent_id
    if new_parent_ref in (None, "", "top"):
        new_parent = None
        dest_updated = course.updated
    else:
        try:
            new_parent = ContentNode.objects.select_for_update().get(
                pk=new_parent_ref, course=course
            )
        except ContentNode.DoesNotExist:
            raise ConflictError() from None
        dest_updated = new_parent.updated
        ordering.assert_not_descendant(node, new_parent)  # ValidationError -> 422
    # Destination existence is already guaranteed by the locked re-fetch above (a
    # vanished destination yields 409). The strict stale-check is conditional: the no-JS
    # Move picker sends no `parent_token` (existence-only), while JS injects the
    # selected option's token for the bonus strict check. The moved node's
    # `node_token` check above stays mandatory.
    if parent_token:
        _check_token(dest_updated, parent_token)
    node.parent = new_parent
    node.full_clean()  # kind-depth -> 422
    ordering.place_node(node, new_parent, course, position)
    ordering.compact_nodes(course, old_parent_id)
    course.save(update_fields=["updated"])
    return node, old_parent_id


@transaction.atomic
def delete_node(course, node_pk, token):
    node = _locked_node(course, node_pk)
    _check_token(node.updated, token)
    parent_id = node.parent_id
    node.delete()  # cascades children + their elements
    ordering.compact_nodes(course, parent_id)
    if parent_id is None:
        course.save(update_fields=["updated"])
    return parent_id


@transaction.atomic
def reorder_element(course, element_pk, unit_token, *, direction=None, position=None):
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    if position is not None:
        changed = ordering.place_element(el, unit, position)
    else:
        siblings = list(
            Element.objects.select_for_update()
            .filter(unit=unit)
            .order_by("order", "pk")
        )
        moved = ordering.move_in_list(siblings, el, direction)
        if moved is None:
            return unit, False
        ordering.assign_orders_elements(moved)
        changed = True
    if not changed:
        return unit, False
    unit.save(update_fields=["updated"])
    return unit, True


@transaction.atomic
def delete_element(course, element_pk, unit_token):
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    obj = el.content_object
    if obj is not None:
        obj.delete()  # cascades the Element join-row via GenericRelation
    else:
        el.delete()
    ordering.compact_elements(unit)
    unit.save(update_fields=["updated"])
    return unit


class ElementFormInvalid(Exception):
    """Carries the bound, invalid per-type form (with its instance) — and, for question
    types, the bound Choice formset — so the view re-renders the SAME bound pair at
    422."""

    def __init__(self, form, formset=None):
        self.form = form
        self.formset = formset
        super().__init__("element form invalid")


@transaction.atomic
def save_element(course, unit_pk, type_key, element_ref, post_data, files):
    """Create-on-first-save (element_ref == 'new') or update an existing Element.
    Token-checked against the unit; bumps unit.updated. Returns the unit.
    Raises ConflictError (409) on stale/vanished, ElementFormInvalid (422) on bad form.
    Raising inside @transaction.atomic rolls back, so a failed create leaves zero
    rows."""
    from courses.element_forms import FORM_FOR_TYPE  # avoid import cycle

    unit = _locked_unit(course, unit_pk)
    _check_token(unit.updated, post_data.get("unit_token"))
    if element_ref == "new":
        join, instance = None, None
    else:
        join = _locked_element_in_unit(unit, element_ref)
        instance = join.content_object
    if type_key == "choicequestion":
        from courses.element_forms import ChoiceQuestionElementForm
        from courses.element_forms import build_choice_formset

        is_create = join is None
        form = ChoiceQuestionElementForm(data=post_data, instance=instance)
        form_valid = form.is_valid()
        # multiple authority: derive from the VALIDATED form on create — its
        # BooleanField coerces the hidden field's "False"/"True" string correctly.
        # Do NOT parse the raw POST value: HiddenInput renders value="False", and
        # bool("False") is True, so a naive bool(post_data.get("multiple")) would
        # mis-save every single-choice as multi.
        # Pinned to the stored value on edit (the field is popped from the edit form).
        if is_create:
            multiple = bool(form.cleaned_data.get("multiple")) if form_valid else False
        else:
            multiple = instance.multiple
        formset = build_choice_formset(
            data=post_data, files=files, instance=instance, multiple=multiple
        )
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save(commit=False)
        obj.multiple = (
            multiple  # enforce the pinned value (field absent on the edit form)
        )
        obj.save()
        formset.instance = obj
        formset.save()
    else:
        extra = {"course": course} if type_key in ("image", "video") else {}
        form = FORM_FOR_TYPE[type_key](
            data=post_data, files=files, instance=instance, **extra
        )
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()  # concrete row saved (TextElement.save sanitises)
    title = (post_data.get("el_title") or "").strip()
    if join is None:
        Element.objects.create(unit=unit, content_object=obj, title=title)
    elif join.title != title:
        join.title = title
        join.save(update_fields=["title"])
    unit.save(update_fields=["updated"])
    return unit


def _locked_unit(course, unit_pk):
    try:
        return ContentNode.objects.select_for_update().get(
            pk=unit_pk, course=course, kind=ContentNode.Kind.UNIT
        )
    except ContentNode.DoesNotExist:
        raise ConflictError() from None


def _locked_element_in_unit(unit, element_pk):
    try:
        return Element.objects.select_for_update().get(pk=element_pk, unit=unit)
    except (Element.DoesNotExist, ValueError, TypeError):
        raise ConflictError() from None


def _locked_node(course, node_pk):
    try:
        return ContentNode.objects.select_for_update().get(pk=node_pk, course=course)
    except ContentNode.DoesNotExist:
        raise ConflictError() from None


def _locked_element(course, element_pk):
    try:
        el = (
            Element.objects.select_for_update()
            .select_related("unit")
            .get(pk=element_pk, unit__course=course)
        )
    except Element.DoesNotExist:
        raise ConflictError() from None
    return el, el.unit
