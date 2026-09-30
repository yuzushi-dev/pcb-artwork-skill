import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "pcb-artwork"
BOARDS = ROOT / "tests" / "fixtures" / "boards"


def run_script(base, name, *args):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(base / "scripts" / name), *map(str, args)],
        capture_output=True, text=True, cwd=base, env=environment,
    )


def plan(item):
    return {"version": 1, "layer": "F.SilkS", "items": [item]}


RECT = {"id": "field", "type": "rect", "region": [0, 0, 10, 10]}
HATCH = {"id": "hatch", "type": "hatching", "region": [0, 0, 10, 10],
         "bar_width_mm": 0.2, "spacing_mm": 0.5, "angle_deg": 45}


@pytest.mark.parametrize("item", [
    {"id": "a", "type": "polygon", "points": [[0, 0], [1, 1]]},
    {"id": "a", "type": "polygon", "points": [[0, 0, 1], [1, 0], [0, 1]]},
    {"id": "a", "type": "polygon", "points": [[0, 0], [1, 1], [2, 2]]},
    {"id": "a", "type": "polygon", "points": [[0, 0], [2, 2], [0, 2], [2, 0]]},
    {"id": "a", "type": "polyline", "points": [[0, 0], [1, 1]]},
    {"id": "a", "type": "polyline", "points": [[0, 0], [1, 1]], "width_mm": 0},
    {"id": "a", "type": "polyline", "points": [[0, 0], [0, 0]], "width_mm": 1},
    {**RECT, "region": [0, 0, 1]},
    {**RECT, "region": [0, 0, 0, 1]},
    {**RECT, "points": [[0, 0], [1, 1]]},
    {**HATCH, "spacing_mm": 0},
    {**HATCH, "spacing_mm": -1},
    {**HATCH, "bar_width_mm": 0},
    {**HATCH, "spacing_mm": 1e-12},
])
def test_invalid_primitive_fails_before_generation(tmp_path, item):
    source = tmp_path / "artwork.json"
    source.write_text(json.dumps(plan(item)))
    result = run_script(SKILL, "validate_artwork.py", source)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_nonfinite_json_is_rejected(tmp_path, literal):
    source = tmp_path / "artwork.json"
    source.write_text(json.dumps(plan(RECT)).replace("10", literal, 1))
    result = run_script(SKILL, "validate_artwork.py", source)
    assert result.returncode == 1
    assert "finite" in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_duplicate_ids_and_malformed_json(tmp_path):
    source = tmp_path / "artwork.json"
    data = plan(RECT)
    data["items"].append(RECT)
    source.write_text(json.dumps(data))
    result = run_script(SKILL, "validate_artwork.py", source)
    assert result.returncode == 1
    assert "duplicate" in result.stdout + result.stderr
    source.write_text('{"version":')
    result = run_script(SKILL, "validate_artwork.py", source)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_public_readme_plan_still_valid(tmp_path):
    example = re.search(r"```json\n(.*?)\n```", (ROOT / "README.md").read_text(), re.S)
    source = tmp_path / "artwork.json"
    source.write_text(example.group(1))
    assert run_script(SKILL, "validate_artwork.py", source).returncode == 0


@pytest.mark.parametrize("board,item", [
    ("custom-pad.kicad_pcb", RECT),
    ("open-outline.kicad_pcb", RECT),
])
@pytest.mark.parametrize("base", [ROOT, SKILL])
def test_unsupported_compilation_never_writes_output(tmp_path, board, item, base):
    source = tmp_path / "artwork.json"
    output = tmp_path / "compiled.json"
    source.write_text(json.dumps(plan(item)))
    result = run_script(base, "clip_artwork.py", "--board", BOARDS / board,
                        "--artwork", source, "--output", output)
    assert result.returncode == 1
    assert "blocked" in result.stderr
    assert not output.exists()
    output.write_text("previous artifact")
    result = run_script(base, "clip_artwork.py", "--board", BOARDS / board,
                        "--artwork", source, "--output", output)
    assert result.returncode == 1
    assert output.read_text() == "previous artifact"


@pytest.mark.parametrize("base", [ROOT, SKILL])
@pytest.mark.parametrize("name", ["compile_artwork.py", "clip_artwork.py", "patch_kicad.py"])
def test_single_command_compiles_real_geometry(tmp_path, base, name):
    from lib.sexpr import parse
    from shapely.ops import unary_union

    artwork = tmp_path / "artwork.json"
    artwork.write_text(json.dumps(plan(RECT)))
    output = tmp_path / "out.kicad_pcb"
    report = tmp_path / "report.json"
    source = BOARDS / "mask-pad.kicad_pcb"
    original = source.read_bytes()
    result = run_script(base, name, "--board", source, "--artwork", artwork,
                        "--output", output, "--report", report)
    assert result.returncode == 0, result.stderr
    root = parse(output.read_text())
    polygons = [Polygon([[float(v.values[1]), float(v.values[2])]
                         for v in obj.child("pts").children("xy")])
                for obj in root.children("gr_poly")]
    union = unary_union(polygons)
    assert not union.covers(Polygon([(4.8, 4.8), (5.2, 4.8), (5.2, 5.2), (4.8, 5.2)]))
    assert union.area > 80
    assert source.read_bytes() == original
    assert json.loads(report.read_text())["geometry"] == "passed"


@pytest.mark.parametrize("base", [ROOT, SKILL])
def test_patcher_rejects_unverified_legacy_artifact(tmp_path, base):
    artifact = tmp_path / "compiled.json"
    artifact.write_text(json.dumps(plan({"id": "unsafe", "type": "polygon",
                                        "points": [[0, 0], [10, 0], [0, 10]]}) | {"meta": {"keepout_parser": "not-yet-implemented"}}))
    output = tmp_path / "out.kicad_pcb"
    result = run_script(base, "patch_kicad.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", artifact, "--output", output)
    assert result.returncode == 1
    assert "invalid" in result.stdout + result.stderr or "blocked" in result.stderr
    assert not output.exists()


def test_inspection_explicitly_reports_partial_support():
    result = run_script(SKILL, "inspect_board.py", BOARDS / "mask-pad.kicad_pcb")
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["support"]["status"] == "supported_subset"
    assert report["support"]["board_geometry"] == "extracted"
    assert report["support"]["kicad_validation"] == "not_run"


def test_skill_works_without_checkout(tmp_path):
    standalone = tmp_path / "standalone"
    shutil.copytree(SKILL, standalone)
    source = tmp_path / "artwork.json"
    source.write_text(json.dumps(plan(HATCH)))
    assert run_script(standalone, "validate_artwork.py", source).returncode == 0
    output = tmp_path / "compiled.kicad_pcb"
    result = run_script(standalone, "clip_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", source, "--output", output)
    assert result.returncode == 0, result.stderr
    reference = tmp_path / "reference.kicad_pcb"
    result = run_script(ROOT, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", source, "--output", reference)
    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == reference.read_bytes()


@pytest.fixture
def validation():
    spec = importlib.util.spec_from_file_location("validation", SKILL / "lib" / "validation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_input_resource_limits(tmp_path, validation):
    source = tmp_path / "huge.json"
    source.write_bytes(b" " * (validation.MAX_INPUT_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        validation.load_artwork(source)
    source.write_text("[" * 2000 + "0" + "]" * 2000)
    with pytest.raises(ValueError, match="nesting"):
        validation.load_artwork(source)
    data = plan(RECT)
    data["items"] = [{**RECT, "id": str(index)} for index in range(validation.MAX_ITEMS + 1)]
    with pytest.raises(ValueError):
        validation.validate(data)


def test_total_vertex_budget_checked_before_geometry(validation):
    points = [[0, 0]] * (validation.MAX_VERTICES // 2 + 1)
    data = plan({"id": "a", "type": "polygon", "points": points})
    data["items"].append({"id": "b", "type": "polygon", "points": points})
    with pytest.raises(ValueError, match="vertex budget"):
        validation.validate(data)


def test_hatch_budget_is_global(validation):
    data = plan({**HATCH, "spacing_mm": 0.002})
    data["items"].append({**data["items"][0], "id": "second"})
    with pytest.raises(ValueError, match="hatch bar budget"):
        validation.validate(data)


def test_valid_primitives_and_reversed_region(validation):
    for item in [RECT, HATCH, {**RECT, "region": [10, 10, 0, 0]},
                 {"id": "p", "type": "polygon", "points": [[0, 0], [1, 0], [0, 1]]},
                 {"id": "l", "type": "polyline", "points": [[0, 0], [1, 1]], "width_mm": 0.1}]:
        assert validation.validate(plan(item))["items"] == [item]


def test_patch_gate_preserves_source_and_existing_output(tmp_path):
    source = tmp_path / "board.kicad_pcb"
    original = (BOARDS / "mask-pad.kicad_pcb").read_bytes()
    source.write_bytes(original)
    artifact = tmp_path / "compiled.json"
    artifact.write_text(json.dumps(plan(RECT)))
    aliases = [source, tmp_path / "symlink.kicad_pcb", tmp_path / "hardlink.kicad_pcb"]
    aliases[1].symlink_to(source)
    aliases[2].hardlink_to(source)
    for output in aliases:
        result = run_script(SKILL, "patch_kicad.py", "--board", source,
                            "--artwork", artifact, "--output", output)
        assert result.returncode == 1
        assert source.read_bytes() == original
    output = tmp_path / "existing.kicad_pcb"
    output.write_text("existing output")
    artifact.write_text('{"version":')
    result = run_script(SKILL, "patch_kicad.py", "--board", source,
                        "--artwork", artifact, "--output", output)
    assert result.returncode == 1
    assert output.read_text() == "existing output"


def test_report_cannot_overwrite_any_input_or_board_output(tmp_path):
    artwork = tmp_path / "artwork.json"
    artwork.write_text(json.dumps(plan(RECT)))
    output = tmp_path / "out.kicad_pcb"
    for report in [BOARDS / "mask-pad.kicad_pcb", artwork, output]:
        result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                            "--artwork", artwork, "--output", output, "--report", report)
        assert result.returncode == 1
        assert not output.exists()


def test_all_removed_has_distinct_status_and_no_board_copy(tmp_path):
    artwork = tmp_path / "outside.json"
    artwork.write_text(json.dumps(plan({**RECT, "region": [20, 20, 30, 30]})))
    output = tmp_path / "out.kicad_pcb"
    report = tmp_path / "report.json"
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", artwork, "--output", output, "--report", report)
    assert result.returncode == 2, result.stderr
    assert json.loads(report.read_text())["status"] == "all_removed"
    assert not output.exists()


@pytest.mark.parametrize("flag,value", [("--curve-error-mm", "1e-300"),
                                       ("--curve-error-mm", "nan"),
                                       ("--edge-margin-mm", "inf")])
def test_numeric_profile_errors_are_bounded(tmp_path, flag, value):
    output = tmp_path / "output.kicad_pcb"
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", ROOT / "tests/fixtures/artwork/example.json",
                        "--output", output, flag, value)
    assert result.returncode == 1
    assert "blocked" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_extreme_clearance_is_rejected_cleanly(tmp_path):
    source = tmp_path / "artwork.json"
    source.write_text(json.dumps({**plan(RECT), "clearance_mm": 1e308}))
    output = tmp_path / "output.kicad_pcb"
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "geometry-pads.kicad_pcb",
                        "--artwork", source, "--output", output)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_bundle_entry_points_and_schema_copy():
    result = run_script(ROOT, "verify_bundle.py")
    assert result.returncode == 0, result.stderr


def test_semantic_diagnostics_are_bounded(tmp_path):
    source = tmp_path / "artwork.json"
    data = plan(RECT)
    data["items"] = [
        {**RECT, "id": str(index) + "x" * 10_000}
        for index in range(20) for _ in range(2)
    ]
    source.write_text(json.dumps(data))
    result = run_script(SKILL, "validate_artwork.py", source)
    assert result.returncode == 1
    assert "duplicate" in result.stderr
    assert len(result.stderr) < 1000


def test_all_removed_preserves_existing_output_and_reports_it(tmp_path):
    artwork = tmp_path / "outside.json"
    artwork.write_text(json.dumps(plan({**RECT, "region": [20, 20, 30, 30]})))
    output = tmp_path / "out.kicad_pcb"
    output.write_text("previous result")
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", artwork, "--output", output)
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["output_written"] is False
    assert report["existing_output_preserved"] is True
    assert output.read_text() == "previous result"


def test_invalid_report_parent_does_not_write_board(tmp_path):
    output = tmp_path / "out.kicad_pcb"
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", ROOT / "tests/fixtures/artwork/example.json",
                        "--output", output, "--report", tmp_path / "missing" / "report.json")
    assert result.returncode == 1
    assert not output.exists()


def test_external_custom_rules_are_rejected(tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_bytes((BOARDS / "mask-pad.kicad_pcb").read_bytes())
    board.with_suffix(".kicad_dru").write_text("(version 1)")
    output = tmp_path / "out.kicad_pcb"
    result = run_script(SKILL, "compile_artwork.py", "--board", board,
                        "--artwork", ROOT / "tests/fixtures/artwork/example.json", "--output", output)
    assert result.returncode == 1
    assert ".kicad_dru" in result.stderr
    assert not output.exists()


def test_default_manufacturing_profile_and_geometry_only_optout(tmp_path):
    for mode, expected in [("conservative", 0.25), ("geometry-only", 0.16)]:
        result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                            "--artwork", ROOT / "tests/fixtures/artwork/example.json",
                            "--output", tmp_path / (mode + ".kicad_pcb"),
                            "--manufacturing-profile", mode)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["clearance_mm"] == expected


def test_review_svg_marks_thin_details_and_cannot_alias_inputs(tmp_path):
    artwork = tmp_path / "thin.json"
    artwork.write_text(json.dumps(plan({"id": "thin", "type": "rect", "region": [1, 1, 3, 1.1]})))
    output, preview = tmp_path / "out.kicad_pcb", tmp_path / "review.svg"
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", artwork, "--output", output, "--review-svg", preview)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["minimum_width"] == "review_required"
    assert "#d93838" in preview.read_text()
    original = artwork.read_bytes()
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", artwork, "--output", output, "--review-svg", artwork)
    assert result.returncode == 1
    assert artwork.read_bytes() == original


def test_invalid_preview_parent_does_not_promote_board(tmp_path):
    output = tmp_path / "out.kicad_pcb"
    result = run_script(SKILL, "compile_artwork.py", "--board", BOARDS / "mask-pad.kicad_pcb",
                        "--artwork", ROOT / "tests/fixtures/artwork/example.json",
                        "--output", output, "--review-svg", tmp_path / "missing" / "review.svg")
    assert result.returncode == 1
    assert not output.exists()
