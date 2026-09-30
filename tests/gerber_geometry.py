"""Turn the supported Gerber primitives into conservative Shapely geometry."""

from __future__ import annotations

import math
import warnings

from shapely import affinity
from shapely.geometry import Point, Polygon, box


DEFAULT_MAX_ERROR_MM = 0.0002


def _primitive_geometry(primitive, max_error):
    from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle

    if isinstance(primitive, Circle):
        radius = primitive.r + max_error
        quad_segs = max(8, math.ceil(math.pi / math.acos(1 - max_error / radius) / 4))
        geometry = Point(primitive.x, primitive.y).buffer(radius, quad_segs=quad_segs)
    elif isinstance(primitive, Rectangle):
        geometry = box(
            primitive.x - primitive.w / 2,
            primitive.y - primitive.h / 2,
            primitive.x + primitive.w / 2,
            primitive.y + primitive.h / 2,
        )
        geometry = affinity.rotate(
            geometry, primitive.rotation, origin=(primitive.x, primitive.y), use_radians=True
        )
    elif isinstance(primitive, (Arc, ArcPoly, Line)):
        if isinstance(primitive, (Arc, Line)):
            primitive = primitive.to_arc_poly()
        has_arcs = any(center is not None for center in primitive.arc_centers)
        approximated = primitive.approximate_arcs(max_error=max_error)
        geometry = Polygon(approximated.outline)
        if has_arcs:
            geometry = geometry.buffer(max_error)
    else:
        raise TypeError(f"Unsupported Gerber primitive: {type(primitive).__name__}")

    return affinity.scale(geometry, yfact=-1, origin=(0, 0))


def apply_primitive(accumulated, primitive, max_error=DEFAULT_MAX_ERROR_MM):
    geometry = _primitive_geometry(primitive, max_error)
    if primitive.polarity_dark:
        return accumulated.union(geometry)
    if max_error:
        geometry = geometry.buffer(-max_error)
    return accumulated.difference(geometry)


def read_gerber_geometry(path, max_error=DEFAULT_MAX_ERROR_MM):
    from gerbonara import GerberFile
    from gerbonara.utils import MM

    return _objects_geometry(GerberFile.open(path), max_error)


def read_excellon_geometry(path, max_error=DEFAULT_MAX_ERROR_MM):
    from gerbonara import ExcellonFile

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r'.*"G90": G90 header statement found after end of header',
            category=SyntaxWarning,
        )
        layer = ExcellonFile.open(path)
    return _objects_geometry(layer, max_error)


def _objects_geometry(layer, max_error):
    from gerbonara.utils import MM

    geometry = Polygon()
    for obj in layer.objects:
        for primitive in obj.to_primitives(unit=MM):
            geometry = apply_primitive(geometry, primitive, max_error=max_error)
    return geometry
