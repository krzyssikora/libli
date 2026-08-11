from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from courses.access import can_access_course
from courses.access import get_node_or_404
from courses.htmlsandbox import titles_have_math
from tags import services
from tags.models import TAG_PALETTE
from tags.models import Tag
from tags.rendering import unit_tags_context


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _unit_url(unit):
    name = "courses:quiz_unit" if unit.unit_type == "quiz" else "courses:lesson_unit"
    return reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})


def _panel_response(request, unit, *, status=200, error=None, draft=""):
    ctx = unit_tags_context(request.user, unit, panel_open=True)
    ctx.update(course=unit.course, unit=unit, tag_error=error, tag_draft=draft)
    return render(request, "tags/_unit_tag_panel.html", ctx, status=status)


@login_required
@require_POST
def tag_add(request, slug, node_pk):
    unit = get_node_or_404(node_pk, slug, viewer=request.user, require_unit=True)
    if not can_access_course(request.user, unit.course):
        raise PermissionDenied
    tag_pks = request.POST.getlist("tag_pk")
    name = request.POST.get("name", "")
    if tag_pks:
        # atomic so a foreign id later in the list leaves no partial links (it 404s)
        with transaction.atomic():
            for pk in tag_pks:
                services.tag_unit_by_id(request.user, unit, pk)
    elif name.strip():
        try:
            services.tag_unit(request.user, unit, name)
        except ValidationError as exc:
            return _add_error(request, unit, name, exc)
    else:
        msg = _("Enter a tag name or pick a tag.")
        return _add_error(request, unit, "", ValidationError(msg))
    if _wants_fragment(request):
        return _panel_response(request, unit)
    return redirect(_unit_url(unit) + "?panel=tags")


def _add_error(request, unit, draft, exc):
    msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
    if _wants_fragment(request):
        return _panel_response(request, unit, status=422, error=msg, draft=draft)
    ctx = unit_tags_context(request.user, unit, panel_open=True)
    ctx.update(course=unit.course, unit=unit, tag_error=msg, tag_draft=draft)
    ctx["has_math"] = titles_have_math([unit.title])
    # Re-render the unit page would require its full context; for the no-JS error
    # path we render the standalone panel page (mirrors notes' standalone surfaces).
    return render(request, "tags/panel_page.html", ctx, status=422)


@login_required
@require_POST
def tag_remove(request, slug, node_pk):
    unit = get_node_or_404(node_pk, slug, viewer=request.user, require_unit=True)
    if not can_access_course(request.user, unit.course):
        raise PermissionDenied
    services.untag_unit(request.user, unit, request.POST.get("tag_pk"))
    if _wants_fragment(request):
        return _panel_response(request, unit)
    return redirect(_unit_url(unit) + "?panel=tags")


def _hub_context(user):
    """The tags-hub context, shared by my_tags and tag_recolor's error branch.

    THE HUB RENDERS TWICE and there is no other shared seam, so without this the
    scan has to be applied at both sites or a recolor validation error
    re-renders the hub with no has_math and shows raw delimiters.

    tags_by_tag is [(Tag, {Course: [unit, ...]})] -- a real list, so scanning it
    here and passing it on iterates it twice safely. Note the nesting: a direct
    translation of _tag_section.html's `{% for course, units in grouped.items %}`
    would unpack (tag, grouped) into (course, units) and silently scan Course
    objects instead of units.
    """
    tags_by_tag = services.units_by_tag(user)
    return {
        "tags_by_tag": tags_by_tag,
        "palette": TAG_PALETTE,
        # Both current render sites pass the same value; it stays in the shared
        # context so neither can drift.
        "hub_tab": "manage_tags",
        "has_math": titles_have_math(
            u.title
            for _tag, grouped in tags_by_tag
            for units in grouped.values()
            for u in units
        ),
    }


@login_required
def my_tags(request):
    return render(request, "tags/my_tags.html", _hub_context(request.user))


@login_required
def tag_rename(request, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=request.user)
    if request.method == "POST":
        try:
            services.rename_tag(request.user, tag.pk, request.POST.get("name", ""))
        except ValidationError as exc:
            return render(
                request,
                "tags/rename_page.html",
                {
                    "tag": tag,
                    "error": exc.messages[0],
                    "draft": request.POST.get("name", ""),
                },
                status=422,
            )
        return redirect("tags:my_tags")
    return render(request, "tags/rename_page.html", {"tag": tag, "draft": tag.name})


@login_required
@require_POST
def tag_recolor(request, tag_pk):
    get_object_or_404(Tag, pk=tag_pk, author=request.user)
    try:
        services.recolor_tag(request.user, tag_pk, request.POST.get("color", ""))
    except ValidationError:
        return render(
            request, "tags/my_tags.html", _hub_context(request.user), status=422
        )
    return redirect("tags:my_tags")


@login_required
def tag_delete(request, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=request.user)
    if request.method == "POST":
        services.delete_tag(request.user, tag.pk)
        return redirect("tags:my_tags")
    count = services._accessible_unit_count(request.user, tag)
    return render(request, "tags/delete_confirm.html", {"tag": tag, "count": count})
