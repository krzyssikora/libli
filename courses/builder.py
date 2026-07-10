"""Course-builder tree mutations with optimistic-concurrency token checks."""

from django.db import transaction
from django.utils.dateparse import parse_datetime

from courses import ordering
from courses.models import ContentNode
from courses.models import Element
from courses.models import TabsElement
from courses.models import _delete_element_content_objects

_UNSET = object()


class ConflictError(Exception):
    """Optimistic-concurrency conflict → HTTP 409."""


class NestingError(Exception):
    """A nested add/save violated the nesting rules -> HTTP 400."""


# Positive allowlist: any type NOT named here is non-nestable, including types added
# by future slices. Deliberately NOT the element_add/element_save allow-tuples, which
# admit every question type and slidebreak.
NESTABLE_TYPE_KEYS = frozenset(
    {"text", "math", "image", "video", "iframe", "html", "table", "gallery"}
)


def resolve_scope(unit, parent_ref, tab, type_key):
    """Validate and resolve a nested element's scope.

    Returns (parent_join|None, tab_id).

    `parent` and `tab` come together or not at all; neither means top-level. Any
    violation raises NestingError, which the view turns into a 400. Filtering the
    parent by `unit` enforces same-unit and (transitively) same-course, because `unit`
    was already resolved against the course by the caller.
    """
    parent_ref = (parent_ref or "").strip()
    tab = (tab or "").strip()
    if not parent_ref and not tab:
        return None, ""
    if not parent_ref or not tab:
        raise NestingError("parent and tab must be supplied together")
    try:
        join = Element.objects.filter(pk=int(parent_ref), unit=unit).first()
    except (TypeError, ValueError):
        raise NestingError("bad parent ref") from None
    if join is None:
        raise NestingError("unknown parent")
    parent_obj = join.content_object
    if not isinstance(parent_obj, TabsElement):
        raise NestingError("parent is not a tabs element")
    # normalize_data (behind normalized_data) is DESTRUCTIVE and read-side only: it
    # pads/truncates and mints fresh random ids on every call, so a tab validated
    # against it here could be an ephemeral phantom that never matches again at
    # render time -- silently orphaning the child. A write path must validate
    # against the ids that actually exist, via the non-destructive normalizer.
    valid_tab_ids = {
        t["id"] for t in TabsElement.normalize_labels_and_ids(parent_obj.data)["tabs"]
    }
    if tab not in valid_tab_ids:
        raise NestingError("unknown tab")
    if type_key not in NESTABLE_TYPE_KEYS:
        raise NestingError(f"{type_key} may not be nested")
    return join, tab


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
    fields = ["updated"]
    if title is not _UNSET:
        node.title = title
        fields.append("title")
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
    """Reorder WITHIN the element's own scope. Takes no parent/tab: a reorder gesture
    never sends them (top-level reorders never have), so scope is read off the row.
    That is also what makes a cross-scope move impossible by construction."""
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    if position is not None:
        changed = ordering.place_element(el, unit, position)
    else:
        siblings = list(
            ordering.element_siblings(unit, el.parent, el.tab_id)
            .select_for_update()
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
    """Delete an element. If it is a tabs element, its children's CONCRETE rows must
    go first: the `parent` FK cascades the child join rows, but a concrete is only
    reachable through the GFK, which DB cascade cannot traverse -- they would orphan.
    """
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    parent, tab_id = el.parent, el.tab_id  # capture before the row disappears
    _delete_element_content_objects(Element.objects.filter(parent=el))
    obj = el.content_object
    if obj is not None:
        obj.delete()  # cascades the Element join-row via GenericRelation
    else:
        el.delete()
    ordering.compact_elements(unit, parent=parent, tab_id=tab_id)
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
    elif type_key == "fillblankquestion":
        from courses.element_forms import FillBlankQuestionElementForm

        form = FillBlankQuestionElementForm(data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()  # token-stem stored; QuestionElement.save() sanitises
        obj.blanks.all().delete()  # rebuild from the freshly-parsed markers
        from courses.models import Blank

        for pieces in form.parsed_blanks:
            Blank.objects.create(question=obj, accepted="\n".join(pieces))
    elif type_key == "dragfillblankquestion":
        from courses.element_forms import DragFillBlankQuestionElementForm

        form = DragFillBlankQuestionElementForm(data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()  # token-stem stored; QuestionElement.save() sanitises
        obj.dragblanks.all().delete()  # rebuild from the freshly-parsed markers
        from courses.models import DragBlank

        for token in form.parsed_dragblanks:
            DragBlank.objects.create(question=obj, correct_token=token)
    elif type_key == "matchpairquestion":
        from courses.element_forms import MatchPairQuestionElementForm
        from courses.element_forms import build_matchpair_formset

        form = MatchPairQuestionElementForm(data=post_data, instance=instance)
        form_valid = form.is_valid()
        formset = build_matchpair_formset(
            data=post_data, files=files, instance=instance
        )
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save()
        formset.instance = obj
        formset.save()
    elif type_key == "dragtoimagequestion":
        from courses.element_forms import DragToImageQuestionElementForm
        from courses.element_forms import build_dragzone_formset

        form = DragToImageQuestionElementForm(
            data=post_data, files=files, instance=instance, course=course
        )
        form_valid = form.is_valid()
        formset = build_dragzone_formset(data=post_data, files=files, instance=instance)
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save()
        formset.instance = obj
        formset.save()
    elif type_key == "tabs":
        # Capture the OLD tab ids BEFORE the form mutates instance.data on save.
        old_ids = (
            set()
            if instance is None
            else {
                t["id"]
                for t in TabsElement.normalize_labels_and_ids(instance.data)["tabs"]
            }
        )
        form = FORM_FOR_TYPE["tabs"](data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()
        if join is not None:
            # clean_data already minted ids for new rows, so new_ids is complete and a
            # brand-new tab can never be mistaken for a removal.
            new_ids = {t["id"] for t in obj.data["tabs"]}
            removed = old_ids - new_ids
            if removed:
                # Concretes first -- the join rows cascade, the concretes would orphan.
                doomed = Element.objects.filter(parent=join, tab_id__in=removed)
                _delete_element_content_objects(doomed)
                Element.objects.filter(parent=join, tab_id__in=removed).delete()
    else:
        extra = {"course": course} if type_key in ("image", "video", "gallery") else {}
        form = FORM_FOR_TYPE[type_key](
            data=post_data, files=files, instance=instance, **extra
        )
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()  # concrete row saved (TextElement.save sanitises)
    title = (post_data.get("el_title") or "").strip()
    if join is None:
        # Scope is chosen ONCE, at creation, and is immutable thereafter.
        parent_join, tab_id = resolve_scope(
            unit, post_data.get("parent"), post_data.get("tab"), type_key
        )
        Element.objects.create(
            unit=unit,
            content_object=obj,
            title=title,
            parent=parent_join,
            tab_id=tab_id,
        )
    elif join.title != title:
        join.title = title
        join.save(update_fields=["title"])
    # NOTE: the update path deliberately never touches join.parent / join.tab_id. The
    # inline edit form does not resubmit them; writing "absent means top-level" here
    # would silently reparent every nested child on every edit.
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
