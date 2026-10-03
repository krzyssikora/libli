# "W skrócie" Summary Callout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sixth, visually quiet `CalloutElement` kind, stored as `"summary"` and labelled "Key facts" / "W skrócie". It renders as a flat card with a slate top bar and a real `<h3>` topic title. It is never numbered and never shifts the numbers of the Examples and Tasks around it.

**Architecture:** A new `TextChoices` member drives the editor `<select>`, the transfer validator and `KIND_DEFAULT_HEADING` with no code change. The hand-written changes are:
- a write-side force in `CalloutElement.save()` and a read-side guard in `numbering.walk()`;
- a separate `{% if %}` branch in `calloutelement.html`;
- one selector in `math.js`;
- three accent one-liners and one surface block in `courses.css`;
- an `original_kind` + `clean()` pair on `CalloutElementForm`, which hides the "numbered" checkbox for a saved summary card and restores the per-kind default when a card leaves summary;
- a catalog entry and help-doc wording.

`FORMAT_VERSION` does not change.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django + pytest-xdist, BeautifulSoup (bs4), Playwright (e2e, `-m e2e`), ruff, Django i18n (`makemessages`/`compilemessages`), `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-10-03-summary-callout-design.md`. Read it in full before starting. The rationale for every non-obvious instruction below is there.

## Global Constraints

- Worktree: `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/summary-callout`, branch `pipeline/summary-callout`. Start EVERY Bash call with `cd C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/summary-callout &&`, because agent shells reset their cwd.
- Owner decisions, VERBATIM (review rounds must not reverse these):

| # | Decision |
|---|---|
| D1 | Cheat-sheet (scan), not self-test: everything visible. |
| D2 | New `CalloutElement` kind, value `"summary"`, label "Key facts" / Polish "W skrócie" (also the empty-heading fallback). |
| D3 | Layout: cards stack full width; side-by-side only by the author putting cards in the existing `TwoColumnElement`. NO auto-grid, no renderer grouping of adjacent elements. |
| D4 | Visual = option B′ "flat card": white surface (no accent tint), hairline border all round (`var(--border-subtle)`), 3px muted slate TOP bar (light `#4b6b8a`; a dark-theme value and a print rule like the other five kinds) INSTEAD of the left spine, NO shadow, NO icon chip, NO uppercase eyebrow. The heading is a real heading element in normal title case (the topic name). Rejected: hairline-only (C), because opened spoilers (`.spoiler__children`) and before/after panels (`.ba__panel`) already use a 2px left rule and would be confused with it. |
| D5 | Summary cards are NEVER numbered. `courses/numbering.py` `callout_numbers` skips `kind == "summary"`, so the shared unit-wide counter is not consumed. `CalloutElement.save()` forces `numbered=False` for summary. `KIND_DEFAULT_NUMBERED` gains `summary: False`. The editor hides the "numbered" checkbox for this kind and the server ignores it. |
| D6 | The back-link to the source lesson is an ordinary internal content link the author types in the card body. NO new "related lesson" field (deferred). |
| D7 | **`FORMAT_VERSION` is NOT bumped; it stays at 16** (owner, 2026-10-03, "yes, go with b"). This reverses an earlier approval of a bump, which rested on a false premise. It follows the Task-kind D2 precedent and the rule in `test_format_version_is_unchanged`: the version rises only when an EXISTING payload shape changes. Export never validates kinds, so exporting always works. An instance running a build from before this feature refuses an archive that contains a summary card, with "Element 'x' has an unknown callout kind". Every other archive still imports. There is one course (mat-pp), authored on libli.pl, so the sequence is: deploy, then author cards. |

- Stored value `"summary"`; enum member `SUMMARY`; English label `"Key facts"`; Polish `"W skrócie"`.
- **`FORMAT_VERSION` stays 16.** Do not edit `courses/transfer/schema.py` or any test that pins 16.
- Light accent `#4b6b8a`. Dark accent `#9db4cb`: this is the candidate. It must pass T9b (≥ 3:1 against both `--surface-raised` and `--surface-base` in its theme; measured 6.77:1 and 8.28:1). If it is ever changed, change `courses.css` and the T9 pin together. Print value `#4b6b8a`.
- Title CSS, exactly: `font-size: 1.05rem; font-weight: 700; line-height: 1.3; letter-spacing: normal; color: var(--text-primary); margin: 0 0 var(--space-3);`, plus `.callout__title:last-child { margin-bottom: 0; }` and `.callout__title .katex { font-size: 1em; font-weight: inherit; color: inherit; }`.
- Title markup, exactly: `<h3 class="callout__title">{{ el.display_heading }}</h3>`. It REPLACES the `<div class="callout__header">` wrapper and is the first child of the `<aside>`. The heading level is fixed and never depth-computed. The card has no `overflow: hidden` and no pseudo-element bar.
- Do NOT touch migration `0060` or `courses/tests/test_callout_numbered_migration.py`. `_callout_icon.html` gains ONLY a comment.
- The new form attribute is named `original_kind` (public, set in `CalloutElementForm.__init__` AFTER `super().__init__`). The template keys on `form.original_kind`, never on `form.instance.kind` or `form.kind.value`.
- Tools are not on PATH. Always use `uv run pytest ...`, `uv run python manage.py ...`, `uv run ruff check --no-cache .` AND `uv run ruff format --check .` (both are CI gates).
- Start the test DB before ANY pytest run: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. Without it a run hangs for about 4 minutes.
- Isolate this worktree's test DB by prefixing EVERY pytest command with `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary`. Editing `.env` has no effect. Add `--create-db` to the first run of the plan only.
- NEVER pass `-q`: `addopts` already has it, and a second one hides the summary line. Read the summary line (`N passed`, `N failed`), never the exit code.
- e2e files need `-m e2e`, or pytest silently deselects them. Scope runs narrowly per task. The whole-repo sweep is the branch gate at the very end (Task 8), run in chunks.
- After ANY CSS edit, run EVERY CSS source test: `tests/test_*css*.py courses/tests/test_*css*.py`.
- Django template comments that span lines MUST be `{% comment %}…{% endcomment %}`, never `{# #}`. A multi-line `{# #}` renders as page text. Do not put template tags inside a comment block.
- CSS comments: never cite `courses.css:<line>` (enforced by `test_css_citations_are_durable`). Never write a star directly followed by a slash inside comment prose.
- Bash heredocs can eat backslashes. Write CSS, regex or LaTeX containing backslashes with the Edit/Write tools.
- After Task 1: `uv run python manage.py makemigrations --check --dry-run` must report no changes.
- i18n:
  1. Run `uv run python manage.py makemessages -l pl -l en`.
  2. Fix any fuzzy entry by deleting BOTH the `#, fuzzy` line and the `#|` line.
  3. Run `uv run python manage.py compilemessages -l pl`.
  4. Commit only `locale/*/LC_MESSAGES/django.po` and `locale/pl/LC_MESSAGES/django.mo`.
- Before each commit, run `uv run ruff format <every .py file the task touched>` (the plan's code is not pre-wrapped to 88 columns everywhere), then both ruff gates. Migrations are excluded from ruff.
- Falsification is a house rule. A mutant is applied by HAND-EDIT and removed BY EDITING it back. NEVER use `git checkout`/`git restore`/`git stash` to revert a mutant, because that destroys uncommitted work. After removing a mutant, run `git diff --stat` and confirm the diff matches the pre-mutant state.
- Commit with explicit paths only (never `git add -A` / `git add .`). Every commit message ends with these two lines:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
  ```

## Review Focus

The spec's §6 table covers each mechanism, but it leaves these five user-facing input classes unexercised. They are listed most likely first, and each now has a test in its owning task:

1. **An author switches an existing, ticked Example to "W skrócie" in the select and saves.** No JS hides the box, so the POST carries `numbered=on` for a summary. The card must be stored `numbered=False`, and the re-opened form must show no checkbox. Test: Task 5, `test_switching_a_ticked_example_to_summary_unnumbers_it_and_hides_the_box`.
2. **A card with a blank heading.** T1 checks only `display_heading`. The rendered `<h3>` must read "Key facts" and must not be empty. Test: Task 3, `test_an_empty_heading_summary_titles_itself_key_facts`.
3. **Two cards inside Columns (D3's only side-by-side path) before an Example.** The numbering walk descends `TwoColumnElement` through a different accessor than the top-level case in T3. Even with the rows flagged `numbered=True` behind `save()`'s back, the Example must stay "1". Test: Task 2, `test_summary_cards_inside_columns_leave_the_next_example_at_one`.
4. **Duplicating or pasting a summary card.** This is the commonest copy gesture. It goes through `build_element_export` → `graft_elements`, which runs NO validator. The copy must stay `kind="summary"`, keep its heading and stay unnumbered. Test: Task 6, `test_duplicating_a_summary_card_keeps_it_an_unnumbered_summary`.
5. **`save(update_fields=…)` given a generator, the caller's own list, or an empty iterable.** These are the shapes the spec says must be handled. The generator must be consumed only once, the caller's list must not be mutated, and an empty iterable must stay Django's no-op. Tests: Task 1, `test_update_fields_generator_is_consumed_once`, `test_the_callers_update_fields_list_is_not_mutated`, `test_empty_update_fields_stays_a_no_op`.

---

### Task 1: Model kind, `save()` force, numbering default, migration 0068, surface lists

**Files:**
- Modify: `courses/models.py` (`CalloutElement` docstring, `Kind`, `save()`, `KIND_DEFAULT_NUMBERED`)
- Create: `courses/migrations/0068_alter_calloutelement_kind.py` (generated)
- Test: `courses/tests/test_callout_model.py` (T1, T2, Review Focus 5)
- Test: `courses/tests/test_callout_numbering.py` (T4)
- Test: `tests/test_text_colour_css.py`, `tests/test_border_contrast_css.py` (T11)

T11 is placed here and not in the CSS task on purpose. `test_every_callout_kind_has_a_ground_in_both_surface_lists` derives its expectation from `CalloutElement.Kind.values`, so it goes RED the moment the enum gains `SUMMARY`. The surface literals must land in the same commit.

**Interfaces:**
- Consumes: nothing.
- Produces: `CalloutElement.Kind.SUMMARY` (value `"summary"`, label `_("Key facts")`). `KIND_DEFAULT_HEADING["summary"]` follows automatically. `KIND_DEFAULT_NUMBERED["summary"] is False`. `CalloutElement.save()` forces `numbered=False` for summary and extends a non-empty `update_fields`. `LIGHT_SURFACES["callout-summary"]` / `DARK_SURFACES["callout-summary"]` and `BORDER_GROUNDS` gain `"callout-summary"`. Migration `0068_alter_calloutelement_kind` becomes the graph head.

- [ ] **Step 1: Start the test DB**

```
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
```

- [ ] **Step 2: Write the failing tests (T1, T2, Review Focus 5)**

In `courses/tests/test_callout_model.py`, extend the existing `test_display_heading_falls_back_to_kind_default` with one line (T1):

```python
def test_display_heading_falls_back_to_kind_default():
    # gettext_lazy under the EN catalog renders the English label.
    assert str(CalloutElement(kind="example").display_heading) == "Example"
    assert str(CalloutElement(kind="note").display_heading) == "Note"
    assert str(CalloutElement(kind="tip").display_heading) == "Tip"
    assert str(CalloutElement(kind="warning").display_heading) == "Important"
    assert str(CalloutElement(kind="task").display_heading) == "Task"
    assert str(CalloutElement(kind="summary").display_heading) == "Key facts"
```

Append to the end of the same file (T2 + Review Focus 5):

```python
def test_a_summary_is_never_stored_numbered():
    """D5, the write-side guard. Mutant: remove the save() force -> True."""
    el = CalloutElement.objects.create(kind="summary", numbered=True, body="")
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False


def test_switching_to_summary_with_update_fields_still_unnumbers():
    """save(update_fields=["kind"]) would otherwise persist the kind and leave the
    stale True in the row. Mutant: drop the update_fields extension -> True."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    el.kind = "summary"
    el.save(update_fields=["kind"])
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False


def test_update_fields_generator_is_consumed_once():
    """Review Focus 5. Mutant: test membership on the raw iterable, then splat it
    -> the generator is already exhausted, only `numbered` is written, and the
    kind change is lost."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    el.kind = "summary"
    el.save(update_fields=(f for f in ["kind"]))
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False


def test_the_callers_update_fields_list_is_not_mutated():
    """Review Focus 5. Mutant: `update_fields.append("numbered")` -> the caller's
    list grows behind its back."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    fields = ["kind"]
    el.kind = "summary"
    el.save(update_fields=fields)
    assert fields == ["kind"]


def test_empty_update_fields_stays_a_no_op():
    """Review Focus 5. Django treats an empty update_fields as "save nothing".
    Mutant: extend it even when empty -> {"numbered"} is written and the row
    flips to False."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    el.kind = "summary"
    el.save(update_fields=[])
    el.refresh_from_db()
    assert el.kind == "example"
    assert el.numbered is True
```

- [ ] **Step 3: Write the failing test (T4)**

In `courses/tests/test_callout_numbering.py`, extend `test_kind_default_numbered_values`:

```python
def test_kind_default_numbered_values():
    assert KIND_DEFAULT_NUMBERED["example"] is True
    assert KIND_DEFAULT_NUMBERED["task"] is True
    assert KIND_DEFAULT_NUMBERED["warning"] is True
    assert KIND_DEFAULT_NUMBERED["note"] is False
    assert KIND_DEFAULT_NUMBERED["tip"] is False
    assert KIND_DEFAULT_NUMBERED["summary"] is False
```

(`test_kind_default_numbered_covers_every_kind` is left unchanged. It goes red on its own once the enum gains the member without a map entry.)

- [ ] **Step 4: Write the T11 surface-list changes**

In `tests/test_text_colour_css.py`:

(a) In the module docstring, change `which is eleven surfaces, not two` to `which is twelve surfaces, not two`.

(b) Replace the comment block above `LIGHT_SURFACES` (from `# Normative surface list` through `# Callout grounds are`) so it reads:

```python
# Normative surface list (spec: "The surface list is the specification").
#
# These literals are a CROSS-CHECK, not the source of truth:
# test_surface_literals_still_match_the_css below re-reads the six token surfaces
# from tokens.css and recomputes the five callout grounds from courses.css. So
# changing --surface-base, a .callout--* accent, or the 6% mix reddens the suite
# instead of silently leaving the AA guard measuring values that no longer exist.
# The summary card ("W skrócie") is the exception: it is UNTINTED, so its ground is
# --surface-raised itself and is pinned by equality, not recomputed as a mix.
# Callout grounds are
```

(c) Add the last entry of `LIGHT_SURFACES`:

```python
    "callout-task": "#FAF3F8",
    "callout-summary": "#FFFFFF",  # untinted (D4): equals --surface-raised
}
```

(d) Add the last entry of `DARK_SURFACES`:

```python
    "callout-task": "#383030",
    "callout-summary": "#2C2925",  # untinted (D4): equals --surface-raised
}
```

(e) At the END of `test_surface_literals_still_match_the_css` (after the `for theme, surfaces, ground in (...)` loop, at the function's indentation), append:

```python
    # The summary card is untinted (D4). Its ground IS --surface-raised, so it can
    # never be recomputed as a 6% mix by the loop above. Pin it by equality instead,
    # or a later --surface-raised change would leave a stale summary ground
    # measuring green.
    for label, surfaces in (("LIGHT", LIGHT_SURFACES), ("DARK", DARK_SURFACES)):
        assert surfaces["callout-summary"] == surfaces["--surface-raised"], (
            f"{label} callout-summary must equal --surface-raised; update both"
        )
```

Do NOT add `"summary"` to the `("example", "note", "tip", "warning", "task")` tuple in that test.

In `tests/test_border_contrast_css.py`, extend `BORDER_GROUNDS`:

```python
BORDER_GROUNDS = (
    "--surface-raised",
    "--surface-base",
    "--surface-sunken",
    "callout-example",
    "callout-note",
    "callout-tip",
    "callout-warning",
    "callout-task",
    "callout-summary",
)
```

- [ ] **Step 5: Run the tests and confirm they FAIL**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest --create-db courses/tests/test_callout_model.py courses/tests/test_callout_numbering.py tests/test_text_colour_css.py tests/test_border_contrast_css.py
```

Expected failures, each with its reason:
- `test_display_heading_falls_back_to_kind_default`: `'Example' == 'Key facts'`. With no enum member, `kind_label` falls back to `"example"`.
- `test_a_summary_is_never_stored_numbered`: `save()` coerces `summary` → `example`, so `el.kind == "summary"` fails.
- `test_switching_to_summary_with_update_fields_still_unnumbers`, `test_update_fields_generator_is_consumed_once`: these fail on the kind assertion for the same reason.
- `test_kind_default_numbered_values`: `KeyError: 'summary'`.
- `test_every_callout_kind_has_a_ground_in_both_surface_lists`: `callout grounds drifted: {'callout-summary'}`. The lists now carry a kind the enum lacks.

`test_the_callers_update_fields_list_is_not_mutated` and `test_empty_update_fields_stays_a_no_op` PASS before the change. They guard the implementation shape and are falsified in Step 10. The border tests pass, because the new key exists in both lists.

- [ ] **Step 6: Implement the model change**

In `courses/models.py`, change the class docstring's kind list:

```python
class CalloutElement(ElementBase):
    """A framed, always-visible callout/aside (Example/Note/Tip/Important/Task/Key
    facts) holding rich text + math. Zero JS, no server endpoint. Mirrors
    SpoilerElement minus the toggle, plus a `kind` and an optional heading. See the
    callout-element design doc."""
```

Append the member after `TASK`:

```python
        TASK = "task", _("Task")
        # "W skrócie" in Polish. A flat card for summary units: never numbered
        # (save() below and numbering.walk() both enforce it), no icon, no eyebrow.
        SUMMARY = "summary", _("Key facts")
```

Replace `save()`:

```python
    def save(self, *args, **kwargs):
        if self.kind not in self.Kind.values:
            self.kind = self.Kind.EXAMPLE
        if self.kind == self.Kind.SUMMARY:
            # D5: a summary card is never numbered, whoever writes it (editor form,
            # transfer importer, seeders, shell). A save(update_fields=["kind"])
            # that switches a row to summary must persist the False too, so
            # "numbered" joins a NON-EMPTY update_fields. Materialise once into a NEW
            # collection: the caller's object may be a generator (one pass only) or
            # its own list (never mutate it). An empty iterable stays Django's
            # deliberate no-op.
            self.numbered = False
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                update_fields = frozenset(update_fields)
                if update_fields and "numbered" not in update_fields:
                    update_fields = update_fields | {"numbered"}
                kwargs["update_fields"] = update_fields
        self.body = normalize_body(self.body)
        super().save(*args, **kwargs)
```

Extend `KIND_DEFAULT_NUMBERED`. Leave its comment for Task 5, which adds the second reader that makes the comment stale:

```python
KIND_DEFAULT_NUMBERED = {
    CalloutElement.Kind.EXAMPLE.value: True,
    CalloutElement.Kind.TASK.value: True,
    CalloutElement.Kind.WARNING.value: True,
    CalloutElement.Kind.NOTE.value: False,
    CalloutElement.Kind.TIP.value: False,
    CalloutElement.Kind.SUMMARY.value: False,
}
```

- [ ] **Step 7: Generate the migration**

```
uv run python manage.py makemigrations courses -n alter_calloutelement_kind
```

Open `courses/migrations/0068_alter_calloutelement_kind.py` and confirm it has exactly the following. The header date and quoting style may differ:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0067_questionresponse_revealed_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calloutelement',
            name='kind',
            field=models.CharField(choices=[('example', 'Example'), ('note', 'Note'), ('tip', 'Tip'), ('warning', 'Important'), ('task', 'Task'), ('summary', 'Key facts')], default='example', max_length=12),
        ),
    ]
```

It has one state-only `AlterField` and no `RunPython`. Then confirm it is the single graph head and nothing else is pending:

```
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py showmigrations courses
```

Expected: `No changes detected`, and `0068_alter_calloutelement_kind` is the last `courses` entry.

- [ ] **Step 8: Run the tests and confirm they PASS**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_model.py courses/tests/test_callout_numbering.py tests/test_text_colour_css.py tests/test_border_contrast_css.py
```

Expected: all passed.

- [ ] **Step 9: Run the neighbouring suites that walk the migration graph**

These restore to the graph head with a bare `migrate courses`. Confirm that 0068 does not break them:

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_numbered_migration.py courses/tests/test_blank_answer_unescape_migration.py courses/tests/test_caption_migration.py courses/tests/test_shortnumeric_migration.py courses/tests/test_blank_question_stem.py courses/tests/test_publish_migration.py tests/test_geogebra_migration.py tests/test_subject_migrations.py courses/tests/test_callout_form.py courses/tests/test_callout_render.py
```

Expected: all passed.

- [ ] **Step 10: FALSIFY**

Apply each mutant by hand-edit, run the named test, see RED, then remove the mutant by editing it back:

| Mutant (hand-edit in `courses/models.py` unless stated) | Run | Expected RED |
|---|---|---|
| T1: delete the `SUMMARY = "summary", _("Key facts")` line (also delete the map entry so the module imports) | `courses/tests/test_callout_model.py::test_display_heading_falls_back_to_kind_default` | `'Example' == 'Key facts'` |
| T2a: delete the line `self.numbered = False` | `courses/tests/test_callout_model.py::test_a_summary_is_never_stored_numbered` | `assert True is False` |
| T2b: delete the whole `update_fields = kwargs.get(...)` … `kwargs["update_fields"] = update_fields` block | `courses/tests/test_callout_model.py::test_switching_to_summary_with_update_fields_still_unnumbers` | `assert True is False` |
| RF5a: replace the block with `uf = kwargs.get("update_fields")` / `if uf is not None and "numbered" not in uf: kwargs["update_fields"] = {*uf, "numbered"}` | `...::test_update_fields_generator_is_consumed_once` | `assert 'example' == 'summary'` |
| RF5b: replace the block with `uf = kwargs.get("update_fields")` / `if uf: uf.append("numbered")` | `...::test_the_callers_update_fields_list_is_not_mutated` | `['kind', 'numbered'] == ['kind']` |
| RF5c: change `if update_fields and "numbered" not in update_fields:` to `if "numbered" not in update_fields:` | `...::test_empty_update_fields_stays_a_no_op` | `assert False is True` |
| T4: `CalloutElement.Kind.SUMMARY.value: True` | `courses/tests/test_callout_numbering.py::test_kind_default_numbered_values` | `assert True is False` |
| T11a (`tests/test_text_colour_css.py`): delete the `"callout-summary"` line from `DARK_SURFACES` | `tests/test_text_colour_css.py::test_every_callout_kind_has_a_ground_in_both_surface_lists` | `DARK_SURFACES callout grounds drifted: {'callout-summary'}` (the equality block also errors with KeyError) |
| T11b (`tests/test_border_contrast_css.py`): misspell `"callout-summary"` as `"callout-sumary"` in `BORDER_GROUNDS` | `tests/test_border_contrast_css.py::test_border_grounds_all_exist_in_the_measured_surface_lists` | `has no entry for: ['callout-sumary']` |
| T11c (`tests/test_text_colour_css.py`): change the LIGHT `"callout-summary"` literal to `"#FAFAFA"` | `tests/test_text_colour_css.py::test_surface_literals_still_match_the_css` | `LIGHT callout-summary must equal --surface-raised` |

Each run command takes the form `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest <node id>`. After the last mutant is removed:

```
git diff --stat
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_model.py courses/tests/test_callout_numbering.py tests/test_text_colour_css.py tests/test_border_contrast_css.py
```

Expected: the diff lists only the files of this task, and all tests pass.

- [ ] **Step 11: Lint and commit**

```
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/models.py courses/migrations/0068_alter_calloutelement_kind.py courses/tests/test_callout_model.py courses/tests/test_callout_numbering.py tests/test_text_colour_css.py tests/test_border_contrast_css.py
git commit -m "$(cat <<'EOF'
feat(callout): add the W skrócie (summary) kind, never numbered

Kind.SUMMARY "Key facts"; save() forces numbered=False and extends a
non-empty update_fields without mutating the caller's iterable;
KIND_DEFAULT_NUMBERED["summary"] = False; state-only migration 0068;
the untinted summary ground joins the surface and border lists.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

---

### Task 2: Numbering guard in `walk()`

**Files:**
- Modify: `courses/numbering.py` (module docstring, `walk()`)
- Test: `courses/tests/test_callout_numbering.py` (T3, T3b, Review Focus 3)

**Interfaces:**
- Consumes: `CalloutElement.Kind.SUMMARY` (Task 1).
- Produces: `callout_numbers(unit)` never assigns a number to a summary card, and still descends into its children.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_callout_numbering.py`. The `_callout` helper creates through `save()`, which forces summary to False, so each test forces True with `QuerySet.update()`. It then asserts that the bypass really happened; otherwise the test would be vacuous.

```python
def _force_numbered(*joins):
    """Write numbered=True BEHIND save()'s back (QuerySet.update), the way a raw
    migration or a bulk update could. Asserts the bypass took, or the test using
    it would pass vacuously on a build with no read-side guard."""
    pks = [j.object_id for j in joins]
    CalloutElement.objects.filter(pk__in=pks).update(numbered=True)
    assert all(
        CalloutElement.objects.filter(pk__in=pks).values_list("numbered", flat=True)
    )


def test_a_summary_card_never_consumes_a_number():
    """T3 / D5, the read-side guard. Mutant: remove `kind != SUMMARY` from the
    numbered branch in walk() -> {ex1: 1, summary: 2, ex2: 3}."""
    _course, unit = make_course_with_unit()
    ex1 = _callout(unit, "example", numbered=True, order=0)
    summary = _callout(unit, "summary", numbered=False, order=1)
    ex2 = _callout(unit, "example", numbered=True, order=2)
    _force_numbered(summary)

    numbers = callout_numbers(unit)
    assert numbers == {ex1.pk: 1, ex2.pk: 2}
    assert summary.pk not in numbers


def test_a_numbered_example_nested_in_a_summary_card_keeps_its_number():
    """T3b. Only the INCREMENT is skipped for a summary card; the container descent
    must still run. Mutant: `continue` for a summary before the CONTAINER_MODELS
    recursion -> the nested Example vanishes: {ex1: 1, ex3: 2}."""
    _course, unit = make_course_with_unit()
    ex1 = _callout(unit, "example", numbered=True, order=0)
    summary = _callout(unit, "summary", numbered=False, order=1)
    nested = _callout(
        unit, "example", numbered=True, parent=summary, tab_id=SINGLE_SLOT_ID, order=0
    )
    ex3 = _callout(unit, "example", numbered=True, order=2)
    _force_numbered(summary)

    numbers = callout_numbers(unit)
    assert numbers == {ex1.pk: 1, nested.pk: 2, ex3.pk: 3}
    assert summary.pk not in numbers


def test_summary_cards_inside_columns_leave_the_next_example_at_one():
    """Review Focus 3. D3's only side-by-side path is a TwoColumnElement, which the
    walk descends through a DIFFERENT accessor (resolved_columns) than the
    top-level case above. Mutant: remove `kind != SUMMARY` -> {left: 1, right: 2,
    ex: 3}."""
    from courses.models import TwoColumnElement

    _course, unit = make_course_with_unit()
    cols = TwoColumnElement.objects.create(
        data={"columns": [{"id": "c000001"}, {"id": "c000002"}]}
    )
    cols_join = Element.objects.create(unit=unit, content_object=cols, order=0)
    left = _callout(
        unit, "summary", numbered=False, parent=cols_join, tab_id="c000001", order=0
    )
    right = _callout(
        unit, "summary", numbered=False, parent=cols_join, tab_id="c000002", order=0
    )
    ex = _callout(unit, "example", numbered=True, order=1)
    _force_numbered(left, right)

    assert callout_numbers(unit) == {ex.pk: 1}
```

- [ ] **Step 2: Run the tests and confirm they FAIL**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_numbering.py
```

Expected: all three FAIL. With no guard, the force-numbered summary rows take numbers:
- T3 gets `{ex1: 1, summary: 2, ex2: 3}`;
- T3b gets `{ex1: 1, summary: 2, nested: 3, ex3: 4}`;
- RF3 gets `{left: 1, right: 2, ex: 3}`.

- [ ] **Step 3: Implement the guard**

In `courses/numbering.py`, add one sentence to the module docstring, before `See docs/...`:

```python
"""Consecutive numbering of callouts within a unit.

ONE public function. It is deliberately self-contained -- it re-queries its own
roots rather than accepting a caller's element list -- so its query count is a
property of this module and not of each of its four call sites.

Summary ("W skrócie") cards never take a number. CalloutElement.save() already
forces numbered=False for them, but walk() skips them too, because a row written
by QuerySet.update() or a raw migration bypasses save().

See docs/superpowers/specs/2026-08-18-callout-numbering-design.md section 3.
"""
```

In `walk()`, replace the numbered branch:

```python
            # D5: never number a summary card, even one whose row bypassed save().
            # ONLY the increment is skipped -- the CONTAINER_MODELS descent below is
            # a separate `if` and still runs, so a numbered Example nested in a card
            # keeps its number. Never write this as an early `continue`.
            if (
                isinstance(obj, CalloutElement)
                and obj.numbered
                and obj.kind != CalloutElement.Kind.SUMMARY
            ):
                counter += 1
                numbers[row.pk] = counter  # PRE-ORDER: before descending
```

- [ ] **Step 4: Run the tests and confirm they PASS**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_numbering.py courses/tests/test_callout_numbering_render.py
```

Expected: all passed. `test_query_count_on_a_real_shaped_unit` stays at 21, because the guard reads an attribute that is already loaded.

- [ ] **Step 5: FALSIFY**

| Mutant (hand-edit `courses/numbering.py`) | Run | Expected RED |
|---|---|---|
| T3: delete `and obj.kind != CalloutElement.Kind.SUMMARY` | `courses/tests/test_callout_numbering.py::test_a_summary_card_never_consumes_a_number` and `::test_summary_cards_inside_columns_leave_the_next_example_at_one` | dict mismatch, the summary rows numbered |
| T3b: keep the guard and also insert, directly after `continue  # dangling GFK...`: `if isinstance(obj, CalloutElement) and obj.kind == CalloutElement.Kind.SUMMARY:` / `    continue` | `courses/tests/test_callout_numbering.py::test_a_numbered_example_nested_in_a_summary_card_keeps_its_number` | `{ex1: 1, ex3: 2}` != expected |

Remove each mutant by editing. Then run `git diff --stat` (only `courses/numbering.py` and the test file) and re-run Step 4: expected all passed.

- [ ] **Step 6: Lint and commit**

```
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/numbering.py courses/tests/test_callout_numbering.py
git commit -m "$(cat <<'EOF'
feat(callout): numbering skips summary cards but still descends into them

Belt-and-braces read-side guard for rows that bypassed save(). Only the
counter increment is skipped; a numbered Example nested in a card keeps
its number.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

---

### Task 3: Summary render branch, icon-partial comment, KaTeX selector

**Files:**
- Modify: `templates/courses/elements/calloutelement.html`
- Modify: `templates/courses/elements/_callout_icon.html` (comment only)
- Modify: `courses/static/courses/js/math.js` (`renderInlineText` selector list)
- Test: `courses/tests/test_callout_render.py` (T5, Review Focus 2, escaping)
- Test: `courses/tests/test_callout_numbering_render.py` (T6)
- Test: `courses/tests/test_math_selectors.py` (T5b)

**Interfaces:**
- Consumes: `CalloutElement.Kind.SUMMARY`, `display_heading` (Task 1).
- Produces: for `kind == "summary"`, the `<aside class="callout callout--summary">` whose first element child is `<h3 class="callout__title">`. It has no `callout__header`, `callout__icon` or `callout__heading`. `.callout__title` is in `renderInlineText`'s selector list. Task 4 styles `.callout__title`.

- [ ] **Step 1: Write the T6 characterisation test first, and confirm it PASSES on the current build**

T6 guards the generic branch, which this task must not change. Writing it first and seeing it GREEN on the untouched template proves its exact-string literal is right.

Append to `courses/tests/test_callout_numbering_render.py`:

```python
# The Example (book) icon, verbatim from _callout_icon.html's else-branch.
BOOK_ICON = (
    '<svg class="callout__icon" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<path d="M12 7v14"/>'
    '<path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3z"/>'
    '<path d="M21 18a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1h-5a4 4 0 0 0-4 4"/></svg>'
)


def _squash(html):
    """Whitespace-normalised: the summary branch adds an {% if %} that may shift
    indentation in the generic branch without changing a single tag."""
    return " ".join(html.split())


def test_the_generic_header_is_unchanged_by_the_summary_branch():
    """T6, exact. Mutant: any edit that alters the generic header or leaks the
    summary branch into it."""
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(
        kind="example", heading="Heading", numbered=True, body=""
    )
    join = Element.objects.create(unit=unit, content_object=el)
    html = _squash(_rendered(el, join, {join.pk: 1}))
    assert (
        '<div class="callout__header"> '
        + BOOK_ICON
        + ' <span class="callout__heading">Example '
        '<span class="callout__number">1</span>. Heading</span> </div>'
    ) in html
    assert "callout__title" not in html


@pytest.mark.parametrize(
    "kind, numbered",
    [
        ("example", True),
        ("note", False),
        ("tip", False),
        ("warning", True),
        ("task", True),
    ],
)
def test_every_other_kind_keeps_the_eyebrow_header(kind, numbered):
    """T6, loose, over all five non-summary kinds (an unnumbered Note included).
    Mutant: make the summary branch unconditional -> no callout__header here."""
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind=kind, numbered=numbered, body="")
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 1} if numbered else {})
    assert "callout__header" in html
    assert "callout__heading" in html
    assert "callout__title" not in html
```

Run:

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_numbering_render.py
```

Expected: all PASS on the current template. If the exact-string test fails, the literal is wrong. Print `_squash(...)` and correct `BOOK_ICON` or the joining spaces to match the CURRENT render. Never change the template to fit the test.

- [ ] **Step 2: Write the failing tests (T5, T5b, Review Focus 2)**

Append to `courses/tests/test_callout_render.py`:

```python
def _summary_soup(**fields):
    from bs4 import BeautifulSoup

    # PERSISTED: save() must keep "summary" (the enum member exists), and the
    # render reads the stored kind.
    el = CalloutElement.objects.create(kind="summary", **fields)
    html = el.render()
    return html, BeautifulSoup(html, "html.parser")


def test_summary_renders_an_h3_title_and_no_eyebrow():
    """T5. Mutant: render summary through the generic branch -> a callout__header
    with an icon and an eyebrow, and no h3."""
    html, soup = _summary_soup(heading="Funkcja liniowa", body="<p>x</p>")
    aside = soup.find("aside")
    assert "callout--summary" in aside["class"]
    first = aside.find(True, recursive=False)  # first ELEMENT child, not whitespace
    assert first.name == "h3"
    assert first["class"] == ["callout__title"]
    assert first.get_text() == "Funkcja liniowa"
    assert "callout__header" not in html
    assert "callout__icon" not in html
    assert "callout__heading" not in html


def test_an_empty_heading_summary_titles_itself_key_facts():
    """Review Focus 2 (D2 fallback, rendered). Mutant: `{{ el.heading }}` in the h3
    -> an empty title."""
    _html, soup = _summary_soup(heading="", body="<p>x</p>")
    title = soup.find("h3", class_="callout__title")
    assert title is not None
    assert title.get_text() == "Key facts"


def test_the_summary_title_escapes_the_heading():
    """Mutant: `{{ el.display_heading|safe }}` -> raw markup in the h3."""
    html, _soup = _summary_soup(heading="a < b & c", body="")
    assert '<h3 class="callout__title">a &lt; b &amp; c</h3>' in html
```

In `courses/tests/test_math_selectors.py`, extend the region tuple (T5b):

```python
def test_every_typeset_region_is_in_the_selector_list():
    sel = _render_inline_text_selectors()
    for region in (
        ".el--text",
        ".spoiler__toggle",
        ".callout__heading",
        ".callout__title",
    ):
        assert region in sel, f"{region} missing from renderInlineText"
```

- [ ] **Step 3: Run the tests and confirm they FAIL**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_render.py courses/tests/test_math_selectors.py
```

Expected failures:
- `test_summary_renders_an_h3_title_and_no_eyebrow`: the first child is a `div`, not `h3`.
- `test_an_empty_heading_summary_titles_itself_key_facts`: `title is None`.
- `test_the_summary_title_escapes_the_heading`: the string is not found.
- `test_every_typeset_region_is_in_the_selector_list`: `.callout__title missing from renderInlineText`.

- [ ] **Step 4: Implement the template branch**

In `templates/courses/elements/calloutelement.html`, replace the five lines from the `<aside class="callout callout--{{ el.kind }}">` opener through the header's closing `</div>` (the opener, `<div class="callout__header">`, the include, the span, `</div>`) with the block below. The block repeats the `<aside>` opener, so the result has exactly one `<aside>`:

```django
<aside class="callout callout--{{ el.kind }}">
  {% comment %}
  Summary ("W skrócie" / Key facts) is a flat card: a real h3 topic title and
  nothing else in the header -- no icon chip, no number, no uppercase eyebrow
  (D4/D5). The h3 REPLACES the callout__header wrapper rather than sitting in it,
  so the wrapper's flex layout and margin-bottom never stack with the h3's own
  margin. The level is FIXED at h3, deliberately not computed from nesting depth:
  summary units' topics are h3 in their text bodies today, and the unit title is
  the page's h1. Do not reuse callout__heading here -- that is the eyebrow class.
  The generic branch below must stay tag-for-tag unchanged.
  {% endcomment %}
  {% if el.kind == "summary" %}
  <h3 class="callout__title">{{ el.display_heading }}</h3>
  {% else %}
  <div class="callout__header">
    {% include "courses/elements/_callout_icon.html" %}
    <span class="callout__heading">{% if number %}{{ el.kind_label }} <span class="callout__number">{{ number }}</span>{% if el.heading %}. {{ el.heading }}{% endif %}{% else %}{{ el.display_heading }}{% endif %}</span>
  </div>
  {% endif %}
```

Everything from `{% if el.body %}` to `</aside>` is unchanged.

At the very top of `templates/courses/elements/_callout_icon.html`, before `{% if el.kind == "note" %}`, add:

```django
{% comment %}
There is deliberately no branch for the summary kind (W skrócie / Key facts): its
flat card has no icon chip (D4), and calloutelement.html's summary branch never
includes this partial. The final else-branch book icon is the Example icon only.
{% endcomment %}
```

In `courses/static/courses/js/math.js`, in `renderInlineText`, insert `.callout__title, ` directly after `.callout__heading, ` in the `querySelectorAll` string. The result is:

```js
    (root || document).querySelectorAll(".el--text, .el--table, .el--gallery, .el--tabs, .fillgate, .stepper, .markdone, .guessnumber, .spoiler__toggle, .callout__heading, .callout__title, [data-math-title]").forEach(function (el) {
```

- [ ] **Step 5: Run the tests and confirm they PASS**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_render.py courses/tests/test_callout_numbering_render.py courses/tests/test_math_selectors.py tests/test_container_label_math.py
```

Expected: all passed, T6 included.

- [ ] **Step 6: FALSIFY**

| Mutant (hand-edit) | Run | Expected RED |
|---|---|---|
| T5: change `{% if el.kind == "summary" %}` to `{% if el.kind == "summaryX" %}` | `courses/tests/test_callout_render.py::test_summary_renders_an_h3_title_and_no_eyebrow` | first child is `div` |
| RF2: in the h3, `{{ el.display_heading }}` → `{{ el.heading }}` | `...::test_an_empty_heading_summary_titles_itself_key_facts` | `'' == 'Key facts'` |
| Escape: `{{ el.display_heading }}` → `{{ el.display_heading|safe }}` | `...::test_the_summary_title_escapes_the_heading` | string not found |
| T5b: delete `.callout__title, ` from math.js | `courses/tests/test_math_selectors.py` | `.callout__title missing from renderInlineText` |
| T6 (leak): change `{% if el.kind == "summary" %}` to `{% if True %}` | `courses/tests/test_callout_numbering_render.py` | both T6 tests red, with no `callout__header` |
| T6 (alter header): in the generic branch, change `{{ el.kind_label }} <span` to `{{ el.kind_label }}&nbsp;<span` | `courses/tests/test_callout_numbering_render.py::test_the_generic_header_is_unchanged_by_the_summary_branch` | exact string not found |

Remove each mutant by editing. Then run `git diff --stat` (only the three source files and three test files of this task) and re-run Step 5: expected all passed.

- [ ] **Step 7: Lint and commit**

```
uv run ruff check --no-cache .
uv run ruff format --check .
git add templates/courses/elements/calloutelement.html templates/courses/elements/_callout_icon.html courses/static/courses/js/math.js courses/tests/test_callout_render.py courses/tests/test_callout_numbering_render.py courses/tests/test_math_selectors.py
git commit -m "$(cat <<'EOF'
feat(callout): render the summary card with an h3 title, no eyebrow

Separate {% if %} branch; the h3 replaces callout__header. Generic header
pinned whitespace-normalised. math.js typesets .callout__title.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

---

### Task 4: Summary CSS (accents, flat surface, title, print)

**Files:**
- Modify: `courses/static/courses/css/courses.css` (callout header comment, title rules, accent groups, surface block, print block)
- Test: `tests/test_callout_css.py` (T9, T9b)
- Test: `courses/tests/test_callout_nesting_css.py` (T9c)
- Test: `tests/test_print_tokens_css.py` (T10)

**Interfaces:**
- Consumes: the `callout--summary` and `callout__title` classes emitted by Task 3. `LIGHT_SURFACES`, `DARK_SURFACES` and `_ratio` come from `tests/test_text_colour_css.py`, extended in Task 1.
- Produces: `.callout--summary { --callout-accent: #4b6b8a; }`, `[data-theme="dark"] .callout--summary { --callout-accent: #9db4cb; }`, the surface block, the `.callout__title*` rules, and the print rule.

- [ ] **Step 1: Write the failing tests (T9, T9b)**

Replace `tests/test_callout_css.py` in full with the following. The two existing task tests are kept verbatim. The class list gains two entries, and the summary tests are appended:

```python
import re
from pathlib import Path

from tests.test_text_colour_css import DARK_SURFACES
from tests.test_text_colour_css import LIGHT_SURFACES
from tests.test_text_colour_css import _ratio

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"

# The same print marker tests/test_print_tokens_css.py uses. Everything BEFORE it
# is the screen CSS -- deliberately NOT that test's light/dark split, whose light
# half would exclude the summary surface block that sits after the dark group.
PRINT_MARKER = '@media print {\n  [data-theme="dark"] .callout--'

# ^-anchored so the light pattern can never match inside the dark selector, and
# the dark one never matches the INDENTED print-block line.
SUMMARY_LIGHT_ACCENT = (
    r"^\.callout--summary\s*\{\s*--callout-accent:\s*"
    r"(#[0-9a-fA-F]{6})"
)
SUMMARY_DARK_ACCENT = (
    r'^\[data-theme="dark"\]\s+\.callout--summary\s*\{\s*--callout-accent:\s*'
    r"(#[0-9a-fA-F]{6})"
)


def _screen_css():
    css = CSS.read_text(encoding="utf-8")
    screen, sep, _printed = css.partition(PRINT_MARKER)
    assert sep, "courses.css has no callout @media print block"
    return re.sub(r"/\*.*?\*/", "", screen, flags=re.S)


def _summary_accent(pattern):
    match = re.search(pattern, CSS.read_text(encoding="utf-8"), re.M)
    assert match, f"no summary accent matching {pattern!r}"
    return match.group(1).lower()


def _summary_blocks():
    """Every non-print `.callout--summary { ... }` body. UNANCHORED, so the
    [data-theme="dark"]-prefixed one-liner is caught too."""
    return [
        " ".join(body.split())
        for body in re.findall(r"\.callout--summary\s*\{([^}]*)\}", _screen_css())
    ]


def _anchored_block(pattern):
    match = re.search(pattern, _screen_css(), re.M)
    assert match, f"no block matching {pattern!r}"
    return " ".join(match.group(1).split())


def test_courses_css_defines_callout_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".callout",
        ".callout__header",
        ".callout__icon",
        ".callout__heading",
        ".callout__body",
        ".callout--example",
        ".callout--note",
        ".callout--tip",
        ".callout--warning",
        ".callout--task",
        ".callout--summary",
        ".callout__title",
    ]:
        assert cls in css, f"missing callout class: {cls}"


def test_callout_task_light_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    # ^-anchored: without it this pattern also matches inside the dark selector,
    # so deleting the light rule would leave the test green.
    assert re.search(
        r"^\.callout--task\s*\{\s*--callout-accent:\s*#a8318f", css, re.M
    ), "light .callout--task accent missing or changed"


def test_callout_task_dark_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(
        r'^\[data-theme="dark"\]\s+\.callout--task\s*\{\s*--callout-accent:\s*#ee9fd8',
        css,
        re.M,
    ), "dark .callout--task accent missing or changed"


def test_callout_summary_accents_are_pinned():
    """T9. The dark literal is the implementer's pick (spec 3.4); if it changes,
    change it here and in courses.css together, and re-run T9b."""
    assert _summary_accent(SUMMARY_LIGHT_ACCENT) == "#4b6b8a"
    assert _summary_accent(SUMMARY_DARK_ACCENT) == "#9db4cb"


def test_callout_summary_is_a_flat_card():
    """T9, D4: no tint, a hairline instead of the spine, a 3px accent top bar and
    no shadow in ANY summary block."""
    blocks = _summary_blocks()
    assert len(blocks) >= 3, f"expected light, dark and surface blocks: {blocks!r}"
    joined = " ".join(blocks)
    assert "border-top: 3px solid var(--callout-accent);" in joined
    assert "border-left: 1px solid var(--border-subtle);" in joined
    assert "background: var(--surface-raised);" in joined
    for block in blocks:
        assert "box-shadow" not in block, f"a summary block has a shadow: {block!r}"


def test_callout_title_overrides_the_heading_reset():
    """T9. reset.css gives headings line-height 1.15 and the house letter-spacing,
    and zeroes margins; the title must override all three explicitly."""
    block = _anchored_block(r"^\.callout__title\s*\{([^}]*)\}")
    assert "letter-spacing: normal;" in block
    assert "line-height: 1.3;" in block
    assert "margin: 0 0 var(--space-3);" in block


def test_callout_title_last_child_drops_its_bottom_margin():
    """T9. A heading-only card: .callout's padding blocks margin collapsing."""
    block = _anchored_block(r"^\.callout__title:last-child\s*\{([^}]*)\}")
    assert "margin-bottom: 0" in block


def test_callout_summary_accents_clear_3_to_1_on_both_grounds():
    """T9b, WCAG 1.4.11: the top bar is the kind's only visual identity. Its
    neighbours are the card inside and the page ground outside. Read from
    courses.css, never restated as literals here."""
    for pattern, surfaces in (
        (SUMMARY_LIGHT_ACCENT, LIGHT_SURFACES),
        (SUMMARY_DARK_ACCENT, DARK_SURFACES),
    ):
        accent = _summary_accent(pattern)
        for ground in ("--surface-raised", "--surface-base"):
            ratio = _ratio(accent, surfaces[ground])
            assert ratio >= 3.0, (
                f"summary accent {accent} on {ground} {surfaces[ground]}: "
                f"{ratio:.2f}:1 < 3:1"
            )
```

Append to `courses/tests/test_callout_nesting_css.py` (T9c):

```python
def test_callout_title_katex_matches_the_title_size():
    """KaTeX's own sheet sets 1.21em, which would make inline maths visibly larger
    than the 1.05rem title. Mutant: delete the rule, or drop font-size: 1em."""
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    assert ".callout__title .katex" in css, "no .callout__title .katex rule"
    block = css.split(".callout__title .katex")[1].split("}")[0]
    assert "font-size: 1em" in block
```

In `tests/test_print_tokens_css.py`, change (T10):

```python
CALLOUT_KINDS = ("example", "note", "tip", "warning", "task", "summary")
```

- [ ] **Step 2: Run the tests and confirm they FAIL**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_callout_css.py courses/tests/test_callout_nesting_css.py tests/test_print_tokens_css.py
```

Expected failures:
- `test_courses_css_defines_callout_element`: `missing callout class: .callout--summary`.
- The accent, flat-card, title and last-child tests: `no summary accent…` or `no block matching…`.
- T9b: `no summary accent…`.
- T9c: `no .callout__title .katex rule`.
- `test_print_restates_every_dark_callout_accent_with_the_light_value`: `.callout--summary has a dark accent but no print override`.

- [ ] **Step 3: Implement the CSS**

All edits are in `courses/static/courses/css/courses.css`. Use the Edit tool.

(a) In the callout header comment, change `(Example / Note / Tip / Important / Task)` to `(Example / Note / Tip / Important / Task /\n   Key facts)`. The full first lines become:

```css
/* --- Callout element (student consumption). A framed, always-visible aside
   (Example / Note / Tip / Important / Task / Key facts) holding rich text +
   math. Zero JS: the static render IS the behaviour.
```

(b) Directly after the `.callout__heading { … }` block, which ends with `color: var(--callout-accent);\n}`, and before `.callout__body { color: …`, insert:

```css
/* The summary kind's title (Key facts / W skrócie). A real h3 in normal case,
   not the eyebrow above. reset.css zeroes heading margins and gives headings
   line-height 1.15 and the house letter-spacing, so all three are overridden
   here explicitly. The last-child rule serves a heading-only card, where
   .callout's padding stops the bottom margin from collapsing away. */
.callout__title {
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: normal;
  color: var(--text-primary);
  margin: 0 0 var(--space-3);
}
.callout__title:last-child { margin-bottom: 0; }
```

(c) Directly after the `.callout__heading .katex { … }` block, insert:

```css
/* KaTeX inside the summary title. No uppercase to undo here, but KaTeX's own
   1.21em would make inline maths visibly larger than the title text. */
.callout__title .katex { font-size: 1em; font-weight: inherit; color: inherit; }
```

(d) In the light accent group, after `.callout--task    { --callout-accent: #a8318f; }`, add:

```css
.callout--summary { --callout-accent: #4b6b8a; }
```

(e) In the dark accent group, after `[data-theme="dark"] .callout--task    { --callout-accent: #ee9fd8; }`, add:

```css
[data-theme="dark"] .callout--summary { --callout-accent: #9db4cb; }
```

(f) Directly after the dark group, before the `/* Before / after — base */` comment, insert one blank line and then:

```css
/* Key facts (W skrócie), the summary card: flat, per D4. No accent tint, a
   hairline where the other kinds draw the 3px spine, and the 3px accent as a
   TOP bar instead. No shadow, and never overflow: hidden -- callouts hold wide
   display maths and scroll boxes. The accent itself stays in the aligned
   one-liners above, like every other kind. Border, radius, padding and margin
   are inherited from .callout. */
.callout--summary {
  background: var(--surface-raised);
  border-left: 1px solid var(--border-subtle);
  border-top: 3px solid var(--callout-accent);
}
```

(g) In the `@media print` "Print: callout accents" block, after `  [data-theme="dark"] .callout--task    { --callout-accent: #a8318f; }`, add a line with the same two-space indent:

```css
  [data-theme="dark"] .callout--summary { --callout-accent: #4b6b8a; }
```

- [ ] **Step 4: Run every CSS source test and confirm they PASS**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_*css*.py courses/tests/test_*css*.py
```

Expected: all passed. This includes `test_css_comments_are_terminated_once`, `test_css_citations_are_durable`, `test_courses_css_braces_balance` and the T11 surface tests from Task 1.

- [ ] **Step 5: FALSIFY**

| Mutant (hand-edit `courses.css` unless stated) | Run | Expected RED |
|---|---|---|
| delete `border-top: 3px solid var(--callout-accent);` | `tests/test_callout_css.py::test_callout_summary_is_a_flat_card` | border-top assertion |
| `border-left: 1px solid var(--border-subtle);` → `border-left: 3px solid var(--border-subtle);` | same | border-left assertion |
| `border-left: 1px solid var(--border-subtle);` → `border-left: 1px solid var(--callout-accent);` | same | border-left assertion |
| `background: var(--surface-raised);` → `background: color-mix(in srgb, var(--callout-accent) 6%, var(--surface-raised));` | same | background assertion |
| add `box-shadow: var(--shadow-sm);` inside the dark one-liner: `[data-theme="dark"] .callout--summary { --callout-accent: #9db4cb; box-shadow: var(--shadow-sm); }` | same | `a summary block has a shadow` |
| delete `letter-spacing: normal;` from `.callout__title` | `tests/test_callout_css.py::test_callout_title_overrides_the_heading_reset` | letter-spacing assertion |
| `.callout__title:last-child { margin-bottom: 0; }` → `.callout__title:last-child { margin-bottom: var(--space-3); }` | `tests/test_callout_css.py::test_callout_title_last_child_drops_its_bottom_margin` | assertion |
| dark accent `#9db4cb` → `#4b6b8a` (too dark on dark: 2.60:1) in courses.css only | `tests/test_callout_css.py::test_callout_summary_accents_clear_3_to_1_on_both_grounds` | `2.60:1 < 3:1` (the pin test is red too) |
| delete the `.callout__title .katex` rule | `courses/tests/test_callout_nesting_css.py::test_callout_title_katex_matches_the_title_size` | `no .callout__title .katex rule` |
| delete only `font-size: 1em; ` from that rule | same | `font-size: 1em` assertion |
| delete the print line `[data-theme="dark"] .callout--summary { --callout-accent: #4b6b8a; }` | `tests/test_print_tokens_css.py::test_print_restates_every_dark_callout_accent_with_the_light_value` | `.callout--summary has a dark accent but no print override` |

Remove each mutant by editing. Then run `git diff --stat` (only `courses.css` and the three test files) and re-run Step 4: expected all passed.

- [ ] **Step 6: Lint and commit**

```
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/static/courses/css/courses.css tests/test_callout_css.py courses/tests/test_callout_nesting_css.py tests/test_print_tokens_css.py
git commit -m "$(cat <<'EOF'
feat(callout): flat-card CSS for the summary kind

Slate accent (#4b6b8a light, #9db4cb dark, print restates light) drawn as
a 3px top bar; untinted surface, hairline instead of the spine, no shadow.
.callout__title overrides the reset.css heading metrics. Both accents
measured >= 3:1 on --surface-raised and --surface-base.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

---

### Task 5: Editor: hide the checkbox for summary, restore the default when leaving summary

**Files:**
- Modify: `courses/element_forms.py` (`CalloutElementForm`, imports)
- Modify: `templates/courses/manage/editor/_edit_callout.html`
- Modify: `courses/models.py` (three stale comments: the `numbered` field comment, and the `KIND_DEFAULT_NUMBERED` comment's "Exactly ONE runtime caller" and "NOT read by CalloutElementForm")
- Modify: `courses/tests/test_callout_numbering.py` (the stale docstring of `test_model_default_is_a_flat_true_regardless_of_kind`)
- Test: `courses/tests/test_callout_authoring.py` (T7, T7b, Review Focus 1)
- Test: `courses/tests/test_callout_form.py` (T7c)

The stale comments are rewritten HERE rather than in Task 1, because this task adds the second runtime reader of the map that makes them stale. Rewriting them in Task 1 would describe behaviour that does not exist yet.

**Interfaces:**
- Consumes: `CalloutElement.Kind.SUMMARY`, `KIND_DEFAULT_NUMBERED["summary"]` (Task 1), and `save()`'s force (Task 1).
- Produces: `CalloutElementForm.original_kind` (str, set once in `__init__`) and `CalloutElementForm.clean()`. `_edit_callout.html` renders the checkbox iff `form.original_kind != "summary"`.

- [ ] **Step 1: Write the failing tests (T7, T7b, Review Focus 1)**

In `courses/tests/test_callout_authoring.py`, add after `_lesson_unit`:

```python
def _save_callout(client, course, unit, element="new", **fields):
    """The FULL element_save shape. A missing `el_title` blanks the join title, and
    `unit_token` is the concurrency token, so the unit is re-read first: creating
    rows bumps `updated`."""
    unit.refresh_from_db()
    data = {
        "type": "callout",
        "element": str(element),
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "",
        "heading": "",
        "body": "<p>x</p>",
    }
    data.update(fields)
    return client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _edit_form_html(client, course, join):
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": join.pk},
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="kind"' in html  # the callout form really rendered
    return html


def _saved(kind, numbered, unit):
    el = CalloutElement.objects.create(kind=kind, numbered=numbered, body="")
    return el, Element.objects.create(unit=unit, content_object=el)
```

Append the tests:

```python
def test_edit_form_offers_the_summary_kind(client):
    """T7. Fixture kind is NOT summary, or the option would carry `selected`."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("example", True, unit)
    html = _edit_form_html(client, course, join)
    assert '<option value="summary">Key facts</option>' in html


def test_save_round_trips_the_summary_kind(client):
    """T7. A ticked box on a NEW summary is ignored: save() forces False."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = _save_callout(
        client, course, unit, kind="summary", heading="Funkcja liniowa", numbered="on"
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit).content_object
    assert el.kind == "summary"
    assert el.heading == "Funkcja liniowa"
    assert el.numbered is False


def test_the_summary_edit_form_has_no_numbered_checkbox(client):
    """T7 / D5. Mutant: remove the {% if %} around the checkbox."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("summary", False, unit)
    assert 'name="numbered"' not in _edit_form_html(client, course, join)


def test_the_example_edit_form_keeps_the_numbered_checkbox(client):
    """T7, the present half. Mutant: invert the {% if %}."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("example", True, unit)
    assert 'name="numbered"' in _edit_form_html(client, course, join)


def test_switching_a_ticked_example_to_summary_unnumbers_it_and_hides_the_box(
    client,
):
    """Review Focus 1. No JS hides the box when the select changes, so the POST
    carries numbered=on for a summary. Mutant: remove the save() force -> True."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("example", True, unit)
    resp = _save_callout(
        client, course, unit, element=join.pk, kind="summary", numbered="on"
    )
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False
    assert 'name="numbered"' not in _edit_form_html(client, course, join)


def test_leaving_summary_for_example_restores_numbered(client):
    """T7b. The summary form rendered no checkbox, so the POST has no key.
    Mutant: remove the clean() restore -> False."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("summary", False, unit)
    resp = _save_callout(client, course, unit, element=join.pk, kind="example")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.kind == "example"
    assert el.numbered is True


def test_leaving_summary_for_note_restores_unnumbered(client):
    """T7b. Mutant: restore a flat True instead of KIND_DEFAULT_NUMBERED."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("summary", False, unit)
    resp = _save_callout(client, course, unit, element=join.pk, kind="note")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.kind == "note"
    assert el.numbered is False


def test_a_sent_numbered_value_is_not_overridden_when_leaving_summary(client):
    """T7b. CheckboxInput reads "false" as False. Mutant: drop the
    `not in self.data` check -> True."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("summary", False, unit)
    resp = _save_callout(
        client, course, unit, element=join.pk, kind="example", numbered="false"
    )
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.numbered is False


def test_an_unticked_example_stays_unnumbered(client):
    """T7b. The restore applies ONLY when leaving summary. Mutant: apply it
    unconditionally -> True."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("example", True, unit)
    resp = _save_callout(client, course, unit, element=join.pk, kind="example")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.numbered is False


def test_a_422_after_asking_for_summary_still_shows_the_checkbox(client):
    """T7b. kind stays VALID and the heading is over max_length=120, so the form
    fails while construct_instance() still copies kind="summary" onto
    form.instance. Mutant: key the {% if %} on form.instance.kind -> hidden."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("example", True, unit)
    resp = _save_callout(
        client, course, unit, element=join.pk, kind="summary", heading="z" * 121
    )
    assert resp.status_code == 422
    assert 'name="numbered"' in resp.content.decode()


def test_a_new_callout_still_renders_and_saves_the_checkbox(client):
    """T7b, the create path (no instance): original_kind is the default
    "example", so the box renders ticked and a ticked POST saves True."""
    from django.template.loader import render_to_string

    from courses.element_forms import CalloutElementForm

    body = render_to_string(
        "courses/manage/editor/_edit_callout.html", {"form": CalloutElementForm()}
    )
    assert 'name="numbered" checked' in body

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = _save_callout(client, course, unit, kind="example", numbered="on")
    assert resp.status_code == 200
    assert Element.objects.get(unit=unit).content_object.numbered is True
```

- [ ] **Step 2: Write the failing tests (T7c)**

Append to `courses/tests/test_callout_form.py`:

```python
def _summary():
    from courses.models import CalloutElement

    return CalloutElement.objects.create(kind="summary", heading="", body="")


def test_leaving_summary_restores_the_new_kinds_numbered_default():
    """T7c. Mutant: remove the clean() restore -> False (no key was sent)."""
    form = CalloutElementForm(
        data={"kind": "example", "heading": "", "body": ""}, instance=_summary()
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["numbered"] is True


def test_a_sent_false_is_never_overridden():
    """T7c. Mutant: drop the key-presence check -> True."""
    form = CalloutElementForm(
        data={"kind": "example", "numbered": "false", "heading": "", "body": ""},
        instance=_summary(),
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["numbered"] is False


def test_the_key_presence_check_is_prefix_safe():
    """A prefixed form's data key is "p-numbered". Mutant: test the bare
    "numbered" in self.data -> the sent False is overridden to True."""
    form = CalloutElementForm(
        data={"p-kind": "example", "p-numbered": "false", "p-heading": "", "p-body": ""},
        instance=_summary(),
        prefix="p",
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["numbered"] is False


def test_original_kind_is_read_before_validation_mutates_the_instance():
    """T7c. kind is VALID (so construct_instance copies it) and the heading is
    not, so the form fails AND the two attributes diverge. With an unchanged kind
    the lazy mutant could never go red. Mutant: derive original_kind lazily from
    self.instance (e.g. a property) -> "example"."""
    form = CalloutElementForm(
        data={"kind": "example", "heading": "z" * 121, "body": ""},
        instance=_summary(),
    )
    assert not form.is_valid()
    assert form.original_kind == "summary"
    assert form.instance.kind == "example"


def test_an_invalid_kind_skips_the_restore_and_reports_the_field():
    """kind failed choice validation -> no cleaned kind; the restore must not
    KeyError, and the normal field error must come back."""
    form = CalloutElementForm(
        data={"kind": "bogus", "heading": "", "body": ""}, instance=_summary()
    )
    assert not form.is_valid()
    assert "kind" in form.errors


def test_the_create_path_original_kind_is_the_default():
    assert CalloutElementForm().original_kind == "example"
```

- [ ] **Step 3: Run the tests and confirm they FAIL**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_authoring.py courses/tests/test_callout_form.py
```

Expected failures:
- `test_the_summary_edit_form_has_no_numbered_checkbox` and `test_switching_a_ticked_example_to_summary_unnumbers_it_and_hides_the_box`: the box is still rendered.
- `test_leaving_summary_for_example_restores_numbered`: `False is True`.
- `test_leaving_summary_restores_the_new_kinds_numbered_default`: `False is True`.
- The `original_kind` tests: `AttributeError: 'CalloutElementForm' object has no attribute 'original_kind'`.

Others pass already: the option and round trip (Task 1), the note, sent-false, unticked-example and 422 tests, and the new-callout test. They guard against the wrong implementation and are falsified in Step 7.

- [ ] **Step 4: Implement the form**

In `courses/element_forms.py`, add the import as the first `courses.models` import line. Ruff's isort orders constants first; if `ruff check` reports `I001`, run `uv run ruff check --no-cache --fix courses/element_forms.py`:

```python
from courses.models import KIND_DEFAULT_NUMBERED
from courses.models import BeforeAfterElement
```

Replace `CalloutElementForm`:

```python
class CalloutElementForm(forms.ModelForm):
    class Meta:
        model = CalloutElement
        fields = ["kind", "numbered", "heading", "body"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Read ONCE, here. self.instance is the saved row, or (on the create path,
        # where builder passes instance=None) a fresh CalloutElement() whose kind
        # is the default "example". construct_instance has NOT run yet: it runs in
        # full_clean(), and even on an INVALID post it copies the posted kind onto
        # self.instance -- which element_save then re-renders on a 422. So both the
        # editor partial's checkbox condition and clean()'s restore read THIS
        # attribute, never self.instance.kind.
        self.original_kind = self.instance.kind

    def clean(self):
        cleaned_data = super().clean()
        new_kind = cleaned_data.get("kind")
        # A summary card's form renders no "numbered" checkbox (D5), so a POST that
        # moves a card AWAY from summary carries no key, and Django reads an absent
        # checkbox as False: the card would silently land unnumbered. Restore the
        # new kind's default instead. Fill only an ABSENT key (prefix-safe): a sent
        # value, even "false", is the author's. No cleaned kind means the kind
        # failed choice validation -- skip, and let the field error give the 422.
        if (
            new_kind is not None
            and self.original_kind == CalloutElement.Kind.SUMMARY
            and new_kind != CalloutElement.Kind.SUMMARY
            and self.add_prefix("numbered") not in self.data
        ):
            cleaned_data["numbered"] = KIND_DEFAULT_NUMBERED[new_kind]
        return cleaned_data
```

- [ ] **Step 5: Implement the template wrap**

In `templates/courses/manage/editor/_edit_callout.html`, replace the checkbox `<label class="el-editor__check">…</label>` block with:

```django
  {% comment %}
  Not rendered for a saved summary card (W skrócie / Key facts): summary is never
  numbered (D5), save() forces False and the server ignores the box. The test is
  form.original_kind -- the kind the row had when the form was built -- and never
  form.instance.kind or form.kind.value: on a 422 re-render, construct_instance
  has already copied the POSTed kind onto form.instance. No JS toggles this when
  the select changes, deliberately: switching Example to W skrócie leaves the box
  visible until the next save, which is harmless (save() forces False) and the
  re-render hides it. Do not "fix" that with JS.
  {% endcomment %}
  {% if form.original_kind != "summary" %}
  <label class="el-editor__check">
    <input type="checkbox" name="numbered" {% if form.numbered.value %}checked{% endif %}>
    {% trans "Number this callout" %}
  </label>
  {% endif %}
```

The `<input>` line is byte-identical to today's. `test_the_editor_partial_renders_the_checkbox` and `test_an_unnumbered_instance_renders_the_box_unchecked` depend on that.

- [ ] **Step 6: Rewrite the four stale texts**

In `courses/models.py`, replace the `numbered` field comment:

```python
    # A FLAT default, deliberately not per-kind: a field default cannot vary by kind.
    # The per-kind map (KIND_DEFAULT_NUMBERED, below the class) is read by the
    # backfill migration (as a frozen literal), by the importer's pre-v13 fallback,
    # and by CalloutElementForm.clean() when a card is switched AWAY from summary --
    # never as a form initial. save() forces False for summary. No `blank=True`
    # -- models.BooleanField.formfield hard-codes required=False, because an unchecked
    # checkbox transmits nothing.
    numbered = models.BooleanField(default=True)
```

Replace the `KIND_DEFAULT_NUMBERED` comment:

```python
# Per-kind numbering defaults. Built after the class body for the same reason as
# KIND_DEFAULT_HEADING: it reads the enum. Two runtime readers: the importer's
# default for pre-v13 archives (courses/transfer/payloads.py), and
# CalloutElementForm.clean(), which restores the NEW kind's default when a card
# leaves summary (the summary form renders no checkbox, so that POST carries no
# `numbered`). The backfill migration encodes the same decision as a frozen literal,
# never an import. Still NOT a form initial: a new callout is always created as
# `example`, whose default equals the flat model default, so an initial would be
# unobservable and untestable.
```

In `courses/tests/test_callout_numbering.py`, replace the docstring of `test_model_default_is_a_flat_true_regardless_of_kind`:

```python
    """The model default is a flat True for every kind. The per-kind map is read
    only by backfill, legacy import, and CalloutElementForm.clean() when a card
    leaves summary. A form INITIAL is still forbidden: an author-created Note is
    born numbered; the author unticks. Mutant: add a per-kind form/model initial
    -> this fails, which is the point (see spec section 1)."""
```

- [ ] **Step 7: Run the tests and confirm they PASS**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_authoring.py courses/tests/test_callout_form.py courses/tests/test_callout_numbering_render.py courses/tests/test_callout_numbering.py
```

Expected: all passed.

- [ ] **Step 8: FALSIFY**

| Mutant (hand-edit) | Run | Expected RED |
|---|---|---|
| T7: delete the `{% if form.original_kind != "summary" %}` and its `{% endif %}` | `courses/tests/test_callout_authoring.py::test_the_summary_edit_form_has_no_numbered_checkbox` | `name="numbered"` found |
| T7: invert to `{% if form.original_kind == "summary" %}` | `...::test_the_example_edit_form_keeps_the_numbered_checkbox` and `...::test_a_new_callout_still_renders_and_saves_the_checkbox` | not found |
| T7b/T7c: delete the whole `if (...): cleaned_data["numbered"] = ...` statement in `clean()` | `...::test_leaving_summary_for_example_restores_numbered` and `courses/tests/test_callout_form.py::test_leaving_summary_restores_the_new_kinds_numbered_default` | `False is True` |
| T7b: replace `KIND_DEFAULT_NUMBERED[new_kind]` with `True` | `...::test_leaving_summary_for_note_restores_unnumbered` | `True is False` |
| T7b: delete the line `and self.original_kind == CalloutElement.Kind.SUMMARY` (restore applies unconditionally) | `...::test_an_unticked_example_stays_unnumbered` | `True is False` |
| T7b/T7c: delete the line `and self.add_prefix("numbered") not in self.data` | `...::test_a_sent_numbered_value_is_not_overridden_when_leaving_summary` and `test_callout_form.py::test_a_sent_false_is_never_overridden` | `True is False` |
| prefix: replace `self.add_prefix("numbered")` with `"numbered"` | `test_callout_form.py::test_the_key_presence_check_is_prefix_safe` | `True is False` |
| T7b: change the template condition to `{% if form.instance.kind != "summary" %}` | `...::test_a_422_after_asking_for_summary_still_shows_the_checkbox` | `name="numbered"` not in the 422 body |
| T7c (lazy): delete `self.original_kind = self.instance.kind` from `__init__` and add to the class `@property` / `def original_kind(self): return self.instance.kind` | `test_callout_form.py::test_original_kind_is_read_before_validation_mutates_the_instance` | `'example' == 'summary'` |
| RF1: in `courses/models.py`, delete `self.numbered = False` from `save()` | `...::test_switching_a_ticked_example_to_summary_unnumbers_it_and_hides_the_box` | `True is False` |

Remove each mutant by editing. Then run `git diff --stat` (only this task's six files) and re-run Step 7: expected all passed.

- [ ] **Step 9: Lint and commit**

```
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/element_forms.py templates/courses/manage/editor/_edit_callout.html courses/models.py courses/tests/test_callout_authoring.py courses/tests/test_callout_form.py courses/tests/test_callout_numbering.py
git commit -m "$(cat <<'EOF'
feat(callout): hide the numbered box for summary; restore it on leaving

CalloutElementForm.original_kind is read once in __init__, before
construct_instance can overwrite the instance; the partial keys on it.
clean() restores KIND_DEFAULT_NUMBERED[new_kind] when a card leaves
summary and no `numbered` key was sent (prefix-safe). Stale comments on
the map's readers updated.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

---

### Task 6: Transfer and duplicate coverage

**Files:**
- Test: `courses/tests/test_callout_transfer.py` (T8, Review Focus 4)

There are no source changes. `_val_callout`, `_ser_callout` and `_build_callout` are data-driven off the enum and the map (spec §3.6). These tests are guards: they PASS on arrival because Task 1 already landed. Their value is proved in Step 3 by falsifying them.

**Interfaces:**
- Consumes: `CalloutElement.Kind.SUMMARY`, `KIND_DEFAULT_NUMBERED["summary"]`, `save()` force (Task 1).
- Produces: nothing new.

- [ ] **Step 1: Write the tests**

In `courses/tests/test_callout_transfer.py`, extend the loop in `test_a_pre_v13_payload_imports_with_the_per_kind_default`. It asserts on the VALIDATED payload, because the saved row would be masked by `save()`'s force:

```python
    for kind, expected in (
        ("example", True),
        ("note", False),
        ("tip", False),
        ("summary", False),
    ):
        data = {"kind": kind, "heading": "", "body": "<p>x</p>"}
        VALIDATORS["callout"](data, "e1", set())
        assert data["numbered"] is expected
```

Append:

```python
@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_round_trip_preserves_the_summary_kind_unnumbered():
    """T8."""
    el = CalloutElement.objects.create(
        kind="summary", heading="Funkcja liniowa", body="<p>hi</p>"
    )
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):  # unused by callout
            return None

    data = ser(el, _Ids())
    assert data == {
        "kind": "summary",
        "heading": "Funkcja liniowa",
        "body": "<p>hi</p>",
        "numbered": False,
    }
    VALIDATORS["callout"](data, "e1", set())
    rebuilt, _refs = BUILDERS["callout"](data, {})
    rebuilt.refresh_from_db()
    assert rebuilt.kind == "summary"
    assert rebuilt.heading == "Funkcja liniowa"
    assert "hi" in rebuilt.body
    assert rebuilt.numbered is False


@pytest.mark.django_db  # _clean_save writes to the DB
def test_a_hand_edited_numbered_summary_imports_unnumbered():
    """This build never exports numbered=True for a summary, but a hand-edited
    archive can carry it; save() forces False (spec 3.6)."""
    data = {"kind": "summary", "heading": "", "body": "<p>x</p>", "numbered": True}
    VALIDATORS["callout"](data, "e1", set())
    concrete, _media = BUILDERS["callout"](data, {})
    concrete.refresh_from_db()
    assert concrete.numbered is False


@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_exporting_a_summary_card_keeps_format_version_16():
    """T8 / D7: a new kind never changes an existing payload shape."""
    from courses.transfer import export as _export
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    add_element(unit, CalloutElement.objects.create(kind="summary", body="<p>x</p>"))
    manifest, document, _media, _problems = _export.build_export(course)
    assert manifest["format_version"] == 16
    callout = next(e for e in document["elements"] if e["type"] == "callout")
    assert callout["data"]["kind"] == "summary"


@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_duplicating_a_summary_card_keeps_it_an_unnumbered_summary():
    """Review Focus 4. Duplicate/paste run build_element_export -> graft_elements,
    which runs NO validator."""
    from courses import builder
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(
        kind="summary", heading="Procenty", body="<p>x</p>"
    )
    join = add_element(unit, el)
    unit.refresh_from_db()

    _unit, new_join = builder.duplicate_element(
        course, join.pk, unit.updated.isoformat()
    )
    copy = new_join.content_object
    assert copy.pk != el.pk
    assert copy.kind == "summary"
    assert copy.heading == "Procenty"
    assert copy.numbered is False
```

- [ ] **Step 2: Run the tests and confirm they PASS**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_transfer.py courses/tests/test_beforeafter_transfer.py
```

Expected: all passed. `test_format_version_is_pinned` still pins 16.

- [ ] **Step 3: FALSIFY**

| Mutant (hand-edit) | Run | Expected RED |
|---|---|---|
| T8: in `courses/models.py`, delete the `CalloutElement.Kind.SUMMARY.value: False,` line from `KIND_DEFAULT_NUMBERED` | `courses/tests/test_callout_transfer.py::test_a_pre_v13_payload_imports_with_the_per_kind_default` | `True is False` for summary (`.get(_kind, True)`) |
| T8: in `courses/models.py` `save()`, delete `self.numbered = False` | `...::test_a_hand_edited_numbered_summary_imports_unnumbered` | `True is False` |
| T8: in `courses/transfer/export.py` `_ser_callout`, emit `"kind": "example"` instead of the instance's kind | `...::test_round_trip_preserves_the_summary_kind_unnumbered` and `...::test_duplicating_a_summary_card_keeps_it_an_unnumbered_summary` | dict / kind mismatch |
| RF4: in `courses/transfer/importer.py` `_build_callout`, `kind=data.get("kind", "example")` → `kind="example"` | `...::test_duplicating_a_summary_card_keeps_it_an_unnumbered_summary` | `'example' == 'summary'` |
| D7: in `courses/transfer/schema.py`, `FORMAT_VERSION = 17` | `...::test_exporting_a_summary_card_keeps_format_version_16` | `17 == 16` |

Before applying the `_ser_callout` mutant, open `_ser_callout` in `courses/transfer/export.py` and edit its `kind` entry.

Remove each mutant by editing. Then run `git diff --stat` (only `courses/tests/test_callout_transfer.py`) and re-run Step 2: expected all passed.

- [ ] **Step 4: Lint and commit**

```
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/tests/test_callout_transfer.py
git commit -m "$(cat <<'EOF'
test(callout): summary transfer, legacy default, duplicate, format 16

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

---

### Task 7: Catalogs and help manual

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`, `locale/en/LC_MESSAGES/django.po`
- Modify: `docs/help/course-admin/content-editors.md`, `docs/help/course-admin/content-editors.pl.md`
- Create: `tests/test_i18n_callout_summary.py` (T12)
- Test: `tests/test_help.py` (T13)

**Interfaces:**
- Consumes: the `_("Key facts")` msgid (Task 1) and the editor behaviour (Task 5) that the docs describe.
- Produces: pl `msgstr "W skrócie"`; one live, empty en `msgid "Key facts"` entry; the help wording.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_i18n_callout_summary.py`:

```python
"""Pins the Polish label and the English catalog entry for the summary callout kind
("Key facts" / "W skrócie"). Sibling of test_i18n_callout_task.py.

No django_db mark: the CalloutElement is never saved.
"""

from django.utils import translation

from courses.models import CalloutElement
from tests.test_i18n_po_health import EN_PO
from tests.test_i18n_po_health import PL_PO
from tests.test_i18n_po_health import _entries


def test_summary_kind_renders_w_skrocie_in_polish():
    # override(), NOT activate(): a bare activate leaks the language into every
    # later test in this xdist worker. Reads the COMPILED .mo, so a fuzzy or empty
    # msgstr falls back to "Key facts" here.
    with translation.override("pl"):
        assert str(CalloutElement(kind="summary").display_heading) == "W skrócie"


def test_pl_catalog_entry_is_live_and_translated():
    matches = [
        e for e in _entries(PL_PO) if e["msgid"] == "Key facts" and not e["obsolete"]
    ]
    assert len(matches) == 1, "expected exactly one live `Key facts` entry in pl"
    assert not matches[0]["fuzzy"], "the pl `Key facts` entry is fuzzy"
    assert matches[0]["msgstrs"] == ["W skrócie"]


def test_en_catalog_has_the_key_facts_msgid():
    # _entries() RETAINS obsolete entries with a flag, so the filter is what makes
    # "live" true; a commented-out `#~ msgid "Key facts"` must not count.
    matches = [
        e for e in _entries(EN_PO) if e["msgid"] == "Key facts" and not e["obsolete"]
    ]
    assert len(matches) == 1, "expected exactly one live `Key facts` entry in locale/en"
    assert matches[0]["msgstrs"] == [""], "the en catalog entry must stay empty"
```

Append to `tests/test_help.py`:

```python
@pytest.mark.parametrize(
    "rel, needles",
    [
        (
            "help/course-admin/content-editors.md",
            ("Task, or Key facts", "never numbered", "Columns", "H4"),
        ),
        (
            "help/course-admin/content-editors.pl.md",
            ("Zadanie lub W skrócie", "nigdy nie jest numerowana", "Kolumny", "H4"),
        ),
    ],
)
def test_the_callout_entry_documents_the_summary_kind(rel, needles):
    """T13. Checked INSIDE the {el:callout} paragraph as _EL_PARA_RE matches it, on
    the same markdown render core.help uses (before its icon pass rewrites the
    paragraph). The last needles come from the paragraph's LAST sentences, so a
    stray blank line that splits the paragraph turns this red."""
    import markdown

    text = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["fenced_code", "tables"])
    paras = {m.group(1): m.group(2) for m in core_help._EL_PARA_RE.finditer(html)}
    assert "callout" in paras, f"{rel}: no {{el:callout}} paragraph"
    body = " ".join(paras["callout"].split())
    for needle in needles:
        assert needle in body, f"{rel}: callout paragraph lacks {needle!r}"
```

- [ ] **Step 2: Run the tests and confirm they FAIL**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_i18n_callout_summary.py tests/test_help.py
```

Expected failures:
- `'Key facts' == 'W skrócie'`.
- `expected exactly one live 'Key facts' entry` (pl and en).
- `callout paragraph lacks 'Task, or Key facts'` / `'Zadanie lub W skrócie'`.

- [ ] **Step 3: Update the catalogs**

```
uv run python manage.py makemessages -l pl -l en
```

In `locale/pl/LC_MESSAGES/django.po`, find the new `msgid "Key facts"` entry, which carries the `courses\models.py` reference, and set:

```
msgid "Key facts"
msgstr "W skrócie"
```

If makemessages pre-filled it as fuzzy, delete BOTH the `#, fuzzy` line and the `#| msgid "…"` line, and replace the msgstr. In `locale/en/LC_MESSAGES/django.po`, the entry must read `msgstr ""`. If it was pre-filled as fuzzy there, delete both lines and empty the msgstr.

Then check that no other entry became fuzzy or obsolete in this run:

```
grep -n "#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
grep -n "^#~" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
```

Expected: no output from either, or only the header's `#, fuzzy` if it was there before (compare with `git diff`). Then compile:

```
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 4: Update the help docs**

In `docs/help/course-admin/content-editors.md`, replace the whole `{el:callout}` paragraph. It must stay ONE paragraph with no blank line inside:

```markdown
{el:callout} **Callout** — a framed, always-visible aside for a note that should stand out
from the surrounding text. Choose a **Kind** (Example, Note, Tip, Important, Task, or
Key facts — each with its own accent colour and icon, except Key facts, which shows its
accent colour as a bar across the top and has no icon), an optional **Heading** (falls
back to a default per kind when left blank), a **Number this callout** checkbox (on
by default; callouts numbered this way share one running sequence per unit,
and Notes and Tips in existing content start unnumbered; Key facts is never
numbered, so a saved Key facts callout has no checkbox), and rich-text body
content. A callout is also a container: it can hold nested elements added
below the body from its own **Add element** menu — see "Containers and
nesting" below for what can go inside. Key facts is meant for summary units:
add one card per topic, with the topic name as its **Heading** — a blank heading
shows the generic "Key facts", and several of those make a run of identical
headings. Two cards can sit side by side inside **Columns**. Inside a card, use
H4 or bold text for sub-points rather than H2 or H3, which would look bigger than
the card's title.
```

In `docs/help/course-admin/content-editors.pl.md`, replace the whole `{el:callout}` paragraph. It must stay ONE paragraph. "Kolumny" is the name this file already uses for the container:

```markdown
{el:callout} **Ramka** — zawsze widoczna, oprawiona wstawka na notatkę, która ma się
wyróżnić na tle otaczającego tekstu. Wybierz **Rodzaj** (Przykład, Notatka,
Wskazówka, Ważne, Zadanie lub W skrócie — każdy z własnym kolorem akcentu i ikoną,
z wyjątkiem W skrócie, które pokazuje swój kolor akcentu jako pasek u góry i nie
ma ikony), opcjonalny **Nagłówek** (jeśli pozostawiony pusty, używany jest domyślny
nagłówek dla danego rodzaju), pole wyboru **Numeruj tę ramkę** (domyślnie
zaznaczone; ramki numerowane w ten sposób mają wspólną numerację w obrębie
jednostki, a Notatki i Wskazówki w istniejącej treści pozostają nienumerowane;
ramka W skrócie nigdy nie jest numerowana, więc zapisana ramka W skrócie nie ma
tego pola) oraz treść w tekście sformatowanym. Ramka jest też kontenerem: może
zawierać zagnieżdżone elementy dodawane poniżej treści z jej własnego menu
**Dodaj element** — zobacz „Kontenery i zagnieżdżanie” poniżej, co można w niej
umieścić. Rodzaj W skrócie jest przeznaczony do jednostek podsumowujących: dodaj
jedną ramkę na każdy temat, z nazwą tematu jako **Nagłówkiem** — pusty nagłówek
pokazuje ogólne „W skrócie”, a kilka takich daje ciąg identycznych nagłówków. Dwie
ramki można ustawić obok siebie w kontenerze **Kolumny**. Wewnątrz ramki do
podpunktów używaj H4 lub pogrubienia zamiast H2 czy H3, które wyglądałyby na
większe niż tytuł ramki.
```

- [ ] **Step 5: Run the tests and confirm they PASS**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_i18n_callout_summary.py tests/test_i18n_callout_task.py tests/test_i18n_po_health.py tests/test_help.py
```

Expected: all passed, including `test_pl_icon_sequence_matches_en`, `test_polish_file_is_not_an_english_copy` and the no-fuzzy and no-obsolete guards.

- [ ] **Step 6: FALSIFY**

| Mutant (hand-edit) | Run | Expected RED |
|---|---|---|
| T12: pl `msgstr "W skrócie"` → `msgstr ""`, then `uv run python manage.py compilemessages -l pl` | `tests/test_i18n_callout_summary.py` | `'Key facts' == 'W skrócie'` and the msgstrs assertion |
| T12: restore the msgstr and add a `#, fuzzy` line above the pl entry, then recompile | same | fuzzy assertion, plus the runtime test (compilemessages skips fuzzy) |
| T12: delete the en `msgid "Key facts"` / `msgstr ""` entry | `tests/test_i18n_callout_summary.py::test_en_catalog_has_the_key_facts_msgid` | `expected exactly one live` |
| T12: duplicate the en entry with a different reference comment | same | `expected exactly one live` |
| T13: revert the en paragraph's kind list to `(Example, Note, Tip, Important, or Task —` | `tests/test_help.py::test_the_callout_entry_documents_the_summary_kind` | `lacks 'Task, or Key facts'` |
| T13: insert a blank line before `Key facts is meant for summary units:` in the en doc, and before `Rodzaj W skrócie jest` in the pl doc | same | `lacks 'Columns'` / `lacks 'Kolumny'` |

After each `.po` mutant is removed BY EDITING, re-run `uv run python manage.py compilemessages -l pl` so the `.mo` matches the restored `.po`. Then run `git diff --stat` (only this task's files) and re-run Step 5: expected all passed.

- [ ] **Step 7: Lint and commit**

`makemessages` may also churn line references of unrelated entries. Commit the `.po` files whole, but nothing else from `locale/`:

```
uv run ruff check --no-cache .
uv run ruff format --check .
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po docs/help/course-admin/content-editors.md docs/help/course-admin/content-editors.pl.md tests/test_i18n_callout_summary.py tests/test_help.py
git commit -m "$(cat <<'EOF'
i18n(callout): W skrócie label and help wording for the summary kind

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

---

### Task 8: UI verification (light + dark + print) and the branch gate

**Files:**
- Create: `tests/capture_summary_callout_screenshots.py` (an e2e capture script, not an assertion suite; it follows the `tests/capture_*_screenshots.py` convention)
- Create: `docs/superpowers/screenshots/summary-callout-*.png` (new names only; no existing tracked screenshot is overwritten)

The task produces screenshots and a findings list. Production code changes ONLY if one of the capture's sanity assertions or the branch gate fails. Debug such a failure with superpowers:systematic-debugging; do not restyle anything on a hunch. The spec's §3.4 and §6 DoD findings (the bar's rounded corners, how the H4 reads against the title) are REPORTED to the owner, not fixed here.

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: screenshots, plus the findings text and operator note for the PR body.

- [ ] **Step 1: Write the capture script**

Create `tests/capture_summary_callout_screenshots.py`:

```python
"""Produce the images the design pass judges for the "W skrócie" summary card.

Not an assertion suite -- run it on its own:

    TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary \
        uv run pytest tests/capture_summary_callout_screenshots.py -m e2e

Writes NEW file names under docs/superpowers/screenshots/ (override with SHOT_DIR)
and never touches an existing screenshot. The few asserts are sanity checks that
the page is the one being judged (KaTeX ran in the title; the Example after the
cards reads 2, not 3+; print restates the light bar), not the feature's tests.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings

from courses.models import CalloutElement
from courses.models import Element
from courses.models import ImageElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.test_e2e_tabs import _lesson_url
from tests.test_e2e_tabs import _login
from tests.test_e2e_tabs import _make_pa_user
from tests.test_e2e_tabs import _seed_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)

TOPICS = [
    (
        "Funkcja liniowa",
        "<ul><li>Wzór: \\(y = ax + b\\).</li><li>\\(a\\) to współczynnik "
        "kierunkowy, \\(b\\) to wyraz wolny.</li><li>Dla \\(a &gt; 0\\) funkcja "
        "rośnie, dla \\(a &lt; 0\\) maleje.</li></ul>",
    ),
    (
        "Układy równań",
        "<ul><li>Metoda podstawiania.</li><li>Metoda przeciwnych "
        "współczynników.</li><li>Interpretacja: punkt przecięcia "
        "prostych.</li></ul>",
    ),
    (
        "Procenty",
        "<ul><li>\\(p\\%\\) liczby \\(x\\) to \\(\\frac{p}{100}x\\).</li>"
        "<li>Punkt procentowy to różnica procentów.</li></ul>",
    ),
]
WIDE = (
    "<p>Wzór skróconego mnożenia:</p><p>\\[(a+b)^5 = a^5 + 5a^4b + 10a^3b^2 + "
    "10a^2b^3 + 5ab^4 + b^5 \\quad\\text{oraz}\\quad (a-b)^5 = a^5 - 5a^4b + "
    "10a^3b^2 - 10a^2b^3 + 5ab^4 - b^5\\]</p>"
)
HEADINGS_BODY = (
    "<h3>Typed H3 inside the card</h3><p>Compare this with the card title.</p>"
    "<h4>An H4 sub-point</h4><p>It must read as subordinate to the title.</p>"
)


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _card(unit, heading, body="", parent=None, tab_id="", order=0):
    co = CalloutElement.objects.create(kind="summary", heading=heading, body=body)
    return Element.objects.create(
        unit=unit, content_object=co, parent=parent, tab_id=tab_id, order=order
    )


def _seed(course, unit):
    order = 0

    def nxt():
        nonlocal order
        order += 1
        return order

    first = CalloutElement.objects.create(kind="example", numbered=True, body="<p>A</p>")
    Element.objects.create(unit=unit, content_object=first, order=nxt())
    for heading, body in TOPICS:  # three cards stacked
        _card(unit, heading, body, order=nxt())
    cols = TwoColumnElement.objects.create(
        data={"columns": [{"id": "c000001"}, {"id": "c000002"}]}
    )
    cols_join = Element.objects.create(unit=unit, content_object=cols, order=nxt())
    powers = "<p>\\(a^m \\cdot a^n = a^{m+n}\\)</p>"
    roots = "<p>\\(\\sqrt{ab} = \\sqrt a \\sqrt b\\)</p>"
    _card(unit, "Potęgi", powers, cols_join, "c000001")
    _card(unit, "Pierwiastki", roots, cols_join, "c000002")
    fig = _card(unit, "Wykres i wzór", WIDE, order=nxt())
    img = ImageElement.objects.create(
        media=make_image_asset(course, "wykres.png", size=(480, 240), color="#88aacc"),
        alt="Wykres funkcji",
    )
    Element.objects.create(
        unit=unit, content_object=img, parent=fig, tab_id=CalloutElement.SLOT_ID
    )
    _card(unit, "Twierdzenie \\(a^2 + b^2 = c^2\\)", "<p>Pitagoras.</p>", order=nxt())
    _card(unit, "Sam nagłówek", "", order=nxt())  # heading-only card
    _card(unit, "Nagłówki w karcie", HEADINGS_BODY, order=nxt())
    after = CalloutElement.objects.create(kind="example", numbered=True, body="<p>B</p>")
    Element.objects.create(unit=unit, content_object=after, order=nxt())
    # add_element would use order=0 and sort this FIRST; it must render last.
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>Koniec podsumowania.</p>"),
        order=nxt(),
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_summary_cards(page, browser, live_server, theme):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1280, "height": 1000})
    username = f"summary-shot-{theme}"
    user = _make_pa_user(username)
    user.theme = theme  # the user row, NOT the cookie
    user.save()
    course, unit = _seed_unit(user, f"summary-shot-{theme}")
    _seed(course, unit)

    _login(page, live_server, username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("h3.callout__title .katex")  # math.js typeset the title

    numbers = page.locator(".callout--example .callout__number").all_inner_texts()
    assert numbers == ["1", "2"], f"cards shifted the Example numbers: {numbers}"

    page.screenshot(path=str(OUT_DIR / f"summary-callout-{theme}-page.png"), full_page=True)
    cards = page.locator(".callout--summary")
    for i, name in enumerate(
        ["stack-1", "stack-2", "stack-3", "col-left", "col-right", "figure-wide",
         "math-heading", "heading-only", "h3-h4"]
    ):
        cards.nth(i).screenshot(path=str(OUT_DIR / f"summary-callout-{theme}-{name}.png"))
    page.locator(".el--twocolumn").first.screenshot(
        path=str(OUT_DIR / f"summary-callout-{theme}-columns.png")
    )

    # Bar corners at zoom: the 3px top border meets the 1px sides on the radius.
    zoom = browser.new_page(device_scale_factor=4, viewport={"width": 1280, "height": 1000})
    _login(zoom, live_server, username)
    zoom.goto(_lesson_url(live_server, unit))
    zoom.wait_for_selector(".callout--summary")
    box = zoom.locator(".callout--summary").first.bounding_box()
    for side, x in (("left", box["x"] - 4), ("right", box["x"] + box["width"] - 36)):
        zoom.screenshot(
            path=str(OUT_DIR / f"summary-callout-{theme}-corner-{side}.png"),
            clip={"x": x, "y": box["y"] - 4, "width": 40, "height": 24},
        )
    zoom.close()

    if theme == "dark":
        # Print in the dark theme restates the LIGHT bar colour (#4b6b8a).
        page.emulate_media(media="print")
        colour = page.locator(".callout--summary").first.evaluate(
            "el => getComputedStyle(el).borderTopColor"
        )
        assert colour == "rgb(75, 107, 138)", f"print bar is {colour}"
        cards.first.screenshot(path=str(OUT_DIR / "summary-callout-dark-print.png"))
```

- [ ] **Step 2: Run the capture**

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/capture_summary_callout_screenshots.py -m e2e
```

Expected: `2 passed`. If a sanity assertion fails, treat it as a bug in Tasks 1–7. Debug it, fix it in the owning file with a red-then-green test in that task's test module, and commit that fix separately. Ruff-check the script: `uv run ruff check --no-cache tests/capture_summary_callout_screenshots.py` and `uv run ruff format --check tests/capture_summary_callout_screenshots.py`. If the formatter wants changes, run `uv run ruff format tests/capture_summary_callout_screenshots.py`.

- [ ] **Step 3: Judge the screenshots (light, then dark separately) and write the findings**

Open every `summary-callout-*.png` with the Read tool and check each item of the spec §6 DoD:
1. Three cards stack full width, flat, white or raised, with no tint, no shadow and no icon.
2. Two cards sit side by side inside the two-column element.
3. The card with a figure and a wide display formula: the formula scrolls inside the card and the card is not clipped.
4. The heading with inline maths: the KaTeX is the title's size, not larger.
5. The heading-only card has no extra bottom space.
6. The typed H3 and the H4 sit next to the card title. Does the H4 read as subordinate to the 1.05rem title? If not, record it as a FINDING; do not restyle h4.
7. The Example after the cards shows "2", unshifted.
8. The corner crops: how does the 3px bar meet the 1px sides on the radius? If it reads badly, record it as a FINDING; do not change the drawing method.
9. Dark: the slate bar is legible on the dark ground and the title text is readable.
10. `summary-callout-dark-print.png`: the bar shows the light slate.

Write the findings as a short list to include in the PR body, together with:
- The dark accent value chosen: `#9db4cb`. It measures 6.77:1 on `--surface-raised` and 8.28:1 on `--surface-base`.
- The operator note, VERBATIM: *Deploy this build to libli.pl before authoring a W skrócie card; an archive that contains one is refused ("unknown callout kind") by any instance still running a build without the `SUMMARY` enum member. The gate is the deployed code, not the migration. Before importing an archive with W skrócie cards into any other instance (for example a school box on a tagged release), confirm that instance runs a release containing this feature.*

- [ ] **Step 4: Commit the capture script and screenshots**

```
git status --short docs/superpowers/screenshots
git add tests/capture_summary_callout_screenshots.py docs/superpowers/screenshots/summary-callout-*.png
git commit -m "$(cat <<'EOF'
test(callout): capture light/dark/print screenshots of the summary card

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JQepuSpsygGPchKAXdXCfc
EOF
)"
```

`git status` must show ONLY new `summary-callout-*.png` files. If any other screenshot shows as modified, the script overwrote a tracked file. Restore that one binary with `git checkout -- <that .png path>`. That is safe because a PNG never holds uncommitted work of ours; the no-`git checkout` rule protects text files carrying edits. Then fix the script's output name and investigate.

- [ ] **Step 5: The spec's run scope, then the branch gate**

Spec run scope (callout, numbering, transfer, i18n, help, every CSS test, migrations):

```
uv run python manage.py makemigrations --check --dry-run
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests/test_callout_model.py courses/tests/test_callout_numbering.py courses/tests/test_callout_numbering_render.py courses/tests/test_callout_render.py courses/tests/test_callout_authoring.py courses/tests/test_callout_form.py courses/tests/test_callout_transfer.py courses/tests/test_math_selectors.py courses/tests/test_beforeafter_transfer.py tests/test_i18n_callout_summary.py tests/test_i18n_callout_task.py tests/test_i18n_po_health.py tests/test_help.py tests/test_*css*.py courses/tests/test_*css*.py
```

Then run the existing callout e2e suites, because the template and form changed:

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_e2e_callout_container.py tests/test_e2e_callout_numbering.py tests/test_e2e_callout_body_row.py tests/test_e2e_print_foundations.py -m e2e -n 2
```

Branch gate: the whole repo in five chunks, covering every test directory (`courses/tests`, `integrations/tests`, `notifications/tests`, top-level `tests/test_*.py`, `tests/demo`, `tests/lal_import`), one at a time, never two concurrently. Read each summary line:

```
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest courses/tests integrations/tests notifications/tests -n 4
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_[a-f]*.py -n 4
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_[g-p]*.py -n 4
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/test_[q-z]*.py -n 4
TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary uv run pytest tests/demo tests/lal_import -n 4
uv run ruff check --no-cache .
uv run ruff format --check .
```

Expected: every chunk reports `passed` with 0 failed and 0 errors. Both ruff gates are clean. If a failure is in a file this branch did not touch, re-run that file alone before believing it: parallel-load flakes are known. A/B against master before blaming the diff.
