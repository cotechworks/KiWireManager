"""Physical wire records, numbering, and portable project files."""
import csv
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4


def display_net_name(name):
    marker = '.kicad_sch::'
    index = name.lower().find(marker)
    return name[index + len(marker):] if index >= 0 else name


@dataclass
class Wire:
    source_device: str = ''
    source_terminal: str = ''
    target_device: str = ''
    target_terminal: str = ''
    number: str = ''
    wire_id: str = field(default_factory=lambda: uuid4().hex)
    net_name: str = ''


@dataclass
class Numbering:
    prefix: str = ''
    start: int = 1
    digits: int = 3

    def validate(self):
        if not isinstance(self.prefix, str):
            raise ValueError('接頭辞は文字列で指定してください。')
        if type(self.start) is not int or self.start < 0:
            raise ValueError('開始番号は0以上の整数で指定してください。')
        if type(self.digits) is not int or not 1 <= self.digits <= 12:
            raise ValueError('桁数は1〜12で指定してください。')


def issues(wires, include_unnumbered=True):
    result = []
    net_numbers = {}
    number_nets = {}
    for i, wire in enumerate(wires, 1):
        if not all((wire.source_device.strip(), wire.source_terminal.strip(),
                    wire.target_device.strip(), wire.target_terminal.strip())):
            result.append(f'{i}行目: 接続元・接続先の機器番号と端子番号が必要です。')
        if include_unnumbered:
            if not wire.net_name.strip():
                result.append(f'{i}行目: ネット名が未設定です。')
            elif len(wire.number) != 3 or not wire.number.isascii() or not wire.number.isdigit() or wire.number == '000':
                result.append(f'{i}行目: 線番は001〜999の3桁で採番してください。')
            else:
                if wire.net_name in net_numbers and net_numbers[wire.net_name] != wire.number:
                    result.append(f'{i}行目: 同じネットに異なる線番があります。')
                if wire.number in number_nets and number_nets[wire.number] != wire.net_name:
                    result.append(f'{i}行目: 異なるネットで線番が重複しています。')
                net_numbers[wire.net_name] = wire.number
                number_nets[wire.number] = wire.net_name
    return result


def assign_numbers(wires, settings=None):
    # Numbering belongs to the net, independently of physical routing.
    nets = dict.fromkeys(w.net_name for w in wires if w.net_name.strip())
    if len(nets) > 999:
        raise ValueError('ネット数が999を超えるため採番できません。データは変更していません。')
    numbers = {net: f'{i:03d}' for i, net in enumerate(nets, 1)}
    count = 0
    for wire in wires:
        if wire.net_name in numbers and wire.number != numbers[wire.net_name]:
            wire.number = numbers[wire.net_name]
            count += 1
    return count


def save_project(path, wires, settings):
    settings.validate()
    payload = {'version': 2, 'numbering': asdict(settings),
               'wires': [asdict(w) for w in wires]}
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_project(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if type(data) is not dict or type(data.get('version')) is not int or data['version'] not in (1, 2):
            raise ValueError('対応していないプロジェクト形式です。')
        settings = Numbering(**data['numbering'])
        settings.validate()
        if not isinstance(data['wires'], list):
            raise ValueError('電線一覧の形式が不正です。')
        wires = []
        ids = set()
        fields = set(Wire.__dataclass_fields__)
        if data['version'] == 1:
            fields = fields - {'net_name'}
        for record in data['wires']:
            if not isinstance(record, dict) or set(record) != fields:
                raise ValueError('電線データの項目が不正です。')
            if not all(isinstance(value, str) for value in record.values()):
                raise ValueError('電線データは文字列である必要があります。')
            wire = Wire(**record)
            if not wire.wire_id or wire.wire_id in ids:
                raise ValueError('電線IDが空、または重複しています。')
            ids.add(wire.wire_id)
            wires.append(wire)
        return wires, settings
    except (KeyError, TypeError) as exc:
        raise ValueError('プロジェクト形式が不正です。') from exc


def export_csv(path, wires):
    errors = issues(wires)
    if errors:
        raise ValueError('\n'.join(errors))
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['電線ID', '線番', 'ネット名', '接続元機器', '接続元端子', '接続先機器', '接続先端子'])
        for w in wires:
            writer.writerow([w.wire_id, w.number, display_net_name(w.net_name), w.source_device, w.source_terminal,
                             w.target_device, w.target_terminal])
