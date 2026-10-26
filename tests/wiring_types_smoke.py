"""Real KiCad import, mixed-stroke mapping and managed deletion on temp copies."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kicad_import import children, discover, import_folder, merge_imported_wires, serialize
from schematic_writeback import prepare_writeback, execute_writeback, net_signature
from wire_model import Numbering, assign_numbers, save_project, load_project
from wiring_types import WiringType, collect_wiring_types, clear_excluded_numbers, excluded_nets


source = discover(sys.argv[1])
before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.sheets}
with tempfile.TemporaryDirectory(prefix='kiwire-types-smoke-') as temporary:
    folder = Path(temporary)
    # Use the actual hierarchy; add distinct strokes only in the copies.
    palette = [WiringType(), WiringType('dash', '0.25', ('255', '0', '0', '1')),
               WiringType('dot', '0.5', ('0', '0', '255', '1'))]
    index = 0
    for path, sheet in source.sheets.items():
        node = sheet.node
        for wire in children(node, 'wire'):
            kind = palette[index % len(palette)]
            wire[:] = [n for n in wire if not isinstance(n, list) or not n or n[0] != 'stroke']
            wire.append(['stroke', ['width', kind.width], ['type', kind.style], ['color', *kind.color]])
            index += 1
        destination = folder / path.relative_to(source.folder)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialize(node), encoding='utf-8')
    imported = import_folder(folder)
    types, mapping, warnings = collect_wiring_types(imported)
    assert set(types) == {t.key for t in palette}
    mixed = sum(len(kinds) > 1 for kinds in mapping.values())
    assert mixed, 'fixture must exercise mixed types within real nets'
    settings = Numbering(wire_types=dict.fromkeys(types, True), net_wire_types=mapping)
    wires = merge_imported_wires([], imported.nets)
    assign_numbers(wires, settings)
    project = folder / 'project.json'
    save_project(project, wires, settings)
    initial = prepare_writeback(imported, wires, settings, [], project)
    assert initial.edits
    execute_writeback(initial)
    signature = net_signature(imported)
    # One off must retain every mixed net that still contains an enabled type.
    settings.wire_types[palette[0].key] = False
    assert all(net not in excluded_nets(settings) for net, kinds in mapping.items() if len(kinds) > 1)
    # All off removes every mapped net and its managed graphical annotations.
    settings.wire_types = dict.fromkeys(types, False)
    clear_excluded_numbers(wires, settings)
    deletion = prepare_writeback(imported, wires, settings, initial.annotations, project)
    count = sum(e.number is None for e in deletion.edits)
    assert count == len(initial.annotations), 'every initially annotated net must be excluded'
    execute_writeback(deletion)
    assert load_project(project)[2] == []
    verified = import_folder(folder)
    assert net_signature(verified) == signature
    assert not prepare_writeback(imported, wires, settings, [], project).updates
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.sheets} == before
    print(json.dumps({'sheets': len(imported.sheets), 'nets': len(imported.nets), 'types': len(types),
                      'mixed_nets': mixed, 'created_then_deleted': count, 'warnings': len(warnings)}))
    print('PASS real KiCad mixed strokes, exclusion, managed deletion, backups, no-op repeat, unchanged connectivity and originals')
