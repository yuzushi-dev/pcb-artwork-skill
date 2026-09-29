# PCB Artwork Skill

**Turn a visual PCB reference into production-aware KiCad silkscreen artwork without handing the layout over to the model.**

This repository contains a portable agent skill and a small deterministic geometry pipeline for PCB artwork work. The model handles interpretation: it identifies visual structure, decides which primitives describe it, and produces a normalized artwork plan. The scripts handle the parts that need exactness: coordinate mapping, clipping, KiCad serialization, Gerber checks, and reproducible validation.

The first use case was a 57 × 32 mm biomonitor board whose front silkscreen had to match a concept image while leaving copper, pads, drills, solder-mask openings, routing, and board geometry unchanged.

## What it does

- Reads a KiCad PCB as the mechanical and manufacturing source of truth.
- Treats the visual reference as an artwork source, not as PCB geometry.
- Converts design elements into a small intermediate representation instead of raw KiCad syntax.
- Clips artwork against protected board regions before writing \`F.SilkS\` or \`B.SilkS\`.
- Writes generated artwork as KiCad geometry.
- Produces machine-readable validation results.
- Keeps artwork generation separate from the electrical design.

The skill is meant for agentic workflows in Claude Code, Codex, or any client that can read a \`SKILL.md\` file and run local scripts.

## Workflow

\`\`\`
reference image / SVG
        │
        ▼
visual decomposition
        │
        ▼
artwork.json
        │
        ├── text / stencil
        ├── polygons
        ├── polylines
        ├── hatching
        ├── reticles
        └── barcodes
        │
        ▼
board geometry + keepouts
        │
        ▼
clipping / clearance checks
        │
        ▼
KiCad silkscreen geometry
        │
        ▼
Gerber + validation report
\`\`\`

The agent should not improvise hundreds of \`gr_poly\` objects in the PCB file. It should describe the artwork in the intermediate format and let the scripts compile it.

## Repository structure

\`\`\`
.
├── SKILL.md
├── README.md
├── LICENSE
├── pyproject.toml
├── schemas/
│   └── artwork.schema.json
├── scripts/
│   ├── inspect_board.py
│   ├── clip_artwork.py
│   ├── patch_kicad.py
│   └── validate_artwork.py
├── references/
│   ├── workflow.md
│   └── geometry-rules.md
└── tests/
    └── test_geometry.py
\`\`\`

## Quick start

Create a Python environment with Python 3.11 or newer, then install the package requirements:

\`\`\`bash
python -m pip install -e .
\`\`\`

Inspect a board:

\`\`\`bash
python scripts/inspect_board.py board.kicad_pcb > board-geometry.json
\`\`\`

Validate an artwork plan:

\`\`\`bash
python scripts/validate_artwork.py artwork.json
\`\`\`

Clip it against board keepouts:

\`\`\`bash
python scripts/clip_artwork.py \
  --board board.kicad_pcb \
  --artwork artwork.json \
  --output artwork-clipped.json
\`\`\`

Write the artwork into a copy of the board:

\`\`\`bash
python scripts/patch_kicad.py \
  --board board.kicad_pcb \
  --artwork artwork-clipped.json \
  --output board-artwork.kicad_pcb
\`\`\`

The scripts refuse to edit copper, nets, vias, zones, footprints, drills, or board outline. The patcher replaces only generated silkscreen objects carrying the skill marker.

## Design rule

The reference controls composition. The board controls where ink can exist.

For a desired artwork region \`S\` and protected board geometry \`K\`, the usable artwork is:

\`\`\`
S_safe = S - buffer(K, clearance)
\`\`\`

That rule is the core of the workflow. It lets the agent work from a visual master without treating a render as manufacturing truth.

## Status

This is an early private build. The current scripts cover the intermediate representation, KiCad text patching, and conservative geometry checks. Gerber export still relies on KiCad CLI when available and should remain part of the final review path.

Do not send generated fabrication files to a manufacturer without opening the result in KiCad, running DRC, and reviewing the actual Gerbers.

## License

MIT
