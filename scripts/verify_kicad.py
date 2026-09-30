#!/usr/bin/env python3
"""Compile artwork and collect reproducible KiCad DRC/Gerber evidence."""

from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid


GERBER_SUFFIXES = {
    "F.SilkS": "-f_silkscreen.gto",
    "B.SilkS": "-b_silkscreen.gbo",
    "F.Mask": "-F_Mask.gts",
    "B.Mask": "-B_Mask.gbs",
    "Edge.Cuts": "-Edge_Cuts.gm1",
}


def _without_source_name(value, source_name):
    return str(value).replace(source_name, "<board>") if source_name else str(value)


def _normalized_item(item, source_name):
    position = item.get("pos") or item.get("position") or {}
    return {
        "description": _without_source_name(item.get("description", ""), source_name),
        "position_mm": [float(position.get("x", 0)), float(position.get("y", 0))],
    }


def normalize_drc(report):
    source_name = Path(str(report.get("source", ""))).name
    normalized = []
    for violation in report.get("violations", []):
        normalized.append({
            "description": _without_source_name(
                violation.get("description", ""), source_name
            ),
            "items": sorted(
                (_normalized_item(item, source_name) for item in violation.get("items", [])),
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
            "severity": violation.get("severity", ""),
            "type": violation.get("type", ""),
        })
    return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))


def compare_drc(source, modified):
    source_violations = normalize_drc(source)
    modified_violations = normalize_drc(modified)
    source_counts = Counter(json.dumps(item, sort_keys=True) for item in source_violations)
    modified_counts = Counter(json.dumps(item, sort_keys=True) for item in modified_violations)
    added = modified_counts - source_counts
    new_violations = []
    for serialized, count in sorted(added.items()):
        violation = json.loads(serialized)
        violation["count"] = count
        new_violations.append(violation)
    return {
        "passed": not new_violations,
        "source_violations": source_violations,
        "modified_violations": modified_violations,
        "new_violations": new_violations,
    }


def output_record(path, root):
    path = Path(path)
    return {
        "file": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def find_gerbers(directory):
    files = list(Path(directory).iterdir())
    found = {}
    for layer, suffix in GERBER_SUFFIXES.items():
        matches = [path for path in files if path.name.endswith(suffix)]
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one {layer} Gerber ending in {suffix}, found {len(matches)}"
            )
        found[layer] = matches[0]
    return found


def find_drills(directory):
    return sorted(Path(directory).glob("*.drl"))


def _run(command):
    subprocess.run(command, check=True)


def _formatted_args(template, *, board=None, report=None, directory=None):
    values = {"board": str(board), "report": str(report), "directory": str(directory)}
    return [part.format(**values) for part in template]


def _validate_remote(host, remote_root):
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", host):
        raise ValueError("remote host contains unsupported characters")
    root = Path(remote_root)
    if not root.is_absolute() or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(root)):
        raise ValueError("remote root must be a simple absolute path")
    return root


def _ssh(host, arguments):
    _run(["ssh", host, shlex.join(map(str, arguments))])


def _run_remote_exports(args, target, output, source, modified):
    remote_root = _validate_remote(args.host, args.remote_root)
    workspace_name = f"pcb-artwork-evidence-{uuid.uuid4().hex}"
    remote_workspace = remote_root / workspace_name
    container_workspace = Path("/work") / workspace_name
    _ssh(args.host, ["mkdir", "--", remote_workspace])
    for name in ("source-gerbers", "modified-gerbers"):
        _ssh(args.host, ["mkdir", "--", remote_workspace / name])
    _run(["scp", str(source), f"{args.host}:{remote_workspace}/source.kicad_pcb"])
    _run(["scp", str(modified), f"{args.host}:{remote_workspace}/modified.kicad_pcb"])

    for stem in ("source", "modified"):
        board = container_workspace / f"{stem}.kicad_pcb"
        report = container_workspace / f"{stem}.drc.json"
        gerbers = container_workspace / f"{stem}-gerbers"
        _ssh(args.host, [args.cli, *_formatted_args(
            target["drc_args"], board=board, report=report
        )])
        _ssh(args.host, [args.cli, *_formatted_args(
            target["gerber_args"], board=board, directory=gerbers
        )])
        _ssh(args.host, [args.cli, *_formatted_args(
            target["drill_args"], board=board, directory=gerbers
        )])
        _run(["scp", f"{args.host}:{remote_workspace}/{stem}.drc.json", str(output)])
        _run(["scp", "-r", f"{args.host}:{remote_workspace}/{stem}-gerbers", str(output)])

    version = subprocess.run(
        ["ssh", args.host, shlex.join([args.cli, "--version"])],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return version


def _run_local_exports(args, target, output, source, modified):
    workspace = output / "kicad-work"
    workspace.mkdir()
    shutil.copyfile(source, workspace / "source.kicad_pcb")
    shutil.copyfile(modified, workspace / "modified.kicad_pcb")
    for stem in ("source", "modified"):
        gerbers = output / f"{stem}-gerbers"
        gerbers.mkdir()
        board = workspace / f"{stem}.kicad_pcb"
        report = output / f"{stem}.drc.json"
        _run([args.cli, *_formatted_args(target["drc_args"], board=board, report=report)])
        _run([args.cli, *_formatted_args(
            target["gerber_args"], board=board, directory=gerbers
        )])
        _run([args.cli, *_formatted_args(
            target["drill_args"], board=board, directory=gerbers
        )])
    return subprocess.run(
        [args.cli, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_previews(output, gerber_sets):
    from gerbonara import GerberFile

    preview_directory = output / "previews"
    preview_directory.mkdir()
    records = {}
    for stem, layers in gerber_sets.items():
        records[stem] = {}
        for layer, gerber in layers.items():
            preview = preview_directory / f"{stem}-{layer.replace('.', '_')}.svg"
            preview.write_text(str(GerberFile.open(gerber).to_svg()), encoding="utf-8")
            records[stem][layer] = output_record(preview, output)
    return records


def _output_records(output, gerber_sets, preview_records):
    records = {
        "modified_board": output_record(output / "modified.kicad_pcb", output),
        "compile_report": output_record(output / "compile-report.json", output),
        "drc": {},
        "gerbers": {},
        "drills": {},
        "previews": preview_records,
    }
    for stem, layers in gerber_sets.items():
        records["drc"][stem] = output_record(output / f"{stem}.drc.json", output)
        records["gerbers"][stem] = {
            layer: output_record(path, output) for layer, path in layers.items()
        }
        records["drills"][stem] = [
            output_record(path, output) for path in find_drills(output / f"{stem}-gerbers")
        ]
    return records


def _parse_args(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--artwork", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cli", required=True, help="KiCad CLI executable")
    parser.add_argument("--host", help="SSH host for a remotely installed KiCad")
    parser.add_argument("--remote-root", help="host path mounted as /work by the CLI wrapper")
    parser.add_argument("--target", type=Path, default=root / "tests" / "kicad-target.json")
    parser.add_argument(
        "--compiler", type=Path,
        default=root / "skills" / "pcb-artwork" / "scripts" / "compile_artwork.py",
    )
    args = parser.parse_args(argv)
    if bool(args.host) != bool(args.remote_root):
        parser.error("--host and --remote-root must be used together")
    return args


def main(argv=None):
    args = _parse_args(argv)
    source_before = args.board.read_bytes()
    args.output.mkdir(parents=True, exist_ok=False)
    source_copy = args.output / "source.kicad_pcb"
    source_copy.write_bytes(source_before)
    artwork_copy = args.output / "artwork.json"
    artwork_copy.write_bytes(args.artwork.read_bytes())
    modified = args.output / "modified.kicad_pcb"
    compile_report = args.output / "compile-report.json"
    _run([
        sys.executable, str(args.compiler), "--board", str(args.board),
        "--artwork", str(args.artwork), "--output", str(modified),
        "--report", str(compile_report),
        "--review-svg", str(args.output / "manufacturing-review.svg"),
    ])
    if args.board.read_bytes() != source_before:
        raise RuntimeError("compiler changed the source board")

    target = json.loads(args.target.read_text(encoding="utf-8"))
    if args.host:
        version = _run_remote_exports(args, target, args.output, source_copy, modified)
    else:
        version = _run_local_exports(args, target, args.output, source_copy, modified)
    if version != target["kicad_cli_version"]:
        raise RuntimeError(
            f"KiCad CLI version mismatch: expected {target['kicad_cli_version']}, got {version}"
        )

    source_drc = json.loads((args.output / "source.drc.json").read_text(encoding="utf-8"))
    modified_drc = json.loads((args.output / "modified.drc.json").read_text(encoding="utf-8"))
    comparison = compare_drc(source_drc, modified_drc)
    gerber_sets = {
        stem: find_gerbers(args.output / f"{stem}-gerbers")
        for stem in ("source", "modified")
    }
    previews = _write_previews(args.output, gerber_sets)
    compiler_result = json.loads(compile_report.read_text(encoding="utf-8"))
    outputs = _output_records(args.output, gerber_sets, previews)
    outputs["manufacturing_review"] = output_record(args.output / "manufacturing-review.svg", args.output)
    evidence = {
        "version": 1,
        "kicad_cli_version": version,
        "inputs": {"board": args.board.name, "artwork": args.artwork.name},
        "export_settings": {
            "layers": list(GERBER_SUFFIXES),
            "precision": 6,
            "mask_subtraction": target["gerber_mask_subtraction"],
            "drc_units": "mm",
            "drc_severities": "all",
        },
        "checks": {
            "fixture_loading": "passed",
            "drc": "passed" if comparison["passed"] else "failed",
            "gerber_export": "passed",
            "drill_export": "passed",
            "visual_review": "not_run",
            "minimum_silk_width": compiler_result["minimum_width"],
        },
        "drc_comparison": comparison,
        "ignored_checks": {
            "source": source_drc.get("ignored_checks", []),
            "modified": modified_drc.get("ignored_checks", []),
        },
        "outputs": outputs,
    }
    evidence_path = args.output / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(evidence_path)
    return 0 if comparison["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"KiCad verification failed: {str(error)[:2000]}", file=sys.stderr)
        raise SystemExit(1)
