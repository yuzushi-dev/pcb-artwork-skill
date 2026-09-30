"""Expand v1 artwork primitives into area geometry."""

import math
import sys

from shapely import affinity
from shapely.errors import GEOSException
from shapely.geometry import LineString, Polygon, box


def _hatching(item):
    x1, y1, x2, y2 = item["region"]
    region = box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    radius = math.hypot(x2 - x1, y2 - y1) / 2
    pitch = item["spacing_mm"]
    width = item["bar_width_mm"]
    if width > math.sqrt(sys.float_info.max):
        raise OverflowError("hatch width exceeds supported magnitude")
    extent = radius + width
    last_offset = math.ceil(radius / pitch)
    angle = item.get("angle_deg", 0)
    bars = []
    for index, step in enumerate(range(-last_offset, last_offset + 1)):
        offset = step * pitch
        line = LineString(
            [
                (center_x - extent, center_y + offset),
                (center_x + extent, center_y + offset),
            ]
        )
        bar = line.buffer(width / 2, cap_style="flat", join_style="mitre")
        if angle:
            bar = affinity.rotate(bar, angle, origin=(center_x, center_y))
        bar = bar.intersection(region)
        if not bar.is_empty and bar.area:
            bars.append((f"{index:05d}", bar))
    return bars


def _expand_item(item):
    kind = item["type"]
    if kind == "polygon":
        geometry = Polygon(item["points"])
    elif kind == "polyline":
        if item["width_mm"] > math.sqrt(sys.float_info.max):
            raise OverflowError("polyline width exceeds supported magnitude")
        geometry = LineString(item["points"]).buffer(
            item["width_mm"] / 2, cap_style="flat", join_style="mitre"
        )
    elif kind == "rect":
        x1, y1, x2, y2 = item["region"]
        geometry = box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    elif kind == "hatching":
        return _hatching(item)
    else:
        raise ValueError(f"unsupported artwork primitive: {kind}")
    return [("00000", geometry)]


def expand_item(item):
    """Return checked, deterministic ``(expanded_id, geometry)`` pairs."""
    label = item["id"][:80]
    try:
        expanded = _expand_item(item)
    except (GEOSException, OverflowError, FloatingPointError) as error:
        raise ValueError(f"{label}: primitive expansion failed") from error
    for _, geometry in expanded:
        finite_bounds = all(math.isfinite(value) for value in geometry.bounds)
        if (
            geometry.is_empty
            or geometry.geom_type not in ("Polygon", "MultiPolygon")
            or not geometry.is_valid
            or not math.isfinite(geometry.area)
            or not finite_bounds
        ):
            raise ValueError(f"{label}: primitive expansion is empty, invalid, or non-finite")
    return expanded
