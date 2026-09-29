# Workflow notes

The board file and the visual reference answer different questions.

The board file answers: where can artwork exist without colliding with manufacturing geometry?

The reference answers: what should the board look like?

Keeping those roles separate avoids a common agent failure mode: copying a render into KiCad as if the render contained reliable pad, drill, mask, and component geometry.

## Intermediate representation

The artwork JSON acts as a boundary between interpretation and execution.

An agent can reason about one hatching region, one stencil word, or one reticle without touching KiCad syntax. Scripts can then expand repeated patterns, apply clearances, and serialize the result.

This split also makes review easier. A human can inspect a short artwork plan before it becomes hundreds of KiCad primitives.

## Reference matching

Exact pixel matching is rarely the right target. Match the composition first:

1. dominant regions;
2. visual hierarchy;
3. spacing and rhythm;
4. line weight;
5. local detail.

Board constraints win when the reference conflicts with real geometry.

## Gerber review

A KiCad editor screenshot is useful for iteration. The exported Gerber is the manufacturing artifact.

For final review, inspect the actual exported silkscreen and compare it with the compiled artwork geometry.
