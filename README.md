<p align="center">
  <img src="assets/pcb-artwork-skill-mark.png" alt="PCB Artwork Skill logo" width="128">
</p>

# PCB Artwork Skill

**Turn a visual PCB reference into production-aware KiCad silkscreen artwork without asking the model to hand-draw the board.**

PCB Artwork Skill separates visual interpretation from PCB geometry. The agent reads the reference, breaks the design into primitives, and writes a compact artwork plan. Deterministic scripts handle coordinates, clipping, KiCad serialization, and validation.

```bash
npx skills add yuzushi-dev/pcb-artwork-skill
```


## How it works

```text
reference image / SVG
        │
        ▼
visual decomposition
        │
        ▼
artwork.json
        │
        ├── stencil geometry
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
clipping + clearance checks
        │
        ▼
KiCad F.SilkS / B.SilkS
        │
        ▼
Gerber + validation
```

The reference controls the composition. The board controls where ink can exist.

For desired artwork `S` and protected board geometry `K`:

```text
S_safe = S - buffer(K, clearance)
```

The agent should describe the artwork in the intermediate representation instead of improvising hundreds of `gr_poly` entries inside the PCB file.

## What it handles

- KiCad PCB inspection before artwork changes
- visual-reference decomposition into reusable primitives
- millimetre-based artwork plans
- `F.SilkS` and `B.SilkS` output
- geometry-based lettering when a font would make the result machine-dependent
- repeated patterns such as hatching and barcode bars
- explicit clearance rules
- reproducible generated artwork
- validation before Gerber review

The electrical design stays outside the artwork pipeline. The skill does not move footprints, tracks, vias, zones, pads, nets, drills, or the board outline unless the user asks for a board change.

## Install

Install the skill straight from GitHub:

```bash
npx skills add yuzushi-dev/pcb-artwork-skill
```

The repository exposes the installable skill at `skills/pcb-artwork/`, including its scripts, schema, and references. The installer can therefore copy the complete skill instead of leaving runtime files behind at repository root.

The skill needs Python 3.11 or newer. Its geometry helpers use Shapely and JSON Schema:

```bash
python -m pip install "shapely>=2,<3" "jsonschema>=4.22,<5"
```

## Use

Inspect the board first:

```bash
python scripts/inspect_board.py board.kicad_pcb > board-geometry.json
```

Write and validate an `artwork.json` plan:

```bash
python scripts/validate_artwork.py artwork.json
```

Compile the artwork against the board:

```bash
python scripts/clip_artwork.py \
  --board board.kicad_pcb \
  --artwork artwork.json \
  --output artwork-clipped.json
```

Write the compiled polygons into a copy of the PCB:

```bash
python scripts/patch_kicad.py \
  --board board.kicad_pcb \
  --artwork artwork-clipped.json \
  --output board-artwork.kicad_pcb
```

Then open the result in KiCad, run DRC, export the Gerbers, and inspect the manufactured layers rather than relying on the PCB editor preview.

## Intermediate representation

A design instruction stays small enough to inspect:

```json
{
  "version": 1,
  "layer": "F.SilkS",
  "clearance_mm": 0.16,
  "items": [
    {
      "id": "edge-hatch",
      "type": "hatching",
      "region": [2.0, 2.0, 14.0, 4.5],
      "angle_deg": 55,
      "bar_width_mm": 0.42,
      "spacing_mm": 0.68
    },
    {
      "id": "ecg",
      "type": "polyline",
      "width_mm": 0.25,
      "points": [[3, 29], [9, 29], [10, 27.1], [11, 30.0], [12, 29]]
    }
  ]
}
```

This boundary keeps visual reasoning readable and leaves repetition, clipping, and serialization to code.

## Repository structure

```text
.
├── SKILL.md
├── README.md
├── LICENSE
├── pyproject.toml
├── assets/
│   └── pcb-artwork-skill-mark.png
├── skills/
│   └── pcb-artwork/
│       ├── SKILL.md
│       ├── schemas/
│       │   └── artwork.schema.json
│       ├── scripts/
│       │   ├── inspect_board.py
│       │   ├── clip_artwork.py
│       │   ├── patch_kicad.py
│       │   └── validate_artwork.py
│       └── references/
│           ├── workflow.md
│           └── geometry-rules.md
├── schemas/                 Development copy
├── scripts/                 Development copy
├── references/              Development copy
└── tests/
    └── test_geometry.py
```

## License

Released under the [MIT License](LICENSE). You may use, copy, modify, merge, publish, distribute, sublicense, and sell copies of the software under its terms. The copyright and license notice must remain with copies or substantial portions of the software.