#!/usr/bin/env python3
"""Forward to the canonical installable skill."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "skills" / "pcb-artwork" / "scripts" / Path(__file__).name), run_name="__main__")
