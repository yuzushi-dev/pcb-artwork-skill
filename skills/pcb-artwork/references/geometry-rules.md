# Geometry rules

Use millimetres for coordinates and widths.

Treat configured clearance as a minimum. Protect solder-mask openings and drills before writing artwork.

Keep generated artwork inside the board outline unless the fabrication process and user request say otherwise.

Use native KiCad text for ordinary labels. Convert identity lettering, logos, and stencil display type into geometry when font rendering would make the result machine-dependent.

Represent hatching, barcodes, ticks, grids, and other repeated elements by parameters and expand them in code.

Preserve the target board revision instead of copying a stale revision from the visual reference.

The same board, artwork JSON, and script version should produce the same generated objects.
