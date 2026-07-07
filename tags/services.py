"""Author-scoped services for personal unit tags (create, rename, delete)."""

from collections import OrderedDict
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count
from django.db.models import Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from courses.access import accessible_courses
from tags.models import TAG_NAME_MAX_LEN
from tags.models import TAG_PALETTE
from tags.models import Tag
from tags.models import UnitTag
from tags.models import default_color_for


def normalize_name(raw):
    """Collapse all whitespace runs to single spaces; strip ends."""
    return " ".join((raw or "").split())


def _clean_name(raw):
    name = normalize_name(raw)
    if not name:
        raise ValidationError(_("Enter a tag name."))
    if len(name) > TAG_NAME_MAX_LEN:
        raise ValidationError(
            _("Tag name is too long (max %(n)d characters).") % {"n": TAG_NAME_MAX_LEN}
        )
    return name


def _reuse_or_create_tag(author, name):
    name = _clean_name(name)
    existing = Tag.objects.filter(author=author, name__iexact=name).first()
    if existing:
        return existing
    try:
        return Tag.objects.create(
            author=author, name=name, color=default_color_for(name)
        )
    except IntegrityError:  # concurrent insert hit the Lower(name) constraint
        return Tag.objects.get(author=author, name__iexact=name)


def rename_tag(author, tag_pk, name):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    name = _clean_name(name)
    clash = (
        Tag.objects.filter(author=author, name__iexact=name).exclude(pk=tag.pk).exists()
    )
    if clash:
        raise ValidationError(_("You already have a tag with this name."))
    tag.name = name
    try:
        tag.save(update_fields=["name"])
    except IntegrityError:  # concurrent same-author rename race
        raise ValidationError(_("You already have a tag with this name.")) from None
    return tag


def recolor_tag(author, tag_pk, color):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    if color not in TAG_PALETTE:
        raise ValidationError(_("Invalid colour."))
    tag.color = color
    tag.save(update_fields=["color"])
    return tag


def _accessible_unit_count(author, tag):
    return UnitTag.objects.filter(
        tag=tag, unit__course__in=accessible_courses(author)
    ).count()


def delete_tag(author, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    count = _accessible_unit_count(author, tag)  # snapshot BEFORE cascade
    tag.delete()
    return count


def list_tags(author):
    accessible = accessible_courses(author)
    return list(
        Tag.objects.filter(author=author).annotate(
            unit_count=Count(
                "unit_tags", filter=Q(unit_tags__unit__course__in=accessible)
            )
        )
    )


def tag_unit(author, unit, name):
    tag = _reuse_or_create_tag(author, name)
    link, _created = UnitTag.objects.get_or_create(tag=tag, unit=unit)
    return link


def tag_unit_by_id(author, unit, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    link, _created = UnitTag.objects.get_or_create(tag=tag, unit=unit)
    return link


def untag_unit(author, unit, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    UnitTag.objects.filter(tag=tag, unit=unit).delete()


def tags_for_unit(author, unit):
    return list(
        Tag.objects.filter(author=author, unit_tags__unit=unit).order_by(
            Lower("name"), "pk"
        )
    )


def tags_for_outline(author, course):
    """({unit_pk: [Tag, ...]}, [Tag, ...]) — per-unit chips + the in-course tag set."""
    qs = (
        UnitTag.objects.filter(tag__author=author, unit__course=course)
        .select_related("tag")
        .order_by(Lower("tag__name"), "tag__pk")
    )
    tags_by_unit = defaultdict(list)
    course_tags = []
    seen = set()
    for ut in qs:
        tags_by_unit[ut.unit_id].append(ut.tag)
        if ut.tag_id not in seen:
            seen.add(ut.tag_id)
            course_tags.append(ut.tag)
    return dict(tags_by_unit), course_tags


def outline_with_tags(outline, tags_by_unit, active_ids):
    """Annotate each build_outline node dict in place: `tags` (units) + `tag_hidden`.

    Empty active set ⇒ nothing hidden. Otherwise: a unit is visible iff it carries
    ≥1 active tag; a container is visible iff ≥1 descendant unit is visible.
    """
    active = set(active_ids)

    def visit(d):
        if d["is_unit"]:
            tags = tags_by_unit.get(d["node"].pk, [])
            d["tags"] = tags
            d["tag_hidden"] = bool(active) and not any(t.pk in active for t in tags)
            return not d["tag_hidden"]
        any_visible = False
        for child in d["children"]:
            if visit(child):
                any_visible = True
        d["tag_hidden"] = bool(active) and not any_visible
        return not d["tag_hidden"]

    for root in outline:
        visit(root)
    return outline


def filter_chip_hrefs(base, course_tags, active_ids):
    """[{tag, active, href}] — each href toggles that tag in/out of the active set."""
    active = set(active_ids)
    chips = []
    for tag in course_tags:
        if tag.pk in active:
            ids = [i for i in active_ids if i != tag.pk]
        else:
            ids = active_ids + [tag.pk]
        query = "&".join(f"tags={i}" for i in ids)
        href = f"{base}?{query}" if query else base
        chips.append({"tag": tag, "active": tag.pk in active, "href": href})
    return chips


def units_by_tag(author):
    """[(Tag, {Course: [unit, ...]})] for the My tags page (accessible courses only).

    Courses ordered by title; units within a course in true **outline (pre-order)**
    position. NB: `ContentNode.order` is per-parent (`OrderField(for_fields=
    ["course","parent"])`), so units under different parents share order values — a flat
    `order` sort would interleave them. We index each course's pre-order walk instead.
    """
    from courses.rollups import _walk_preorder

    accessible = accessible_courses(author)
    result = []
    for tag in list_tags(author):  # ordered, carries accessible unit_count
        links = UnitTag.objects.filter(
            tag=tag, unit__course__in=accessible
        ).select_related("unit", "unit__course")
        by_course = defaultdict(list)
        for link in links:
            by_course[link.unit.course].append(link.unit)
        grouped = OrderedDict()
        for course in sorted(by_course, key=lambda c: c.title):
            order_index = {n.pk: i for i, n in enumerate(_walk_preorder(course))}
            grouped[course] = sorted(
                by_course[course], key=lambda u: order_index.get(u.pk, 1 << 30)
            )
        result.append((tag, grouped))
    return result


def tags_by_course(author):
    """OrderedDict {Course: [Tag, ...]} — distinct tags the author used on each
    accessible course's units, courses keyed by object, tags in Lower(name) order.
    One UnitTag query."""
    links = (
        UnitTag.objects.filter(
            tag__author=author, unit__course__in=accessible_courses(author)
        )
        .select_related("tag", "unit__course")
        .order_by(Lower("tag__name"), "tag__pk")
    )
    by_course = OrderedDict()
    seen = defaultdict(set)  # course_id -> {tag_id}
    for link in links:
        course = link.unit.course
        if link.tag_id not in seen[course.pk]:
            seen[course.pk].add(link.tag_id)
            by_course.setdefault(course, []).append(link.tag)
    return by_course
