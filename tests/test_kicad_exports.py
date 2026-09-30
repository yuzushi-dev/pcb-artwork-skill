import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    path = ROOT / "scripts" / "verify_kicad.py"
    spec = importlib.util.spec_from_file_location("verify_kicad", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drc_comparison_ignores_run_metadata_and_uuid():
    verifier = load_verifier()
    source = {
        "date": "2026-01-01T00:00:00Z",
        "source": "/personal/source.kicad_pcb",
        "violations": [{
            "type": "clearance",
            "severity": "error",
            "description": "Clearance violation",
            "items": [{
                "description": "Pad 1",
                "pos": {"x": 5.0, "y": 6.0},
                "uuid": "first-random-uuid",
            }],
        }],
    }
    modified = {
        "date": "2026-09-30T12:34:56Z",
        "source": "/another/private/modified.kicad_pcb",
        "violations": [{
            "type": "clearance",
            "severity": "error",
            "description": "Clearance violation",
            "items": [{
                "description": "Pad 1",
                "pos": {"x": 5, "y": 6},
                "uuid": "second-random-uuid",
            }],
        }],
    }

    comparison = verifier.compare_drc(source, modified)

    assert comparison["passed"] is True
    assert comparison["new_violations"] == []
    assert comparison["source_violations"] == comparison["modified_violations"]


def test_drc_comparison_reports_only_added_multiset_members():
    verifier = load_verifier()
    violation = {
        "type": "silk_over_copper",
        "severity": "warning",
        "description": "Silkscreen overlap",
        "items": [{"description": "graphic", "pos": {"x": 1, "y": 2}}],
    }

    comparison = verifier.compare_drc(
        {"violations": [violation]},
        {"violations": [violation, violation]},
    )

    assert comparison["passed"] is False
    assert comparison["new_violations"] == [{
        "count": 1,
        "description": "Silkscreen overlap",
        "items": [{"description": "graphic", "position_mm": [1.0, 2.0]}],
        "severity": "warning",
        "type": "silk_over_copper",
    }]


def test_drc_comparison_removes_source_filename_from_descriptions():
    verifier = load_verifier()
    source = {
        "source": "source.kicad_pcb",
        "violations": [{
            "type": "board_issue", "severity": "warning",
            "description": "Issue in source.kicad_pcb", "items": [],
        }],
    }
    modified = {
        "source": "modified.kicad_pcb",
        "violations": [{
            "type": "board_issue", "severity": "warning",
            "description": "Issue in modified.kicad_pcb", "items": [],
        }],
    }

    assert verifier.compare_drc(source, modified)["passed"] is True


def test_evidence_uses_relative_outputs_and_output_hashes(tmp_path):
    verifier = load_verifier()
    output = tmp_path / "evidence"
    (output / "source-gerbers").mkdir(parents=True)
    gerber = output / "source-gerbers" / "board-F_Mask.gts"
    gerber.write_text("gerber bytes")

    record = verifier.output_record(gerber, output)

    assert record == {
        "file": "source-gerbers/board-F_Mask.gts",
        "sha256": "3d7cd118a1914852067e83ea82ac671d4cadc35ddf693c1c6d72faf0a632ac48",
    }


def test_layer_files_are_identified_by_kicad_suffix(tmp_path):
    verifier = load_verifier()
    for name in (
        "board-f_silkscreen.gto",
        "board-b_silkscreen.gbo",
        "board-F_Mask.gts",
        "board-B_Mask.gbs",
        "board-Edge_Cuts.gm1",
        "board-job.gbrjob",
    ):
        (tmp_path / name).write_text(name)

    assert {layer: path.name for layer, path in verifier.find_gerbers(tmp_path).items()} == {
        "F.SilkS": "board-f_silkscreen.gto",
        "B.SilkS": "board-b_silkscreen.gbo",
        "F.Mask": "board-F_Mask.gts",
        "B.Mask": "board-B_Mask.gbs",
        "Edge.Cuts": "board-Edge_Cuts.gm1",
    }


def test_drill_files_are_listed_without_job_metadata(tmp_path):
    verifier = load_verifier()
    (tmp_path / "board-PTH.drl").write_text("drill")
    (tmp_path / "board-NPTH.drl").write_text("drill")
    (tmp_path / "board-job.gbrjob").write_text("metadata")

    assert [path.name for path in verifier.find_drills(tmp_path)] == [
        "board-NPTH.drl", "board-PTH.drl"
    ]


def test_gerber_primitives_flip_y_and_apply_clear_polarity():
    pytest.importorskip("gerbonara", reason="Gerber checks need requirements-kicad.txt")
    from gerbonara.graphic_primitives import Circle, Rectangle
    from gerber_geometry import apply_primitive

    geometry = apply_primitive(Polygon(), Circle(5, -5, 1.1, True))
    geometry = apply_primitive(
        geometry,
        Rectangle(5, -5, 1, 1, rotation=0, polarity_dark=False),
    )

    assert geometry.covers(Point(5, 5.9))
    assert not geometry.covers(Point(5, 5))


def test_gerber_line_uses_round_end_caps():
    pytest.importorskip("gerbonara", reason="Gerber checks need requirements-kicad.txt")
    from gerbonara.graphic_primitives import Line
    from gerber_geometry import apply_primitive

    geometry = apply_primitive(Polygon(), Line(1, -2, 3, -2, 1, True))

    assert geometry.covers(Point(1, 2.49))
    assert geometry.covers(Point(3.49, 2))
    assert not geometry.covers(Point(3.51, 2))


def test_gerber_parser_rejects_unknown_primitives():
    pytest.importorskip("gerbonara", reason="Gerber checks need requirements-kicad.txt")
    from gerber_geometry import apply_primitive

    class Unknown:
        polarity_dark = True

    with pytest.raises(TypeError, match="Unsupported Gerber primitive"):
        apply_primitive(Polygon(), Unknown())


def evidence_directory():
    configured = os.environ.get("PCB_ARTWORK_KICAD_EVIDENCE")
    if not configured:
        pytest.skip(
            "real KiCad export gate not run: set PCB_ARTWORK_KICAD_EVIDENCE"
        )
    path = Path(configured)
    if not (path / "evidence.json").is_file():
        pytest.fail(f"missing KiCad evidence: {path / 'evidence.json'}")
    return path


def test_real_kicad_evidence_has_no_regressions_and_declares_ignored_checks():
    evidence = json.loads((evidence_directory() / "evidence.json").read_text())

    assert evidence["checks"]["fixture_loading"] == "passed"
    assert evidence["checks"]["drc"] == "passed"
    assert evidence["checks"]["gerber_export"] == "passed"
    assert evidence["checks"]["visual_review"] in {"not_run", "passed"}
    width_status = evidence["checks"]["minimum_silk_width"]
    assert width_status in {"not_checked", "review_required", "heuristic_passed"}
    report = json.loads((evidence_directory() / "compile-report.json").read_text())
    assert width_status == report["minimum_width"]
    assert evidence["drc_comparison"]["new_violations"] == []
    assert evidence["ignored_checks"]
    assert "/home/" not in json.dumps(evidence)


def _managed_geometry(board_path, layer):
    skill = ROOT / "skills" / "pcb-artwork"
    sys.path.insert(0, str(skill / "lib"))
    try:
        from sexpr import Node, parse
    finally:
        sys.path.pop(0)

    text = board_path.read_text(encoding="utf-8")
    root = parse(text)
    def atoms(node):
        return [value for value in node.values[1:] if not isinstance(value, Node)]

    groups = [
        node for node in root.children("group")
        if atoms(node) == [f"pcb-artwork-skill:{layer}"]
    ]
    assert len(groups) == 1
    members = set(atoms(groups[0].child("members")))
    polygons = []
    for node in root.children("gr_poly"):
        identifier = node.child("uuid")
        identifiers = atoms(identifier) if identifier is not None else []
        if len(identifiers) != 1 or identifiers[0] not in members:
            continue
        points = []
        for point in node.child("pts").children("xy"):
            points.append(tuple(map(float, atoms(point))))
        polygons.append(Polygon(points))
    assert len(polygons) == len(members)
    from shapely.ops import unary_union
    return unary_union(polygons)


def test_real_exports_preserve_manufacturing_layers_and_match_compiled_geometry():
    evidence = evidence_directory()
    verifier = load_verifier()
    source_sets = verifier.find_gerbers(evidence / "source-gerbers")
    modified_sets = verifier.find_gerbers(evidence / "modified-gerbers")
    from gerber_geometry import read_excellon_geometry, read_gerber_geometry
    from shapely.ops import unary_union

    skill = ROOT / "skills" / "pcb-artwork"
    sys.path.insert(0, str(skill / "lib"))
    try:
        from board_geometry import read_board
    finally:
        sys.path.pop(0)
    board = read_board((evidence / "source.kicad_pcb").read_text(), curve_error_mm=0.001)
    report = json.loads((evidence / "compile-report.json").read_text())
    tolerance = 0.002

    for side in ("F", "B"):
        mask_layer = f"{side}.Mask"
        silk_layer = f"{side}.SilkS"
        source_mask = read_gerber_geometry(source_sets[mask_layer])
        modified_mask = read_gerber_geometry(modified_sets[mask_layer])
        assert source_mask.symmetric_difference(modified_mask).area <= tolerance ** 2
        assert board.obstacles[silk_layer].difference(source_mask.buffer(tolerance)).area <= tolerance ** 2
        assert source_mask.difference(board.obstacles[silk_layer].buffer(tolerance)).area <= tolerance ** 2

    source_edge = read_gerber_geometry(source_sets["Edge.Cuts"])
    modified_edge = read_gerber_geometry(modified_sets["Edge.Cuts"])
    assert source_edge.symmetric_difference(modified_edge).area <= tolerance ** 2
    source_drills = unary_union([
        read_excellon_geometry(path) for path in verifier.find_drills(evidence / "source-gerbers")
    ])
    modified_drills = unary_union([
        read_excellon_geometry(path) for path in verifier.find_drills(evidence / "modified-gerbers")
    ])
    assert source_drills.symmetric_difference(modified_drills).area <= tolerance ** 2

    layer = report["layer"]
    exported_silk = read_gerber_geometry(modified_sets[layer])
    exported_mask = read_gerber_geometry(modified_sets[layer.replace("SilkS", "Mask")])
    serialized = _managed_geometry(evidence / "modified.kicad_pcb", layer)
    assert exported_silk.symmetric_difference(serialized).area <= tolerance
    if not board.obstacles[layer].is_empty:
        assert exported_silk.distance(board.obstacles[layer]) >= report["clearance_mm"] - tolerance
    if not exported_mask.is_empty:
        assert exported_silk.distance(exported_mask) >= report["clearance_mm"] - tolerance
    assert board.area.buffer(-report["edge_margin_mm"] + tolerance).covers(exported_silk)
