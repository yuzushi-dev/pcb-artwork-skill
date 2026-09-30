#!/usr/bin/env python3
"""Check distributed assets and execute the four root forwarding entry points."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "pcb-artwork"


def main():
    for asset in (Path("schemas/artwork.schema.json"), Path("SKILL.md")):
        if (ROOT / asset).read_bytes() != (SKILL / asset).read_bytes():
            print(f"bundle mismatch: {asset}", file=sys.stderr)
            return 1
    for name in ("inspect_board.py", "validate_artwork.py", "compile_artwork.py", "clip_artwork.py", "patch_kicad.py"):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / name), "--help"],
                                capture_output=True, text=True)
        if result.returncode:
            print(f"bundle entry point failed: {name}\n{result.stderr}", file=sys.stderr)
            return 1
    print("bundle checks passed; standalone execution is covered by tests/test_pipeline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
