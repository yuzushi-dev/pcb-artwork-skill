import json
import math
from pathlib import Path
import sys

import pytest
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "skills" / "pcb-artwork" / "lib"
sys.path.insert(0, str(LIB))

import board_geometry as geometry_module  # noqa: E402
from board_geometry import GeometryError, read_board  # noqa: E402
import sexpr as sexpr_module  # noqa: E402
from sexpr import MAX_BYTES, MAX_DEPTH, Node, ParseError, parse  # noqa: E402


BOARDS = ROOT / "tests" / "fixtures" / "boards"


def board(name):
    return (BOARDS / name).read_text()


def test_sexpr_preserves_spans_and_decodes_quoted_atoms():
    text = ' (root bare (child "a\\n\\\"b" tail)) '
    root = parse(text)

    assert isinstance(root, Node)
    assert root.head == "root"
    assert root.values[0] == "root"
    assert text[root.start : root.end] == '(root bare (child "a\\n\\\"b" tail))'
    child = root.child("child")
    assert child.values == ["child", 'a\n"b', "tail"]
    assert root.children("child") == [child]
    assert root.child("missing") is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "expected one root"),
        ("(a", "unclosed"),
        ("(a))", "unexpected closing"),
        ('(a "x)', "unterminated string"),
        ("(a)(b)", "trailing expression"),
    ],
)
def test_sexpr_rejects_malformed_input_with_position(text, message):
    with pytest.raises(ParseError, match=message) as caught:
        parse(text)

    assert "line" in str(caught.value)
    assert "column" in str(caught.value)
    assert "offset" in str(caught.value)


def test_sexpr_enforces_size_and_depth_budgets():
    with pytest.raises(ParseError, match="byte limit"):
        parse("(" + "x" * MAX_BYTES + ")")

    deep = "(" * (MAX_DEPTH + 1) + "x" + ")" * (MAX_DEPTH + 1)
    with pytest.raises(ParseError, match="nesting depth"):
        parse(deep)


def test_sexpr_counts_atoms_and_limits_individual_strings(monkeypatch):
    monkeypatch.setattr(sexpr_module, "MAX_TOKENS", 3)
    with pytest.raises(ParseError, match="token limit"):
        parse("(root one two)")

    monkeypatch.setattr(sexpr_module, "MAX_TOKENS", 1_000_000)
    monkeypatch.setattr(sexpr_module, "MAX_STRING_BYTES", 4)
    with pytest.raises(ParseError, match="string byte limit"):
        parse('(root "12345")')


def test_sexpr_rejects_duplicate_singular_child_with_second_offset():
    root = parse("(root (size 1 1) (size 2 2))")

    with pytest.raises(ValueError, match=r"duplicate child 'size'.*offset 17"):
        root.child("size")


def test_reads_closed_board_with_cutout_and_json_inventory():
    geometry = read_board(board("geometry-pads.kicad_pcb"))

    assert geometry.version == "20241229"
    assert geometry.area.geom_type == "Polygon"
    assert geometry.area.contains(Point(1, 1))
    assert not geometry.area.contains(Point(15, 10))
    assert geometry.area.area == pytest.approx(600 - math.pi * 4, abs=0.04)
    assert geometry.inventory["footprints"] == 2
    assert geometry.inventory["pads"] == 6
    assert geometry.inventory["vias"] == 1
    assert geometry.inventory["drills"] == 3
    json.dumps(geometry.inventory)


def test_reconstructs_three_point_arc_conservatively():
    geometry = read_board(board("geometry-arc-outline.kicad_pcb"), curve_error_mm=0.001)

    exact_area = 100 + math.pi * 25 / 2
    assert geometry.area.area <= exact_area
    assert geometry.area.area == pytest.approx(exact_area, abs=0.05)
    assert geometry.area.contains(Point(14.9, 5))
    assert not geometry.area.contains(Point(15.1, 5))


def test_mask_margins_transformations_holes_via_and_mask_graphics():
    geometry = read_board(board("geometry-pads.kicad_pcb"))
    front = geometry.obstacles["F.SilkS"]
    back = geometry.obstacles["B.SilkS"]

    # KiCad rotates footprint-local positions clockwise in numeric board XY.
    # Drill offset moves the pad/mask body, not the physical hole.
    assert front.contains(Point(5.25, 4))
    # Pad angle is absolute board orientation; this oval is vertical at (9, 5).
    assert front.contains(Point(9, 6.69))
    assert not front.contains(Point(9, 6.71))
    # Pad margin 0.3 overrides footprint/board and creates a 2.6 x 1.6 opening.
    assert front.contains(Point(6.29, 1))
    assert not front.contains(Point(6.31, 1))

    # Back footprint uses the stored relative coordinates directly, then rotates.
    assert back.contains(Point(25, 4))
    assert back.contains(Point(27.141, 4.859))
    # The offset pad's physical drill remains at nominal pad position (5, 4).
    assert back.contains(Point(5.49, 4))
    # Exposed via mask opening has radius 0.6 + board margin 0.2 on both sides.
    assert front.contains(Point(10.79, 15))
    assert back.contains(Point(10.79, 15))
    # Explicit mask graphics are protected too.
    assert front.contains(Point(6, 14))
    assert back.contains(Point(24, 15))
    # KiCad plots both the fill and the centered stroke of filled graphics.
    assert back.contains(Point(22.91, 15))
    assert not back.contains(Point(22.89, 15))


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("custom-pad.kicad_pcb", "unsupported protected pad shape 'custom'"),
        ("open-outline.kicad_pcb", "open or disconnected Edge.Cuts contour"),
        ("geometry-mask-min-width.kicad_pcb", "solder_mask_min_width"),
    ],
)
def test_unsupported_protected_geometry_fails_with_source_position(filename, message):
    with pytest.raises(GeometryError, match=message) as caught:
        read_board(board(filename))

    rendered = str(caught.value)
    assert "line" in rendered
    assert "column" in rendered
    assert "offset" in rendered


def test_rejects_unsupported_file_version():
    text = board("geometry-arc-outline.kicad_pcb").replace("20241229", "20260101", 1)

    with pytest.raises(GeometryError, match="unsupported KiCad board version"):
        read_board(text)


def test_rejects_invalid_curve_error():
    with pytest.raises(ValueError, match="curve_error_mm"):
        read_board(board("geometry-arc-outline.kicad_pcb"), curve_error_mm=0)


@pytest.mark.parametrize("bad_error", [0, 1e-300])
def test_rejects_unresolvable_curve_error(bad_error):
    with pytest.raises(ValueError, match="curve_error_mm"):
        read_board(board("geometry-arc-outline.kicad_pcb"), curve_error_mm=bad_error)


@pytest.mark.parametrize("via_type", ["blind", "buried", "micro"])
def test_rejects_non_through_vias(via_type):
    text = board("geometry-pads.kicad_pcb").replace("(via (at 10 15)", f"(via {via_type} (at 10 15)")

    with pytest.raises(GeometryError, match="non-through via"):
        read_board(text)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("(tenting none)", "(tenting none) (allow_soldermask_bridges_in_footprints yes)", "allow_soldermask_bridges"),
        ("(via (at 10 15)", "(via (remove_unused_layers) (at 10 15)", "via construct 'remove_unused_layers'"),
        ("(via (at 10 15)", '(zone (layer "F.Mask"))\n  (via (at 10 15)', "solder-mask zones"),
        ('(pad "1" thru_hole circle', '(fp_line (start 0 0) (end 1 0) (layer "F.Mask"))\n    (pad "1" thru_hole circle', "footprint solder-mask construct"),
    ],
)
def test_rejects_active_unsupported_mask_features(old, new, message):
    text = board("geometry-pads.kicad_pcb").replace(old, new, 1)

    with pytest.raises(GeometryError, match=message) as caught:
        read_board(text)

    assert "line" in str(caught.value)


def test_rejects_through_hole_pad_without_explicit_drill():
    text = board("mask-pad.kicad_pcb").replace("(drill 1) ", "")

    with pytest.raises(GeometryError, match="requires an explicit drill"):
        read_board(text)


def test_rejects_finite_but_unrepresentable_coordinates():
    text = board("geometry-arc-outline.kicad_pcb").replace("(start 0 0)", "(start 1e308 0)", 1)

    with pytest.raises(GeometryError, match="exceeds supported magnitude") as caught:
        read_board(text)

    assert "line" in str(caught.value)


def test_global_geometry_vertex_budget_fails_before_large_curve_expansion(monkeypatch):
    monkeypatch.setattr(geometry_module, "MAX_GEOMETRY_VERTICES", 10)

    with pytest.raises(GeometryError, match="geometry vertex budget exceeded") as caught:
        read_board(board("geometry-arc-outline.kicad_pcb"))

    assert "line" in str(caught.value)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("(size 2 2)", "(size 2 2) (size 3 3)", "duplicate child 'size'"),
        ("(solder_mask_margin 0.3)", "(solder_mask_margin 0.3) (solder_mask_margin 0.4)", "duplicate child 'solder_mask_margin'"),
        ("(size 2 2)", "(size 2 2 99)", "requires exactly 2 numeric values"),
        ("(at 5 5 90)", "(at 5 5 90 99)", "requires 2 or 3 numeric values"),
        ("(start 0 0)", "(start 0 0 99)", "requires exactly 2 numeric values"),
        ("(tenting none)", "(tenting (front yes) (front no))", "duplicate child 'front'"),
    ],
)
def test_rejects_duplicate_or_extra_singular_geometry_fields(old, new, message):
    filename = "geometry-arc-outline.kicad_pcb" if old == "(start 0 0)" else "geometry-pads.kicad_pcb"
    text = board(filename).replace(old, new, 1)

    with pytest.raises(ValueError, match=message):
        read_board(text)


def test_requires_board_mask_margin_in_board_setup():
    text = board("geometry-arc-outline.kicad_pcb").replace(
        "(setup (pad_to_mask_clearance 0))", "(setup)", 1
    )

    with pytest.raises(GeometryError, match="missing required pad_to_mask_clearance"):
        read_board(text)
