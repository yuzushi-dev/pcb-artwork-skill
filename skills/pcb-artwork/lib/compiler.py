"""Compile validated artwork against a board's printable geometry."""

from dataclasses import dataclass
from copy import deepcopy
import math
import sys

from shapely import constrained_delaunay_triangles
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, Polygon
from shapely.ops import unary_union

from .primitives import expand_item
from .validation import validate


PRECISION = 6
ROUNDING_DISPLACEMENT_MM = math.sqrt(2) * 0.5 * 10**-PRECISION
MAX_OUTPUT_POLYGONS = 50_000
MAX_OUTPUT_VERTICES = 200_000
MAX_GEOMETRY_MAGNITUDE = math.sqrt(sys.float_info.max)


@dataclass(frozen=True)
class Compilation:
    polygons: list
    layer: str
    report: dict
    review_geometry: object = None


def _polygon_parts(geometry, nonarea=None):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type in ("MultiPolygon", "GeometryCollection"):
        parts = []
        for child in geometry.geoms:
            if child.is_empty:
                continue
            parts.extend(_polygon_parts(child, nonarea))
        return parts
    if nonarea is not None and geometry.geom_type in (
        "Point", "MultiPoint", "LineString", "MultiLineString", "LinearRing"
    ):
        nonarea.append(geometry.geom_type)
        return []
    raise ValueError(f"unsupported geometry residue: {geometry.geom_type}")


def _simple_parts(polygon):
    if not polygon.interiors:
        return [polygon]
    triangles = constrained_delaunay_triangles(polygon)
    parts = [part for part in _polygon_parts(triangles) if part.area]
    assembled = unary_union(parts) if parts else GeometryCollection()
    tolerance = max(1e-12, polygon.area * 1e-12)
    if assembled.symmetric_difference(polygon).area > tolerance:
        raise ValueError("hole decomposition does not preserve artwork geometry")
    if any(not polygon.covers(part) or part.interiors for part in parts):
        raise ValueError("hole decomposition produced geometry outside artwork")
    return parts


def _serialize(polygon):
    points = [
        [round(float(x), PRECISION), round(float(y), PRECISION)]
        for x, y in list(polygon.exterior.coords)[:-1]
    ]
    serialized = Polygon(points)
    if len(points) < 3 or not serialized.is_valid or serialized.area <= 0:
        raise ValueError("geometry collapsed during six-decimal serialization")
    return points, serialized


def _rounded_area(value):
    return round(float(value), PRECISION)


def _expand_obstacles(obstacles, clearance, curve_error):
    radius = clearance + 2 * curve_error + 2 * ROUNDING_DISPLACEMENT_MM
    if radius == 0 or obstacles.is_empty:
        return obstacles
    if curve_error == 0:
        return obstacles.buffer(radius, join_style="mitre")
    allowed_sagitta = curve_error + ROUNDING_DISPLACEMENT_MM
    ratio = max(-1.0, min(1.0, 1 - allowed_sagitta / radius))
    angle = math.acos(ratio)
    quad_segs = math.ceil(math.pi / (4 * angle)) if angle else 257
    if quad_segs > 256:
        return obstacles.buffer(radius, join_style="mitre")
    return obstacles.buffer(radius, quad_segs=max(8, quad_segs), join_style="round")


def compile_artwork(board, data, edge_margin_mm=None, curve_error_mm=0.001,
                    manufacturing_profile=None):
    """Clip a validated v1 plan to the board and return simple polygons."""
    validate(data)
    if curve_error_mm < 0 or not math.isfinite(curve_error_mm):
        raise ValueError("curve_error_mm must be a finite non-negative number")
    if curve_error_mm > MAX_GEOMETRY_MAGNITUDE:
        raise ValueError("curve_error_mm exceeds supported magnitude")
    clearance = data.get("clearance_mm", 0.16)
    if clearance > MAX_GEOMETRY_MAGNITUDE:
        raise ValueError("clearance_mm exceeds supported magnitude")
    requested_clearance = clearance
    if manufacturing_profile not in (None, "conservative"):
        raise ValueError("unsupported manufacturing profile")
    if manufacturing_profile:
        from .manufacturing import CONSERVATIVE_PROFILE
        clearance = max(clearance, CONSERVATIVE_PROFILE["min_mask_clearance_mm"])
    edge_margin = clearance if edge_margin_mm is None else edge_margin_mm
    if edge_margin < 0 or not math.isfinite(edge_margin):
        raise ValueError("edge_margin_mm must be a finite non-negative number")
    if edge_margin > MAX_GEOMETRY_MAGNITUDE:
        raise ValueError("edge_margin_mm exceeds supported magnitude")

    layer = data["layer"]
    try:
        board_area = board.area
        obstacles = board.obstacles[layer]
    except (AttributeError, KeyError) as error:
        raise ValueError(f"board geometry is missing layer {layer}") from error
    if board_area.is_empty or not board_area.is_valid:
        raise ValueError("board area is empty or invalid")
    if not obstacles.is_valid:
        raise ValueError(f"board obstacles for {layer} are invalid")

    guard = curve_error_mm + 2 * ROUNDING_DISPLACEMENT_MM
    try:
        printable = board_area.buffer(-(edge_margin + guard), join_style="mitre")
        protected = _expand_obstacles(obstacles, clearance, curve_error_mm)
        allowed = printable.difference(protected)
    except (GEOSException, OverflowError, FloatingPointError) as error:
        raise ValueError("board clearance geometry exceeds supported magnitude") from error

    output = []
    input_geometries = []
    serialized_geometries = []
    fully_removed = []
    affected = []
    removed_areas = {}
    fragment_count = 0
    nonarea_types = []
    empty_fragments = 0
    output_vertices = 0

    for source_index, item in enumerate(data["items"]):
        expanded = expand_item(item)
        unsupported = [
            geometry.geom_type
            for _, geometry in expanded
            if geometry.geom_type not in ("Polygon", "MultiPolygon")
        ]
        if unsupported:
            raise ValueError(f"unsupported geometry residue from primitive: {unsupported[0]}")
        item_input = unary_union([geometry for _, geometry in expanded])
        item_input_area = item_input.area
        input_geometries.append(item_input)
        clipped_parts = []
        for expanded_id, geometry in expanded:
            clipped = geometry.intersection(allowed)
            if clipped.is_empty:
                empty_fragments += 1
            for component_index, component in enumerate(
                _polygon_parts(clipped, nonarea_types)
            ):
                clipped_parts.append((expanded_id, component_index, component))

        clipped_area = unary_union(
            [component for _, _, component in clipped_parts]
        ).area if clipped_parts else 0.0
        removed_area = max(0.0, item_input_area - clipped_area)
        if removed_area > 1e-12:
            affected.append(item["id"])
            removed_areas[item["id"]] = _rounded_area(removed_area)
        if item_input_area and not clipped_parts:
            fully_removed.append(item["id"])
        fragment_count += len(clipped_parts)

        output_index = 0
        source_label = item["id"][:40]
        for expanded_id, component_index, component in clipped_parts:
            simple = _simple_parts(component)
            decomposed = unary_union(simple) if simple else GeometryCollection()
            if decomposed.symmetric_difference(component).area > max(
                1e-12, component.area * 1e-12
            ):
                raise ValueError("polygon decomposition changed artwork geometry")
            serialized_parts = []
            for part in simple:
                points, serialized = _serialize(part)
                if len(output) >= MAX_OUTPUT_POLYGONS:
                    raise ValueError(
                        f"output polygon budget exceeded: maximum {MAX_OUTPUT_POLYGONS}"
                    )
                output_vertices += len(points)
                if output_vertices > MAX_OUTPUT_VERTICES:
                    raise ValueError(
                        f"output vertex budget exceeded: maximum {MAX_OUTPUT_VERTICES}"
                    )
                if not board_area.covers(serialized):
                    raise ValueError("serialized polygon extends outside the board")
                if edge_margin and serialized.distance(board_area.boundary) < edge_margin:
                    raise ValueError("serialized polygon violates board-edge margin")
                if not obstacles.is_empty and serialized.distance(obstacles) < clearance:
                    raise ValueError("serialized polygon violates obstacle clearance")
                identifier = (
                    f"{source_label}:{source_index:05d}:{str(expanded_id)[:16]}:"
                    f"{component_index:05d}:{output_index:05d}"
                )
                output.append({"id": identifier, "points": points})
                output_index += 1
                serialized_parts.append(serialized)
                serialized_geometries.append(serialized)

            serialized_union = unary_union(serialized_parts)
            rounding_tolerance = max(
                1e-12, component.length * ROUNDING_DISPLACEMENT_MM * 2
            )
            if serialized_union.symmetric_difference(component).area > rounding_tolerance:
                raise ValueError("six-decimal serialization changed artwork geometry")

    serialized_union = unary_union(serialized_geometries) if serialized_geometries else GeometryCollection()
    review_geometry = GeometryCollection()
    manufacturing = None
    if manufacturing_profile:
        from .manufacturing import audit_geometry
        manufacturing, review_geometry = audit_geometry(
            serialized_union, CONSERVATIVE_PROFILE["min_line_width_mm"])
        manufacturing = {**manufacturing, "profile": deepcopy(CONSERVATIVE_PROFILE),
                         "text_height": "not_checked",
                         "text_height_reason": "input contains geometry without text semantics"}
    report = {
        "status": "all_removed" if not output else "passed",
        "input_validation": "passed",
        "geometry": "passed",
        "minimum_width": manufacturing["status"] if manufacturing else "not_checked",
        "requested_clearance_mm": requested_clearance,
        "layer": layer,
        "clearance_mm": clearance,
        "edge_margin_mm": edge_margin,
        "curve_error_mm": curve_error_mm,
        "input_area_mm2": _rounded_area(
            unary_union(input_geometries).area if input_geometries else 0
        ),
        "serialized_area_mm2": _rounded_area(
            serialized_union.area
        ),
        "removed": {
            "total": len(fully_removed),
            "source_ids": affected,
            "fragments": fragment_count,
            "areas_mm2": removed_areas,
            "empty": empty_fragments,
            "non_area": {
                "total": len(nonarea_types),
                "types": {
                    kind: nonarea_types.count(kind) for kind in sorted(set(nonarea_types))
                },
            },
        },
    }
    if manufacturing:
        report["manufacturing"] = manufacturing
    return Compilation(polygons=output, layer=layer, report=report, review_geometry=review_geometry)
