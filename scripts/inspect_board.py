#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    args = parser.parse_args()

    text = args.board.read_text(errors="replace")
    report = {
        "file": args.board.name,
        "footprints": count(r"\(footprint\s", text),
        "segments": count(r"\(segment\s", text),
        "vias": count(r"\(via\s", text),
        "zones": count(r"\(zone\s", text),
        "gr_poly": count(r"\(gr_poly\s", text),
        "front_silkscreen_objects": count(r'\(layer "F\.SilkS"\)', text),
        "back_silkscreen_objects": count(r'\(layer "B\.SilkS"\)', text)
    }
    print(json.dumps(report, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
