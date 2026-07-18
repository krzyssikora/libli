# Help doc-page frontend pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the in-app `/help/` element-type lists a scannable term/description treatment and prefix each element-type entry with the same monochrome `#el-*` sprite icon the authoring palette shows, driven by design tokens in both themes.

**Architecture:** A render-time transform in `core/help.py` rewrites author-placed `{el:SLUG}` tokens (in trusted repo markdown) into `<svg><use href="#el-SLUG"/></svg>` markup — a heading pass (a run of leading tokens on an `<hN>`) and a list-entry pass (one leading token in a `<p>`, wrapped into a `.doc-elref` row). `doc.html` includes the existing sprite so the `<use>` refs resolve; `doc-page.css` styles the rows and icons with real tokens (and corrects two phantom tokens already in the file).

**Tech Stack:** Django, python-markdown (`fenced_code`, `tables`), pytest, token-driven CSS (`core/static/core/css/tokens.css`), the `#el-*` SVG sprite (`templates/courses/manage/_icon_sprite.html`).

## Global Constraints

- **Token-driven CSS only**, both themes. Dark mode is `[data-theme="dark"]` on the token set; style with token variables (`--surface-sunken`, `--text-primary`, `--text-tertiary`, `--border-default`, `--space-*`, `--radius-*`) — no media queries, no new hardcoded colors.
- **Reuse the existing `#el-*` sprite** — never invent icons. Slugs are the sprite id minus the `el-` prefix.
- **Help/doc surface only** — no product changes. Screenshot follow-ups (roster re-point, `demo.png` seed) are explicitly out of scope.
- **Slug set is a hardcoded `frozenset`** in `core/help.py` — no import-time reading of the template file. Drift from the sprite is caught by a test, not at runtime.
- **`{el:SLUG}` tokens are language-independent** — the identical token prefix goes in both the `.md` (EN) and `.pl.md` (PL) files.
- **Each element list entry must be a single markdown paragraph** (a blank line starts a new `<p>`, which would orphan the continuation outside the row).
- Icons are decorative: `aria-hidden="true" focusable="false"`.
- Follow repo test style: pytest functions, `monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)` for temp docs, `@pytest.mark.django_db` + `client` + `make_ca`/`make_pa` for view tests, `django.contrib.staticfiles.finders` for static files. Extend `tests/test_help.py`; do not add a parallel module.
- Verify with `uv run pytest` (bash `pytest` is not on PATH — use `uv run`).

---

### Task 1: The `resolve_element_icons` transform + `ELEMENT_ICON_SLUGS`

**Files:**
- Modify: `core/help.py` (add the frozenset, the compiled patterns, the two callbacks, and `resolve_element_icons`; do NOT wire it into `render_markdown_doc` yet — that is Task 2)
- Test: `tests/test_help.py`

**Interfaces:**
- Produces:
  - `ELEMENT_ICON_SLUGS: frozenset[str]` — the 30 sprite ids minus `el-`.
  - `resolve_element_icons(html: str) -> str` — heading-inject pass then list-entry-wrap pass over rendered HTML; a `{el:SLUG}` whose slug ∉ the frozenset is left as literal text.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_help.py` (top-level, near the other pure-function tests):

```python
def test_element_icons_wraps_list_entry():
    from core.help import resolve_element_icons

    html = "<p>{el:text} <strong>Text</strong> — the workhorse block.</p>"
    out = resolve_element_icons(html)
    assert '<div class="doc-elref">' in out
    assert '<use href="#el-text"></use>' in out
    assert '<div class="doc-elref__body"><strong>Text</strong> — the workhorse block.</div>' in out
    assert "{el:" not in out  # token consumed, no leading space before <strong>


def test_element_icons_injects_single_heading():
    from core.help import resolve_element_icons

    out = resolve_element_icons("<h2>{el:revealgate} Show more</h2>")
    # Opening tag reconstructed, icon injected, text + closing tag intact, no stray space.
    assert out == (
        '<h2><svg class="ic" aria-hidden="true" focusable="false">'
        '<use href="#el-revealgate"></use></svg>Show more</h2>'
    )


def test_element_icons_injects_heading_run_two_icons():
    from core.help import resolve_element_icons

    out = resolve_element_icons(
        "<h2>{el:choice-single}{el:choice-multi} Single / Multiple choice</h2>"
    )
    assert out == (
        '<h2><svg class="ic" aria-hidden="true" focusable="false">'
        '<use href="#el-choice-single"></use></svg>'
        '<svg class="ic" aria-hidden="true" focusable="false">'
        '<use href="#el-choice-multi"></use></svg>Single / Multiple choice</h2>'
    )


def test_element_icons_preserves_heading_attrs():
    from core.help import resolve_element_icons

    out = resolve_element_icons('<h3 id="x">{el:spoiler} Spoiler</h3>')
    assert out.startswith('<h3 id="x"><svg')
    assert out.endswith("Spoiler</h3>")


def test_element_icons_adjacent_paragraphs_stay_separate():
    from core.help import resolve_element_icons

    html = "<p>{el:text} <strong>Text</strong> — a.</p>\n<p>{el:image} <strong>Image</strong> — b.</p>"
    out = resolve_element_icons(html)
    assert out.count('<div class="doc-elref">') == 2
    assert '<use href="#el-text"></use>' in out and '<use href="#el-image"></use>' in out


def test_element_icons_unknown_slug_left_literal_in_paragraph():
    from core.help import resolve_element_icons

    html = "<p>{el:bogus} <strong>Nope</strong> — x.</p>"
    out = resolve_element_icons(html)
    assert out == html  # untouched; token stays literal for the no-leak test to catch


def test_element_icons_unknown_slug_left_literal_in_heading():
    from core.help import resolve_element_icons

    out = resolve_element_icons("<h2>{el:bogus} Title</h2>")
    assert out == "<h2>{el:bogus} Title</h2>"


def test_element_icons_leaves_untokened_html_unchanged():
    from core.help import resolve_element_icons

    html = "<p>Ordinary prose with a {curly} brace.</p><h2>Plain heading</h2>"
    assert resolve_element_icons(html) == html


def test_element_icon_slugs_match_sprite():
    """Drift guard: the hardcoded frozenset must equal the sprite's el-* ids."""
    import re as _re

    from core.help import DOCS_ROOT, ELEMENT_ICON_SLUGS

    sprite = (DOCS_ROOT.parent / "templates/courses/manage/_icon_sprite.html").read_text(
        encoding="utf-8"
    )
    sprite_slugs = set(_re.findall(r'id="el-([a-z0-9-]+)"', sprite))
    assert sprite_slugs, "no el-* symbols parsed from sprite"
    assert ELEMENT_ICON_SLUGS == sprite_slugs
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_help.py -k element_icon -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_element_icons'` / `ELEMENT_ICON_SLUGS`.

- [ ] **Step 3: Implement the transform**

In `core/help.py`, after the existing `resolve_static_srcs` function (keep `import re` at the top — it is already imported), add:

```python
# Element-type icon tokens. Authors write {el:SLUG} in trusted help markdown;
# render_markdown_doc rewrites them to the shared #el-* sprite icon. SLUG is the
# sprite id minus its "el-" prefix. Hardcoded (NOT read from the template at import —
# that would resolve a Django template name as a path before the app registry is
# ready, and buys nothing). test_element_icon_slugs_match_sprite keeps this in sync
# with templates/courses/manage/_icon_sprite.html.
ELEMENT_ICON_SLUGS = frozenset(
    {
        "text", "image", "video", "iframe", "math", "html",
        "table", "gallery", "callout", "tabs", "twocolumn", "slidebreak",
        "revealgate", "fillgate", "switchgate", "switchgrid", "filltable",
        "spoiler", "stepper", "markdone", "guessnumber",
        "choice-single", "choice-multi", "shorttext", "shortnumeric",
        "fillblank", "dragwords", "matchpairs", "dragimage", "extended",
    }
)

_ICON_SVG = (
    '<svg class="ic" aria-hidden="true" focusable="false">'
    '<use href="#el-{slug}"></use></svg>'
)

# Heading pass: an <hN> opening tag followed by a run of one-or-more leading tokens.
# The match SPANS the opening tag (groups 1-2) plus the run, so the callback must
# reconstruct the opening tag (re.sub replaces the whole match).
_EL_HEADING_RE = re.compile(r"<h([1-6])([^>]*)>\s*((?:\{el:[a-z0-9-]+\}\s*)+)")
# A single token, used to split a captured run.
_EL_TOKEN_RE = re.compile(r"\{el:([a-z0-9-]+)\}")
# List-entry pass: a paragraph whose first content is a single token. Non-greedy +
# DOTALL so soft-wrapped body lines are captured without swallowing the next entry.
_EL_PARA_RE = re.compile(r"<p>\s*\{el:([a-z0-9-]+)\}\s*(.*?)</p>", re.DOTALL)


def _icon_or_literal(slug):
    """SVG for a known slug; the literal {el:slug} text for an unknown one."""
    if slug in ELEMENT_ICON_SLUGS:
        return _ICON_SVG.format(slug=slug)
    return "{el:" + slug + "}"


def _sub_heading(m):
    level, attrs, run = m.group(1), m.group(2), m.group(3)
    icons = "".join(_icon_or_literal(s) for s in _EL_TOKEN_RE.findall(run))
    return f"<h{level}{attrs}>{icons}"


def _sub_para(m):
    slug, body = m.group(1), m.group(2)
    if slug not in ELEMENT_ICON_SLUGS:
        return m.group(0)  # unknown -> leave the paragraph (and literal token) intact
    return (
        f'<div class="doc-elref">{_ICON_SVG.format(slug=slug)}'
        f'<div class="doc-elref__body">{body}</div></div>'
    )


def resolve_element_icons(html):
    """Rewrite {el:SLUG} tokens into #el-* sprite-icon markup.

    Heading pass first (a run of leading tokens on an <hN> -> one <svg> per token,
    opening tag reconstructed), then list-entry pass (a single leading token in a
    <p> -> a .doc-elref row). Unknown slugs are left as literal text so a typo is
    visible and caught by tests, never a silent wrong/absent icon."""
    html = _EL_HEADING_RE.sub(_sub_heading, html)
    html = _EL_PARA_RE.sub(_sub_para, html)
    return html
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_help.py -k element_icon -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add core/help.py tests/test_help.py
git commit -m "feat(help-doc-page): resolve_element_icons transform + ELEMENT_ICON_SLUGS"
```

---

### Task 2: Wire the transform into rendering + include the sprite on topic pages

**Files:**
- Modify: `core/help.py` (call `resolve_element_icons` in `render_markdown_doc`)
- Modify: `templates/help/doc.html` (include the sprite partial)
- Test: `tests/test_help.py`

**Interfaces:**
- Consumes: `resolve_element_icons` (Task 1).
- Produces: `render_markdown_doc` output now has icon markup; topic pages carry the `#el-*` sprite symbols.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_help.py`:

```python
def test_render_markdown_doc_applies_icon_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    (tmp_path / "d.md").write_text("{el:text} **Text** — body.\n", encoding="utf-8")
    html = core_help.render_markdown_doc("d.md")
    assert '<div class="doc-elref">' in html
    assert '<use href="#el-text"></use>' in html
    assert "{el:" not in html


def test_icon_pass_runs_even_when_static_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    (tmp_path / "d.md").write_text("{el:math} **Math** — body.\n", encoding="utf-8")
    html = core_help.render_markdown_doc("d.md", resolve_static=False)
    assert '<use href="#el-math"></use>' in html  # icons are orthogonal to resolve_static


@pytest.mark.django_db
def test_topic_page_includes_icon_sprite(client):
    make_ca(client)
    resp = client.get(reverse("core:help_topic", args=["content-editors"]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="el-text"' in body  # sprite partial is included -> <use> refs resolve
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_help.py -k "icon_pass or icon_sprite" -v`
Expected: FAIL — icon markup absent (render not wired) and `id="el-text"` not in the page (sprite not included).

- [ ] **Step 3: Wire the transform into `render_markdown_doc`**

In `core/help.py`, change `render_markdown_doc`:

```python
def render_markdown_doc(rel_path, *, resolve_static=True):
    text = (DOCS_ROOT / rel_path).read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["fenced_code", "tables"])
    html = resolve_element_icons(html)
    return resolve_static_srcs(html) if resolve_static else html
```

- [ ] **Step 4: Include the sprite in `templates/help/doc.html`**

Add the include as the first line inside `{% block content %}` (so the sprite symbols are in the same document as the injected `<use>` refs):

```django
{% block content %}
{% include "courses/manage/_icon_sprite.html" %}
<div class="doc-layout">
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_help.py -k "icon_pass or icon_sprite" -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add core/help.py templates/help/doc.html tests/test_help.py
git commit -m "feat(help-doc-page): run icon pass in render + include sprite on topic pages"
```

---

### Task 3: Author `{el:SLUG}` tokens across the element topics (EN + PL) + doc-level guards

**Files:**
- Modify: `docs/help/course-admin/content-editors.md`, `docs/help/course-admin/content-editors.pl.md`
- Modify: `docs/help/course-admin/interactive-elements.md`, `docs/help/course-admin/interactive-elements.pl.md`
- Modify: `docs/help/course-admin/quiz-editors.md`, `docs/help/course-admin/quiz-editors.pl.md`
- Test: `tests/test_help.py`

**Interfaces:**
- Consumes: `render_markdown_doc` with the icon pass (Task 2); `ELEMENT_ICON_SLUGS` (Task 1).

**Token-placement rule:** prepend `{el:SLUG} ` (token + one space) to the start of the line, before the `**Bold term**` (content-editors list) or after the `## ` heading marker (interactive/quiz headings). The identical token prefix goes in the `.md` and `.pl.md` files. Non-element headings ("Containers and nesting", "Where questions live", "See also", "Working with elements", "Structure") and prose get NO token.

**content-editors.md / .pl.md — the 12 "Content element types" list entries** (each is a `**Term** — …` paragraph). Prepend, matching term → slug:
`Text→text`, `Image→image`, `Video→video`, `Iframe→iframe`, `Math→math`, `HTML→html`, `Table→table`, `Gallery→gallery`, `Callout→callout`, `Tabs→tabs`, `Columns→twocolumn`, `Slide break→slidebreak`. (PL terms map by position: `Tekst→text`, `Obraz→image`, `Wideo→video`, `Iframe→iframe`, `Wzór→math`, `HTML→html`, `Tabela→table`, `Galeria→gallery`, `Ramka→callout`, `Zakładki→tabs`, `Kolumny→twocolumn`, `Podział slajdów→slidebreak`.)

Worked example (EN), before → after:
```
**Text** — the workhorse block. A rich-text field supporting headings, lists,
```
→
```
{el:text} **Text** — the workhorse block. A rich-text field supporting headings, lists,
```

**interactive-elements.md / .pl.md — the 9 `##` element headings.** heading → slug:
`Show more→revealgate`, `Fill in & confirm→fillgate`, `Choose & confirm→switchgate`, `Switch grid→switchgrid`, `Fill-in table→filltable`, `Spoiler→spoiler`, `Step-by-step→stepper`, `Checklist→markdone`, `Guess the number→guessnumber`. Leave `## See also` untokened. (The `.pl.md` headings are translated but appear in the same order; prepend the same slug to each.)

Worked example, before → after:
```
## Show more
```
→
```
## {el:revealgate} Show more
```

**quiz-editors.md / .pl.md — the 10 element `##` headings.** heading → slug(s):
`Single / Multiple choice→choice-single + choice-multi` (BOTH tokens), `Short text→shorttext`, `Short numeric→shortnumeric`, `Fill in the blanks→fillblank`, `Drag the words→dragwords`, `Match pairs→matchpairs`, `Matrix question→switchgrid`, `Multi-select grid→switchgrid`, `Drag to image→dragimage`, `Extended response→extended`. Leave `## Where questions live` and `## See also` untokened.

Worked example (the dual-icon combined heading), before → after:
```
## Single / Multiple choice
```
→
```
## {el:choice-single}{el:choice-multi} Single / Multiple choice
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_help.py`:

```python
# --- Element-icon doc coverage ------------------------------------------------

_EL_TOKEN_IN_DOC = re.compile(r"\{el:([a-z0-9-]+)\}")


def _all_help_markdown_paths():
    paths = []
    for topic in TOPICS:
        paths.append(topic.path)
        pl = topic.path.removesuffix(".md") + ".pl.md"
        if (DOCS_ROOT / pl).exists():
            paths.append(pl)
    return paths


def test_every_doc_token_is_a_known_slug():
    from core.help import ELEMENT_ICON_SLUGS

    seen = 0
    for rel in _all_help_markdown_paths():
        text = (DOCS_ROOT / rel).read_text(encoding="utf-8")
        for slug in _EL_TOKEN_IN_DOC.findall(text):
            seen += 1
            assert slug in ELEMENT_ICON_SLUGS, f"{rel}: unknown slug {slug!r}"
    assert seen > 0, "no {el:} tokens found in any help doc"


@pytest.mark.parametrize(
    "rel", ["help/course-admin/content-editors.md",
            "help/course-admin/interactive-elements.md",
            "help/course-admin/quiz-editors.md"],
)
def test_element_topics_leak_no_literal_token(rel):
    html = render_markdown_doc(rel)
    assert "{el:" not in html


# Element name -> expected sprite slug(s), sampled across all three surfaces,
# including the switchgrid reuse and the dual-icon combined choice heading. The
# oracle here is intentional (asserts the deliberate mapping); test_doc_icons_subset
# _of_palette below adds the palette as an independent oracle.
_ICON_EXPECTATIONS = {
    "help/course-admin/content-editors.md": {
        "Text": ["el-text"],          # a .doc-elref list entry
        "Callout": ["el-callout"],
        "Columns": ["el-twocolumn"],
    },
    "help/course-admin/interactive-elements.md": {
        "Show more": ["el-revealgate"],  # a heading
        "Switch grid": ["el-switchgrid"],
    },
    "help/course-admin/quiz-editors.md": {
        "Single / Multiple choice": ["el-choice-single", "el-choice-multi"],  # dual
        "Matrix question": ["el-switchgrid"],       # switchgrid reuse
        "Multi-select grid": ["el-switchgrid"],     # switchgrid reuse
    },
}


@pytest.mark.parametrize("rel", list(_ICON_EXPECTATIONS))
def test_each_element_entry_has_its_expected_icon(rel):
    html = render_markdown_doc(rel)
    for name, slugs in _ICON_EXPECTATIONS[rel].items():
        for slug in slugs:
            assert f'<use href="#{slug}">' in html, f"{rel}: {name} missing #{slug}"


def test_doc_icons_subset_of_palette():
    """Palette is the oracle: every icon the docs use, the add-element palette shows."""
    palette = (
        DOCS_ROOT.parent / "templates/courses/manage/editor/_add_menu.html"
    ).read_text(encoding="utf-8")
    palette_slugs = set(re.findall(r"#el-([a-z0-9-]+)", palette))
    doc_slugs = set()
    for rel in _all_help_markdown_paths():
        text = (DOCS_ROOT / rel).read_text(encoding="utf-8")
        doc_slugs.update(_EL_TOKEN_IN_DOC.findall(text))
    assert doc_slugs, "no doc tokens found"
    assert doc_slugs <= palette_slugs, f"doc icons not in palette: {doc_slugs - palette_slugs}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_help.py -k "doc_token or element_topics_leak or expected_icon or subset_of_palette" -v`
Expected: FAIL — `test_every_doc_token...` fails its `seen > 0` assert and `test_each_element_entry_has_its_expected_icon` fails (no icons rendered yet, tokens not authored).

- [ ] **Step 3: Add tokens to the six markdown files**

Apply the token-placement rule above to all six files. Edit `content-editors.md` and `content-editors.pl.md` (12 list entries each), `interactive-elements.md` and `.pl.md` (9 headings each, skip "See also"), `quiz-editors.md` and `.pl.md` (10 headings each — remember the dual token on the combined choice heading — skip "Where questions live" and "See also"). Keep each list entry a single paragraph.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_help.py -k "doc_token or element_topics_leak or expected_icon or subset_of_palette" -v`
Expected: PASS.

- [ ] **Step 5: Run the full help suite to confirm no regression**

Run: `uv run pytest tests/test_help.py -v`
Expected: PASS (existing tests — including `test_polish_file_is_not_an_english_copy` and the illustration tests — still green; tokens don't disturb images or PL divergence).

- [ ] **Step 6: Commit**

```bash
git add docs/help/course-admin/content-editors.md docs/help/course-admin/content-editors.pl.md docs/help/course-admin/interactive-elements.md docs/help/course-admin/interactive-elements.pl.md docs/help/course-admin/quiz-editors.md docs/help/course-admin/quiz-editors.pl.md tests/test_help.py
git commit -m "feat(help-doc-page): author {el:} icon tokens across element topics (EN+PL)"
```

---

### Task 4: CSS — `.doc-elref` rows, icon sizing, heading icons, phantom-token fix

**Files:**
- Modify: `core/static/core/css/doc-page.css`
- Test: `tests/test_help.py`

**Interfaces:**
- Consumes: the `.doc-elref` / `.doc-elref__body` / `.ic` markup emitted by Task 1, rendered on pages from Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_help.py`:

```python
def test_doc_page_css_uses_real_tokens_and_styles_elref():
    from django.contrib.staticfiles import finders

    css = open(finders.find("core/css/doc-page.css"), encoding="utf-8").read()
    assert ".doc-elref" in css
    assert ".doc-elref__body" in css
    # phantom tokens corrected to real ones
    assert "--surface-2" not in css
    assert "--text-muted" not in css
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_help.py -k doc_page_css -v`
Expected: FAIL — `.doc-elref` absent and `--surface-2` / `--text-muted` still present.

- [ ] **Step 3: Edit `core/static/core/css/doc-page.css`**

(a) Correct the two phantom tokens (4 occurrences). Replace every `var(--surface-2, rgba(127,127,127,.12))` with `var(--surface-sunken)` and every `var(--text-muted, #666)` with `var(--text-tertiary)`:

```css
.doc-page pre { background: var(--surface-sunken);
  padding: 1rem; border-radius: .5rem; overflow-x: auto; }
```
```css
.help-index__empty { color: var(--text-tertiary); margin-top: 1.5rem; }
```
```css
.doc-sidebar__item.is-active { background: var(--surface-sunken);
  font-weight: 600; }
```
```css
.doc-breadcrumb { color: var(--text-tertiary); margin-bottom: 1rem; }
```

(b) Append the element-icon block (icons and rows scoped under `.doc-page`; `.ic` sizing is defined here because `editor.css`'s `.ic` rule is not loaded on help pages):

```css
/* Element-type reference (content-editors list) + per-type icons (help/doc.html
   includes the #el-* sprite). Sizes .ic locally since editor.css isn't loaded here. */
.doc-page .ic { width: 1.15rem; height: 1.15rem; flex: 0 0 auto; fill: currentColor; }
.doc-elref { display: flex; align-items: flex-start; gap: var(--space-3);
  padding: var(--space-2) var(--space-3); margin: var(--space-2) 0;
  background: var(--surface-sunken); border: 1px solid var(--border-default);
  border-radius: var(--radius-md); }
.doc-elref .ic { margin-top: .15rem; }
.doc-elref__body { flex: 1; min-width: 0; }
.doc-page h2 .ic { display: inline-block; vertical-align: -.12em;
  margin-right: var(--space-2); color: var(--text-tertiary); }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_help.py -k doc_page_css -v`
Expected: PASS.

- [ ] **Step 5: Verify visually in light + dark (Playwright screenshots)**

Serve the app, log in as a course-admin, and screenshot the content-editors and interactive-elements topic pages in both themes. Follow the project `run`/screenshot habit; capture:
- `content-editors` (light + dark) — the "Content element types" `.doc-elref` rows: icon aligned to the first line, term legible, rows visually separated, body wraps (no horizontal overflow), surfaces read correctly on both themes.
- `interactive-elements` (light + dark) — `##` headings each show a quiet leading icon; the quiz-editors "Single / Multiple choice" heading shows BOTH icons.

Self-critique the four shots: icon alignment, row rhythm, contrast of `--surface-sunken` rows vs page background, heading-icon weight. If `--surface-sunken` rows are too subtle against the page background, adjust the row background to a token that reads (e.g. `--surface-raised` with the border carrying separation) — token-only, both themes — and re-shoot. Do not ship until both themes look right.

- [ ] **Step 6: Commit**

```bash
git add core/static/core/css/doc-page.css tests/test_help.py
git commit -m "feat(help-doc-page): style .doc-elref rows + per-type icons, fix phantom tokens"
```

---

## Self-Review

**Spec coverage:**
- §1 transform (two-pass, frozenset, unknown-slug-literal, function replacement, heading run) → Task 1. ✓
- §2 sprite availability on topic pages → Task 2 (include) + view test. ✓
- §3 CSS (`.doc-elref`, `.doc-elref__body`, `.ic` sizing, heading icons, phantom-token fix, tokens) → Task 4. ✓
- §4 content edits (EN+PL, dual-token choice heading, switchgrid reuse) → Task 3. ✓
- Data flow (icon pass unconditional vs `resolve_static`) → Task 2 (`test_icon_pass_runs_even_when_static_disabled`). ✓
- Testing §1 frozenset↔sprite → Task 1; §2 token-known → Task 3; §3 no-leak → Task 3; §4 per-entry mapping → Task 3; §5 palette-oracle subset → Task 3; §6 adjacency → Task 1; §7 targeted/untokened-unchanged → Task 1; §8 sprite-on-page → Task 2. ✓
- Manual light+dark verification → Task 4 Step 5. ✓

**Placeholder scan:** No TBD/TODO; every code + test step shows complete content; token edits give the full term→slug mapping plus worked examples per surface.

**Type consistency:** `resolve_element_icons`, `ELEMENT_ICON_SLUGS`, `_ICON_SVG`, `_EL_HEADING_RE`/`_EL_TOKEN_RE`/`_EL_PARA_RE`, `_icon_or_literal`, `_sub_heading`, `_sub_para` are named identically where defined (Task 1) and consumed (Tasks 2–3). Emitted markup (`<div class="doc-elref">`, `<div class="doc-elref__body">`, `<use href="#el-SLUG">`, reconstructed `<hN attrs>`) matches between Task 1 code, Task 3 assertions, and Task 4 CSS selectors.
