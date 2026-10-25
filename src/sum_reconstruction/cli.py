"""Read-only input, JSON output, explicit disclosure exit codes."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import MAX_BYTES, InputError, audit, load_json, parse_problem, verify_report


def _read(name):
    if name == "-":
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
    else:
        with Path(name).open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    return load_json(data)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Find exact reconstructions from public aggregates."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("audit", help="audit explicitly mapped aggregate equations")
    check.add_argument("input", help="input JSON file or - for stdin")
    check.add_argument(
        "--show-values", action="store_true", help="include recovered numeric values"
    )
    check.add_argument(
        "-o", "--output", help="create a new report file; existing files are refused"
    )
    verify = sub.add_parser("verify", help="verify positive certificates, not report completeness")
    verify.add_argument("input")
    verify.add_argument("report")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify" and args.input == "-" and args.report == "-":
            raise InputError("only one input may use stdin")
        problem = parse_problem(_read(args.input))
        if args.command == "verify":
            checked = verify_report(problem, _read(args.report))
            result = {"status": "certificates-valid", "checked": checked}
            code = 0
        else:
            result = audit(problem, show_values=args.show_values)
            code = {"no-unique-reconstruction": 0, "reconstructible": 1, "inconsistent": 2}[
                result["status"]
            ]
        output = json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        if args.command == "audit" and args.output:
            with Path(args.output).open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(output)
        else:
            sys.stdout.write(output)
        return code
    except InputError as exc:
        print(f"sum-reconstruction: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        print("sum-reconstruction: input/output operation failed", file=sys.stderr)
        return 2
