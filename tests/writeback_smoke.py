"""End-to-end writer check on temporary copies only. Requires KiCad 10."""
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kicad_import import discover, import_folder
from schematic_writeback import prepare_writeback, execute_writeback, net_signature
from wire_model import Numbering, assign_numbers, load_project, save_project
from kicad_import import merge_imported_wires


source = discover(sys.argv[1])
before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.sheets}
with tempfile.TemporaryDirectory(prefix='kiwire-write-test-') as temporary:
    folder = Path(temporary)
    for path, sheet in source.sheets.items():
        copy = folder / path.relative_to(source.folder)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(sheet.original_bytes)
    imported = import_folder(folder)
    wires = merge_imported_wires([], imported.nets)
    assign_numbers(wires)
    project = folder / 'project.json'
    save_project(project, wires, Numbering())
    plan = prepare_writeback(imported, wires, Numbering(), [], project)
    assert plan.edits
    backup = execute_writeback(plan)
    assert backup.is_dir()
    annotations = load_project(project)[2]
    assert annotations == plan.annotations
    assert not prepare_writeback(imported, wires, Numbering(), annotations, project).updates
    fresh = import_folder(folder)
    assert set(fresh.sheets) == set(imported.sheets), 'backup files entered import'
    assert net_signature(fresh) == net_signature(imported)
    # Renumber every net, then exercise UUID updates with the production validator.
    mapping = {key: f'{index:03d}' for index, key in enumerate(reversed(list(dict.fromkeys(w.net_name for w in wires))), 1)}
    for wire in wires:
        wire.number = mapping[wire.net_name]
    update = prepare_writeback(fresh, wires, Numbering(), annotations, project)
    next_backup = execute_writeback(update)
    assert next_backup != backup
    assert load_project(project)[2] == update.annotations
    assert len(load_project(project)[2]) == len(annotations)
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.sheets} == before
    print('PASS temporary-copy write, backup, UUID JSON, no-op repeat, renumber update, network invariance, original hashes')
    print('sheets=%d nets=%d annotations=%d warnings=%d' % (len(imported.sheets), len(imported.nets), len(annotations), len(plan.warnings)))
