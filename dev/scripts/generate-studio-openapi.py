#!/usr/bin/env python3
"""Generate or check the ComfyGit Studio contract API OpenAPI document."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from comfygit_studio.api_schema import studio_contract_api_openapi, write_openapi

DEFAULT_OUTPUT = Path("packages/studio-runtime/comfygit_studio/openapi/studio-contract-api.v1.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if the checked-in file is stale")
    args = parser.parse_args()

    if args.check:
        expected = _generated_text()
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != expected:
            print(f"{args.output} is stale. Run: make generate-openapi", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date")
        return 0

    write_openapi(args.output)
    print(f"wrote {args.output}")
    return 0


def _generated_text() -> str:
    import json

    return json.dumps(studio_contract_api_openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
