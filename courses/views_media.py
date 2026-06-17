from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from courses import media as media_svc
from courses.element_forms import MediaAssetForm
from courses.models import MediaAsset
from courses.views_manage import _require_manage
from courses.views_manage import _wants_fragment


@login_required
def media_manager(request, slug):
    course = _require_manage(request, slug)
    kind = request.GET.get("kind")
    q = request.GET.get("q", "")
    assets = media_svc.assets_with_usage(course, kind=kind, q=q)
    ctx = {"course": course, "assets": assets, "kind": kind or "", "q": q}
    if _wants_fragment(request):
        return render(request, "courses/manage/media/_asset_grid.html", ctx)
    return render(request, "courses/manage/media/manager.html", ctx)


@login_required
def media_upload(request, slug):
    course = _require_manage(request, slug)
    form = MediaAssetForm(request.POST, request.FILES)
    if not form.is_valid():
        msg = "; ".join(m for errs in form.errors.values() for m in errs)
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    try:
        asset = media_svc.create_asset(
            course,
            form.cleaned_data["kind"],
            request.FILES["file"],
            request.user,
            name=(request.POST.get("name") or "").strip(),
        )
    except ValidationError as e:  # create_asset.full_clean() is the single authority
        msg = "; ".join(e.messages)
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    if not _wants_fragment(request):
        return redirect("courses:manage_media", slug=course.slug)
    # A just-uploaded asset is unused by construction, so 0/0 is correct here (not a
    # placeholder) — usage only grows once an element references it via a later save.
    return render(
        request,
        "courses/manage/media/_asset_cell.html",
        {"course": course, "asset": asset, "img_uses": 0, "vid_uses": 0},
    )


@login_required
def media_rename(request, slug):
    course = _require_manage(request, slug)
    try:
        asset_pk = int(request.POST.get("id") or 0)
    except (TypeError, ValueError):
        asset_pk = 0
    asset = get_object_or_404(MediaAsset, pk=asset_pk, course=course)
    name = (request.POST.get("name") or "").strip()
    if len(name) > 255:
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(
            request,
            "courses/manage/_op_error.html",
            {"message": "Name is too long (max 255 characters)."},
            status=422,
        )
    media_svc.rename_asset(asset, name)
    if not _wants_fragment(request):
        return redirect("courses:manage_media", slug=course.slug)
    uses = media_svc.usage_count(asset)
    return render(
        request,
        "courses/manage/media/_asset_cell.html",
        {"course": course, "asset": asset, "img_uses": uses, "vid_uses": 0},
    )


@login_required
def media_picker(request, slug):
    course = _require_manage(request, slug)
    kind = request.GET.get("kind", "image")
    if kind not in ("image", "video"):
        kind = "image"
    q = (request.GET.get("q") or "").strip()
    # Filtering is duplicated here (rather than delegated to
    # media_svc.assets_with_usage) on purpose: the picker shows no usage counts,
    # so it wants a plain queryset without the usage-annotation joins.
    assets = course.media_assets.filter(kind=kind)
    if q:
        assets = assets.filter(Q(name__icontains=q) | Q(original_filename__icontains=q))
    assets = assets.order_by("-created")
    ctx = {"course": course, "kind": kind, "assets": assets, "q": q}
    if request.GET.get("grid") == "1":  # JS search → grid-only fragment
        return render(request, "courses/manage/media/_picker_grid.html", ctx)
    return render(request, "courses/manage/media/_picker.html", ctx)


@login_required
def media_delete(request, slug, pk):
    course = _require_manage(request, slug)
    asset = get_object_or_404(MediaAsset, pk=pk, course=course)
    try:
        media_svc.delete_asset(asset)
    except media_svc.AssetInUseError:
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(
            request,
            "courses/manage/_op_error.html",
            {"message": "This file is in use and cannot be deleted."},
            status=409,
        )
    if not _wants_fragment(request):
        return redirect("courses:manage_media", slug=course.slug)
    return render(request, "courses/manage/_empty.html", {})  # JS removes the cell
