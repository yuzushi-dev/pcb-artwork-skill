import sys
from pathlib import Path

import pytest
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union


SKILL = Path(__file__).resolve().parents[1] / "skills" / "pcb-artwork"
sys.path.insert(0, str(SKILL))

from lib import manufacturing
from lib.manufacturing import CONSERVATIVE_PROFILE, audit_geometry


def test_conservative_profile_records_values_sources_and_caveats():
    assert CONSERVATIVE_PROFILE["min_line_width_mm"] == 0.20
    assert CONSERVATIVE_PROFILE["min_mask_clearance_mm"] == 0.25
    assert CONSERVATIVE_PROFILE["min_text_height_mm"] == 1.0
    assert CONSERVATIVE_PROFILE["source_snapshot_date"] == "2026-09-30"
    assert {source["provider"] for source in CONSERVATIVE_PROFILE["sources"]} == {
        "JLCPCB",
        "PCBWay",
    }
    assert all(source["url"].startswith("https://") for source in CONSERVATIVE_PROFILE["sources"])
    assert "text" in CONSERVATIVE_PROFILE["caveats"][0].lower()
    assert "PCBWay" in CONSERVATIVE_PROFILE["caveats"][1]


def test_isolated_strip_below_minimum_width_requires_review():
    report, problems = audit_geometry(box(0, 0, 4, 0.19))

    assert report["status"] == "review_required"
    assert report["minimum_width"] == "review_required"
    assert report["checks"]["eroded_empty_components"] == 1
    assert report["checks"]["opening_feature_loss"] >= 1
    assert problems.area == pytest.approx(0.76)


def test_exact_threshold_and_wide_rectangles_do_not_warn_for_corners():
    geometry = MultiPolygon(
        [box(0, 0, 4, 0.20), box(0, 2, 4, 3), Point(8, 1).buffer(1)]
    )

    report, problems = audit_geometry(geometry)

    assert report["status"] == "heuristic_passed"
    assert report["minimum_width"] == "heuristic_passed"
    assert report["checks"] == {
        "eroded_empty_components": 0,
        "eroded_component_splits": 0,
        "opening_feature_loss": 0,
        "opening_residue_ignored": 0,
        "minimum_gap": "not_checked",
        "text_height": "not_checked",
    }
    assert problems.is_empty


def test_empty_geometry_has_no_risks_and_records_zero_inspected_area():
    report, problems = audit_geometry(GeometryCollection())

    assert report["status"] == "heuristic_passed"
    assert report["inspected_area_mm2"] == 0
    assert report["input"]["union_component_count"] == 0
    assert problems.is_empty


def test_thin_neck_between_large_areas_is_reported():
    geometry = unary_union(
        [box(0, 0, 2, 2), box(3, 0, 5, 2), box(2, 0.95, 3, 1.05)]
    )

    report, problems = audit_geometry(geometry)

    assert report["status"] == "review_required"
    assert report["checks"]["eroded_empty_components"] == 0
    assert report["checks"]["eroded_component_splits"] == 1
    assert report["checks"]["opening_feature_loss"] >= 1
    assert problems.intersects(box(2.2, 0.94, 2.8, 1.06))


def test_union_of_serialization_triangles_has_no_artificial_seams():
    triangles = GeometryCollection(
        [
            Polygon([(0, 0), (4, 0), (4, 2)]),
            Polygon([(0, 0), (4, 2), (0, 2)]),
        ]
    )

    report, problems = audit_geometry(triangles)

    assert report["status"] == "heuristic_passed"
    assert report["input"]["polygon_count"] == 2
    assert report["input"]["union_component_count"] == 1
    assert problems.is_empty


def test_wide_shape_with_hole_is_preserved_and_input_is_not_mutated():
    geometry = box(0, 0, 10, 10).difference(box(2, 2, 8, 8))
    original_wkb = geometry.wkb

    report, problems = audit_geometry(geometry)

    assert geometry.wkb == original_wkb
    assert report["status"] == "heuristic_passed"
    assert report["checks"]["opening_feature_loss"] == 0
    assert problems.is_empty


def test_polygonal_round_hole_and_attached_numeric_dust_do_not_warn():
    round_hole = Point(2, 2).buffer(0.5, quad_segs=64)
    annulus = box(0, 0, 4, 4).difference(round_hole)
    numeric_dust = box(4, 1.99, 4.00001, 2.00001)

    report, problems = audit_geometry(unary_union([annulus, numeric_dust]))

    assert report["status"] == "heuristic_passed"
    assert report["checks"]["opening_feature_loss"] == 0
    assert report["checks"]["opening_residue_ignored"] >= 1
    assert problems.is_empty


def test_tiny_disconnected_component_is_never_filtered_as_numeric_dust():
    geometry = MultiPolygon([box(0, 0, 1, 1), box(2, 0, 2.0001, 0.0001)])

    report, problems = audit_geometry(geometry)

    assert report["status"] == "review_required"
    assert report["checks"]["eroded_empty_components"] == 1
    assert problems.area == pytest.approx(1e-8)


def test_diagnostics_are_deterministic_and_capped(monkeypatch):
    monkeypatch.setattr(manufacturing, "MAX_DIAGNOSTICS", 2)
    geometry = MultiPolygon([box(index, 0, index + 0.5, 0.1) for index in range(3)])

    first_report, first_problems = audit_geometry(geometry)
    second_report, second_problems = audit_geometry(geometry)

    assert first_report == second_report
    assert first_problems.wkb == second_problems.wkb
    assert first_report["diagnostics"]["total"] == 3
    assert first_report["diagnostics"]["returned"] == 2
    assert first_report["diagnostics"]["truncated"] is True
    assert len(first_report["diagnostics"]["features"]) == 2


def test_polygon_limit_is_checked_before_union(monkeypatch):
    monkeypatch.setattr(manufacturing, "MAX_INPUT_POLYGONS", 1)
    monkeypatch.setattr(
        manufacturing,
        "unary_union",
        lambda unused: (_ for _ in ()).throw(AssertionError("union was called")),
    )

    with pytest.raises(ValueError, match="polygon limit"):
        audit_geometry(MultiPolygon([box(0, 0, 1, 1), box(2, 0, 3, 1)]))


def test_vertex_limit_is_checked_before_union(monkeypatch):
    monkeypatch.setattr(manufacturing, "MAX_INPUT_VERTICES", 4)
    monkeypatch.setattr(
        manufacturing,
        "unary_union",
        lambda unused: (_ for _ in ()).throw(AssertionError("union was called")),
    )

    with pytest.raises(ValueError, match="vertex limit"):
        audit_geometry(box(0, 0, 1, 1))


@pytest.mark.parametrize("width", [0, -0.2, float("inf"), float("nan")])
def test_minimum_width_must_be_finite_and_positive(width):
    with pytest.raises(ValueError, match="minimum line width"):
        audit_geometry(box(0, 0, 1, 1), min_width_mm=width)


def test_non_polygonal_and_invalid_geometry_are_rejected():
    with pytest.raises(ValueError, match="polygonal"):
        audit_geometry(Point(0, 0))

    bow_tie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    with pytest.raises(ValueError, match="valid"):
        audit_geometry(bow_tie)


def test_extreme_coordinates_are_rejected_before_union(monkeypatch):
    monkeypatch.setattr(
        manufacturing,
        "unary_union",
        lambda unused: (_ for _ in ()).throw(AssertionError("union was called")),
    )

    with pytest.raises(ValueError, match="supported magnitude"):
        audit_geometry(box(0, 0, 1e154, 1e154))


def test_report_states_method_and_non_certifying_limitations():
    report, unused = audit_geometry(box(0, 0, 1, 1))

    assert report["method"] == "mitre morphological opening"
    assert report["min_line_width_mm"] == 0.20
    assert report["tolerance_mm"] > 0
    assert any("heuristic" in limitation.lower() for limitation in report["limitations"])
    assert any("certif" in limitation.lower() for limitation in report["limitations"])
    assert report["checks"]["minimum_gap"] == "not_checked"
    assert report["checks"]["text_height"] == "not_checked"
    assert any("registration" in limitation.lower() for limitation in report["limitations"])
