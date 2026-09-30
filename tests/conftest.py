from pathlib import Path
import sys

# Tests import exactly the package shipped in the standalone skill.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "pcb-artwork"))
