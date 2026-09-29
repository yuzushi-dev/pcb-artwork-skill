---
name: pcb-artwork
description: Convert visual PCB references into production-aware KiCad silkscreen artwork through a deterministic geometry pipeline. Use when a user provides a KiCad PCB plus a reference image, render, SVG, or artwork brief and wants F.SilkS or B.SilkS redesigned without changing the electrical design.
---

# PCB Artwork

Treat the KiCad PCB as the source of truth for board shape, holes, pads, solder-mask openings, components, and routing. Treat the reference as the source for composition.

Preserve the electrical and mechanical design unless the user asks for a board change. Do not move footprints, tracks, vias, zones, pads, nets, drills, or board outline to make the artwork fit.

Use the model for visual interpretation and decomposition. Use the bundled scripts for coordinates, repetition, clipping, serialization, and validation.

## Process

1. Find the authoritative `.kicad_pcb` and keep an untouched baseline.
2. Run `python scripts/inspect_board.py <board.kicad_pcb> > board-geometry.json`.
3. Break the reference into polygons, polylines, rectangles, hatching, reticles, barcodes, and text. Prefer geometry when lettering forms part of the visual identity.
4. Map reference coordinates to PCB millimetres. Use an affine transform when the source has perspective or skew.
5. Write `artwork.json` against `schemas/artwork.schema.json`.
6. Run `python scripts/validate_artwork.py artwork.json`.
7. Protect solder-mask openings, drills, board exterior, and explicit keepouts. Use `safe_artwork = desired_artwork - buffer(protected_geometry, clearance)`.
8. Compile the artwork with `scripts/clip_artwork.py`.
9. Patch a copy of the PCB with `scripts/patch_kicad.py`.
10. Export and inspect the real Gerbers, then run KiCad DRC.

Do not improvise hundreds of KiCad `gr_poly` objects when the same design can be expressed through the artwork intermediate representation.

Keep every generated element reproducible from `artwork.json`.

Preserve revision truth. A reference marked `r5` does not make a target `r10` board an `r5`.

## Boundaries

The current general keepout parser is incomplete. Do not claim complete production clearance checking until mask, drill, and board-edge extraction has run.

Do not call generated fabrication files production-ready unless KiCad DRC and the exported Gerbers have been reviewed.

When reporting the result, name the changed silkscreen layer, state which electrical/manufacturing layers stayed unchanged, and identify any reference details altered because of board constraints.

Read `references/workflow.md` for the reasoning model and `references/geometry-rules.md` for geometry rules.
