"""Bounded, non-certifying manufacturability checks for final silk geometry."""

from __future__ import annotations

import math

from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union


MAX_INPUT_POLYGONS = 50_000
MAX_INPUT_VERTICES = 200_000
MAX_DIAGNOSTICS = 100
MAX_ABSOLUTE_VALUE_MM = 1_000_000

CONSERVATIVE_PROFILE = {
    "name": "conservative",
    "source_snapshot_date": "2026-09-30",
    "min_line_width_mm": 0.20,
    "min_mask_clearance_mm": 0.25,
    "min_text_height_mm": 1.0,
    "sources": [
        {
            "provider": "JLCPCB",
            "url": "https://jlcpcb.com/capabilities/pcb-capabilities",
        },
        {
            "provider": "JLCPCB",
            "url": "https://jlcpcb.com/blog/pcb-silkscreen",
        },
        {
            "provider": "PCBWay",
            "url": "https://www.pcbway.com/capabilities.html",
        },
    ],
    "caveats": [
        "Text height is guidance only because artwork geometry has no text semantics.",
        "The 0.25 mm mask clearance is an engineering extension based on JLCPCB "
        "guidance; it is not a verified PCBWay requirement.",
    ],
}


def _polygon_parts(geometry):
    """Return polygon leaves without invoking a topology operation."""
    if geometry is None:
        raise ValueError("manufacturing audit requires polygonal geometry")
    stack = [geometry]
    parts = []
    while stack:
        current = stack.pop()
        if current.is_empty:
            continue
        if current.geom_type == "Polygon":
            parts.append(current)
        elif current.geom_type in ("MultiPolygon", "GeometryCollection"):
            stack.extend(reversed(current.geoms))
        else:
            raise ValueError(
                f"manufacturing audit requires polygonal geometry, got {current.geom_type}"
            )
    return parts


def _vertex_count(polygon):
    return len(polygon.exterior.coords) + sum(
        len(ring.coords) for ring in polygon.interiors
    )


def _validate_parts(parts):
    if len(parts) > MAX_INPUT_POLYGONS:
        raise ValueError(
            f"manufacturing audit polygon limit exceeded ({MAX_INPUT_POLYGONS})"
        )
    vertices = 0
    for polygon in parts:
        if not polygon.is_valid:
            raise ValueError("manufacturing audit requires valid polygonal geometry")
        vertices += _vertex_count(polygon)
        if vertices > MAX_INPUT_VERTICES:
            raise ValueError(
                f"manufacturing audit vertex limit exceeded ({MAX_INPUT_VERTICES})"
            )
        for ring in (polygon.exterior, *polygon.interiors):
            for coordinate in ring.coords:
                x, y = coordinate[:2]
                if (
                    not math.isfinite(x)
                    or not math.isfinite(y)
                    or abs(x) > MAX_ABSOLUTE_VALUE_MM
                    or abs(y) > MAX_ABSOLUTE_VALUE_MM
                ):
                    raise ValueError(
                        "manufacturing audit geometry exceeds supported magnitude"
                    )
        if not math.isfinite(float(polygon.area)):
            raise ValueError("manufacturing audit geometry has non-finite area")
    return vertices


def _summary(polygon):
    return {
        "area_mm2": round(float(polygon.area), 9),
        "bounds_mm": [round(float(value), 6) for value in polygon.bounds],
    }


def audit_geometry(geometry, min_width_mm=CONSERVATIVE_PROFILE["min_line_width_mm"]):
    """Audit final union silk geometry and return ``(report, problem_geometry)``.

    The test is deliberately conservative and diagnostic.  A mitred
    morphological opening finds components and features that cannot contain a
    shape approximately ``min_width_mm`` wide.  It is not a fab acceptance
    certificate and it never modifies the supplied geometry.
    """
    if (
        isinstance(min_width_mm, bool)
        or not isinstance(min_width_mm, (int, float))
        or not math.isfinite(min_width_mm)
        or min_width_mm <= 0
        or min_width_mm > MAX_ABSOLUTE_VALUE_MM
    ):
        raise ValueError("minimum line width must be finite and positive")

    parts = _polygon_parts(geometry)
    input_vertices = _validate_parts(parts)
    if not parts:
        merged_parts = []
        merged = GeometryCollection()
    else:
        try:
            merged = unary_union(parts)
        except (GEOSException, OverflowError, FloatingPointError) as error:
            raise ValueError("manufacturing audit could not union input geometry") from error
        merged_parts = _polygon_parts(merged)
        if not merged.is_valid:
            raise ValueError("manufacturing audit union produced invalid geometry")
        if not math.isfinite(float(merged.area)):
            raise ValueError("manufacturing audit union has non-finite area")

    # GEOS can collapse a polygon when a negative buffer leaves only a few
    # micrometres.  This tolerance is 20 times the six-decimal serialization
    # unit, and only relaxes the nominal width by 0.00004 mm.
    tolerance_mm = min(
        max(0.00002, float(min_width_mm) * 1e-6), float(min_width_mm) / 4
    )
    radius = float(min_width_mm) / 2 - tolerance_mm
    area_tolerance = max(1e-12, float(merged.area) * 1e-12)
    feature_loss_area_floor = max(
        area_tolerance, tolerance_mm * float(min_width_mm)
    )

    empty_components = 0
    split_components = 0
    ignored_residue = 0
    losses = []
    try:
        for component in merged_parts:
            eroded = component.buffer(-radius, join_style="mitre")
            if not math.isfinite(float(eroded.area)):
                raise ValueError("manufacturing audit erosion has non-finite area")
            if eroded.is_empty:
                empty_components += 1
                losses.extend(_polygon_parts(component))
            else:
                eroded_parts = _polygon_parts(eroded)
                if len(eroded_parts) > 1:
                    split_components += len(eroded_parts) - 1
                opened = eroded.buffer(radius, join_style="mitre")
                if not math.isfinite(float(opened.area)):
                    raise ValueError("manufacturing audit opening has non-finite area")
                loss = component.difference(opened)
                for part in _polygon_parts(loss):
                    area = float(part.area)
                    if not math.isfinite(area):
                        raise ValueError(
                            "manufacturing audit diagnostic has non-finite area"
                        )
                    if area > feature_loss_area_floor:
                        losses.append(part)
                    elif area > area_tolerance:
                        ignored_residue += 1
    except (GEOSException, OverflowError, FloatingPointError) as error:
        raise ValueError("manufacturing audit morphology failed") from error

    losses = sorted(
        losses,
        key=lambda part: (
            tuple(round(float(value), 9) for value in part.bounds),
            round(float(part.area), 12),
            part.wkb,
        ),
    )
    selected = losses[:MAX_DIAGNOSTICS]
    problems = GeometryCollection(selected)
    risk = bool(empty_components or split_components or losses)
    status = "review_required" if risk else "heuristic_passed"
    report = {
        "status": status,
        "minimum_width": status,
        "method": "mitre morphological opening",
        "min_line_width_mm": float(min_width_mm),
        "tolerance_mm": tolerance_mm,
        "feature_loss_area_floor_mm2": feature_loss_area_floor,
        "inspected_area_mm2": round(float(merged.area), 9),
        "input": {
            "polygon_count": len(parts),
            "vertex_count": input_vertices,
            "union_component_count": len(merged_parts),
        },
        "checks": {
            "eroded_empty_components": empty_components,
            "eroded_component_splits": split_components,
            "opening_feature_loss": len(losses),
            "opening_residue_ignored": ignored_residue,
            "minimum_gap": "not_checked",
            "text_height": "not_checked",
        },
        "diagnostics": {
            "total": len(losses),
            "returned": len(selected),
            "truncated": len(losses) > len(selected),
            "features": [_summary(part) for part in selected],
        },
        "limitations": [
            "This morphology test is heuristic and cannot prove every local line width.",
            "It is not a manufacturing certification or provider CAM approval.",
            "Minimum negative-space gaps and text height are not checked.",
            "Process registration, ink behavior, materials, and CAM edits are not modeled.",
        ],
    }
    return report, problems
