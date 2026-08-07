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
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
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
