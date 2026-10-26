"""Probe invisible wire-number markers using KiCad 10 on synthetic temp files.

Run: python tests/marker_probe.py [path/to/kicad-cli.exe]
No user schematic or project JSON is read or modified.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


CLI = sys.argv[1] if len(sys.argv) > 1 else r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe'
ROOT = Path(tempfile.mkdtemp(prefix='kiwire-marker-results-'))
TEXT_UUID = '11e86946-5cbb-4d41-a8e3-3aee7f3eac4e'
MARKED_UUID = '4b574d31-5cbb-4d41-a8e3-3aee7f3eac4e'
GROUP_UUID = '63cf656c-caa6-4686-b0a4-07db09d9471a'
GROUP_NAME = 'KiWireManager.WireNumber/v1'


def run(*args):
    result = subprocess.run([CLI, *map(str, args)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result


def schematic(extra='', group='', identifier=TEXT_UUID):
    return f'''(kicad_sch (version 20250114) (generator "kiwire_marker_probe")
      (uuid "782794df-e9a5-467c-86f8-7689c459d28f") (paper "A4") (lib_symbols)
      (text "001" (at 100 100 0) (effects (font (size 1.27 1.27)))
        (uuid "{identifier}") {extra}) {group})'''


def svg(sheet, output):
    result = run('sch', 'export', 'svg', '--output', output, sheet)
    if result.returncode:
        return None, result.stderr + result.stdout
    files = list(output.glob('*.svg'))
    if len(files) != 1:
        raise AssertionError(files)
    # The SVG title contains a wall-clock timestamp; it is not drawing content.
    root = ET.fromstring(files[0].read_bytes())
    for title in root.findall('{http://www.w3.org/2000/svg}title'):
        root.remove(title)
    return ET.tostring(root, encoding='utf-8'), ''


group = f'(group "{GROUP_NAME}" (uuid "{GROUP_UUID}") (members "{TEXT_UUID}"))'
cases = {'plain': schematic(), 'property': schematic('(property "KiWireManager" "wire-number-v1")'),
         'group': schematic(group=group), 'uuid_prefix': schematic(identifier=MARKED_UUID)}
results = {}
baseline_svg = None
for name, content in cases.items():
    folder = ROOT / name
    folder.mkdir()
    sheet = folder / 'probe.kicad_sch'
    sheet.write_text(content, encoding='utf-8')
    before, error = svg(sheet, folder / 'before')
    if name == 'plain':
        assert before is not None, error
        baseline_svg = before
    entry = {'load_ok': before is not None, 'error': error[-1500:]}
    if before is not None:
        entry['same_svg_as_plain'] = before == baseline_svg
        for cycle in (1, 2):
            saved = run('sch', 'upgrade', '--force', sheet)
            assert saved.returncode == 0, saved.stderr + saved.stdout
            current = sheet.read_text(encoding='utf-8-sig')
            if name == 'group':
                assert GROUP_NAME in current and GROUP_UUID in current and TEXT_UUID in current
            if name == 'uuid_prefix':
                assert MARKED_UUID in current
            rendered, error = svg(sheet, folder / f'after{cycle}')
            assert rendered == baseline_svg, (name, cycle, error)
        entry['resave_cycles'] = 2
        entry['resaved_svg_matches_plain'] = True
        entry['saved_sha256'] = hashlib.sha256(sheet.read_bytes()).hexdigest()
    results[name] = entry
assert results['property']['load_ok'] is False
assert results['group']['same_svg_as_plain'] is True
assert results['uuid_prefix']['same_svg_as_plain'] is True
summary = {'kicad': run('version').stdout.strip(), 'artifacts': str(ROOT), 'results': results}
(ROOT / 'results.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
