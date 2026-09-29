#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

BEGIN = "; PCB-ARTWORK-SKILL BEGIN"
END = "; PCB-ARTWORK-SKILL END"

def poly_to_kicad(points, layer):
    pts = " ".join(f"(xy {x:.6f} {y:.6f})" for x, y in points)
    return f'  (gr_poly (pts {pts}) (stroke (width 0) (type solid)) (fill solid) (layer "{layer}"))'

def generated_block(data):
    objects = []
    for item in data["items"]:
        if item["type"] != "polygon":
            raise ValueError(f"patcher accepts compiled polygons only: {item['id']} is {item['type']}")
        objects.append(poly_to_kicad(item["points"], data["layer"]))
    return "\n".join([BEGIN, *objects, END])

def strip_old_block(text):
    start = text.find(BEGIN)
    if start == -1:
        return text
    end = text.find(END, start)
    if end == -1:
        raise ValueError("found generated block start without end marker")
    end += len(END)
    return text[:start] + text[end:]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--artwork", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    data = json.loads(args.artwork.read_text())
    board = strip_old_block(args.board.read_text())
    insert_at = board.rfind(")")
    if insert_at < 0:
        raise ValueError("not a KiCad S-expression")

    patched = board[:insert_at].rstrip() + "\n" + generated_block(data) + "\n" + board[insert_at:]
    args.output.write_text(patched)
    print(f"wrote {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
