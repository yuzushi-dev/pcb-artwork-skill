"""Input v1 validation. Validation does not verify board clearance."""
from collections import Counter
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator
from shapely.geometry import LineString, Polygon
from shapely.validation import explain_validity

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_ITEMS = 10_000
MAX_VERTICES = 100_000
MAX_HATCH_BARS = 10_000
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "artwork.schema.json").read_text())


def finite_numbers(value):
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("all numbers must be finite and representable")
    if isinstance(value, dict):
        for child in value.values():
            finite_numbers(child)
    elif isinstance(value, list):
        for child in value:
            finite_numbers(child)


def load_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        data = json.loads(raw)
        finite_numbers(data)
    except (RecursionError, OverflowError) as error:
        raise ValueError("input nesting or number exceeds supported limits") from error
    return data


def validate(data):
    finite_numbers(data)
    if isinstance(data, dict) and isinstance(data.get("items"), list) and len(data["items"]) > MAX_ITEMS:
        raise ValueError(f"primitive budget exceeded: maximum {MAX_ITEMS}")
    error = next(Draft202012Validator(SCHEMA).iter_errors(data), None)
    if error:
        location = ".".join(map(str, error.path)) or "<root>"
        message = error.message
        if len(message) > 500:
            message = message[:500] + "..."
        raise ValueError(f"{location}: {message}")
    items = data["items"]
    duplicates = sorted(key for key, count in Counter(item["id"] for item in items).items() if count > 1)
    if duplicates:
        preview = ", ".join(key[:80] for key in duplicates[:5])
        raise ValueError(f"duplicate ids ({len(duplicates)}): {preview}")
    vertices = sum(len(item.get("points", [])) for item in items)
    if vertices > MAX_VERTICES:
        raise ValueError(f"vertex budget exceeded: maximum {MAX_VERTICES}")
    hatch_bars = 0
    for item in items:
        kind = item["type"]
        label = item["id"][:80]
        if kind in ("polygon", "polyline"):
            points = item["points"]
            try:
                geometry = Polygon(points) if kind == "polygon" else LineString(points)
            except (ValueError, OverflowError) as error:
                raise ValueError(f"{label}: unsupported coordinate magnitude") from error
            measure = geometry.area if kind == "polygon" else geometry.length
            if not geometry.is_valid or geometry.is_empty or not math.isfinite(measure) or measure <= 0:
                raise ValueError(f"{label}: degenerate or invalid {kind}: {explain_validity(geometry)}")
        else:
            x1, y1, x2, y2 = item["region"]
            width, height = abs(x2 - x1), abs(y2 - y1)
            if width == 0 or height == 0 or not math.isfinite(width * height):
                raise ValueError(f"{label}: degenerate or non-finite region")
            if kind == "hatching":
                # Bound the rotated region's projection before any generation loop.
                estimate = math.hypot(width, height) / item["spacing_mm"] + 2
                if not math.isfinite(estimate) or estimate > MAX_HATCH_BARS:
                    raise ValueError(f"{label}: hatch bar budget exceeded: maximum {MAX_HATCH_BARS}")
                hatch_bars += math.ceil(estimate)
                if hatch_bars > MAX_HATCH_BARS:
                    raise ValueError(f"hatch bar budget exceeded: maximum {MAX_HATCH_BARS}")
    return data


def load_artwork(path):
    return validate(load_json(path))
