# Workflow notes

The board file answers where artwork can exist. The visual reference answers what the board should look like.

Keep those roles separate. Copying a render into KiCad as if it contained reliable pad, drill, mask, and component geometry produces fragile boards.

## Intermediate representation

Use artwork JSON as the boundary between interpretation and execution. The agent can reason about a hatching region, stencil word, or reticle without editing KiCad syntax. Scripts can expand patterns, apply clearances, and serialize the result.

## Reference matching

Match dominant regions, visual hierarchy, spacing, rhythm, line weight, then local detail. Board constraints win when the reference conflicts with real geometry.

## Gerber review

A PCB editor screenshot helps during iteration. The exported Gerber is the manufacturing artifact. Inspect the actual silkscreen Gerber before production.
