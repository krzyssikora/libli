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
