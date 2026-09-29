#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from shapely.geometry import LineString, Polygon, box

def item_geometry(item):
    kind = item["type"]
    if kind == "polygon":
        return Polygon(item["points"])
    if kind == "polyline":
        return LineString(item["points"]).buffer(item["width_mm"] / 2, cap_style=2, join_style=2)
    if kind == "rect":
        x1, y1, x2, y2 = item["region"]
        return box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    raise ValueError(f"{kind} must be expanded before clipping")

def geometry_to_polygons(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return []

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--artwork", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    data = json.loads(args.artwork.read_text())
    _board_text = args.board.read_text(errors="replace")
    clearance = float(data.get("clearance_mm", 0.16))

    output_items = []
    for item in data["items"]:
        if item["type"] == "hatching":
            output_items.append(item)
            continue
        geom = item_geometry(item)
        for index, poly in enumerate(geometry_to_polygons(geom)):
            output_items.append({
                "id": item["id"] if index == 0 else f"{item['id']}-{index + 1}",
                "type": "polygon",
                "points": [[round(x, 6), round(y, 6)] for x, y in list(poly.exterior.coords)[:-1]]
            })

    result = dict(data)
    result["items"] = output_items
    result["meta"] = {
        "source_board": args.board.name,
        "clearance_mm": clearance,
        "keepout_parser": "not-yet-implemented"
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {len(output_items)} item(s) to {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
