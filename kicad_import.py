"""Read-only schematic discovery and KiCad 10 XML netlist import.

Only sanitized, temporary copies are passed to KiCad. External/missing sheet
references are removed from those copies, never from the user's schematics.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from wire_model import Wire


def parse_schematic(text):
    matches = list(re.finditer(r'"(?:\\.|[^"\\])*"|[()]|[^\s()"]+', text))
    cursor = 0
    for match in matches:
        if text[cursor:match.start()].strip():
            raise ValueError('回路図の文字列が閉じられていません。')
        cursor = match.end()
    if text[cursor:].strip():
        raise ValueError('回路図の文字列が閉じられていません。')
    tokens = [match.group() for match in matches]
    stack, roots = [], []
    for token in tokens:
        if token == '(':
            node = []
            (stack[-1] if stack else roots).append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError('回路図の括弧が対応していません。')
            stack.pop()
        elif stack:
            stack[-1].append(token)
        else:
            raise ValueError('回路図の形式が不正です。')
    if stack or len(roots) != 1 or not roots[0] or roots[0][0] != 'kicad_sch':
        raise ValueError('KiCad回路図として読み込めません。')
    return roots[0]


def children(node, name):
    return [item for item in node if isinstance(item, list) and item and item[0] == name]


def value(token):
    return json.loads(token) if token.startswith('"') else token


def serialize(node):
    return '(' + ' '.join(serialize(x) if isinstance(x, list) else x for x in node) + ')'


@dataclass
class SheetRef:
    name: str
    filename: str
    target: Path | None
    reason: str = ''
    node: list = field(default_factory=list, repr=False)


@dataclass
class Sheet:
    path: Path
    node: list = field(repr=False)
    refs: list = field(default_factory=list)


@dataclass(frozen=True)
class Terminal:
    device: str
    pin: str
    sheet: str = ''
    pinfunction: str = ''

    @property
    def label(self):
        name = f'{self.pinfunction} [pin {self.pin}]' if self.pinfunction else self.pin
        return f'{self.device} : {name}  {self.sheet}'


@dataclass
class ImportedNet:
    key: str
    name: str
    root: str
    terminals: list


@dataclass
class ImportResult:
    folder: Path
    sheets: dict
    roots: list
    diagnostics: list
    nets: list = field(default_factory=list)


def merge_imported_wires(existing, nets):
    """Append chain connections in XML order, retaining existing edits and IDs."""
    def key(wire):
        return (wire.net_name, frozenset(((wire.source_device, wire.source_terminal),
                                         (wire.target_device, wire.target_terminal))))

    result = list(existing)
    seen = {key(wire) for wire in existing}
    for net in nets:
        terminals = net.terminals
        pairs = list(zip(terminals, terminals[1:])) if len(terminals) > 1 else [(terminals[0] if terminals else None, None)]
        for source, target in pairs:
            wire = Wire(net_name=net.key,
                        source_device=source.device if source else '',
                        source_terminal=source.pin if source else '',
                        target_device=target.device if target else '',
                        target_terminal=target.pin if target else '')
            if key(wire) not in seen:
                result.append(wire)
                seen.add(key(wire))
    return result


def discover(folder):
    base = Path(folder).resolve()
    if not base.is_dir():
        raise ValueError('フォルダーが存在しません。')
    sheets, diagnostics = {}, []
    # Do not follow linked directories. Resolve files before reading their contents.
    visited = set()
    for directory, directories, files in os.walk(base, followlinks=False):
        real_directory = Path(directory).resolve()
        if real_directory in visited or not real_directory.is_relative_to(base):
            directories[:] = []
            continue
        visited.add(real_directory)
        directories[:] = sorted(d for d in directories
                                if not Path(directory, d).is_symlink()
                                and Path(directory, d).resolve().is_relative_to(base)
                                and not (hasattr(Path(directory, d), 'is_junction') and Path(directory, d).is_junction()))
        for filename in sorted(files):
            if filename.lower().startswith('_autosave'):
                continue
            path = Path(directory, filename)
            if path.suffix.lower() != '.kicad_sch':
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(base):
                diagnostics.append(f'不足（フォルダー外）: {path}')
                continue
            try:
                sheets[resolved] = Sheet(resolved, parse_schematic(resolved.read_text(encoding='utf-8-sig')))
            except (OSError, ValueError) as exc:
                diagnostics.append(f'読込失敗: {path.name}: {exc}')
    if not sheets:
        raise ValueError('読み込める .kicad_sch がありません。\n' + '\n'.join(diagnostics))
    for sheet in sheets.values():
        for node in children(sheet.node, 'sheet'):
            props = {value(p[1]): value(p[2]) for p in children(node, 'property') if len(p) >= 3}
            filename = props.get('Sheetfile', props.get('Sheet file', ''))
            target = None
            reason = ''
            if not filename or '${' in filename:
                reason = 'ファイル名未指定・未解決変数'
            else:
                target = (sheet.path.parent / filename).resolve()
                if not target.is_relative_to(base):
                    reason = 'フォルダー外'
                elif target not in sheets:
                    reason = '参照先がない、または読込不可'
            ref = SheetRef(props.get('Sheetname', props.get('Sheet name', filename)), filename, target, reason, node)
            sheet.refs.append(ref)
            if reason:
                diagnostics.append(f'不足（{reason}）: {sheet.path.relative_to(base)} → {filename}')
    referenced = {ref.target for sheet in sheets.values() for ref in sheet.refs if not ref.reason}
    roots = sorted(set(sheets) - referenced)
    # DFS across all components, including components without any root.
    done, active = set(), []

    def visit(path):
        if path in active:
            cycle = active[active.index(path):] + [path]
            raise ValueError('循環参照: ' + ' → '.join(str(p.relative_to(base)) for p in cycle))
        if path in done:
            return
        active.append(path)
        for ref in sheets[path].refs:
            if not ref.reason:
                visit(ref.target)
        active.pop()
        done.add(path)

    for path in sheets:
        visit(path)
    return ImportResult(base, sheets, roots, diagnostics)


def find_cli():
    executable = shutil.which('kicad-cli')
    candidates = [Path(executable)] if executable else []
    if os.name == 'nt':
        candidates.insert(0, Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'KiCad/10.0/bin/kicad-cli.exe')
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise ValueError('KiCad 10のkicad-cliが見つかりません。KiCad 10をインストールしてPATHに追加してください。')


def read_netlist(xml_path, root_name, root_key=None):
    document = ET.parse(xml_path).getroot()
    # Validate before filtering/deduplication, including unconnected library pins.
    invalid_parts = set()
    for part in document.findall('./libparts/libpart'):
        if any(not pin.get('num', '').strip() for pin in part.findall('./pins/pin')):
            invalid_parts.add((part.get('lib', ''), part.get('part', '')))
    missing = {node.get('ref', '').strip() or '（リファレンス不明）'
               for node in document.findall('./nets/net/node')
               if not node.get('pin', '').strip()}
    for component in document.findall('./components/comp'):
        source = component.find('libsource')
        if source is not None and (source.get('lib', ''), source.get('part', '')) in invalid_parts:
            missing.add(component.get('ref', '').strip() or '（リファレンス不明）')
    if missing:
        raise ValueError(f'ピン番号が未設定のシンボルがあります（{root_name}）。\nリファレンス: '
                         + ', '.join(sorted(missing)) + '\nKiCadで各ピンに一意の番号を設定してください。')
    components = {}
    for component in document.findall('./components/comp'):
        ref = component.get('ref', '')
        if not ref or ref in components:
            raise ValueError('機器番号が空、または重複しています。KiCadでアノテーションを確認してください。')
        sheet = component.find('sheetpath')
        components[ref] = sheet.get('names', '') if sheet is not None else ''
    nets = []
    for node in document.findall('./nets/net'):
        name = node.get('name', '')
        terminals = []
        seen = set()
        for endpoint in node.findall('node'):
            ref, pin = endpoint.get('ref', ''), endpoint.get('pin', '')
            if not ref or not pin or (ref, pin) in seen:
                continue
            seen.add((ref, pin))
            terminals.append(Terminal(ref, pin, components.get(ref, ''),
                                      endpoint.get('pinfunction', '')))
        if name:
            nets.append(ImportedNet(f'{root_key or root_name}::{name}', name, root_name, terminals))
    return nets


def import_folder(folder, cli=None):
    result = discover(folder)
    cli = cli or find_cli()
    with tempfile.TemporaryDirectory(prefix='kiwire-import-') as temporary:
        stage = Path(temporary) / 'schematics'
        stage.mkdir()
        staged = {path: stage / path.relative_to(result.folder) for path in result.sheets}
        for path, sheet in result.sheets.items():
            # Rewrite every child reference to an allowed staged file. Invalid
            # references are removed in copies so KiCad cannot open originals.
            blocked = {id(ref.node) for ref in sheet.refs if ref.reason}
            node = [item for item in sheet.node if id(item) not in blocked]
            node = parse_schematic(serialize(node))
            valid_refs = [ref for ref in sheet.refs if not ref.reason]
            for ref_node, ref in zip(children(node, 'sheet'), valid_refs):
                for prop in children(ref_node, 'property'):
                    if len(prop) >= 3 and value(prop[1]) in ('Sheetfile', 'Sheet file'):
                        prop[2] = json.dumps(os.path.relpath(staged[ref.target], staged[path].parent).replace('\\', '/'), ensure_ascii=False)
            staged[path].parent.mkdir(parents=True, exist_ok=True)
            staged[path].write_text(serialize(node), encoding='utf-8')
        for index, root in enumerate(result.roots):
            output = Path(temporary) / f'netlist-{index}.xml'
            environment = os.environ.copy()
            environment['KICAD_CONFIG_HOME'] = str(Path(temporary) / 'config')
            try:
                process = subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                                          '--output', str(output), str(staged[root])],
                                         capture_output=True, text=True, encoding='utf-8', errors='replace',
                                         timeout=60, env=environment,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired as exc:
                raise ValueError(f'KiCadの処理がタイムアウトしました: {root.name}') from exc
            if process.returncode or not output.exists():
                raise ValueError(f'ネットリスト取得失敗: {root.name}\n{process.stderr[-3000:]}\n{process.stdout[-1000:]}')
            root_name = root.relative_to(result.folder).as_posix()
            result.nets.extend(read_netlist(output, root_name, root.as_posix()))
            if process.stderr.strip():
                result.diagnostics.append(f'KiCad: {root_name}: {process.stderr[-1500:].strip()}')
    return result
