#!/usr/bin/env python3
"""Read, clip and patch in one invocation; no transferable compiled artifact."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.board_geometry import read_board
from lib.compiler import compile_artwork
from lib.patching import patch_text, write_board_copy
from lib.validation import load_artwork


def same_file(left, right):
    if left.resolve() == right.resolve():
        return True
    return left.exists() and right.exists() and os.path.samefile(left, right)


def stage_report(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".pcb-artwork-report-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        return temporary
    except BaseException:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        raise


def review_svg(board, compilation):
    """Model-space review, not a Gerber manufacturing export."""
    x0, y0, x1, y1 = board.area.bounds
    silk = unary_union([Polygon(item["points"]) for item in compilation.polygons])
    def shape(geometry, color):
        if geometry is None or geometry.is_empty:
            return ""
        if geometry.geom_type != "Polygon":
            return "".join(shape(part, color) for part in geometry.geoms)
        return geometry.svg(scale_factor=0.01, fill_color=color).replace(
            'stroke="#555555"', 'stroke="none"').replace('opacity="0.6"', 'opacity="1"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700" '
            f'viewBox="{x0-1} {y0-1} {x1-x0+2} {y1-y0+2}">'
            '<title>Model-space silkscreen review: red indicates potential detail loss</title>'
            f'<rect x="{x0-1}" y="{y0-1}" width="{x1-x0+2}" height="{y1-y0+2}" fill="white"/>'
            + shape(board.area, "#e7edf0")
            + shape(board.obstacles[compilation.layer], "#eaa252")
            + shape(silk, "#172c36")
            + shape(compilation.review_geometry, "#d93838") + '</svg>\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--artwork", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="PCB copy, not compiled JSON")
    parser.add_argument("--report", type=Path, help="optional JSON report; also printed to stdout")
    parser.add_argument("--manufacturing-profile", choices=["conservative", "geometry-only"],
                        default="conservative", help="default: 0.20 mm target width and 0.25 mm clearance")
    parser.add_argument("--review-svg", type=Path, help="model-space preview with potential detail loss in red")
    parser.add_argument("--edge-margin-mm", type=float, help="defaults to effective clearance")
    parser.add_argument("--curve-error-mm", type=float, default=0.001)
    args = parser.parse_args()
    staged_report = None
    staged_preview = None
    board_written = False
    try:
        if args.board.with_suffix(".kicad_dru").exists():
            raise ValueError("external .kicad_dru rules are unsupported; use a standalone board")
        if args.review_svg and args.review_svg.is_dir():
            raise ValueError("review SVG path is a directory")
        if args.review_svg and any(same_file(args.review_svg, path) for path in
                                   (args.board, args.artwork, args.output, *([args.report] if args.report else []))):
            raise ValueError("review SVG must be distinct from inputs, PCB output and report")
        if args.report and args.report.is_dir():
            raise ValueError("report path is a directory")
        for number, name in [(args.edge_margin_mm, "edge margin"), (args.curve_error_mm, "curve error")]:
            if number is not None and (not math.isfinite(number) or number < 0):
                raise ValueError(f"{name} must be finite and nonnegative")
        if args.curve_error_mm == 0:
            raise ValueError("curve error must be positive")
        if same_file(args.output, args.artwork) or same_file(args.output, args.board):
            raise ValueError("output must be a copy distinct from both inputs")
        if args.report and any(same_file(args.report, path) for path in (args.board, args.artwork, args.output)):
            raise ValueError("report must be distinct from the inputs and PCB output")
        data = load_artwork(args.artwork)
        with args.board.open("rb") as stream:
            original = stream.read(16 * 1024 * 1024 + 1)
        if len(original) > 16 * 1024 * 1024:
            raise ValueError("board exceeds 16 MiB input budget")
        text = original.decode("utf-8")
        board = read_board(text, curve_error_mm=args.curve_error_mm)
        compilation = compile_artwork(board, data, edge_margin_mm=args.edge_margin_mm,
                                      curve_error_mm=args.curve_error_mm,
                                      manufacturing_profile="conservative" if args.manufacturing_profile == "conservative" else None)
        report = dict(compilation.report)
        report.update({"output_written": bool(compilation.polygons),
                       "existing_output_preserved": not compilation.polygons and args.output.exists(),
                       "board_file_version": board.version,
                       "manufacturing_requirements": ("conservative engineering profile; supplier confirmation required"
                                                      if args.manufacturing_profile == "conservative" else "unspecified"),
                       "checks": {"kicad_loading": "not_run", "drc": "not_run",
                                  "gerber_export": "not_run", "visual_review": "not_run"}})
        report_text = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.review_svg:
            staged_preview = stage_report(args.review_svg, review_svg(board, compilation))
        if args.report:
            staged_report = stage_report(args.report, report_text)
        if compilation.polygons:
            patched = patch_text(text, compilation)
            write_board_copy(args.board, original, patched, args.output)
            board_written = True
        if staged_report:
            os.replace(staged_report, args.report)
            staged_report = None
        if staged_preview:
            os.replace(staged_preview, args.review_svg)
            staged_preview = None
        print(report_text, end="")
        return 0 if compilation.polygons else 2
    except (ValueError, OSError, GEOSException, OverflowError, FloatingPointError) as error:
        prefix = "PCB written, report or preview promotion failed" if board_written else "compilation blocked"
        print(f"{prefix}: {str(error)[:1000]}", file=sys.stderr)
        return 1
    finally:
        for staged in (staged_report, staged_preview):
            if staged is not None and staged.exists():
                staged.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
