import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import GeometryCollection, Polygon, box
from shapely.ops import unary_union


SKILL = Path(__file__).resolve().parents[1] / "skills" / "pcb-artwork"
sys.path.insert(0, str(SKILL))

from lib.compiler import compile_artwork


def board(area=None, front=None, back=None):
    return SimpleNamespace(
        area=area or box(0, 0, 10, 10),
        obstacles={
            "F.SilkS": front or GeometryCollection(),
            "B.SilkS": back or GeometryCollection(),
        },
    )


def plan(*items, layer="F.SilkS", clearance=0):
    return {
        "version": 1,
        "layer": layer,
        "clearance_mm": clearance,
        "items": list(items),
    }


def output_geometry(compilation):
    return unary_union([Polygon(item["points"]) for item in compilation.polygons])


def test_expands_polyline_and_hatching_deterministically():
    data = plan(
        {
            "id": "trace",
            "type": "polyline",
            "points": [[1, 1], [4, 1], [4, 3]],
            "width_mm": 0.4,
        },
        {
            "id": "field",
            "type": "hatching",
            "region": [5, 1, 9, 5],
            "bar_width_mm": 0.2,
            "spacing_mm": 1,
        },
    )

    first = compile_artwork(board(), data, edge_margin_mm=0)
    second = compile_artwork(board(), data, edge_margin_mm=0)

    assert first.polygons == second.polygons
    assert any(item["id"].startswith("trace:") for item in first.polygons)
    hatch = [item for item in first.polygons if item["id"].startswith("field:")]
    assert len(hatch) == 5
    assert output_geometry(first).area == pytest.approx(5.2, abs=1e-5)


def test_uses_only_obstacles_for_selected_side():
    obstacle = box(4, 0, 6, 10)
    artwork = {"id": "bar", "type": "rect", "region": [1, 4, 9, 6]}

    front = compile_artwork(board(front=obstacle), plan(artwork), edge_margin_mm=0)
    back = compile_artwork(
        board(front=obstacle), plan(artwork, layer="B.SilkS"), edge_margin_mm=0
    )

    assert 11.99 < output_geometry(front).area < 12
    assert output_geometry(back).area == pytest.approx(16)


def test_decomposes_internal_holes_without_covering_them():
    central_hole = box(4, 4, 6, 6)
    board_area = box(0, 0, 10, 10).difference(central_hole)
    data = plan({"id": "fill", "type": "rect", "region": [1, 1, 9, 9]})

    result = compile_artwork(board(area=board_area), data, edge_margin_mm=0)
    geometry = output_geometry(result)

    assert all(not Polygon(item["points"]).interiors for item in result.polygons)
    assert geometry.intersection(central_hole).area == 0
    assert 59.98 < geometry.area < 60


def test_reports_clipping_fragments_and_removed_area():
    obstacle = box(4, 0, 6, 10)
    data = plan({"id": "split", "type": "rect", "region": [1, 4, 9, 6]})

    result = compile_artwork(board(front=obstacle), data, edge_margin_mm=0)

    assert result.report["status"] == "passed"
    assert result.report["removed"]["total"] == 0
    assert result.report["removed"]["source_ids"] == ["split"]
    assert result.report["removed"]["fragments"] == 2
    assert 4 < result.report["removed"]["areas_mm2"]["split"] < 4.01


def test_reports_all_removed_distinctly():
    data = plan({"id": "hidden", "type": "rect", "region": [4, 4, 6, 6]})

    result = compile_artwork(board(front=box(3, 3, 7, 7)), data, edge_margin_mm=0)

    assert result.polygons == []
    assert result.report["status"] == "all_removed"
    assert result.report["removed"]["total"] == 1
    assert result.report["removed"]["source_ids"] == ["hidden"]
    assert result.report["removed"]["areas_mm2"] == {"hidden": 4.0}
    assert result.report["removed"]["empty"] == 1


def test_serialized_polygons_keep_requested_clearance_after_rounding():
    obstacle = box(4.1234564, 0, 6.1234564, 10)
    data = plan(
        {"id": "near", "type": "rect", "region": [1, 1, 9, 9]},
        clearance=0.16,
    )

    result = compile_artwork(
        board(front=obstacle), data, edge_margin_mm=0, curve_error_mm=0.001
    )
    geometry = output_geometry(result)

    assert geometry.distance(obstacle) >= 0.16
    assert all(
        coordinate == round(coordinate, 6)
        for item in result.polygons
        for point in item["points"]
        for coordinate in point
    )
    assert result.report["input_validation"] == "passed"
    assert result.report["geometry"] == "passed"
    assert result.report["minimum_width"] == "not_checked"


def test_large_clearance_remains_conservative_at_rounded_obstacle_corners():
    obstacle = box(4, 4, 6, 6)
    data = plan(
        {"id": "surround", "type": "rect", "region": [1, 1, 9, 9]},
        clearance=1,
    )

    result = compile_artwork(board(front=obstacle), data, edge_margin_mm=0)

    assert output_geometry(result).distance(obstacle) >= 1


def test_default_edge_margin_survives_serialization():
    data = plan(
        {"id": "full", "type": "rect", "region": [0, 0, 10, 10]},
        clearance=0.16,
    )

    result = compile_artwork(board(), data)

    assert output_geometry(result).distance(board().area.boundary) >= 0.16
    assert result.report["edge_margin_mm"] == 0.16


def test_report_areas_do_not_double_count_overlapping_hatch_bars():
    data = plan(
        {
            "id": "dense",
            "type": "hatching",
            "region": [1, 1, 5, 5],
            "bar_width_mm": 1.5,
            "spacing_mm": 1,
        }
    )

    result = compile_artwork(board(), data, edge_margin_mm=0)

    assert result.report["input_area_mm2"] == 16
    assert result.report["serialized_area_mm2"] == 16


def test_zero_curve_error_does_not_create_unserializable_corner_slivers():
    obstacle = box(4, 4, 6, 6)
    data = plan({"id": "surround", "type": "rect", "region": [1, 1, 9, 9]})

    result = compile_artwork(
        board(front=obstacle), data, edge_margin_mm=0, curve_error_mm=0
    )

    assert output_geometry(result).intersection(obstacle).area == 0


def test_classifies_zero_area_clipping_residue(monkeypatch):
    from lib import compiler

    monkeypatch.setattr(compiler, "ROUNDING_DISPLACEMENT_MM", 0)
    data = plan({"id": "touch", "type": "rect", "region": [10, 1, 11, 2]})

    result = compile_artwork(board(), data, edge_margin_mm=0, curve_error_mm=0)

    assert result.report["status"] == "all_removed"
    assert result.report["removed"]["non_area"] == {
        "total": 1,
        "types": {"LineString": 1},
    }


def test_rejects_output_that_exceeds_polygon_budget(monkeypatch):
    from lib import compiler

    monkeypatch.setattr(compiler, "MAX_OUTPUT_POLYGONS", 1)
    data = plan(
        {"id": "one", "type": "rect", "region": [1, 1, 2, 2]},
        {"id": "two", "type": "rect", "region": [3, 3, 4, 4]},
    )

    with pytest.raises(ValueError, match="output polygon budget"):
        compile_artwork(board(), data, edge_margin_mm=0)


def test_reports_unrepresentable_primitive_magnitude_cleanly():
    data = plan(
        {
            "id": "huge",
            "type": "polyline",
            "points": [[1, 1], [2, 2]],
            "width_mm": 1e308,
        }
    )

    with pytest.raises(ValueError, match="huge: primitive expansion"):
        compile_artwork(board(), data, edge_margin_mm=0)


def test_rejects_unrepresentable_clearance_before_geos():
    data = plan(
        {"id": "shape", "type": "rect", "region": [1, 1, 2, 2]},
        clearance=1e308,
    )

    with pytest.raises(ValueError, match="clearance_mm exceeds supported magnitude"):
        compile_artwork(board(front=box(4, 4, 6, 6)), data)


def test_output_ids_are_bounded_when_source_id_is_large():
    data = plan(
        {
            "id": "x" * 10_000,
            "type": "hatching",
            "region": [1, 1, 5, 5],
            "bar_width_mm": 0.2,
            "spacing_mm": 1,
        }
    )

    result = compile_artwork(board(), data, edge_margin_mm=0)

    assert max(map(len, (item["id"] for item in result.polygons))) < 100


def test_rejects_unsupported_residue_instead_of_silently_dropping(monkeypatch):
    from lib import compiler

    data = plan({"id": "shape", "type": "rect", "region": [1, 1, 2, 2]})
    monkeypatch.setattr(compiler, "expand_item", lambda item: [(item["id"], box(1, 1, 2, 2).boundary)])

    with pytest.raises(ValueError, match="unsupported geometry residue"):
        compile_artwork(board(), data, edge_margin_mm=0)


def test_conservative_profile_preserves_stricter_clearance_and_reports_origin():
    data = plan({"id": "field", "type": "rect", "region": [1, 1, 9, 9]}, clearance=0.1)
    obstacle = box(4, 4, 6, 6)
    result = compile_artwork(board(front=obstacle), data, manufacturing_profile="conservative")
    assert result.report["clearance_mm"] == 0.25
    assert result.report["requested_clearance_mm"] == 0.1
    assert output_geometry(result).distance(obstacle) >= 0.25
    assert result.report["manufacturing"]["text_height"] == "not_checked"
    assert result.report["manufacturing"]["profile"]["min_line_width_mm"] == 0.2
    stricter = compile_artwork(board(front=obstacle), {**data, "clearance_mm": 0.4},
                              manufacturing_profile="conservative")
    assert stricter.report["clearance_mm"] == 0.4


def test_profile_audits_clipped_fragment_without_removing_it():
    data = plan({"id": "strip", "type": "rect", "region": [1, 1, 9, 2]}, clearance=0)
    result = compile_artwork(board(front=box(0, 1.15, 10, 10)), data,
                             manufacturing_profile="conservative")
    assert result.polygons == []  # profile clearance removes the whole strip
    result = compile_artwork(board(front=box(0, 1.40, 10, 10)), data,
                             manufacturing_profile="conservative")
    assert result.polygons
    assert result.report["minimum_width"] == "review_required"
    assert not result.review_geometry.is_empty
    assert output_geometry(result).area > 0


def test_mutating_profile_report_cannot_change_future_compiles():
    import copy
    from lib.manufacturing import CONSERVATIVE_PROFILE
    original = copy.deepcopy(CONSERVATIVE_PROFILE)
    data = plan({"id": "field", "type": "rect", "region": [1, 1, 9, 9]}, clearance=0.1)
    try:
        first = compile_artwork(board(), data, manufacturing_profile="conservative")
        first.report["manufacturing"]["profile"]["min_mask_clearance_mm"] = 0
        first.report["manufacturing"]["profile"]["sources"][0]["provider"] = "mutated"
        second = compile_artwork(board(), data, manufacturing_profile="conservative")
        assert second.report["clearance_mm"] == 0.25
        assert second.report["manufacturing"]["profile"] == original
    finally:
        CONSERVATIVE_PROFILE.clear()
        CONSERVATIVE_PROFILE.update(original)
