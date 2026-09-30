---
name: pcb-artwork
description: Use when a user provides a KiCad PCB and a reference image, SVG, or artwork brief and wants front or back silkscreen redesigned without changing the electrical design.
---

# PCB Artwork

The reference determines composition; the PCB determines where ink can exist.
Keep footprints, pads, tracks, vias, zones, nets, drills, existing silk and the
board outline unchanged. Work on a copy.

## Workflow

1. Identify the authoritative `.kicad_pcb`, target silk side and original revision.
2. Inspect supported geometry: `python scripts/inspect_board.py board.kicad_pcb`.
3. Describe the reference using input v1 polygons, polylines, rectangles and
   hatching; build lettering/reticles from these primitives when needed.
4. Validate: `python scripts/validate_artwork.py artwork.json`.
5. Compile and write the copy in one invocation:

```bash
python scripts/compile_artwork.py --board board.kicad_pcb --artwork artwork.json \
  --output board-artwork.kicad_pcb --report artwork-report.json --review-svg review.svg
```

6. Review clipping/removals and manufacturing warnings. Export real Gerbers, compare DRC
   with the source and inspect the exported silk before fabrication.

`clip_artwork.py` and `patch_kicad.py` alias the same operation: both accept the
original v1 input and output a PCB. Do not pass legacy compiled JSON containing
`meta`. No separate compiled artifact or input-hash handshake is needed.

## Input and geometry

Install Python 3.11+ with `shapely>=2.1,<3` and `jsonschema>=4.22,<5` in a venv.
Coordinates and widths use millimetres. Points are finite 2D values; widths and
hatch pitch are positive. `spacing_mm` is centre-to-centre pitch. `angle_deg`
defaults to 0 and rotates bars in the artwork XY plane. Each primitive accepts
only its own fields; IDs are unique. Reject degenerate/self-intersecting polygons.

Supported board file version: `20241229`, verified with KiCad CLI 10.0.5.
Require board `setup/pad_to_mask_clearance`; companion `.kicad_dru` custom rules
are unsupported. See `references/supported-geometry.md` for the supported subset.

The compiler clips each side against effective solder-mask openings and physical
holes, inside the board with its cutouts. Unsupported protected constructs must
fail; do not approximate them manually or bypass errors to obtain an output.
The numerical curve error defaults to 0.001 mm; coordinates serialize to six
millimetre decimals. Verify distance after serialization. Edge margin defaults
to effective clearance and can be set with `--edge-margin-mm`.

Budgets: 16 MiB per input, 10,000 primitives, 100,000 input vertices, 10,000
estimated hatch bars, 50,000 output polygons and 200,000 output vertices.
A completely removed composition returns exit 2 with `output_written:false`; an
existing output remains unchanged and is reported as such.
Malformed/unsupported input returns exit 1; useful compilation returns exit 0.

## Ownership and verification

Update generated objects independently by side using native named groups and
reserved UUID prefix `50434241`. Missing groups, orphan tagged polygons, prefix
collisions and inconsistent membership block the operation. Preserve all unmanaged
source bytes. Do not manually remove ownership metadata or rewrite generated UUIDs.

The compile report separates geometry from external KiCad loading, DRC, Gerber
and visual checks. Those external checks remain `not_run` until actually run.
The CLI defaults to a conservative engineering profile: target line width
0.20 mm, mask/drill clearance at least 0.25 mm, text-height guidance 1.0 mm.
Stricter artwork clearance is preserved. `--manufacturing-profile geometry-only`
explicitly disables this profile and its width audit. Library callers opt in.

The width audit checks the UNION of serialized polygons. It flags potential
small-feature loss, leaves ink unchanged and reports `review_required` or
`heuristic_passed`; neither certifies printable minimum width. `--review-svg`
shows suspect regions in red in model space, not an actual Gerber export.
Text height, minimum negative gap and process registration remain unchecked.
See `references/manufacturing-profile.md` for sources and remaining limits.
Supplier confirmation and an actual calibration sample are still needed.
A configured clearance of 0.16 mm is an example, not a fabrication guarantee.
Do not call an output production-ready without supplier requirements and all
required external checks. Preserve revision labels from the actual target board.
