"""Course-builder tree mutations with optimistic-concurrency token checks."""

from django.db import transaction
from django.utils.dateparse import parse_datetime

from courses import ordering
from courses.models import ContentNode
from courses.models import Element
from courses.models import TabsElement
from courses.models import TwoColumnElement
from courses.models import _delete_element_content_objects

_UNSET = object()


class ConflictError(Exception):
    """Optimistic-concurrency conflict → HTTP 409."""


class NestingError(Exception):
    """A nested add/save violated the nesting rules -> HTTP 400."""


# Positive allowlist: any type NOT named here is non-nestable, including types added
# by future slices. Deliberately NOT the element_add/element_save allow-tuples, which
# admit every question type and slidebreak.
#
# Members are TRANSFER keys (courses.transfer.export.SERIALIZERS), not the
# element_add/element_save "type" strings -- an invariant test asserts
# NESTABLE_TYPE_KEYS <= set(SERIALIZERS). Every type here coincides in both
# namespaces except the reveal-gate, whose transfer key ("reveal_gate") differs
# from its form key ("revealgate"); resolve_scope() below translates the
# incoming form key before checking membership.
NESTABLE_TYPE_KEYS = frozenset(
    {
        "text",
        "math",
        "image",
        "video",
        "iframe",
        "html",
        "table",
        "gallery",
        "callout",
        "spoiler",
        "reveal_gate",
        "fill_gate",
        "switch_gate",
        "switch_grid",
        "fill_table",
        "stepper",
    }
)

# Form key -> transfer key, for the types where the two namespaces diverge.
_NESTABLE_FORM_KEY_ALIASES = {
    "revealgate": "reveal_gate",
    "fillgate": "fill_gate",
    "switchgate": "switch_gate",
    "switchgrid": "switch_grid",
    "filltable": "fill_table",
}

# Container element registry: model class -> (non_destructive_normalizer,
# slot_list_key, slot_id_key). CONTRACT: each normalizer returns
# {slot_list_key: [{slot_id_key: <id>}, ...]}. resolve_scope indexes the normalizer
# output by slot_list_key, so slot_list_key MUST equal the key the normalizer emits.
_CONTAINER_REGISTRY = {
    TabsElement: (TabsElement.normalize_labels_and_ids, "tabs", "id"),
    TwoColumnElement: (TwoColumnElement.normalize_ids, "columns", "id"),
}


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
    # normalize_data (behind normalized_data) is DESTRUCTIVE and read-side only: it
    # pads/truncates and mints fresh random ids on every call, so a slot validated
    # against it here could be an ephemeral phantom that never matches again at
    # render time -- silently orphaning the child. A write path must validate
    # against the ids that actually exist, via the non-destructive normalizer.
    container = _CONTAINER_REGISTRY.get(type(parent_obj))
    if container is None:
        raise NestingError("parent is not a container")
    normalizer, list_key, id_key = container
    valid_slot_ids = {s[id_key] for s in normalizer(parent_obj.data)[list_key]}
    if tab not in valid_slot_ids:
        raise NestingError("unknown slot")
    nestable_key = _NESTABLE_FORM_KEY_ALIASES.get(type_key, type_key)
    if nestable_key not in NESTABLE_TYPE_KEYS:
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

    def __init__(self, form, formset=None, formset2=None):
        self.form = form
        self.formset = formset
        self.formset2 = formset2
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
    elif type_key == "choicegridquestion":
        from courses.element_forms import ChoiceGridQuestionElementForm
        from courses.element_forms import build_choicegrid_columns_formset
        from courses.element_forms import build_choicegrid_rows_formset

        form = ChoiceGridQuestionElementForm(data=post_data, instance=instance)
        col_fs = build_choicegrid_columns_formset(
            data=post_data, files=files, instance=instance
        )
        row_fs = build_choicegrid_rows_formset(
            data=post_data, files=files, instance=instance
        )
        if not form.is_valid() or not col_fs.is_valid() or not row_fs.is_valid():
            raise ElementFormInvalid(form, col_fs, row_fs)  # 422; both bound formsets

        obj = form.save()

        # 1) Save/keep columns WITHOUT applying deletions yet (commit=False defers
        #    deletions), so rows can be re-pointed off any to-be-deleted column BEFORE
        #    PROTECT bites.
        col_fs.instance = obj
        kept_cols = col_fs.save(commit=False)  # new/changed instances only
        for col in kept_cols:
            col.save()
        # temp_id -> surviving GridColumn, from the NON-deleted column forms.
        temp_map = {}
        for f in col_fs.forms:
            cd = f.cleaned_data
            if not cd or cd.get("DELETE") or not cd.get("label"):
                continue
            temp_map[cd.get("temp_id") or str(f.instance.pk)] = f.instance

        # 2) Re-point + save EVERY non-deleted row against a surviving column; delete
        #    the rows marked for deletion. (Iterating row_fs.forms — not just the
        #    save(commit=False) changed set — so an unchanged row whose column was
        #    removed is still validated against surviving columns.)
        row_fs.instance = obj
        # populate .instance (incl. inline FK) on each form; persist nothing yet
        row_fs.save(commit=False)
        for rf in row_fs.forms:
            cd = rf.cleaned_data
            if not cd:
                continue
            if cd.get("DELETE"):
                if rf.instance.pk:
                    rf.instance.delete()
                continue
            if not cd.get("statement"):
                continue
            col = temp_map.get(cd.get("correct_temp_id"))
            if col is None:  # temp-id resolves to no surviving column
                raise ElementFormInvalid(form, col_fs, row_fs)  # 422, atomic rollback
            rf.instance.correct_column = col
            rf.instance.save()

        # 3) ONLY NOW apply column deletions — every surviving row points at a surviving
        #    column, so PROTECT is satisfied.
        for dead_col in col_fs.deleted_objects:
            dead_col.delete()
    elif type_key == "multigridquestion":
        from courses.element_forms import MultiGridQuestionElementForm
        from courses.element_forms import _parse_temp_ids
        from courses.element_forms import build_multigrid_columns_formset
        from courses.element_forms import build_multigrid_rows_formset

        form = MultiGridQuestionElementForm(data=post_data, instance=instance)
        col_fs = build_multigrid_columns_formset(
            data=post_data, files=files, instance=instance
        )
        row_fs = build_multigrid_rows_formset(
            data=post_data, files=files, instance=instance
        )
        if not form.is_valid() or not col_fs.is_valid() or not row_fs.is_valid():
            raise ElementFormInvalid(form, col_fs, row_fs)

        obj = form.save()

        # 1) Save/keep columns without applying deletions yet (deletions deferred).
        col_fs.instance = obj
        kept_cols = col_fs.save(commit=False)
        for col in kept_cols:
            col.save()
        # temp_id -> surviving MultiGridColumn, from NON-deleted column forms.
        temp_map = {}
        for f in col_fs.forms:
            cd = f.cleaned_data
            if not cd or cd.get("DELETE") or not cd.get("label"):
                continue
            temp_map[cd.get("temp_id") or str(f.instance.pk)] = f.instance

        # 2) Resolve + set the M2M for EVERY non-deleted row form (not just changed):
        #    deleting a column cascade-clears the M2M for untouched rows too, so each
        #    must be re-validated against surviving columns.
        row_fs.instance = obj
        row_fs.save(commit=False)  # populate .instance (incl. inline FK); persist none
        for rf in row_fs.forms:
            cd = rf.cleaned_data
            if not cd:
                continue
            if cd.get("DELETE"):
                if rf.instance.pk:
                    rf.instance.delete()
                continue
            if not cd.get("statement"):
                continue
            resolved = [
                temp_map[t]
                for t in _parse_temp_ids(cd.get("correct_temp_ids"))
                if t in temp_map
            ]
            if not resolved:  # zero surviving correct columns -> invalid
                raise ElementFormInvalid(form, col_fs, row_fs)
            rf.instance.save()  # need a pk before .set()
            rf.instance.correct_columns.set(resolved)

        # 3) Only now apply column deletions (M2M through-rows drop automatically).
        for dead_col in col_fs.deleted_objects:
            dead_col.delete()
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
    elif type_key == "twocolumn":
        form = FORM_FOR_TYPE["twocolumn"](data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        count = form.cleaned_data["column_count"]
        obj = form.save(commit=False)  # binds no fields; does not write `data`
        # Derive the column list from the EXISTING persisted list (create -> default).
        if instance is None:
            existing = TwoColumnElement.default_data()["columns"]
        else:
            existing = TwoColumnElement.normalize_ids(instance.data)["columns"]
            if len(existing) < TwoColumnElement.MIN_COLUMNS:
                existing = TwoColumnElement.default_data()["columns"]
        taken = {c["id"] for c in existing}
        if count > len(existing):  # GROW
            new_columns = list(existing)
            while len(new_columns) < count:
                cid = TwoColumnElement.new_column_id(taken)
                taken.add(cid)
                new_columns.append({"id": cid})
            dropped = []
        else:  # SHRINK (drop trailing)
            new_columns = existing[:count]
            dropped = existing[count:]
        obj.data = {"columns": new_columns}
        obj.save()  # non-destructive normalize_ids keeps these ids
        # Move dropped columns' children to the new last column (never delete).
        if join is not None and dropped:
            new_last = new_columns[-1]["id"]
            target = list(
                Element.objects.filter(parent=join, tab_id=new_last).order_by(
                    "order", "pk"
                )
            )
            moved = []
            for col in dropped:  # original column order
                moved.extend(
                    Element.objects.filter(parent=join, tab_id=col["id"]).order_by(
                        "order", "pk"
                    )
                )
            for child in moved:
                child.tab_id = new_last
            if moved:
                Element.objects.bulk_update(moved, ["tab_id"])
                ordering.assign_orders_elements(target + moved)
    elif type_key == "stepper":
        from courses.element_forms import StepperElementForm
        from courses.element_forms import build_stepper_formset

        form = StepperElementForm(data=post_data, instance=instance)
        form_valid = form.is_valid()
        formset = build_stepper_formset(data=post_data, files=files, instance=instance)
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save()
        formset.instance = obj
        # Persist steps with explicit 0-based order = submitted row position; drop
        # blank rows, delete rows flagged DELETE. Deterministic + gap-free.
        idx = 0
        for f in formset.forms:
            cd = f.cleaned_data
            if not cd:
                continue
            if cd.get("DELETE"):
                if f.instance.pk:
                    f.instance.delete()
                continue
            if not (cd.get("content") or "").strip():
                if f.instance.pk:
                    f.instance.delete()
                continue
            f.instance.stepper = obj
            f.instance.content = cd["content"]
            f.instance.order = idx
            f.instance.save()
            idx += 1
    elif type_key == "markdone":
        from courses.element_forms import MarkDoneElementForm
        from courses.element_forms import build_markdone_formset

        form = MarkDoneElementForm(data=post_data, instance=instance)
        form_valid = form.is_valid()
        formset = build_markdone_formset(data=post_data, files=files, instance=instance)
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save()
        formset.instance = obj
        # Persist items with explicit 0-based order = submitted row position; drop
        # blank rows, delete rows flagged DELETE. Deterministic + gap-free.
        idx = 0
        for f in formset.forms:
            cd = f.cleaned_data
            if not cd:
                continue
            if cd.get("DELETE"):
                if f.instance.pk:
                    f.instance.delete()
                continue
            if not (cd.get("content") or "").strip():
                if f.instance.pk:
                    f.instance.delete()
                continue
            f.instance.element = obj
            f.instance.content = cd["content"]
            f.instance.order = idx
            f.instance.save()
            idx += 1
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
