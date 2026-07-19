"""Fail-loud preconditions for the LAL import loader."""

import json
from pathlib import Path

from django.core.exceptions import ValidationError

from courses.geogebra import canonicalize_geogebra_url
from courses.lal_loader.builders import LoaderError
from courses.models import ContentNode
from courses.models import Course
from courses.validators import validate_embed_url


def resolve_course(slug):
    try:
        return Course.objects.get(slug=slug)
    except Course.DoesNotExist as e:
        raise LoaderError(f"no Course with slug {slug!r}; create it first") from e


def ensure_depth_policy(course, set_policy):
    if set_policy:
        # Import writes Part->Chapter->Unit; turn sections off (spec §4.4). A
        # pre-existing uses_sections=True is otherwise harmless — the ContentNode
        # invariant permits skipping the optional Section level.
        course.uses_parts = True
        course.uses_chapters = True
        course.uses_sections = False
        course.save(update_fields=["uses_parts", "uses_chapters", "uses_sections"])
        return
    if not (course.uses_parts and course.uses_chapters):
        raise LoaderError(
            f"course {course.slug!r} lacks uses_parts/uses_chapters; "
            "pass --set-policy to enable them"
        )


def owned_part_orders(json_dir):
    orders = set()
    for manifest in Path(json_dir).glob("*/manifest.json"):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        orders.add(data["part"]["order"])
    return orders


def assert_no_foreign_top_level(course, owned):
    foreign = ContentNode.objects.filter(course=course, parent__isnull=True).exclude(
        order__in=owned
    )
    if foreign.exists():
        bad = list(foreign.values_list("order", "title")[:5])
        raise LoaderError(
            f"course {course.slug!r} has top-level nodes not owned by this import "
            f"(orders/titles {bad}); refusing to touch a foreign tree"
        )


def assert_iframe_hosts_allowlisted(elements):
    # Validate the SAME url the builder will store (canonicalized), so the check
    # and the stored value can't disagree on host (M3). GeoGebra canonicalization
    # keeps the host; non-GeoGebra urls pass through unchanged.
    for el in elements:
        if el.get("type") == "iframe":
            url = canonicalize_geogebra_url(el["url"])
            try:
                validate_embed_url(url)
            except ValidationError as e:
                raise LoaderError(f"iframe host not allowlisted: {url}") from e
