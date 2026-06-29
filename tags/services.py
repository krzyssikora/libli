from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count
from django.db.models import Q
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
