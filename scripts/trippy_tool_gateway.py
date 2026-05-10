#!/usr/bin/env python
"""Utility entrypoint for Trippy's Printing Press-style tool gateway.

Examples:
  python scripts/trippy_tool_gateway.py healthcheck
  python scripts/trippy_tool_gateway.py describe
  python scripts/trippy_tool_gateway.py dry-run flight_search '{"origin":"YYZ","destination":"SCL"}'
  python scripts/trippy_tool_gateway.py run lodging_search '{"destination":"Valparaiso","start_date":"2026-06-11","end_date":"2026-06-14"}'
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from trippy.tool_registry.gateway import TrippyToolGateway


def _json_arg(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("input JSON must be an object")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and call Trippy registered tools")
    sub = parser.add_subparsers(dest="command", required=True)

    describe = sub.add_parser("describe")
    describe.add_argument("tool_id", nargs="?")

    health = sub.add_parser("healthcheck")
    health.add_argument("tool_id", nargs="?")

    dry = sub.add_parser("dry-run")
    dry.add_argument("tool_id")
    dry.add_argument("input", nargs="?", default="{}", type=_json_arg)

    run = sub.add_parser("run")
    run.add_argument("tool_id")
    run.add_argument("input", nargs="?", default="{}", type=_json_arg)

    args = parser.parse_args()
    gateway = TrippyToolGateway()

    if args.command == "describe":
        payload = gateway.describe(args.tool_id)
    elif args.command == "healthcheck":
        payload = gateway.healthcheck(args.tool_id)
    elif args.command == "dry-run":
        payload = gateway.call(args.tool_id, args.input, dry_run=True)
    elif args.command == "run":
        payload = gateway.call(args.tool_id, args.input, dry_run=False)
    else:
        parser.error(f"Unknown command: {args.command}")
        return 2

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
