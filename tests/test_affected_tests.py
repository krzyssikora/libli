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
