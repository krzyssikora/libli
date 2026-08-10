"""Shared fixtures for the LaTeX-in-titles tasks (spec 2026-08-10).

Not collected by pytest (no test_ prefix) -- imported by
test_title_math_filter / _markers / _assets and the e2e file.
"""

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login

# One inline pair and one display pair, plus prose around them, so a single
# fixture exercises both INLINE_DELIMS entries and the title-alone rule.
MATHS_TITLE = r"Rozwiaz \(x^2\) oraz \[y_3\]"
MATHS_TITLE_STRIPPED = "Rozwiaz x^2 oraz y_3"


def login_student(client, course, username="student"):
    """A verified, enrolled, logged-in student for `course`."""
    user = make_login(client, username)
    EnrollmentFactory(student=user, course=course)
    return user


def make_title_course(*, maths_on="none"):
    """A two-part course. Returns (course, viewed_unit, nodes) where `nodes` maps
    a name to its ContentNode.

    Shape (pre-order):
        part1  "Czesc pierwsza"
          unitA  <- the unit every view test opens
          unitB  <- unitA's `next`
        part2
          unitC

    `maths_on` places the ONLY maths title in the whole course:
      "none"   -- nothing carries maths (the negative-direction fixture)
      "unitA"  -- on the viewed unit itself
      "unitB"  -- on the viewed unit's `next` (the e2e / nav-button case)
      "far"    -- on unitC AND part2, i.e. several sections away from unitA,
                  with unitA, unitB, part1 and all their neighbours plain.
                  This is the TREE TRAP fixture: the whole course outline is in
                  unitA's DOM (build_unit_nav sets unit_nav["tree"] to it), so
                  unitA's page must still load KaTeX.
      "group"  -- on part2 only (a GROUP title, not a leaf) -- the analytics
                  expanded-group case, where a scan over matrix["columns"]
                  would silently miss it.
    """
    course = CourseFactory()
    part1 = ContentNodeFactory(
        course=course,
        kind="part",
        parent=None,
        unit_type=None,
        order=0,
        title="Czesc pierwsza",
    )
    part2 = ContentNodeFactory(
        course=course,
        kind="part",
        parent=None,
        unit_type=None,
        order=1,
        title=MATHS_TITLE if maths_on in ("far", "group") else "Czesc druga",
    )
    unit_a = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part1,
        order=0,
        obligatory=True,
        title=MATHS_TITLE if maths_on == "unitA" else "Lekcja pierwsza",
    )
    unit_b = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part1,
        order=1,
        obligatory=True,
        title=MATHS_TITLE if maths_on == "unitB" else "Lekcja druga",
    )
    unit_c = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part2,
        order=0,
        obligatory=True,
        title=MATHS_TITLE if maths_on == "far" else "Lekcja trzecia",
    )
    return (
        course,
        unit_a,
        {
            "part1": part1,
            "part2": part2,
            "unitA": unit_a,
            "unitB": unit_b,
            "unitC": unit_c,
        },
    )
