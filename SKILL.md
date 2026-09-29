---
name: pcb-artwork
description: Convert visual PCB references into production-aware KiCad silkscreen artwork through a deterministic geometry pipeline. Use when a user provides a KiCad PCB plus a reference image, render, SVG, or artwork brief and wants F.SilkS or B.SilkS redesigned without changing the electrical design.
---

# PCB Artwork

Use this skill when the job is about PCB artwork, front or back silkscreen composition, reference-image matching, decorative board graphics, labels, reticles, hatching, barcodes, warning marks, or similar visual work on a KiCad board.

Do not treat the reference image as manufacturing geometry. Treat the KiCad PCB as the source of truth for board shape, holes, pads, solder-mask openings, components, and routing.

## Contract

Preserve the electrical and mechanical design unless the user asks for a board change.

Do not move footprints, tracks, vias, zones, pads, nets, drills, or board outline for the sake of the artwork.

Do not write large amounts of KiCad geometry by hand when the same result can be expressed through the artwork intermediate representation and compiled by the scripts in this repository.

Do not claim that a board is production-ready unless KiCad DRC and the exported Gerbers have been reviewed.

## Process

### 1. Establish the baseline

Find the authoritative \`.kicad_pcb\` file and identify the target silkscreen layer.

Record:

- board dimensions and outline;
- footprint count and positions;
- drills and slots;
- front and back solder-mask openings;
- existing silkscreen;
- revision labels and board identifiers.

Run:

\`\`\`bash
python scripts/inspect_board.py <board.kicad_pcb> > board-geometry.json
\`\`\`

Keep an untouched baseline copy.

### 2. Read the reference as a composition

Break the visual reference into families of primitives.

Use these categories before inventing a new one:

- \`polygon\` for filled marks and stencil glyphs;
- \`polyline\` for traces such as ECG lines;
- \`rect\` for bars and blocks;
- \`hatching\` for repeated diagonal marks;
- \`circle\` and \`arc\` for reticles;
- \`text\` only when a normal KiCad font is acceptable.

Prefer geometry over a font dependency when the lettering is part of the visual identity.

Do not ask the model to reproduce the whole reference in one pass. Map the board, then handle each visual family.

### 3. Map image coordinates to board coordinates

Choose two or more reliable landmarks from the image and board. Compute a scale and origin mapping.

For axis-aligned references:

\`\`\`
x_pcb = x0 + x_image * sx
y_pcb = y0 + y_image * sy
\`\`\`

Use an affine transform when the source has perspective or skew.

Store resulting geometry in the artwork intermediate representation. Use millimetres.

### 4. Write the artwork plan

Create an \`artwork.json\` file that validates against \`schemas/artwork.schema.json\`.

Example:

\`\`\`json
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
\`\`\`

Run:

\`\`\`bash
python scripts/validate_artwork.py artwork.json
\`\`\`

### 5. Protect the board

Build protected geometry from the real board.

At minimum protect:

- solder-mask openings;
- drills and slots;
- the board exterior;
- any explicit user keepout.

Use the requested clearance. When none exists, use a conservative value and state it.

Clip desired artwork against the protected geometry:

\`\`\`
safe_artwork = desired_artwork - buffer(protected_geometry, clearance)
\`\`\`

Run:

\`\`\`bash
python scripts/clip_artwork.py \
  --board <board.kicad_pcb> \
  --artwork artwork.json \
  --output artwork-clipped.json
\`\`\`

Review removed areas instead of silently restoring them.

### 6. Patch a copy of the board

Write only generated silkscreen objects.

Run:

\`\`\`bash
python scripts/patch_kicad.py \
  --board <board.kicad_pcb> \
  --artwork artwork-clipped.json \
  --output <new-board.kicad_pcb>
\`\`\`

The patcher must not alter unrelated board data.

### 7. Validate

Run the repository checks:

\`\`\`bash
python scripts/validate_artwork.py artwork-clipped.json
python -m pytest
\`\`\`

When KiCad CLI is installed, export Gerbers from the resulting board and inspect the produced silkscreen layer. Compare the generated Gerber geometry with the intended artwork instead of relying on a screenshot of the PCB editor.

Then open the project in KiCad and run DRC.

### 8. Report changes with boundaries

State which layer changed.

State which manufacturing and electrical layers remained unchanged.

Call out any differences from the reference that came from board constraints.

If KiCad DRC, ERC, schematic comparison, or Gerber review did not run, say so.

## Working style

Use the model for visual interpretation and decomposition. Use code for coordinates, repetition, clipping, serialization, and validation.

Keep every generated element reproducible from \`artwork.json\`.

Preserve revision truth. If the reference says \`r5\` but the edited board is \`r10\`, do not copy the stale revision unless the user asks for it.

Prefer a small number of documented rules over hand-tuned coordinates spread through the PCB file.
