"""Stored wire stroke properties and per-net numbering eligibility.

Read the explicit schematic properties, preserving 'default' / zero values.
Do not substitute display-theme or netclass defaults.
"""
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


STYLES = {'default', 'solid', 'dash', 'dot', 'dash_dot', 'dash_dot_dot'}


def decimal_text(token):
    try:
        number = Decimal(str(token))
        if not number.is_finite() or number < 0:
            raise ValueError('配線の幅・色には有限の非負数が必要です。')
        return '0' if number == 0 else format(number.normalize(), 'f')
    except InvalidOperation as exc:
        raise ValueError('配線の幅・色の値が不正です。') from exc


@dataclass(frozen=True)
class WiringType:
    style: str = 'default'
    width: str = '0'
    color: tuple = ('0', '0', '0', '0')

    @property
    def key(self):
        return json.dumps([self.style, self.width, self.color], separators=(',', ':'))

    @classmethod
    def from_key(cls, key):
        try:
            style, width, color = json.loads(key)
            if style not in STYLES or not isinstance(width, str) or not isinstance(color, list) or len(color) != 4:
                raise ValueError('配線の種類の形式が不正です。')
            result = cls(style, decimal_text(width), tuple(decimal_text(c) for c in color))
            if any(Decimal(c) > 255 for c in result.color[:3]) or Decimal(result.color[3]) > 1:
                raise ValueError('配線の色の範囲が不正です。')
            if result.key != key:
                raise ValueError('配線の種類の識別子が不正です。')
            return result
        except (TypeError, KeyError) as exc:
            raise ValueError('配線の種類の形式が不正です。') from exc

    @property
    def labels(self):
        styles = {'default': '既定', 'solid': '実線', 'dash': '破線', 'dot': '点線',
                  'dash_dot': '一点鎖線', 'dash_dot_dot': '二点鎖線'}
        color = '既定' if self.color == ('0', '0', '0', '0') else 'RGBA(' + ', '.join(self.color) + ')'
        return styles[self.style], '既定 (0)' if self.width == '0' else self.width + ' mm', color


def read_wiring_type(wire):
    # Local import keeps this value object usable by wire_model without a cycle.
    from kicad_import import children, value
    stroke = next(iter(children(wire, 'stroke')), [])
    def tokens(name, fallback):
        node = next(iter(children(stroke, name)), None)
        return [value(t) for t in node[1:]] if node is not None else fallback
    style, = tokens('type', ['default'])
    width, = tokens('width', ['0'])
    color = tokens('color', ['0', '0', '0', '0'])
    result = WiringType(style, decimal_text(width), tuple(decimal_text(c) for c in color))
    return WiringType.from_key(result.key)


def collect_wiring_types(imported):
    """Return unique properties and net mappings across every sheet instance."""
    from kicad_import import children
    from schematic_annotations import resolved_segments
    types = dict.fromkeys(read_wiring_type(w).key for sheet in imported.sheets.values()
                          for w in children(sheet.node, 'wire'))
    segments, _, warnings = resolved_segments(imported)
    mapping = {net.key: [] for net in imported.nets}
    for path, context, a, b, net_key, kind in segments:
        if kind not in mapping[net_key]:
            mapping[net_key].append(kind)
    return types, mapping, warnings


def excluded_nets(settings):
    return {net for net, kinds in settings.net_wire_types.items()
            if kinds and all(not settings.wire_types.get(kind, True) for kind in kinds)}


def clear_excluded_numbers(wires, settings):
    excluded = excluded_nets(settings)
    count = 0
    for wire in wires:
        if wire.net_name in excluded and wire.number:
            wire.number = ''
            count += 1
    return count


def validate_wiring_settings(types, mapping):
    if not isinstance(types, dict) or not isinstance(mapping, dict):
        raise ValueError('配線の種類の設定が不正です。')
    for key, enabled in types.items():
        WiringType.from_key(key)
        if type(enabled) is not bool:
            raise ValueError('採番対象の指定には真偽値が必要です。')
    for net, kinds in mapping.items():
        if not isinstance(net, str) or not net.strip() or not isinstance(kinds, list):
            raise ValueError('ネットと配線の種類の対応が不正です。')
        if any(not isinstance(kind, str) or kind not in types for kind in kinds) or len(set(kinds)) != len(kinds):
            raise ValueError('ネットに未登録または重複した配線の種類があります。')
