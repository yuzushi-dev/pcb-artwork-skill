import importlib
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "skills" / "pcb-artwork" / "lib"
SKILL = LIB.parent


def module(name):
    sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location(name, LIB / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


BOARD = '''(kicad_pcb (version 20241229) (generator "fixture")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal)
    (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen"))
  (net 0 "")
  (net 1 "GND")
  (footprint "Fixture:Part" (layer "F.Cu")
    (pad "1" thru_hole circle (at 1 1) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask")))
  (segment (start 1 1) (end 2 1) (width 0.25) (layer "F.Cu") (net 1)
    (uuid "11111111-1111-4111-8111-111111111111"))
  (via (at 2 1) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1)
    (uuid "22222222-2222-4222-8222-222222222222"))
  (zone (net 1) (net_name "GND") (layer "F.Cu")
    (polygon (pts (xy 0 0) (xy 3 0) (xy 3 3) (xy 0 3))))
  (gr_text "existing silk Ω" (at 1 2) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15))))
)
'''


def compilation(layer="F.SilkS", polygon_id="art", points=None):
    return SimpleNamespace(layer=layer, polygons=[{
        "id": polygon_id, "points": points or [[4, 4], [6, 4], [5, 6]]
    }], report={})


def test_native_group_owns_generated_polygons_and_unmanaged_bytes_are_exact():
    patching = module("patching")
    invariants = module("board_invariants")
    patched = patching.patch_text(BOARD, compilation())
    assert invariants.without_managed_objects(patched) == BOARD
    assert '; PCB-ARTWORK-SKILL' not in patched
    assert '(group "pcb-artwork-skill:F.SilkS"' in patched
    generated = re.search(r'\(uuid "([0-9a-f-]{36})"\)', invariants.managed_text(
        patched, "F.SilkS"
    )).group(1)
    assert generated.replace("-", "").startswith("50434241")
    assert uuid.UUID(generated).version == 5


def test_same_side_is_byte_idempotent_and_uuid_is_stable_across_geometry_changes():
    patching = module("patching")
    invariants = module("board_invariants")
    first = patching.patch_text(BOARD, compilation())
    assert patching.patch_text(first, compilation()) == first
    changed = patching.patch_text(BOARD, compilation(points=[[5, 6], [4, 4], [6, 4]]))
    pattern = r'\(uuid "([0-9a-f-]{36})"\)'
    first_id = re.search(pattern, invariants.managed_text(first, "F.SilkS")).group(1)
    changed_id = re.search(pattern, invariants.managed_text(changed, "F.SilkS")).group(1)
    assert first_id == changed_id


def test_front_and_back_update_independently():
    patching = module("patching")
    invariants = module("board_invariants")
    front = patching.patch_text(BOARD, compilation())
    both = patching.patch_text(front, compilation("B.SilkS", "back"))
    saved_front = invariants.managed_text(both, "F.SilkS")
    changed = patching.patch_text(
        both, compilation("B.SilkS", "new", [[7, 7], [9, 7], [8, 9]])
    )
    assert invariants.managed_text(changed, "F.SilkS") == saved_front
    assert set(invariants.managed_objects(changed)) == {"F.SilkS", "B.SilkS"}


def test_missing_group_with_known_generated_uuid_is_rejected():
    patching = module("patching")
    invariants = module("board_invariants")
    patched = patching.patch_text(BOARD, compilation())
    owned = invariants.managed_objects(patched)["F.SilkS"]
    markerless = patched[:owned.group_span[0]] + patched[owned.group_span[1]:]
    with pytest.raises(ValueError, match="UUID|group"):
        patching.patch_text(markerless, compilation())


def test_missing_group_is_rejected_after_geometry_changes_or_item_removal():
    patching = module("patching")
    invariants = module("board_invariants")
    patched = patching.patch_text(BOARD, compilation())
    owned = invariants.managed_objects(patched)["F.SilkS"]
    markerless = patched[:owned.group_span[0]] + patched[owned.group_span[1]:]
    with pytest.raises(ValueError, match="orphan|group|owned"):
        patching.patch_text(
            markerless, compilation(points=[[7, 7], [9, 7], [8, 9]])
        )
    with pytest.raises(ValueError, match="orphan|group|owned"):
        patching.patch_text(markerless, compilation(polygon_id="replacement"))


def test_unrelated_version_five_uuid_is_preserved_as_unmanaged():
    patching = module("patching")
    unrelated = '''  (gr_poly
    (pts (xy 7 7) (xy 9 7) (xy 8 9))
    (stroke (width 0) (type default))
    (fill yes)
    (layer "F.SilkS")
    (uuid "12345678-1234-5678-9234-123456789abc")
  )
'''
    board = BOARD[:-2] + unrelated + ")\n"
    patched = patching.patch_text(board, compilation())
    assert unrelated in patched


def test_duplicate_or_incomplete_native_group_is_rejected():
    patching = module("patching")
    invariants = module("board_invariants")
    patched = patching.patch_text(BOARD, compilation())
    group = invariants.managed_objects(patched)["F.SilkS"].group_text
    duplicate = patched[:-2] + group + "\n)\n"
    with pytest.raises(ValueError, match="duplicate|ambiguous"):
        patching.patch_text(duplicate, compilation())
    broken = patched.replace('(members "', '(members "00000000-0000-5000-8000-000000000000" "')
    with pytest.raises(ValueError, match="member|owned"):
        patching.patch_text(broken, compilation())


def test_named_group_with_old_untagged_member_is_rejected_without_deletion():
    patching = module("patching")
    patched = patching.patch_text(BOARD, compilation())
    generated = re.search(r'\(uuid "(50434241-[0-9a-f-]+)"\)', patched).group(1)
    old = "12345678" + generated[8:]
    incompatible = patched.replace(generated, old)
    with pytest.raises(ValueError, match="untagged"):
        patching.patch_text(incompatible, compilation())


@pytest.mark.parametrize("child", ["id", "members"])
def test_generated_group_rejects_duplicate_singular_children(child):
    patching = module("patching")
    patched = patching.patch_text(BOARD, compilation())
    line = next(line for line in patched.splitlines() if line.strip().startswith(f"({child} "))
    duplicate = patched.replace(line, line + "\n" + line, 1)
    with pytest.raises(ValueError, match=f"duplicate.*{child}|{child}.*duplicate"):
        patching.patch_text(duplicate, compilation())


def test_unmanaged_object_between_owned_objects_is_preserved():
    patching = module("patching")
    patched = patching.patch_text(BOARD, compilation())
    extra = '  (gr_text "keep me" (at 8 8) (layer "F.SilkS"))\n'
    edited = patched.replace('  (group "pcb-artwork-skill:F.SilkS"', extra + '  (group "pcb-artwork-skill:F.SilkS"')
    updated = patching.patch_text(edited, compilation(points=[[7, 7], [9, 7], [8, 9]]))
    assert extra in updated


def test_group_member_order_has_no_ownership_semantics():
    patching = module("patching")
    two = SimpleNamespace(layer="F.SilkS", polygons=[
        {"id": "one", "points": [[4, 4], [6, 4], [5, 6]]},
        {"id": "two", "points": [[7, 7], [9, 7], [8, 9]]},
    ], report={})
    patched = patching.patch_text(BOARD, two)
    members = re.search(r"\(members ([^)]+)\)", patched).group(1).split()
    resaved = patched.replace(" ".join(members), " ".join(reversed(members)))
    assert patching.patch_text(resaved, compilation())


def test_legacy_comment_block_migrates_to_native_group_without_comments():
    patching = module("patching")
    legacy = BOARD[:-2] + '''  ; PCB-ARTWORK-SKILL BEGIN
  (gr_poly (pts (xy 4 4) (xy 6 4) (xy 5 6)) (layer "F.SilkS"))
  ; PCB-ARTWORK-SKILL END
)
'''
    migrated = patching.patch_text(legacy, compilation())
    assert "; PCB-ARTWORK-SKILL" not in migrated
    assert '(group "pcb-artwork-skill:F.SilkS"' in migrated


@pytest.mark.parametrize("bad", [
    SimpleNamespace(layer="Dwgs.User", polygons=[], report={}),
    SimpleNamespace(layer="F.SilkS", polygons=[], report={}),
    compilation(points=[[0, 0], [1, 1]]),
    compilation(points=[[0, 0], [1, 1], [2, 2]]),
    compilation(points=[[0, 0], [3, 2], [0, 2], [2, 0]]),
    compilation(points=[[0, 0], [1, float("inf")], [2, 0]]),
    compilation(points=[[0, 0], [1.0000001, 1], [2, 0]]),
])
def test_invalid_compilation_is_rejected(bad):
    with pytest.raises(ValueError):
        module("patching").patch_text(BOARD, bad)


def test_packaged_import_and_malformed_board():
    sys.path.insert(0, str(SKILL))
    patching = importlib.import_module("lib.patching")
    assert patching.patch_text(BOARD, compilation())
    with pytest.raises(ValueError):
        patching.patch_text(BOARD[:-3], compilation())


def test_write_copy_guards_aliases_mutation_and_uses_atomic_replace(tmp_path, monkeypatch):
    patching = module("patching")
    source = tmp_path / "source.kicad_pcb"
    source.write_text(BOARD)
    original = source.read_bytes()
    patched = patching.patch_text(BOARD, compilation())
    symlink = tmp_path / "symlink.kicad_pcb"
    symlink.symlink_to(source)
    hardlink = tmp_path / "hardlink.kicad_pcb"
    os.link(source, hardlink)
    for alias in (source, symlink, hardlink):
        with pytest.raises(ValueError, match="source"):
            patching.write_board_copy(source, original, patched, alias)
    output = tmp_path / "output.kicad_pcb"
    calls = []
    real_replace = os.replace
    def record_replace(src, dst):
        calls.append((src, dst))
        real_replace(src, dst)
    monkeypatch.setattr(patching.os, "replace", record_replace)
    patching.write_board_copy(source, original, patched, output)
    assert source.read_bytes() == original
    assert output.read_text() == patched
    assert len(calls) == 1
    source.write_text(BOARD.replace("existing silk Ω", "changed silk Ω"))
    with pytest.raises(ValueError, match="changed"):
        patching.write_board_copy(source, original, patched, tmp_path / "late.kicad_pcb")
