# Conservative manufacturing profile

Source snapshot: 2026-09-30. Applies to ordinary PCB silkscreen artwork; not to
copper trace width or specialized printing processes.

| Parameter | Conservative target | Published source |
| --- | --- | --- |
| Line width | 0.20 mm | JLCPCB recommends 0.20 mm; JLCPCB and PCBWay list 0.15 mm minimum. |
| Mask/drill clearance | At least 0.25 mm | JLCPCB recommends 0.25 mm to soldermask; published minimum 0.15 mm. Drill clearance is our conservative extension. |
| Text height | 1.0 mm guidance | JLCPCB capabilities list 1.0 mm; PCBWay lists 0.8 mm. |

The CLI defaults to this profile. It raises requested clearance only when below
0.25 mm and records both requested and effective values. Edge margin follows
effective clearance unless explicitly set. Library callers opt in with
`manufacturing_profile="conservative"`. Use CLI
`--manufacturing-profile geometry-only` to disable the profile explicitly.

The profile is an engineering recommendation, not a jointly certified supplier
profile. PCBWay mask clearance, actual process options and any CAM adjustments
still need confirmation for the order. Supplier values may change; update the
snapshot intentionally when checking new requirements.

## Width review

The compiler audits the union of final serialized ink, including clipped pieces
and holes. Thin isolated components and potential small-feature loss generate
`review_required`. No automatic deletion or thickening occurs. A result without
warnings is `heuristic_passed`, not a proof of minimum printable width.
The method uses mitred erosion/opening at half the target width, with a
0.00002 mm radius tolerance. A 0.000004 mm² feature-loss floor suppresses
non-structural numerical dust at the default target; fully thin components
and splits remain warnings even at tiny area. Sharp tips may escape this
heuristic, so visual and supplier review remain necessary.
`--review-svg review.svg` shows model-space ink in dark blue, protected geometry
in orange, and suspect regions in red. At most 100 regions are returned; the
report declares truncation when more exist. It complements actual Gerber inspection.

Text height cannot be inferred from unlabelled polygons; minimum negative gap,
ink registration and supplier-specific processing are not checked. The public
calibration coupon intentionally contains details below the profile target so
an ordered sample can reveal actual rendering limits. Preparing it does not
order or upload a board. Preserve the CAM artwork and approve changes explicitly.

Sources:

- [JLCPCB capabilities](https://jlcpcb.com/capabilities/pcb-capabilities).
- [JLCPCB silkscreen recommendations](https://jlcpcb.com/blog/pcb-silkscreen).
- [PCBWay capabilities](https://www.pcbway.com/capabilities.html).
