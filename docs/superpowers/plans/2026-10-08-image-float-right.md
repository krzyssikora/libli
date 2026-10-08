# Image "Float right" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An author ticks "Float right" on a Small image; the image sits at the right of its column and the following text wraps beside it, on desktop and on a phone.

**Architecture:** A `float_right` boolean on `ImageElement`, effective only for Small (`ImageElement.floats`). The figure gains `el--image--float`; ALL layout lives in one new `courses.css` block that floats the image's WRAPPER (chosen by `:has()`), clears non-text siblings, contains the float in every list/slide, and fixes the notes interactions (stacking, rail handle, in-flow pops, print). No JS beyond a live-preview branch in the existing editor handler; no container queries.

**Tech Stack:** Django 5 models/forms/templates, plain CSS (`:has()`, `:is()`), vanilla JS (editor.js), pytest + Playwright (sync) e2e.

**Spec:** `docs/superpowers/specs/2026-10-07-image-float-right-design.md` — read it first; its Owner decisions table (D1–D10) is VERBATIM and may not be reversed. D5 is WITHDRAWN (Small only).

## Global Constraints

- Small ONLY floats: `floats == float_right and size == "small"` (D2). Medium/Large/Full: checkbox disabled, stored `true` ignored.
- NO `container-type` / `@container` anywhere in this work (D5, spec "No width measuring").
- Off by default; a page with no floated image renders byte-for-byte as today, except the unscoped clearing rules, which are no-ops without a float (D10).
- Every quiz-context selector containing `section[data-element-id]` carries the quiz scope `.quiz .slide > ` (a bare one clears every LESSON text block).
- Preview top-level selector is `section.prev-el` (the `section` qualifier is required).
- Never nest `:has()` inside `:has()` — the browser drops the whole rule silently.
- `FORMAT_VERSION` 16 → 17 (`courses/transfer/schema.py`). Migration = next after master's graph head (0069 today).
- Tooling: `uv run …`; never pass `-q` to pytest; e2e needs `-m e2e`; start the test DB first (`docker compose -p libli-test -f docker-compose.test.yml up -d --wait`). If port 55433 is Windows-reserved, use the alt container on 56433 (memory note).
- After ANY CSS edit run every `tests/test_*css*.py` and `courses/tests/test_*css*.py`.
- Falsify every new e2e: remove the rule it guards BY HAND (never `git checkout` a mutant), confirm RED with the expected message, restore, confirm GREEN.

## Review Focus

1. **A floated image as the FIRST element of a unit** (nothing before it): the image must sit at the top right and the first paragraph wrap — no preceding block to clear against. → Task 6, e2e `test_float_as_first_element`.
2. **Two floated images in a row**: the second must stack below the first (it clears), never sit beside it. → Task 6, e2e `test_two_floats_stack`.
3. **A floated image whose following text is a single short line**: the next non-text block must start below the image, not beside it. → covered by Task 6 `test_non_text_after_float_starts_below` (short text fixture).
4. **Switching size to Medium in the editor after ticking**: the preview must un-float immediately, the box unticks, and the save stores `false`. → Task 3 e2e + Task 2 form test.
5. **Reveal gates** (`[data-reveal-gate]`) hiding blocks after a float: the floated image must not overlap the gate button. → Task 6, e2e `test_float_before_reveal_gate`.

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/models.py` (ImageElement) | `float_right` field, `floats` property |
| `courses/migrations/0069_imageelement_float_right.py` | AddField |
| `courses/element_forms.py` (ImageElementForm) | field + `clean()` forcing False unless Small |
| `templates/courses/manage/editor/_edit_image.html` | the checkbox |
| `courses/static/courses/js/editor.js` | live preview branch in the ONE delegated change handler |
| `templates/courses/elements/imageelement.html` | `el--image--float` class |
| `courses/transfer/{export,payloads,importer,schema}.py` | serialise/validate/build + version 17 |
| `courses/static/courses/css/courses.css` | the whole float block (one section, after the image print block at `@media print { .el--image… }` ~:159) |
| `locale/pl/LC_MESSAGES/django.{po,mo}` | "Float right" |
| `courses/tests/test_image_float_{model,editor,render,transfer,js,css}.py` | unit/source tests |
| `tests/image_float_kit.py` | shared e2e seeding/measuring helpers |
| `tests/test_e2e_image_float_{layout,containers,notes,editor}.py` | browser tests |

---

### Task 1: Model field, migration, `floats`

**Files:**
- Modify: `courses/models.py` (class `ImageElement`, after the `size` field)
- Create: `courses/migrations/0069_imageelement_float_right.py` (via makemigrations)
- Test: `courses/tests/test_image_float_model.py`

**Interfaces:**
- Produces: `ImageElement.float_right: BooleanField(default=False)`; `ImageElement.floats -> bool` (property).

- [ ] **Step 1: Write the failing test**

```python
import pytest

from courses.models import ImageElement

SIZES = ["small", "medium", "large", "full"]


def test_float_right_defaults_to_false():
    assert ImageElement().float_right is False


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("flag", [True, False])
def test_floats_only_for_a_flagged_small(size, flag):
    # D2: Small only. A stored True on Medium/Large/Full (import, legacy) is ignored.
    assert ImageElement(size=size, float_right=flag).floats is (flag and size == "small")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_image_float_model.py -p no:cacheprovider`
Expected: FAIL — `TypeError: ImageElement() got unexpected keyword 'float_right'` / AttributeError.

- [ ] **Step 3: Implement**

In `ImageElement`, directly after `size = models.CharField(...)`:

```python
    # "Float right" (spec 2026-10-07-image-float-right-design.md). Honoured for
    # Small only -- see `floats`; a True stored on another size (import, legacy)
    # is kept but ignored, so switching back to Small restores nothing silently:
    # the editor form clears it on any non-Small save.
    float_right = models.BooleanField(default=False)
```

and after `elements = GenericRelation(Element)`:

```python
    @property
    def floats(self):
        """Effective float: the ONE definition the template, form and tests share."""
        return self.float_right and self.size == self.Size.SMALL
```

Then: `uv run python manage.py makemigrations courses -n imageelement_float_right`. Check the generated file's `dependencies` names master's current head (`0068_alter_calloutelement_kind` today) — if master moved, rebase first.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest courses/tests/test_image_float_model.py courses/tests/test_image_size_model.py -p no:cacheprovider`
Expected: all PASS. Also `uv run python manage.py makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 5: Commit**

```bash
git add courses/models.py courses/migrations/0069_imageelement_float_right.py courses/tests/test_image_float_model.py
git commit -m "feat(image): float_right field, effective for Small only"
```

---

### Task 2: Editor form + checkbox + i18n

**Files:**
- Modify: `courses/element_forms.py` (`ImageElementForm`)
- Modify: `templates/courses/manage/editor/_edit_image.html` (after `</fieldset>` of `.size-presets`)
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `courses/tests/test_image_float_editor.py`

**Interfaces:**
- Consumes: `ImageElement.float_right`, `ImageElement.floats` (Task 1).
- Produces: checkbox `<input type="checkbox" name="float_right" data-float-right data-for-element="<pk or ''>">`; Task 3's JS finds it by `[data-float-right]` inside `.el-editor--image`.

- [ ] **Step 1: Write the failing tests**

```python
import re

import pytest
from django.template.loader import render_to_string

from courses.element_forms import ImageElementForm
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )


def _post(media, **extra):
    data = {"media": media.pk, "alt": "a", "figcaption": "", "size": "small"}
    data.update(extra)
    return ImageElementForm(data=data, course=media.course)


def test_form_saves_the_flag_on_small(image_media):
    form = _post(image_media, float_right="on")
    assert form.is_valid(), form.errors
    assert form.save().float_right is True


@pytest.mark.parametrize("size", ["medium", "large", "full"])
def test_a_non_small_post_with_the_flag_stores_false(image_media, size):
    form = _post(image_media, size=size, float_right="on")
    assert form.is_valid(), form.errors
    assert form.save().float_right is False


def test_an_edit_without_the_key_stores_false(image_media):
    el = ImageElement.objects.create(media=image_media, size="small", float_right=True)
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "b", "figcaption": "", "size": "small"},
        instance=el,
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert form.save().float_right is False  # an unchecked checkbox submits nothing


def _box(form):
    html = render_to_string("courses/manage/editor/_edit_image.html", {"form": form})
    m = re.search(r"<input[^>]*data-float-right[^>]*>", html)
    assert m, "no float-right checkbox rendered"
    return m.group(0)


def test_a_stored_true_on_medium_renders_unchecked_and_disabled(image_media):
    el = ImageElement.objects.create(media=image_media, size="medium", float_right=True)
    tag = _box(ImageElementForm(instance=el, course=image_media.course))
    assert " checked" not in tag and " disabled" in tag


def test_a_flagged_small_renders_checked_and_enabled(image_media):
    el = ImageElement.objects.create(media=image_media, size="small", float_right=True)
    tag = _box(ImageElementForm(instance=el, course=image_media.course))
    assert " checked" in tag and " disabled" not in tag


def test_the_create_flow_renders_the_box_disabled(image_media):
    # A new image defaults to Full.
    tag = _box(ImageElementForm(course=image_media.course))
    assert " disabled" in tag and 'data-for-element=""' in tag


def test_an_invalid_post_keeps_the_authors_size_and_tick(image_media):
    form = _post(image_media, float_right="on", figcaption="x" * 100_000)
    assert not form.is_valid()
    tag = _box(form)
    assert " checked" in tag and " disabled" not in tag
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest courses/tests/test_image_float_editor.py -p no:cacheprovider`
Expected: FAIL (`float_right` not in form; "no float-right checkbox rendered").

- [ ] **Step 3: Implement the form**

```python
class ImageElementForm(_CourseScopedMediaForm):
    media_kind = "image"

    class Meta:
        model = ImageElement
        fields = ["media", "alt", "figcaption", "size", "float_right"]

    # ... existing __init__ / clean_figcaption unchanged ...

    def clean(self):
        cleaned = super().clean()
        # D2: only Small floats. The checkbox is disabled (so unsubmitted) for other
        # sizes; this makes a hand-crafted POST agree with it.
        if cleaned.get("size") != ImageElement.Size.SMALL:
            cleaned["float_right"] = False
        return cleaned
```

(If `ImageElementForm` or `_CourseScopedMediaForm` already defines `clean()`, extend it — call `super().clean()` first and keep its body.)

- [ ] **Step 4: Implement the template** — after the size `</fieldset>`:

```django
  {% comment %}Float right (Small only, spec D1/D2). State comes from the FORM's values,
     like the size radios: an invalid POST keeps the author's tick; an unbound form shows
     the stored values, so a legacy True on a non-Small image shows unchecked.{% endcomment %}
  {% with size=form.size.value|stringformat:"s" %}
  <label class="float-right-toggle">
    <input type="checkbox" name="float_right" data-float-right
      data-for-element="{{ form.instance.pk|default_if_none:'' }}"
      {% if form.float_right.value and size == "small" %} checked{% endif %}
      {% if size != "small" %} disabled{% endif %}> {% trans "Float right" %}
  </label>
  {% endwith %}
```

Note `{% comment %}` is used because `{# #}` is single-line only (shipped broken 5 times in this repo).

- [ ] **Step 5: i18n**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`. In `locale/pl/LC_MESSAGES/django.po` set `msgid "Float right"` → `msgstr "Z prawej, obok tekstu"` (wording flagged in the PR for the owner) and DELETE any `#, fuzzy` line above it AND any `#| msgid` line (two deletions). Run `uv run python manage.py compilemessages`. Verify: `grep -n -B2 'msgid "Float right"' locale/pl/LC_MESSAGES/django.po` shows no `fuzzy`.

Add to the test file:

```python
from pathlib import Path

PO = Path(__file__).resolve().parents[2] / "locale/pl/LC_MESSAGES/django.po"


def test_polish_label_exists_and_is_not_fuzzy():
    text = PO.read_text(encoding="utf-8")
    block = re.search(r'((?:#[^\n]*\n)*)msgid "Float right"\nmsgstr "([^"]*)"', text)
    assert block, "msgid missing"
    assert "fuzzy" not in block.group(1) and block.group(2)
```

- [ ] **Step 5b: Style check** — open the image editor (dev server, any Small image), screenshot light + dark. The checkbox and label must sit on one line under the size radios, aligned with them. If app.css's `label`/`input` rules break that, add `.float-right-toggle { display: inline-flex; gap: var(--space-2); align-items: center; margin-top: var(--space-2); }` to `core/static/core/css/app.css` beside `.size-presets` and re-check.

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest courses/tests/test_image_float_editor.py courses/tests/test_image_size_editor.py -p no:cacheprovider`
Expected: all PASS (the size-editor suite proves the existing radios still work).

- [ ] **Step 7: Commit**

```bash
git add courses/element_forms.py templates/courses/manage/editor/_edit_image.html locale/ courses/tests/test_image_float_editor.py
git commit -m "feat(image): Float right checkbox in the image editor (Small only)"
```

---

### Task 3: Live preview in editor.js

**Files:**
- Modify: `courses/static/courses/js/editor.js` (the `var preset = e.target.closest("[data-size-preset]")` branch in the delegated `change` handler, ~:731)
- Test: `courses/tests/test_image_float_js.py`, `tests/test_e2e_image_float_editor.py`

**Interfaces:**
- Consumes: `[data-float-right]` checkbox (Task 2); figure `.el--image[data-preview-el="<pk>"]`.
- Produces: the preview figure toggles `el--image--float`.

- [ ] **Step 1: Write the failing source test**

```python
import re
from pathlib import Path

EDITOR_JS = Path(__file__).resolve().parents[2] / "courses/static/courses/js/editor.js"


def _code():
    src = EDITOR_JS.read_text(encoding="utf-8")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(?m)//.*$", "", src)


def test_float_branch_lives_in_the_one_delegated_handler():
    code = _code()
    assert "data-float-right" in code
    assert "el--image--float" in code
    assert EDITOR_JS.read_text(encoding="utf-8").count('addEventListener("change"') == 1


def test_the_size_handler_finds_its_box_inside_its_own_editor():
    # Not by data-for-element: that is "" for EVERY unsaved image on the create flow.
    assert 'closest(".el-editor--image")' in _code()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_image_float_js.py -p no:cacheprovider` → FAIL.

- [ ] **Step 3: Implement** — replace the preset branch's body end and add a sibling branch:

```js
    var preset = e.target.closest("[data-size-preset]");
    if (preset) {
      var fig = document.querySelector(
        '.el--image[data-preview-el="' + preset.dataset.forElement + '"]'
      );
      if (fig) {
        fig.classList.remove(
          "el--image--small", "el--image--medium", "el--image--large", "el--image--full"
        );
        fig.classList.add("el--image--" + preset.value);
      }
      // Float right is Small-only (spec D2). Found inside THIS editor, never by
      // data-for-element: that is "" for every unsaved image on the create flow.
      var editorEl = preset.closest(".el-editor--image");
      var box = editorEl && editorEl.querySelector("[data-float-right]");
      if (box) {
        var small = preset.value === "small";
        if (!small) box.checked = false;
        box.disabled = !small;
        if (fig) fig.classList.toggle("el--image--float", small && box.checked);
      }
      return;
    }
    var floatBox = e.target.closest("[data-float-right]");
    if (floatBox) {
      var ffig = document.querySelector(
        '.el--image[data-preview-el="' + floatBox.dataset.forElement + '"]'
      );
      if (ffig) ffig.classList.toggle("el--image--float", floatBox.checked);
      return;
    }
```

Keep the existing CREATE-flow comment that sits after the size swap.

- [ ] **Step 4: Run** `uv run pytest courses/tests/test_image_float_js.py courses/tests/test_image_size_js.py -p no:cacheprovider` → PASS.

- [ ] **Step 5: Write the e2e** (needs Task 4's class + Task 6's CSS to show geometry; this task asserts CLASS and box state only, geometry lives in Task 6). Create `tests/image_float_kit.py` now (used by all e2e tasks):

```python
"""Shared seeding/measuring for the image Float-right e2e suites."""

import os

import pytest

from courses.models import ImageElement
from courses.models import TextElement
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

PHONE = {"width": 367, "height": 800}
DESKTOP = {"width": 1300, "height": 900}
PARA = (
    "Flaga jest uszyta z czterech trójkątów w dwóch różnych kolorach oraz naszytego "
    "na nie koła w trzecim kolorze, jak na rysunku obok."
)

# Image <img> tags carry no width/height: EVERY geometry read must wait for decode.
WAIT_IMAGES = """async () => {
  for (let i = 0; i < 200; i++) {
    const imgs = [...document.images];
    if (imgs.length && imgs.every(im => im.complete && im.naturalWidth > 0)) return true;
    await new Promise(r => setTimeout(r, 25));
  }
  return false;
}"""


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)  # live_server serves /media/ from here
    return tmp_path


def make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state("load")


def seed_unit(owner, slug, unit_type="lesson"):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="U"
    )
    return course, unit


def image(course, *, size="small", float_right=True, px=(300, 200), alt="img", caption=""):
    asset = make_image_asset(course, size=px, color="red")
    return ImageElement.objects.create(
        media=asset, alt=alt, size=size, float_right=float_right, figcaption=caption
    )


def text(body=PARA):
    return TextElement.objects.create(body=f"<p>{body}</p>")


def unit_url(live_server, unit):
    base = f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"
    return base + ("quiz/" if unit.unit_type == "quiz" else "")


def editor_url(live_server, unit):
    return f"{live_server.url}/manage/courses/{unit.course.slug}/build/unit/{unit.pk}/edit/"


def open_page(page, url, viewport):
    page.set_viewport_size(viewport)
    page.goto(url)
    page.wait_for_load_state("load")
    assert page.evaluate(WAIT_IMAGES), "fixture images never decoded"
    page.evaluate("() => document.fonts.ready")


def rect(page, selector):
    return page.locator(selector).first.evaluate("e => e.getBoundingClientRect().toJSON()")


def first_line(page, selector):
    """Box of the first rendered line of the text in `selector`."""
    return page.evaluate(
        """(sel) => { const el = document.querySelector(sel);
             const r = document.createRange(); r.selectNodeContents(el);
             return r.getClientRects()[0].toJSON(); }""",
        selector,
    )


# KEEP THIS LAST: helpers added by later tasks go ABOVE it, or the star import
# in the e2e files silently drops them.
__all__ = [n for n in dir() if not n.startswith("__")]
```

Add to `pyproject.toml` under `[tool.ruff.lint.per-file-ignores]`:

```toml
"tests/test_e2e_image_float_*.py" = ["S105", "S106", "S107", "F403", "F405"]  # star import of tests/image_float_kit.py
```

and drop the `# noqa: F403` comments from the e2e imports. Every task: `uv run ruff format <files>` then `uv run ruff check --no-cache <files>`; wrap any JS string over 88 columns by hand (ruff cannot).

Then `tests/test_e2e_image_float_editor.py`:

```python
import pytest

from tests.factories import add_element
from tests.image_float_kit import *

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _open_editor(page, live_server, unit, element):
    page.goto(editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f'.el-act-edit[data-element-id="{element.pk}"]').click()
    page.wait_for_selector("[data-edit-slot] [data-float-right]")


def test_preview_floats_live_and_size_change_unticks(page, live_server):
    owner = make_pa_user("pa-float-ed")
    course, unit = seed_unit(owner, "float-ed")
    img = image(course, float_right=False)
    join = add_element(unit, img)
    add_element(unit, text())
    login(page, live_server, "pa-float-ed")
    _open_editor(page, live_server, unit, join)
    fig = page.locator(f'.el--image[data-preview-el="{img.pk}"]')
    box = page.locator("[data-edit-slot] [data-float-right]")

    box.check()
    assert "el--image--float" in fig.get_attribute("class")  # no save needed
    page.locator("[data-edit-slot] [data-size-preset][value='medium']").check()
    assert box.is_disabled() and not box.is_checked()
    assert "el--image--float" not in fig.get_attribute("class")
    page.locator("[data-edit-slot] [data-size-preset][value='small']").check()
    assert box.is_enabled() and not box.is_checked()  # author re-ticks deliberately
    box.check()
    page.locator("[data-edit-slot] [data-size-preset][value='large']").check()
    assert box.is_disabled() and not box.is_checked()
    assert "el--image--float" not in fig.get_attribute("class")
    page.locator("[data-edit-slot] [data-size-preset][value='small']").check()
    box.check()
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-float-right]", state="detached")
    img.refresh_from_db()
    assert img.float_right is True and img.floats
```

- [ ] **Step 6: Run** (green at Task 3 — it asserts classes editor.js toggles, not layout): `uv run pytest tests/test_e2e_image_float_editor.py -m e2e -p no:cacheprovider` → PASS. Falsify: comment out the `fig.classList.toggle("el--image--float", …)` line in the float branch → RED on the first class assertion; restore.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/editor.js courses/tests/test_image_float_js.py tests/image_float_kit.py tests/test_e2e_image_float_editor.py
git commit -m "feat(editor): live Float-right preview; Small-only checkbox state"
```

---

### Task 4: Render the class

**Files:**
- Modify: `templates/courses/elements/imageelement.html:1`
- Test: `courses/tests/test_image_float_render.py`

**Interfaces:** Consumes `el.floats`. Produces the class `el--image--float` on `figure.el--image`.

- [ ] **Step 1: Failing test**

```python
import pytest

from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _img(size, flag):
    course, _u = make_course_with_unit()
    media = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )
    return ImageElement.objects.create(media=media, size=size, float_right=flag)


@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
@pytest.mark.parametrize("flag", [True, False])
def test_class_only_when_the_image_floats(size, flag):
    html = _img(size, flag).render()
    assert ("el--image--float" in html) is (flag and size == "small")
```

Also add (the spec's render matrix — lesson top level, quiz top level, each container):

```python
CONTAINER_KINDS = ["callout", "tabs", "twocolumn", "spoiler", "beforeafter"]


def _nest(unit, kind, child):
    """Put `child` inside a fresh container of `kind` at the top of `unit`."""
    from courses.models import BeforeAfterElement
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TwoColumnElement
    from tests.factories import add_element

    if kind == "callout":
        obj, slot = CalloutElement.objects.create(kind="note"), CalloutElement.SLOT_ID
    elif kind == "spoiler":
        obj, slot = SpoilerElement.objects.create(label="s"), SpoilerElement.SLOT_ID
    elif kind == "beforeafter":
        obj, slot = BeforeAfterElement.objects.create(), BeforeAfterElement.BEFORE_SLOT_ID
    elif kind == "tabs":
        obj = TabsElement.objects.create(data=TabsElement.default_data())
        slot = obj.data["tabs"][0]["id"]  # read off the SAVED instance
    else:
        obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
        slot = obj.data["columns"][0]["id"]
    join = add_element(unit, obj)
    Element.objects.create(unit=unit, content_object=child, parent=join, tab_id=slot)


@pytest.mark.parametrize("unit_type", ["lesson", "quiz"])
@pytest.mark.parametrize("where", ["top"] + CONTAINER_KINDS)
def test_class_reaches_the_page_in_every_context(client, unit_type, where):
    from django.contrib.auth import get_user_model

    from tests.factories import add_element

    course, unit = make_course_with_unit()
    unit.unit_type = unit_type
    unit.save()
    media = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )
    flagged = ImageElement.objects.create(media=media, size="small", float_right=True)
    if where == "top":
        add_element(unit, flagged)
    else:
        _nest(unit, where, flagged)
    staff = get_user_model().objects.create_user("staff-fl", password="x", is_staff=True)  # noqa: S106
    client.force_login(staff)  # READ access keys on is_staff (course-access memory)
    path = f"/courses/{course.slug}/u/{unit.pk}/" + ("quiz/" if unit_type == "quiz" else "")
    html = client.get(path).content.decode()
    assert html.count("el--image--float") == 1, where
```

- [ ] **Step 2: Run** `uv run pytest courses/tests/test_image_float_render.py -p no:cacheprovider` → FAIL.
- [ ] **Step 3: Implement** — line 1 becomes:

```django
<figure class="el el--image el--image--{{ el.size }}{% if el.floats %} el--image--float{% endif %}" data-preview-el="{{ el.pk }}">
```

- [ ] **Step 4: Run** it plus `courses/tests/test_image_size_render.py` → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(image): emit el--image--float when the image floats"` (add both files).

---

### Task 5: Transfer (export/import, version 17)

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_image`), `courses/transfer/payloads.py` (`_val_image`), `courses/transfer/importer.py` (`_build_image`), `courses/transfer/schema.py:14`
- Modify: every test pinning 16 — derive NOW: `grep -rln "== 16\|format_version.*16\|_16\b" tests courses/tests` (expect `tests/test_link_transfer.py`, `tests/test_table_transfer.py`, `tests/test_tabs_transfer.py`, `tests/test_transfer_export.py`, `tests/test_transfer_schema.py`, `courses/tests/test_beforeafter_transfer.py`, `courses/tests/test_callout_transfer.py`, `courses/tests/test_caption_transfer.py`, `courses/tests/test_image_size_transfer.py` — trust the grep, not this list; read each hit, bump only FORMAT_VERSION pins, rename a `_16` test name to `_17`)
- Test: `courses/tests/test_image_float_transfer.py`

- [ ] **Step 1: Failing tests**

```python
import pytest

from courses.builder import duplicate_element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import FORMAT_VERSION
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db
MEDIA_KINDS = {"m1": "image"}


class _Ids:
    def register(self, *a, **k):
        return "m1"


def _media(course):
    return MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )


def _data(**over):
    d = {"media": "m1", "alt": "a", "figcaption": "", "size": "small"}
    d.update(over)
    return d


def test_version_is_17():
    assert FORMAT_VERSION == 17


def test_round_trip_keeps_the_flag():
    course, _u = make_course_with_unit()
    media = _media(course)
    el = ImageElement.objects.create(media=media, size="small", float_right=True)
    _model, ser = SERIALIZERS["image"]  # (model, fn) tuple, export.py
    data = ser(el, _Ids())
    assert data["float_right"] is True
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)
    built, _ = BUILDERS["image"](data, {"m1": media})
    assert built.float_right is True


def test_missing_key_imports_as_false():
    data = _data()
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)
    assert data["float_right"] is False


@pytest.mark.parametrize("junk", ["yes", 1, None, []])
def test_non_bool_is_coerced_to_false_not_rejected(junk):
    data = _data(float_right=junk)
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)  # must not raise
    assert data["float_right"] is False


def test_duplicate_keeps_the_flag():
    course, unit = make_course_with_unit()
    el = ImageElement.objects.create(media=_media(course), size="small", float_right=True)
    join = add_element(unit, el)
    _unit, new_join = duplicate_element(course, join.pk, unit.updated.isoformat())
    assert new_join.content_object.float_right is True
```

(`duplicate_element(course, element_pk, unit_token)` returns `(unit, new_join)`; the token is `unit.updated.isoformat()`, as in `courses/tests/test_beforeafter_transfer.py`.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**

`export.py` `_ser_image`: add `"float_right": el.float_right,`.

`payloads.py` `_val_image`, before `_exact_keys`:

```python
    # `float_right` is optional (added in FORMAT_VERSION 17). Same policy as `size`:
    # a cosmetic field with a lossless default must never fail an import, so a
    # non-bool is COERCED to False (today's rendering), not rejected.
    data.setdefault("float_right", False)
    if not isinstance(data["float_right"], bool):
        data["float_right"] = False
    _exact_keys(data, ["media", "alt", "figcaption", "size", "float_right"], _("image data"))
```

`importer.py` `_build_image`: add `float_right=data["float_right"],`.

`schema.py`: `FORMAT_VERSION = 17`. Bump every grep hit from Step "Files".

- [ ] **Step 4: Run** `uv run pytest courses/tests/test_image_float_transfer.py $(grep -rln "FORMAT_VERSION\|format_version" tests courses/tests | grep -v e2e) -n 4 -p no:cacheprovider` → all PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transfer): carry image float_right; FORMAT_VERSION 17"`.

---

### Task 6: Core CSS — float, clearing, slide/preview containment (lesson, quiz, preview)

**Files:**
- Modify: `courses/static/courses/css/courses.css` — new section placed directly AFTER the image `@media print { … }` block that follows the presets (~:159-173). Grep first — each MUST print nothing: `grep -rnE "\.slide[^-_a-zA-Z]*::after|\.prev-inner[^-_a-zA-Z]*::after" core courses notes --include=*.css` and `grep -rnE "(slide|prev-inner)[^\"']*scroll-y" courses/static core/static --include=*.js --include=*.html templates`. If either prints a hit, STOP and report.
- Test: `tests/test_e2e_image_float_layout.py`

**Interfaces:** Consumes `el--image--float` (Task 4). Produces the floated-wrapper selector list (named W below) that Tasks 7–8 extend.

- [ ] **Step 1: Write the failing e2e** (`tests/test_e2e_image_float_layout.py`):

```python
import pytest

from tests.factories import add_element
from tests.image_float_kit import *

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]
EPS = 1.5


def _seed(slug, *els, unit_type="lesson"):
    owner = make_pa_user(f"pa-{slug}")
    course, unit = seed_unit(owner, slug, unit_type)
    built = [e(course) if callable(e) else e for e in els]
    for el in built:
        add_element(unit, el)
    return owner, unit, built


@pytest.mark.parametrize("vp", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_small_floats_right_and_text_wraps(page, live_server, vp):
    owner, unit, _ = _seed("fl-basic", lambda c: image(c), text(), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), vp)
    # Reference: a TEXT block's body (full column width), never the float's own body.
    col = rect(page, ".lesson-block:not(:has(.el--image--float)) .lesson-block__body")
    img = rect(page, ".el--image--float img")
    line = first_line(page, ".el--text p")
    assert abs(img["right"] - col["right"]) < EPS, (img, col)
    assert line["right"] <= img["left"] + EPS, (line, img)  # wraps beside, not under
    assert abs(img["top"] - line["top"]) < 2 + EPS, (img, line)  # top-aligned
    second = first_line(page, '.lesson-block:nth-of-type(3) .el--text p')
    assert second["top"] >= line["top"]  # 2nd text element also present (Task 2 shape)


def test_two_text_elements_both_wrap_in_a_quiz(page, live_server):
    owner, unit, _ = _seed(
        "fl-quiz", lambda c: image(c, px=(300, 600)), text(), text(), unit_type="quiz"
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    img = rect(page, ".el--image--float img")
    lines = page.evaluate(
        """() => [...document.querySelectorAll('.quiz .el--text p')].map(p => {
             const r = document.createRange(); r.selectNodeContents(p);
             return r.getClientRects()[0].toJSON(); })"""
    )
    assert all(
        ln["right"] <= img["left"] + EPS for ln in lines if ln["top"] < img["bottom"]
    )
    assert lines[1]["top"] < img["bottom"], "2nd paragraph should start beside the image"


def test_non_text_after_float_starts_below(page, live_server):
    from courses.models import SpoilerElement
    from courses.models import TextElement

    owner, unit, _ = _seed(
        "fl-clear",
        lambda c: image(c, px=(300, 600)),
        text("Krótko."),
        SpoilerElement.objects.create(label="rozwiązanie"),
        TextElement.objects.create(body="<p>akapit</p><h3>Nagłówek</h3>"),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    img = rect(page, ".el--image--float img")
    assert rect(page, ".spoiler")["top"] >= img["bottom"] - EPS


def test_mid_body_heading_drops_but_its_paragraph_wraps(page, live_server):
    from courses.models import TextElement

    owner, unit, _ = _seed(
        "fl-h3",
        lambda c: image(c, px=(300, 600)),
        TextElement.objects.create(body=f"<p>{PARA}</p><h3>Nagłówek</h3>"),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    img = rect(page, ".el--image--float img")
    assert first_line(page, ".el--text p")["right"] <= img["left"] + EPS
    assert rect(page, ".el--text h3")["top"] >= img["bottom"] - EPS


def test_two_floats_stack(page, live_server):
    owner, unit, _ = _seed("fl-two", lambda c: image(c), lambda c: image(c), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    a, b = page.locator(".el--image--float img").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())"
    )
    assert b["top"] >= a["bottom"] - EPS


def test_float_as_first_element(page, live_server):
    owner, unit, _ = _seed("fl-first", lambda c: image(c), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), PHONE)
    img = rect(page, ".el--image--float img")
    assert first_line(page, ".el--text p")["right"] <= img["left"] + EPS


def test_float_ending_a_slide_stays_in_it_without_js(browser, live_server):
    # .unit-shell__main is a flex column, so article.lesson (a flex item) already
    # contains floats before .unit-foot -- a footer test cannot fail. What the
    # .slide::after guards is a float ending slide 1 when slides STACK: no JS.
    from courses.models import SlideBreakElement

    owner, unit, _ = _seed(
        "fl-slides",
        text("Krótko."),
        lambda c: image(c, px=(300, 900)),
        SlideBreakElement.objects.create(),
        text("Druga strona."),
    )
    ctx = browser.new_context(java_script_enabled=False)
    try:
        page = ctx.new_page()
        login(page, live_server, owner.username)
        open_page(page, unit_url(live_server, unit), DESKTOP)
        img = rect(page, ".el--image--float img")
        nxt = rect(page, ".slide:nth-of-type(2) .el--text p")
        assert nxt["top"] >= img["bottom"] - EPS, (nxt, img)
    finally:
        ctx.close()


def test_float_ending_a_deck_slide_stays_in_it_in_print(page, live_server):
    # Print makes deck slides position:static; overflow:visible -- no longer BFCs.
    from courses.models import SlideBreakElement

    owner, unit, _ = _seed(
        "fl-deck-print",
        text("Krótko."),
        lambda c: image(c, px=(300, 900)),
        SlideBreakElement.objects.create(),
        text("Druga strona."),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.wait_for_selector(".slideshow-deck")
    page.emulate_media(media="print")
    img = rect(page, ".el--image--float img")
    nxt = rect(page, ".slide:nth-of-type(2) .el--text p")
    assert nxt["top"] >= img["bottom"] - EPS, (nxt, img)


def test_preview_contains_a_float_and_a_slide_break_clears_it(page, live_server):
    from courses.models import SlideBreakElement

    owner, unit, _ = _seed(
        "fl-prev",
        lambda c: image(c, px=(300, 900)),
        SlideBreakElement.objects.create(),
        text("Po przerwie."),
        text("Krótko."),
        lambda c: image(c, px=(300, 900)),  # LAST preview element
    )
    login(page, live_server, owner.username)
    page.set_viewport_size(DESKTOP)
    page.goto(editor_url(live_server, unit))
    page.wait_for_selector(".prev-inner .el--image--float img")
    assert page.evaluate(WAIT_IMAGES)
    imgs = page.locator(".prev-inner .el--image--float img").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())"
    )
    brk = rect(page, ".prev-inner section.prev-el:nth-of-type(2)")
    assert brk["top"] >= imgs[0]["bottom"] - EPS, (brk, imgs[0])
    inner = rect(page, ".prev-inner")
    assert inner["bottom"] >= imgs[-1]["bottom"] - EPS, (inner, imgs[-1])


def test_maths_beside_float_does_not_scroll_the_page(page, live_server):
    from courses.models import MathElement

    owner, unit, _ = _seed(
        "fl-math", lambda c: image(c, px=(300, 600)), MathElement.objects.create(latex="x^2+y^2=r^2")
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), PHONE)
    page.wait_for_selector(".el--math .katex")
    img = rect(page, ".el--image--float img")
    assert rect(page, ".el--math .katex-html")["right"] <= img["left"] + EPS
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_float_before_reveal_gate(page, live_server):
    from courses.models import RevealGateElement

    owner, unit, _ = _seed(
        "fl-gate", lambda c: image(c, px=(300, 600)), text("Krótko."),
        RevealGateElement.objects.create(), text(),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.locator("[data-reveal-gate]").wait_for(state="visible")  # reveal.js un-hides it
    img = rect(page, ".el--image--float img")
    gate = rect(page, "[data-reveal-gate]")
    assert gate["width"] > 0 and gate["height"] > 0, "gate never rendered; vacuous"
    assert gate["top"] >= img["bottom"] - EPS or gate["right"] <= img["left"] + EPS


@pytest.mark.parametrize("vp", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_clicking_the_floated_image_opens_zoom(page, live_server, vp):
    owner, unit, _ = _seed("fl-zoom", lambda c: image(c), text(), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), vp)
    page.locator(".el--image--float img").click()
    page.wait_for_selector("dialog.imgzoom[open]", timeout=3000)


def test_narrow_and_captioned_images_hug_the_right_edge(page, live_server):
    owner, unit, _ = _seed(
        "fl-narrow",
        lambda c: image(c, px=(90, 90)),  # >= 80px: the in-flow notes handle is ~25-50px
        text(),
        lambda c: image(c, px=(90, 90), caption="Bardzo długi podpis pod małym obrazkiem"),
        text(),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    col = rect(page, ".lesson-block:not(:has(.el--image--float)) .lesson-block__body")
    for img in page.locator(".el--image--float img").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())"
    ):
        assert abs(img["right"] - col["right"]) < EPS, (img, col)


def test_height_capped_portrait_leaves_no_gap(page, live_server):
    owner, unit, _ = _seed("fl-tall", lambda c: image(c, px=(400, 800)), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), {"width": 1300, "height": 700})
    im = page.locator(".el--image--float img")
    h, cap = im.evaluate("e => [e.getBoundingClientRect().height, parseFloat(getComputedStyle(e).maxHeight)]")
    assert abs(h - cap) < EPS, "fixture must be height-capped or the test is vacuous"
    img = rect(page, ".el--image--float img")
    line = first_line(page, ".el--text p")
    assert img["left"] - line["right"] <= 16 + EPS  # <= --space-4
```

(Before running, confirm class names exist: `RevealGateElement`, `MathElement` in `courses/models.py`; `RevealGateElement` may need extra fields — read its model and pass required ones.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_e2e_image_float_layout.py -m e2e -n 2 -p no:cacheprovider`
Expected: geometry assertions FAIL (image is centred on its own line).

- [ ] **Step 3: Implement the CSS block** — insert after the image print block. The four branches are written out EXACTLY as below. Duplication across branches is deliberate: every float declaration on wrapper, figure and img must sit under ONE condition per branch (spec "Every float-specific declaration…"); there is no preprocessor.

```css
/* === Image "Float right" (Small only) ===========================================
   Spec: docs/superpowers/specs/2026-10-07-image-float-right-design.md (D1-D10).
   The image's WRAPPER floats, never the figure alone: at the top level the wrapper
   also carries the notes handle, which a figure-only float left on top of the image.
   Floated wrapper per context:
     lesson top level   .lesson-block:has(> .lesson-block__body > .el--image--float)
     quiz top level     .quiz .slide > section[data-element-id]:has(...)  -- SCOPED:
                        lesson and preview blocks are section[data-element-id] too
     builder preview    section.prev-el:has(...)  -- `section` REQUIRED: container
                        children in preview carry .prev-el as well
     containers         .callout__child / .tabs__child / .twocolumn__child /
                        .spoiler__child / .ba__child
   No container queries here, ever (spec D5, withdrawn): container-type's containment
   makes a stacking context that traps every notes pop under .unit-foot.
   The float is OFF -- the image renders as an unflagged Small -- while a floated
   block's own notes are in flow and open, and in print when it has printable notes. */
/* Rail active: the pop is absolutely positioned, so an open panel never un-floats. */
@media screen and (min-width: 1200px) {
  html.notes-js .lesson-block:has(> .lesson-block__body > .el--image--float),
  html.notes-js .quiz .slide > section[data-element-id]:has(> .el--image--float),
  html.notes-js section.prev-el:has(> .el--image--float),
  html.notes-js :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float) {
    float: right; max-width: 25%; margin: 0 0 var(--space-3) var(--space-4);
  }
  /* notes.css makes every .lesson-block position:relative here; the LATER paragraph
     block would paint and hit-test above the float (zoom dead -- verified on the
     mockup). Task 8 raises this to 50 while the block's own panel is open. */
  html.notes-js .lesson-block:has(> .lesson-block__body > .el--image--float) { z-index: 1; }
  html.notes-js .lesson-block:has(> .lesson-block__body > .el--image--float) .el--image--float,
  html.notes-js .quiz .slide > section[data-element-id]:has(> .el--image--float) .el--image--float,
  html.notes-js section.prev-el:has(> .el--image--float) .el--image--float,
  html.notes-js :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float) .el--image--float {
    max-width: 100%; margin: 0 0 1rem;
  }
  html.notes-js .lesson-block:has(> .lesson-block__body > .el--image--float) .el--image--float img,
  html.notes-js .quiz .slide > section[data-element-id]:has(> .el--image--float) .el--image--float img,
  html.notes-js section.prev-el:has(> .el--image--float) .el--image--float img,
  html.notes-js :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float) .el--image--float img {
    margin-inline: auto 0;
  }
}
/* Pop in flow: un-float while this block's own panel is open. */
@media screen and (max-width: 1199.98px) {
  .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__panel[open])),
  .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__panel[open])),
  section.prev-el:has(> .el--image--float):not(:has(.block-notes__panel[open])),
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) {
    float: right; max-width: 25%; margin: 0 0 var(--space-3) var(--space-4);
  }
  .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float,
  .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float,
  section.prev-el:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float,
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float {
    max-width: 100%; margin: 0 0 1rem;
  }
  .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img,
  .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img,
  section.prev-el:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img,
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img {
    margin-inline: auto 0;
  }
}
/* No notes.js: the pop is in flow at every width. */
@media screen {
  html:not(.notes-js) .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__panel[open])),
  html:not(.notes-js) .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__panel[open])),
  html:not(.notes-js) section.prev-el:has(> .el--image--float):not(:has(.block-notes__panel[open])),
  html:not(.notes-js) :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) {
    float: right; max-width: 25%; margin: 0 0 var(--space-3) var(--space-4);
  }
  html:not(.notes-js) .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float,
  html:not(.notes-js) .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float,
  html:not(.notes-js) section.prev-el:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float,
  html:not(.notes-js) :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float {
    max-width: 100%; margin: 0 0 1rem;
  }
  html:not(.notes-js) .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img,
  html:not(.notes-js) .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img,
  html:not(.notes-js) section.prev-el:has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img,
  html:not(.notes-js) :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) .el--image--float img {
    margin-inline: auto 0;
  }
}
/* Print keeps the float (D9) unless the block prints notes. Descendant alternatives,
   NOT notes.css's `.block-notes__pop:not(:has(...))`: nested :has() is invalid and
   the browser would drop this whole rule silently. Class list pinned by
   test_image_float_css.py against notes.css's print rule. */
@media print {
  .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)),
  .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)),
  section.prev-el:has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)),
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) {
    float: right; max-width: 25%; margin: 0 0 var(--space-3) var(--space-4);
  }
  .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float,
  .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float,
  section.prev-el:has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float,
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float {
    max-width: 100%; margin: 0 0 1rem;
  }
  .lesson-block:has(> .lesson-block__body > .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float img,
  .quiz .slide > section[data-element-id]:has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float img,
  section.prev-el:has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float img,
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) .el--image--float img {
    margin-inline: auto 0;
  }
}
```

Finally the unscoped clearing rules and the slide/preview containment (outside any media query), then CLOSE the section with the end marker `/* === end Image "Float right" === */` — Tasks 7 and 8 insert their rules ABOVE it, and Task 9's source tests slice between the two markers:

```css
/* D3. Unscoped on purpose (D10 exemptions): `clear` is a no-op when no float precedes,
   and the project CSS declares no other float. */
.lesson-block:not(:has(> .lesson-block__body > :is(.el--text, .el--math))),
.quiz .slide > section[data-element-id]:not(:has(> :is(.el--text, .el--math))),
section.prev-el:not(:has(> :is(.el--text, .el--math))),
:is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):not(:has(> :is(.el--text, .el--math))) { clear: right; }
.el--text :is(h2, h3, h4), .el--text pre { clear: right; }   /* heading list = sanitize.ALLOWED_TAGS */

/* Contain a float inside its slide (deck slides included: print makes them static)
   and the builder preview. .slide is display:contents outside a slideshow; its
   ::after still generates and lands in the article. These boxes must never carry
   .scroll-y, whose ::after is an absolutely positioned shadow. */
:is(.slide, .prev-inner):has(.el--image--float)::after { content: ""; display: block; clear: both; }

/* === end Image "Float right" === */
```

- [ ] **Step 4: Run** the layout e2e → PASS. Then run `uv run pytest $(ls tests/test_*css*.py courses/tests/test_*css*.py) -n 4 -p no:cacheprovider` → PASS (marker tests partition on text).
- [ ] **Step 5: Falsify** (by hand, one at a time, restore after each): (a) delete `float: right;` from the max-width:1199.98px branch → phone `test_small_floats_right_and_text_wraps` RED; (b) remove the sibling `clear: right` rule → `test_non_text_after_float_starts_below` RED; (c) remove `.el--text :is(h2…)` → `test_mid_body_heading…` RED; (d) remove `.slide` from the `::after` rule → `test_float_ending_a_slide_stays_in_it_without_js` AND `…deck_slide…in_print` RED; remove `.prev-inner` → `test_preview_contains…` RED; (f) remove the rail `z-index: 1` → `test_clicking_the_floated_image_opens_zoom[desktop]` RED; (e) change the quiz selector to an unscoped `section[data-element-id]` → `test_small_floats_right_and_text_wraps` RED (lesson text cleared). Read `git diff` after each restore — it must show only the intended block.
- [ ] **Step 6: Commit** `git commit -m "feat(css): float Small images right; clear non-text; contain per slide"`.

---

### Task 7: Containers — per-list containment and margins

**Files:**
- Modify: `courses/static/courses/css/courses.css` (same section, ABOVE the `=== end Image "Float right" ===` marker)
- Test: `tests/test_e2e_image_float_containers.py`

- [ ] **Step 1: Grep** `grep -n "::after" courses/static/courses/css/courses.css core/static/core/css/app.css | grep -E "callout__children|tabs__panel|twocolumn__column|spoiler__children|ba__panel"` → must be empty; otherwise STOP.
- [ ] **Step 2: Failing e2e** — seed one container of each kind holding `[image(px=(300,600)), text("Krótko.")]` (copy the nesting idiom from `tests/test_e2e_image_size.py` rows 322-370: `Element.objects.create(unit=…, content_object=…, parent=<join>, tab_id=<slot>)`; tabs/two-column ids from `default_data()` read off the SAVED instance; before/after slots `BeforeAfterElement.BEFORE_SLOT_ID`/`AFTER_SLOT_ID`), then a top-level `text()` after each container.

```python
CONTAINERS = ["callout", "tabs", "carousel", "twocolumn", "spoiler", "beforeafter"]  # carousel = tabs, display="carousel"

@pytest.mark.parametrize("kind", CONTAINERS)
def test_float_is_contained_by_its_container(page, live_server, kind):
    owner, unit, container_sel = seed_container(kind, "fl-c-" + kind)  # helper in this file
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    if kind == "spoiler":
        page.locator(".spoiler__toggle").click()
    img = rect(page, f"{container_sel} .el--image--float img")
    assert rect(page, container_sel)["bottom"] >= img["bottom"] - 1.5
    nxt = rect(page, f'[data-element-id] + [data-element-id] .el--text p')
    assert nxt["top"] >= img["bottom"] - 1.5


# .ba--dead shares html:not(.ba-js)'s declarations by grouped selector
# (beforeafter.js), so the no-JS case covers it. "carousel" = tabs with
# data display="carousel" (idiom: tests/test_e2e_tabs.py's tabs fixture).
@pytest.mark.parametrize("state", ["nojs", "print"])
@pytest.mark.parametrize("kind", ["tabs", "carousel", "beforeafter"])
def test_float_at_end_of_a_non_last_list_stays_in_it(browser, live_server, kind, state):
    # Tabs without JS and in print stack every section; before/after shows both sides.
    owner, unit, sel = seed_stacked(kind, f"fl-s-{kind}-{state}")  # image is LAST child of list 1
    ctx = browser.new_context(java_script_enabled=(state != "nojs"))
    try:
        page = ctx.new_page()
        login(page, live_server, owner.username)
        open_page(page, unit_url(live_server, unit), DESKTOP)
        if state == "print":
            page.emulate_media(media="print")
        _assert_next_list_below(page, kind, sel)
    finally:
        ctx.close()


def _assert_next_list_below(page, kind, sel):
    img = rect(page, f"{sel} .el--image--float img")
    second_list = ".tabs__section:nth-child(2)" if kind in ("tabs", "carousel") else '.ba__panel[data-ba-side="after"]'
    assert rect(page, second_list)["top"] >= img["bottom"] - 1.5
    first_child = f"{second_list} :is(.tabs__child, .ba__child)"
    assert rect(page, first_child)["top"] >= img["bottom"] - 1.5


@pytest.mark.parametrize(
    "vp,medium", [(PHONE, "screen"), (DESKTOP, "screen"), (DESKTOP, "print")]
)
def test_top_alignment_and_no_trailing_space_in_a_callout(page, live_server, vp, medium):
    from courses.models import CalloutElement
    from courses.models import Element

    owner = make_pa_user("pa-fl-callout")
    course, unit = seed_unit(owner, "fl-callout")

    def callout(children):
        join = add_element(unit, CalloutElement.objects.create(kind="note"))
        for c in children:
            Element.objects.create(
                unit=unit, content_object=c, parent=join, tab_id=CalloutElement.SLOT_ID
            )
        return join

    a = callout([image(course, px=(300, 200)), text()])  # image first: top alignment
    b = callout([text("Krótko."), image(course, px=(300, 200))])  # float is LAST child
    c = callout([text("Krótko."), image(course, px=(300, 200), float_right=False)])  # twin
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), vp)
    if medium == "print":
        page.emulate_media(media="print")

    img_a = rect(page, f'[data-element-id="{a.pk}"] .el--image img')
    line_a = first_line(page, f'[data-element-id="{a.pk}"] .callout__child .el--text p')
    assert abs(img_a["top"] - line_a["top"]) <= 2 + 1.5, (img_a, line_a)

    def trailing(join):
        box = rect(page, f'[data-element-id="{join.pk}"] .callout')
        img = rect(page, f'[data-element-id="{join.pk}"] .el--image img')
        return box["bottom"] - img["bottom"]

    assert trailing(b) <= trailing(c) + 1.5, (trailing(b), trailing(c))
```

Write `seed_container` / `seed_stacked` in the test file following the nesting idiom above (seed_container(kind, slug) -> (owner, unit, '[data-element-id="<join pk>"]'); seed_stacked puts the floated image as the LAST child of the FIRST list and one text child in the second list).

- [ ] **Step 3: Run** → the stacked/no-JS and print cases FAIL (float leaks), margins case FAILS.
- [ ] **Step 4: Implement**

```css
/* D4: contain a float in EVERY list, not once per container -- tabs (no JS / print)
   and before/after (no JS / dead / print) stack their lists, and a float at the end of
   list 1 would spill into list 2 (whose label is outside any .el--text). Two-column and
   carousel sections already contain floats on screen, but print makes the carousel
   static, so they get it too. */
:is(.callout__children, .tabs__panel, .twocolumn__column, .spoiler__children, .ba__panel):has(.el--image--float)::after {
  content: ""; display: block; clear: both;
}
/* In a container the figure needs no notes-handle clearance (notes attach to top-level
   blocks only); a floated LAST child adds no trailing space. Specificity of the W
   selectors ((0,3,1)+ via :is) already beats the container child-spacing rules
   ((0,4,0) two-column `+`, (0,3,0) tabs/callout); verify with the e2e, not by eye. */
```

and the container margin rules, one per Task 6 media branch, each carrying THAT branch's
prefix AND `:not(...)` suffix — without the suffix they are less specific than Task 6's
figure rule ((0,3,0) vs (0,5,0)) and lose; with it they tie and win on source order, so
they MUST sit after the Task 6 branches:

```css
@media screen and (min-width: 1200px) {
  html.notes-js :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float) > .el--image--float { margin-bottom: 0; }
  html.notes-js :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):last-child { margin-bottom: 0; }
}
@media screen and (max-width: 1199.98px) {
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) > .el--image--float { margin-bottom: 0; }
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])):last-child { margin-bottom: 0; }
}
@media screen {
  html:not(.notes-js) :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])) > .el--image--float { margin-bottom: 0; }
  html:not(.notes-js) :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__panel[open])):last-child { margin-bottom: 0; }
}
@media print {
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)) > .el--image--float { margin-bottom: 0; }
  :is(.callout__child, .tabs__child, .twocolumn__child, .spoiler__child, .ba__child):has(> .el--image--float):not(:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, .block-notes__pop .note-composer--has-draft, .block-notes__pop .note-composer__error)):last-child { margin-bottom: 0; }
}
```

If the e2e shows a container rule still winning (e.g. `.el--twocolumn > .twocolumn__column > .twocolumn__child + .twocolumn__child { margin-top }` at (0,4,0)), add `margin-top: 0` for the floated child inside the same four blocks and re-run.

- [ ] **Step 5: Run** containers e2e + all CSS source tests → PASS. Falsify: drop `.tabs__panel` from the `::after` list → tabs `nojs` RED; restore.
- [ ] **Step 6: Commit** `git commit -m "feat(css): contain floated images in every container list"`.

---

### Task 8: Notes interactions — stacking, rail handle, in-flow pops, print

**Files:**
- Modify: `courses/static/courses/css/courses.css` (same section, ABOVE the `=== end Image "Float right" ===` marker)
- Test: `tests/test_e2e_image_float_notes.py`

First: `grep -n "z-index" courses/static/courses/css/courses.css core/static/core/css/app.css notes/static/notes/css/notes.css` and list every positive z-index in the PR description (spec: re-grep at plan time; known: `.unit-foot` 20, `.unit-toc-pin` 21, `.dragimage__target`/`__badge` 3/4, pop 50).

- [ ] **Step 1: Failing e2e** — notes need a published lesson and an enrolled STUDENT (idiom from `tests/test_e2e_notes_rail.py::_build_lesson`).

Add to `tests/image_float_kit.py`, ABOVE the final `__all__` line:

```python
def seed_student_lesson(slug, username, builders):
    """Published lesson + enrolled STUDENT (notes need a student; PA users suffice for
    layout only). `builders` are callables taking the course and returning a saved
    concrete element, added top-level in order. Returns (course, unit, joins, student)."""
    from django.contrib.auth.models import Group

    from courses.models import ContentNode
    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON, title="F", published=True,
    )
    joins = [add_element(unit, b(course)) for b in builders]
    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    student.groups.add(Group.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    return course, unit, joins, student


def note(student, unit, join, body="notatka"):
    from notes.models import Note

    return Note.objects.create(author=student, unit=unit, element=join, body=body)


def boxes_intersect(a, b):
    return not (
        a["right"] <= b["left"] or b["right"] <= a["left"]
        or a["bottom"] <= b["top"] or b["bottom"] <= a["top"]
    )
```

Then `tests/test_e2e_image_float_notes.py`:

```python
import pytest

from tests.image_float_kit import *

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]
SHAPE = [lambda c: image(c, px=(300, 220)), lambda c: text(), lambda c: text()]


def _block(join):
    return f'.lesson-block[data-element-id="{join.pk}"]'


def _float(page, join):
    return page.locator(_block(join)).evaluate("e => getComputedStyle(e).float")


def test_rail_handles_do_not_intersect_and_pop_opens_at_handle(page, live_server):
    course, unit, joins, st = seed_student_lesson("fn-rail", "fn_rail", SHAPE)
    for j in joins:
        note(st, unit, j)
    login(page, live_server, "fn_rail")
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.wait_for_selector("html.notes-js")
    img_h = rect(page, f"{_block(joins[0])} .block-notes__handle")
    for j in joins[1:]:
        assert not boxes_intersect(img_h, rect(page, f"{_block(j)} .block-notes__handle"))
    page.locator(f"{_block(joins[0])} .block-notes__handle").click()
    pop = rect(page, f"{_block(joins[0])} .block-notes__pop")
    handle = rect(page, f"{_block(joins[0])} .block-notes__handle")
    assert abs(pop["top"] - handle["top"]) < 2, (pop, handle)
    assert _float(page, joins[0]) == "right"  # rail: open notes never un-float


def test_open_pop_beats_the_sticky_footer(page, live_server):
    lead = [lambda c: text() for _ in range(25)]  # page must scroll
    course, unit, joins, st = seed_student_lesson(
        "fn-foot", "fn_foot", lead + SHAPE + [lambda c: text("Ostatni.")]
    )
    img_join, plain_join = joins[25], joins[12]
    note(st, unit, img_join)
    note(st, unit, plain_join)
    login(page, live_server, "fn_foot")
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.wait_for_selector("html.notes-js")
    for j in (img_join, plain_join):
        handle = f"{_block(j)} .block-notes__handle"
        # Put the handle near the viewport bottom so the opened pop meets .unit-foot.
        page.evaluate(
            """(sel) => { const h = document.querySelector(sel);
                 window.scrollBy(0, h.getBoundingClientRect().top - innerHeight + 140); }""",
            handle,
        )
        page.locator(handle).click()
        pop_r = rect(page, f"{_block(j)} .block-notes__pop")
        assert boxes_intersect(pop_r, rect(page, ".unit-foot")), (
            "fixture: the open pop must overlap .unit-foot, or this proves nothing")
        hit = page.evaluate(
            """(sel) => { const p = document.querySelector(sel).getBoundingClientRect();
                 const y = Math.min(p.bottom - 4, innerHeight - 4);
                 const e = document.elementFromPoint(p.left + p.width / 2, y);
                 return !!(e && e.closest(sel)); }""",
            f"{_block(j)} .block-notes__pop",
        )
        assert hit, f"block {j.pk}: its pop is painted under something (.unit-foot?)"
        page.locator(handle).click()  # close before the next block


def test_below_rail_open_notes_unfloat_to_an_unflagged_small(page, live_server):
    course, unit, joins, st = seed_student_lesson("fn-phone", "fn_phone", SHAPE)
    note(st, unit, joins[0])
    _c2, twin, _j2, _s2 = seed_student_lesson(
        "fn-phone-twin", "fn_phone_twin",
        [lambda c: image(c, px=(300, 220), float_right=False), lambda c: text()],
    )
    login(page, live_server, "fn_phone")
    open_page(page, unit_url(live_server, unit), PHONE)
    page.locator(f"{_block(joins[0])} .block-notes__handle").click()
    assert _float(page, joins[0]) == "none"
    pop = rect(page, f"{_block(joins[0])} .block-notes__pop")
    col = rect(page, f"{_block(joins[1])} .lesson-block__body")
    assert abs(pop["width"] - col["width"]) < 2, (pop, col)
    a = rect(page, f"{_block(joins[0])} img")
    page.context.clear_cookies()
    login(page, live_server, "fn_phone_twin")
    open_page(page, unit_url(live_server, twin), PHONE)
    b = rect(page, ".el--image img")
    assert all(abs(a[k] - b[k]) < 1 for k in ("left", "width")), (a, b)


@pytest.mark.parametrize("medium", ["screen", "print"])
def test_neighbour_note_card_never_runs_under_the_image(page, live_server, medium):
    course, unit, joins, st = seed_student_lesson(
        f"fn-nb-{medium}", f"fn_nb_{medium}",
        [lambda c: image(c, px=(300, 600)), lambda c: text("Krótko.")],
    )
    note(st, unit, joins[1], body="notatka obok obrazka " * 5)
    login(page, live_server, f"fn_nb_{medium}")
    open_page(page, unit_url(live_server, unit), PHONE)
    if medium == "print":
        page.emulate_media(media="print")  # notes.css prints pops that have cards
    else:
        page.locator(f"{_block(joins[1])} .block-notes__handle").click()
    card = rect(page, f"{_block(joins[1])} .note-card")
    img = rect(page, f"{_block(joins[0])} img")
    assert not boxes_intersect(card, img), (card, img)


def test_spacing_unchanged_for_a_block_far_from_the_float(page, live_server):
    far = [lambda c: text() for _ in range(5)]
    course, unit, joins, st = seed_student_lesson("fn-sp", "fn_sp", SHAPE + far)
    note(st, unit, joins[-1])
    _c2, twin, tj, ts = seed_student_lesson(
        "fn-sp-twin", "fn_sp_twin",
        [lambda c: image(c, px=(300, 220), float_right=False)] + SHAPE[1:] + far,
    )
    note(ts, twin, tj[-1])

    def offset(user, u, j):
        page.context.clear_cookies()
        login(page, live_server, user)
        open_page(page, unit_url(live_server, u), PHONE)
        page.locator(f"{_block(j)} .block-notes__handle").click()
        return (rect(page, f"{_block(j)} .note-card")["top"]
                - rect(page, f"{_block(j)} .block-notes__pop")["top"])

    assert abs(offset("fn_sp", unit, joins[-1]) - offset("fn_sp_twin", twin, tj[-1])) < 0.5


def test_print_keeps_the_float_unless_notes_print(page, live_server):
    course, unit, joins, st = seed_student_lesson(
        "fn-print", "fn_print",
        [lambda c: image(c, px=(300, 220)), lambda c: text(),
         lambda c: image(c, px=(300, 220)), lambda c: text()],
    )
    note(st, unit, joins[2])  # the second image prints notes -> un-floats
    login(page, live_server, "fn_print")
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.emulate_media(media="print")
    assert _float(page, joins[0]) == "right"
    cap = page.locator(f"{_block(joins[0])} img").evaluate("e => getComputedStyle(e).maxHeight")
    assert cap.endswith("px") and abs(float(cap[:-2]) - 45 * 96 / 25.4) < 1  # 45mm
    assert _float(page, joins[2]) == "none"
    assert page.locator(f"{_block(joins[1])} .block-notes__pop").evaluate(
        "e => getComputedStyle(e).display") == "none"  # an EMPTY pop stays hidden


def test_clamped_pop_beats_a_following_drag_to_image_target(page, live_server):
    # z-index 50 while open exists to beat positive-z content in the root context;
    # .dragimage__target / __badge (3/4) is one. 1400px clamps the pop over the column
    # (tests/test_e2e_notes_rail.py, "clamped").
    from tests.reveal_pr2_kit import build
    from tests.test_e2e_quiz_reveal_pr2 import _size_stages

    course, unit, joins, st = seed_student_lesson(
        "fn-drag", "fn_drag",
        [lambda c: image(c, px=(300, 220)), lambda c: text("Krótko."),
         lambda c: build("dragimage").question],
    )
    note(st, unit, joins[0], body="notatka " * 30)
    login(page, live_server, "fn_drag")
    open_page(page, unit_url(live_server, unit), {"width": 1400, "height": 950})
    _size_stages(page)  # the factory image is not served; give the stage real size
    page.wait_for_selector("html.notes-js")
    page.locator(f"{_block(joins[0])} .block-notes__handle").click()
    pop_sel = f"{_block(joins[0])} .block-notes__pop"
    page.wait_for_selector(f"{pop_sel}.block-notes__pop--clamped")
    pop = rect(page, pop_sel)
    target = rect(page, ".dragimage__target")
    assert boxes_intersect(pop, target), "fixture: the pop must overlap a target"
    x = (max(pop["left"], target["left"]) + min(pop["right"], target["right"])) / 2
    y = (max(pop["top"], target["top"]) + min(pop["bottom"], target["bottom"])) / 2
    on_top = page.evaluate(
        "([x, y, sel]) => !!document.elementFromPoint(x, y).closest(sel)", [x, y, pop_sel]
    )
    assert on_top, "the floated block's open pop is under the drag-image target"
```

- [ ] **Step 2: Run** → stacking/handle/pop/print/neighbour tests FAIL.
- [ ] **Step 3: Implement**

```css
@media screen and (min-width: 1200px) {
  /* notes.css makes every block position:relative here; a later positioned block
     (the paragraph beside the float) would paint and hit-test ABOVE the float --
     zoom dead (verified on the mockup). z-index 1 lifts the float; while its panel
     is open it rises to the pop's own 50, else the pop (trapped in this stacking
     context) would sit under .unit-foot (20) / .unit-toc-pin (21). */
  /* z-index 1 is Task 6's (rail branch). While the floated block's panel is open it
     rises to the pop's own 50, else the pop (trapped in that stacking context) would
     sit under .unit-foot (20) / .unit-toc-pin (21) / .dragimage__target (3). */
  html.notes-js .lesson-block:has(> .lesson-block__body > .el--image--float):has(.block-notes__panel[open]) { z-index: 50; }
  /* D8: anchor the floated block's rail handle to its bottom, below the top-anchored
     handle of the paragraph beside it. notes.js opens the pop at handle.offsetTop. */
  html.notes-js [data-unit-shell] .lesson-block:has(> .lesson-block__body > .el--image--float) .block-notes__handle {
    top: auto; bottom: 0;
  }
}
/* A neighbour's in-flow note card / composer becomes a BFC so it narrows beside the
   float instead of running under it. Cards and composers, NOT the pop: a BFC pop would
   stop the first card's margin collapsing and double the gap on every annotated block.
   The pop's own display is never touched, so notes.css's print hide of EMPTY pops holds. */
@media screen and (max-width: 1199.98px) {
  .slide:has(.el--image--float) :is(.note-card, .note-composer) { display: flow-root; }
}
@media screen {
  html:not(.notes-js) .slide:has(.el--image--float) :is(.note-card, .note-composer) { display: flow-root; }
}
@media print {
  .slide:has(.el--image--float) :is(.note-card, .note-composer) { display: flow-root; }
}
```

The z-index rule must only apply while the block actually floats; at ≥1200px+notes-js the float branch has no un-float condition, so the selectors above match exactly the floating case. The composer's textarea is `width: 100%` of its composer, so it narrows with the BFC composer; no extra rule.

- [ ] **Step 4: Run** notes e2e + `tests/test_e2e_notes_rail.py` + all CSS source tests → PASS.
- [ ] **Step 5: Falsify** by hand: remove the `z-index: 50` rule → footer test AND clamped drag-image test RED; delete the WHOLE D8 handle rule → handle intersection RED; remove the print `.note-card` flow-root → neighbour print RED. Restore each; read `git diff`.
- [ ] **Step 6: Commit** `git commit -m "feat(css): floated images keep notes, clicks and print working"`.

---

### Task 9: CSS source guards, legacy Medium, dark plate, branch gate

**Files:**
- Test: `courses/tests/test_image_float_css.py`; extend `tests/test_e2e_image_float_layout.py`

- [ ] **Step 1: Source tests**

```python
import re
from pathlib import Path

from courses.sanitize import ALLOWED_TAGS

REPO = Path(__file__).resolve().parents[2]
RAW = (REPO / "courses/static/courses/css/courses.css").read_text(encoding="utf-8")
NOTES = (REPO / "notes/static/notes/css/notes.css").read_text(encoding="utf-8")


def _strip(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


CSS = _strip(RAW)
# The whole feature lives between two marker comments (Task 6 Step 3); slice on the
# RAW text, where the markers still exist, then strip comments.
BLOCK = _strip(RAW[RAW.index("=== Image \"Float right\"") : RAW.index("=== end Image \"Float right\" ===")])


def _rules(css):
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def test_no_container_queries():
    assert "container-type" not in CSS and "@container" not in CSS


def test_every_rule_but_the_clears_is_keyed_on_the_float_class():
    for sel, body in _rules(BLOCK):
        if body.strip() == "clear: right;":
            continue
        assert "el--image--float" in sel, sel


def test_quiz_selectors_carry_the_quiz_scope():
    for sel, _ in _rules(CSS):
        for part in sel.split(","):
            if "section[data-element-id]" in part:
                assert ".quiz .slide > section[data-element-id]" in part, part


def test_heading_clear_lists_every_allowed_heading():
    allowed = sorted(t for t in ALLOWED_TAGS if re.fullmatch(r"h[1-6]", t))
    m = re.search(r"\.el--text :is\(([^)]*)\)", CSS)
    assert sorted(x.strip() for x in m.group(1).split(",")) == allowed


def test_print_unfloat_class_list_matches_notes_print_rule():
    notes = re.search(r"\.block-notes__pop:not\(:has\(([^)]*)\)\)", NOTES).group(1)
    want = sorted(c.strip() for c in notes.split(","))
    got = sorted(re.findall(r"\.block-notes__pop (\.[\w-]+)", CSS))
    assert sorted(set(got)) == want


def test_no_nested_has():
    for sel, _ in _rules(CSS):
        for m in re.finditer(r":has\(", sel):
            depth, i = 1, m.end()
            while depth:
                ch = sel[i]
                if sel.startswith(":has(", i):
                    raise AssertionError(f"nested :has() in {sel}")
                depth += ch == "("
                depth -= ch == ")"
                i += 1
```

Falsify `test_quiz_selectors_carry_the_quiz_scope` by temporarily writing an unscoped quiz selector → RED; restore.

- [ ] **Step 2: e2e — legacy Medium + dark plate** (append to the layout file):

```python
@pytest.mark.parametrize("vp", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_a_stored_true_on_medium_does_not_float(page, live_server, vp):
    # Both images in ONE unit: a second course would be unreadable to this PA user.
    owner, unit, _ = _seed(
        "fl-med",
        lambda c: image(c, size="medium", alt="flagged"),
        text(),
        lambda c: image(c, size="medium", float_right=False, alt="plain"),
        text(),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), vp)
    a = rect(page, 'img[alt="flagged"]')
    b = rect(page, 'img[alt="plain"]')
    assert all(abs(a[k] - b[k]) < 1 for k in ("left", "width", "height")), (a, b)


def test_dark_plate_on_a_floated_image(page, live_server):
    owner, unit, _ = _seed("fl-dark", lambda c: image(c), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    bg = page.locator(".el--image--float img").evaluate("e => getComputedStyle(e).backgroundColor")
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent")
```

(The dark e2e may need `user.theme`, not the attribute — see memory "dialog ignores the page theme"; the plate is a page style, so the attribute is enough here. If it is not, set the user's theme field.)

- [ ] **Step 3: Run** both → PASS; falsify `test_a_stored_true_on_medium…` by changing `floats` to `self.float_right` → RED; restore.
- [ ] **Step 4: Branch gate** (run in ~4 chunks; never two runs at once; grep the summary line, do not trust the exit code):
  - `uv run pytest courses/tests -n 4 -p no:cacheprovider`
  - `uv run pytest tests -m "not e2e" -n 4 -p no:cacheprovider`
  - `uv run pytest $(ls tests/test_e2e_image*.py tests/test_e2e_notes*.py tests/test_e2e_table*.py tests/test_e2e_print*.py tests/test_e2e_imagezoom.py tests/test_e2e_uniform_block_width.py | grep -v capture_) -m e2e -n 2 -p no:cacheprovider`
  - `uv run ruff check --no-cache . && uv run ruff format --check .`
  - `uv run python manage.py makemigrations --check --dry-run`
- [ ] **Step 5: Screenshots** of unit-914-shaped content (image + two paragraphs + spoiler) at 367 and 1300, light and dark (scratchpad), for the PR.
- [ ] **Step 6: Commit** `git commit -m "test(image-float): CSS source guards, legacy Medium, dark plate"`; then re-check master's FORMAT_VERSION and migration head before opening the PR.
