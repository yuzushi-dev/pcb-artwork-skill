"""Native KiCad group ownership and byte-preserving removal spans."""

from dataclasses import dataclass
import re
import uuid


LAYERS = ("F.SilkS", "B.SilkS")
GROUP_PREFIX = "pcb-artwork-skill:"
OWNED_UUID_PREFIX = "50434241"
LEGACY_MARKER = re.compile(
    r"^[ \t]*;[ \t]*PCB-ARTWORK-SKILL(?:[ \t]+(F\.SilkS|B\.SilkS))?"
    r"[ \t]+(BEGIN|END)[ \t]*$"
)


@dataclass(frozen=True)
class ManagedObjects:
    layer: str
    group_span: tuple | None
    object_spans: tuple
    group_text: str
    legacy: bool = False

    @property
    def spans(self):
        return self.object_spans if self.legacy else self.object_spans + (self.group_span,)


def _parse(text):
    if __package__:
        from .sexpr import parse
    else:
        from sexpr import parse
    return parse(text)


def _atoms(node):
    values = [value for value in node.values if isinstance(value, str)]
    return values[1:] if values and values[0] == node.head else values


def is_owned_uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.hex.startswith(OWNED_UUID_PREFIX) and parsed.version == 5


def _line_span(text, start, end):
    line_start = text.rfind("\n", 0, start) + 1
    newline = text.find("\n", end)
    line_end = len(text) if newline < 0 else newline + 1
    if text[line_start:start].strip() or text[end:line_end].strip():
        raise ValueError("managed KiCad object must occupy complete source lines")
    return line_start, line_end


def _direct_nodes(root):
    return [value for value in root.values if hasattr(value, "start")]


def _native_objects(text, root):
    nodes = _direct_nodes(root)
    groups = {}
    for node in nodes:
        if node.head != "group":
            continue
        names = _atoms(node)
        if not names or not names[0].startswith(GROUP_PREFIX):
            continue
        layer = names[0][len(GROUP_PREFIX):]
        if layer not in LAYERS or len(names) != 1:
            raise ValueError("generated group name has an invalid side")
        if layer in groups:
            raise ValueError(f"duplicate generated group for {layer}")
        groups[layer] = node

    by_uuid = {}
    for node in nodes:
        identifier = node.child("uuid")
        atoms = _atoms(identifier) if identifier is not None else []
        if len(atoms) == 1:
            by_uuid.setdefault(atoms[0], []).append(node)

    managed = {}
    claimed = set()
    for layer, group in groups.items():
        members_node = group.child("members")
        members = _atoms(members_node) if members_node is not None else []
        if not members or len(members) != len(set(members)):
            raise ValueError(f"generated group for {layer} has invalid members")
        polygons = []
        for member in members:
            if not is_owned_uuid(member):
                raise ValueError("generated group contains an untagged member UUID")
            matches = by_uuid.get(member, [])
            if len(matches) != 1 or matches[0].head != "gr_poly":
                raise ValueError(f"generated group member is not one owned polygon: {member}")
            polygon = matches[0]
            layer_node = polygon.child("layer")
            if layer_node is None or _atoms(layer_node) != [layer]:
                raise ValueError("generated group owns a polygon on the wrong side")
            try:
                if uuid.UUID(member).version != 5:
                    raise ValueError
            except ValueError as error:
                raise ValueError("generated group member has an invalid UUID") from error
            polygons.append(polygon)
            claimed.add(member)
        object_spans = tuple(_line_span(text, node.start, node.end) for node in polygons)
        group_span = _line_span(text, group.start, group.end)
        managed[layer] = ManagedObjects(
            layer, group_span, object_spans, text[group.start:group.end]
        )
    tagged = {
        identifier
        for identifier, matches in by_uuid.items()
        if is_owned_uuid(identifier) and any(node.head == "gr_poly" for node in matches)
    }
    orphaned = tagged - claimed
    if orphaned:
        raise ValueError(
            "orphaned PCB artwork UUID exists outside its named generated group"
        )
    return managed


def _legacy_objects(text, root):
    nodes = _direct_nodes(root)
    markers = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        match = LEGACY_MARKER.fullmatch(content)
        if match:
            nested = any(node.start <= offset < node.end for node in nodes)
            if not nested:
                if not (root.start < offset < root.end):
                    raise ValueError("legacy marker is outside the board root")
                markers.append((offset, offset + len(line), match.group(1), match.group(2)))
        offset += len(line)
    if not markers:
        return {}
    if len(markers) != 2 or markers[0][3] != "BEGIN" or markers[1][3] != "END":
        raise ValueError("legacy artwork markers are ambiguous")
    begin, end = markers
    if begin[2] != end[2]:
        raise ValueError("legacy artwork marker sides do not match")
    inside = [node for node in nodes if begin[1] <= node.start and node.end <= end[0]]
    if not inside or any(node.head != "gr_poly" for node in inside):
        raise ValueError("legacy artwork block contains an unowned object")
    sides = set()
    for polygon in inside:
        layer_node = polygon.child("layer")
        atoms = _atoms(layer_node) if layer_node is not None else []
        if len(atoms) != 1 or atoms[0] not in LAYERS:
            raise ValueError("legacy artwork polygon has no identifiable side")
        sides.add(atoms[0])
    if begin[2]:
        sides.add(begin[2])
    if len(sides) != 1:
        raise ValueError("legacy artwork block does not identify one side")
    layer = sides.pop()
    block_span = (begin[0], end[1])
    return {layer: ManagedObjects(layer, None, (block_span,), "", True)}


def managed_objects(text):
    root = _parse(text)
    native = _native_objects(text, root)
    legacy = _legacy_objects(text, root)
    if native and legacy:
        raise ValueError("native and legacy artwork ownership cannot be mixed")
    return native or legacy


def _remove_spans(text, spans):
    result = []
    position = 0
    for start, end in sorted(spans):
        if start < position:
            raise ValueError("managed ownership spans overlap")
        result.append(text[position:start])
        position = end
    result.append(text[position:])
    return "".join(result)


def without_managed_objects(text):
    spans = [span for owned in managed_objects(text).values() for span in owned.spans]
    return _remove_spans(text, spans)


def managed_text(text, layer):
    try:
        owned = managed_objects(text)[layer]
    except KeyError as error:
        raise ValueError(f"no managed objects for {layer}") from error
    return "".join(text[start:end] for start, end in sorted(owned.spans))


def require_unmanaged_bytes_unchanged(before, after):
    if without_managed_objects(before) != without_managed_objects(after):
        raise ValueError("patch changed content outside managed artwork objects")


# Compatibility names for callers from the comment-marker implementation.
without_managed_blocks = without_managed_objects
managed_blocks = managed_objects
managed_block = managed_text
