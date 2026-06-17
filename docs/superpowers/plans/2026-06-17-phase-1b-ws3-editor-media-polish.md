# Phase 1b — WS3: Editor & Media Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the editor｜preview page and media manager/picker to the accepted mockups, add the icon-only text toolbar, `<iframe>` embed-snippet paste, element drag-and-drop, the unit title in preview, and a full media manager (display-name rename + filter/search), all on a near-unchanged backend.

**Architecture:** Server-rendered Django + vanilla-JS fragment swaps (the established 1b rhythm). Each element op re-renders the editor pane + preview fragments via `_render_editor_fragments`; the optimistic `unit.updated` token (409-before-422) is reused unchanged. Two genuinely new backend pieces: a pure `courses/embed.py` parser and an absolute-position element-reorder mode (`ordering.place_element`). One model field (`MediaAsset.name`, migration 0009).

**Tech Stack:** Django 5.2, pytest + pytest-playwright (e2e marked `-m e2e`, excluded by default), token-driven bespoke CSS (`core/css/tokens.css`), stdlib `html.parser`.

**Spec:** `docs/superpowers/specs/2026-06-17-phase-1b-ws3-editor-media-polish-design.md` (reviewed clean, 46 catches applied).

**Conventions (verified against the repo):**
- Run Python via `.venv/Scripts/python.exe` (Windows; `uv run python` also works). Tests: `.venv/Scripts/python.exe -m pytest …`.
- Test settings pin non-manifest static + LocMemCache; e2e tests need `pytestmark = pytest.mark.e2e` and the `_allow_sync_orm_under_playwright` autouse fixture pattern (see `tests/test_e2e_builder_ws2.py`).
- Test helpers: `tests/factories.py` → `make_verified_user`, `TEST_PASSWORD`, `CourseFactory`, `ContentNodeFactory`. PA login helper pattern: `tests/test_e2e_builder_ws2.py::_make_pa_user` / `_login`.
- Commit trailer (every commit): `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch: `phase-1b-ws3-editor-media-polish` (already checked out; spec + spec-review commits are on it).

**Task order** (each commit stays green): 1 embed parser → 2 MediaAsset.name → 3 element absolute-position reorder → 4 media rename + name-on-upload → 5 media filter/search → 6 editor page restyle + #14a/#14b → 7 inline-expansion + add-menu → 8 element DnD → 9 toolbar icons → 10 media manager/picker restyle JS → 11 i18n → 12 e2e + DoD gate.

---

## Task 1: Embed-snippet parser (`courses/embed.py`) + iframe form wiring + responsive render

**Files:**
- Create: `courses/embed.py`
- Create: `tests/test_embed.py`
- Modify: `courses/element_forms.py` (IframeElementForm)
- Modify: `templates/courses/elements/iframeelement.html`
- Modify: `templates/courses/manage/editor/_edit_iframe.html`
- Modify: `courses/static/courses/css/editor.css` (responsive iframe wrapper)

- [ ] **Step 1: Write the failing parser tests**

Create `tests/test_embed.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from courses.embed import extract_embed_url

VALID = (
    '<iframe scrolling="no" title="demo" '
    'src="https://www.geogebra.org/material/iframe/id/abc123/width/800/height/600" '
    'width="800" height="600" style="border:0px;"> </iframe>'
)


def test_plain_https_whitelisted_url_passes_through():
    assert extract_embed_url("https://www.geogebra.org/m/abc") == "https://www.geogebra.org/m/abc"


def test_valid_snippet_extracts_src():
    assert extract_embed_url(VALID) == (
        "https://www.geogebra.org/material/iframe/id/abc123/width/800/height/600"
    )


def test_wrapper_div_with_single_iframe_is_valid():
    raw = '<div class="wrap">' + VALID + "</div>"
    assert extract_embed_url(raw).startswith("https://www.geogebra.org/")


def test_non_whitelisted_host_rejected():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src="https://evil.example.com/x"></iframe>')
    assert "allow-list" in str(ei.value)


def test_non_snippet_non_whitelisted_url_rejected():
    with pytest.raises(ValidationError):
        extract_embed_url("https://evil.example.com/x")


def test_no_iframe_img_rejected():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<img src=x onerror="alert(1)">')
    assert "iframe" in str(ei.value).lower()


def test_script_embed_hits_no_iframe():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<script src="https://www.geogebra.org/apps/deployggb.js"></script>')
    assert "iframe" in str(ei.value).lower()


def test_javascript_src_rejected_via_https_check():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src="javascript:alert(1)"></iframe>')
    assert "https" in str(ei.value).lower()


def test_scheme_relative_src_rejected_via_https_check():
    # spec §D: scheme-relative //host parses with scheme="" -> fails the https check
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src="//evil.example.com/x"></iframe>')
    assert "https" in str(ei.value).lower()


def test_two_iframes_rejected_multi():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a"></iframe>'
        '<iframe src="https://www.geogebra.org/material/iframe/id/b"></iframe>'
    )
    with pytest.raises(ValidationError) as ei:
        extract_embed_url(raw)
    assert "single" in str(ei.value).lower()


def test_empty_src_is_missing_src_not_https():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src=""></iframe>')
    msg = str(ei.value).lower()
    assert "src" in msg and "https" not in msg


def test_absent_src_is_missing_src():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url("<iframe></iframe>")
    assert "src" in str(ei.value).lower()


def test_blank_input_rejected():
    with pytest.raises(ValidationError):
        extract_embed_url("   ")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_embed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.embed'`.

- [ ] **Step 3: Implement `courses/embed.py`**

```python
"""Parse a pasted <iframe> embed snippet (or a plain URL) down to a single
validated https `src`. Never store raw HTML — only the extracted, whitelisted URL.

First-match-wins error precedence (one deterministic message per case):
  malformed-parse -> multi-iframe (>1) -> no-iframe (0) -> missing-src
  -> non-whitelisted-domain (delegated to validate_embed_url).
"""

from html.parser import HTMLParser

from django.core.exceptions import ValidationError

from courses.validators import validate_embed_url


class _IframeCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.iframes = []  # list of attr-dicts, one per <iframe> anywhere in the input

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            self.iframes.append({k.lower(): (v or "") for k, v in attrs})


def extract_embed_url(raw):
    """Return a validated https embed URL, or raise ValidationError.

    Dispatch on the trimmed input: a leading '<' means an HTML snippet (parse it);
    otherwise treat it as a plain URL and hand it straight to validate_embed_url.
    """
    text = (raw or "").strip()
    if not text:
        raise ValidationError("Enter an embed URL or paste the embed's <iframe …> code.")
    if not text.startswith("<"):
        validate_embed_url(text)  # raises on non-https / non-whitelisted
        return text

    parser = _IframeCollector()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # stdlib html.parser rarely raises; treat as malformed
        raise ValidationError("Could not parse that embed code.") from exc

    iframes = parser.iframes
    if len(iframes) > 1:
        raise ValidationError("Paste a single embed (found more than one <iframe>).")
    if len(iframes) == 0:
        raise ValidationError(
            "No <iframe> found — paste the embed's <iframe …> code or a direct URL."
        )
    src = iframes[0].get("src", "").strip()
    if not src:
        raise ValidationError("The pasted <iframe> has no src.")
    validate_embed_url(src)  # https + allow-list; never receives ""
    return src
```

- [ ] **Step 4: Run parser tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_embed.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Wire the parser into `IframeElementForm`**

In `courses/element_forms.py`, replace the `IframeElementForm` class (currently lines 78-81) with:

```python
class IframeElementForm(forms.ModelForm):
    # Override the model's URLField as a free-text field so a pasted "<iframe …>"
    # snippet survives form-field validation; extract_embed_url does the real work
    # and returns the validated https src, which the model's URLField + the
    # validate_embed_url model validator then accept on save.
    url = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "data-embed-input": ""}),
        label="URL or embed code",
    )

    class Meta:
        model = IframeElement
        fields = ["url", "title"]

    def clean_url(self):
        from courses.embed import extract_embed_url

        return extract_embed_url(self.cleaned_data.get("url", ""))
```

Add the import at the top of `element_forms.py` if not present: `from django import forms` is already imported (line 1).

- [ ] **Step 6: Write a form-level test (snippet stored as src; reject leaves nothing)**

Append to `tests/test_embed.py`:

```python
@pytest.mark.django_db
def test_iframe_form_stores_only_src():
    from courses.element_forms import IframeElementForm

    form = IframeElementForm(data={"url": VALID, "title": "Demo"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == (
        "https://www.geogebra.org/material/iframe/id/abc123/width/800/height/600"
    )


@pytest.mark.django_db
def test_iframe_form_rejects_non_whitelisted_snippet():
    from courses.element_forms import IframeElementForm

    form = IframeElementForm(data={"url": '<iframe src="https://evil.example.com/x"></iframe>', "title": ""})
    assert not form.is_valid()
    assert "url" in form.errors
```

- [ ] **Step 7: Update the iframe render template to a responsive 16:9 wrapper**

Replace `templates/courses/elements/iframeelement.html` entirely with:

```django
<div class="el el--iframe">
  <div class="embed-16x9">
    <iframe src="{{ el.url }}" loading="lazy" title="{{ el.title|default:'embedded content' }}"></iframe>
  </div>
</div>
```

- [ ] **Step 8: Add the responsive wrapper CSS**

Append to `courses/static/courses/css/editor.css`:

```css
/* --- Responsive embed (#13): 16:9 wrapper, ignore pasted width/height --- */
.embed-16x9 { position: relative; width: 100%; aspect-ratio: 16 / 9; }
.embed-16x9 > iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
```

Note: `courses.css` (loaded by the student `lesson_unit.html` and the editor) — confirm the `.el--iframe` student render also picks up `embed-16x9`. Since `editor.css` is loaded on the editor page and the student lesson page loads `courses/css/courses.css`, also append the same two rules to `courses/static/courses/css/courses.css` so the student render is responsive too.

- [ ] **Step 9: Update the editor iframe edit partial to the smart single field**

Replace `templates/courses/manage/editor/_edit_iframe.html` with:

```django
{% load i18n %}
<div class="el-editor el-editor--iframe">
  <label>{% trans "URL or embed code" %}
    <textarea name="url" rows="3" data-embed-input>{{ form.url.value|default:'' }}</textarea>
  </label>
  <p class="helptext">{% trans "Paste a direct https URL or a full <iframe …> embed snippet." %}</p>
  <label>{% trans "Title" %} <input type="text" name="title" value="{{ form.title.value|default:'' }}"></label>
  {% for e in form.url.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  {% for e in form.title.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

- [ ] **Step 10: Run the full embed test module + a quick check**

Run: `.venv/Scripts/python.exe -m pytest tests/test_embed.py -q && .venv/Scripts/python.exe manage.py check`
Expected: PASS; `System check identified no issues`.

- [ ] **Step 11: Commit**

```bash
git add courses/embed.py tests/test_embed.py courses/element_forms.py \
  templates/courses/elements/iframeelement.html \
  templates/courses/manage/editor/_edit_iframe.html \
  courses/static/courses/css/editor.css courses/static/courses/css/courses.css
git commit -m "feat(embed): parse <iframe> snippet to a validated src (#13) + responsive render"
```

---

## Task 2: `MediaAsset.name` + `display_name` + `__str__` + migration 0009 + `element_summary` switch

**Files:**
- Modify: `courses/models.py` (MediaAsset)
- Create: `courses/migrations/0009_mediaasset_name.py` (generated)
- Modify: `courses/templatetags/courses_manage_extras.py` (element_summary)
- Create/Modify: `tests/test_media_model.py` (append)

- [ ] **Step 1: Write the failing model test**

Append to `tests/test_media_model.py`:

```python
@pytest.mark.django_db
def test_display_name_falls_back_to_filename():
    from tests.factories import CourseFactory
    from courses.models import MediaAsset

    course = CourseFactory()
    a = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png",
        original_filename="x.png", name="",
    )
    assert a.display_name == "x.png"
    assert str(a) == "Image: x.png"
    a.name = "Cover"
    assert a.display_name == "Cover"
    assert str(a) == "Image: Cover"
```

(If `tests/test_media_model.py` lacks `import pytest`, add it.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_model.py::test_display_name_falls_back_to_filename -q`
Expected: FAIL — `AttributeError: 'MediaAsset' object has no attribute 'name'` (or `display_name`).

- [ ] **Step 3: Add the field, property, and `__str__`**

In `courses/models.py`, in `class MediaAsset`, add the field after `original_filename` (currently line 196):

```python
    name = models.CharField(max_length=255, blank=True, default="")
```

Add a property and update `__str__` (replace the existing `__str__` at lines 212-213):

```python
    @property
    def display_name(self):
        return self.name or self.original_filename

    def __str__(self):
        return f"{self.get_kind_display()}: {self.display_name}"
```

- [ ] **Step 4: Generate migration 0009**

Run: `.venv/Scripts/python.exe manage.py makemigrations courses`
Expected: creates `courses/migrations/0009_mediaasset_name.py` adding `name` with `default=""`. Verify it depends on `0008_migrate_files_to_assets` and adds exactly one field.

- [ ] **Step 5: Switch `element_summary` media labels to `display_name`**

In `courses/templatetags/courses_manage_extras.py`, in `element_summary` (lines ~44-53), within the `el.media_id`-guarded branches only, replace `el.media.original_filename` with `el.media.display_name`:
- image branch (line 50): `return el.alt or (el.media.display_name if el.media_id else "") or "Image"`
- video branch (line 53): `return el.media.display_name`

Leave the no-media `_host(el.url)` / `""` fallbacks untouched.

- [ ] **Step 6: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_model.py -q && .venv/Scripts/python.exe manage.py makemigrations --check`
Expected: PASS; `No changes detected` (0009 already created).

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0009_mediaasset_name.py \
  courses/templatetags/courses_manage_extras.py tests/test_media_model.py
git commit -m "feat(media): add MediaAsset.name + display_name fallback (migration 0009)"
```

---

## Task 3: Element absolute-position reorder (`ordering.place_element` + `reorder_element` + `element_move` view)

**Files:**
- Modify: `courses/ordering.py` (add `place_element`)
- Modify: `courses/builder.py` (`reorder_element` signature)
- Modify: `courses/views_manage.py` (`element_move`)
- Modify/Create: `tests/test_manage_element_ops.py` (append)

- [ ] **Step 1: Write the failing service/helper tests**

Append to `tests/test_manage_element_ops.py` (mirror existing factory usage in that file):

```python
@pytest.mark.django_db
def test_place_element_moves_to_absolute_index():
    from courses import ordering
    from courses.builder import reorder_element
    from tests.factories import CourseFactory, ContentNodeFactory
    from courses.models import Element, TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None)
    els = []
    for i in range(4):
        t = TextElement.objects.create(body=f"<p>{i}</p>")
        els.append(Element.objects.create(unit=unit, content_object=t))
    token = unit.updated.isoformat()
    # move element at index 0 to index 2 (post-removal index)
    unit2, changed = reorder_element(course, els[0].pk, token, position=2)
    assert changed is True
    order = list(Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True))
    assert order == [els[1].pk, els[2].pk, els[0].pk, els[3].pk]


@pytest.mark.django_db
def test_place_element_clamps_out_of_range():
    from courses.builder import reorder_element
    from tests.factories import CourseFactory, ContentNodeFactory
    from courses.models import Element, TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None)
    els = [Element.objects.create(unit=unit, content_object=TextElement.objects.create(body=f"<p>{i}</p>")) for i in range(3)]
    token = unit.updated.isoformat()
    unit2, changed = reorder_element(course, els[0].pk, token, position=999)
    order = list(Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True))
    assert order == [els[1].pk, els[2].pk, els[0].pk]
    assert changed is True


@pytest.mark.django_db
def test_place_element_same_slot_is_noop():
    from courses.builder import reorder_element
    from tests.factories import CourseFactory, ContentNodeFactory
    from courses.models import Element, TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None)
    els = [Element.objects.create(unit=unit, content_object=TextElement.objects.create(body=f"<p>{i}</p>")) for i in range(3)]
    token = unit.updated.isoformat()
    unit2, changed = reorder_element(course, els[1].pk, token, position=1)
    assert changed is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manage_element_ops.py -k place_element -q`
Expected: FAIL — `reorder_element() got an unexpected keyword argument 'position'`.

- [ ] **Step 3: Add `place_element` to `courses/ordering.py`**

Append to `courses/ordering.py`:

```python
def place_element(element, unit, position):
    """Insert `element` at a 0-based `position` among the unit's other elements
    (clamped 0..len(others)), renumbering only rows whose order changed. Returns
    True iff any order changed. `others` is the POST-REMOVAL sibling list, so a valid
    `position` is `[0, len(others)]` (matching place_node)."""
    others = list(
        Element.objects.select_for_update()
        .filter(unit=unit)
        .exclude(pk=element.pk)
        .order_by("order", "pk")
    )
    if position is None or position > len(others):
        position = len(others)
    if position < 0:
        position = 0
    ordered = others[:position] + [element] + others[position:]
    changed = False
    for idx, el in enumerate(ordered):
        if el.order != idx:
            el.order = idx
            el.save(update_fields=["order"])
            changed = True
    return changed
```

- [ ] **Step 4: Change `reorder_element` to the keyword-only direction/position signature**

In `courses/builder.py`, replace `reorder_element` (lines 143-155) with:

```python
@transaction.atomic
def reorder_element(course, element_pk, unit_token, *, direction=None, position=None):
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    if position is not None:
        changed = ordering.place_element(el, unit, position)
    else:
        siblings = list(
            Element.objects.select_for_update().filter(unit=unit).order_by("order", "pk")
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
```

- [ ] **Step 5: Update the `element_move` view to parse direction/position (exactly one)**

In `courses/views_manage.py`, replace the body of `element_move` (lines 490-506) with:

```python
@login_required
def element_move(request, slug):
    course = _require_manage(request, slug)
    direction = request.POST.get("direction")
    position_raw = request.POST.get("position")
    has_dir = direction in ("up", "down")
    has_pos = position_raw not in (None, "")
    if has_dir == has_pos:  # both present, or neither -> ambiguous
        return _op_error(request, _("Provide exactly one of direction or position."))
    position = None
    if has_pos:
        try:
            position = int(position_raw)
        except (TypeError, ValueError):
            return _op_error(request, _("Invalid position."))
    try:
        unit, _changed = builder_svc.reorder_element(
            course,
            request.POST.get("element"),
            request.POST.get("unit_token"),
            direction=direction if has_dir else None,
            position=position,
        )
    except builder_svc.ConflictError:
        return _element_conflict(request, course)
    if _editor_ctx(request):
        return _render_editor_fragments(request, unit)
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    return _render_unit_panel(request, unit)
```

Add a small 422 helper near `_element_conflict` in `views_manage.py`:

```python
def _op_error(request, message):
    return render(
        request, "courses/manage/_op_error.html", {"message": message}, status=422
    )
```

- [ ] **Step 6: Run service + existing element-move tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manage_element_ops.py -q`
Expected: PASS. (Existing direction-path tests go through the `element_move` view's POST contract — `direction=up/down` — which is unchanged, so they keep passing. If any test calls `builder.reorder_element` positionally with `direction`, update it to `reorder_element(course, pk, token, direction="up")`.)

- [ ] **Step 7: Commit**

```bash
git add courses/ordering.py courses/builder.py courses/views_manage.py tests/test_manage_element_ops.py
git commit -m "feat(editor): absolute-position element reorder mode (backend for DnD)"
```

---

## Task 4: Media rename endpoint + optional name-on-upload

**Files:**
- Modify: `courses/media.py` (`rename_asset`, `create_asset` name)
- Modify: `courses/element_forms.py` (`MediaAssetForm` gains `name`)
- Modify: `courses/views_media.py` (`media_rename` view, `media_upload` passes name)
- Modify: `courses/urls.py` (route)
- Modify/Create: `tests/test_media_manager.py` (append)

- [ ] **Step 1: Write the failing rename tests**

Append to `tests/test_media_manager.py` (uses its existing PA/client helpers; adapt to that file's login pattern):

```python
@pytest.mark.django_db
def test_rename_asset_trims_and_clears(client_pa, course_with_asset):
    # client_pa: a logged-in PA test client; course_with_asset: (course, asset) fixture
    from django.urls import reverse
    course, asset = course_with_asset
    url = reverse("courses:manage_media_rename", kwargs={"slug": course.slug})
    r = client_pa.post(url, {"id": asset.pk, "name": "  Cover art  "}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 200
    asset.refresh_from_db()
    assert asset.name == "Cover art"  # trimmed
    # empty clears back to filename fallback
    r = client_pa.post(url, {"id": asset.pk, "name": "   "}, HTTP_X_REQUESTED_WITH="fetch")
    asset.refresh_from_db()
    assert asset.name == ""
    assert asset.display_name == asset.original_filename


@pytest.mark.django_db
def test_rename_over_length_is_422(client_pa, course_with_asset):
    from django.urls import reverse
    course, asset = course_with_asset
    url = reverse("courses:manage_media_rename", kwargs={"slug": course.slug})
    r = client_pa.post(url, {"id": asset.pk, "name": "x" * 256}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 422


@pytest.mark.django_db
def test_rename_cross_course_is_404(client_pa, course_with_asset, other_course):
    from django.urls import reverse
    course, asset = course_with_asset
    url = reverse("courses:manage_media_rename", kwargs={"slug": other_course.slug})
    r = client_pa.post(url, {"id": asset.pk, "name": "Hax"}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 404
```

If `tests/test_media_manager.py` lacks these fixtures, add them at the top of the file:

```python
import pytest


@pytest.fixture
def client_pa(client):
    from django.contrib.auth.models import Group
    from institution.roles import PLATFORM_ADMIN, seed_roles
    from tests.factories import make_verified_user, TEST_PASSWORD
    seed_roles()
    u = make_verified_user(username="pamedia", email="pamedia@t.example.com", password=TEST_PASSWORD)
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    client.force_login(u)
    return client


@pytest.fixture
def course_with_asset():
    from tests.factories import CourseFactory
    from courses.models import MediaAsset
    course = CourseFactory(slug="mediacourse")
    asset = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )
    return course, asset


@pytest.fixture
def other_course():
    from tests.factories import CourseFactory
    return CourseFactory(slug="othercourse")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_manager.py -k rename -q`
Expected: FAIL — `NoReverseMatch: 'manage_media_rename'`.

- [ ] **Step 3: Add `rename_asset` to `courses/media.py`**

Append to `courses/media.py`:

```python
def rename_asset(asset, name):
    """Set the display name (trimmed; empty clears to the filename fallback). The
    255-cap is enforced by the caller (view) before this is reached."""
    asset.name = (name or "").strip()
    asset.save(update_fields=["name"])
    return asset
```

- [ ] **Step 4: Add the route**

In `courses/urls.py`, add inside the media routes block (after the `manage_media_upload` path, ~line 109):

```python
    path(
        "manage/courses/<slug:slug>/media/rename/",
        views_media.media_rename,
        name="manage_media_rename",
    ),
```

- [ ] **Step 5: Add the `media_rename` view + name on upload**

In `courses/views_media.py`, add the view (after `media_upload`):

```python
@login_required
def media_rename(request, slug):
    course = _require_manage(request, slug)
    asset = get_object_or_404(MediaAsset, pk=request.POST.get("id"), course=course)
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
```

Update `media_upload` to read an optional name. Replace the `create_asset` call (lines 35-38) so it passes the trimmed name:

```python
    try:
        asset = media_svc.create_asset(
            course,
            form.cleaned_data["kind"],
            request.FILES["file"],
            request.user,
            name=(request.POST.get("name") or "").strip(),
        )
```

- [ ] **Step 6: Accept `name` in `create_asset`**

In `courses/media.py`, change `create_asset` signature/body (lines 45-55):

```python
def create_asset(course, kind, uploaded_file, user, name=""):
    asset = MediaAsset(
        course=course,
        kind=kind,
        file=uploaded_file,
        original_filename=truncate_filename(uploaded_file.name),
        name=(name or "").strip()[:255],
        uploaded_by=user,
    )
    asset.full_clean()  # per-kind extension + size validators (ValidationError -> 422)
    asset.save()
    return asset
```

(Name is trimmed and hard-capped to 255 here for the upload path; the rename view returns 422 on over-length rather than truncating, per spec.)

- [ ] **Step 7: Run tests to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_manager.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/media.py courses/element_forms.py courses/views_media.py courses/urls.py tests/test_media_manager.py
git commit -m "feat(media): rename endpoint + optional name-on-upload"
```

---

## Task 5: Server-side media filter + search (`?kind=` / `?q=`)

**Files:**
- Modify: `courses/media.py` (`assets_with_usage` gains `kind`/`q`)
- Modify: `courses/views_media.py` (`media_manager`, `media_picker` read params)
- Modify/Create: `tests/test_media_manager.py` (append)

- [ ] **Step 1: Write the failing filter test**

Append to `tests/test_media_manager.py`:

```python
@pytest.mark.django_db
def test_assets_with_usage_filters_by_kind_and_q():
    from courses import media as media_svc
    from tests.factories import CourseFactory
    from courses.models import MediaAsset
    course = CourseFactory(slug="filtercourse")
    MediaAsset.objects.create(course=course, kind="image", file="a.png", original_filename="apple.png", name="Red apple")
    MediaAsset.objects.create(course=course, kind="image", file="b.png", original_filename="banana.png", name="")
    MediaAsset.objects.create(course=course, kind="video", file="c.mp4", original_filename="apple-clip.mp4", name="")

    only_images = media_svc.assets_with_usage(course, kind="image")
    assert {a.original_filename for a in only_images} == {"apple.png", "banana.png"}

    apples = media_svc.assets_with_usage(course, q="apple")
    # matches name="Red apple" (image) + original_filename="apple-clip.mp4" (video)
    assert {a.original_filename for a in apples} == {"apple.png", "apple-clip.mp4"}

    empty_q = media_svc.assets_with_usage(course, q="   ")
    assert len(empty_q) == 3  # blank q = no filter


@pytest.mark.django_db
def test_picker_view_filters_by_q(client_pa, course_with_asset):
    # picker/manager parity: the picker view's ?q= must filter the same way
    from django.urls import reverse
    from courses.models import MediaAsset
    course, asset = course_with_asset  # asset: image "x.png"
    MediaAsset.objects.create(course=course, kind="image", file="y.png", original_filename="yacht.png", name="Yacht")
    url = reverse("courses:manage_media_picker", kwargs={"slug": course.slug})
    html = client_pa.get(url + "?kind=image&q=yacht", HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "yacht.png" in html and "x.png" not in html
```

(`client_pa` / `course_with_asset` are the fixtures added in Task 4.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_manager.py -k filters_by_kind -q`
Expected: FAIL — `assets_with_usage() got an unexpected keyword argument 'kind'`.

- [ ] **Step 3: Extend `assets_with_usage`**

In `courses/media.py`, replace `assets_with_usage` (lines 23-30) with:

```python
def assets_with_usage(course, kind=None, q=None):
    """Course assets annotated with a bulk usage count (avoids a per-asset N+1),
    optionally filtered by exact `kind` and a trimmed `q` substring over name OR
    original_filename. Blank/None `q` or `kind` = no filter for that dimension."""
    from django.db.models import Q

    qs = course.media_assets.all()
    if kind in ("image", "video"):
        qs = qs.filter(kind=kind)
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(original_filename__icontains=q))
    return list(
        qs.annotate(
            img_uses=Count("imageelement", distinct=True),
            vid_uses=Count("videoelement", distinct=True),
        ).order_by("-created")
    )
```

- [ ] **Step 4: Read params in the views**

In `courses/views_media.py`, replace `media_manager` (lines 14-21):

```python
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
```

And replace `media_picker` (lines 57-68):

```python
@login_required
def media_picker(request, slug):
    course = _require_manage(request, slug)
    kind = request.GET.get("kind", "image")
    if kind not in ("image", "video"):
        kind = "image"
    q = (request.GET.get("q") or "").strip()
    assets = course.media_assets.filter(kind=kind)
    if q:
        from django.db.models import Q
        assets = assets.filter(Q(name__icontains=q) | Q(original_filename__icontains=q))
    assets = assets.order_by("-created")
    ctx = {"course": course, "kind": kind, "assets": assets, "q": q}
    if request.GET.get("grid") == "1":  # JS search → grid-only fragment
        return render(request, "courses/manage/media/_picker_grid.html", ctx)
    return render(request, "courses/manage/media/_picker.html", ctx)
```

(The `_asset_grid.html` and `_picker_grid.html` partials are created in Task 10, which restyles the templates. This task only adds the server filtering + the fragment routing; if running tests before Task 10, the `_wants_fragment` / `grid=1` branches are not exercised by the Task-5 unit tests, which call `assets_with_usage` directly and the non-fragment view. Create empty stubs now to keep `manage.py check` clean: see Step 5.)

- [ ] **Step 5: Create grid-fragment stubs (filled in Task 10)**

Create `templates/courses/manage/media/_asset_grid.html`:

```django
{% load i18n %}
<div class="asset-grid">
  {% for asset in assets %}
    {% include "courses/manage/media/_asset_cell.html" with asset=asset img_uses=asset.img_uses vid_uses=asset.vid_uses %}
  {% empty %}
    <p class="empty-state">{% trans "No media match." %}</p>
  {% endfor %}
</div>
```

Create `templates/courses/manage/media/_picker_grid.html`:

```django
{% load i18n %}
<div class="asset-grid">
  {% for asset in assets %}
    <button type="button" class="asset-cell asset-pick" data-asset-id="{{ asset.pk }}"
            data-url="{{ asset.file.url }}" data-name="{{ asset.display_name }}">
      {% if asset.kind == "image" %}<img class="asset-thumb" src="{{ asset.file.url }}" alt="">
      {% else %}<span class="asset-thumb asset-thumb--video">▶</span>{% endif %}
      <span class="asset-name">{{ asset.display_name }}</span>
    </button>
  {% empty %}<p class="empty-state">{% trans "No media match." %}</p>{% endfor %}
</div>
```

- [ ] **Step 6: Run tests + check**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_manager.py -q && .venv/Scripts/python.exe manage.py check`
Expected: PASS; no check issues.

- [ ] **Step 7: Commit**

```bash
git add courses/media.py courses/views_media.py \
  templates/courses/manage/media/_asset_grid.html templates/courses/manage/media/_picker_grid.html \
  tests/test_media_manager.py
git commit -m "feat(media): server-side kind/q filter for manager + picker"
```

---

## Task 6: Editor page restyle — pane cards, breadcrumb, unit title + type chip, icon back-nav (#14b), unit title in preview (#14a)

**Files:**
- Modify: `courses/views_manage.py` (`editor`, `_render_editor_fragments`, add `_unit_ancestors`)
- Modify: `templates/courses/manage/editor/editor.html`
- Modify: `templates/courses/manage/editor/_editor_scope.html`
- Modify: `templates/courses/manage/editor/_preview.html`
- Modify: `templates/courses/lesson_unit.html` (student unit title — #14a)
- Modify: `courses/static/courses/css/editor.css`
- Test: `tests/test_editor_page.py` (append)

- [ ] **Step 1: Write the failing context/render test**

Append to `tests/test_editor_page.py` (uses that file's existing PA-client helper; adapt names):

```python
@pytest.mark.django_db
def test_editor_shows_ancestors_and_type_chip(client_pa_editor):
    from django.urls import reverse
    from tests.factories import CourseFactory, ContentNodeFactory
    course = CourseFactory(slug="editorbc")
    ch = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch1")
    sec = ContentNodeFactory(course=course, kind="section", parent=ch, title="Sec A")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=sec, title="Intro")
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    html = client_pa_editor.get(url).content.decode()
    assert "Ch1" in html and "Sec A" in html  # breadcrumb ancestors
    assert "Intro" in html                       # page-head h1
    assert "Lesson" in html                      # type chip get_unit_type_display


@pytest.mark.django_db
def test_preview_shows_unit_title(client_pa_editor):
    from django.urls import reverse
    from tests.factories import CourseFactory, ContentNodeFactory
    course = CourseFactory(slug="editorprev")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, title="Preview Me")
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    html = client_pa_editor.get(url).content.decode()
    # title appears inside the preview pane
    assert 'data-scope="preview"' in html
    assert "Preview Me" in html
```

Add a `client_pa_editor` fixture if absent (same shape as `client_pa` in Task 4).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_editor_page.py -k "ancestors or unit_title" -q`
Expected: FAIL (ancestors/chip/title not yet rendered).

- [ ] **Step 3: Add the ancestor-chain helper + pass it to the editor + fragments**

In `courses/views_manage.py`, add near `_editor_rows`:

```python
def _unit_ancestors(unit):
    """Root→parent chain (excluding the unit), for the breadcrumb. Variable depth."""
    chain, cur = [], unit.parent
    while cur is not None:
        chain.append(cur)
        cur = cur.parent
    chain.reverse()
    return chain
```

In `editor` (lines 586-603), add `"ancestors": _unit_ancestors(unit)` to the context dict. In `_render_editor_fragments` (lines 562-583), add `"ancestors": _unit_ancestors(unit)` to its context dict too (the breadcrumb lives on the page, not the swapped fragment — but pass it for symmetry; the fragment template ignores it). The unit title in preview is rendered by `_preview.html`, which both code paths already render.

- [ ] **Step 4: Restyle `editor.html` — breadcrumb + page-head + icon back-nav**

Replace `templates/courses/manage/editor/editor.html` content `{% block content %}` region (lines 9-16) with:

```django
{% block content %}
<section class="editor" data-course-slug="{{ course.slug }}"
         data-picker-url="{% url 'courses:manage_media_picker' slug=course.slug %}">
  {% if changed %}<div class="op-error" role="alert">{% trans "This changed elsewhere — reloaded to the latest." %}</div>{% endif %}
  <p class="editor-crumb">
    <a class="iconbtn" href="{% url 'courses:manage_builder' slug=course.slug %}"
       aria-label="{% trans 'Back to builder' %}" title="{% trans 'Back to builder' %}">←</a>
    <span class="editor-crumb__path">
      {{ course.title }}{% for a in ancestors %} <span class="editor-crumb__sep">/</span> {{ a.title }}{% endfor %}
    </span>
  </p>
  <div class="editor-head">
    <h1 class="editor-head__title">{{ unit.title }}</h1>
    <span class="editor-head__type">{% trans "Unit" %}{% if unit.unit_type %} · {{ unit.get_unit_type_display }}{% endif %}</span>
  </div>
  {% include "courses/manage/editor/_editor_scope.html" with open_form="" open_form_pk="" %}
</section>
{% endblock %}
```

- [ ] **Step 5: Restyle `_editor_scope.html` — two `.pane` cards**

Replace `templates/courses/manage/editor/_editor_scope.html` with:

```django
{% load i18n %}
<div class="editor-grid">
  <section class="pane editor-pane" data-scope="editor" data-updated="{{ unit.updated.isoformat }}"
       data-unit="{{ unit.pk }}"
       data-add-url="{% url 'courses:manage_element_add' slug=unit.course.slug %}"
       data-save-url="{% url 'courses:manage_element_save' slug=unit.course.slug %}"
       data-move-url="{% url 'courses:manage_element_move' slug=unit.course.slug %}">
    <div class="pane-head"><h2>{% trans "Editor" %}</h2><span class="pane-head__count">{{ rows|length }} {% trans "elements" %}</span></div>
    <div class="pane-body">
      <ol class="element-list">
        {% for el, obj in rows %}{% include "courses/manage/editor/_element_row.html" %}{% empty %}
          <li class="empty-state">{% trans "No elements yet." %}</li>{% endfor %}
      </ol>
      {% include "courses/manage/editor/_add_menu.html" %}
      <div class="editor-form-host">{{ open_form|safe }}</div>
    </div>
  </section>
  {% include "courses/manage/editor/_preview.html" %}
</div>
```

(Task 6 **keeps** the existing `.editor-form-host` div so the current `editor.js` add/edit flow keeps working through Task 6's commit — Task 6 is independently shippable. Task 7 removes the host div and switches to per-row `[data-edit-slot]` injection together with the `editor.js` rewrite. The `_add_menu.html` partial is created in Step 9a.)

- [ ] **Step 6: Add the unit title to the preview pane (#14a)**

Replace `templates/courses/manage/editor/_preview.html` with:

```django
{% load i18n courses_extras %}
<section class="pane preview-pane" data-scope="preview">
  <div class="pane-head"><h2>{% trans "Live preview" %}</h2><span class="pane-head__count">{% trans "as students see it" %}</span></div>
  <div class="pane-body prev">
    <h2 class="prev-unit-title">{{ unit.title }}</h2>
    {% for el in preview_elements %}
      <section>{% render_element el %}</section>
    {% empty %}
      <p class="empty-state">{% trans "Nothing to preview yet." %}</p>
    {% endfor %}
  </div>
</section>
```

- [ ] **Step 7: (no new heading) — the student lesson title already exists**

`templates/courses/lesson_unit.html` **already** renders `<h1>{{ unit.title }}</h1>` (line 11), so the student-facing title requirement is met — do **NOT** add a second heading (it would duplicate). The #14a gap this workstream closes is the *preview pane* (Step 6). Optional, no behaviour change: add `class="lesson-unit__title"` to the existing line-11 `<h1>` for styling parity.

- [ ] **Step 8: Add the editor restyle CSS (pane cards, breadcrumb, head, preview title)**

Append to `courses/static/courses/css/editor.css`:

```css
/* --- WS3 editor page: panes, breadcrumb, head --- */
.editor-crumb { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.editor-crumb__path { color: var(--text-secondary); font-size: .9rem; }
.editor-crumb__sep { color: var(--text-tertiary); }
.editor-head { display: flex; align-items: baseline; gap: var(--space-3); margin-bottom: var(--space-5); }
.editor-head__title { font-weight: 700; letter-spacing: var(--heading-letter-spacing); }
.editor-head__type { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text-tertiary); }
.pane { background: var(--surface-raised); border: 1px solid var(--border-default);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-xs); }
.pane-head { display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-subtle); }
.pane-head h2 { font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text-tertiary); }
.pane-head__count { font-size: .72rem; color: var(--text-tertiary); }
.pane-body { padding: var(--space-4); }
.preview-pane { position: sticky; top: var(--space-4); align-self: start; }
.prev-unit-title { font-weight: 700; margin-bottom: var(--space-3); }
/* generic icon button (back-nav, row actions) */
.iconbtn { display: inline-flex; align-items: center; justify-content: center;
  min-width: 1.9rem; min-height: 1.9rem; padding: var(--space-1);
  background: none; border: 1px solid var(--border-default); border-radius: var(--radius-sm);
  color: var(--text-secondary); cursor: pointer; text-decoration: none; }
.iconbtn:hover { background: var(--surface-sunken); color: var(--text-primary); border-color: var(--border-strong); }
.iconbtn--danger:hover { color: var(--danger); border-color: var(--danger); }
```

- [ ] **Step 9: Run tests + check**

**Create the `_add_menu.html` stub from Step 9a FIRST** (the restyled `_editor_scope.html` includes it, so rendering 404s without it), THEN run:
`.venv/Scripts/python.exe -m pytest tests/test_editor_page.py tests/test_manage_builder.py -q && .venv/Scripts/python.exe manage.py check`
Expected: PASS. (`_element_row.html` is unchanged in Task 6; the dashed add-button + 5-card menu replaces the stub in Task 7.)

- [ ] **Step 9a: Minimal `_add_menu.html` stub (replaced in Task 7)**

Create `templates/courses/manage/editor/_add_menu.html`:

```django
{% load i18n %}
<div class="editor-add">
  <button type="button" class="btn btn--small" data-add-type="text">+ {% trans "Text" %}</button>
  <button type="button" class="btn btn--small" data-add-type="image">+ {% trans "Image" %}</button>
  <button type="button" class="btn btn--small" data-add-type="video">+ {% trans "Video" %}</button>
  <button type="button" class="btn btn--small" data-add-type="iframe">+ {% trans "Iframe" %}</button>
  <button type="button" class="btn btn--small" data-add-type="math">+ {% trans "Math" %}</button>
</div>
```

- [ ] **Step 10: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/editor/editor.html \
  templates/courses/manage/editor/_editor_scope.html templates/courses/manage/editor/_preview.html \
  templates/courses/manage/editor/_add_menu.html templates/courses/lesson_unit.html \
  courses/static/courses/css/editor.css tests/test_editor_page.py
git commit -m "feat(editor): pane-card layout, breadcrumb, unit title in preview (#14a/#14b)"
```

---

## Task 7: Inline row-expansion + 5-card add-menu

**Files:**
- Modify: `courses/views_manage.py` (`_render_editor_fragments`, `_render_open_form`, `element_add`/`element_save`/`element_form` pass `open_form_pk`)
- Modify: `templates/courses/manage/editor/_element_row.html` (`[data-edit-slot]` + expand)
- Modify: `templates/courses/manage/editor/_editor_scope.html` (thread `open_form`/`open_form_pk`)
- Rewrite: `templates/courses/manage/editor/_add_menu.html` (dashed button + 5-card menu)
- Modify: `courses/static/courses/js/editor.js` (retarget, add-menu toggle, single-open)
- Modify: `courses/static/courses/css/editor.css` (rows-as-cards, add-menu, edit-slot)

- [ ] **Step 1: Thread `open_form_pk` through the fragment renderers**

In `courses/views_manage.py`:
- `_render_editor_fragments` (line 562): add a param `open_form_pk=""` and include it in the context dict passed to `_editor_scope.html`.
- `_render_open_form` (line 607): it already takes `element_pk`; pass `open_form_pk=element_pk` into `_render_editor_fragments`:

```python
    return _render_editor_fragments(
        request, unit, status=status, open_form=form_html, open_form_pk=str(element_pk), refresh=False
    )
```

- In `_render_editor_fragments`, the context dict gains `"open_form_pk": open_form_pk`.

- [ ] **Step 2: Update `_editor_scope.html` to pass `open_form`/`open_form_pk` into rows**

In the edited `_editor_scope.html` from Task 6, change the row include line to forward the two values, and render the `new`-row form when `open_form_pk == "new"`:

```django
      <ol class="element-list">
        {% for el, obj in rows %}{% include "courses/manage/editor/_element_row.html" with open_form=open_form open_form_pk=open_form_pk %}{% empty %}
          {% if open_form_pk != "new" %}<li class="empty-state">{% trans "No elements yet." %}</li>{% endif %}{% endfor %}
        {% if open_form_pk == "new" %}<li class="el-row el-row--editing"><div class="el-row__head"><span class="el-tag">{% trans "New" %}</span></div><div class="el-edit-slot">{{ open_form|safe }}</div></li>{% endif %}
      </ol>
```

**Also delete the `<div class="editor-form-host">{{ open_form|safe }}</div>` line that Task 6 retained** — the open form now lives in each row's `[data-edit-slot]` (existing edit) or the appended `new`-row `<li>` (add).

- [ ] **Step 3: Rewrite `_element_row.html` as a card with an edit slot**

Replace `templates/courses/manage/editor/_element_row.html` with:

```django
{% load i18n courses_manage_extras %}
<li class="el-row{% if open_form_pk == el.pk|stringformat:'s' %} el-row--editing{% endif %}"
    data-element="{{ el.pk }}" data-updated="{{ unit.updated.isoformat }}" data-unit="{{ unit.pk }}">
  <div class="el-row__head">
    <button type="button" class="iconbtn ica--grip" draggable="true"
            aria-label="{% trans 'Drag to reorder' %}" title="{% trans 'Drag to reorder' %}">⠿</button>
    <span class="el-tag">{% element_type_label el.content_type %}</span>
    <button type="button" class="el-select" data-element-id="{{ el.pk }}"
            data-form-url="{% url 'courses:manage_element_form' slug=unit.course.slug pk=el.pk %}">{{ obj|element_summary }}</button>
    <span class="el-actions">
      <button type="button" class="iconbtn el-select" data-element-id="{{ el.pk }}"
              data-form-url="{% url 'courses:manage_element_form' slug=unit.course.slug pk=el.pk %}"
              aria-label="{% trans 'Edit' %}" title="{% trans 'Edit' %}">✎</button>
      <form class="tree__inline" method="post" action="{% url 'courses:manage_element_move' slug=unit.course.slug %}" data-op="element-move">
        {% csrf_token %}
        <input type="hidden" name="ctx" value="editor">
        <input type="hidden" name="element" value="{{ el.pk }}">
        <input type="hidden" name="unit" value="{{ unit.pk }}">
        <input type="hidden" name="unit_token" value="{{ unit.updated.isoformat }}">
        <button class="iconbtn" type="submit" name="direction" value="up" aria-label="{% trans 'Move up' %}" title="{% trans 'Move up' %}">↑</button>
        <button class="iconbtn" type="submit" name="direction" value="down" aria-label="{% trans 'Move down' %}" title="{% trans 'Move down' %}">↓</button>
      </form>
      <form class="tree__inline" method="post" action="{% url 'courses:manage_element_delete' slug=unit.course.slug %}" data-op="element-delete">
        {% csrf_token %}
        <input type="hidden" name="ctx" value="editor">
        <input type="hidden" name="element" value="{{ el.pk }}">
        <input type="hidden" name="unit" value="{{ unit.pk }}">
        <input type="hidden" name="unit_token" value="{{ unit.updated.isoformat }}">
        <button class="iconbtn iconbtn--danger" type="submit" aria-label="{% trans 'Delete' %}" title="{% trans 'Delete' %}">🗑</button>
      </form>
    </span>
  </div>
  <div class="el-edit-slot" data-edit-slot>{% if open_form_pk == el.pk|stringformat:'s' %}{{ open_form|safe }}{% endif %}</div>
</li>
```

- [ ] **Step 4: Rewrite `_add_menu.html` as a dashed button + 5-card menu**

Replace `templates/courses/manage/editor/_add_menu.html` with:

```django
{% load i18n %}
<div class="addwrap" data-add-menu>
  <button type="button" class="addbtn" data-add-toggle>＋ {% trans "Add element" %}</button>
  <div class="typemenu" hidden data-type-menu>
    <button type="button" class="typecard" data-add-type="text"><span class="ic">📝</span>{% trans "Text" %}</button>
    <button type="button" class="typecard" data-add-type="image"><span class="ic">🖼</span>{% trans "Image" %}</button>
    <button type="button" class="typecard" data-add-type="video"><span class="ic">▶</span>{% trans "Video" %}</button>
    <button type="button" class="typecard" data-add-type="iframe"><span class="ic">🔗</span>{% trans "Iframe" %}</button>
    <button type="button" class="typecard" data-add-type="math"><span class="ic">∑</span>{% trans "Math" %}</button>
  </div>
</div>
```

- [ ] **Step 5: Rewrite `editor.js` — retarget swaps, add-menu, single-open**

Replace `courses/static/courses/js/editor.js` with:

```javascript
(function () {
  "use strict";
  var root = document.querySelector(".editor");
  if (!root) return;
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  function applyFragments(html) {
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    ["editor", "preview"].forEach(function (scope) {
      var incoming = tmp.querySelector('[data-scope="' + scope + '"]');
      var existing = root.querySelector('[data-scope="' + scope + '"]');
      if (incoming && existing) existing.replaceWith(incoming);
    });
    var preview = root.querySelector('[data-scope="preview"]');
    if (preview && window.libliRenderMath) window.libliRenderMath(preview);
    var editorPane = root.querySelector('[data-scope="editor"]');
    if (editorPane && window.libliInitMathLive) window.libliInitMathLive(editorPane);
    if (editorPane && window.libliInitRte) window.libliInitRte(editorPane);
    bindDnD();  // handlers re-bound after every swap (Task 8)
  }

  function post(form, submitter) {
    var body = new FormData(form);
    if (submitter && submitter.name) body.append(submitter.name, submitter.value);
    return fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
      body: body,
    }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); });
  }

  root.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-op]");
    if (!form) return;
    e.preventDefault();
    post(form, e.submitter).then(function (res) {
      if (res.status === 200 || res.status === 409 || res.status === 422) {
        applyFragments(res.text);
        if (res.status === 409) flash("This changed elsewhere — refreshed to the latest.");
      }
    });
  });

  root.addEventListener("click", function (e) {
    // Add-element: toggle the type menu.
    var toggle = e.target.closest("[data-add-toggle]");
    if (toggle) { var menu = root.querySelector("[data-type-menu]"); if (menu) menu.hidden = !menu.hidden; return; }
    // Type chosen -> POST add (render-only), swap in the new inline row.
    var add = e.target.closest("[data-add-type]");
    if (add) {
      var pane = root.querySelector('[data-scope="editor"]');
      var fd = new FormData();
      fd.append("type", add.getAttribute("data-add-type"));
      fd.append("unit", pane.getAttribute("data-unit"));
      fetch(pane.getAttribute("data-add-url"), {
        method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd,
      }).then(function (r) { return r.text(); }).then(applyFragments);
      return;
    }
    // Cancel an open inline editor -> just re-render the pane (drops the open form).
    var cancel = e.target.closest("[data-cancel-edit]");
    if (cancel) {
      var pane2 = root.querySelector('[data-scope="editor"]');
      // Re-fetch a clean editor (no open form) via the element-move no-op is overkill;
      // simplest: reload the editor page fragment by GETting the editor URL is not a
      // fragment endpoint — instead just remove the open slot's contents client-side.
      var slot = cancel.closest("[data-edit-slot]");
      if (slot) slot.innerHTML = "";
      var editingRow = cancel.closest(".el-row--editing");
      if (editingRow) editingRow.classList.remove("el-row--editing");
      var newRow = cancel.closest(".el-row--editing");
      if (cancel.closest(".el-row") && !cancel.closest(".el-row").getAttribute("data-element")) {
        cancel.closest(".el-row").remove();  // unsaved new row
      }
      return;
    }
    // Open an existing element's editor (pencil or summary) -> GET its form fragment.
    var sel = e.target.closest(".el-select");
    if (sel) {
      fetch(sel.getAttribute("data-form-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); }).then(applyFragments);
    }
  });

  function flash(msg) {
    var bar = document.createElement("div"); bar.className = "op-error"; bar.textContent = msg;
    root.prepend(bar); setTimeout(function () { bar.remove(); }, 6000);
  }

  // --- Drag-and-drop (Task 8 fills bindDnD) ---
  function bindDnD() { if (window.__libliEditorDnD) window.__libliEditorDnD(root); }
  bindDnD();
})();
```

(Note: the cancel path is simplified — clearing the slot client-side is enough since the single-open invariant means re-opening another editor re-renders the whole pane. The DnD `bindDnD`/`window.__libliEditorDnD` hook is filled in Task 8.)

- [ ] **Step 6: Add rows-as-cards + add-menu + edit-slot CSS**

Append to `courses/static/courses/css/editor.css`:

```css
/* --- WS3 element rows as cards + inline edit slot --- */
.element-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.el-row { border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
  background: var(--surface-sunken); padding: var(--space-2) var(--space-3); }
.el-row__head { display: flex; align-items: center; gap: var(--space-2); }
.el-row:hover { border-color: var(--border-strong); }
.el-row--editing { border-color: var(--primary); background: var(--surface-raised); box-shadow: var(--shadow-sm); }
.el-actions { display: inline-flex; gap: 2px; margin-left: auto; opacity: .4; transition: opacity .12s; align-items: center; }
.el-row:hover .el-actions, .el-row--editing .el-actions { opacity: 1; }
.el-edit-slot:empty { display: none; }
.el-edit-slot { margin-top: var(--space-3); }
.ica--grip { cursor: grab; border-color: transparent; }
.ica--grip:active { cursor: grabbing; }
.el-row.lifted { opacity: .45; }
.el-drop-line { height: 0; border-top: 2px solid var(--primary); margin: 1px 0; list-style: none; }

/* add-element dashed button + 5-card type menu */
.addwrap { margin-top: var(--space-4); }
.addbtn { display: flex; width: 100%; justify-content: center; align-items: center; gap: 6px;
  background: none; border: 1px dashed var(--border-strong); color: var(--primary);
  border-radius: var(--radius-md); padding: var(--space-2) var(--space-3); cursor: pointer; }
.addbtn:hover { border-color: var(--primary); background: var(--primary-subtle); }
.typemenu { margin-top: var(--space-2); display: grid; grid-template-columns: repeat(5, 1fr); gap: var(--space-2); }
.typemenu[hidden] { display: none; }
.typecard { display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: var(--space-3) var(--space-2); border: 1px solid var(--border-default);
  border-radius: var(--radius-md); background: var(--surface-sunken); cursor: pointer;
  color: var(--text-secondary); font-size: .78rem; }
.typecard:hover { border-color: var(--primary); color: var(--text-primary); background: var(--primary-subtle); }
.typecard .ic { font-size: 1.2rem; }
@media (max-width: 720px) { .typemenu { grid-template-columns: repeat(3, 1fr); } }
```

- [ ] **Step 7: Add a server test that the open form lands in the matching row's slot**

Append to `tests/test_editor_page.py`:

```python
@pytest.mark.django_db
def test_element_form_renders_inside_matching_row_slot(client_pa_editor):
    from django.urls import reverse
    from tests.factories import CourseFactory, ContentNodeFactory
    from courses.models import Element, TextElement
    course = CourseFactory(slug="editslot")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, title="U")
    el = Element.objects.create(unit=unit, content_object=TextElement.objects.create(body="<p>hi</p>"))
    url = reverse("courses:manage_element_form", kwargs={"slug": course.slug, "pk": el.pk})
    html = client_pa_editor.get(url, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    # the editing row carries the editing class and the host form
    assert "el-row--editing" in html
    assert 'data-op="element-save"' in html
```

- [ ] **Step 8: Run tests + check**

Run: `.venv/Scripts/python.exe -m pytest tests/test_editor_page.py tests/test_element_editor_ops.py -q && .venv/Scripts/python.exe manage.py check`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/editor/_editor_scope.html \
  templates/courses/manage/editor/_element_row.html templates/courses/manage/editor/_add_menu.html \
  courses/static/courses/js/editor.js courses/static/courses/css/editor.css tests/test_editor_page.py
git commit -m "feat(editor): inline row-expansion editing + 5-card add menu"
```

---

## Task 8: Element drag-and-drop

**Files:**
- Create: `courses/static/courses/js/editor_dnd.js`
- Modify: `templates/courses/manage/editor/editor.html` (load the new script)
- Test: covered by the e2e in Task 12 (`test_editor_dnd_reorder`).

- [ ] **Step 1: Implement the flat DnD module**

Create `courses/static/courses/js/editor_dnd.js`:

```javascript
(function () {
  "use strict";
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  // Exposed so editor.js can (re)bind after each fragment swap.
  window.__libliEditorDnD = function (root) {
    var pane = root.querySelector('[data-scope="editor"]');
    var list = pane && pane.querySelector(".element-list");
    if (!list || list.__dndBound) return;
    list.__dndBound = true;
    var drag = null;  // { pk, row }

    function clearMarks() {
      list.querySelectorAll(".el-drop-line").forEach(function (n) { n.remove(); });
      list.querySelectorAll(".el-row.lifted").forEach(function (n) { n.classList.remove("lifted"); });
    }

    list.addEventListener("dragstart", function (e) {
      var grip = e.target.closest(".ica--grip");
      if (!grip) { e.preventDefault(); return; }
      var row = grip.closest(".el-row");
      drag = { pk: row.getAttribute("data-element"), row: row };
      row.classList.add("lifted");
      e.dataTransfer.effectAllowed = "move";
    });

    list.addEventListener("dragover", function (e) {
      if (!drag) return;
      e.preventDefault();
      clearMarks(); drag.row.classList.add("lifted");
      var rows = Array.prototype.slice.call(list.querySelectorAll(".el-row"))
        .filter(function (r) { return r.getAttribute("data-element") !== drag.pk; });
      var before = null;
      for (var i = 0; i < rows.length; i++) {
        var box = rows[i].getBoundingClientRect();
        if (e.clientY < box.top + box.height / 2) { before = rows[i]; break; }
      }
      var line = document.createElement("li"); line.className = "el-drop-line";
      if (before) list.insertBefore(line, before); else list.appendChild(line);
    });

    list.addEventListener("dragend", clearMarks);

    list.addEventListener("drop", function (e) {
      if (!drag) return;
      e.preventDefault();
      // post-removal index = number of NON-dragged rows before the drop line
      var nodes = Array.prototype.slice.call(list.children);
      var lineIdx = nodes.findIndex(function (n) { return n.classList && n.classList.contains("el-drop-line"); });
      var position = 0;
      for (var i = 0; i < lineIdx; i++) {
        var n = nodes[i];
        if (n.classList && n.classList.contains("el-row") && n.getAttribute("data-element") !== drag.pk) position++;
      }
      var fd = new FormData();
      fd.append("ctx", "editor");
      fd.append("element", drag.pk);
      fd.append("unit", pane.getAttribute("data-unit"));
      fd.append("unit_token", pane.getAttribute("data-updated"));
      fd.append("position", String(position));
      var moveUrl = pane.getAttribute("data-move-url");
      drag = null; clearMarks();
      fetch(moveUrl, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          var tmp = document.createElement("div"); tmp.innerHTML = html.trim();
          ["editor", "preview"].forEach(function (scope) {
            var inc = tmp.querySelector('[data-scope="' + scope + '"]');
            var ex = root.querySelector('[data-scope="' + scope + '"]');
            if (inc && ex) ex.replaceWith(inc);
          });
          if (window.__libliEditorDnD) window.__libliEditorDnD(root);  // re-bind
          var prev = root.querySelector('[data-scope="preview"]');
          if (prev && window.libliRenderMath) window.libliRenderMath(prev);
        });
    });
  };
})();
```

(A 409/422 response is swapped in just like 200 — `clearMarks` already ran on drop, so no stale insertion line remains, satisfying the spec's "409 swap clears transient drag UI".)

- [ ] **Step 2: Load the DnD script before `editor.js`**

In `templates/courses/manage/editor/editor.html` `{% block extra_js %}` (lines 17-23), add the new script BEFORE `editor.js`:

```django
  <script src="{% static 'courses/js/editor_dnd.js' %}" defer></script>
  <script src="{% static 'courses/js/editor.js' %}" defer></script>
```

- [ ] **Step 3: Run check (JS is e2e-tested in Task 12)**

Run: `.venv/Scripts/python.exe manage.py check && .venv/Scripts/python.exe manage.py collectstatic --noinput`
Expected: no issues; collectstatic includes `editor_dnd.js`.

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/js/editor_dnd.js templates/courses/manage/editor/editor.html
git commit -m "feat(editor): pointer drag-and-drop element reorder (post-removal index)"
```

---

## Task 9: Icon-only text toolbar (#12)

**Files:**
- Modify: `templates/courses/manage/editor/_edit_text.html` (icon buttons + sprite refs)
- Modify: `templates/courses/manage/editor/editor.html` (inline `<svg>` sprite)
- Modify: `courses/static/courses/js/text_toolbar.js` (active-state)
- Modify: `courses/static/courses/css/editor.css` (toolbar restyle)

- [ ] **Step 1: Add an inline SVG symbol sprite to `editor.html`**

In `templates/courses/manage/editor/editor.html`, immediately after the opening `<section class="editor" …>` tag (line 10), insert the sprite (mirrors the builder's `builder__sprite` pattern):

```django
  <svg width="0" height="0" class="editor__sprite" aria-hidden="true" focusable="false">
    <symbol id="ed-bold" viewBox="0 0 16 16"><path fill="currentColor" d="M4 2h5a3 3 0 0 1 0 6H4zm0 6h6a3 3 0 0 1 0 6H4z"/></symbol>
    <symbol id="ed-italic" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M7 3h5M4 13h5M10 3 6 13"/></symbol>
    <symbol id="ed-underline" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M4 3v5a4 4 0 0 0 8 0V3M3 14h10"/></symbol>
    <symbol id="ed-ul" viewBox="0 0 16 16"><g fill="currentColor"><circle cx="3" cy="4" r="1.2"/><circle cx="3" cy="8" r="1.2"/><circle cx="3" cy="12" r="1.2"/></g><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M6 4h8M6 8h8M6 12h8"/></symbol>
    <symbol id="ed-ol" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M6 4h8M6 8h8M6 12h8"/><text x="1" y="5.5" font-size="5" fill="currentColor">1</text><text x="1" y="9.5" font-size="5" fill="currentColor">2</text><text x="1" y="13.5" font-size="5" fill="currentColor">3</text></symbol>
    <symbol id="ed-link" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M6.5 9.5a3 3 0 0 0 4.2 0l2-2a3 3 0 0 0-4.2-4.2l-1 1M9.5 6.5a3 3 0 0 0-4.2 0l-2 2a3 3 0 0 0 4.2 4.2l1-1"/></symbol>
    <symbol id="ed-quote" viewBox="0 0 16 16"><path fill="currentColor" d="M3 4h4v4H5c0 1 .5 1.5 1.5 2L5 12C3.5 11 3 9.5 3 8zm6 0h4v4h-2c0 1 .5 1.5 1.5 2L11 12c-1.5-1-2-2.5-2-4z"/></symbol>
    <symbol id="ed-code" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="m5 5-3 3 3 3m6-6 3 3-3 3"/></symbol>
  </svg>
```

- [ ] **Step 2: Rewrite `_edit_text.html` toolbar to icon buttons (+ headings as text)**

Replace `templates/courses/manage/editor/_edit_text.html` with:

```django
{% load i18n %}
<div class="el-editor el-editor--text">
  <div class="rte-toolbar" data-rte-toolbar>
    <button type="button" class="rte-btn" data-cmd="bold" title="{% trans 'Bold' %}" aria-label="{% trans 'Bold' %}"><svg class="ic"><use href="#ed-bold"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="italic" title="{% trans 'Italic' %}" aria-label="{% trans 'Italic' %}"><svg class="ic"><use href="#ed-italic"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="underline" title="{% trans 'Underline' %}" aria-label="{% trans 'Underline' %}"><svg class="ic"><use href="#ed-underline"/></svg></button>
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h2" title="{% trans 'Heading 2' %}">H2</button>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h3" title="{% trans 'Heading 3' %}">H3</button>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h4" title="{% trans 'Heading 4' %}">H4</button>
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn" data-cmd="ul" title="{% trans 'Bullet list' %}" aria-label="{% trans 'Bullet list' %}"><svg class="ic"><use href="#ed-ul"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="ol" title="{% trans 'Numbered list' %}" aria-label="{% trans 'Numbered list' %}"><svg class="ic"><use href="#ed-ol"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="link" title="{% trans 'Link' %}" aria-label="{% trans 'Link' %}"><svg class="ic"><use href="#ed-link"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="blockquote" title="{% trans 'Quote' %}" aria-label="{% trans 'Quote' %}"><svg class="ic"><use href="#ed-quote"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="code" title="{% trans 'Code' %}" aria-label="{% trans 'Code' %}"><svg class="ic"><use href="#ed-code"/></svg></button>
  </div>
  <textarea name="body" class="rte-source" data-rte-source rows="6">{{ form.body.value|default:"" }}</textarea>
  {% for e in form.body.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

- [ ] **Step 3: Add active-state reflection to `text_toolbar.js`**

In `courses/static/courses/js/text_toolbar.js`, inside `wireRte`, **immediately before the closing `}` of `wireRte`** (so `surface` and `toolbar` are in scope — do NOT place it outside the function), add a selection-driven active-state updater:

```javascript
    function refreshActive() {
      if (!toolbar) return;
      var map = { bold: "bold", italic: "italic", underline: "underline" };
      toolbar.querySelectorAll("[data-cmd]").forEach(function (btn) {
        var cmd = btn.getAttribute("data-cmd");
        if (map[cmd]) {
          var on = false;
          try { on = document.queryCommandState(map[cmd]); } catch (e) { on = false; }
          btn.classList.toggle("is-on", !!on);
        }
      });
    }
    surface.addEventListener("keyup", refreshActive);
    surface.addEventListener("mouseup", refreshActive);
    document.addEventListener("selectionchange", function () {
      if (document.activeElement === surface) refreshActive();
    });
```

(Bold/italic/underline only — heading active-state is intentionally not reflected, per spec §C.)

- [ ] **Step 4: Restyle the toolbar CSS**

In `courses/static/courses/css/editor.css`, replace the existing `.rte-toolbar` / `.rte-toolbar button` rules (lines 79-87) with:

```css
.rte-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 3px; margin-bottom: var(--space-2); }
.rte-btn { display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 30px; padding: 0; background: var(--surface-sunken);
  border: 1px solid var(--border-default); border-radius: var(--radius-sm);
  color: var(--text-primary); cursor: pointer; font-weight: 700; }
.rte-btn--text { width: auto; padding: 0 var(--space-2); font-size: .85rem; }
.rte-btn:hover { background: var(--surface-base); }
.rte-btn.is-on { background: var(--primary); color: var(--text-inverse); border-color: var(--primary); }
.rte-btn .ic { width: 15px; height: 15px; display: block; }
.rte-sep { width: 1px; align-self: stretch; background: var(--border-default); margin: 2px 3px; }
```

- [ ] **Step 5: Run check + collectstatic**

Run: `.venv/Scripts/python.exe manage.py check && .venv/Scripts/python.exe manage.py collectstatic --noinput`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/editor/_edit_text.html templates/courses/manage/editor/editor.html \
  courses/static/courses/js/text_toolbar.js courses/static/courses/css/editor.css
git commit -m "feat(editor): icon-only text toolbar with tooltips + active state (#12)"
```

---

## Task 10: Media manager + picker restyle (upload name, filter/search, inline rename, kind-lock)

**Files:**
- Modify: `templates/courses/manage/media/manager.html`
- Modify: `templates/courses/manage/media/_asset_cell.html`
- Modify: `templates/courses/manage/media/_picker.html`
- Modify: `courses/static/courses/js/media_picker.js`
- Modify: `courses/static/courses/css/editor.css`

- [ ] **Step 1: Restyle `manager.html` — optional name + grid-head filter/search/count**

Replace `templates/courses/manage/media/manager.html` `{% block content %}` (lines 5-26) with:

```django
{% block content %}
<section class="media-manager" data-course-slug="{{ course.slug }}"
         data-upload-url="{% url 'courses:manage_media_upload' slug=course.slug %}"
         data-rename-url="{% url 'courses:manage_media_rename' slug=course.slug %}"
         data-list-url="{% url 'courses:manage_media' slug=course.slug %}">
  <div class="page-head"><h1>{% trans "Media" %}</h1><span class="muted">{{ course.title }}</span></div>
  <div class="uploadcard">
    <form class="media-upload" method="post" enctype="multipart/form-data"
          action="{% url 'courses:manage_media_upload' slug=course.slug %}">
      {% csrf_token %}
      <label class="field">{% trans "Kind" %}
        <select name="kind"><option value="image">{% trans "Image" %}</option><option value="video">{% trans "Video" %}</option></select>
      </label>
      <label class="field">{% trans "File" %} <input type="file" name="file" required></label>
      <label class="field">{% trans "Name" %} <span class="muted">({% trans "optional" %})</span>
        <input type="text" name="name" placeholder="{% trans 'defaults to filename' %}"></label>
      <button class="btn" type="submit">{% trans "Upload" %}</button>
    </form>
    <div class="media-drop" hidden>{% trans "Drag & drop files here" %}</div>
  </div>
  <div class="gridhead">
    <form class="filters" method="get" action="{% url 'courses:manage_media' slug=course.slug %}" data-media-filters>
      <select name="kind" class="input" data-filter-kind>
        <option value="">{% trans "All types" %}</option>
        <option value="image"{% if kind == "image" %} selected{% endif %}>{% trans "Images" %}</option>
        <option value="video"{% if kind == "video" %} selected{% endif %}>{% trans "Videos" %}</option>
      </select>
      <label class="search"><input type="search" name="q" class="input" value="{{ q }}"
             placeholder="{% trans 'Search by name or filename…' %}" data-filter-q></label>
      <noscript><button class="btn btn--small" type="submit">{% trans "Filter" %}</button></noscript>
    </form>
    <span class="muted" data-media-count>{{ assets|length }} {% trans "files" %}</span>
  </div>
  {% include "courses/manage/media/_asset_grid.html" %}
</section>
{% endblock %}
```

- [ ] **Step 2: Restyle `_asset_cell.html` — display name + rename pencil + filename**

Replace `templates/courses/manage/media/_asset_cell.html` with:

```django
{% load i18n %}
<div class="asset-cell" data-asset-id="{{ asset.pk }}" data-kind="{{ asset.kind }}"
     data-url="{{ asset.file.url }}" data-name="{{ asset.display_name }}">
  {% if asset.kind == "image" %}
    <img class="asset-thumb" src="{{ asset.file.url }}" alt="">
  {% else %}
    <span class="asset-thumb asset-thumb--video">▶</span>
  {% endif %}
  <div class="asset-names">
    <span class="asset-dname" data-asset-dname>{{ asset.display_name }}</span>
    <button type="button" class="iconbtn iconbtn--pen" data-rename-asset="{{ asset.pk }}"
            aria-label="{% trans 'Rename' %}" title="{% trans 'Rename' %}">✎</button>
    <span class="asset-fname">{{ asset.original_filename }}</span>
  </div>
  {% with uses=img_uses|add:vid_uses %}
    <div class="asset-foot">
      {% if uses %}<span class="asset-uses">{% trans "in use" %} ×{{ uses }}</span>
      {% else %}<span class="muted">{% trans "unused" %}</span>{% endif %}
      <form class="asset-del" method="post"
            action="{% url 'courses:manage_media_delete' slug=course.slug pk=asset.pk %}" data-op="asset-delete">
        {% csrf_token %}
        <button type="submit" class="iconbtn iconbtn--danger"
                {% if uses %}disabled title="{% trans 'In use — cannot delete' %}"{% else %}title="{% trans 'Delete' %}"{% endif %}>🗑</button>
      </form>
    </div>
  {% endwith %}
</div>
```

- [ ] **Step 3: Add a search box + kind-locked Upload tab to `_picker.html`**

Replace `templates/courses/manage/media/_picker.html` with:

```django
{% load i18n %}
<div class="picker" data-kind="{{ kind }}"
     data-upload-url="{% url 'courses:manage_media_upload' slug=course.slug %}"
     data-search-url="{% url 'courses:manage_media_picker' slug=course.slug %}">
  <div class="picker__tabs">
    <button type="button" class="picker__tab is-on" data-tab="library">{% trans "Library" %}</button>
    <button type="button" class="picker__tab" data-tab="upload">{% trans "Upload" %}</button>
  </div>
  <div class="picker__panel" data-panel="library">
    <label class="search"><input type="search" class="input" data-picker-search
           placeholder="{% if kind == 'image' %}{% trans 'Search images…' %}{% else %}{% trans 'Search videos…' %}{% endif %}"></label>
    <div data-picker-grid>
      {% include "courses/manage/media/_picker_grid.html" %}
    </div>
  </div>
  <div class="picker__panel" data-panel="upload" hidden>
    <p class="muted">{% if kind == "image" %}{% trans "Upload an image — added and selected." %}{% else %}{% trans "Upload a video — added and selected." %}{% endif %}</p>
    <input type="file" class="picker__file" data-kind="{{ kind }}">
  </div>
</div>
```

- [ ] **Step 4: Extend `media_picker.js` — inline rename, debounced manager search, picker search**

In `courses/static/courses/js/media_picker.js`, inside `wireManager` (before its closing `}` at line 208), add inline rename + debounced filter:

```javascript
    // Inline rename: pencil swaps display name to an input; Enter saves, Esc cancels.
    var renameUrl = root.dataset.renameUrl;
    root.addEventListener("click", function (e) {
      var pen = e.target.closest("[data-rename-asset]");
      if (!pen) return;
      var cell = pen.closest(".asset-cell");
      var dname = cell.querySelector("[data-asset-dname]");
      if (!dname || cell.querySelector(".asset-rename-input")) return;
      var input = document.createElement("input");
      input.className = "asset-rename-input input"; input.value = dname.textContent.trim();
      dname.replaceWith(input); input.focus(); input.select();
      var done = false;
      function commit(save) {
        if (done) return;  // re-entrancy guard: Enter/Esc fires, then the focusout(blur) fires
        done = true;
        if (!save) { input.replaceWith(dname); return; }
        var fd = new FormData();
        fd.append("id", cell.getAttribute("data-asset-id"));
        fd.append("name", input.value);
        fetch(renameUrl, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd })
          .then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
          .then(function (res) {
            if (res.status !== 200) { input.replaceWith(dname); flash(root, "Rename failed."); return; }
            var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
            var fresh = tmp.querySelector(".asset-cell");
            if (fresh) cell.replaceWith(fresh);
          });
      }
      input.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { ev.preventDefault(); commit(true); }
        if (ev.key === "Escape") { ev.preventDefault(); commit(false); }
      });
      input.addEventListener("blur", function () { commit(true); });
    });

    // Debounced server-side filter (kind + q), swaps the grid; drops stale responses.
    var filters = root.querySelector("[data-media-filters]");
    var listUrl = root.dataset.listUrl;
    if (filters) {
      var seq = 0, timer;
      function runFilter() {
        var kind = (filters.querySelector("[data-filter-kind]") || {}).value || "";
        var q = (filters.querySelector("[data-filter-q]") || {}).value || "";
        var mine = ++seq;
        var url = listUrl + "?kind=" + encodeURIComponent(kind) + "&q=" + encodeURIComponent(q);
        fetch(url, { headers: { "X-Requested-With": "fetch" } })
          .then(function (r) { return r.text(); })
          .then(function (html) {
            if (mine !== seq) return;  // superseded
            var oldGrid = root.querySelector(".asset-grid");
            var tmp = document.createElement("div"); tmp.innerHTML = html.trim();
            var newGrid = tmp.querySelector(".asset-grid");
            if (oldGrid && newGrid) oldGrid.replaceWith(newGrid);
            var count = root.querySelector("[data-media-count]");
            if (count) count.textContent = (newGrid ? newGrid.querySelectorAll(".asset-cell").length : 0) + " files";
          });
      }
      filters.addEventListener("submit", function (e) { e.preventDefault(); runFilter(); });
      filters.querySelector("[data-filter-kind]").addEventListener("change", runFilter);
      filters.querySelector("[data-filter-q]").addEventListener("input", function () {
        clearTimeout(timer); timer = setTimeout(runFilter, 250);
      });
    }
```

In `wireEditorPicker`, add a debounced picker search (inside the `document.addEventListener("click"…)` region is fine, but add a dedicated `input` listener). After the `change` upload handler (line 117), add:

```javascript
    var psTimer, psSeq = 0;
    document.addEventListener("input", function (e) {
      if (!overlay) return;
      var box = e.target.closest("[data-picker-search]");
      if (!box || !overlay.contains(box)) return;
      var picker = overlay.querySelector(".picker");
      var kind = picker.getAttribute("data-kind");
      var base = picker.getAttribute("data-search-url");
      clearTimeout(psTimer);
      psTimer = setTimeout(function () {
        var mine = ++psSeq;
        var url = base + "?grid=1&kind=" + encodeURIComponent(kind) + "&q=" + encodeURIComponent(box.value);
        fetch(url, { headers: { "X-Requested-With": "fetch" } })
          .then(function (r) { return r.text(); })
          .then(function (html) {
            if (mine !== psSeq) return;
            var host = overlay.querySelector("[data-picker-grid]");
            if (host) host.innerHTML = html.trim();
          });
      }, 250);
    });
```

- [ ] **Step 5: Add the media-manager restyle CSS (upload card, grid head, cell names, foot)**

Append to `courses/static/courses/css/editor.css`:

```css
/* --- WS3 media manager restyle --- */
.page-head { display: flex; align-items: baseline; gap: var(--space-3); margin-bottom: var(--space-4); }
.muted { color: var(--text-tertiary); font-size: .85rem; }
.uploadcard { background: var(--surface-raised); border: 1px solid var(--border-default);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-xs); padding: var(--space-4); margin-bottom: var(--space-5); }
.field { display: flex; flex-direction: column; gap: 4px; font-size: .82rem; color: var(--text-secondary); }
.gridhead { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  margin-bottom: var(--space-3); flex-wrap: wrap; }
.filters { display: flex; align-items: center; gap: var(--space-3); }
.search { position: relative; }
.input { font-family: inherit; padding: 7px 10px; background: var(--surface-sunken);
  border: 1px solid var(--border-default); border-radius: var(--radius-sm); color: var(--text-primary); }
.asset-names { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.asset-dname { font-size: .9rem; font-weight: 600; color: var(--text-primary); }
.asset-fname { flex-basis: 100%; font-size: .72rem; color: var(--text-tertiary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-rename-input { width: 100%; font-weight: 600; }
.asset-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-top: auto; }
.iconbtn--pen { opacity: 0; border-color: transparent; }
.asset-cell:hover .iconbtn--pen { opacity: 1; }
.picker .search { display: block; margin-bottom: var(--space-4); }
.picker .search .input { width: 100%; }
```

- [ ] **Step 6: Run check + collectstatic + the media unit tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_manager.py tests/test_media_picker.py -q && .venv/Scripts/python.exe manage.py check && .venv/Scripts/python.exe manage.py collectstatic --noinput`
Expected: PASS; no issues.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/media/manager.html templates/courses/manage/media/_asset_cell.html \
  templates/courses/manage/media/_picker.html courses/static/courses/js/media_picker.js \
  courses/static/courses/css/editor.css
git commit -m "feat(media): manager/picker restyle — name, filter, search, inline rename, kind-locked picker"
```

---

## Task 11: i18n — wrap new strings + Polish

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Possibly modify: any new template with an unwrapped literal (audit)

- [ ] **Step 1: Audit new literals**

Run a grep over the WS3-touched templates/JS for unwrapped user-facing strings:

Use the `Grep` tool over `templates/courses/manage/editor/` and `templates/courses/manage/media/` for user-facing literals NOT inside a trans tag (search text nodes `>[A-Za-z]` and `placeholder="`/`title="` attributes that aren't `{% trans %}`-rendered). Every new template string in Tasks 6–10 is already `{% trans %}`-wrapped, so this is a confirmation scan, not new work. JS user-facing strings (`flash("Rename failed.")`, `"Upload failed."`, `"This changed elsewhere…"`) follow the existing editor.js/media_picker.js pattern of English-literal flashes; per the WS2 precedent, leave the JS flash literals as-is unless a `data-msg-*` attr already exists (none here) — they match the existing untranslated flashes in those files and are out of scope for this WS's PL gate (consistent with the spec's "JS notices via data-* attrs (the WS2 pattern)" only for *new* notice surfaces; these reuse existing untranslated ones). Note this explicitly in the commit.

- [ ] **Step 2: Extract messages**

Run: `.venv/Scripts/python.exe manage.py makemessages -l pl`
Expected: `locale/pl/LC_MESSAGES/django.po` updated with the new `{% trans %}` msgids (Editor, Live preview, Add element, Text/Image/Video/Iframe/Math, Bold/Italic/Underline/Heading 2-4/Bullet list/Numbered list/Link/Quote/Code, URL or embed code, Name, optional, All types, Images, Videos, Search by name or filename…, in use, unused, Rename, Drag to reorder, etc.).

- [ ] **Step 3: Fill in Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po` — provide `msgstr` for every new empty entry. Examples (use the project's established translations for repeats):

```
msgid "Editor"
msgstr "Edytor"

msgid "Live preview"
msgstr "Podgląd na żywo"

msgid "Add element"
msgstr "Dodaj element"

msgid "URL or embed code"
msgstr "Adres URL lub kod osadzenia"

msgid "Search by name or filename…"
msgstr "Szukaj wg nazwy lub pliku…"

msgid "in use"
msgstr "w użyciu"

msgid "unused"
msgstr "nieużywane"

msgid "Rename"
msgstr "Zmień nazwę"

msgid "Drag to reorder"
msgstr "Przeciągnij, aby zmienić kolejność"
```

(Translate ALL new empty msgstr; do not leave any blank for the new entries, and clear any `#, fuzzy` on entries you touch.)

- [ ] **Step 4: Compile**

Run: `.venv/Scripts/python.exe manage.py compilemessages -l pl`
Expected: `locale/pl/LC_MESSAGES/django.mo` regenerated; no errors.

- [ ] **Step 5: Verify no empty/fuzzy among the new entries**

Run: `.venv/Scripts/python.exe -m pytest tests/test_surfaces.py -q` (sanity that nothing broke) and visually confirm the new msgids have non-empty `msgstr`.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(ws3): Polish for editor/media polish strings"
```

---

## Task 12: Playwright e2e + DoD gate

**Files:**
- Create: `tests/test_e2e_editor_ws3.py`

- [ ] **Step 1: Write the e2e suite**

Create `tests/test_e2e_editor_ws3.py` (mirror `tests/test_e2e_builder_ws2.py` boilerplate — `pytestmark = pytest.mark.e2e`, the `_allow_sync_orm_under_playwright` autouse fixture, `_make_pa_user`, `_login`):

```python
"""Playwright e2e for WS3: inline add/edit, element drag-drop, embed paste, media
rename, picker kind-lock, toolbar active-state. Marked e2e (run with -m e2e)."""

import os
import pytest

from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group
    from institution.roles import PLATFORM_ADMIN, seed_roles
    seed_roles()
    u = make_verified_user(username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD)
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return u


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type=submit]").click()


def _seed_unit(pa, slug="ws3"):
    from tests.factories import CourseFactory, ContentNodeFactory
    course = CourseFactory(slug=slug, owner=pa)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, title="U")
    return course, unit


@pytest.mark.django_db(transaction=True)
def test_inline_add_text_persists(page, live_server):
    pa = _make_pa_user("ws3a")
    course, unit = _seed_unit(pa, "ws3a")
    _login(page, live_server, "ws3a")
    page.goto(f"{live_server.url}/manage/courses/ws3a/build/unit/{unit.pk}/edit/")
    page.locator("[data-add-toggle]").click()
    page.locator('[data-add-type="text"]').click()
    page.wait_for_selector("form[data-op='element-save']")
    page.locator(".rte-surface").fill("Hello world")
    page.locator("form[data-op='element-save'] button[type=submit]").first.click()
    page.wait_for_selector("text=Hello world")
    from courses.models import Element, TextElement
    assert Element.objects.filter(unit=unit).count() == 1
    # text_toolbar.js syncs the contenteditable surface -> hidden textarea on every `input`,
    # so fill() keeps name="body" current regardless of submit-listener order — assert the body.
    assert TextElement.objects.filter(body__icontains="Hello world").count() == 1


@pytest.mark.django_db(transaction=True)
def test_element_dnd_reorder(page, live_server):
    pa = _make_pa_user("ws3d")
    course, unit = _seed_unit(pa, "ws3d")
    from courses.models import Element, TextElement
    els = [Element.objects.create(unit=unit, content_object=TextElement.objects.create(body=f"<p>E{i}</p>")) for i in range(3)]
    _login(page, live_server, "ws3d")
    page.goto(f"{live_server.url}/manage/courses/ws3d/build/unit/{unit.pk}/edit/")
    page.wait_for_selector(".el-row")
    src = page.locator(f'.el-row[data-element="{els[0].pk}"] .ica--grip')
    dst = page.locator(f'.el-row[data-element="{els[2].pk}"]')
    src.drag_to(dst)
    page.wait_for_timeout(500)
    order = list(Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True))
    assert order[0] != els[0].pk  # E0 moved out of first slot


@pytest.mark.django_db(transaction=True)
def test_embed_paste_reject_stores_nothing(page, live_server):
    pa = _make_pa_user("ws3e")
    course, unit = _seed_unit(pa, "ws3e")
    _login(page, live_server, "ws3e")
    page.goto(f"{live_server.url}/manage/courses/ws3e/build/unit/{unit.pk}/edit/")
    page.locator("[data-add-toggle]").click()
    page.locator('[data-add-type="iframe"]').click()
    page.wait_for_selector("[data-embed-input]")
    page.locator("[data-embed-input]").fill('<iframe src="https://evil.example.com/x"></iframe>')
    page.locator("form[data-op='element-save'] button[type=submit]").first.click()
    page.wait_for_selector(".field-error")
    from courses.models import IframeElement
    assert IframeElement.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_picker_kind_locked_to_image(page, live_server):
    from tests.factories import CourseFactory, ContentNodeFactory
    from courses.models import MediaAsset
    pa = _make_pa_user("ws3p")
    course = CourseFactory(slug="ws3p", owner=pa)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, title="U")
    MediaAsset.objects.create(course=course, kind="image", file="i.png", original_filename="pic.png")
    MediaAsset.objects.create(course=course, kind="video", file="v.mp4", original_filename="clip.mp4")
    _login(page, live_server, "ws3p")
    page.goto(f"{live_server.url}/manage/courses/ws3p/build/unit/{unit.pk}/edit/")
    page.locator("[data-add-toggle]").click()
    page.locator('[data-add-type="image"]').click()
    page.wait_for_selector("[data-pick-media]")
    page.locator("[data-pick-media]").click()
    page.wait_for_selector(".picker")
    # only the image asset shows; the video is filtered out server-side
    assert page.locator(".asset-pick", has_text="pic.png").count() == 1
    assert page.locator(".asset-pick", has_text="clip.mp4").count() == 0
```

- [ ] **Step 2: Run the e2e suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_editor_ws3.py -m e2e -q`
Expected: PASS (4 tests). If `drag_to` proves flaky for the native HTML5 DnD, fall back to the manual dispatch pattern used in `tests/test_e2e_builder_ws2.py` (synthesising `dragstart`/`dragover`/`drop` events) — copy that helper.

- [ ] **Step 3: Run the full DoD gate**

Run each; all must pass:

```bash
.venv/Scripts/python.exe -m pytest -q            # default suite (-m 'not e2e')
.venv/Scripts/python.exe -m pytest -m e2e -q     # full e2e incl. builder + editor
.venv/Scripts/ruff check .
.venv/Scripts/ruff format --check .
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check   # only 0009 exists; "No changes"
.venv/Scripts/python.exe manage.py collectstatic --noinput
.venv/Scripts/python.exe manage.py compilemessages -l pl
```

Expected: all green; `makemigrations --check` reports no changes.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_editor_ws3.py
git commit -m "test(ws3): e2e for inline add/edit, element DnD, embed reject, picker kind-lock"
```

---

## Self-review notes (spec coverage)

- **Editor restyle / panes / breadcrumb / unit-title / icon back-nav** → Tasks 6 (+ #14a student title in 6, #14b in 6).
- **Inline row-expansion (open_form + open_form_pk + [data-edit-slot]) + 5-card add-menu + unsaved-new-row 422 re-emit** → Task 7 (the `new`-row branch in `_editor_scope.html` re-renders the typed form keyed by `new`; `element_save`'s 422 path already calls `_render_open_form(element_pk="new")`).
- **Element drag-and-drop (post-removal index, clamp, re-bind, 409 clears UI)** → Tasks 3 (backend) + 8 (JS).
- **Toolbar icon-only + tooltips + active state** → Task 9.
- **Embed paste #13 (parser, precedence, fixtures, store-only-src, responsive render, reject-aborts-save)** → Task 1.
- **MediaAsset.name / display_name / __str__ / element_summary / migration 0009** → Task 2.
- **Media manager full (optional name, filter, search, rename endpoint + JS, in-use badge + delete-guard kept)** → Tasks 4, 5, 10.
- **Picker (search, kind-locked, server-enforced)** → Tasks 5 (server `?kind=`/`?q=`) + 10 (UI).
- **i18n + compilemessages gate** → Task 11 + Task 12 gate.
- **Element editors restyle (`_edit_*`/`_host_form`)** → covered: `_edit_iframe` (Task 1), `_edit_text` (Task 9); image/video/math partials keep their fields and inherit the `.el-editor` styling — restyle is CSS-level via the existing `.el-editor` rules. If image/video/math partials need spacing tweaks, fold into Task 7's CSS (no field changes).
- **Concurrency unchanged (unit token, 409-before-422)** → reused; absolute-position path bumps `unit.updated` (Task 3).

**Type/name consistency check:** `reorder_element(course, element_pk, unit_token, *, direction=None, position=None)` used consistently in Task 3 service + view; `place_element(element, unit, position)` defined (Task 3) and referenced in the spec's `assign_orders_elements`/`place_element` note; `display_name` property used in Tasks 2/5/10 templates; `manage_media_rename` route (Task 4) referenced by `data-rename-url` (Task 10) and tests (Task 4); `_asset_grid.html`/`_picker_grid.html` created in Task 5, consumed in Tasks 5/10; `__libliEditorDnD` defined in Task 8, called from `editor.js` `bindDnD` (Task 7). `open_form_pk` defined in Task 7 across view + `_editor_scope.html` + `_element_row.html`.
