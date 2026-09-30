"""Patch compiled artwork into a byte-preserving copy of a KiCad board."""

import math
import numbers
import os
from pathlib import Path
import tempfile
import uuid

from shapely.geometry import Polygon

if __package__:
    from .board_invariants import (
        LAYERS,
        OWNED_UUID_PREFIX,
        managed_objects,
        require_unmanaged_bytes_unchanged,
    )
    from .sexpr import parse
else:
    from board_invariants import (
        LAYERS,
        OWNED_UUID_PREFIX,
        managed_objects,
        require_unmanaged_bytes_unchanged,
    )
    from sexpr import parse


_NAMESPACE = uuid.UUID("0919ed18-58cb-5580-9141-7e12d954e21e")


def _atoms(node):
    values = [value for value in node.values if isinstance(value, str)]
    return values[1:] if values and values[0] == node.head else values


def _canonical_points(raw_points):
    if not isinstance(raw_points, (list, tuple)) or len(raw_points) < 3:
        raise ValueError("compiled polygon must have at least three points")
    points = []
    for raw in raw_points:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValueError("compiled polygon point must contain exactly x and y")
        point = []
        for coordinate in raw:
            if isinstance(coordinate, bool) or not isinstance(coordinate, numbers.Real):
                raise ValueError("compiled polygon coordinates must be numbers")
            value = float(coordinate)
            if not math.isfinite(value):
                raise ValueError("compiled polygon coordinates must be finite")
            if round(value, 6) != value:
                raise ValueError("compiled polygon coordinates must already be rounded to six decimals")
            point.append(0.0 if value == 0 else value)
        points.append(tuple(point))
    area_twice = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )
    if not math.isfinite(area_twice) or abs(area_twice) < 1e-12:
        raise ValueError("compiled polygon is degenerate")
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError("compiled polygon is invalid")
    return tuple(points)


def _validated_polygons(compilation):
    layer = getattr(compilation, "layer", None)
    if layer not in LAYERS:
        raise ValueError("compiled artwork layer must be F.SilkS or B.SilkS")
    raw_polygons = getattr(compilation, "polygons", None)
    if not isinstance(raw_polygons, list):
        raise ValueError("compiled artwork polygons must be a list")
    if not raw_polygons:
        raise ValueError("compiled artwork has no polygons to patch")
    polygons = []
    identifiers = set()
    for raw in raw_polygons:
        if not isinstance(raw, dict):
            raise ValueError("compiled polygon must be an object")
        identifier = raw.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("compiled polygon id must be a non-empty string")
        if identifier in identifiers:
            raise ValueError(f"duplicate compiled polygon id: {identifier}")
        identifiers.add(identifier)
        polygons.append((identifier, _canonical_points(raw.get("points"))))
    return layer, polygons


def _uuid(layer, identifier, points=None):
    generated = uuid.uuid5(_NAMESPACE, f"polygon\0{layer}\0{identifier}").hex
    return str(uuid.UUID(hex=OWNED_UUID_PREFIX + generated[len(OWNED_UUID_PREFIX):]))


def _group_uuid(layer):
    return str(uuid.uuid5(_NAMESPACE, f"group\0{layer}"))


def _block(layer, polygons, newline):
    lines = []
    member_ids = []
    for identifier, points in polygons:
        item_uuid = _uuid(layer, identifier, points)
        member_ids.append(item_uuid)
        xy = " ".join(f"(xy {x:.6f} {y:.6f})" for x, y in points)
        lines.extend([
            "  (gr_poly",
            f"    (pts {xy})",
            "    (stroke (width 0) (type default))",
            "    (fill yes)",
            f'    (layer "{layer}")',
            f'    (uuid "{item_uuid}")',
            "  )",
        ])
    members = " ".join(f'"{item_uuid}"' for item_uuid in member_ids)
    lines.extend([
        f'  (group "pcb-artwork-skill:{layer}"',
        f'    (id "{_group_uuid(layer)}")',
        f"    (members {members})",
        "  )",
    ])
    return newline.join(lines)


def _root(text):
    root = parse(text)
    if root.head != "kicad_pcb":
        raise ValueError("input is not a KiCad PCB")
    return root


def _closing_parenthesis(text, root):
    position = root.end - 1
    if position < 0 or text[position] != ")" or text[root.end:].strip():
        raise ValueError("KiCad PCB has content outside its root expression")
    return position


def _expected(layer, polygons):
    return [
        (identifier, points, _uuid(layer, identifier, points))
        for identifier, points in polygons
    ]


def _one_atom(node, head):
    child = node.child(head)
    atoms = _atoms(child) if child is not None else []
    if len(atoms) != 1:
        raise ValueError(f"managed block has invalid {head}")
    return atoms[0]


def _verify_serialized(text, layer, polygons):
    root = _root(text)
    owned = managed_objects(text).get(layer)
    if owned is None or owned.legacy:
        raise ValueError(f"serialized board has no native managed {layer} group")
    expected = _expected(layer, polygons)
    by_uuid = {}
    for node in root.children("gr_poly"):
        pts = node.child("pts")
        layer_node = node.child("layer")
        uuid_node = node.child("uuid")
        if pts is None or layer_node is None or uuid_node is None:
            continue
        coordinates = []
        for xy in pts.children("xy"):
            atoms = _atoms(xy)
            if len(atoms) != 2:
                raise ValueError("serialized managed polygon has an invalid point")
            try:
                point = tuple(float(value) for value in atoms)
            except ValueError as error:
                raise ValueError("serialized managed polygon has a non-numeric point") from error
            if not all(math.isfinite(value) for value in point):
                raise ValueError("serialized managed polygon has a non-finite point")
            coordinates.append(point)
        layers = _atoms(layer_node)
        uuids = _atoms(uuid_node)
        if layers != [layer] or len(uuids) != 1:
            continue
        by_uuid[uuids[0]] = tuple(coordinates)
    for _, expected_points, item_uuid in expected:
        if by_uuid.get(item_uuid) != expected_points:
            raise ValueError("serialized polygons do not match compiled polygons")
    group = parse(owned.group_text)
    if _one_atom(group, "id") != _group_uuid(layer):
        raise ValueError("serialized managed group identifier changed")


def patch_text(text, compilation):
    """Return a board with one side's generated block inserted or replaced."""
    if not isinstance(text, str):
        raise ValueError("board text must be a string")
    root = _root(text)
    layer, polygons = _validated_polygons(compilation)
    objects = managed_objects(text)
    for existing_layer, owned in objects.items():
        if not owned.legacy:
            group = parse(owned.group_text)
            if _one_atom(group, "id") != _group_uuid(existing_layer):
                raise ValueError("generated group has an unknown identifier")

    expected_ids = [_uuid(layer, identifier, points) for identifier, points in polygons]
    if layer not in objects and any(item_uuid in text for item_uuid in expected_ids):
        raise ValueError("generated UUID exists without its PCB artwork group")

    newline = "\r\n" if "\r\n" in text else "\n"
    replacement = _block(layer, polygons, newline) + newline
    current = objects.get(layer)
    if current is not None:
        spans = sorted(current.spans)
        insertion = spans[0][0]
        pieces = []
        position = 0
        for start, end in spans:
            pieces.append(text[position:start])
            position = end
        pieces.append(text[position:])
        base = "".join(pieces)
        patched = base[:insertion] + replacement + base[insertion:]
    else:
        insertion = _closing_parenthesis(text, root)
        patched = text[:insertion] + replacement + text[insertion:]

    require_unmanaged_bytes_unchanged(text, patched)
    _verify_serialized(patched, layer, polygons)
    return patched


def _same_file(source, output):
    try:
        return os.path.samefile(source, output)
    except FileNotFoundError:
        return source.resolve() == output.resolve()


def write_board_copy(source_path, original_bytes, patched_text, output_path):
    """Atomically write a validated board copy without ever replacing source."""
    source = Path(source_path)
    output = Path(output_path)
    if _same_file(source, output):
        raise ValueError("output must not resolve to the source board")
    if not isinstance(original_bytes, bytes):
        raise ValueError("original board snapshot must be bytes")
    if source.read_bytes() != original_bytes:
        raise ValueError("source board changed after it was read")
    _root(patched_text)
    managed_objects(patched_text)

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(patched_text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        _root(temporary.read_text(encoding="utf-8"))
        managed_objects(temporary.read_text(encoding="utf-8"))
        if source.read_bytes() != original_bytes:
            raise ValueError("source board changed before output promotion")
        if _same_file(source, output):
            raise ValueError("output became an alias of the source board")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
