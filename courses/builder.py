"""Course-builder tree mutations with optimistic-concurrency token checks."""

from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

from courses import ordering
from courses.models import ContentNode
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TwoColumnElement
from courses.models import _delete_element_content_objects

_UNSET = object()


class ConflictError(Exception):
    """Optimistic-concurrency conflict → HTTP 409."""


class NestingError(Exception):
    """A nested add/save violated the nesting rules -> HTTP 400."""


MAX_NEST_DEPTH = 4  # a top-level element has depth 1

# Container TYPE KEYS (transfer namespace). Clause 4 of the containment rule tests
# membership here. PR2 (Callout as a container) must add its key to THIS set, to
# _CONTAINER_REGISTRY and to payloads._CONTAINER_SLOT_KEY -- all three. The drift
# test in test_nesting_rule.py is what stops it landing in only two.
CONTAINER_TRANSFER_KEYS = frozenset({"tabs", "two_column", "spoiler"})

# Positive allowlist: any type NOT named here is non-nestable, including types added
# by future slices. Deliberately NOT the element_add/element_save allow-tuples, which
# admit every question type and slidebreak.
#
# Members are TRANSFER keys (courses.transfer.export.SERIALIZERS), not the
# element_add/element_save "type" strings -- an invariant test asserts
# NESTABLE_TYPE_KEYS <= set(SERIALIZERS). Several types' form key differs from
# their transfer key (fill_blank, fill_gate, fill_table, guess_number, mark_done,
# reveal_gate, switch_gate, switch_grid, two_column -- see
# _NESTABLE_FORM_KEY_ALIASES below); resolve_scope() translates the incoming form
# key before checking membership.
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
        "fill_blank",
        "fill_table",
        "stepper",
        "mark_done",
        "guess_number",
        # Containers, as of the depth-3 slice. Both are already in
        # transfer.export.SERIALIZERS, so NESTABLE_TYPE_KEYS <= SERIALIZERS holds.
        "tabs",
        "two_column",
    }
)

# Form key -> transfer key, for the types where the two namespaces diverge.
_NESTABLE_FORM_KEY_ALIASES = {
    "fillblankquestion": "fill_blank",
    "fillgate": "fill_gate",
    "filltable": "fill_table",
    "guessnumber": "guess_number",
    "markdone": "mark_done",
    "revealgate": "reveal_gate",
    "switchgate": "switch_gate",
    "switchgrid": "switch_grid",
    "twocolumn": "two_column",
}

# Container element registry: model class -> (non_destructive_normalizer,
# slot_list_key, slot_id_key). CONTRACT: each normalizer returns
# {slot_list_key: [{slot_id_key: <id>}, ...]}. resolve_scope indexes the normalizer
# output by slot_list_key, so slot_list_key MUST equal the key the normalizer emits.
_CONTAINER_REGISTRY = {
    TabsElement: (TabsElement.normalize_labels_and_ids, "tabs", "id"),
    TwoColumnElement: (TwoColumnElement.normalize_ids, "columns", "id"),
    # Single-slot: ignores its argument and returns one fixed slot. SpoilerElement
    # has no `data` field, which is why the call site below uses getattr().
    SpoilerElement: (
        lambda _data: {"slots": [{"id": SpoilerElement.SLOT_ID}]},
        "slots",
        "id",
    ),
}


def element_depth(join):
    """1 for a top-level element; +1 per parent hop.

    Bounded by MAX_NEST_DEPTH hops so a corrupt parent cycle returns a too-deep
    value instead of looping. The bound is for cycle safety ONLY -- what makes
    MAX_NEST_DEPTH load-bearing is clauses 3 and 4 comparing against it.
    """
    depth = 1
    parent = join.parent
    while parent is not None and depth <= MAX_NEST_DEPTH:
        depth += 1
        parent = parent.parent
    return depth


def slot_key(parent_pk, tab_id):
    """Flattened '<parent_pk>:<tab_id>' key for one container slot; the
    top-level slot is ':'.

    A single flattened string rather than a tuple, because Django's template
    language cannot construct a tuple and the <details> open test has to build
    this key from two values inside an expression. One helper for the view and
    the template so the two can never disagree about the shape.

    The `is None` test is explicit on purpose: `parent_pk or ""` would collapse a
    pk of 0 onto the top-level key.
    """
    return f"{'' if parent_pk is None else parent_pk}:{tab_id}"


def ancestor_slots(join):
    """Slot keys of every container slot ABOVE `join`, so a render can force
    those <details> open and a newly created element is not born inside a
    collapsed tab.

    Bounded by MAX_NEST_DEPTH hops for the same reason element_depth is: a
    corrupt parent cycle must terminate rather than spin.
    """
    keys, cur, hops = set(), join, 0
    while cur.parent_id is not None and hops <= MAX_NEST_DEPTH:
        keys.add(slot_key(cur.parent_id, cur.tab_id))
        cur = cur.parent
        hops += 1
    return keys


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
        join = (
            Element.objects.select_related("parent__parent__parent")
            .filter(pk=int(parent_ref), unit=unit)
            .first()
        )
    except (TypeError, ValueError):
        raise NestingError("bad parent ref") from None
    if join is None:
        raise NestingError("unknown parent")

    parent_obj = join.content_object
    container = _CONTAINER_REGISTRY.get(type(parent_obj))
    if container is None:
        raise NestingError("parent is not a container")

    child_key = _NESTABLE_FORM_KEY_ALIASES.get(type_key, type_key)
    if child_key not in NESTABLE_TYPE_KEYS:  # clause 1
        raise NestingError(f"{type_key} may not be nested")

    # normalize_data (behind normalized_data) is DESTRUCTIVE and read-side only: it
    # pads/truncates and mints fresh random ids on every call, so a slot validated
    # against it could be an ephemeral phantom that never matches again at render
    # time -- silently orphaning the child. A write path must validate against the
    # ids that actually exist, via the non-destructive normalizer.
    normalizer, list_key, id_key = container
    # getattr: a single-slot container (spoiler) has no `data` field at all, and the
    # argument is evaluated HERE, before the normalizer runs.
    slots = normalizer(getattr(parent_obj, "data", None))[list_key]
    if tab not in {s[id_key] for s in slots}:  # clause 2
        raise NestingError("unknown slot")

    parent_depth = element_depth(join)
    if parent_depth >= MAX_NEST_DEPTH:  # clause 3
        raise NestingError("too deep")
    if (  # clause 4
        parent_depth >= MAX_NEST_DEPTH - 1 and child_key in CONTAINER_TRANSFER_KEYS
    ):
        raise NestingError("a container may not be nested this deeply")
    return join, tab


def _check_token(current_dt, token):
    expected = parse_datetime(token) if token else None
    if expected is None or expected != current_dt:
        raise ConflictError()


def _clean_title(title):
    """Normalize a node title before validation.

    Strips surrounding whitespace so a whitespace-only title becomes "" and is
    rejected by full_clean()'s blank check on EVERY path -- JS, no-JS, and the
    editor settings form.

    This deliberately does NOT live in ContentNode.clean(): full_clean() runs
    clean_fields() (which enforces blank) BEFORE clean(), so stripping there
    would let "   " pass the blank check and persist as "". Pushing the strip
    even earlier -- into a custom field's to_python(), which DOES run before the
    blank check -- was considered and rejected as disproportionate: a field
    subclass drags in deconstruct() and a migration, for whitespace trimming
    with only two entry points.

    Not applied by course import/transfer, which builds ContentNode directly
    rather than going through add_node/rename_node.
    """
    return title.strip()


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
        title=_clean_title(title),
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
        node.title = _clean_title(title)
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
def duplicate_unit(course, node_pk, *, token):
    """Deep-copy a unit as a sibling immediately below the source, sharing media.

    Reuses the transfer export/import path. `_locked_node` + `_check_token` run
    FIRST and raise ConflictError (-> 409) unwrapped. Only the region after them
    is wrapped so any other failure becomes TransferError (-> 422); the whole
    duplicate is atomic.
    """
    source = _locked_node(course, node_pk)
    _check_token(source.updated, token)

    # Lazy imports: the transfer package pulls courses.forms / courses.media,
    # so a top-level edge here risks an import cycle (builder.py convention).
    from courses.transfer import export as _export  # avoid import cycle
    from courses.transfer import importer as _importer  # avoid import cycle
    from courses.transfer.schema import TransferError  # avoid import cycle

    try:
        if source.kind != "unit":
            raise ValueError("duplicate_unit only supports units")
        parent = source.parent
        _manifest, document, media_assets, _problems = _export.build_export(
            course, node=source, drop_missing_media=False
        )
        media_map = {mid: asset for (mid, asset, _ph) in media_assets}
        new_node = _importer.materialize_duplicate(document, media_map, course, parent)
        # Place the copy immediately after the source among its siblings. The
        # sibling list is read AFTER materialize appended new_node at the end;
        # source's index is unaffected by new_node sitting last, and place_node
        # excludes new_node from the reindexed others.
        new_node.parent = parent
        siblings = list(
            ContentNode.objects.filter(course=course, parent=parent).order_by(
                "order", "pk"
            )
        )
        idx = next(i for i, n in enumerate(siblings) if n.pk == source.pk)
        ordering.place_node(new_node, parent, course, idx + 1)
        if parent is None:
            course.save(update_fields=["updated"])
        return new_node
    except ConflictError:
        # Defensive only: _check_token already ran BEFORE this try, so no
        # ConflictError normally reaches here. Keep the 409 path unwrapped in case
        # a nested op ever raises one — never normalize it to 422.
        raise
    except TransferError:
        raise  # already normalized by materialize's _run_import
    except Exception as exc:
        raise TransferError(str(exc) or "Duplicate failed.") from exc


@transaction.atomic
def duplicate_element(course, element_pk, unit_token):
    """Deep-copy one element and its whole subtree into the SOURCE's own group,
    directly below the source. Returns (unit, new_join).

    Depth is unchanged -- the copy lands where the source already lives -- so a
    duplicate needs no admissibility check at all; it is safe by construction.
    """
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)

    # Lazy imports: the transfer package pulls courses.forms / courses.media,
    # so a top-level edge here risks an import cycle (builder.py convention).
    from courses.transfer import export as _export
    from courses.transfer import importer as _importer
    from courses.transfer.schema import TransferError

    try:
        return _copy_below(el, unit, _export, _importer, TransferError)
    except ConflictError:
        # Defensive only: _check_token already ran above, so no ConflictError
        # normally reaches here. Keep the 409 path unwrapped -- never normalize
        # it to 422. (duplicate_unit carries the same guard for the same reason.)
        raise
    except TransferError:
        raise  # already normalized by graft_elements' _run_import
    except Exception as exc:
        # build_element_export is NOT wrapped by _run_import, so a serializer
        # edge or the export's own assert would otherwise escape as a 500 --
        # element_duplicate catches only ConflictError and TransferError.
        raise TransferError(str(exc) or "Duplicate failed.") from exc


def _copy_below(el, unit, _export, _importer, TransferError):
    """The export/graft/place region of duplicate_element, split out so the
    caller's try/except reads as one block. Runs inside the caller's atomic
    transaction and its element+unit lock."""
    document, media_assets, problems = _export.build_element_export(unit, el)
    if problems:
        # build_export RECORDS a dangling GFK and continues, dropping the broken
        # join and its entire subtree from the payload; duplicate_unit discards
        # this list outright. Copy that shape here and a damaged element yields a
        # silently thinned copy with a 200. drop_missing_media=False means no
        # media problem can be produced, so a non-empty list means exactly one
        # thing.
        raise TransferError(_("This element is damaged and cannot be copied."))

    media_map = {mid: asset for (mid, asset, _ph) in media_assets}
    new_join = _importer.graft_elements(document, media_map, unit)

    # The graft returns a PARENTLESS root: the payload root has no `parent`, and
    # _create_elements' second pass skips exactly those rows. place_element will
    # not fix it either -- it saves only `order`. So the scope is set and SAVED
    # here, or a copy of a nested element silently lands at top level.
    new_join.parent = el.parent
    new_join.tab_id = el.tab_id
    new_join.save(update_fields=["parent", "tab_id"])

    # Read the sibling list AFTER the graft. Element.order is
    # OrderField(for_fields=["unit"]), so the copy is born with a unit-wide max+1
    # and sorts last in its group -- the source's index is therefore unaffected
    # by the copy's presence. Do not "fix" this by excluding the copy from the
    # list or by reading the group before the graft: both change which index
    # means "below the source".
    siblings = list(
        ordering.element_siblings(unit, el.parent, el.tab_id).order_by("order", "pk")
    )
    idx = next(i for i, s in enumerate(siblings) if s.pk == el.pk)
    ordering.place_element(new_join, unit, idx + 1)

    unit.save(update_fields=["updated"])
    return unit, new_join


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


def _collect_subtree_pks(roots):
    """Join pks of `roots` plus every descendant, ROOT-INCLUSIVE.

    Descends `join.children` -- every child row, container or not, matched slot or
    not. Deliberately NOT the slot accessors the export walk uses: resolved_tabs()
    runs the destructive normalize_data and skips children whose tab_id matches no
    slot. Export omits those on purpose; delete must not, or their concretes orphan.

    Reads join.children WITHOUT its own select_for_update -- concurrency safety
    against a grandchild inserted mid-walk comes entirely from the CALLER already
    holding the unit row's lock (see _locked_element's docstring). Do not treat
    that lock as incidental to this function.

    RECURSIVE and `seen`-guarded, not an iterative worklist: dropping the guard from
    a recursive walk raises RecursionError on a cycle, which a test can assert,
    whereas an iterative worklist would spin forever (pytest-timeout is not
    installed, so a hanging mutant can never be verified RED).

    Returns pks, not instances, so callers can hand
    _delete_element_content_objects a QuerySet -- it requires one
    (it calls .prefetch_related). Deletion ORDER is irrelevant: the prefetch
    materialises every row before the first delete fires.
    """
    seen = set()

    def walk(join):
        if join.pk in seen:
            return
        seen.add(join.pk)
        for child in join.children.all():
            walk(child)

    for root in roots:
        walk(root)
    return seen


@transaction.atomic
def delete_element(course, element_pk, unit_token):
    """Delete an element together with its WHOLE subtree, at every depth. The
    `parent` FK cascades descendant join rows, but a concrete is only reachable
    through the GFK, which DB cascade cannot traverse -- one level of collection
    would orphan every grandchild concrete.
    """
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    parent, tab_id = el.parent, el.tab_id  # capture before the row disappears
    pks = _collect_subtree_pks([el])
    _delete_element_content_objects(Element.objects.filter(pk__in=pks))
    # Unconditional: the collector is root-inclusive, so this element's concrete --
    # and, via its GenericRelation cascade, this join row -- is already gone. The old
    # `if obj is not None` branch is therefore dead. A 0-row DELETE in the normal
    # case; it does real work only when the root carried no concrete at all.
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
                doomed = list(Element.objects.filter(parent=join, tab_id__in=removed))
                # Root at each DOOMED CHILD, never at `join`: rooting at the tabs
                # element would sweep KEPT tabs' descendants, whose join rows survive
                # (the delete below is tab_id__in=removed only) -- live rows pointing
                # at deleted concretes.
                pks = _collect_subtree_pks(doomed)
                _delete_element_content_objects(Element.objects.filter(pk__in=pks))
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
        extra = (
            {"course": course}
            if type_key in ("image", "video", "gallery", "filltable")
            else {}
        )
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
    """Lock the element row AND its unit row in one query.

    select_for_update() carries no `of=` clause, so on the select_related("unit")
    join Postgres locks rows in EVERY joined table -- not just Element, but the
    unit's ContentNode row too. That is load-bearing: delete_element's
    _collect_subtree_pks (above) walks join.children WITHOUT its own
    select_for_update, so in isolation a concurrent write could insert a new
    grandchild after the walk has already passed its parent, orphaning that
    child's concrete when the delete proceeds. It cannot happen here, because
    save_element also takes the SAME unit row's lock (via _locked_unit) before it
    writes anything, so it blocks until this transaction commits or rolls back.
    Do NOT add `of=("self",)` to this select_for_update() -- Django's own docs
    recommend `of` as an optimisation that skips locking joined tables, but doing
    so here would silently reopen the orphaning window described above. Re-check
    delete_element/_collect_subtree_pks before narrowing this lock.
    """
    try:
        el = (
            Element.objects.select_for_update()
            .select_related("unit")
            .get(pk=element_pk, unit__course=course)
        )
    except (Element.DoesNotExist, ValueError, TypeError):
        raise ConflictError() from None
    return el, el.unit
