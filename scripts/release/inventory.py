#!/usr/bin/env python3
"""The school inventory (B2, spec §6), read from the SCHOOL_HOSTS secret:

    {"school-01": {"host": "<ip>", "host_key": "ssh-ed25519 AAAA...",
                   "domain": "<registrable domain>"}, ...}

    inventory.py plan <school|all> --output <file>   masks all; codes=<json>
    inventory.py entry <code> --dir <dir>            masks one; host, known_hosts

GitHub masks the whole secret, not the values inside it, and the plan job runs
before any mask exists -- so no message here ever prints a field value, a key
that is not a school code, or the school argument. Masks are printed before
anything is written anywhere.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse  # noqa: E402
from _release_common import run_main  # noqa: E402

CODE_RE = re.compile(r"school-[0-9]{2}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]*")
KEY_RE = re.compile(
    r"(ssh-ed25519|ecdsa-sha2-nistp(256|384|521)|ssh-rsa) [A-Za-z0-9+/]+={0,2}"
)
FIELDS = ("host", "host_key", "domain")


def load(raw):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise Refuse("SCHOOL_HOSTS is not valid JSON") from None
    if not isinstance(data, dict):
        raise Refuse("SCHOOL_HOSTS must be a JSON object of school code -> entry")
    for code, item in data.items():
        if not CODE_RE.fullmatch(code):
            raise Refuse("an inventory key is not of the form school-NN")
        if not isinstance(item, dict):
            raise Refuse(f"{code}: the entry is not an object")
        for field in FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value:
                raise Refuse(f"{code}: {field} is empty")
            pattern = KEY_RE if field == "host_key" else NAME_RE
            if not pattern.fullmatch(value):
                raise Refuse(f"{code}: {field} is malformed")
    return data


def resolve(inventory, school):
    if school == "all":
        codes = sorted(inventory)
    elif school in inventory:
        codes = [school]
    else:
        raise Refuse("unknown school code (use a key of SCHOOL_HOSTS, or all)")
    if not codes:
        raise Refuse("no schools to deploy to (SCHOOL_HOSTS is empty)")
    return codes


def _mask(item):
    print(f"::add-mask::{item['host']}", flush=True)
    print(f"::add-mask::{item['domain']}", flush=True)


def _option(args, name):
    if name not in args or args.index(name) + 1 >= len(args):
        raise Refuse(f"missing {name}")
    return args[args.index(name) + 1]


def main():
    args = sys.argv[1:]
    inventory = load(os.environ.get("SCHOOL_HOSTS", ""))
    if args[:1] == ["plan"] and len(args) == 4:
        codes = resolve(inventory, args[1])
        for item in inventory.values():
            _mask(item)
        with open(_option(args, "--output"), "a", encoding="utf-8") as fh:
            fh.write(f"codes={json.dumps(codes)}\n")
    elif args[:1] == ["entry"] and len(args) == 4:
        code = args[1]
        if code not in inventory:
            raise Refuse("unknown school code")
        item = inventory[code]
        _mask(item)
        target = Path(_option(args, "--dir"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "host").write_bytes(f"{item['host']}\n".encode())
        (target / "known_hosts").write_bytes(
            f"{item['host']} {item['host_key']}\n".encode()
        )
    else:
        raise Refuse(
            "usage: inventory.py plan <school|all> --output <f> | entry <c> --dir <d>"
        )


if __name__ == "__main__":
    run_main(main)
