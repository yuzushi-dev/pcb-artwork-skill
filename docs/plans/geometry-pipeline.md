# Geometry pipeline — implemented P1–P5

The original implementation specification is preserved in
[geometry-pipeline-spec.md](geometry-pipeline-spec.md). The user approved a smaller
interface: one command consumes the original artwork v1 and board, clips and
writes a PCB copy. There are no input hashes, public compiled schema, external
ownership manifest or separate invariant snapshot.

| Phase | Result |
| --- | --- |
| P1 | Strict schema and semantic validation, finite coordinates, primitive budgets, duplicate IDs and bounded diagnostics. |
| P2 | Structural parser with source spans; board outline/cutouts, effective per-side mask openings and physical holes. |
| P3 | Primitive expansion, conservative clipping, hole-preserving decomposition and distances checked after six-decimal serialization. |
| P4 | Native KiCad groups and tagged UUID ownership; deterministic side-independent updates, byte-preserved unmanaged content and atomic PCB copy writes. |
| P5 | Real KiCad 10.0.5 loading, source/output DRC comparison, five Gerber layers and Excellon drill comparison; independent Gerber geometry and visual review. |

## Command and migration

```bash
python scripts/compile_artwork.py --board board.kicad_pcb --artwork artwork.json \
  --output board-artwork.kicad_pcb --report artwork-report.json
```

`clip_artwork.py` and `patch_kicad.py` are aliases of this command. Their input is
original v1, and their output is a PCB, not compiled JSON. Legacy JSON with `meta`
is rejected. A uniquely bounded old comment-marked managed block may be migrated;
new output uses valid native groups, because KiCad rejects semicolon comments.
Old experimental native groups without tagged members are rejected safely.

Exit 0 means useful geometry was written. Exit 2 means all artwork was removed:
`output_written:false`, no new PCB, any existing output is preserved and reported.
Exit 1 means a diagnostic. The optional report is staged before writing the PCB;
a rare report-promotion failure after PCB promotion explicitly reports partial
success. The two destination files are not a filesystem-wide transaction.
Inputs, outputs and report must be distinct, including symlink/hardlink aliases.

## Geometry and scope

The supported subset is documented in
[the shipped reference](../../skills/pcb-artwork/references/supported-geometry.md).
The first supported board file token is `20241229`; actual CLI target is 10.0.5.
Other file versions and unsupported protected geometry fail with a named location.
Curve error defaults to 0.001 mm; clipping includes conservative approximation and
rounding guards. Edge margin defaults to clearance. Holes are decomposed using
Shapely constrained Delaunay triangulation, with union/area checks before writing.

The board stores current mask defaults in `setup`; a required explicit
`pad_to_mask_clearance` prevents guessing absent settings. `.kicad_pro` mask
settings were migrated into the board by KiCad. Companion `.kicad_dru` custom
rules are rejected because mask-expansion rules can override board/pad values.
This is a standalone-board geometry tool, not a general project rule evaluator.

The parser bounds file size, nesting, decoded strings and total tokens; geometry
bounds curve segments, total board vertices, primitives and serialized vertices.
It rejects duplicate singular fields and extra numeric arguments rather than
accepting potentially different interpretations of the same source.

Each side owns a native `pcb-artwork-skill:<layer>` group and root polygons with
reserved UUID prefix `50434241`, retaining UUID v5/RFC variant. IDs depend on
layer and stable compiled ID, so changed geometry cannot conceal an orphan.
Any tagged polygon outside its group, duplicate membership or prefix collision
blocks the patch. Ordinary objects remain untouched. Manual replacement of both
ownership UUIDs and groups cannot be recognized; keep that metadata intact.
The source is checked directly for concurrent changes before copy promotion.

## Verification and limits

See [real evidence and rerun commands](../verification/README.md). The local suite
also covers unsupported geometry, holes, rotations, mask margins, offsets, slots,
rounding, all-removed status, byte preservation, idempotence, independent sides,
missing ownership and malformed/resource-heavy inputs. External evidence tests
are explicitly skipped when no evidence directory is supplied.

The compile report leaves external gates `not_run`; the separate evidence report
records gates actually executed. DRC comparison means no new normalized violations,
not a clean source design: fixtures retain preexisting library/geometry issues.
Ignored KiCad DRC checks are preserved in each evidence report. The original geometry-only cohort left manufacturer requirements unspecified
and printable width unchecked. The current CLI adds the conservative profile
and post-clipping feature heuristic described in
[manufacturing-profile.md](../../references/manufacturing-profile.md). Narrow
fragments remain visible and require review; supplier compliance and text height
are not certified. No fabrication-readiness claim is made.

## Implementation sources and dependency choice

- [Official PCB S-expression format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/).
- [KiCad 10.0.5 parser](https://gitlab.com/kicad/code/kicad/-/blob/10.0.5/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp).
- [Pad geometry and mask precedence](https://gitlab.com/kicad/code/kicad/-/blob/10.0.5/pcbnew/pad.cpp).
- [Footprint-relative transforms](https://gitlab.com/kicad/code/kicad/-/blob/10.0.5/pcbnew/board_item.cpp).
- [Board settings migration](https://gitlab.com/kicad/code/kicad/-/blob/10.0.5/pcbnew/board_design_settings.cpp).

`sexpdata` 1.0.2 (BSD-2-Clause) was evaluated but lacks list source spans and the
required bounded parsing interface; the small structural parser is local MIT
code. Runtime geometry uses Shapely >=2.1,<3 and jsonschema >=4.22,<5. Optional
independent export verification uses Gerbonara 1.6.3 (Apache-2.0), not a runtime
parser dependency. Rendering does not replace numerical Gerber comparison.
