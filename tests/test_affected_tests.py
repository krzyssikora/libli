"""Tests for scripts/affected_tests.py.

Located here, not under scripts/, because `scripts/` sits outside every test
directory and pyproject.toml sets no `testpaths` -- this path is what guarantees
the existing configuration collects them.
"""

import importlib.util
import subprocess
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
