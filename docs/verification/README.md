# Real KiCad verification

Test target: KiCad CLI **10.0.5**, container `kicad/kicad:10.0` on the verification host.
Board format token: `20241229`. Final evidence uses native named groups and tagged
UUIDs; output was accepted by the actual KiCad parser.

| Evidence | Case | External geometry tests |
| --- | --- | --- |
| [demo-final](kicad-10.0.5/demo-final/evidence.json) | Hatch, filled square around pad/drill, polyline | 11 passed |
| [pads-final](kicad-10.0.5/pads-final/evidence.json) | Front pads, mask graphics, offset/slot, cutout | 11 passed |
| [pads-back-final](kicad-10.0.5/pads-back-final/evidence.json) | Positive back artwork and back mask clipping | 11 passed |
| [arc-final](kicad-10.0.5/arc-final/evidence.json) | Curved board edge | 11 passed |
| [demo-conservative-final](kicad-10.0.5/demo-conservative-final/evidence.json) | Current profile: 0.25 mm clearance, 2 detail warnings | 11 passed |
| [calibration-conservative-final](kicad-10.0.5/calibration-conservative-final/evidence.json) | Current profile: calibration coupon, intentional thin details | 11 passed |

Every case loaded and exported five Gerber layers and Excellon drills. Source and
modified DRC have **zero new normalized violations**. Demo has a preexisting
missing-library warning; the pads fixture also has preexisting design errors.
These synthetic boards are test cases, not examples of production-clean DRC.
Each report retains baseline findings and configured ignored checks.

Independent Gerbonara geometry tests compare actual silk with serialized polygon
unions, clearance against actual mask apertures, and unchanged mask/edge/drill
geometry. Reader curve error is 0.0002 mm; model/export comparison tolerance is
0.002 mm. Small conservative guards account for model and export approximation.

`previews/overlay-F.png` and `overlay-B.png` were visually inspected by the coding agent. Pale grey is
board area, orange is actual mask opening, dark blue is actual exported silk and
white is physical drilling/cutouts. Both sides use board XY without back mirroring.
SVG unions avoid antialias seams between adjacent triangulated Gerber regions;
raw individual-layer Gerber SVGs remain available. Visual review complements the
numerical checks. The four original geometry cohorts retain `not_checked`
for printable width. The two conservative-profile cohorts record
`review_required`: the demo has two isolated hatch tips, and the coupon contains
intentional thin lines, lettering and clipped hatch ends. This is a heuristic
review requirement, not a factory acceptance test. Text height and negative gaps
remain unchecked.

The new cohorts include `manufacturing-review.svg` (model-space risk markers)
and an actual exported front overlay. The calibration cohort also includes
a complete seven-layer copper/mask/silk/edge package plus Excellon in
`fabrication-gerbers.zip`. It is prepared for supplier review and a future
physical calibration sample; no board has been ordered or physically tested.

## Reproduce

```bash
python -m pip install -r requirements-test.txt -r requirements-kicad.txt
python scripts/verify_kicad.py \
  --board tests/fixtures/boards/mask-pad.kicad_pcb \
  --artwork tests/fixtures/artwork/example.json \
  --output /tmp/pcb-artwork-evidence \
  --host YOUR_KICAD_HOST --remote-root /ABSOLUTE/KICAD/DATA/ROOT \
  --cli /ABSOLUTE/PATH/TO/kicad-cli
PCB_ARTWORK_KICAD_EVIDENCE=/tmp/pcb-artwork-evidence \
  python -m pytest -q tests/test_kicad_exports.py
```

Alternatively provide a local CLI via `--cli` and omit SSH options. The runner
freezes CLI version, settings and relative artifact paths. Checksums identify
exported evidence artifacts, not an input-hash compilation protocol. Automatic
runs leave visual review `not_run` until inspected. Without the environment
variable, evidence tests explicitly skip instead of reporting a mock pass.

The earlier `demo-failed-markers` preserves the actual parse failure that exposed
invalid semicolon ownership comments. Earlier accepted runs are retained for
traceability. `demo-conservative` preserves the first manufacturing audit,
including numerical dust later filtered out; its geometry was valid but its
report was noisy. The two `*-conservative-final` directories are authoritative
for the current profile; the other `*-final` directories preserve the completed
geometry-only release gates.
