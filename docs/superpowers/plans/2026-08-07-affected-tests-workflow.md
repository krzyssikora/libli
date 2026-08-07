# Affected-tests workflow (Part B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `scripts/affected_tests.py` — an advisory tool that maps a diff to the pytest commands worth running locally — plus its tests and the documented practice that tells a developer when to trust it.

**Architecture:** One module under `scripts/`, split internally into a **pure core** (`normalize_name_status`, `map_paths`, `render_commands`) that performs no I/O, and a **CLI wrapper** that owns every git and filesystem access and injects two callables (`search`, `module_symbols`) into the core. The purity boundary exists so the mapping rules are tested against literal stubs rather than a fixture repository; only the wrapper needs a real repo. Tests live at `tests/test_affected_tests.py` because `scripts/` sits outside every test directory and `pyproject.toml` sets no `testpaths`, so that path is what guarantees collection by the existing configuration.

**Tech Stack:** Python 3.13, stdlib only (`argparse`, `subprocess`, `fnmatch`, `re`, `ast`, `dataclasses`, `enum`, `pathlib.PurePosixPath`). pytest + pytest-django for the tests. No new dependencies.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec (`docs/superpowers/specs/2026-08-07-test-suite-wall-clock-design.md` §4) or measured against this working tree at `00f1e03b`.

- **The tool is advisory, never authoritative.** CI's full suite remains the gate. Bias every undecidable case toward visibility (report as `unmapped`), never toward silent omission.
- **Corpus is built from `git ls-files`, never a filesystem walk.** MEASURED at `00f1e03b`: 3,197 files on disk match `test_*.py`; only **647** are tracked. The other 2,534 live in nested worktrees under `.claude/worktrees/`.
- **Unit/e2e classification is NON-exclusive.** A file may appear in both selections. `tests/test_tabs_editor_dnd.py` collects **10 non-e2e and 2 e2e** tests (measured); an "iff" rule strands the 10.
- **An empty candidate list emits NO command** for that selection, and prints `no <unit|e2e> tests mapped; see unmapped`.
- **The emitted e2e command always carries `-m e2e`.**
- **Both emitted commands carry the note that exit code 5 means "nothing selected", not "green".** MEASURED: `tests/test_link_apply.py` (29), `test_link_dialog_behaviour.py` (32) and `test_table_grid_algebra.py` (38) collect **zero** non-e2e tests, so a diff touching only those yields a unit command that is entirely deselected.
- **"A test file" means the basename matches `python_files` = `test_*.py`**, not "lives in a test directory". `tests/capture_help_screenshots.py` is deliberately not collectible.
- **Breadth caps, per selection, independent:** unit **40**, e2e **15**.
- **Diff range is merge-base with `origin/master`** (not local `master`, routinely stale in a worktree). `--base` overrides. A missing ref is a hard error, never a silent empty diff.
- **ruff config applies to `scripts/`** — `select = ["E", "F", "I", "UP", "B", "S"]`, `isort.force-single-line = true`. `subprocess` calls need `# noqa: S603 -- <reason>`; the precedent is `tests/test_help_capture_isolation.py:19`.
- **Comments explaining a non-obvious choice are prefixed `MEASURED:`** when they record an observation, matching `conftest.py` and `scripts/build_favicons.py`.
- **Never run the full suite to check this work.** Run the named test file only.

### Deviation from the spec, already decided

- **`migration_models` is cut.** Migrations map to the fixed `tests/test_transfer*.py` glob only; the model-name half of the rule and its injected dependency are dropped. Rationale (measured): of the last 200 commits, exactly **one** touches a migration, and it touched `models.py` in the same commit, so the module rule already covered it.
- **`module_symbols` is added in its place**, keeping arity at three. The spec's own justification for injecting `migration_models` ("absent from the corpus, and `paths: list[str]` carries no content") applies verbatim to the module rule's *"or its module-level public defs/classes"*: a changed source module is equally absent from the corpus. Without this seam the module rule is unimplementable under the stated purity constraint.

### Final interface

```python
normalize_name_status(lines: list[str]) -> list[str]
map_paths(
    paths: list[str],
    search: Callable[[str], set[str]],
    module_symbols: Callable[[str], set[str]],
) -> Result
render_commands(result: Result) -> str
```

`search(term)` returns the corpus files containing `term` **on a word boundary**. `module_symbols(path)` returns the module-level public defs and classes of a Python source path (empty set if unreadable or unparseable).

---

## File Structure

| File | Responsibility |
|---|---|
| Create `scripts/affected_tests.py` | The whole tool. Pure core + CLI wrapper in one module, matching `scripts/build_favicons.py`'s single-file convention. |
| Create `tests/test_affected_tests.py` | B3. Stub-based unit tests for the core; one fixture-repo integration test for the wrapper. |
| Modify `docs/development/testing.md` | B1. Adds the affected-tests practice section. Part A already shipped the branch-gate, never-twice, one-run-at-a-time and troubleshooting content. |

---

## Task 1: `normalize_name_status` and the test-file predicate

**Files:**
- Create: `scripts/affected_tests.py`
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_test_file(path: str) -> bool`; `normalize_name_status(lines: list[str]) -> list[str]`; constant `PYTHON_FILES_GLOB = "test_*.py"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_affected_tests.py`:

```python
"""Tests for scripts/affected_tests.py.

Located here, not under scripts/, because `scripts/` sits outside every test
directory and pyproject.toml sets no `testpaths` -- this path is what guarantees
the existing configuration collects them.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "affected_tests.py"
_spec = importlib.util.spec_from_file_location("affected_tests", _MODULE_PATH)
affected_tests = importlib.util.module_from_spec(_spec)
sys.modules["affected_tests"] = affected_tests
_spec.loader.exec_module(affected_tests)

is_test_file = affected_tests.is_test_file
normalize_name_status = affected_tests.normalize_name_status


class TestIsTestFile:
    def test_matches_the_configured_python_files_pattern(self):
        assert is_test_file("tests/test_thing.py")
        assert is_test_file("courses/tests/test_thing.py")

    def test_a_test_named_helper_that_pytest_does_not_collect_is_not_a_test_file(self):
        # `python_files = ["test_*.py"]` matches the BASENAME. This file sits in
        # tests/ and defines test_-named functions but is deliberately not
        # collectible; mapping it to itself would emit a command that exits 5.
        assert not is_test_file("tests/capture_help_screenshots.py")

    def test_a_source_module_is_not_a_test_file(self):
        assert not is_test_file("courses/models.py")


class TestNormalizeNameStatus:
    def test_addition_and_modification_pass_through(self):
        assert normalize_name_status(["A\tcourses/a.py", "M\tcourses/b.py"]) == [
            "courses/a.py",
            "courses/b.py",
        ]

    def test_rename_follows_to_the_new_path(self):
        assert normalize_name_status(["R100\tcourses/old.py\tcourses/new.py"]) == [
            "courses/new.py"
        ]

    def test_copy_follows_to_the_new_path(self):
        assert normalize_name_status(["C075\tcourses/src.py\tcourses/copy.py"]) == [
            "courses/copy.py"
        ]

    def test_a_deleted_test_file_is_dropped(self):
        # It would map to "itself" and emit an unrunnable command that errors at
        # collection.
        assert normalize_name_status(["D\ttests/test_gone.py"]) == []

    def test_a_deleted_source_file_is_retained(self):
        # A deleted view/model/template is a HIGH blast-radius change; its
        # referencing tests must still be selected.
        assert normalize_name_status(["D\tcourses/views.py"]) == ["courses/views.py"]

    def test_blank_and_malformed_lines_are_ignored(self):
        assert normalize_name_status(["", "   ", "M", "M\tcourses/a.py"]) == [
            "courses/a.py"
        ]

    def test_duplicates_collapse_preserving_first_order(self):
        assert normalize_name_status(["M\ta.py", "M\tb.py", "M\ta.py"]) == [
            "a.py",
            "b.py",
        ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /c/Users/krzys/Documents/Python/own/libli/.claude/worktrees/affected-tests && uv run pytest tests/test_affected_tests.py -v`

Expected: collection error — `FileNotFoundError` / `spec_from_file_location` returns None, because `scripts/affected_tests.py` does not exist.

- [ ] **Step 3: Create the module with the docstring and these two functions**

Create `scripts/affected_tests.py`:

```python
"""Suggest the pytest commands worth running for a diff. Advisory, never authoritative.

    uv run python scripts/affected_tests.py              # vs origin/master
    uv run python scripts/affected_tests.py --base HEAD~3

CI's full suite stays the gate; this only decides what is worth running locally
while iterating. It is deliberately biased toward visibility: a path no rule can
decide is reported as unmapped rather than dropped.

Three structural decisions, each measured, each wrong in an earlier draft:

* The corpus comes from `git ls-files`, NEVER a filesystem walk. MEASURED: this
  working tree holds 3,197 files matching `test_*.py`, of which only 647 are
  real -- the other 2,534 live in nested git worktrees under `.claude/worktrees/`.
  They are gitignored and pytest skips them via `norecursedirs`, but a walk sees
  roughly five phantoms per real file and emits node IDs pointing into another
  branch.

* Unit/e2e classification is NON-exclusive -- a file may be suggested in both
  commands. MEASURED: `tests/test_tabs_editor_dnd.py` collects 10 non-e2e tests
  and 2 e2e ones. Classifying it "e2e" puts it only in the `-m e2e` command,
  where the other 10 are deselected: selected nowhere, silently.

* An empty candidate list emits NO command. Interpolating an empty file list
  yields a bare `uv run pytest` -- the whole 5,133-test unit selection, silently,
  for a diff that mapped nothing.

Purity: `normalize_name_status`, `map_paths` and `render_commands` do no I/O.
Everything touching git or the filesystem lives in the wrapper at the bottom and
reaches the core through the `search` and `module_symbols` callables, so the
rules are testable against literal stubs instead of a fixture repository.
"""

import fnmatch
from pathlib import PurePosixPath

# Mirrors `python_files` in pyproject.toml's [tool.pytest.ini_options]. pytest
# matches this against the BASENAME, which is the whole point of the predicate
# below: "lives in tests/" is not the same rule and gets
# tests/capture_help_screenshots.py wrong.
PYTHON_FILES_GLOB = "test_*.py"


def is_test_file(path: str) -> bool:
    """Whether pytest would collect `path` as a test module."""
    return fnmatch.fnmatch(PurePosixPath(path).name, PYTHON_FILES_GLOB)


def normalize_name_status(lines: list[str]) -> list[str]:
    """Turn raw `git diff --name-status` output into a de-duplicated path list.

    Renames and copies follow to the NEW path. Deletions are dropped ONLY when
    the deleted path is a test file: a deleted test mapped to "itself" emits an
    unrunnable command that errors at collection, but a deleted SOURCE file is a
    high-blast-radius change whose referencing tests must still be selected, so
    it flows through the normal per-path rules.

    Pure, and deliberately separate from `map_paths`: a bare `list[str]` carries
    no status codes, so this decision cannot be made downstream.
    """
    out: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0][:1]
        if code in {"R", "C"}:
            if len(parts) < 3:
                continue
            path = parts[2]
        else:
            path = parts[1]
        if code == "D" and is_test_file(path):
            continue
        if path not in out:
            out.append(path)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 10 tests.

- [ ] **Step 5: Falsify the two load-bearing tests**

Prove each guards something. Apply each mutant, confirm RED, revert.

| Mutant | Must turn red |
|---|---|
| Change `if code == "D" and is_test_file(path)` to `if code == "D"` | `test_a_deleted_source_file_is_retained` |
| Change `PYTHON_FILES_GLOB` to `"*.py"` | `test_a_test_named_helper_that_pytest_does_not_collect_is_not_a_test_file` |

Run after each: `uv run pytest tests/test_affected_tests.py -q`

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "feat(scripts): add affected-tests diff normalization

Renames follow to the new path. Deletions drop only for test files -- a
deleted source file's referencing tests must still be selected."
```

---

## Task 2: The global blast-radius class and the short-circuit

**Files:**
- Modify: `scripts/affected_tests.py`
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: `is_test_file` (Task 1).
- Produces: `Reason` (StrEnum: `NONE`, `GLOBAL`, `CAPPED`); `Result` (frozen dataclass with `unit_files: tuple[str, ...]`, `e2e_files: tuple[str, ...]`, `unmapped: tuple[str, ...]`, `unit_reason: Reason`, `e2e_reason: Reason`); `is_global_path(path: str) -> bool`; `map_paths(paths, search, module_symbols) -> Result` handling only the global case so far.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
Reason = affected_tests.Reason
Result = affected_tests.Result
is_global_path = affected_tests.is_global_path
map_paths = affected_tests.map_paths


def no_hits(term):
    """A `search` stub that finds nothing."""
    return set()


def no_symbols(path):
    """A `module_symbols` stub that finds nothing."""
    return set()


class TestIsGlobalPath:
    @pytest.mark.parametrize(
        "path",
        [
            "conftest.py",
            "tests/conftest.py",
            "tests/factories.py",
            "tests/db_quiesce.py",
            "tests/deadlock_retry.py",
            "config/settings/base.py",
            "config/settings/test.py",
            "config/urls.py",
            "pyproject.toml",
            "uv.lock",
            "templates/base.html",
            "templates/allauth/layouts/base.html",
            "templates/_groups_tabs.html",
            "locale/pl/LC_MESSAGES/django.po",
            "locale/pl/LC_MESSAGES/django.mo",
        ],
    )
    def test_members(self, path):
        assert is_global_path(path)

    @pytest.mark.parametrize(
        "path",
        [
            "courses/models.py",
            "courses/tests/conftest.py",  # a per-app conftest is NOT the root one
            "templates/courses/detail.html",
            "templates/allauth/account/login.html",
        ],
    )
    def test_non_members(self, path):
        assert not is_global_path(path)

    def test_star_does_not_cross_a_directory_separator(self):
        # `templates/_*.html` must not match a file nested under a `_`-prefixed
        # directory. fnmatch's `*` crosses `/`; PurePosixPath.full_match does not.
        assert not is_global_path("templates/_partials/deep/thing.html")


class TestGlobalShortCircuit:
    def test_a_global_path_sets_both_reasons_to_global(self):
        result = map_paths(["tests/conftest.py"], no_hits, no_symbols)
        assert result.unit_reason is Reason.GLOBAL
        assert result.e2e_reason is Reason.GLOBAL

    def test_the_short_circuit_beats_the_module_rule(self):
        # conftest.py and factories.py ARE Python modules, so without the
        # short-circuit the module rule would emit a small, confidently-wrong
        # list -- the failure mode "advisory only" does not protect against,
        # because a human sees a plausible list and trusts it.
        def search_finds_one(term):
            return {"tests/test_unrelated.py"}

        def symbols(path):
            return {"make_pa"}

        result = map_paths(["tests/factories.py"], search_finds_one, symbols)
        assert result.unit_reason is Reason.GLOBAL
        assert result.unit_files == ()
        assert result.e2e_files == ()

    def test_one_global_path_among_ordinary_ones_still_short_circuits(self):
        result = map_paths(
            ["courses/models.py", "config/urls.py"], no_hits, no_symbols
        )
        assert result.unit_reason is Reason.GLOBAL

    def test_a_binary_catalog_is_global_not_unmapped(self):
        # A .mo maps to nothing under the per-path rules, but Django loads
        # COMPILED catalogs at runtime, so it changes every assertion on
        # translated strings.
        result = map_paths(["locale/pl/LC_MESSAGES/django.mo"], no_hits, no_symbols)
        assert result.e2e_reason is Reason.GLOBAL
        assert result.unmapped == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'Reason'`.

- [ ] **Step 3: Implement the global class and the short-circuit**

Add to the imports at the top of `scripts/affected_tests.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
```

Then append:

```python
# Paths whose change can alter the behaviour of tests that do not mention them.
# That is the whole membership criterion, and it is why the class is checked
# FIRST and short-circuits: conftest.py and factories.py are themselves Python
# modules, so the module rule below would otherwise emit a small,
# confidently-wrong list -- which "advisory only" does not protect against,
# because a human sees a plausible list and trusts it.
GLOBAL_PATHS = frozenset(
    {
        "conftest.py",
        "tests/conftest.py",
        "tests/factories.py",
        "tests/db_quiesce.py",
        "tests/deadlock_retry.py",
        # Would otherwise fall to the module rule and map to almost nothing,
        # despite affecting every view test.
        "config/urls.py",
        "pyproject.toml",
        "uv.lock",
        "templates/base.html",
    }
)

GLOBAL_GLOBS = (
    "config/settings/*.py",
    "templates/allauth/layouts/**",
    "templates/_*.html",
    # .mo matters MORE than .po: Django loads compiled catalogs at runtime, so a
    # .po edit without recompilation changes no behaviour, while a committed .mo
    # changes every assertion on translated strings -- and a binary file maps to
    # nothing under the per-path rules.
    "locale/**/*.po",
    "locale/**/*.mo",
)


def is_global_path(path: str) -> bool:
    """Whether `path` belongs to the global blast-radius class."""
    if path in GLOBAL_PATHS:
        return True
    # PurePosixPath.full_match, NOT fnmatch: fnmatch's `*` crosses `/`, so
    # `templates/_*.html` would match `templates/_partials/deep/thing.html`.
    candidate = PurePosixPath(path)
    return any(candidate.full_match(glob) for glob in GLOBAL_GLOBS)


class Reason(StrEnum):
    """Why a selection's emitted command is what it is."""

    NONE = "NONE"  # ordinary mapping; emit the candidate list
    GLOBAL = "GLOBAL"  # a global-blast-radius path changed; emit the full run
    CAPPED = "CAPPED"  # too many candidates to be meaningful; emit the full run


@dataclass(frozen=True)
class Result:
    """The outcome of mapping a diff.

    Two reasons, not one: the caps are independent, so "unit capped, e2e fine"
    and "e2e capped, unit fine" are both reachable and a single shared field
    would collapse them. GLOBAL is necessarily set on both.
    """

    unit_files: tuple[str, ...]
    e2e_files: tuple[str, ...]
    unmapped: tuple[str, ...]
    unit_reason: Reason
    e2e_reason: Reason


def map_paths(
    paths: list[str],
    search: Callable[[str], set[str]],
    module_symbols: Callable[[str], set[str]],
) -> Result:
    """Map changed paths to candidate test files. Pure -- all I/O is injected."""
    if any(is_global_path(p) for p in paths):
        return Result((), (), (), Reason.GLOBAL, Reason.GLOBAL)
    return Result((), (), (), Reason.NONE, Reason.NONE)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 31 tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Delete the `if any(is_global_path(p) ...)` block | `test_a_global_path_sets_both_reasons_to_global`, `test_the_short_circuit_beats_the_module_rule` |
| Swap `full_match` for `fnmatch.fnmatch` in `is_global_path` | `test_star_does_not_cross_a_directory_separator` |
| Remove `"config/urls.py"` from `GLOBAL_PATHS` | `test_one_global_path_among_ordinary_ones_still_short_circuits` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "feat(scripts): add global blast-radius class with short-circuit

Checked first, because conftest.py and factories.py are themselves modules
and the module rule would emit a confidently-wrong list for them."
```

---

## Task 3: The per-path mapping rules

**Files:**
- Modify: `scripts/affected_tests.py`
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: `is_test_file`, `is_global_path`, `Reason`, `Result` (Tasks 1–2).
- Produces: `import_path(path: str) -> str`; `map_one(path, search, module_symbols) -> set[str]`; constants `MIGRATION_GLOB = "**/migrations/*.py"`, `MIGRATION_TESTS_GLOB = "tests/test_transfer*.py"`, `FILENAME_SUFFIXES = frozenset({".html", ".css", ".js"})`. `map_paths` now populates `unmapped` and an internal candidate list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
import_path = affected_tests.import_path
map_one = affected_tests.map_one


CORPUS = {
    "tests/test_transfer_export.py",
    "tests/test_transfer_import.py",
    "tests/test_builder.py",
    "tests/test_e2e_builder.py",
}


def make_search(index):
    """Build a `search` stub from {term: {files}}."""

    def search(term):
        return set(index.get(term, set()))

    return search


class TestImportPath:
    def test_dots_replace_separators_and_the_suffix_is_dropped(self):
        assert import_path("courses/services/builder.py") == "courses.services.builder"

    def test_a_package_init_maps_to_the_package(self):
        assert import_path("courses/services/__init__.py") == "courses.services"


class TestMapOne:
    def test_a_test_file_maps_to_itself(self):
        assert map_one("tests/test_builder.py", make_search({}), no_symbols) == {
            "tests/test_builder.py"
        }

    def test_a_module_maps_to_tests_referencing_its_import_path(self):
        search = make_search({"courses.services.builder": {"tests/test_builder.py"}})
        assert map_one("courses/services/builder.py", search, no_symbols) == {
            "tests/test_builder.py"
        }

    def test_a_module_maps_to_tests_referencing_its_public_symbols(self):
        search = make_search({"duplicate_unit": {"tests/test_builder.py"}})

        def symbols(path):
            return {"duplicate_unit"}

        assert map_one("courses/services/builder.py", search, symbols) == {
            "tests/test_builder.py"
        }

    def test_a_template_maps_to_tests_referencing_its_filename(self):
        search = make_search({"_tree_node.html": {"tests/test_builder.py"}})
        assert map_one("templates/courses/_tree_node.html", search, no_symbols) == {
            "tests/test_builder.py"
        }

    @pytest.mark.parametrize(
        "path,term",
        [
            ("core/static/core/css/app.css", "app.css"),
            ("core/static/core/js/builder.js", "builder.js"),
        ],
    )
    def test_css_and_js_map_by_filename(self, path, term):
        search = make_search({term: {"tests/test_builder.py"}})
        assert map_one(path, search, no_symbols) == {"tests/test_builder.py"}

    def test_a_migration_maps_to_the_fixed_transfer_glob(self):
        # Deliberately mechanical: "transfer and model tests" names no pattern,
        # so two implementers would produce two different selections.
        search = make_search({affected_tests.MIGRATION_TESTS_GLOB: set(CORPUS)})
        hits = map_one(
            "courses/migrations/0055_thing.py", make_search({}), no_symbols
        )
        assert hits == {"tests/test_transfer_export.py", "tests/test_transfer_import.py"}

    def test_a_migration_does_not_fall_through_to_the_module_rule(self):
        # It is a .py file; ordering matters.
        def search_everything(term):
            return {"tests/test_builder.py"}

        hits = map_one(
            "courses/migrations/0055_thing.py", search_everything, no_symbols
        )
        assert "tests/test_builder.py" not in hits

    def test_a_binary_or_unknown_suffix_maps_to_nothing(self):
        assert map_one("core/static/core/img/logo.png", no_hits, no_symbols) == set()
        assert map_one("README.md", no_hits, no_symbols) == set()


class TestUnmappedReporting:
    def test_a_path_that_maps_to_nothing_is_reported_unmapped(self):
        result = map_paths(["core/static/core/img/logo.png"], no_hits, no_symbols)
        assert result.unmapped == ("core/static/core/img/logo.png",)

    def test_a_path_that_maps_to_something_is_not_unmapped(self):
        search = make_search({"courses.models": {"tests/test_builder.py"}})
        result = map_paths(["courses/models.py"], search, no_symbols)
        assert result.unmapped == ()
        assert "tests/test_builder.py" in result.unit_files
```

Note `map_one` needs the corpus for the migration glob. Pass it through `search`: the wrapper's `search` is content-based, so the migration rule instead needs a **corpus filter**. Resolve this in Step 3 by giving `map_one` the corpus via a `search` call on a sentinel — no: implement `map_one` to take an explicit `corpus` argument, and `map_paths` to obtain it as `search(CORPUS_SENTINEL)`. Simpler and stated plainly below: **`map_one` takes `corpus: set[str]`**, and `map_paths` derives it from `search`. See Step 3 for the exact resolution.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'import_path'`.

- [ ] **Step 3: Implement the rules**

The migration rule needs the corpus (to expand a glob over test files), which content-based `search` cannot supply. Rather than add a fourth callable, **`search` gains a documented contract**: `search(CORPUS)` — the module-level sentinel — returns the whole corpus. Stubs implement it in one line.

Add to `scripts/affected_tests.py`:

```python
# A `search` stub or implementation returns the ENTIRE corpus for this sentinel.
# The migration rule expands a glob over test-file NAMES, which content-based
# search cannot express; this keeps the injected dependencies at two rather than
# adding a fourth parameter for one rule.
CORPUS = "\x00corpus"

MIGRATION_GLOB = "**/migrations/*.py"
MIGRATION_TESTS_GLOB = "tests/test_transfer*.py"
FILENAME_SUFFIXES = frozenset({".html", ".css", ".js"})


def import_path(path: str) -> str:
    """`courses/services/builder.py` -> `courses.services.builder`."""
    p = PurePosixPath(path)
    if p.name == "__init__.py":
        p = p.parent
    else:
        p = p.with_suffix("")
    return str(p).replace("/", ".")


def map_one(
    path: str,
    search: Callable[[str], set[str]],
    module_symbols: Callable[[str], set[str]],
) -> set[str]:
    """Map one changed path to candidate test files. Order is significant."""
    if is_test_file(path):
        return {path}

    candidate = PurePosixPath(path)

    # BEFORE the module rule: a migration is a .py file and would otherwise fall
    # through to it.
    if candidate.full_match(MIGRATION_GLOB):
        return {
            f
            for f in search(CORPUS)
            if PurePosixPath(f).full_match(MIGRATION_TESTS_GLOB)
        }

    if candidate.suffix == ".py":
        # Bounded to module-level PUBLIC defs and classes. Unbounded matching on
        # common names (Element, render, save, index) would select a large
        # fraction of the corpus -- indistinguishable from the full suite, and a
        # silent failure.
        terms = {import_path(path)} | module_symbols(path)
        hits: set[str] = set()
        for term in terms:
            hits |= search(term)
        return hits

    if candidate.suffix in FILENAME_SUFFIXES:
        return search(candidate.name)

    # Binary and unknown suffixes map to nothing and are reported as unmapped by
    # the caller -- never silently dropped.
    return set()
```

Replace the body of `map_paths` after the global short-circuit with:

```python
    candidates: list[str] = []
    unmapped: list[str] = []
    for path in paths:
        hits = map_one(path, search, module_symbols)
        if hits:
            candidates.extend(sorted(hits))
        else:
            unmapped.append(path)

    ordered = sorted(set(candidates))
    return Result(tuple(ordered), (), tuple(unmapped), Reason.NONE, Reason.NONE)
```

Update the test stubs — `no_hits` and `make_search` must honour the sentinel:

```python
def no_hits(term):
    """A `search` stub that finds nothing (but still answers the corpus query)."""
    return set()


def make_search(index):
    def search(term):
        return set(index.get(term, set()))

    return search
```

For the migration tests, the stub must return the corpus:

```python
def corpus_search(term):
    if term == affected_tests.CORPUS:
        return set(CORPUS)
    return set()
```

and `test_a_migration_maps_to_the_fixed_transfer_glob` / `test_a_migration_does_not_fall_through_to_the_module_rule` use `corpus_search` (the latter wrapping it to also return `{"tests/test_builder.py"}` for any other term).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 44 tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Move the migration branch below the `.py` branch | `test_a_migration_does_not_fall_through_to_the_module_rule` |
| Drop `| module_symbols(path)` from `terms` | `test_a_module_maps_to_tests_referencing_its_public_symbols` |
| Return `{path}` instead of `set()` in the final fallthrough | `test_a_binary_or_unknown_suffix_maps_to_nothing` |
| Append to `candidates` instead of `unmapped` on an empty `hits` | `test_a_path_that_maps_to_nothing_is_reported_unmapped` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "feat(scripts): add per-path mapping rules

Migrations are checked before the module rule -- they are .py files and
would otherwise fall through to it."
```

---

## Task 4: Non-exclusive unit/e2e classification and the breadth caps

**Files:**
- Modify: `scripts/affected_tests.py`
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `classify(candidates: list[str], search) -> tuple[list[str], list[str]]`; constants `E2E_NAME_GLOB = "test_e2e_*.py"`, `E2E_MARKER = "pytest.mark.e2e"`, `UNIT_CAP = 40`, `E2E_CAP = 15`. `map_paths` now returns fully populated `Result`s.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
classify = affected_tests.classify


class TestClassification:
    def test_a_test_e2e_named_file_goes_to_e2e_only(self):
        unit, e2e = classify(["tests/test_e2e_builder.py"], no_hits)
        assert unit == []
        assert e2e == ["tests/test_e2e_builder.py"]

    def test_an_unmarked_file_goes_to_unit_only(self):
        unit, e2e = classify(["tests/test_builder.py"], no_hits)
        assert unit == ["tests/test_builder.py"]
        assert e2e == []

    def test_a_per_function_marked_file_goes_to_BOTH(self):
        # MEASURED: tests/test_tabs_editor_dnd.py collects 10 non-e2e tests and 2
        # e2e ones. An "iff" rule puts it solely in the `-m e2e` command, which
        # deselects the 10 -- selected nowhere, silently.
        def search(term):
            if term == affected_tests.E2E_MARKER:
                return {"tests/test_tabs_editor_dnd.py"}
            return set()

        unit, e2e = classify(["tests/test_tabs_editor_dnd.py"], search)
        assert unit == ["tests/test_tabs_editor_dnd.py"]
        assert e2e == ["tests/test_tabs_editor_dnd.py"]

    def test_the_trailing_underscore_in_the_name_glob_is_required(self):
        # integrations/tests/test_e2e.py carries NO e2e marker (its pytestmark is
        # django_db) and collects nothing under `-m e2e`. A looser `test_e2e*.py`
        # would misclassify it as e2e-only and strand its unit tests.
        unit, e2e = classify(["integrations/tests/test_e2e.py"], no_hits)
        assert unit == ["integrations/tests/test_e2e.py"]
        assert e2e == []

    def test_the_marker_search_happens_once_not_per_file(self):
        calls = []

        def counting_search(term):
            calls.append(term)
            return set()

        classify([f"tests/test_{i}.py" for i in range(20)], counting_search)
        assert calls.count(affected_tests.E2E_MARKER) == 1


class TestBreadthCaps:
    def test_unit_over_the_cap_sets_capped(self):
        files = [f"tests/test_m{i:03d}.py" for i in range(affected_tests.UNIT_CAP + 1)]
        search = make_search({"courses.models": set(files)})
        result = map_paths(["courses/models.py"], search, no_symbols)
        assert result.unit_reason is Reason.CAPPED

    def test_unit_at_the_cap_is_not_capped(self):
        files = [f"tests/test_m{i:03d}.py" for i in range(affected_tests.UNIT_CAP)]
        search = make_search({"courses.models": set(files)})
        result = map_paths(["courses/models.py"], search, no_symbols)
        assert result.unit_reason is Reason.NONE

    def test_e2e_over_the_cap_sets_capped(self):
        files = [
            f"tests/test_e2e_m{i:03d}.py" for i in range(affected_tests.E2E_CAP + 1)
        ]
        search = make_search({"courses.models": set(files)})
        result = map_paths(["courses/models.py"], search, no_symbols)
        assert result.e2e_reason is Reason.CAPPED

    def test_the_caps_are_independent(self):
        # "unit capped, e2e fine" must be representable -- which is why there are
        # two reason fields and not one.
        files = {f"tests/test_m{i:03d}.py" for i in range(affected_tests.UNIT_CAP + 1)}
        files |= {"tests/test_e2e_one.py"}
        search = make_search({"courses.models": files})
        result = map_paths(["courses/models.py"], search, no_symbols)
        assert result.unit_reason is Reason.CAPPED
        assert result.e2e_reason is Reason.NONE
        assert result.e2e_files == ("tests/test_e2e_one.py",)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'classify'`.

- [ ] **Step 3: Implement classification and the caps**

Add to `scripts/affected_tests.py`:

```python
# The trailing underscore is REQUIRED. MEASURED: integrations/tests/test_e2e.py
# carries no e2e marker (its pytestmark is django_db) and collects nothing under
# `-m e2e`; a looser `test_e2e*.py` would call it e2e-only and strand its unit
# tests.
E2E_NAME_GLOB = "test_e2e_*.py"
E2E_MARKER = "pytest.mark.e2e"

# Per selection, and independent: a joint cap would be dominated by the unit
# side. 40 of ~549 unit test files; 15 of 97 e2e ones.
UNIT_CAP = 40
E2E_CAP = 15


def classify(
    candidates: list[str], search: Callable[[str], set[str]]
) -> tuple[list[str], list[str]]:
    """Split candidates into (unit, e2e). NON-exclusive: a file may be in both.

    Only two tests, both expressible through `search()`, because distinguishing a
    module-level `pytestmark` from per-function decorators is not implementable
    under the purity constraint: a substring search cannot tell them apart, and
    `search("pytestmark = pytest.mark.e2e")` misses the list form this repo uses
    (`pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]`).
    The distinction is unnecessary anyway -- every module-level-marked file here
    is already named `test_e2e_*.py`, so the first rule catches it.

    Routing a marked file to BOTH is safe: the surplus command simply selects
    nothing there, which the exit-5 caveat covers.
    """
    # Once, not per file -- the wrapper's implementation scans the whole corpus.
    marked = search(E2E_MARKER)
    unit: list[str] = []
    e2e: list[str] = []
    for path in candidates:
        if fnmatch.fnmatch(PurePosixPath(path).name, E2E_NAME_GLOB):
            e2e.append(path)
        elif path in marked:
            unit.append(path)
            e2e.append(path)
        else:
            unit.append(path)
    return unit, e2e
```

Replace `map_paths`'s return with:

```python
    ordered = sorted(set(candidates))
    unit, e2e = classify(ordered, search)

    unit_reason = Reason.CAPPED if len(unit) > UNIT_CAP else Reason.NONE
    e2e_reason = Reason.CAPPED if len(e2e) > E2E_CAP else Reason.NONE

    return Result(
        tuple(unit), tuple(e2e), tuple(unmapped), unit_reason, e2e_reason
    )
```

The capped lists are **retained** in the `Result` rather than emptied, so a reader can see what was capped; `render_commands` ignores them and emits the full run.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 53 tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Change the `elif path in marked` branch to `e2e.append(path)` only (exclusive) | `test_a_per_function_marked_file_goes_to_BOTH` |
| Change `E2E_NAME_GLOB` to `"test_e2e*.py"` | `test_the_trailing_underscore_in_the_name_glob_is_required` |
| Move `marked = search(E2E_MARKER)` inside the loop | `test_the_marker_search_happens_once_not_per_file` |
| Change `>` to `>=` in the unit cap | `test_unit_at_the_cap_is_not_capped` |
| Use one shared `reason` for both selections | `test_the_caps_are_independent` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "feat(scripts): non-exclusive unit/e2e classification with per-selection caps

A file may land in BOTH selections: test_tabs_editor_dnd.py holds 10 unit
tests and 2 e2e ones, and an exclusive rule strands the 10."
```

---

## Task 5: Command emission — the reason matrix, `-m e2e`, and the exit-5 caveat

**Files:**
- Modify: `scripts/affected_tests.py`
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: `Result`, `Reason` (Tasks 2–4).
- Produces: `render_commands(result: Result) -> str`; constants `EXIT5_NOTE`, `FULL_UNIT_COMMAND = "uv run pytest"`, `FULL_E2E_COMMAND = "uv run pytest -m e2e"`.

**This task carries the highest-consequence behaviour in the tool.** The reason must be checked *before* emptiness, or a `GLOBAL` result — whose file tuples are empty by construction — would be misread as "nothing mapped" and emit no command at all.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
render_commands = affected_tests.render_commands


class TestEmission:
    def test_a_normal_result_emits_both_candidate_lists(self):
        result = Result(
            ("tests/test_a.py",),
            ("tests/test_e2e_b.py",),
            (),
            Reason.NONE,
            Reason.NONE,
        )
        out = render_commands(result)
        assert "uv run pytest tests/test_a.py" in out
        assert "uv run pytest tests/test_e2e_b.py -m e2e" in out

    def test_the_e2e_command_always_carries_the_marker(self):
        result = Result((), ("tests/test_e2e_b.py",), (), Reason.NONE, Reason.NONE)
        out = render_commands(result)
        e2e_line = next(ln for ln in out.splitlines() if "test_e2e_b.py" in ln)
        assert e2e_line.rstrip().endswith("-m e2e")

    def test_both_commands_carry_the_exit_5_caveat(self):
        # Not just the e2e one: non-exclusive classification puts every
        # per-function-marked file into both selections, and three such files
        # collect ZERO non-e2e tests -- so a diff touching only those emits a
        # unit command whose every file is deselected by `-m 'not e2e'`.
        result = Result(
            ("tests/test_a.py",),
            ("tests/test_e2e_b.py",),
            (),
            Reason.NONE,
            Reason.NONE,
        )
        out = render_commands(result)
        assert out.count(affected_tests.EXIT5_NOTE) == 2

    def test_an_empty_unit_selection_emits_no_command(self):
        # Interpolating an empty file list yields a bare `uv run pytest`, i.e.
        # the whole unit selection, silently, for a diff that mapped nothing.
        result = Result((), ("tests/test_e2e_b.py",), ("README.md",), Reason.NONE, Reason.NONE)
        out = render_commands(result)
        assert "no unit tests mapped; see unmapped" in out
        unit_lines = [
            ln
            for ln in out.splitlines()
            if ln.strip().startswith("uv run pytest") and "-m e2e" not in ln
        ]
        assert unit_lines == []

    def test_an_empty_e2e_selection_emits_no_command(self):
        result = Result(("tests/test_a.py",), (), ("README.md",), Reason.NONE, Reason.NONE)
        out = render_commands(result)
        assert "no e2e tests mapped; see unmapped" in out
        assert "-m e2e" not in out

    def test_a_wholly_empty_result_emits_no_pytest_command_at_all(self):
        result = Result((), (), ("README.md",), Reason.NONE, Reason.NONE)
        out = render_commands(result)
        assert "uv run pytest" not in out

    def test_global_emits_the_full_run_for_both_despite_empty_file_tuples(self):
        # THE interaction: a GLOBAL result carries empty tuples by construction.
        # Checking emptiness before the reason would emit no command at all --
        # exactly inverting the intended "run everything" answer.
        result = Result((), (), (), Reason.GLOBAL, Reason.GLOBAL)
        out = render_commands(result)
        assert affected_tests.FULL_UNIT_COMMAND in out
        assert affected_tests.FULL_E2E_COMMAND in out
        assert "no unit tests mapped" not in out

    def test_capped_emits_the_full_run_for_that_selection_only(self):
        files = tuple(f"tests/test_m{i:03d}.py" for i in range(41))
        result = Result(files, ("tests/test_e2e_b.py",), (), Reason.CAPPED, Reason.NONE)
        out = render_commands(result)
        assert affected_tests.FULL_UNIT_COMMAND in out
        assert "uv run pytest tests/test_e2e_b.py -m e2e" in out

    def test_unmapped_paths_are_listed(self):
        result = Result(("tests/test_a.py",), (), ("logo.png", "README.md"), Reason.NONE, Reason.NONE)
        out = render_commands(result)
        assert "logo.png" in out
        assert "README.md" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'render_commands'`.

- [ ] **Step 3: Implement emission**

Add to `scripts/affected_tests.py`:

```python
EXIT5_NOTE = "(exit code 5 means \"nothing selected\", not \"green\")"
FULL_UNIT_COMMAND = "uv run pytest"
FULL_E2E_COMMAND = "uv run pytest -m e2e"

_FULL_RUN_BECAUSE = {
    Reason.GLOBAL: "a global blast-radius path changed",
    Reason.CAPPED: "too many candidates to be meaningful",
}


def _render_one(label: str, files: tuple[str, ...], reason: Reason, suffix: str) -> list[str]:
    """Render one selection's block.

    The REASON is checked before emptiness. A GLOBAL result carries empty file
    tuples by construction, so testing emptiness first would print "nothing
    mapped" for the one input that means "run everything".
    """
    if reason in _FULL_RUN_BECAUSE:
        full = f"{FULL_UNIT_COMMAND}{suffix}"
        return [
            f"{label}: full run -- {_FULL_RUN_BECAUSE[reason]}",
            f"    {full}    {EXIT5_NOTE}",
        ]
    if not files:
        return [f"{label}: no {label} tests mapped; see unmapped"]
    joined = " ".join(files)
    return [
        f"{label}: {len(files)} file(s)",
        f"    {FULL_UNIT_COMMAND} {joined}{suffix}    {EXIT5_NOTE}",
    ]


def render_commands(result: Result) -> str:
    """Render the advisory output. Pure."""
    lines: list[str] = []
    lines += _render_one("unit", result.unit_files, result.unit_reason, "")
    lines.append("")
    lines += _render_one("e2e", result.e2e_files, result.e2e_reason, " -m e2e")
    if result.unmapped:
        lines.append("")
        lines.append("unmapped (no rule matched -- check these by hand):")
        lines += [f"    {p}" for p in result.unmapped]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 62 tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Move the `if not files` check above the `if reason in _FULL_RUN_BECAUSE` check | `test_global_emits_the_full_run_for_both_despite_empty_file_tuples` |
| Change `if not files: return [...]` to fall through and interpolate the empty list | `test_an_empty_unit_selection_emits_no_command` |
| Drop `-m e2e` from the e2e suffix | `test_the_e2e_command_always_carries_the_marker` |
| Append `EXIT5_NOTE` to the e2e block only | `test_both_commands_carry_the_exit_5_caveat` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "feat(scripts): emit advisory pytest commands

Reason is checked before emptiness: a GLOBAL result has empty file tuples by
construction, and an empty candidate list must emit NO command rather than a
bare 'uv run pytest'."
```

---

## Task 6: The CLI wrapper — corpus, search, symbols, diff range

**Files:**
- Modify: `scripts/affected_tests.py`
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `git_lines(args: list[str], cwd: Path) -> list[str]`; `build_corpus(cwd: Path) -> set[str]`; `make_search(corpus: set[str], cwd: Path) -> Callable[[str], set[str]]`; `read_module_symbols(cwd: Path) -> Callable[[str], set[str]]`; `resolve_base(base: str, cwd: Path) -> str`; `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
build_corpus = affected_tests.build_corpus
make_corpus_search = affected_tests.make_search
read_module_symbols = affected_tests.read_module_symbols


class TestModuleSymbols:
    def test_module_level_public_defs_and_classes_only(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "import os\n"
            "\n"
            "PUBLIC_CONST = 1\n"
            "\n"
            "def public_fn():\n"
            "    def inner_fn():\n"
            "        pass\n"
            "\n"
            "def _private_fn():\n"
            "    pass\n"
            "\n"
            "class PublicClass:\n"
            "    def a_method(self):\n"
            "        pass\n"
            "\n"
            "class _PrivateClass:\n"
            "    pass\n",
            encoding="utf-8",
        )
        symbols = read_module_symbols(tmp_path)("m.py")
        assert symbols == {"public_fn", "PublicClass"}

    def test_an_unparseable_module_yields_nothing_rather_than_raising(self, tmp_path):
        (tmp_path / "bad.py").write_text("def (\n", encoding="utf-8")
        assert read_module_symbols(tmp_path)("bad.py") == set()

    def test_a_missing_module_yields_nothing(self, tmp_path):
        # A DELETED source file is retained by normalize_name_status and reaches
        # the module rule, but is no longer on disk.
        assert read_module_symbols(tmp_path)("gone.py") == set()


class TestSearch:
    def test_matches_on_word_boundaries(self, tmp_path):
        (tmp_path / "test_a.py").write_text("from courses import render\n", encoding="utf-8")
        (tmp_path / "test_b.py").write_text("rendered = 1\n", encoding="utf-8")
        search = make_corpus_search({"test_a.py", "test_b.py"}, tmp_path)
        assert search("render") == {"test_a.py"}

    def test_a_dotted_term_is_escaped_not_treated_as_regex(self, tmp_path):
        (tmp_path / "test_a.py").write_text("pytest.mark.e2e\n", encoding="utf-8")
        (tmp_path / "test_b.py").write_text("pytestXmarkYe2e\n", encoding="utf-8")
        search = make_corpus_search({"test_a.py", "test_b.py"}, tmp_path)
        assert search("pytest.mark.e2e") == {"test_a.py"}

    def test_the_corpus_sentinel_returns_the_whole_corpus(self, tmp_path):
        search = make_corpus_search({"test_a.py", "test_b.py"}, tmp_path)
        assert search(affected_tests.CORPUS) == {"test_a.py", "test_b.py"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'build_corpus'`.

- [ ] **Step 3: Implement the wrapper**

Add these imports (isort `force-single-line`, one per line):

```python
import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
```

Append to `scripts/affected_tests.py`:

```python
def git_lines(args: list[str], cwd: Path) -> list[str]:
    """Run a git command and return its stdout lines. Raises on failure."""
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no untrusted input
        ["git", *args],  # noqa: S607 -- git is expected on PATH, as everywhere else here
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.splitlines()


def build_corpus(cwd: Path) -> set[str]:
    """Every TRACKED file pytest would collect as a test module.

    `git ls-files`, never a filesystem walk. MEASURED: 3,197 files on disk match
    `test_*.py` here against 647 tracked ones -- the rest are in nested worktrees
    under `.claude/worktrees/`, gitignored and skipped by pytest, but a walk sees
    roughly five phantoms per real file and emits node IDs into another branch.
    """
    return {p for p in git_lines(["ls-files"], cwd) if is_test_file(p)}


def make_search(corpus: set[str], cwd: Path) -> Callable[[str], set[str]]:
    """Build a word-boundary `search` over the corpus, reading each file once."""
    contents: dict[str, str] = {}
    for rel in corpus:
        try:
            contents[rel] = (cwd / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            contents[rel] = ""

    def search(term: str) -> set[str]:
        if term == CORPUS:
            return set(corpus)
        # Word boundaries, and re.escape -- otherwise "pytest.mark.e2e" is a
        # regex whose dots match any character.
        pattern = re.compile(rf"\b{re.escape(term)}\b")
        return {rel for rel, text in contents.items() if pattern.search(text)}

    return search


def read_module_symbols(cwd: Path) -> Callable[[str], set[str]]:
    """Build a `module_symbols` that AST-parses a source path.

    Module-level PUBLIC defs and classes only -- no methods, no private names.
    Unbounded matching on common names (Element, render, save, index) would
    select a large fraction of the corpus, indistinguishable from a full run.
    """

    def module_symbols(path: str) -> set[str]:
        try:
            source = (cwd / path).read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            # A DELETED source file is retained by normalize_name_status and
            # reaches this rule while no longer being on disk. Degrade to the
            # import-path term rather than crashing the whole run.
            return set()
        return {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and not node.name.startswith("_")
        }

    return module_symbols


def resolve_base(base: str, cwd: Path) -> str:
    """Resolve the merge base with `base`. A missing ref is a HARD error.

    `origin/master`, not local `master`, which is routinely stale in a worktree.
    """
    try:
        git_lines(["rev-parse", "--verify", f"{base}^{{commit}}"], cwd)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"affected_tests: base ref {base!r} does not exist.\n"
            f"  Try `git fetch origin`, or pass --base <ref>.\n"
            f"  Refusing to continue: an unresolvable base yields an empty diff, "
            f"which would silently look like 'nothing changed'."
        ) from exc
    merge_base = git_lines(["merge-base", base, "HEAD"], cwd)
    return merge_base[0].strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Suggest the pytest commands worth running for the current diff.",
        epilog="Advisory only. CI's full suite remains the gate.",
    )
    parser.add_argument(
        "--base",
        default="origin/master",
        help="base ref to diff against (default: origin/master)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="repository root (default: the git root containing this script)",
    )
    args = parser.parse_args(argv)

    cwd = args.repo or Path(git_lines(["rev-parse", "--show-toplevel"], Path.cwd())[0])
    base = resolve_base(args.base, cwd)
    changed = normalize_name_status(git_lines(["diff", "--name-status", base], cwd))
    if not changed:
        print(f"no changes against {args.base} ({base[:8]}); nothing to run")
        return 0

    corpus = build_corpus(cwd)
    result = map_paths(changed, make_search(corpus, cwd), read_module_symbols(cwd))
    print(f"{len(changed)} changed path(s) against {args.base} ({base[:8]})")
    print()
    print(render_commands(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 68 tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Drop `re.escape` from the pattern | `test_a_dotted_term_is_escaped_not_treated_as_regex` |
| Drop the `\b` anchors | `test_matches_on_word_boundaries` |
| Remove the `not node.name.startswith("_")` filter | `test_module_level_public_defs_and_classes_only` |
| Walk with `ast.walk` instead of iterating `tree.body` | `test_module_level_public_defs_and_classes_only` (picks up `inner_fn`, `a_method`) |
| Remove the `except (OSError, SyntaxError, ValueError)` guard | `test_an_unparseable_module_yields_nothing_rather_than_raising` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "feat(scripts): add the affected-tests CLI wrapper

Corpus from git ls-files, never a walk: 3,197 test_*.py files on disk here
against 647 tracked. A missing base ref is a hard error, never a silent
empty diff."
```

---

## Task 7: Integration test against a deterministic fixture repository

**Files:**
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: `main`, `build_corpus`, `resolve_base` (Task 6).
- Produces: nothing consumed downstream.

A **fixture repository built in `tmp_path`** with a known commit and a known `origin/master` ref — not "a real recent diff", whose content changes with every branch, making assertions either vacuous or perpetually broken.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
import subprocess


def run_git(cwd, *args):
    subprocess.run(  # noqa: S603 -- fixed argv, tmp_path fixture repo
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def fixture_repo(tmp_path):
    """A deterministic repo with a known origin/master and one ignored worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "master")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "T")

    (repo / "tests").mkdir()
    (repo / "courses").mkdir()
    (repo / "courses" / "models.py").write_text(
        "class Widget:\n    pass\n", encoding="utf-8"
    )
    (repo / "tests" / "test_widget.py").write_text(
        "from courses.models import Widget\n\n\ndef test_w():\n    assert Widget\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_e2e_widget.py").write_text(
        "import pytest\n\npytestmark = pytest.mark.e2e\n\n\n"
        "def test_w(page):\n    assert Widget\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "base")
    # A stand-in for the nested worktrees: gitignored, on disk, must never enter
    # the corpus.
    phantom = repo / ".claude" / "worktrees" / "other" / "tests"
    phantom.mkdir(parents=True)
    (phantom / "test_phantom.py").write_text("def test_p():\n    pass\n", encoding="utf-8")
    # `origin/master` as a real remote-tracking ref, pinned at the base commit.
    run_git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    return repo


class TestCorpusExcludesIgnoredPaths:
    def test_a_nested_worktree_test_file_never_enters_the_corpus(self, fixture_repo):
        corpus = build_corpus(fixture_repo)
        assert corpus == {"tests/test_widget.py", "tests/test_e2e_widget.py"}
        assert not any(".claude" in p for p in corpus)

    def test_the_phantom_really_is_on_disk(self, fixture_repo):
        # Guards the guard: if the fixture stopped writing the phantom, the test
        # above would pass vacuously.
        assert (
            fixture_repo / ".claude" / "worktrees" / "other" / "tests" / "test_phantom.py"
        ).exists()


class TestWrapperIntegration:
    def test_a_source_change_maps_to_its_tests_with_both_commands(
        self, fixture_repo, capsys
    ):
        (fixture_repo / "courses" / "models.py").write_text(
            "class Widget:\n    pass\n\n\ndef helper():\n    pass\n", encoding="utf-8"
        )
        run_git(fixture_repo, "add", "-A")
        run_git(fixture_repo, "commit", "-q", "-m", "change")

        assert affected_tests.main(["--repo", str(fixture_repo)]) == 0
        out = capsys.readouterr().out

        assert "uv run pytest tests/test_widget.py" in out
        assert "uv run pytest tests/test_e2e_widget.py -m e2e" in out
        assert out.count(affected_tests.EXIT5_NOTE) == 2
        assert "test_phantom.py" not in out

    def test_a_missing_base_ref_fails_loudly(self, fixture_repo):
        with pytest.raises(SystemExit) as excinfo:
            affected_tests.main(["--repo", str(fixture_repo), "--base", "origin/nope"])
        assert "does not exist" in str(excinfo.value)

    def test_a_docs_only_diff_emits_no_pytest_command(self, fixture_repo, capsys):
        (fixture_repo / "README.md").write_text("hi\n", encoding="utf-8")
        run_git(fixture_repo, "add", "-A")
        run_git(fixture_repo, "commit", "-q", "-m", "docs")

        assert affected_tests.main(["--repo", str(fixture_repo)]) == 0
        out = capsys.readouterr().out

        assert "uv run pytest" not in out
        assert "no unit tests mapped" in out
        assert "no e2e tests mapped" in out
        assert "README.md" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -k "Corpus or WrapperIntegration" -v`

Expected: FAIL — the fixture repo and assertions are new; confirm each failure names the assertion, not a fixture error.

- [ ] **Step 3: Fix whatever the integration surfaces**

No new production code is planned here. If a test fails for a real reason (path separators on Windows, `git diff --name-status` against a merge base that equals HEAD, `PurePosixPath` vs `\`), fix `scripts/affected_tests.py` — and normalize paths from git to forward slashes if Windows surfaces backslashes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 74 tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Change `build_corpus` to walk with `Path.rglob("test_*.py")` | `test_a_nested_worktree_test_file_never_enters_the_corpus` |
| Make `resolve_base` return `""` on a missing ref instead of raising | `test_a_missing_base_ref_fails_loudly` |
| Delete the phantom write from the fixture | `test_the_phantom_really_is_on_disk` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check tests/test_affected_tests.py
git add tests/test_affected_tests.py
git commit -m "test(scripts): integration-test affected_tests on a fixture repo

Deterministic tmp_path repo with a known origin/master, including a
gitignored nested-worktree test file that must never enter the corpus."
```

---

## Task 8: B1 — document the practice in `testing.md`

**Files:**
- Modify: `docs/development/testing.md`

Part A already shipped the branch-gate rule, the never-twice rule, one-run-at-a-time and troubleshooting. What is missing is the per-file-justification practice and the pointer to the script.

- [ ] **Step 1: Read the existing file**

Run: `cat docs/development/testing.md`

Confirm the `## What runs where` section exists at the end and says "Run the affected tests locally; let CI run the full suite."

- [ ] **Step 2: Replace the `## What runs where` section**

Replace the final section of `docs/development/testing.md` with:

```markdown
## What runs where

Run the affected tests locally; let CI run the full suite. CI does both
selections plus lint in about **8m45s**, in three parallel jobs, and it does not
consume your session.

Do not run the full suite locally twice in one session. The exception is a
deliberate before/after benchmark, which is a measurement, not a gate.

## Which tests are affected

```bash
uv run python scripts/affected_tests.py            # vs origin/master
uv run python scripts/affected_tests.py --base HEAD~3
```

It prints one command per selection, or explicitly says a selection mapped
nothing. **It is advisory.** CI's full suite is the gate; the script only decides
what is worth running while iterating.

Read its output with three things in mind:

- **`unmapped` is the interesting part.** Anything listed there matched no rule
  — a binary asset, a new file type, something the tool does not understand. Judge
  those by hand rather than assuming they are safe.
- **A full run is a real answer.** Changing `conftest.py`, `config/settings/`,
  `config/urls.py`, `pyproject.toml` or a compiled `.mo` catalog can alter tests
  that never mention it, so the script stops mapping and tells you to run
  everything. Same when a selection exceeds its breadth cap: a list that long is
  no longer meaningfully narrower than the suite.
- **Exit code 5 means "nothing selected", not "green"** — for either command.
  Some files hold only e2e tests, so a unit command built from them is entirely
  deselected by the default `-m 'not e2e'`.

### Justify the selection before a slice

Before a multi-task slice, write down the files you will treat as the local gate
and why each one can be affected — the format is
`docs/superpowers/notes/2026-07-28-affected-tests-slice2.md`: a table of file,
baseline exit code, test count, and the reason the slice can touch it.

The point is the classification it lets you make later. Mark each file as either
encoding behaviour the slice **changes** — where a red is expected migration —
or behaviour it must **preserve**, where **a red is a REGRESSION, not
migration**. Without that written down first, every red mid-slice becomes an
argument with yourself about whether it was intended.

Baseline the selection green before you start. A red you cannot attribute to a
before-state is a red you will spend an hour on.
```

- [ ] **Step 3: Verify the docs build reference is intact**

Run: `grep -n "affected_tests\|REGRESSION" docs/development/testing.md`

Expected: the script path appears twice (both commands), `REGRESSION` once.

- [ ] **Step 4: Confirm no test asserts on the replaced text**

Run: `uv run pytest tests/ -k "docs or testing_md or conventions" -q --collect-only`

Expected: either no tests collected, or none that regex `testing.md`'s "What runs where" body. If one exists, update it.

- [ ] **Step 5: Commit**

```bash
git add docs/development/testing.md
git commit -m "docs(testing): document the affected-tests practice

Adds the script's usage and how to read it, plus the per-file justification
format and the regression-vs-migration classification it exists to enable."
```

---

## Task 9: Dogfood the tool on its own branch

**Files:**
- Modify: none (verification only, unless a defect surfaces)

The tool has never been run against a real diff. This task runs it once against this branch and checks the answer by hand — the cheapest possible check that the rules behave on real input rather than stubs.

- [ ] **Step 1: Run it against this branch**

Run:
```bash
uv run python scripts/affected_tests.py --base origin/master
```

- [ ] **Step 2: Check the answer by hand**

The diff adds `scripts/affected_tests.py`, `tests/test_affected_tests.py` and modifies `docs/development/testing.md`, plus this plan file.

Expected, and each is a real assertion about the rules:

| Input path | Expected treatment |
|---|---|
| `tests/test_affected_tests.py` | test file → maps to itself → **unit** selection |
| `scripts/affected_tests.py` | Python module → searched by import path `scripts.affected_tests` and its public symbols → likely finds `tests/test_affected_tests.py` |
| `docs/development/testing.md` | `.md` → no rule → **unmapped** |
| `docs/superpowers/plans/2026-08-07-affected-tests-workflow.md` | `.md` → **unmapped** |

The e2e selection should report `no e2e tests mapped; see unmapped`, and **no `-m e2e` command should be printed at all**.

- [ ] **Step 3: Confirm the run time is not itself a cost**

Run: `uv run python -c "import time; t=time.perf_counter(); import subprocess; subprocess.run(['uv','run','python','scripts/affected_tests.py'],capture_output=True); print(f'{time.perf_counter()-t:.1f}s')"`

Record the number. The tool reads ~647 files; if it takes more than a few seconds, note it — a slow advisory tool does not get run, which was the whole scoping premise.

- [ ] **Step 4: Run the full named test file once more**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, 74 tests, exit 0. **Do not run the full suite** — this branch adds no application code, and CI is the gate.

- [ ] **Step 5: Lint the whole diff**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
```

- [ ] **Step 6: Record the dogfood result and commit if anything changed**

If Steps 1–3 surfaced a defect, fix it, add a test that would have caught it, and commit. If not, no commit is needed for this task — state the observed output in the task report.

---

## Self-Review

**Spec coverage (§4):**

| Spec requirement | Task |
|---|---|
| B1 documented practice, per-file justification, regression-vs-migration | 8 |
| B1 branch gate / never-twice / one-run-at-a-time / troubleshooting | already shipped by Part A; Task 8 preserves them |
| `normalize_name_status`, renames, deleted test vs source | 1 |
| Corpus from `git ls-files`, ignored paths excluded | 6, 7 |
| Global blast-radius class, checked first, short-circuiting | 2 |
| Per-path rules: test file, module, template/CSS/JS, migration | 3 |
| `python_files` definition of "a test file" | 1 |
| Bounded module-level public symbols, word-boundary matching | 3, 6 |
| Breadth caps, per selection, independent | 4 |
| Non-exclusive unit/e2e classification | 4 |
| `Result` with per-selection reasons | 2, 4 |
| Empty selections emit no command | 5 |
| `-m e2e` always; exit-5 caveat on both | 5 |
| Diff range merge-base `origin/master`, `--base`, hard error | 6 |
| B3 core-on-stubs coverage | 1–5 |
| B3 corpus case for an ignored directory | 7 |
| B3 wrapper integration on a fixture repo | 7 |
| `migration_models` | **cut by decision**; `module_symbols` substituted (Task 3, 6) |

**Placeholder scan:** none. Every code step carries the actual code; every test step carries the actual assertions.

**Type consistency:** `Result` fields (`unit_files`, `e2e_files`, `unmapped`, `unit_reason`, `e2e_reason`) are used identically in Tasks 2, 4, 5, 7. `search` has one contract throughout (word-boundary substring, plus the `CORPUS` sentinel), introduced in Task 3 and implemented in Task 6. `module_symbols` is `Callable[[str], set[str]]` in Tasks 3, 4 and 6. `map_one` takes `(path, search, module_symbols)` in both its definition and every call site.

**One known wrinkle, deliberately left for execution:** Task 3's `map_one` needs the corpus for the migration glob, resolved by the `CORPUS` sentinel on `search` rather than a fourth parameter. Task 3 Step 1's tests are written against `make_search`/`no_hits` stubs that must honour the sentinel; Step 3 states the fix. Any subagent executing Task 3 must apply the Step 3 stub updates or those two migration tests fail for the wrong reason.
