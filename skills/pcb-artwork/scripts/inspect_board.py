#!/usr/bin/env python3
"""Inspect the supported structural board geometry, failing on unsupported input."""
import argparse
import json
from pathlib import Path
import sys
from shapely.errors import GEOSException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.board_geometry import read_board


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    args = parser.parse_args()
    try:
        with args.board.open("rb") as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("board exceeds 16 MiB input budget")
        board = read_board(raw.decode("utf-8"))
        report = {"file": args.board.name, "version": board.version,
                  "inventory": board.inventory,
                  "area_mm2": round(board.area.area, 6),
                  "bounds_mm": list(board.area.bounds),
                  "protected_area_mm2": {side: round(geometry.area, 6)
                                         for side, geometry in board.obstacles.items()},
                  "support": {"status": "supported_subset", "board_geometry": "extracted",
                              "kicad_validation": "not_run", "drc": "not_run",
                              "gerber_export": "not_run", "visual_review": "not_run"}}
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, GEOSException, OverflowError, FloatingPointError) as error:
        print(f"inspection blocked: {str(error)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
