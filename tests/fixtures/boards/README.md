# Synthetic board fixtures

Constructed here without private design data. File token `20241229`; real test
CLI 10.0.5. Final accepted exports and DRC are in
[verification evidence](../../../docs/verification/README.md).

| Fixture | Case |
| --- | --- |
| mask-pad | 10 × 10 mm board, central 2 mm pad / 1 mm drill, 0.1 mm mask expansion. |
| geometry-pads | Rotated front/back pad shapes, margin overrides, offset bodies, slot, exposed via, mask graphics and circular board cutout. |
| geometry-arc-outline | D-shaped outline with semicircular edge; checks curved clipping. |
| custom-pad | Unsupported custom pad; expected rejection. |
| open-outline | Open contour; expected rejection. |
| geometry-mask-min-width | Nonzero mask minimum width; expected rejection. |

Supported fixtures are compared against actual mask Gerbers and Excellon holes.
Negative fixtures deliberately cannot compile. Fixture DRC findings predate the
artwork; passing comparison means no new violations, not production readiness.
