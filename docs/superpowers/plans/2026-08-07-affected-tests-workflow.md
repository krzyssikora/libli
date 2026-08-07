# Affected-tests workflow (Part B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `scripts/affected_tests.py` — an advisory tool that maps a diff to the pytest commands worth running locally — plus its tests and the documented practice that tells a developer when to trust it.

**Architecture:** One module under `scripts/`, split internally into a **pure core** (`normalize_name_status`, `map_paths`, `render_commands`) that performs no I/O, and a **CLI wrapper** that owns every git and filesystem access and injects two callables (`search`, `module_symbols`) into the core. The purity boundary exists so the mapping rules are tested against literal stubs rather than a fixture repository; only the wrapper needs a real repo. Tests live at `tests/test_affected_tests.py` because `scripts/` sits outside every test directory and `pyproject.toml` sets no `testpaths`, so that path is what guarantees collection by the existing configuration.

**The test module shadows `tests/conftest.py`'s autouse `_enable_db_access(db)` fixture.** That fixture gives every test in `tests/` a database, deliberately — but this module tests stdlib-only pure functions and needs none. VERIFIED by measurement: with the shadow, the file passes in **0.82 s** against a dead `TEST_DATABASE_URL`; without it, the same file **ERRORs after 12.08 s**. Leaving it unshadowed would make every "Expected: PASS" line below false on a machine with no container running, and would needlessly wrap pure-function tests in a transaction.

**Tech Stack:** Python 3.13, stdlib only (`argparse`, `subprocess`, `fnmatch`, `re`, `ast`, `dataclasses`, `enum`, `pathlib.PurePosixPath`). pytest + pytest-django for the tests. No new dependencies.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec (`docs/superpowers/specs/2026-08-07-test-suite-wall-clock-design.md` §4) or measured against this tree at `00f1e03b`.

- **The tool is advisory, never authoritative.** CI's full suite remains the gate. Bias every undecidable case toward visibility (report as `unmapped`), never toward silent omission.
- **Corpus is built from `git ls-files`, never a filesystem walk.** MEASURED in the main checkout: **647** tracked files match `test_*.py`, while a walk sees **3,197** — the difference is 16 under `.venv/` and 2,534 inside nested worktrees under `.claude/worktrees/`. The nested-worktree figure is **checkout-local** (a fresh worktree has none), so it must not ship as a fixed constant in source; `.venv/` alone justifies the rule everywhere.
- **Unit/e2e classification is NON-exclusive.** A file may appear in both selections. `tests/test_tabs_editor_dnd.py` collects **10 non-e2e and 2 e2e** tests (measured); an "iff" rule strands the 10.
- **An empty candidate list emits NO command** for that selection, and prints `<unit|e2e>: nothing mapped`. No "see unmapped" pointer: the unmapped section is printed only when non-empty, and a diff touching only e2e files leaves the unit selection empty with nothing unmapped to point at.
- **The emitted e2e command always carries `-m e2e`.**
- **Both emitted commands carry the note that exit code 5 means "nothing selected", not "green".** MEASURED: `tests/test_link_apply.py` (29), `test_link_dialog_behaviour.py` (32) and `test_table_grid_algebra.py` (38) collect **zero** non-e2e tests. All three carry a **module-level** `pytestmark = pytest.mark.e2e` and are **not** named `test_e2e_*`, so they land in both selections and their unit command is entirely deselected.
- **"A test file" means the basename matches `python_files` = `test_*.py`**, not "lives in a test directory". `tests/capture_help_screenshots.py` is deliberately not collectible.
- **Breadth caps, per selection, independent:** unit **40**, e2e **15**.
- **Diff range is merge-base with `origin/master`** (not local `master`, routinely stale in a worktree). `--base` overrides. A missing ref is a hard error, never a silent empty diff.
- **ruff applies to `scripts/`** — `select = ["E", "F", "I", "UP", "B", "S"]`, `ignore = ["S101"]`, `isort.force-single-line = true`, **line length 88** (no override). Consequences, all verified: `subprocess` calls need `# noqa: S603` (precedent `tests/test_help_capture_isolation.py:19`); no unused imports (`F401`), so each task adds only the imports it uses; no mid-file imports (`E402`); bare `assert` in tests is fine (`S101` is ignored globally); and `ruff format` rewrites `"...\"x\"..."` to `'..."x"...'`, so **write strings containing double quotes with single outer quotes**.
- **Comments recording an observation are prefixed `MEASURED:`**, matching `conftest.py` (3 occurrences) and 31 other python files repo-wide.
- **Never run the full suite to check this work.** Run the named test file only.

### Deviations from the spec, already decided

- **`migration_models` is cut.** Migrations map to the fixed `tests/test_transfer*.py` glob only. Rationale (measured): of the last 200 commits, exactly **one** touches a migration, and it touched `models.py` in the same commit, so the module rule already covered it.
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

**`search` contract, used by every rule and every stub:** `search(term)` returns the corpus files containing `term` **on a word boundary**; `search(CORPUS_SENTINEL)` returns the entire corpus. The sentinel exists because the migration rule expands a glob over test-file *names*, which a content search cannot express — it keeps the injected dependencies at two rather than adding a fourth parameter for one rule.

`module_symbols(path)` returns the module-level public defs and classes of a Python source path, or an empty set if the file is missing or unparseable.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `scripts/affected_tests.py` | The whole tool. Pure core + CLI wrapper in one module, matching `scripts/build_favicons.py`'s single-file convention. |
| Create `tests/test_affected_tests.py` | B3. Stub-based unit tests for the core; one fixture-repo integration test for the wrapper. |
| Modify `docs/development/testing.md` | B1. Adds the affected-tests practice. Part A already shipped the branch-gate, never-twice, one-run-at-a-time and troubleshooting content, which must survive. |

**Expected test totals after each task:** 10 → 34 → 49 → 58 → 70 → 77 → 88. Parametrized cases are counted expanded.

**Placement rule for every code addition:** unless a task says otherwise, **append at the end of the module**. Function bodies resolve names at call time, so order between `def`s never matters — but `_FULL_RUN_BECAUSE` (Task 5) is a module-level dict that dereferences `Reason` at import, so it must physically follow `class Reason`. Appending at the end always satisfies this; "append after `<the previous function>`" does not.

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


@pytest.fixture(autouse=True)
def _enable_db_access():
    """Shadow tests/conftest.py's autouse fixture, which gives every test a DB.

    Everything here tests stdlib-only pure functions. MEASURED: with this shadow
    the file passes in 0.82 s against a dead TEST_DATABASE_URL; without it the
    same file ERRORs after 12.08 s waiting for a database it never uses.
    """


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
        # Defensive: `git diff --name-status` emits C only under -C/--find-copies,
        # which the wrapper does not pass. Kept so the branch is not undefined if
        # the invocation ever gains that flag.
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

Expected: a collection error — `FileNotFoundError` raised by `_spec.loader.exec_module`, because `scripts/affected_tests.py` does not exist. (`spec_from_file_location` does not stat the path; it returns a valid spec backed by `SourceFileLoader`, so the error arrives at `exec_module`, not as a `None` spec.)

- [ ] **Step 3: Create the module**

Create `scripts/affected_tests.py`. The import block is exactly:

```python
import fnmatch
from pathlib import PurePosixPath
```

Full file:

```python
"""Suggest the pytest commands worth running for a diff. Advisory, never authoritative.

    uv run python scripts/affected_tests.py              # vs origin/master
    uv run python scripts/affected_tests.py --base HEAD~3

CI's full suite stays the gate; this only decides what is worth running locally
while iterating. It is deliberately biased toward visibility: a path no rule can
decide is reported as unmapped rather than dropped.

Three structural decisions, each measured, each wrong in an earlier draft:

* The corpus comes from `git ls-files`, NEVER a filesystem walk. A walk also
  descends into `.venv/` and into any nested git worktrees under
  `.claude/worktrees/`. Both are gitignored and pytest skips them, but a walk
  emits node IDs pointing into a virtualenv or another branch. MEASURED in the
  main checkout: 647 tracked test files against 3,197 seen by a walk.

* Unit/e2e classification is NON-exclusive -- a file may be suggested in both
  commands. MEASURED: `tests/test_tabs_editor_dnd.py` collects 10 non-e2e tests
  and 2 e2e ones. Classifying it "e2e" puts it only in the `-m e2e` command,
  where the other 10 are deselected: selected nowhere, silently.

* An empty candidate list emits NO command. Interpolating an empty file list
  yields a bare `uv run pytest` -- the whole unit selection, silently, for a diff
  that mapped nothing.

Purity: `normalize_name_status`, `map_paths` and `render_commands` do no I/O.
Everything touching git or the filesystem lives in the wrapper at the bottom and
reaches the core through the `search` and `module_symbols` callables, so the
rules are testable against literal stubs instead of a fixture repository.
"""

import fnmatch
from pathlib import PurePosixPath

# Mirrors `python_files` in pyproject.toml's [tool.pytest.ini_options]. pytest
# matches this against the BASENAME, which is the whole point of the predicate
# below: "lives in tests/" is a different rule and gets
# tests/capture_help_screenshots.py wrong.
PYTHON_FILES_GLOB = "test_*.py"


def is_test_file(path: str) -> bool:
    """Whether pytest would collect `path` as a test module."""
    # fnmatchcase, NOT fnmatch: fnmatch applies os.path.normcase, so it
    # case-folds on Windows and does not on Linux. VERIFIED: "Test_Foo.py"
    # matches "test_*.py" under fnmatch on Windows and not under fnmatchcase.
    # All four predicates in this module are case-sensitive, like full_match,
    # so a dev box and CI agree.
    return fnmatch.fnmatchcase(PurePosixPath(path).name, PYTHON_FILES_GLOB)


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

Expected: PASS, **10** tests.

- [ ] **Step 5: Falsify — one mutant per behaviour-defining test**

Apply each mutant, confirm the named test goes RED, revert.

| Mutant | Must turn red |
|---|---|
| `if code == "D" and is_test_file(path)` → `if code == "D"` | `test_a_deleted_source_file_is_retained` |
| `if code == "D" and is_test_file(path)` → delete the branch | `test_a_deleted_test_file_is_dropped` |
| `PYTHON_FILES_GLOB = "*.py"` | `test_a_test_named_helper_..._is_not_a_test_file` |
| In the `R`/`C` branch, `path = parts[2]` → `path = parts[1]` | `test_rename_follows_to_the_new_path`, `test_copy_follows_to_the_new_path` |
| Drop the `if path not in out` guard (append unconditionally) | `test_duplicates_collapse_preserving_first_order` |
| Drop the `if len(parts) < 2: continue` guard | `test_blank_and_malformed_lines_are_ignored` |

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
- Produces: `Reason` (StrEnum: `NONE`, `GLOBAL`, `CAPPED`); `Result` (frozen dataclass: `unit_files`, `e2e_files`, `unmapped` as `tuple[str, ...]`, plus `unit_reason`, `e2e_reason` as `Reason`); `is_global_path(path: str) -> bool`; `map_paths(paths, search, module_symbols) -> Result` handling only the global case so far.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
Reason = affected_tests.Reason
Result = affected_tests.Result
is_global_path = affected_tests.is_global_path
map_paths = affected_tests.map_paths


def no_hits(term):
    """A `search` stub finding nothing -- including an empty corpus."""
    return set()


def no_symbols(path):
    """A `module_symbols` stub finding nothing."""
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
            # A per-app conftest is not the root one. Safe only while no
            # per-app conftest defines an AUTOUSE fixture -- one that did
            # would meet the membership criterion and belong in the class.
            # VERIFIED: today only conftest.py and tests/conftest.py exist,
            # and both are already members.
            "courses/tests/conftest.py",
            "templates/courses/detail.html",
            "templates/allauth/account/login.html",
        ],
    )
    def test_non_members(self, path):
        assert not is_global_path(path)

    def test_star_does_not_cross_a_directory_separator(self):
        # `templates/_*.html` must not match a file nested under a `_`-prefixed
        # directory. VERIFIED: fnmatch's `*` crosses `/` and would match this;
        # PurePosixPath.full_match does not.
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
        result = map_paths(["courses/models.py", "config/urls.py"], no_hits, no_symbols)
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

The import block becomes exactly:

```python
import fnmatch
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
```

Append at the end of the module:

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
    """Map changed paths to candidate test files. Pure -- all I/O is injected.

    On the GLOBAL path `unmapped` is deliberately left empty rather than being
    populated: reporting it would mean running every per-path rule anyway, and
    the answer is already "run everything", which no per-path detail refines.
    This is the one place the bias-toward-visibility rule is traded away, and
    it is traded for the short-circuit that keeps a confidently-wrong list off
    the screen.
    """
    if any(is_global_path(p) for p in paths):
        return Result((), (), (), Reason.GLOBAL, Reason.GLOBAL)
    return Result((), (), (), Reason.NONE, Reason.NONE)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, **34** tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Delete the `if any(is_global_path(p) ...)` block | `test_a_global_path_sets_both_reasons_to_global`, `test_the_short_circuit_beats_the_module_rule` |
| Swap `full_match` for `fnmatch.fnmatch` in `is_global_path` | `test_star_does_not_cross_a_directory_separator` |
| Remove `"config/urls.py"` from `GLOBAL_PATHS` | `test_one_global_path_among_ordinary_ones_still_short_circuits` |
| Remove the `locale/**/*.mo` glob | `test_a_binary_catalog_is_global_not_unmapped` |
| Change `path in GLOBAL_PATHS` to a `PurePosixPath(path).name` comparison | `test_non_members[courses/tests/conftest.py]` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
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
- Produces: `import_path(path: str) -> str`; `map_one(path, search, module_symbols) -> set[str]`; constants `CORPUS_SENTINEL`, `MIGRATION_GLOB = "**/migrations/*.py"`, `MIGRATION_TESTS_GLOB = "tests/test_transfer*.py"`, `FILENAME_SUFFIXES = frozenset({".html", ".css", ".js"})`. `map_paths` now populates `unmapped` and an internal candidate list.

`map_one` takes exactly `(path, search, module_symbols)` — no corpus parameter. The migration rule reaches the corpus through `search(CORPUS_SENTINEL)`, per the contract fixed in Global Constraints.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_affected_tests.py`:

```python
import_path = affected_tests.import_path
map_one = affected_tests.map_one

FAKE_CORPUS = {
    "tests/test_transfer_export.py",
    "tests/test_transfer_import.py",
    "tests/test_builder.py",
    "tests/test_e2e_builder.py",
}


def make_search(index):
    """Build a `search` stub from {term: {files}}, honouring the corpus sentinel."""

    def search(term):
        if term == affected_tests.CORPUS_SENTINEL:
            return set(index.get(term, FAKE_CORPUS))
        return set(index.get(term, set()))

    return search


def corpus_only_search(term):
    """Answers the corpus query; finds nothing by content."""
    if term == affected_tests.CORPUS_SENTINEL:
        return set(FAKE_CORPUS)
    return set()


def corpus_plus_everything_search(term):
    """Answers the corpus query; claims every content term hits test_builder.py."""
    if term == affected_tests.CORPUS_SENTINEL:
        return set(FAKE_CORPUS)
    return {"tests/test_builder.py"}


class TestImportPath:
    def test_dots_replace_separators_and_the_suffix_is_dropped(self):
        assert import_path("courses/services/builder.py") == "courses.services.builder"

    def test_a_package_init_maps_to_the_package(self):
        assert import_path("courses/services/__init__.py") == "courses.services"


class TestMapOne:
    def test_a_test_file_maps_to_itself(self):
        assert map_one("tests/test_builder.py", corpus_only_search, no_symbols) == {
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
        hits = map_one(
            "courses/migrations/0055_thing.py", corpus_only_search, no_symbols
        )
        assert hits == {
            "tests/test_transfer_export.py",
            "tests/test_transfer_import.py",
        }

    def test_a_migration_does_not_fall_through_to_the_module_rule(self):
        # It is a .py file; ordering matters. Even a search that claims every
        # term hits test_builder.py must not pull it in.
        hits = map_one(
            "courses/migrations/0055_thing.py",
            corpus_plus_everything_search,
            no_symbols,
        )
        assert "tests/test_builder.py" not in hits

    @pytest.mark.parametrize(
        "path",
        [
            "courses/migrations_helpers/thing.py",  # near-miss directory name
            "courses/migrations/sub/thing.py",  # `*` must not cross a separator
        ],
    )
    def test_a_near_miss_path_is_not_treated_as_a_migration(self, path):
        # Pins the NON-match side, so a later loosening to `**/migrations/**`
        # cannot pass unnoticed.
        search = make_search({import_path(path): {"tests/test_builder.py"}})
        assert map_one(path, search, no_symbols) == {"tests/test_builder.py"}

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'import_path'`.

- [ ] **Step 3: Implement the rules**

No new imports. Append at the end of the module:

```python
# A `search` implementation or stub returns the ENTIRE corpus for this sentinel.
# The migration rule expands a glob over test-file NAMES, which a content search
# cannot express; this keeps the injected dependencies at two rather than adding
# a fourth parameter for one rule. The value is not a plausible search term.
CORPUS_SENTINEL = "\x00corpus"

MIGRATION_GLOB = "**/migrations/*.py"
MIGRATION_TESTS_GLOB = "tests/test_transfer*.py"
FILENAME_SUFFIXES = frozenset({".html", ".css", ".js"})


def import_path(path: str) -> str:
    """`courses/services/builder.py` -> `courses.services.builder`."""
    p = PurePosixPath(path)
    # A package __init__.py yields the bare package name (`courses`, `core`),
    # which is a broad term: expect the breadth cap to absorb it and report a
    # full run. That is the honest answer for a package-wide change, not a bug.
    p = p.parent if p.name == "__init__.py" else p.with_suffix("")
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
            for f in search(CORPUS_SENTINEL)
            if PurePosixPath(f).full_match(MIGRATION_TESTS_GLOB)
        }

    if candidate.suffix == ".py":
        # Bounded to module-level PUBLIC defs and classes. Unbounded matching on
        # common names (Element, render, save, index) would select a large
        # fraction of the corpus -- indistinguishable from the full suite, and a
        # silent failure.
        hits: set[str] = set()
        for term in {import_path(path)} | module_symbols(path):
            hits |= search(term)
        return hits

    if candidate.suffix in FILENAME_SUFFIXES:
        return search(candidate.name)

    # Binary and unknown suffixes map to nothing and are reported as unmapped by
    # the caller -- never silently dropped.
    return set()
```

Replace the body of `map_paths` **after** the global short-circuit — that is, replace the single line `return Result((), (), (), Reason.NONE, Reason.NONE)` with:

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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, **49** tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Move the migration branch below the `.py` branch | `test_a_migration_does_not_fall_through_to_the_module_rule` |
| `MIGRATION_GLOB` → `"**/migrations/**"` | `test_a_near_miss_path_is_not_treated_as_a_migration[courses/migrations/sub/thing.py]` |
| Drop `| module_symbols(path)` from the term set | `test_a_module_maps_to_tests_referencing_its_public_symbols` |
| Drop `{import_path(path)}` from the term set | `test_a_module_maps_to_tests_referencing_its_import_path` |
| Delete the `__init__.py` branch in `import_path` | `test_a_package_init_maps_to_the_package` |
| Drop the `FILENAME_SUFFIXES` branch | `test_a_template_maps_to_tests_referencing_its_filename`, both `test_css_and_js_map_by_filename` cases |
| Return `{path}` instead of `set()` in the final fallthrough | `test_a_binary_or_unknown_suffix_maps_to_nothing` |
| Append to `candidates` instead of `unmapped` on empty `hits` | `test_a_path_that_maps_to_nothing_is_reported_unmapped` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
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

    def test_a_marked_file_not_named_test_e2e_goes_to_BOTH(self):
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

    def test_e2e_at_and_over_the_cap(self):
        at = [f"tests/test_e2e_m{i:03d}.py" for i in range(affected_tests.E2E_CAP)]
        over = at + ["tests/test_e2e_extra.py"]
        at_result = map_paths(
            ["courses/models.py"], make_search({"courses.models": set(at)}), no_symbols
        )
        over_result = map_paths(
            ["courses/models.py"],
            make_search({"courses.models": set(over)}),
            no_symbols,
        )
        assert at_result.e2e_reason is Reason.NONE
        assert over_result.e2e_reason is Reason.CAPPED

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

No new imports. Append at the end of the module:

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

    The distinction is also unnecessary. MEASURED: three files carry a
    module-level `pytestmark = pytest.mark.e2e` while NOT being named
    `test_e2e_*` -- tests/test_link_apply.py, test_link_dialog_behaviour.py and
    test_table_grid_algebra.py -- and each collects zero non-e2e tests. Routing
    them to BOTH is still correct: the surplus unit command simply selects
    nothing, which is exactly what the exit-5 caveat on that command covers.
    """
    # Once, not per file -- the wrapper's implementation scans the whole corpus.
    marked = search(E2E_MARKER)
    unit: list[str] = []
    e2e: list[str] = []
    for path in candidates:
        if fnmatch.fnmatchcase(PurePosixPath(path).name, E2E_NAME_GLOB):
            e2e.append(path)
        elif path in marked:
            unit.append(path)
            e2e.append(path)
        else:
            unit.append(path)
    return unit, e2e
```

Then in `map_paths`, replace the **final two lines** (`ordered = sorted(set(candidates))` and the `return Result(...)` that follows it) with:

```python
    ordered = sorted(set(candidates))
    unit, e2e = classify(ordered, search)

    unit_reason = Reason.CAPPED if len(unit) > UNIT_CAP else Reason.NONE
    e2e_reason = Reason.CAPPED if len(e2e) > E2E_CAP else Reason.NONE

    return Result(tuple(unit), tuple(e2e), tuple(unmapped), unit_reason, e2e_reason)
```

Capped lists are **retained** in the `Result` rather than emptied; `render_commands` (Task 5) emits the full run but prints a short preview of what was capped, so the retention is observable.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, **58** tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Make the `elif path in marked` branch append to `e2e` only (exclusive) | `test_a_marked_file_not_named_test_e2e_goes_to_BOTH` |
| `E2E_NAME_GLOB` → `"test_e2e*.py"` | `test_the_trailing_underscore_in_the_name_glob_is_required` |
| Move `marked = search(E2E_MARKER)` inside the loop | `test_the_marker_search_happens_once_not_per_file` |
| `>` → `>=` in the unit cap | `test_unit_at_the_cap_is_not_capped` |
| `>` → `>=` in the e2e cap | `test_e2e_at_and_over_the_cap` |
| Use one shared `reason` for both selections | `test_the_caps_are_independent` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
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
- Produces: `render_commands(result: Result) -> str`; constants `PYTEST = "uv run pytest"`, `E2E_FLAG = " -m e2e"`, `EXIT5_NOTE`, `FULL_UNIT_COMMAND`, `FULL_E2E_COMMAND`.

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
        assert "-m e2e" in e2e_line

    def test_both_commands_carry_the_exit_5_caveat(self):
        # Not just the e2e one: non-exclusive classification puts every
        # marked file into both selections, and three such files collect ZERO
        # non-e2e tests -- so a diff touching only those emits a unit command
        # whose every file is deselected by `-m 'not e2e'`.
        result = Result(
            ("tests/test_a.py",),
            ("tests/test_e2e_b.py",),
            (),
            Reason.NONE,
            Reason.NONE,
        )
        out = render_commands(result)
        assert out.count(affected_tests.EXIT5_NOTE) == 2

    def test_every_emitted_command_line_is_pasteable(self):
        # VERIFIED: appending the caveat to the command line yields
        # `bash: syntax error near unexpected token '('`. The one thing this
        # tool exists to do is print a command you can paste.
        result = Result(
            ("tests/test_a.py",),
            ("tests/test_e2e_b.py",),
            (),
            Reason.NONE,
            Reason.NONE,
        )
        for line in render_commands(result).splitlines():
            stripped = line.strip()
            if stripped.startswith("uv run pytest"):
                assert "(" not in stripped and ")" not in stripped

    def test_the_caveat_is_a_comment_on_its_own_line(self):
        result = Result(("tests/test_a.py",), (), (), Reason.NONE, Reason.NONE)
        note_lines = [
            ln.strip()
            for ln in render_commands(result).splitlines()
            if affected_tests.EXIT5_NOTE in ln
        ]
        assert note_lines == [affected_tests.EXIT5_NOTE]
        assert note_lines[0].startswith("#")

    def test_an_empty_selection_with_nothing_unmapped_points_at_nothing(self):
        # A diff touching only e2e files leaves unit empty with an empty
        # unmapped, so the message must not send the reader to a section that
        # is never printed.
        result = Result((), ("tests/test_e2e_b.py",), (), Reason.NONE, Reason.NONE)
        out = render_commands(result)
        assert "unit: nothing mapped" in out
        assert "see unmapped" not in out

    def test_an_empty_unit_selection_emits_no_command(self):
        # Interpolating an empty file list yields a bare `uv run pytest`, i.e.
        # the whole unit selection, silently, for a diff that mapped nothing.
        result = Result(
            (), ("tests/test_e2e_b.py",), ("README.md",), Reason.NONE, Reason.NONE
        )
        out = render_commands(result)
        assert "unit: nothing mapped" in out
        unit_lines = [
            ln
            for ln in out.splitlines()
            if ln.strip().startswith("uv run pytest") and "-m e2e" not in ln
        ]
        assert unit_lines == []

    def test_an_empty_e2e_selection_emits_no_command(self):
        result = Result(
            ("tests/test_a.py",), (), ("README.md",), Reason.NONE, Reason.NONE
        )
        out = render_commands(result)
        assert "e2e: nothing mapped" in out
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
        assert "unit: nothing mapped" not in out
        assert "e2e: nothing mapped" not in out

    def test_capped_emits_the_full_run_for_that_selection_only(self):
        files = tuple(f"tests/test_m{i:03d}.py" for i in range(41))
        result = Result(files, ("tests/test_e2e_b.py",), (), Reason.CAPPED, Reason.NONE)
        out = render_commands(result)
        # Assert on the UNIT block specifically. A bare `"uv run pytest" in out`
        # would be satisfied by the e2e line and could never fail.
        assert "unit: full run -- too many candidates to be meaningful" in out
        assert "uv run pytest tests/test_m000.py" not in out
        assert "41 candidate(s) not listed" in out
        assert "uv run pytest tests/test_e2e_b.py -m e2e" in out

    def test_unmapped_paths_are_listed(self):
        result = Result(
            ("tests/test_a.py",),
            (),
            ("logo.png", "README.md"),
            Reason.NONE,
            Reason.NONE,
        )
        out = render_commands(result)
        assert "logo.png" in out
        assert "README.md" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'render_commands'`.

- [ ] **Step 3: Implement emission**

No new imports. **Append at the end of the module, after `map_paths`** — `_FULL_RUN_BECAUSE` is a module-level dict that dereferences `Reason` at import time, so placing it earlier (following the "after the previous function" pattern) raises `NameError` on import and Step 4 becomes unreachable.

Note the **single outer quotes** on `EXIT5_NOTE` — `ruff format` rewrites the escaped-double-quote form and would fail `--check`.

```python
PYTEST = "uv run pytest"
E2E_FLAG = " -m e2e"
FULL_UNIT_COMMAND = PYTEST
FULL_E2E_COMMAND = f"{PYTEST}{E2E_FLAG}"

# A `#` comment on its OWN line, never appended to the command line. VERIFIED:
# appending it inline produces `bash: syntax error near unexpected token '('`,
# because `(` is a metacharacter in both bash and PowerShell -- so the one thing
# this tool exists to do, print a command you can paste, would not work. As a
# leading `#` line it survives a two-line paste in both shells.
EXIT5_NOTE = '# exit code 5 means "nothing selected", not "green"'

_FULL_RUN_BECAUSE = {
    Reason.GLOBAL: "a global blast-radius path changed",
    Reason.CAPPED: "too many candidates to be meaningful",
}


def _render_one(
    label: str,
    files: tuple[str, ...],
    reason: Reason,
    full_command: str,
    suffix: str,
) -> list[str]:
    """Render one selection's block.

    The REASON is checked before emptiness. A GLOBAL result carries empty file
    tuples by construction, so testing emptiness first would print "nothing
    mapped" for the one input that means "run everything".

    `full_command` is passed in rather than composed here, so FULL_UNIT_COMMAND
    and FULL_E2E_COMMAND stay the single source of truth for the full-run lines.
    """
    if reason in _FULL_RUN_BECAUSE:
        lines = [f"{label}: full run -- {_FULL_RUN_BECAUSE[reason]}"]
        if files:
            preview = ", ".join(files[:3])
            lines.append(f"    # {len(files)} candidate(s) not listed: {preview}, ...")
        lines.append(f"    {EXIT5_NOTE}")
        lines.append(f"    {full_command}")
        return lines
    if not files:
        # No "see unmapped" pointer here: the unmapped section is only printed
        # when it is non-empty, and a diff touching only e2e files leaves this
        # selection empty with nothing unmapped to point at.
        return [f"{label}: nothing mapped"]
    joined = " ".join(files)
    return [
        f"{label}: {len(files)} file(s)",
        f"    {EXIT5_NOTE}",
        f"    {PYTEST} {joined}{suffix}",
    ]


def render_commands(result: Result) -> str:
    """Render the advisory output. Pure.

    Every emitted command sits alone on its line, with the exit-5 caveat on the
    preceding line as a `#` comment, so a two-line paste runs in bash and
    PowerShell alike.
    """
    lines: list[str] = []
    lines += _render_one(
        "unit", result.unit_files, result.unit_reason, FULL_UNIT_COMMAND, ""
    )
    lines.append("")
    lines += _render_one(
        "e2e", result.e2e_files, result.e2e_reason, FULL_E2E_COMMAND, E2E_FLAG
    )
    if result.unmapped:
        lines.append("")
        lines.append("unmapped (no rule matched -- check these by hand):")
        lines += [f"    {p}" for p in result.unmapped]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, **70** tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Move the `if not files` check above the `if reason in _FULL_RUN_BECAUSE` check | `test_global_emits_the_full_run_for_both_despite_empty_file_tuples` |
| Make `if not files` fall through and interpolate the empty list | `test_an_empty_unit_selection_emits_no_command` |
| `_FULL_RUN_BECAUSE` keeps only `Reason.GLOBAL` | `test_capped_emits_the_full_run_for_that_selection_only` |
| Delete the `if files:` preview block | `test_capped_emits_the_full_run_for_that_selection_only` |
| `E2E_FLAG = ""` | `test_the_e2e_command_always_carries_the_marker` |
| Append `EXIT5_NOTE` to the e2e block only | `test_both_commands_carry_the_exit_5_caveat` |
| Drop the `if result.unmapped` block | `test_unmapped_paths_are_listed` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
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
- Produces: `git_lines(args, cwd) -> list[str]`; `untracked_paths(cwd) -> list[str]`; `_die(message)`; `build_corpus(cwd) -> set[str]`; `make_search(corpus, cwd) -> Callable[[str], set[str]]`; `read_module_symbols(cwd) -> Callable[[str], set[str]]`; `resolve_base(base, cwd) -> str`; `main(argv=None) -> int`.

Note the production `make_search` shares its name with the test module's stub factory; the tests alias it as `make_corpus_search` to keep them distinct.

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
        (tmp_path / "test_a.py").write_text(
            "from courses import render\n", encoding="utf-8"
        )
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
        assert search(affected_tests.CORPUS_SENTINEL) == {"test_a.py", "test_b.py"}

    def test_a_returned_set_cannot_poison_the_cache(self, tmp_path):
        # Results are memoized; handing callers the cached set itself would let
        # one mutation corrupt every later query for that term.
        (tmp_path / "test_a.py").write_text("render\n", encoding="utf-8")
        search = make_corpus_search({"test_a.py"}, tmp_path)
        first = search("render")
        first.add("bogus.py")
        assert search("render") == {"test_a.py"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: `AttributeError: module 'affected_tests' has no attribute 'build_corpus'`.

- [ ] **Step 3: Implement the wrapper**

The import block becomes exactly this — alphabetical, one name per line (`isort.force-single-line`):

```python
import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from pathlib import PurePosixPath
```

Append at the end of the module:

```python
def git_lines(args: list[str], cwd: Path) -> list[str]:
    """Run a git command and return its stdout lines. Raises on failure."""
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no untrusted input
        # -c core.quotepath=false: with git's default, a path containing
        # non-ASCII bytes is emitted double-quoted and octal-escaped
        # ("locale/pl/\305\233.po"), which matches no rule and would be
        # reported as a mangled unmapped path.
        ["git", "-c", "core.quotepath=false", *args],  # noqa: S607 -- git on PATH
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.splitlines()


def untracked_paths(cwd: Path) -> list[str]:
    """Files git can see but does not track. --exclude-standard honours
    .gitignore, which is what keeps .venv and the nested worktrees out."""
    return [
        p for p in git_lines(["ls-files", "--others", "--exclude-standard"], cwd) if p
    ]


def build_corpus(cwd: Path) -> set[str]:
    """Every file pytest would collect as a test module -- tracked AND untracked.

    `git ls-files`, never a filesystem walk: a walk descends into `.venv/` and
    into any nested worktrees under `.claude/worktrees/`, both gitignored and
    both skipped by pytest, and emits node IDs pointing outside this branch.

    The untracked half is here for CLASSIFICATION, not just for the diff. A
    brand-new `tests/test_thing.py` carrying a module-level `pytest.mark.e2e`
    reaches the candidate list through `main`'s untracked union, but if it is
    absent from the corpus then `search(E2E_MARKER)` cannot see it, `classify`
    treats it as unmarked, and it goes to the unit selection alone -- where
    `-m 'not e2e'` deselects every test in it. Selected nowhere, silently: the
    exact failure the non-exclusive rule exists to prevent.
    """
    tracked = git_lines(["ls-files"], cwd)
    return {p for p in [*tracked, *untracked_paths(cwd)] if is_test_file(p)}


def make_search(corpus: set[str], cwd: Path) -> Callable[[str], set[str]]:
    """Build a word-boundary `search` over the corpus, reading each file once.

    Memoized by term: the module rule issues one query per import path plus one
    per public symbol, so a broad diff repeats terms across paths.
    """
    contents: dict[str, str] = {}
    for rel in corpus:
        try:
            contents[rel] = (cwd / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            contents[rel] = ""
    cache: dict[str, set[str]] = {}

    def search(term: str) -> set[str]:
        if term == CORPUS_SENTINEL:
            return set(corpus)
        if term not in cache:
            # Word boundaries, and re.escape -- otherwise "pytest.mark.e2e" is a
            # regex whose dots match any character.
            pattern = re.compile(rf"\b{re.escape(term)}\b")
            # The `term in t` pre-filter is the reason this is usable: a plain
            # substring scan is far cheaper than a regex pass and rejects almost
            # every file before the regex runs. It cannot change the result --
            # \bTERM\b can only match where TERM occurs. MEASURED over the
            # 647-file corpus, 18 terms: 2.26 s without it, 0.09 s with. 25x.
            #
            # re.escape is therefore belt-and-braces: the pre-filter already
            # rejects any file lacking the literal term, so an unescaped `.`
            # cannot match a stray character in practice. It stays because the
            # pattern must not depend on that argument staying true if the
            # pre-filter is ever removed.
            cache[term] = {
                rel for rel, t in contents.items() if term in t and pattern.search(t)
            }
        return set(cache[term])  # a copy: callers must not mutate the cache

    return search


def read_module_symbols(cwd: Path) -> Callable[[str], set[str]]:
    """Build a `module_symbols` that AST-parses a source path.

    Module-level PUBLIC defs and classes only -- no methods, no private names.
    Unbounded matching on common names (Element, render, save, index) would
    select a large fraction of the corpus, indistinguishable from a full run.
    """

    def module_symbols(path: str) -> set[str]:
        try:
            tree = ast.parse((cwd / path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            # A DELETED source file is retained by normalize_name_status and
            # reaches this rule while no longer being on disk. Degrade to the
            # import-path term rather than crashing the whole run.
            return set()
        wanted = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        return {
            node.name
            for node in tree.body  # tree.body, NOT ast.walk: module level only
            if isinstance(node, wanted) and not node.name.startswith("_")
        }

    return module_symbols


def _die(message: str) -> None:
    raise SystemExit(f"affected_tests: {message}")


def resolve_base(base: str, cwd: Path) -> str:
    """Resolve the merge base with `base`. Every failure is loud.

    `origin/master`, not local `master`, which is routinely stale in a worktree.
    """
    try:
        git_lines(["rev-parse", "--verify", f"{base}^{{commit}}"], cwd)
    except subprocess.CalledProcessError:
        _die(
            f"base ref {base!r} does not exist.\n"
            f"  Try `git fetch origin`, or pass --base <ref>.\n"
            f"  Refusing to continue: an unresolvable base yields an empty diff, "
            f"which would look like 'nothing changed'."
        )
    try:
        merge_base = git_lines(["merge-base", base, "HEAD"], cwd)
    except subprocess.CalledProcessError:
        merge_base = []
    if not merge_base or not merge_base[0].strip():
        _die(f"no merge base between {base!r} and HEAD (unrelated histories?)")
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
        help="repository root (default: the git root containing the cwd)",
    )
    args = parser.parse_args(argv)

    cwd = args.repo
    if cwd is None:
        try:
            cwd = Path(git_lines(["rev-parse", "--show-toplevel"], Path.cwd())[0])
        except (subprocess.CalledProcessError, IndexError):
            _die("not inside a git repository; pass --repo <path>")

    base = resolve_base(args.base, cwd)
    changed = normalize_name_status(git_lines(["diff", "--name-status", base], cwd))
    # Untracked files are invisible to `git diff` (VERIFIED), and a brand-new
    # test or source file that has not been `git add`-ed yet is the single most
    # common iterating state. Reporting "nothing to run" for it would be exactly
    # the silent omission this tool refuses everywhere else, so they are folded
    # in as additions. --exclude-standard honours .gitignore, which is what keeps
    # .venv and the nested worktrees out.
    for path in untracked_paths(cwd):
        if path not in changed:
            changed.append(path)
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

Expected: PASS, **77** tests.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| Drop `re.escape` **and** the `term in t` pre-filter together | `test_a_dotted_term_is_escaped_not_treated_as_regex` |
| Drop the `\b` anchors | `test_matches_on_word_boundaries` |
| Remove the `not node.name.startswith("_")` filter | `test_module_level_public_defs_and_classes_only` |
| `tree.body` → `ast.walk(tree)` | `test_module_level_public_defs_and_classes_only` (picks up `inner_fn`, `a_method`) |
| Remove the `except (OSError, SyntaxError, ValueError)` guard | `test_an_unparseable_module_yields_nothing_rather_than_raising`, `test_a_missing_module_yields_nothing` |
| `return set(cache[term])` → `return cache[term]` | `test_a_returned_set_cannot_poison_the_cache` |
| Drop the `CORPUS_SENTINEL` branch | `test_the_corpus_sentinel_returns_the_whole_corpus` |

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "feat(scripts): add the affected-tests CLI wrapper

Corpus from git ls-files, never a walk -- a walk descends into .venv and any
nested worktrees. A missing or unmergeable base ref is a hard error, never a
silent empty diff."
```

---

## Task 7: Integration test against a deterministic fixture repository

**Files:**
- Test: `tests/test_affected_tests.py`

**Interfaces:**
- Consumes: `main`, `build_corpus`, `resolve_base` (Task 6).
- Produces: nothing consumed downstream.

A **fixture repository built in `tmp_path`** with a known commit and a known `origin/master` — not "a real recent diff", whose content changes with every branch, making assertions either vacuous or perpetually broken.

- [ ] **Step 1: Add `import subprocess` to the header, then write the tests**

First **edit the existing import block** at the top of `tests/test_affected_tests.py` so it reads exactly:

```python
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
```

(Adding the import mid-file instead would trip `E402`.)

Then append:

```python
def run_git(cwd, *args):
    proc = subprocess.run(  # noqa: S603 -- fixed argv, tmp_path fixture repo
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # NOT check=True. It would carry stderr on the exception just fine
        # (VERIFIED) -- the reason is the SHAPE of the failure: a fixture
        # problem (an old git without `init -b`, a global commit.template, a
        # locked index) is not a test failing, and pytest.fail reports it as
        # one clear line instead of a CalledProcessError traceback.
        pytest.fail(f"git {' '.join(args)} failed:\n{proc.stderr}")


@pytest.fixture
def fixture_repo(tmp_path):
    """A deterministic repo with a known origin/master and one ignored worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "master")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "T")
    # A global commit.gpgsign or core.hooksPath would otherwise surface as a
    # fixture error rather than an assertion failure.
    run_git(repo, "config", "commit.gpgsign", "false")
    run_git(repo, "config", "core.hooksPath", "")

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
    (phantom / "test_phantom.py").write_text(
        "def test_p():\n    pass\n", encoding="utf-8"
    )
    run_git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    return repo


class TestCorpusExcludesIgnoredPaths:
    def test_a_nested_worktree_test_file_never_enters_the_corpus(self, fixture_repo):
        corpus = build_corpus(fixture_repo)
        assert corpus == {"tests/test_widget.py", "tests/test_e2e_widget.py"}

    def test_an_untracked_test_file_does_enter_the_corpus(self, fixture_repo):
        # Tracked-only would be wrong: classification reads the corpus, so an
        # untracked marked file would look unmarked. See the next test.
        (fixture_repo / "tests" / "test_fresh.py").write_text(
            "def test_f():\n    pass\n", encoding="utf-8"
        )
        assert "tests/test_fresh.py" in build_corpus(fixture_repo)

    def test_the_phantom_really_is_on_disk(self, fixture_repo):
        # Guards the guard: if the fixture stopped writing the phantom, the test
        # above would pass vacuously.
        phantom = (
            fixture_repo
            / ".claude"
            / "worktrees"
            / "other"
            / "tests"
            / "test_phantom.py"
        )
        assert phantom.exists()


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

    def test_the_diff_is_taken_from_the_fork_point_not_the_base_tip(
        self, fixture_repo, capsys
    ):
        # THE merge-base test. In every other scenario origin/master is an
        # ancestor of HEAD, so merge-base(origin/master, HEAD) == origin/master
        # and `return base` would pass everything -- leaving the stated
        # "merge-base with origin/master" constraint entirely unfalsified.
        #
        # Here origin/master ADVANCES onto a commit that is not in HEAD's
        # history. Diffing against its tip would report courses/on_master.py as
        # a deleted path (it is absent from HEAD); diffing against the fork
        # point correctly reports only what HEAD changed.
        run_git(fixture_repo, "checkout", "-q", "-b", "topic")
        (fixture_repo / "courses" / "models.py").write_text(
            "class Widget:\n    pass\n\n\ndef on_topic():\n    pass\n",
            encoding="utf-8",
        )
        run_git(fixture_repo, "add", "-A")
        run_git(fixture_repo, "commit", "-q", "-m", "topic work")

        run_git(fixture_repo, "checkout", "-q", "master")
        (fixture_repo / "courses" / "on_master.py").write_text(
            "def only_on_master():\n    pass\n", encoding="utf-8"
        )
        run_git(fixture_repo, "add", "-A")
        run_git(fixture_repo, "commit", "-q", "-m", "master work")
        run_git(fixture_repo, "update-ref", "refs/remotes/origin/master", "HEAD")
        run_git(fixture_repo, "checkout", "-q", "topic")

        assert affected_tests.main(["--repo", str(fixture_repo)]) == 0
        out = capsys.readouterr().out

        assert "on_master.py" not in out

    def test_an_untracked_marked_file_still_lands_in_both_selections(
        self, fixture_repo, capsys
    ):
        # THE untracked-classification case. This file is untracked (so it is
        # invisible to `git diff`), carries a MODULE-LEVEL e2e marker, and is
        # NOT named test_e2e_* -- so only the marker search can classify it. If
        # the corpus were tracked-only it would be routed to unit alone, where
        # `-m 'not e2e'` deselects everything in it: selected nowhere, silently.
        (fixture_repo / "tests" / "test_mixed_new.py").write_text(
            "import pytest\n\npytestmark = pytest.mark.e2e\n\n\n"
            "def test_m():\n    pass\n",
            encoding="utf-8",
        )

        assert affected_tests.main(["--repo", str(fixture_repo)]) == 0
        out = capsys.readouterr().out

        unit_line = next(
            ln for ln in out.splitlines() if ln.strip().startswith("uv run pytest")
        )
        assert "tests/test_mixed_new.py" in unit_line
        e2e_line = next(
            ln
            for ln in out.splitlines()
            if ln.strip().startswith("uv run pytest") and ln.rstrip().endswith("-m e2e")
        )
        assert "tests/test_mixed_new.py" in e2e_line

    def test_an_explicit_base_override_is_honoured(self, fixture_repo, capsys):
        # The --base flag is a stated requirement, but only its FAILURE path was
        # covered -- code that ignored args.base and always used origin/master
        # would have gone unnoticed.
        (fixture_repo / "courses" / "models.py").write_text(
            "class Widget:\n    pass\n\n\ndef helper():\n    pass\n", encoding="utf-8"
        )
        run_git(fixture_repo, "add", "-A")
        run_git(fixture_repo, "commit", "-q", "-m", "change")

        assert affected_tests.main(["--repo", str(fixture_repo), "--base", "HEAD"]) == 0
        out = capsys.readouterr().out

        # Against HEAD itself there is no diff, so the default (origin/master,
        # one commit back) and this must give different answers.
        assert "nothing to run" in out

    def test_a_missing_base_ref_fails_loudly(self, fixture_repo):
        with pytest.raises(SystemExit) as excinfo:
            affected_tests.main(["--repo", str(fixture_repo), "--base", "origin/nope"])
        assert "does not exist" in str(excinfo.value)

    def test_an_untracked_new_test_file_still_reaches_the_selection(
        self, fixture_repo, capsys
    ):
        # `git diff` cannot see it (VERIFIED), yet "I just created this test" is
        # the most common iterating state. Without the ls-files --others union
        # the tool would answer "nothing to run".
        (fixture_repo / "tests" / "test_brand_new.py").write_text(
            "def test_n():\n    pass\n", encoding="utf-8"
        )

        assert affected_tests.main(["--repo", str(fixture_repo)]) == 0
        out = capsys.readouterr().out

        assert "uv run pytest tests/test_brand_new.py" in out
        # --exclude-standard must still keep the gitignored phantom out, and
        # this assertion is non-vacuous because the command list is non-empty.
        assert "test_phantom.py" not in out

    def test_a_clean_tree_reports_nothing_to_run_and_emits_no_command(
        self, fixture_repo, capsys
    ):
        # HEAD == origin/master, and the only untracked file is the gitignored
        # phantom the fixture wrote. This is the branch that would mask the
        # untracked-file gap, so it gets its own test -- and it doubles as proof
        # that --exclude-standard really excludes the phantom, since any leak
        # would make `changed` non-empty and suppress this message.
        assert affected_tests.main(["--repo", str(fixture_repo)]) == 0
        out = capsys.readouterr().out

        assert "nothing to run" in out
        assert "uv run pytest" not in out

    def test_a_docs_only_diff_emits_no_pytest_command(self, fixture_repo, capsys):
        (fixture_repo / "README.md").write_text("hi\n", encoding="utf-8")
        run_git(fixture_repo, "add", "-A")
        run_git(fixture_repo, "commit", "-q", "-m", "docs")

        assert affected_tests.main(["--repo", str(fixture_repo)]) == 0
        out = capsys.readouterr().out

        assert "uv run pytest" not in out
        assert "unit: nothing mapped" in out
        assert "e2e: nothing mapped" in out
        assert "README.md" in out
```

- [ ] **Step 2: Run the tests — PASS is the expected outcome**

Run: `uv run pytest tests/test_affected_tests.py -k "ExcludesIgnored or WrapperIntegration" -v`

Expected: **PASS, 11 tests.** These are new tests over code that Tasks 1–6 already shipped, so there is no red phase to stage here — a failure means a real defect in Tasks 1–6, or a genuine environment difference (path separators, `git diff` against a merge base equal to HEAD). Step 5's falsification is what proves these tests guard something.

- [ ] **Step 3: Fix anything the integration surfaces**

No new production code is planned. If a test fails, diagnose and fix `scripts/affected_tests.py`. Known candidates: git emits forward slashes on Windows (VERIFIED — no normalization needed), and `commit.gpgsign` (already neutralized in the fixture).

- [ ] **Step 4: Run the whole file**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, **88** tests — or 88 plus any **new test** Step 3 added while fixing a real defect. An assertion added to an existing test leaves the count at 88. Record the total; a higher number is not itself a failure.

- [ ] **Step 5: Falsify**

| Mutant | Must turn red |
|---|---|
| `build_corpus` walks with `Path(cwd).rglob("test_*.py")` instead of `git ls-files` | `test_a_nested_worktree_test_file_never_enters_the_corpus` |
| `resolve_base` returns `""` on a missing ref instead of calling `_die` | `test_a_missing_base_ref_fails_loudly` |
| Delete the phantom write from the fixture | `test_the_phantom_really_is_on_disk` |
| `render_commands` interpolates an empty file list rather than the "nothing mapped" line | `test_a_docs_only_diff_emits_no_pytest_command` |
| Delete the `untracked` union from `main` | `test_an_untracked_new_test_file_still_reaches_the_selection` |
| Drop `--exclude-standard` from `untracked_paths` | `test_a_clean_tree_reports_nothing_to_run_and_emits_no_command`, `test_an_untracked_new_test_file_...` |
| `build_corpus` returns tracked files only (drop `untracked_paths`) | `test_an_untracked_test_file_does_enter_the_corpus`, `test_an_untracked_marked_file_still_lands_in_both_selections` |

**One mutant that does NOT work, recorded so nobody re-derives it.** "Make the `if not changed` branch fall through instead of returning" is *not* a valid mutant for `test_a_clean_tree_reports_nothing_to_run_and_emits_no_command`: falling through with an empty `changed` list produces `Result((), (), (), NONE, NONE)`, which renders `unit: nothing mapped` / `e2e: nothing mapped` and still emits no `uv run pytest` line — so both of that test's assertions hold and it stays green. The early `return 0` saves a wasted corpus build; it is not load-bearing for output. Deleting the whole block is the mutant that bites, because it removes the `nothing to run` message the first assertion requires.
| Delete the whole `if not changed:` block from `main` | `test_a_clean_tree_reports_nothing_to_run_and_emits_no_command` |
| `resolve_base` returns `base` instead of `merge_base[0]` | `test_the_diff_is_taken_from_the_fork_point_not_the_base_tip` |
| `main` passes the literal `"origin/master"` to `resolve_base` instead of `args.base` | `test_an_explicit_base_override_is_honoured` |

- [ ] **Step 6: Lint and commit**

```bash
# Step 3 authorises fixes to scripts/affected_tests.py -- lint and stage BOTH,
# or a fix made there is left uncommitted and the next task starts dirty.
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "test(scripts): integration-test affected_tests on a fixture repo

Deterministic tmp_path repo with a known origin/master, including a
gitignored nested-worktree test file that must never enter the corpus."
```

---

## Task 8: B1 — document the practice in `testing.md`

**Files:**
- Modify: `docs/development/testing.md`

Part A already shipped `### Troubleshooting`, `### One run at a time` and the `## What runs where` paragraphs. **All of that must survive.** This task edits two paragraphs and appends one new section.

- [ ] **Step 1: Record the before-state**

Run:
```bash
grep -nE '^#{1,4} ' docs/development/testing.md
```

Note the full heading list. `## What runs where` should be last. Keep this output — Step 4 compares against it.

(Lines 29 and 32 -- `# start (once per session)` and `# stop and wipe ...` -- are **bash comments inside the compose code fence**, and they appear in this output too: they begin `# `, so no `grep` anchor excludes them. VERIFIED. Ignore those two lines when comparing before against after; a line-oriented grep cannot tell fenced content from prose.)

- [ ] **Step 2: Append the new section**

Leave `## What runs where` and everything above it **unchanged**. Append the following to the end of the file (the outer fence below is four backticks so the inner ```bash block nests correctly — paste the inner content, not the outer fence):

````markdown
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
  — a binary asset, a new file type, something the tool does not understand.
  Judge those by hand rather than assuming they are safe.
- **A full run is a real answer — and it usually means "push".** Changing
  `conftest.py`, `config/settings/`, `config/urls.py`, `pyproject.toml` or a
  compiled `.mo` catalog can alter tests that never mention it, so the script
  stops mapping and tells you to run everything. Same when a selection exceeds
  its breadth cap: a list that long is no longer meaningfully narrower than the
  suite.

  This does **not** override the two rules above. A full-run answer normally
  means commit and let CI's 8m45s be the gate — that is what the branch gate is
  for. Run it locally only if you have not already spent your one full run this
  session, and only when you need the answer before pushing.
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
````

- [ ] **Step 3: Update the pointer in `## What runs where`**

**This is a sentence-level edit inside a wrapped paragraph, not a line replace.** The target sentence is the head of `docs/development/testing.md:89`, which reads in full:

```
Run the affected tests locally; let CI run the full suite. CI does both
```

and continues on the next two lines with `selections plus lint in about **8m45s**, in three parallel jobs, and it does not` / `consume your session.` Replacing the whole line would silently delete Part A's measured 8m45s sentence.

Replace **only** `Run the affected tests locally; let CI run the full suite.` with:

```
Run the affected tests locally — `scripts/affected_tests.py` below works out
which those are — and let CI run the full suite.
```

so the paragraph still ends with `CI does both selections plus lint in about **8m45s**, in three parallel jobs, and it does not consume your session.` Change nothing else in that section.

- [ ] **Step 4: Verify Part A's content survived**

Run:
```bash
grep -nE '^#{1,4} ' docs/development/testing.md
```

Expected: every heading from Step 1 is still present, in the same order, plus the two new ones (`## Which tests are affected`, `### Justify the selection before a slice`) at the end. Specifically confirm `### Troubleshooting` and `### One run at a time` are still there.

Then run:
```bash
grep -c 'affected_tests.py' docs/development/testing.md   # expect 3
grep -c 'REGRESSION' docs/development/testing.md          # expect 1
grep -c 'in about \*\*8m45s\*\*' docs/development/testing.md  # expect 1 -- the sentence Step 3 could have eaten
grep -c '8m45s' docs/development/testing.md               # expect 2 -- that one, plus the new section's own mention
grep -c 'connect_timeout' docs/development/testing.md     # expect 2 -- Part A troubleshooting intact
```

- [ ] **Step 5: Confirm nothing asserts on this file's prose**

Run: `git grep -n "What runs where" -- '*.py'`

Expected: no output. (A `--collect-only` probe would be the wrong tool here: `--collect-only` disables xdist, `addopts` already supplies `-q` so a second makes it `-qq`, and it would pay the full Django import cost to answer a question `git grep` answers in a second.)

- [ ] **Step 6: Commit**

```bash
git add docs/development/testing.md
git commit -m "docs(testing): document the affected-tests practice

Adds the script's usage and how to read it, plus the per-file justification
format and the regression-vs-migration classification it exists to enable."
```

---

## Task 9: Dogfood the tool on its own branch

**Files:**
- Modify: none, unless a defect surfaces.

The tool has never run against a real diff. This is the cheapest check that the rules behave on real input rather than stubs.

- [ ] **Step 1: Run it against this branch**

Run:
```bash
uv run python scripts/affected_tests.py --base origin/master
```

Record the full output verbatim in the task report.

- [ ] **Step 2: Check the answer against the rules**

The diff adds `scripts/affected_tests.py` and `tests/test_affected_tests.py`, and modifies `docs/development/testing.md` plus this plan file.

| Input path | Expected treatment |
|---|---|
| `tests/test_affected_tests.py` | test file → maps to itself → **unit *and* e2e**. It contains the literal string `pytest.mark.e2e` (in Task 6's `TestSearch` fixture text and Task 7's fixture-repo source), so the marker search matches it and non-exclusive classification routes it to both. |
| `scripts/affected_tests.py` | Python module → searched by import path `scripts.affected_tests` **and every public symbol it defines** |
| `docs/development/testing.md` | `.md` → no rule → **unmapped** |
| `docs/superpowers/plans/2026-08-07-affected-tests-workflow.md` | `.md` → **unmapped** |

**A substantial `-m e2e` command WILL therefore be printed — and it is a real browser run, not a no-op.** MEASURED against the live 647-file corpus before implementation: `scripts.affected_tests` → 0 hits, `main` → 14, `Reason` → 1, every other public symbol → 0, giving a union of **15**. `classify` then splits that union into roughly **10 unit and 6 e2e**, plus `tests/test_affected_tests.py` itself in **both** — so about **11 unit / 7 e2e**.

The six e2e files are `tests/test_e2e_builder_tree_layout.py`, `test_e2e_image_size.py`, `test_e2e_review.py`, `test_e2e_subjects.py`, `test_e2e_unit_nav.py` and `tests/test_link_dialog_behaviour.py`. **VERIFIED by collection: that command collects 78 real e2e tests.** An earlier draft of this plan predicted "it exits 5"; that was wrong, and acting on it would have launched a Playwright run — the exact wall-clock cost this whole design exists to eliminate.

Note also that 14 of the 15 union members match only the bare word `main`, so most are false positives — informative about the symbol rule's precision, and **not** a reason to change it in this task.

**Both a small unit list and `unit_reason = CAPPED` are acceptable outcomes, and the distinction is the point of this step.** This module's public symbols include deliberately generic names — `main`, `classify`, `search`, `Result`, `Reason` — and `\bmain\b` or `\bResult\b` may match many of the 647 corpus files. Decide as follows, and record which happened:

- **Not capped** — the measured expectation. The union is ~15 candidates, which `classify` splits into roughly **11 unit / 7 e2e**; confirm the unit list contains `tests/test_affected_tests.py` and that it also appears in the e2e list. Comparing the printed unit count against 15 would be wrong: 15 is the pre-classification union.
- **CAPPED** → **also working as designed.** The cap exists precisely to refuse a list that is no longer meaningfully narrower than the suite, and a module whose symbols are this generic is the honest case for it. Record the candidate count. Do **not** add a symbol stop-list in this task — that is a design change, and it belongs in a follow-up with its own measurement, not in a dogfood step.

- [ ] **Step 3: Time it, against a stated budget**

Run:
```bash
uv run python -c "import subprocess,time; t=time.perf_counter(); p=subprocess.run(['uv','run','python','scripts/affected_tests.py'],capture_output=True,text=True); print(f'{time.perf_counter()-t:.1f}s exit={p.returncode}'); print(p.stderr if p.returncode else '')"
```

**Budget: under 8 seconds**, including the doubled `uv run` interpreter startup this command itself pays. The premise of the whole scoping decision was that a tool developers actually run beats a complete one they don't, and a slow advisory tool does not get run.

A 5 s budget was measured to straddle the real number before the `term in t` pre-filter existed, which is why the pre-filter is in `make_search` and the budget is 8 s. MEASURED in-process over the 647-file corpus with this diff's 18 terms (17 module-level public symbols plus the import path): reading the files 0.21 s, search **2.26 s without** the pre-filter and **0.09 s with** it. So the work itself is ~0.3 s and the budget is almost entirely interpreter startup — if this step is anywhere near 8 s, something is wrong rather than merely slow.

Memoization is *not* what makes this fast: within a single run every term is distinct, so the cache never hits. Over budget → record the number and open a follow-up; the next lever is a single combined-alternation pass per file instead of one pass per term. Do **not** implement it here.

- [ ] **Step 4: Run the commands the tool actually emitted**

Nothing else in this plan ever executes the tool's output — which is how the unpasteable-command bug survived until it was caught by inspection. Close the loop.

**Three guards, because this is the one step that runs arbitrary repo tests.**

1. **If either selection rendered a full-run block** (`unit: full run --` / `e2e: full run --`, i.e. `GLOBAL` or `CAPPED`), **do NOT execute that one.** The emitted command there is the bare `uv run pytest` / `uv run pytest -m e2e`, and running it violates this plan's own "never run the full suite" constraint. Record the block verbatim and check pasteability by inspection only.
2. **Do NOT run the e2e command.** Step 2 measured it at **78 real e2e tests across 6 browser modules** — minutes of Playwright, which is precisely the cost this design exists to reclaim. Verify it is *well-formed* instead:
   ```bash
   <paste the emitted e2e command, with --collect-only --verbosity=0 appended>
   ```
   Expected: a non-zero collected count and exit 0, proving the file list and `-m e2e` are valid. Record the count.
3. **Run the unit command** only if it is a concrete file list. Requires the test database: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait` (the ~11 selected modules take the `db` fixture). Expected exit **0**; budget **under 2 minutes**. If it exceeds that or the container is down, record the fact and move on rather than debugging unrelated tests — they are not this branch's work.

A **syntax error from the shell** on any paste is a defect in `render_commands`, not a typo: fix it, and add a `render_commands` assertion that would have caught it.

- [ ] **Step 5: Run the named test file**

Run: `uv run pytest tests/test_affected_tests.py -v`

Expected: PASS, **88** tests — or 88 plus any **new test** Step 4 added; an assertion added to an existing test leaves it at 88 — exit 0. **Do not run the full suite** — this branch adds no application code, and CI is the gate.

- [ ] **Step 6: Lint the whole diff**

```bash
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
uv run ruff format --check scripts/affected_tests.py tests/test_affected_tests.py
```

- [ ] **Step 7: Record the measurements in a note, and commit**

The spec's §5.5 requires that **all measured numbers land in a note under `docs/superpowers/notes/`, dated and naming the commit measured** — a task report is ephemeral, so the dogfood numbers would otherwise be lost.

Create `docs/superpowers/notes/2026-08-07-affected-tests-dogfood.md` containing:

- the commit SHA measured (`git rev-parse --short HEAD`) and the `--base` used;
- the verbatim tool output from Step 1;
- the unit and e2e file counts, and whether either selection was `CAPPED`;
- the Step 3 timing against the 8 s budget, and the Step 4 exit codes for both emitted commands;
- one line on whether the `main`-driven false positives showed up as predicted.

If Steps 1–4 surfaced a defect, also fix it and add a test that would have caught it.

```bash
# Stage the module and its tests too: Steps 1-4 authorise fixes to both, and
# an uncommitted fix would be invisible to the branch.
uv run ruff check scripts/affected_tests.py tests/test_affected_tests.py
git add docs/superpowers/notes/2026-08-07-affected-tests-dogfood.md
git add scripts/affected_tests.py tests/test_affected_tests.py
git commit -m "docs(notes): record the affected-tests dogfood run

Tool output, selection sizes and wall clock on its own diff, per spec 5.5."
```

---

## Self-Review

**Spec coverage (§4):**

| Spec requirement | Task |
|---|---|
| B1 documented practice, per-file justification, regression-vs-migration | 8 |
| B1 branch gate / never-twice / one-run-at-a-time / troubleshooting | shipped by Part A; Task 8 Steps 1 and 4 verify they survive |
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
| `migration_models` | **cut by decision**; `module_symbols` substituted (Tasks 3, 6) |

**Placeholder scan:** none. Every code step carries actual code; every test step carries actual assertions.

**Type consistency:** `Result` fields are used identically in Tasks 2, 4, 5, 7. `map_one` is `(path, search, module_symbols)` in its definition and at every call site — there is no `corpus` parameter anywhere. The sentinel is `CORPUS_SENTINEL` throughout (the test module's fake corpus set is `FAKE_CORPUS`, deliberately distinct). `search` has one contract everywhere: word-boundary content match, plus `CORPUS_SENTINEL` → whole corpus. `_render_one` takes `(label, files, reason, full_command, suffix)` at both call sites.

**Lint consistency:** the exact import block is shown at each task that changes it (Tasks 1, 2, 6) and never contains an unused name (`F401`); `import subprocess` enters the test file through a header edit, not a mid-file insert (`E402`); `EXIT5_NOTE` uses single outer quotes so `ruff format --check` passes.

**Test counts** are stated expanded (parametrized cases counted individually): 10 → 34 → 49 → 58 → 70 → 77 → 88. Per-task additions: 10, 24, 15, 9, 12, 7, 11.

**Placement:** every code addition says "append at the end of the module", which is the only ordering that is safe for `_FULL_RUN_BECAUSE` (a module-level dict dereferencing `Reason` at import).

**Beyond §4, deliberately:** the untracked-file union in Task 6 is not in the spec. `git diff` cannot see a file that has not been `git add`-ed (VERIFIED), and "I just created this test" is the most common iterating state — reporting `nothing to run` for it would be the exact silent omission the Global Constraints forbid. Task 9 Step 6's note satisfies the spec's §5.5 recording requirement, which §4 does not restate.
