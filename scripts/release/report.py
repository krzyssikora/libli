#!/usr/bin/env python3
"""Per-leg outcomes and the Deploy release summary (B2, spec §2).

    report.py outcome --code C --attempt N --from F --to V --deploy-outcome O --now-on T
    report.py summarise --plan-result R --codes JSON --attempt N --dir D --summary FILE

A row from an earlier run attempt is marked "(attempt N)" and never counts
toward success; a planned code with no artifact is "no result"; a plan refusal
(no codes) is always a fail -- otherwise "every planned code succeeded" would
be vacuously true on exactly the runs whose alert matters most.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse  # noqa: E402
from _release_common import run_main  # noqa: E402


def outcome(code, attempt, frm, to, deploy_outcome, now_on):
    return {
        "code": code,
        "run_attempt": int(attempt),
        "from": frm,
        "to": to,
        "result": "success" if deploy_outcome == "success" else "failure",
        "now_on": now_on,
    }


def load_outcomes(directory):
    found = {}
    path = Path(directory)
    if not path.is_dir():
        return found
    for f in sorted(path.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "code" in data:
            found[data["code"]] = data
    return found


def verdict(plan_result, codes, attempt, outcomes):
    if plan_result != "success" or not codes:
        return "fail"
    for code in codes:
        o = outcomes.get(code)
        if (
            not o
            or o.get("result") != "success"
            or int(o.get("run_attempt", 0)) != int(attempt)
        ):
            return "fail"
    return "success"


def table(plan_result, codes, attempt, outcomes):
    lines = [
        "## Deploy release",
        "",
        "| School | Result | From | To | Now on |",
        "|---|---|---|---|---|",
    ]
    if plan_result != "success" or not codes:
        lines.append("| — | ❌ plan refused — see the plan job | | | |")
        return lines
    for code in codes:
        o = outcomes.get(code)
        if not o:
            lines.append(f"| {code} | ❌ no result | | | |")
            continue
        mark = "✅" if o.get("result") == "success" else "❌"
        if int(o.get("run_attempt", 0)) != int(attempt):
            mark += f" (attempt {o.get('run_attempt')})"
        frm, to, now_on = o.get("from", ""), o.get("to", ""), o.get("now_on", "")
        lines.append(f"| {code} | {mark} | {frm} | {to} | {now_on} |")
    return lines


def _opts(args, required):
    if len(args) % 2:
        raise Refuse("options come in --name value pairs")
    found = {args[i].lstrip("-"): args[i + 1] for i in range(0, len(args), 2)}
    missing = [name for name in required if name not in found]
    if missing:
        raise Refuse(f"missing --{missing[0]}")
    return found


def main():
    args = sys.argv[1:]
    if args[:1] == ["outcome"]:
        o = _opts(
            args[1:], ("code", "attempt", "from", "to", "deploy-outcome", "now-on")
        )
        print(
            json.dumps(
                outcome(
                    o["code"],
                    o["attempt"],
                    o["from"],
                    o["to"],
                    o["deploy-outcome"],
                    o["now-on"],
                )
            )
        )
    elif args[:1] == ["summarise"]:
        o = _opts(args[1:], ("plan-result", "codes", "attempt", "dir", "summary"))
        codes = json.loads(o["codes"]) if o["codes"].strip() else []
        outs = load_outcomes(o["dir"])
        with open(o["summary"], "a", encoding="utf-8") as fh:
            fh.write(
                "\n".join(table(o["plan-result"], codes, o["attempt"], outs)) + "\n"
            )
        print(verdict(o["plan-result"], codes, o["attempt"], outs))
    else:
        raise Refuse("usage: report.py outcome ... | summarise ...")


if __name__ == "__main__":
    run_main(main)
