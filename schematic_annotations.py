"""Resolve schematic wire geometry and edit only managed graphical texts."""
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from uuid import uuid4

from kicad_import import children, value, parse_schematic
from wire_model import TextAnnotation, validate_annotations


def first(node, name, default=None):
    found = children(node, name)
    return found[0] if found else default


def uid(node):
    item = first(node, 'uuid')
    return value(item[1]) if item and len(item) > 1 else ''


def xy(node):
    return (round(float(node[1]), 6), round(float(node[2]), 6))


class Union:
    def __init__(self):
        self.parents = {}

    def find(self, key):
        self.parents.setdefault(key, key)
        if self.parents[key] != key:
            self.parents[key] = self.find(self.parents[key])
        return self.parents[key]

    def join(self, a, b):
        self.parents[self.find(a)] = self.find(b)


def pin_positions(symbol, library):
    identifier = value(first(symbol, 'lib_id', ['', ''])[1])
    unit = int(first(symbol, 'unit', ['', '1'])[1])
    body = int(first(symbol, 'body_style', ['', '1'])[1])
    origin = first(symbol, 'at')
    if not origin or identifier not in library:
        return []
    angle = math.radians(float(origin[3]) if len(origin) > 3 else 0)
    mirror = first(symbol, 'mirror', ['mirror'])[1:]
    result, visiting = [], set()

    def collect(name):
        if name in visiting or name not in library:
            return
        visiting.add(name)
        definition = library[name]
        parent = first(definition, 'extends')
        if parent:
            inherited = value(parent[1])
            collect(inherited if inherited in library else identifier.rsplit(':', 1)[0] + ':' + inherited)
        for variant in children(definition, 'symbol'):
            match = re.search(r'_(\d+)_(\d+)$', value(variant[1]))
            if not match or int(match[1]) not in (0, unit) or int(match[2]) not in (0, body):
                continue
            for pin in children(variant, 'pin'):
                at, number = first(pin, 'at'), first(pin, 'number')
                if not at or not number:
                    continue
                x, y = float(at[1]), float(at[2])
                if 'x' in mirror:
                    y = -y
                if 'y' in mirror:
                    x = -x
                point = (round(float(origin[1]) + x * math.cos(angle) - y * math.sin(angle), 6),
                         round(float(origin[2]) - x * math.sin(angle) - y * math.cos(angle), 6))
                result.append((value(number[1]), point))
    collect(identifier)
    return result


def on_segment(point, a, b):
    x, y = point
    return abs((x-a[0])*(b[1]-a[1]) - (y-a[1])*(b[0]-a[0])) < 1e-6 and min(a[0], b[0])-1e-6 <= x <= max(a[0], b[0])+1e-6 and min(a[1], b[1])-1e-6 <= y <= max(a[1], b[1])+1e-6


def resolved_segments(imported):
    """Match physical wire segments to imported net keys using existing geometry."""
    from wiring_types import read_wiring_type
    resolved, all_instances, warnings = [], [], []
    for root in imported.roots:
        union = Union()
        seeds, segments, globals_, locals_, hierarchical = [], [], {}, {}, {}
        instances = []

        def instance(path, ids, names, parent=None, reference=None):
            context = tuple(ids)
            sheet = imported.sheets[path]
            instances.append((path, context, tuple(names)))
            node = sheet.node
            if children(node, 'bus') or children(node, 'bus_entry'):
                warnings.append(f'バスを含むシートは自動配置対象外: {path.name}')
                return
            library_node = first(node, 'lib_symbols', [])
            library = {value(s[1]): s for s in children(library_node, 'symbol')}
            points, wires = set(), []
            for wire in children(node, 'wire'):
                pts = first(wire, 'pts', [])
                coords = children(pts, 'xy')
                if len(coords) == 2:
                    a, b = map(xy, coords)
                    points.update((a, b))
                    wires.append((a, b, read_wiring_type(wire).key))
            for junction in children(node, 'junction'):
                at = first(junction, 'at')
                if at:
                    points.add(xy(at))
            def key(point):
                return (context, point)
            for symbol in children(node, 'symbol'):
                props = {value(p[1]): value(p[2]) for p in children(symbol, 'property') if len(p) > 2}
                ref = props.get('Reference', '')
                for block in children(symbol, 'instances'):
                    for project in children(block, 'project'):
                        for item in children(project, 'path'):
                            if tuple(value(item[1]).strip('/').split('/')) == context:
                                ref = value(first(item, 'reference', ['', ref])[1])
                for pin, point in pin_positions(symbol, library):
                    points.add(point)
                    seeds.append((key(point), ref, pin, uid(symbol), context, tuple(names)))
            for kind in ('label', 'global_label', 'hierarchical_label'):
                for label in children(node, kind):
                    at = first(label, 'at')
                    if not at:
                        continue
                    point = xy(at)
                    points.add(point)
                    name = value(label[1])
                    label_key = key(point)
                    group = globals_ if kind == 'global_label' else locals_ if kind == 'label' else hierarchical
                    identity = name if kind == 'global_label' else (context, name)
                    if identity in group:
                        union.join(label_key, group[identity])
                    group[identity] = label_key
            for ref in sheet.refs:
                if ref.reason:
                    continue
                child_context = context + (uid(ref.node),)
                instance(ref.target, child_context, names + [ref.name], context, ref)
                for pin in children(ref.node, 'pin'):
                    at = first(pin, 'at')
                    if not at:
                        continue
                    point = xy(at)
                    points.add(point)
                    child_key = hierarchical.get((child_context, value(pin[1])))
                    if child_key is not None:
                        union.join(key(point), child_key)
            for a, b, kind in wires:
                union.join(key(a), key(b))
                for point in points:
                    if on_segment(point, a, b):
                        union.join(key(a), key(point))
                segments.append((path, context, a, b, key(a), kind))
        instance(root, (uid(imported.sheets[root].node),), [])
        net_lookup = defaultdict(set)
        root_name = root.relative_to(imported.folder).as_posix()
        for net in imported.nets:
            if net.root != root_name:
                continue
            for terminal in net.terminals:
                if terminal.symbol_uuid and terminal.instance_path:
                    identity = (terminal.symbol_uuid, terminal.pin, tuple(terminal.instance_path.strip('/').split('/')))
                else:
                    identity = (terminal.device, terminal.pin, terminal.sheet)
                net_lookup[identity].add(net.key)
                net_lookup[terminal.device, terminal.pin, terminal.sheet].add(net.key)
        connected = defaultdict(set)
        for point, ref, pin, symbol_uuid, context, names in seeds:
            nets = net_lookup.get((symbol_uuid, pin, context), set())
            if not nets:
                nets = net_lookup.get((symbol_uuid, pin, context[1:]), set())
            if not nets:
                nets = net_lookup.get((ref, pin, '/' + '/'.join(names) + ('/' if names else '')), set())
            if len(nets) == 1:
                connected[union.find(point)].update(nets)
            elif len(nets) > 1:
                warnings.append(f'同じ機器・ピン番号が複数ネットに存在するため、この端子からの配置は対象外: {ref}:{pin}')
        for path, context, a, b, point, kind in segments:
            nets = connected[union.find(point)]
            if len(nets) != 1:
                if len(nets) > 1:
                    raise ValueError(f'配線とネットの対応が競合しています: {path.name}: {a} {sorted(nets)}')
                continue
            net_key = next(iter(nets))
            resolved.append((path, context, a, b, net_key, kind))
        all_instances.extend(instances)
    return resolved, all_instances, list(dict.fromkeys(warnings))


def placement_candidates(imported, eligible_nets=None):
    """Return (sheet file, net key) -> text position, plus skipped reasons."""
    segments, instances, warnings = resolved_segments(imported)
    candidates = {}
    by_net = defaultdict(list)
    for path, context, a, b, net_key, kind in segments:
        if eligible_nets is not None and net_key not in eligible_nets:
            continue
        if a[1] == b[1] and a != b:
            position = ((a[0]+b[0])/2, a[1]-1.27)
            priority = (0, -abs(a[0]-b[0]), a, b)
        elif a[0] == b[0] and a != b:
            position = (a[0]+1.27, (a[1]+b[1])/2)
            priority = (1, -abs(a[1]-b[1]), a, b)
        else:
            continue
        by_net[(path, context, net_key)].append((priority, position))

    physical = defaultdict(dict)
    for (path, context, net_key), options in by_net.items():
        position = min(options)[1]
        physical[path, context][net_key] = position
    # Shared files must yield the same net set in every placement. Otherwise
    # one physical text cannot represent instance-specific numbering.
    path_instances = defaultdict(list)
    for path, context, names in instances:
        path_instances[path].append(physical.get((path, context), {}))
    for path, mappings in path_instances.items():
        if mappings and any(set(m) != set(mappings[0]) for m in mappings[1:]):
            raise ValueError(f'同じ子シートの複数配置でネットが異なります: {path.name}')
        if mappings:
            for net_key, position in mappings[0].items():
                candidates[path, net_key] = position
    return candidates, warnings


@dataclass
class TextEdit:
    sheet: object
    net_key: str
    number: str | None
    text_uuid: str
    old_number: str | None
    position: tuple | None = None


def top_level_spans(text):
    tokens = list(re.finditer(r'"(?:\\.|[^"\\])*"|[()]|[^\s()"]+', text))
    depth, start = 0, None
    spans = []
    for token in tokens:
        if token.group() == '(':
            if depth == 1:
                start = token.start()
            depth += 1
        elif token.group() == ')':
            depth -= 1
            if depth == 1 and start is not None:
                spans.append((start, token.end()))
    return spans


def edit_texts(original, edits):
    """Preserve non-target text, formatting, position, and all other objects."""
    text = original.decode('utf-8-sig')
    parse_schematic(text)
    texts = {}
    for start, end in top_level_spans(text):
        node = parse_schematic('(kicad_sch ' + text[start:end] + ')')[1]
        if node[0] == 'text':
            identifier = uid(node)
            if identifier in texts:
                raise ValueError('テキストUUIDが重複しています。')
            texts[identifier] = (start, end, node)
    patches, additions = [], []
    for edit in edits:
        if edit.old_number is not None:
            if edit.text_uuid not in texts:
                raise ValueError('更新対象のテキストUUIDが見つかりません。')
            start, end, node = texts[edit.text_uuid]
            if value(node[1]) != edit.old_number:
                raise ValueError('線番テキストが手動変更されています。')
            if edit.number is None:
                patches.append((start, end, ''))
            elif edit.number != edit.old_number:
                token = re.match(r'\(text\s+("(?:\\.|[^"\\])*")', text[start:end])
                if not token:
                    raise ValueError('更新対象のテキスト形式が不正です。')
                patches.append((start+token.start(1), start+token.end(1), json.dumps(edit.number)))
        else:
            x, y = edit.position
            additions.append(f'\n\t(text "{edit.number}" (at {x:.6f} {y:.6f} 0) (effects (font (size 1.27 1.27))) (uuid "{edit.text_uuid}"))\n')
    if additions:
        offset = text.rfind(')')
        patches.append((offset, offset, ''.join(additions)))
    for start, end, replacement in sorted(patches, reverse=True):
        text = text[:start] + replacement + text[end:]
    parse_schematic(text)
    return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + text.encode('utf-8')
