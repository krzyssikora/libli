"""A new element type with a rich-text body that nobody adds to RICH_TEXT_FIELDS would
silently escape both the transfer rewrite and the delete warning. This is the tripwire.

It greps the WHOLE courses/ package, not a hand-maintained file list: an earlier draft
allowlisted three files, missed templatetags/courses_extras.py outright, and could not
have seen a call site added in any other module (courses/switchgrid.py already
establishes that helper modules do sanitising work).
"""

import ast
from pathlib import Path

from courses.richtext import CONCRETE_QUESTION_MODELS

COURSES = Path(__file__).resolve().parent.parent / "courses"

# (file, qualname, assignment target) -- one entry per call site, MEASURED by running
# this walk against the repo. Three refinements, each load-bearing:
#   - qualname (Class.method), not the bare def name: def names and targets repeat
#     across classes, so a coarser key stays byte-identical when someone adds a new
#     element type the cheapest way (copy TextElement: a `body` field plus
#     `save: self.body = sanitize_html(self.body)`) -- the exact case this exists for.
#   - the assignment target, because QuestionElement.save() already holds TWO calls.
#   - compared as a sorted whole, so a DELETED site moves it too.
# The third element is the target ONLY when the call is the entire right-hand side of an
# assignment. A call nested in an expression -- inside strip_sentinel(...), inside
# mark_safe(...), or as a keyword argument to objects.create(...) -- records None.
EXPECTED = [
    ("element_forms.py", "DragFillBlankQuestionElementForm.clean_stem", None),
    ("element_forms.py", "FillBlankQuestionElementForm.clean_stem", None),
    ("element_forms.py", "FillGateElementForm.clean_stem", None),
    ("element_forms.py", "GuessNumberElementForm.clean_stem", None),
    ("element_forms.py", "SwitchGateElementForm.clean", None),
    ("element_forms.py", "SwitchGridElementForm.clean", None),
    ("models.py", "CalloutElement.save", "self.body"),
    ("models.py", "GuessNumberElement.save", "self.success_message"),
    ("models.py", "QuestionElement.save", "self.explanation"),
    ("models.py", "QuestionElement.save", "self.stem"),
    ("models.py", "SpoilerElement.save", "self.body"),
    ("models.py", "TextElement.save", "self.body"),
    # Render-time re-sanitise (the |sanitize filter), NOT a storage location. Recorded
    # rather than omitted, so the baseline is the whole truth.
    ("templatetags/courses_extras.py", "sanitize", None),
    ("transfer/importer.py", "_build_guess_number", None),
]

QUESTION_FORM_MODELS = {m.__name__ for m in CONCRETE_QUESTION_MODELS}


def _is_sanitize(node):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "sanitize_html"
    # Also catches `sanitize.sanitize_html(...)`. An `as`-aliased import stays a known
    # blind spot; nothing in the repo does that today.
    return isinstance(func, ast.Attribute) and func.attr == "sanitize_html"


def _target(assign):
    t = assign.targets[0]
    if isinstance(t, ast.Attribute):
        return f"{getattr(t.value, 'id', '?')}.{t.attr}"
    if isinstance(t, ast.Name):
        return t.id
    return None


def _sites_in(tree, rel):
    """Every sanitize_html call in one module, each recorded EXACTLY once.

    `rel` is a parameter, not a closed-over loop variable -- ruff's B023 flags the
    latter, and the earlier draft tripped it seven times.
    """
    target_of = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_sanitize(node.value):
            target_of[id(node.value)] = _target(node)

    found = []

    def visit(node, stack):
        # iter_child_nodes + explicit recursion visits every node once. An earlier draft
        # used ast.walk inside the loop AND recursed, recording each non-assignment call
        # once per nesting level -- courses_extras.py appeared three times.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, stack + [child.name])
                continue
            if _is_sanitize(child):
                found.append((rel, ".".join(stack), target_of.get(id(child))))
            visit(child, stack)

    visit(tree, [])
    return found


def _sites():
    found = []
    for path in sorted(COURSES.rglob("*.py")):
        rel = path.relative_to(COURSES).as_posix()
        if rel.startswith("tests/") or rel == "sanitize.py":
            continue
        found.extend(_sites_in(ast.parse(path.read_text(encoding="utf-8")), rel))
    return found


def _classify(qualname):
    """Which message a NEW site should get.

    The discriminator is the enclosing class's model, not the file: element_forms.py
    holds both kinds, and two of them even share the def name `clean_stem`.
    """
    cls = qualname.split(".")[0]
    covered = cls.endswith("Form") and cls[: -len("Form")] in QUESTION_FORM_MODELS
    return "covered" if covered else "needs-entry"


def test_sanitize_html_call_sites_match_the_registry_baseline():
    got = sorted(_sites())
    expected = sorted(EXPECTED)
    if got == expected:
        return
    lines = []
    for site in [s for s in got if s not in expected]:
        if _classify(site[1]) == "covered":
            lines.append(
                f"  + {site}: a question-model form -- stem/explanation are covered "
                f"automatically by CONCRETE_QUESTION_MODELS. Update EXPECTED only."
            )
        else:
            lines.append(
                f"  + {site}: NOT a question form -- courses/richtext.py "
                f"RICH_TEXT_FIELDS needs an entry OR a documented exclusion (see the "
                f"switch-grid precedent)."
            )
    for site in [s for s in expected if s not in got]:
        lines.append(f"  - {site}: removed; drop it from EXPECTED and the registry.")
    raise AssertionError(
        "The set of sanitize_html() call sites changed.\n" + "\n".join(lines)
    )


def test_question_models_are_introspected_not_listed():
    assert len(CONCRETE_QUESTION_MODELS) == 10
