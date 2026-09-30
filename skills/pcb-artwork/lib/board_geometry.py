"""Read the supported KiCad 10 board geometry without rewriting the board.

Geometry semantics follow KiCad's 20241229 board format and were checked
against KiCad 10.0.5.  In particular, footprint-relative positions rotate
clockwise in numeric board coordinates, pad angles are already absolute, and
a pad drill ``offset`` moves the pad body while the physical drill stays at
the nominal pad position.
"""

from collections import Counter
from dataclasses import dataclass
import math

from shapely import affinity, get_num_coordinates
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Polygon, box
from shapely.ops import polygonize_full, unary_union
from shapely.strtree import STRtree

try:
    from .sexpr import Node, parse
except ImportError:  # The installable skill also supports direct lib imports.
    from sexpr import Node, parse


SUPPORTED_VERSION = "20241229"
SILK_TO_MASK = {"F.SilkS": "F.Mask", "B.SilkS": "B.Mask"}
MAX_CURVE_SEGMENTS = 16_384
MAX_GEOMETRY_VERTICES = 200_000
MAX_ABSOLUTE_VALUE = 1_000_000.0


class GeometryError(ValueError):
    """Unsupported or invalid protected geometry with source position."""


@dataclass(frozen=True)
class BoardGeometry:
    area: object
    obstacles: dict
    inventory: dict
    version: str


class _VertexBudget:
    def __init__(self, text):
        self.text = text
        self.used = 0

    def reserve(self, count, node):
        if count < 0 or self.used + count > MAX_GEOMETRY_VERTICES:
            _fail(
                self.text,
                node,
                f"geometry vertex budget exceeded: maximum {MAX_GEOMETRY_VERTICES}",
            )
        self.used += count


def _position(text, node):
    offset = node.start
    line = text.count("\n", 0, offset) + 1
    column = offset - text.rfind("\n", 0, offset)
    return f"line {line}, column {column}, offset {offset}"


def _fail(text, node, message):
    raise GeometryError(f"{message} at {_position(text, node)}")


def _number(text, node, value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail(text, node, f"{label} must be numeric")
    if not math.isfinite(number):
        _fail(text, node, f"{label} must be finite")
    if abs(number) > MAX_ABSOLUTE_VALUE:
        _fail(text, node, f"{label} exceeds supported magnitude {MAX_ABSOLUTE_VALUE:g}")
    return number


def _child_numbers(text, parent, head, count, required=True):
    child = parent.child(head)
    if child is None:
        if required:
            _fail(text, parent, f"missing ({head} ...) field")
        return None
    atoms = child.values[1:]
    if len(atoms) != count or any(not isinstance(value, str) for value in atoms):
        _fail(text, child, f"({head} ...) requires exactly {count} numeric values")
    return tuple(_number(text, child, atom, head) for atom in atoms)


def _at(text, parent, label, allow_angle):
    child = parent.child("at")
    if child is None:
        _fail(text, parent, f"missing ({label} at ...) field")
    atoms = child.values[1:]
    allowed = {2, 3} if allow_angle else {2}
    if len(atoms) not in allowed or any(not isinstance(value, str) for value in atoms):
        expected = "2 or 3" if allow_angle else "exactly 2"
        _fail(text, child, f"({label} at ...) requires {expected} numeric values")
    position = tuple(_number(text, child, value, f"{label} at") for value in atoms[:2])
    angle = _number(text, child, atoms[2], f"{label} angle") if len(atoms) == 3 else 0.0
    return position, angle


def _layer(text, node):
    layer = node.child("layer")
    if layer:
        if len(layer.values) != 2 or not isinstance(layer.values[1], str):
            _fail(text, layer, "(layer ...) requires exactly one layer name")
        return layer.values[1]
    return None


def _layers(node):
    layers = node.child("layers")
    if layers is None:
        return []
    return [value for value in layers.values[1:] if isinstance(value, str)]


def _rotate_vector(point, angle_degrees):
    angle = math.radians(angle_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    x, y = point
    return (cosine * x + sine * y, -sine * x + cosine * y)


def _placed(local, origin, angle_degrees):
    x, y = _rotate_vector(local, angle_degrees)
    return (origin[0] + x, origin[1] + y)


def _max_angle(radius, error):
    if radius <= 0:
        return math.tau
    if error >= radius:
        return math.pi
    # 4*asin(sqrt(e/(2r))) is equivalent to 2*acos(1-e/r) but
    # remains nonzero when e/r is too small for ``1 - e/r`` to change.
    return 4 * math.asin(math.sqrt(error / (2 * radius)))


def _segment_count(radius, sweep, error):
    count = max(2, math.ceil(abs(sweep) / _max_angle(radius, error)))
    if count > MAX_CURVE_SEGMENTS:
        raise ValueError(
            f"curve_error_mm requires {count} segments; maximum is {MAX_CURVE_SEGMENTS}"
        )
    return count


def _circle_line(center, radius, error, budget, node):
    if radius <= 0:
        raise ValueError("circle radius must be positive")
    count = max(8, _segment_count(radius, math.tau, error))
    budget.reserve(count + 1, node)
    points = [
        (
            center[0] + radius * math.cos(math.tau * index / count),
            center[1] + radius * math.sin(math.tau * index / count),
        )
        for index in range(count)
    ]
    points.append(points[0])
    return LineString(points)


def _arc_points(start, middle, end, error, budget, node):
    x1, y1 = start
    x2, y2 = middle
    x3, y3 = end
    denominator = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(denominator) < 1e-12:
        raise ValueError("arc points are collinear")
    ux = (
        (x1 * x1 + y1 * y1) * (y2 - y3)
        + (x2 * x2 + y2 * y2) * (y3 - y1)
        + (x3 * x3 + y3 * y3) * (y1 - y2)
    ) / denominator
    uy = (
        (x1 * x1 + y1 * y1) * (x3 - x2)
        + (x2 * x2 + y2 * y2) * (x1 - x3)
        + (x3 * x3 + y3 * y3) * (x2 - x1)
    ) / denominator
    radius = math.hypot(x1 - ux, y1 - uy)
    angles = [math.atan2(y - uy, x - ux) for x, y in (start, middle, end)]
    counterclockwise = (angles[2] - angles[0]) % math.tau
    middle_ccw = (angles[1] - angles[0]) % math.tau
    sweep = counterclockwise if middle_ccw <= counterclockwise else counterclockwise - math.tau
    count = _segment_count(radius, sweep, error)
    budget.reserve(count + 1, node)
    points = [
        (
            ux + radius * math.cos(angles[0] + sweep * index / count),
            uy + radius * math.sin(angles[0] + sweep * index / count),
        )
        for index in range(count + 1)
    ]
    points[0] = start
    points[-1] = end
    return points


def _curve_node_line(text, node, error, budget):
    try:
        if node.head in {"gr_line", "fp_line"}:
            budget.reserve(2, node)
            return LineString(
                [_child_numbers(text, node, "start", 2), _child_numbers(text, node, "end", 2)]
            ), False
        if node.head in {"gr_arc", "fp_arc"}:
            points = _arc_points(
                _child_numbers(text, node, "start", 2),
                _child_numbers(text, node, "mid", 2),
                _child_numbers(text, node, "end", 2),
                error,
                budget,
                node,
            )
            return LineString(points), True
        if node.head in {"gr_rect", "fp_rect"}:
            start = _child_numbers(text, node, "start", 2)
            end = _child_numbers(text, node, "end", 2)
            if start[0] == end[0] or start[1] == end[1]:
                _fail(text, node, "degenerate rectangle")
            budget.reserve(5, node)
            rectangle = box(min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1]))
            return LineString(rectangle.exterior.coords), False
        if node.head in {"gr_circle", "fp_circle"}:
            center = _child_numbers(text, node, "center", 2)
            end = _child_numbers(text, node, "end", 2)
            radius = math.dist(center, end)
            return _circle_line(center, radius, error, budget, node), True
    except GeometryError:
        raise
    except ValueError as error_value:
        _fail(text, node, str(error_value))
    _fail(text, node, f"unsupported curve '{node.head}'")


def _edge_area(text, root, error, budget):
    supported = {"gr_line", "gr_arc", "gr_rect", "gr_circle"}
    edge_nodes = []
    for value in root.values:
        if not isinstance(value, Node):
            continue
        if _layer(text, value) == "Edge.Cuts":
            if value.head not in supported:
                _fail(text, value, f"unsupported Edge.Cuts construct '{value.head}'")
            edge_nodes.append(value)
    for footprint in root.children("footprint"):
        for item in footprint.values:
            if isinstance(item, Node) and _layer(text, item) == "Edge.Cuts":
                _fail(text, item, f"unsupported footprint Edge.Cuts construct '{item.head}'")
    if not edge_nodes:
        _fail(text, root, "board has no supported Edge.Cuts contour")

    lines = []
    endpoint_degree = Counter()
    curved = False
    for node in edge_nodes:
        line, is_curved = _curve_node_line(text, node, error, budget)
        curved |= is_curved
        lines.append(line)
        if not line.is_ring:
            endpoint_degree[tuple(round(value, 9) for value in line.coords[0])] += 1
            endpoint_degree[tuple(round(value, 9) for value in line.coords[-1])] += 1
    if endpoint_degree and any(degree != 2 for degree in endpoint_degree.values()):
        _fail(text, edge_nodes[0], "open or disconnected Edge.Cuts contour")
    multiline = MultiLineString(lines)
    if not multiline.is_simple:
        _fail(text, edge_nodes[0], "self-intersecting or ambiguous Edge.Cuts contour")

    polygons, cuts, dangles, invalid = polygonize_full(lines)
    if not cuts.is_empty or not dangles.is_empty or not invalid.is_empty:
        _fail(text, edge_nodes[0], "open or disconnected Edge.Cuts contour")
    rings = {}
    for polygon in polygons.geoms:
        candidate = Polygon(polygon.exterior)
        rings[candidate.exterior.normalize().wkb] = candidate
    candidates = list(rings.values())
    if not candidates:
        _fail(text, edge_nodes[0], "Edge.Cuts does not enclose an area")

    area = GeometryCollection()
    tree = STRtree(candidates)
    for candidate in sorted(candidates, key=lambda item: item.area, reverse=True):
        point = candidate.representative_point()
        depth = sum(candidates[index].area > candidate.area for index in tree.query(point, predicate="within"))
        # Chords under-approximate curves.  Expanding cutout loops by the
        # stated sagitta bound keeps available board area conservative.
        loop = _round_buffer(candidate, error, error, budget, edge_nodes[0]) if curved and depth % 2 else candidate
        area = area.symmetric_difference(loop)
    if area.is_empty or not area.is_valid:
        _fail(text, edge_nodes[0], "invalid Edge.Cuts topology")
    return area, len(edge_nodes)


def _round_buffer(geometry, distance, error, budget, node):
    radius = max(abs(distance), error)
    quad_segs = max(2, math.ceil((math.pi / 2) / _max_angle(radius, error)))
    quad_segs = min(quad_segs, MAX_CURVE_SEGMENTS // 4)
    budget.reserve(get_num_coordinates(geometry) + 4 * quad_segs + 8, node)
    return geometry.buffer(distance, quad_segs=quad_segs)


def _oval(width, height, error, budget, node):
    if width <= 0 or height <= 0:
        raise ValueError("pad dimensions must be positive")
    radius = min(width, height) / 2
    if abs(width - height) < 1e-12:
        return Polygon(_circle_line((0, 0), radius, error, budget, node).coords)
    if width > height:
        half = (width - height) / 2
        axis = LineString([(-half, 0), (half, 0)])
    else:
        half = (height - width) / 2
        axis = LineString([(0, -half), (0, half)])
    return _round_buffer(axis, radius, error, budget, node)


def _pad_shape(text, pad, shape, width, height, ratio, error, budget):
    if width <= 0 or height <= 0:
        _fail(text, pad, "pad dimensions must be positive")
    try:
        if shape == "circle":
            if abs(width - height) > 1e-9:
                _fail(text, pad, "circular pad must have equal size axes")
            geometry = Polygon(_circle_line((0, 0), width / 2, error, budget, pad).coords)
        elif shape == "oval":
            geometry = _oval(width, height, error, budget, pad)
        elif shape == "rect":
            budget.reserve(5, pad)
            geometry = box(-width / 2, -height / 2, width / 2, height / 2)
        elif shape == "roundrect":
            if ratio is None:
                _fail(text, pad, "roundrect pad is missing roundrect_rratio")
            if not 0 <= ratio <= 0.5:
                _fail(text, pad, "roundrect_rratio must be between 0 and 0.5")
            radius = min(width, height) * ratio
            core = box(-width / 2 + radius, -height / 2 + radius, width / 2 - radius, height / 2 - radius)
            geometry = _round_buffer(core, radius, error, budget, pad)
        else:
            _fail(text, pad, f"unsupported protected pad shape '{shape}'")
    except GeometryError:
        raise
    except ValueError as error_value:
        _fail(text, pad, str(error_value))
    return geometry


def _margin(text, node):
    margin = node.child("solder_mask_margin")
    if margin is None:
        return None
    if len(margin.values) != 2 or not isinstance(margin.values[1], str):
        _fail(text, margin, "solder_mask_margin requires one number")
    return _number(text, margin, margin.values[1], "solder_mask_margin")


def _drill(text, pad, nominal, angle, error, budget):
    node = pad.child("drill")
    if node is None:
        return None, (0.0, 0.0)
    atoms = [value for value in node.values[1:] if isinstance(value, str)]
    oval = bool(atoms and atoms[0] == "oval")
    if oval:
        atoms = atoms[1:]
    expected = 2 if oval else 1
    if len(atoms) != expected:
        _fail(text, node, f"{'oval' if oval else 'circular'} drill requires {expected} size value(s)")
    sizes = [_number(text, node, value, "drill size") for value in atoms]
    if any(value <= 0 for value in sizes):
        _fail(text, node, "drill dimensions must be positive")
    offset = _child_numbers(text, node, "offset", 2, required=False) or (0.0, 0.0)
    try:
        geometry = _oval(sizes[0], sizes[1] if oval else sizes[0], error, budget, node)
    except GeometryError:
        raise
    except ValueError as error_value:
        _fail(text, node, str(error_value))
    geometry = affinity.rotate(geometry, -angle, origin=(0, 0))
    geometry = affinity.translate(geometry, nominal[0], nominal[1])
    return geometry, offset


def _tenting(text, node):
    """Return per-side overrides: True means solder mask covers the via."""
    tenting = node.child("tenting")
    if tenting is None:
        return {}
    overrides = {}
    atoms = [value for value in tenting.values[1:] if isinstance(value, str)]
    children = [value for value in tenting.values[1:] if isinstance(value, Node)]
    if atoms and children:
        _fail(text, tenting, "tenting cannot mix legacy atoms with front/back fields")
    tenting.child("front")
    tenting.child("back")
    if atoms:
        if len(atoms) != len(set(atoms)):
            _fail(text, tenting, "tenting contains a duplicate legacy side")
        if "none" in atoms:
            return {"F.SilkS": False, "B.SilkS": False}
        unknown = set(atoms) - {"front", "back"}
        if unknown:
            _fail(text, tenting, f"unsupported tenting value '{sorted(unknown)[0]}'")
        if "front" in atoms:
            overrides["F.SilkS"] = True
        if "back" in atoms:
            overrides["B.SilkS"] = True
    for child in children:
        if child.head not in {"front", "back"} or len(child.values) != 2:
            _fail(text, child, "tenting requires front/back boolean values")
        value = child.values[1]
        if value not in {"yes", "no", "true", "false"}:
            _fail(text, child, "tenting boolean must be yes or no")
        side = "F.SilkS" if child.head == "front" else "B.SilkS"
        overrides[side] = value in {"yes", "true"}
    return overrides


def _stroke_width(text, node):
    stroke = node.child("stroke")
    width = stroke.child("width") if stroke else node.child("width")
    if width is None or len(width.values) != 2:
        _fail(text, node, "mask graphic requires stroke width")
    value = _number(text, width, width.values[1], "stroke width")
    if value < 0:
        _fail(text, width, "stroke width must not be negative")
    return value


def _mask_graphic(text, node, error, budget):
    supported = {"gr_line", "gr_arc", "gr_rect", "gr_circle"}
    if node.head not in supported:
        _fail(text, node, f"unsupported solder-mask construct '{node.head}'")
    line, curved = _curve_node_line(text, node, error, budget)
    fill = node.child("fill")
    filled = bool(fill and any(value in {"yes", "solid"} for value in fill.values[1:] if isinstance(value, str)))
    if filled:
        if node.head == "gr_rect":
            geometry = Polygon(line.coords)
        elif node.head == "gr_circle":
            geometry = Polygon(line.coords)
        else:
            _fail(text, node, f"filled {node.head} is unsupported on solder mask")
        width = _stroke_width(text, node)
        if width:
            geometry = geometry.union(_round_buffer(line, width / 2, error, budget, node))
    else:
        width = _stroke_width(text, node)
        if width == 0:
            _fail(text, node, "unfilled mask graphic requires positive stroke width")
        geometry = _round_buffer(line, width / 2, error, budget, node)
    return _round_buffer(geometry, error, error, budget, node) if curved else geometry


def _read_board(text, curve_error_mm=0.001):
    """Extract board area and protected F/B silkscreen obstacles."""
    if not isinstance(curve_error_mm, (int, float)) or not math.isfinite(curve_error_mm) or curve_error_mm <= 0:
        raise ValueError("curve_error_mm must be a positive finite number")
    root = parse(text)
    budget = _VertexBudget(text)
    if root.head != "kicad_pcb":
        _fail(text, root, "expected kicad_pcb root")
    version_node = root.child("version")
    if version_node is None or len(version_node.values) != 2:
        _fail(text, root, "missing KiCad board version")
    version = version_node.values[1]
    if version != SUPPORTED_VERSION:
        _fail(text, version_node, f"unsupported KiCad board version '{version}'")

    area, edge_items = _edge_area(text, root, curve_error_mm, budget)
    setup = root.child("setup")
    if setup is None:
        _fail(text, root, "missing required board setup")
    board_margin = 0.0
    default_tenting = {"F.SilkS": True, "B.SilkS": True}
    if setup:
        mask_margin = setup.child("pad_to_mask_clearance")
        if mask_margin is None:
            _fail(text, setup, "missing required pad_to_mask_clearance")
        if len(mask_margin.values) != 2 or not isinstance(mask_margin.values[1], str):
            _fail(text, mask_margin, "pad_to_mask_clearance requires one number")
        board_margin = _number(text, mask_margin, mask_margin.values[1], "pad_to_mask_clearance")
        minimum = setup.child("solder_mask_min_width")
        if minimum:
            if len(minimum.values) != 2 or not isinstance(minimum.values[1], str):
                _fail(text, minimum, "solder_mask_min_width requires one number")
            if _number(text, minimum, minimum.values[1], "solder_mask_min_width") != 0:
                _fail(text, minimum, "nonzero solder_mask_min_width is unsupported")
        bridges = setup.child("allow_soldermask_bridges_in_footprints")
        if bridges and any(value in {"yes", "true", "1"} for value in bridges.values[1:] if isinstance(value, str)):
            _fail(text, bridges, "allow_soldermask_bridges_in_footprints is unsupported")
        default_tenting.update(_tenting(text, setup))

    protected = {side: [] for side in SILK_TO_MASK}
    inventory = {
        "edge_items": edge_items,
        "footprints": 0,
        "pads": 0,
        "mask_openings": 0,
        "drills": 0,
        "vias": 0,
        "mask_graphics": 0,
        "curve_error_mm": curve_error_mm,
    }

    for footprint in root.children("footprint"):
        inventory["footprints"] += 1
        footprint_origin, footprint_angle = _at(text, footprint, "footprint", allow_angle=True)
        footprint_margin = _margin(text, footprint)

        for item in footprint.values:
            if not isinstance(item, Node):
                continue
            item_layer = _layer(text, item)
            item_layers = _layers(item)
            affected = set(item_layers + ([item_layer] if item_layer else []))
            if affected & {"F.Mask", "B.Mask"} and item.head != "pad":
                _fail(text, item, f"unsupported footprint solder-mask construct '{item.head}'")
            if item.head == "zone" and affected & {"F.Mask", "B.Mask"}:
                _fail(text, item, "solder-mask zones are unsupported")

        for pad in footprint.children("pad"):
            inventory["pads"] += 1
            atoms = [value for value in pad.values[1:] if isinstance(value, str)]
            if len(atoms) < 3:
                _fail(text, pad, "pad requires number, type, and shape")
            pad_type, shape = atoms[1], atoms[2]
            if pad_type not in {"thru_hole", "np_thru_hole", "smd", "connect"}:
                _fail(text, pad, f"unsupported pad type '{pad_type}'")
            layers = _layers(pad)
            mask_sides = [
                side for side, mask in SILK_TO_MASK.items() if mask in layers or "*.Mask" in layers
            ]
            drill_node = pad.child("drill")
            if pad_type in {"thru_hole", "np_thru_hole"} and drill_node is None:
                _fail(text, pad, f"{pad_type} pad requires an explicit drill")
            protected_geometry = bool(mask_sides or drill_node)
            if protected_geometry and shape in {"custom", "trapezoid"}:
                _fail(text, pad, f"unsupported protected pad shape '{shape}'")
            for unsupported in ("chamfer", "chamfer_ratio", "rect_delta", "padstack", "backdrill", "tertiary_drill", "front_post_machining", "back_post_machining"):
                child = pad.child(unsupported)
                if protected_geometry and child is not None:
                    _fail(text, child, f"unsupported protected pad construct '{unsupported}'")

            local, angle = _at(text, pad, "pad", allow_angle=True)
            nominal = _placed(local, footprint_origin, footprint_angle)
            drill_geometry, shape_offset = _drill(text, pad, nominal, angle, curve_error_mm, budget)
            if pad_type in {"smd", "connect"}:
                drill_geometry = None
            if drill_geometry is not None:
                inventory["drills"] += 1
                drill_geometry = _round_buffer(drill_geometry, curve_error_mm, curve_error_mm, budget, pad)
                protected["F.SilkS"].append(drill_geometry)
                protected["B.SilkS"].append(drill_geometry)

            if mask_sides:
                width, height = _child_numbers(text, pad, "size", 2)
                ratio_node = pad.child("roundrect_rratio")
                ratio = None
                if ratio_node:
                    if len(ratio_node.values) != 2 or not isinstance(ratio_node.values[1], str):
                        _fail(text, ratio_node, "roundrect_rratio requires one number")
                    ratio = _number(text, ratio_node, ratio_node.values[1], "roundrect_rratio")
                geometry = _pad_shape(text, pad, shape, width, height, ratio, curve_error_mm, budget)
                has_copper = any(layer.endswith(".Cu") or layer == "*.Cu" for layer in layers)
                margin = _margin(text, pad)
                if not has_copper:
                    margin = 0.0
                elif margin is None:
                    margin = footprint_margin if footprint_margin is not None else board_margin
                geometry = _round_buffer(geometry, margin, curve_error_mm, budget, pad) if margin else geometry
                # Standard curved pad shapes are polygonal approximations; grow
                # by their error bound so obstacles never understate openings.
                if shape in {"circle", "oval", "roundrect"} or margin:
                    geometry = _round_buffer(geometry, curve_error_mm, curve_error_mm, budget, pad)
                offset = _rotate_vector(shape_offset, angle)
                geometry = affinity.rotate(geometry, -angle, origin=(0, 0))
                geometry = affinity.translate(geometry, nominal[0] + offset[0], nominal[1] + offset[1])
                if not geometry.is_empty:
                    for side in mask_sides:
                        protected[side].append(geometry)
                        inventory["mask_openings"] += 1

    for via in root.children("via"):
        inventory["vias"] += 1
        via_atoms = [value for value in via.values[1:] if isinstance(value, str)]
        via_types = set(via_atoms) & {"blind", "buried", "micro"}
        if via_types:
            _fail(text, via, f"unsupported non-through via type '{sorted(via_types)[0]}'")
        for unsupported in ("remove_unused_layers", "keep_end_layers", "start_end_only", "padstack", "covering", "plugging", "filling", "capping", "backdrill", "tertiary_drill"):
            child = via.child(unsupported)
            if child is not None:
                _fail(text, child, f"unsupported mask-affecting via construct '{unsupported}'")
        position = _child_numbers(text, via, "at", 2)
        drill = _child_numbers(text, via, "drill", 1)[0]
        size = _child_numbers(text, via, "size", 1)[0]
        if drill <= 0 or size <= 0:
            _fail(text, via, "via size and drill must be positive")
        layer_pair = _layers(via)
        if len(layer_pair) != 2:
            _fail(text, via, "via requires two endpoint layers")
        if set(layer_pair) != {"F.Cu", "B.Cu"}:
            _fail(text, via, "only through vias from F.Cu to B.Cu are supported")
        sides_reached = ["F.SilkS", "B.SilkS"]
        hole = _oval(drill, drill, curve_error_mm, budget, via)
        hole = _round_buffer(hole, curve_error_mm, curve_error_mm, budget, via)
        hole = affinity.translate(hole, *position)
        inventory["drills"] += 1
        for side in sides_reached:
            protected[side].append(hole)

        tenting = dict(default_tenting)
        tenting.update(_tenting(text, via))
        opening_radius = size / 2 + board_margin
        if opening_radius < 0:
            _fail(text, via, "via solder-mask opening has negative radius")
        if opening_radius:
            opening = _oval(opening_radius * 2, opening_radius * 2, curve_error_mm, budget, via)
            opening = _round_buffer(opening, curve_error_mm, curve_error_mm, budget, via)
            opening = affinity.translate(opening, *position)
            for side in sides_reached:
                if not tenting[side]:
                    protected[side].append(opening)
                    inventory["mask_openings"] += 1

    for item in root.values:
        if not isinstance(item, Node):
            continue
        layer = _layer(text, item)
        if layer not in {"F.Mask", "B.Mask"}:
            continue
        if item.head == "zone":
            _fail(text, item, "solder-mask zones are unsupported")
        side = "F.SilkS" if layer == "F.Mask" else "B.SilkS"
        protected[side].append(_mask_graphic(text, item, curve_error_mm, budget))
        inventory["mask_graphics"] += 1

    obstacles = {
        side: unary_union(parts) if parts else GeometryCollection()
        for side, parts in protected.items()
    }
    for side, geometry in obstacles.items():
        if not geometry.is_valid:
            _fail(text, root, f"invalid combined obstacle geometry on {side}")
    return BoardGeometry(area=area, obstacles=obstacles, inventory=inventory, version=version)


def read_board(text, curve_error_mm=0.001):
    """Extract supported geometry, translating geometry-engine input errors."""
    try:
        return _read_board(text, curve_error_mm)
    except GeometryError:
        raise
    except (GEOSException, OverflowError) as error:
        raise GeometryError(f"geometry engine rejected the board: {error}") from error
