"""max_attempts is gone everywhere it could silently survive (spec §4)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = (
    "courses.migrations.0070_attempts_fields",
    "courses.migrations.0071_attempts_data",
    "courses.migrations.0072_attempts_constraints",
)


# The ONE legitimate mention: the v<=17 archive upgrade must name the legacy key.
ALLOWED = {"courses/transfer/payloads.py"}


def test_no_production_reader_or_template_mentions_max_attempts():
    hits = []
    for base in ("courses", "templates", "integrations"):
        for path in (ROOT / base).rglob("*"):
            if path.suffix not in {".py", ".html", ".js"}:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if "/migrations/" in rel or "/tests/" in rel or rel in ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "max_attempts" in text:  # webhook delivery uses MAX_ATTEMPTS (upper)
                hits.append(rel)
    assert hits == []


def test_attempts_migrations_import_no_live_code():
    code = (
        "import importlib, sys\n"
        f"for m in {MIGRATIONS!r}: importlib.import_module(m)\n"
        "print('courses.models' in sys.modules, 'courses.quiz' in sys.modules)\n"
    )
    out = subprocess.run(  # noqa: S603 -- fixed argv, our own interpreter
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "False False", out.stdout + out.stderr
