# Duplicate a unit in the course tree — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a **Duplicate** button to the course-builder tree that deep-copies a unit (sharing media) as a sibling immediately below the original.

**Architecture:** Reuse the existing `courses/transfer/` export→import engine. A new `build_export(..., drop_missing_media=False)` mode serializes the unit in-memory without dropping missing-media elements; a new `importer.materialize_duplicate(...)` rebuilds it sharing the existing `MediaAsset` rows; a new `builder.duplicate_unit(...)` service orchestrates lock/token/place; a new `node_duplicate` view + URL + template button (with a new `bi-duplicate` sprite symbol) wire it to the UI.

**Tech Stack:** Django 5.2, PostgreSQL, pytest / pytest-django, vanilla JS (`builder.js`), gettext i18n (EN + PL).

## Global Constraints

- **Tooling runs via `uv run`** — bare `pytest` / `python` / `ruff` are not on PATH. Run tests with `uv run pytest`, lint with `uv run ruff check` and `uv run ruff format --check`.
- **This is a git worktree** running alongside a parallel session's worktree. Postgres test DB `test_libli` collides across concurrent worktrees — set a **worktree-unique `DATABASE_URL`** (a distinct database name) before running tests so the derived `test_*` DB does not collide. Recover a stuck DB with `pg_terminate_backend` + `DROP DATABASE` if needed.
- **Never hardcode test passwords** — use `tests.factories.TEST_PASSWORD` (via `make_login`). GitGuardian flags literals.
- **i18n:** new translatable strings use `{% trans %}` / `gettext`. Module-level translatable strings must use `gettext_lazy`. After adding a string, run `makemessages` for EN+PL, fill the PL `msgstr`, remove any `#, fuzzy` flag, and `compilemessages`. Catalog tests assert **no** obsolete `#~` entries and no fuzzy flags.
- **Icons are monochrome `currentColor` sprite symbols** (`viewBox="0 0 16 16"`), never inline one-off or multicolour SVG. The builder action icons use the **stroked** convention (`fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"`).
- **Registry lockstep:** `ELEMENT_MODELS` / `SERIALIZERS` / `BUILDERS` must stay in lockstep. This feature adds **no** new element type, so `test_transfer_schema.py`'s count-31 assertion must remain green and unchanged.
- **Django template comments** `{# #}` must be single-line; use `{% comment %}` for multi-line.
- **Tests live under top-level `tests/`** (not `courses/tests/`, though some element-type tests live there). Factories are in `tests/factories.py`.

---

### Task 1: `drop_missing_media` flag on `build_export`

Add a keyword-only `drop_missing_media=True` parameter to `build_export`. Default `True` preserves today's drop/placeholder behavior for every existing caller. When `False`, Pass 3 treats every registered asset as present (`status="real"`), so no element is excluded and `media_assets` contains an entry for every referenced `mid`.

**Files:**
- Modify: `courses/transfer/export.py` (`build_export` signature ~line 443; Pass 3 loop ~lines 512-531)
- Test: `tests/test_transfer_export_nondrop.py` (create)

**Interfaces:**
- Produces: `build_export(course, node=None, source_host="", *, drop_missing_media=True) -> (manifest, document, media_assets, problems)`. `media_assets` is a list of `(mid, asset, is_placeholder)` where `asset` is a `MediaAsset` instance.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transfer_export_nondrop.py`:

```python
from courses.models import Element, ImageElement
from courses.transfer.export import build_export
from tests.factories import make_course_with_unit, make_image_asset


def _unit_with_missing_image():
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "gone.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(
            media=asset, alt="a", figcaption=""
        ),
    )
    # Remove the backing file so the export's on-disk probe reports it missing.
    asset.file.storage.delete(asset.file.name)
    return course, unit, asset


def _entry_for(media_assets, asset):
    return [(m, a, p) for (m, a, p) in media_assets if a.pk == asset.pk]


def test_missing_media_defaults_to_placeholder():
    course, unit, asset = _unit_with_missing_image()
    _manifest, document, media_assets, _problems = build_export(course, node=unit)
    entry = _entry_for(media_assets, asset)
    assert entry, "asset should still be represented"
    assert entry[0][2] is True  # is_placeholder — degraded in default mode


def test_drop_missing_media_false_keeps_asset_real():
    course, unit, asset = _unit_with_missing_image()
    _manifest, document, media_assets, _problems = build_export(
        course, node=unit, drop_missing_media=False
    )
    entry = _entry_for(media_assets, asset)
    assert entry, "every referenced mid must survive into media_assets"
    assert entry[0][2] is False  # treated as real, not placeholder
    assert len(document["elements"]) == 1  # element not dropped
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_transfer_export_nondrop.py -v`
Expected: `test_drop_missing_media_false_keeps_asset_real` FAILS with `TypeError: build_export() got an unexpected keyword argument 'drop_missing_media'`.

- [ ] **Step 3: Add the parameter and short-circuit Pass 3**

In `courses/transfer/export.py`, change the signature:

```python
def build_export(course, node=None, source_host="", *, drop_missing_media=True):
```

Then in **Pass 3** (the `for mid, asset in media_ids.items():` loop that assigns `status`), add the short-circuit branch at the top of the loop body:

```python
        for mid, asset in media_ids.items():
            if not drop_missing_media:
                # Duplicate mode: media rows are shared, not re-uploaded, so on-disk
                # presence is irrelevant. Treat every asset as real — nothing is
                # placeholdered or dropped, and every mid survives into media_assets.
                status[mid] = "real"
                try:
                    total_bytes += asset.file.size
                except OSError:
                    pass
                continue
            present = bool(asset.file.name) and asset.file.storage.exists(
                asset.file.name
            )
            if present:
                try:
                    total_bytes += asset.file.size
                    status[mid] = "real"
                except OSError:  # present-but-unreadable -> treat as missing
                    present = False
            if not present:
                if asset.kind == "image":
                    status[mid] = "placeholder"
                    total_bytes += _placeholder_size()
                else:
                    status[mid] = "dropped"
```

(Only the `if not drop_missing_media:` block is new; the rest is the existing Pass-3 body unchanged. Passes 4 and 5 then see no `"dropped"`/`"placeholder"` statuses and therefore drop/placeholder nothing.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_transfer_export_nondrop.py -v`
Expected: both PASS.

- [ ] **Step 5: Run the transfer regression suite (default behavior unchanged)**

Run: `uv run pytest tests/test_transfer_export.py tests/test_transfer_subtree.py tests/test_transfer_import.py -q`
Expected: all PASS (default `drop_missing_media=True` keeps existing callers' behavior).

- [ ] **Step 6: Commit**

```bash
git add courses/transfer/export.py tests/test_transfer_export_nondrop.py
git commit -m "feat(transfer): add drop_missing_media flag to build_export"
```

---

### Task 2: `materialize_duplicate` in the importer

Add an in-process materialize entry point that rebuilds an exported subtree into a course while **sharing** existing `MediaAsset` rows (via a precomputed `{mid: MediaAsset}` map), skipping the zip-coupled `_create_media`.

**Files:**
- Modify: `courses/transfer/importer.py` (add function next to `import_subtree` ~line 974)
- Test: `tests/test_transfer_materialize_duplicate.py` (create)

**Interfaces:**
- Consumes: `build_export(..., drop_missing_media=False)` output (Task 1); `_create_nodes`, `_create_elements`, `_run_import` (existing).
- Produces: `materialize_duplicate(document, media_map, target_course, insertion_node) -> ContentNode` (the new root node). `media_map` is `{mid: MediaAsset}`. `insertion_node` is a `ContentNode` or `None` (top level).

- [ ] **Step 1: Write the failing test**

Create `tests/test_transfer_materialize_duplicate.py`:

```python
from courses.models import ContentNode, Element, ImageElement, MediaAsset
from courses.transfer.export import build_export
from courses.transfer.importer import materialize_duplicate
from tests.factories import make_course_with_unit, make_image_asset


def test_materialize_duplicate_shares_media_and_creates_nodes():
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "pic.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(
            media=asset, alt="a", figcaption=""
        ),
    )
    _manifest, document, media_assets, _problems = build_export(
        course, node=unit, drop_missing_media=False
    )
    media_map = {mid: a for (mid, a, _p) in media_assets}

    before = ContentNode.objects.filter(course=course).count()
    new_root = materialize_duplicate(document, media_map, course, unit.parent)

    assert ContentNode.objects.filter(course=course).count() == before + 1
    assert new_root.pk != unit.pk
    # shared media: the copy's image element points at the SAME asset row
    new_img = new_root.elements.get().content_object
    assert new_img.media_id == asset.pk
    # no new MediaAsset rows were created
    assert MediaAsset.objects.filter(course=course).count() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_transfer_materialize_duplicate.py -v`
Expected: FAIL with `ImportError: cannot import name 'materialize_duplicate'`.

- [ ] **Step 3: Implement `materialize_duplicate`**

In `courses/transfer/importer.py`, add next to `import_subtree`:

```python
def materialize_duplicate(document, media_map, target_course, insertion_node):
    """In-process graft of an exported subtree into `target_course`, sharing the
    existing MediaAsset rows in `media_map` ({mid: MediaAsset}) instead of
    re-creating them. Mirrors `import_subtree`'s work() but skips `_create_media`
    (no zip, media is shared). Returns the new root ContentNode.

    Wrapped in `_run_import`, so any failure rolls back and is normalized to
    TransferError — the same guarantee `import_subtree` gives.
    """

    def work():
        node_map = _create_nodes(document, target_course, root_parent=insertion_node)
        _create_elements(document, node_map, media_map)
        return node_map[document["nodes"][0]["id"]]

    return _run_import(work, created_files=[])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_transfer_materialize_duplicate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/importer.py tests/test_transfer_materialize_duplicate.py
git commit -m "feat(transfer): add materialize_duplicate (shared-media in-process graft)"
```

---

### Task 3: `duplicate_unit` service in `builder.py`

Orchestrate the copy: lock the source + check token (raising `ConflictError` **before** the normalizing region), then export (non-dropping) → materialize (shared media) → place immediately below the source → bump `course.updated` for a top-level unit. Any failure other than `ConflictError` is normalized to `TransferError`.

**Files:**
- Modify: `courses/builder.py` (add function; `ConflictError`, `_locked_node`, `_check_token`, `ordering`, `ContentNode` already available)
- Test: `tests/test_builder_duplicate_unit.py` (create)

**Interfaces:**
- Consumes: `build_export(..., drop_missing_media=False)` (Task 1); `materialize_duplicate` (Task 2); `_locked_node`, `_check_token`, `ConflictError`, `ordering.place_node`, `ContentNode`.
- Produces: `duplicate_unit(course, node_pk, *, token) -> ContentNode` (the copy). Raises `ConflictError` (→409) on stale/vanished source; raises `TransferError` (→422) on any other failure, including a non-unit node.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_duplicate_unit.py`:

```python
import pytest

from courses.builder import ConflictError, duplicate_unit
from courses.models import (
    ChoiceQuestionElement,
    Choice,
    ContentNode,
    Element,
    ImageElement,
    MediaAsset,
    TabsElement,
    TextElement,
)
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit, make_image_asset


def _tok(node):
    return node.updated.isoformat()


def _rich_unit():
    course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>hi</p>")
    )
    q = ChoiceQuestionElement.objects.create(stem="Q", multiple=True)
    Choice.objects.create(question=q, text="a", is_correct=True)
    Choice.objects.create(question=q, text="b")
    Element.objects.create(unit=unit, content_object=q)
    asset = make_image_asset(course, "pic.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(
            media=asset, alt="a", figcaption=""
        ),
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="tabbed"),
        parent=join,
        tab_id=t2,
    )
    return course, unit, asset


def _images(node):
    return [
        e.content_object
        for e in node.elements.all()
        if isinstance(e.content_object, ImageElement)
    ]


def _texts(node):
    return [
        e.content_object
        for e in node.elements.all()
        if isinstance(e.content_object, TextElement)
    ]


def test_duplicate_rich_unit_equal_structure_and_shared_media():
    course, unit, asset = _rich_unit()
    src_elements = unit.elements.count()
    src_choices = Choice.objects.count()

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.pk != unit.pk
    assert copy.title == unit.title
    assert copy.elements.count() == src_elements
    assert Choice.objects.count() == src_choices * 2  # choices deep-copied
    assert MediaAsset.objects.filter(course=course).count() == 1  # media shared
    assert _images(copy)[0].media_id == asset.pk


def test_duplicate_is_immediate_next_sibling():
    course, unit, _asset = _rich_unit()
    copy = duplicate_unit(course, unit.pk, token=_tok(unit))
    siblings = list(
        ContentNode.objects.filter(course=course, parent=unit.parent).order_by(
            "order", "pk"
        )
    )
    i = [n.pk for n in siblings].index(unit.pk)
    assert siblings[i + 1].pk == copy.pk


def test_duplicate_independence():
    course, unit, _asset = _rich_unit()
    copy = duplicate_unit(course, unit.pk, token=_tok(unit))
    ct = _texts(copy)[0]
    ct.body = "<p>changed</p>"
    ct.save()
    assert _texts(unit)[0].body == "<p>hi</p>"


def test_duplicate_absent_media_keeps_real_shared_asset():
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "gone.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(
            media=asset, alt="a", figcaption=""
        ),
    )
    asset.file.storage.delete(asset.file.name)

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.elements.count() == 1
    assert copy.elements.get().content_object.media_id == asset.pk
    assert MediaAsset.objects.filter(course=course).count() == 1


def test_duplicate_dangling_element_is_skipped():
    course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>keep</p>")
    )
    orphan = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>gone</p>")
    )
    # Make the join DANGLE without cascading (deleting the concrete row would
    # cascade the join via GenericRelation): repoint object_id at a nonexistent
    # row so content_object resolves to None.
    Element.objects.filter(pk=orphan.pk).update(object_id=orphan.object_id + 10_000_000)

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.elements.count() == 1  # broken row silently skipped


def test_duplicate_stale_token_conflict():
    course, unit = make_course_with_unit()
    with pytest.raises(ConflictError):
        duplicate_unit(course, unit.pk, token="2000-01-01T00:00:00+00:00")


def test_duplicate_non_unit_raises_transfer_error():
    course, unit = make_course_with_unit()
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="C")
    with pytest.raises(TransferError):
        duplicate_unit(course, chapter.pk, token=chapter.updated.isoformat())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builder_duplicate_unit.py -v`
Expected: FAIL with `ImportError: cannot import name 'duplicate_unit' from 'courses.builder'`.

- [ ] **Step 3: Implement `duplicate_unit`**

In `courses/builder.py`, add:

```python
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
        new_node = _importer.materialize_duplicate(
            document, media_map, course, parent
        )
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
        raise  # 409 path — never normalize to 422
    except TransferError:
        raise  # already normalized by materialize's _run_import
    except Exception as exc:
        raise TransferError(str(exc) or "Duplicate failed.") from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builder_duplicate_unit.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint**

Run: `uv run ruff check courses/builder.py && uv run ruff format --check courses/builder.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add courses/builder.py tests/test_builder_duplicate_unit.py
git commit -m "feat(builder): add duplicate_unit service (shared-media deep copy)"
```

---

### Task 4: `node_duplicate` view + URL

Wire the service to a POST endpoint mirroring `node_move` / `node_delete`: manage-gated, non-unit → 404, stale token → 409 (fragment or notice), `TransferError` → 422, success → re-rendered scope fragment (or redirect for no-JS).

**Files:**
- Modify: `courses/views_manage.py` (add `node_duplicate`; add `TransferError` import)
- Modify: `courses/urls.py` (add `manage_node_duplicate` route)
- Test: `tests/test_manage_node_duplicate.py` (create)

**Interfaces:**
- Consumes: `builder.duplicate_unit` (Task 3); existing `_require_manage`, `_wants_fragment`, `_render_tree`, `_render_scope`, `_scope_ref`, `_conflict_scope`, `_builder_with_notice`, `get_node_or_404`.
- Produces: URL name `courses:manage_node_duplicate` (slug-only; node pk + token in POST body).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manage_node_duplicate.py`:

```python
from django.urls import reverse

from courses.models import ContentNode, Element, TextElement
from tests.factories import ContentNodeFactory, CourseFactory, make_login

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _setup(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(course=course, title="U1")
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>x</p>")
    )
    return owner, course, unit


def _url(course):
    return reverse("courses:manage_node_duplicate", kwargs={"slug": course.slug})


def test_duplicate_view_creates_sibling_fragment(client):
    _owner, course, unit = _setup(client)
    resp = client.post(
        _url(course), {"node": unit.pk, "token": unit.updated.isoformat()}, **FETCH
    )
    assert resp.status_code == 200
    assert ContentNode.objects.filter(course=course, title="U1").count() == 2


def test_duplicate_view_stale_token_409(client):
    _owner, course, unit = _setup(client)
    resp = client.post(
        _url(course),
        {"node": unit.pk, "token": "2000-01-01T00:00:00+00:00"},
        **FETCH,
    )
    assert resp.status_code == 409
    assert ContentNode.objects.filter(course=course, title="U1").count() == 1


def test_duplicate_view_requires_manage(client):
    _owner, course, unit = _setup(client)
    make_login(client, "intruder")  # not a manager of this course
    resp = client.post(
        _url(course), {"node": unit.pk, "token": unit.updated.isoformat()}
    )
    assert resp.status_code == 403


def test_duplicate_view_non_unit_404(client):
    _owner, course, unit = _setup(client)
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="C")
    resp = client.post(
        _url(course),
        {"node": chapter.pk, "token": chapter.updated.isoformat()},
        **FETCH,
    )
    assert resp.status_code == 404
    assert not ContentNode.objects.filter(course=course, title="C").exclude(
        pk=chapter.pk
    ).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_manage_node_duplicate.py -v`
Expected: FAIL with `NoReverseMatch: 'manage_node_duplicate' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the URL**

In `courses/urls.py`, next to the other `manage_node_*` routes, add:

```python
    path(
        "manage/courses/<slug:slug>/build/node/duplicate/",
        views_manage.node_duplicate,
        name="manage_node_duplicate",
    ),
```

- [ ] **Step 4: Add the `TransferError` import to `views_manage.py`**

Near the other imports in `courses/views_manage.py`, add:

```python
from courses.transfer.schema import TransferError
```

- [ ] **Step 5: Implement the view**

In `courses/views_manage.py`, add (mirrors `node_delete`'s POST branch):

```python
@login_required
def node_duplicate(request, slug):
    course = _require_manage(request, slug)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        node_pk = int(request.POST.get("node"))
    except (TypeError, ValueError):
        raise Http404("Missing or invalid node parameter.") from None
    node = get_node_or_404(node_pk, slug)
    if node.kind != "unit":
        raise Http404("Only units can be duplicated.")
    try:
        new_node = builder_svc.duplicate_unit(
            course, node_pk, token=request.POST.get("token")
        )
    except builder_svc.ConflictError:
        if not _wants_fragment(request):
            return _builder_with_notice(
                request,
                course,
                _("This changed elsewhere — reloaded to the latest."),
                status=409,
            )
        return _conflict_scope(request, course, node_pk)
    except TransferError as exc:
        msg = str(exc)
        if not _wants_fragment(request):
            return _builder_with_notice(request, course, msg, status=422)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    if new_node.parent_id is None:
        return _render_tree(request, course)
    return _render_scope(request, course, _scope_ref(new_node.parent_id))
```

(Confirm `HttpResponseBadRequest` and `Http404` are already imported in `views_manage.py` — `node_move`/`node_delete` use them; add to the import line if the linter flags them missing.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_manage_node_duplicate.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/views_manage.py courses/urls.py tests/test_manage_node_duplicate.py
git commit -m "feat(manage): add node_duplicate view + URL"
```

---

### Task 5: Template button, `bi-duplicate` sprite symbol, i18n

Add the Duplicate button to the tree action cluster (gated on `kind == "unit"`, `data-op="duplicate"` POST form), a matching `bi-duplicate` sprite symbol, and the EN+PL "Duplicate" translation.

**Files:**
- Modify: `templates/courses/manage/_icon_sprite.html` (add `bi-duplicate` symbol)
- Modify: `templates/courses/manage/_tree_node.html` (add the button, unit-gated)
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (via `makemessages`) + compiled `.mo`
- Test: `tests/test_manage_duplicate_button.py` (create)

**Interfaces:**
- Consumes: URL `courses:manage_node_duplicate` (Task 4); `builder.js`'s `form[data-op]` handler (existing — swaps 200/409 fragments, shows 422 notice).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manage_duplicate_button.py`:

```python
from django.urls import reverse
from django.utils import translation

from courses.models import ContentNode, Element, TextElement
from tests.factories import ContentNodeFactory, CourseFactory, make_login


def _builder_html(client, course):
    resp = client.get(
        reverse("courses:manage_builder", kwargs={"slug": course.slug})
    )
    assert resp.status_code == 200
    return resp.content.decode()


def test_duplicate_button_present_for_unit(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(course=course, title="U1")
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>x</p>")
    )
    html = _builder_html(client, course)
    assert 'data-op="duplicate"' in html
    assert "#bi-duplicate" in html


def test_duplicate_button_only_on_units(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, title="U1")  # a unit
    ContentNode.objects.create(course=course, kind="chapter", title="Chap")  # not
    html = _builder_html(client, course)
    assert html.count('data-op="duplicate"') == 1  # only the unit


def test_bi_duplicate_symbol_defined(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, title="U1")
    html = _builder_html(client, course)
    assert 'id="bi-duplicate"' in html


def test_duplicate_label_translated_pl():
    with translation.override("pl"):
        assert translation.gettext("Duplicate") == "Duplikuj"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_manage_duplicate_button.py -v`
Expected: all FAIL (`data-op="duplicate"` / `#bi-duplicate` absent; PL `gettext("Duplicate")` returns `"Duplicate"`).

- [ ] **Step 3: Add the `bi-duplicate` sprite symbol**

In `templates/courses/manage/_icon_sprite.html`, among the existing `bi-*` symbols (before the `el-*` block), add (stroked convention, two overlapping rounded rects):

```html
<symbol id="bi-duplicate" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M6 6h6v6H6z M4 10V4h6v2"/></symbol>
```

- [ ] **Step 4: Add the Duplicate button to the tree cluster**

In `templates/courses/manage/_tree_node.html`, inside `<span class="tree__cluster">`, immediately **after** the Export `<a>` and **before** the Delete `<a>`, add:

```html
      {% if node.kind == "unit" %}
      <form class="tree__inline" method="post" action="{% url 'courses:manage_node_duplicate' slug=node.course.slug %}" data-op="duplicate">
        {% csrf_token %}
        <input type="hidden" name="node" value="{{ node.pk }}">
        <input type="hidden" name="token" value="{{ node.updated.isoformat }}">
        <button class="ica" type="submit" aria-label="{% trans 'Duplicate' %}" title="{% trans 'Duplicate' %}"><svg class="ic"><use href="#bi-duplicate"/></svg></button>
      </form>
      {% endif %}
```

- [ ] **Step 5: Extract and translate the string**

Run: `uv run python manage.py makemessages -l en -l pl`

Then edit `locale/pl/LC_MESSAGES/django.po`: find `msgid "Duplicate"`, set `msgstr "Duplikuj"`, and remove any `#, fuzzy` flag on that entry. In `locale/en/LC_MESSAGES/django.po`, set `msgstr "Duplicate"` for the same msgid (remove any fuzzy flag).

Then compile:

Run: `uv run python manage.py compilemessages`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_manage_duplicate_button.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the i18n catalog tests (no obsolete/fuzzy regressions)**

Run: `uv run pytest -k "i18n or catalog or messages" -q`
Expected: PASS (no `#~` obsolete entries, no stray fuzzy flags). If a catalog test names a specific file, run it directly.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/_icon_sprite.html templates/courses/manage/_tree_node.html locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo locale/pl/LC_MESSAGES/django.mo tests/test_manage_duplicate_button.py
git commit -m "feat(manage): add Duplicate button + bi-duplicate icon + i18n"
```

---

### Task 6: Full-suite regression + final verification

Confirm the whole feature works end-to-end and nothing regressed.

**Files:** none (verification only)

- [ ] **Step 1: Run the full non-e2e suite**

Run: `uv run pytest -q`
Expected: all PASS (remember the worktree-unique `DATABASE_URL`).

- [ ] **Step 2: Confirm the `ELEMENT_MODELS` count assertion is untouched and green**

Run: `uv run pytest tests/test_transfer_schema.py -v`
Expected: `test_element_models_lists_all_31_concrete_element_models` PASSES (count still 31 — no new element type added).

- [ ] **Step 3: Lint the whole diff**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors.

- [ ] **Step 4: Drive the feature in the real app (verify skill)**

Follow the repo's `verify` / `run` skill to launch the builder, open a course with a unit, click **Duplicate**, and confirm a copy appears immediately below the original with identical content, and that the shared image still renders. Screenshot light + dark per the UI-verification convention.

- [ ] **Step 5: Commit any verification fixes** (only if Step 4 surfaced issues)

```bash
git add -A
git commit -m "fix(duplicate-unit): address verification findings"
```
