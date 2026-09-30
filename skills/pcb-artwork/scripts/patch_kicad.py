#!/usr/bin/env python3
"""Compatibility entry point: recompile original v1 artwork against this board."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("compile_artwork.py")), run_name="__main__")
