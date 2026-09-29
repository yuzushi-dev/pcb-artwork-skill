#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "artwork.schema.json").read_text())

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artwork", type=Path)
    args = parser.parse_args()

    data = json.loads(args.artwork.read_text())
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        for error in errors:
            path = ".".join(str(p) for p in error.path) or "<root>"
            print(f"{path}: {error.message}")
        return 1

    ids = [item["id"] for item in data["items"]]
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        print("duplicate ids: " + ", ".join(duplicates))
        return 1

    print(f"valid artwork: {len(ids)} item(s) on {data['layer']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
