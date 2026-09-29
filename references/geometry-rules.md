# Geometry rules

## Units

Use millimetres for every coordinate and width in the intermediate representation.

## Clearance

Treat the configured artwork clearance as a minimum. Keep extra room where it does not hurt the composition.

Protect solder-mask openings and drills before writing artwork.

## Board edge

Keep generated artwork inside the board outline unless the fabrication process and user request say otherwise.

## Text

Use native KiCad text for ordinary labels.

Convert identity lettering, logos, and stencil display type into geometry when font rendering would make the result machine-dependent.

## Repeated patterns

Represent hatching, barcodes, ticks, grids, and similar elements by parameters. Expand them in code.

## Revision marks

A visual reference may show an old board revision. Preserve the revision of the target design unless the user requests a historical reproduction.

## Determinism

The same board, artwork JSON, and script version should produce the same generated objects.
