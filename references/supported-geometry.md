# Supported board geometry

Board file token `20241229` only; verified with KiCad CLI 10.0.5.
Require explicit `setup/pad_to_mask_clearance`. The compiler rejects companion
`.kicad_dru` custom rules. Project-wide custom mask rules are outside this subset.

Supported:

- Closed Edge.Cuts rings formed by lines/arcs, rectangles or circles, including cutouts.
- Front/back circle, rectangle, oval and roundrect pads, transformed from footprints.
- Mask expansion precedence: pad, footprint, then board; per-side mask layers.
- Circular drills and slotted pad drills; drill offset follows actual KiCad body placement.
- Through vias with explicit/default tenting semantics; physical drills remain protected.
- Mask line/arc/rectangle/circle graphics, including filled geometry and its stroke.

Unsupported protected constructs fail instead of being silently omitted:

- Custom, trapezoid/chamfered pads, padstacks and backdrills.
- Blind/micro/internal vias and unsupported via mask semantics.
- Nonzero mask minimum width and enabled mask bridges.
- Mask zones, mask text/text boxes, Beziers and unsupported graphics.
- Open, touching or ambiguous board contours; unsupported file versions.

The parser rejects duplicate singular fields, excess coordinate arguments,
nonfinite numbers and resource-budget violations. Existing ordinary silk and
unmanaged source bytes are preserved. The numerical curve error defaults to
0.001 mm; it is not a supplier manufacturing tolerance. Minimum printable silk
width and supplier-specific rules still need a separate check.
