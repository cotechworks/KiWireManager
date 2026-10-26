"""Plan, validate, back up and transactionally apply schematic annotations."""
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from kicad_import import children, discover, import_folder, parse_schematic, serialize, value
from schematic_annotations import TextEdit, edit_texts, first, placement_candidates, uid
from wire_model import TextAnnotation, validate_annotations
from wiring_types import excluded_nets


def digest(content):
    return hashlib.sha256(content).hexdigest()


def atomic_write(path, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class MissingAnnotations(ValueError):
    def __init__(self, identifiers):
        self.identifiers = identifiers
        super().__init__('管理している線番テキストが削除されています:\n' + '\n'.join(identifiers))


class RecoveryRequired(ValueError):
    def __init__(self, journal):
        self.journal = journal
        super().__init__(f'前回の書込が未完了です。先にバックアップから復元してください:\n{journal}')


@dataclass
class WritePlan:
    imported: object
    project_path: Path
    originals: dict
    updates: dict
    annotations: list
    edits: list
    warnings: list


def pending_transactions(folder):
    base = Path(folder) / 'backup'
    if not base.exists():
        return []
    found = []
    for path in sorted(base.glob('*/writeback.json')):
        try:
            state = json.loads(path.read_text(encoding='utf-8'))['state']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'バックアップの処理記録を確認できません: {path}') from exc
        if state not in ('committed', 'rolled_back'):
            found.append(path)
    return found


def check_sources(imported):
    if not imported.fingerprints:
        raise ValueError('図面の基準情報がありません。再取込してください。')
    current = discover(imported.folder)
    if current.diagnostics or current.fingerprints != imported.fingerprints:
        raise ValueError('取込後に元図面または参照構成が変更されています。再取込してください。')


def prepare_writeback(imported, wires, settings, annotations, project_path, recreate_missing=False):
    pending = pending_transactions(imported.folder)
    if pending:
        raise RecoveryRequired(pending[0])
    if imported.diagnostics:
        raise ValueError('取込時の不足・警告を解消してから書込んでください。')
    check_sources(imported)
    validate_annotations(annotations)
    settings.validate()
    project_path = Path(project_path).resolve()
    if project_path.suffix.lower() != '.json' or not project_path.is_file():
        raise ValueError('先にプロジェクトJSONを保存してください。')
    if project_path.is_relative_to(imported.folder / 'backup'):
        raise ValueError('バックアップ内のJSONを更新先には指定できません。')
    excluded = excluded_nets(settings)
    numbers, number_nets = {}, {}
    for wire in wires:
        n = wire.number
        if wire.net_name in excluded:
            if n:
                raise ValueError('採番対象外のネットに線番が残っています。採番を実行してください。')
            continue
        if not wire.net_name.strip() or len(n) != 3 or not n.isascii() or not n.isdigit() or n == '000':
            raise ValueError('全ネットを001〜999で採番してから書込んでください。')
        if wire.net_name in numbers and numbers[wire.net_name] != n:
            raise ValueError('同じネットの線番が一致していません。')
        if n in number_nets and number_nets[n] != wire.net_name:
            raise ValueError('異なるネットの線番が重複しています。')
        numbers[wire.net_name], number_nets[n] = n, wire.net_name
    if not numbers and not excluded:
        raise ValueError('書込対象のネットがありません。')
    positions, warnings = placement_candidates(imported, set(numbers)) if numbers else ({}, [])
    originals = {p: p.read_bytes() for p in imported.sheets}
    originals[project_path] = project_path.read_bytes()
    edits, updated_annotations, managed, missing = [], [], set(), []
    for annotation in annotations:
        path = (imported.folder / annotation.sheet).resolve()
        if not path.is_relative_to(imported.folder) or path not in imported.sheets:
            raise ValueError(f'管理対象シートが取込範囲外、または存在しません: {annotation.sheet}')
        key = (path, annotation.net_key)
        if key in managed:
            raise ValueError('同じネット・シートに複数の管理テキストがあります。')
        managed.add(key)
        if annotation.net_key in excluded:
            text_nodes = [n for n in children(imported.sheets[path].node, 'text') if uid(n) == annotation.text_uuid]
            if len(text_nodes) > 1:
                raise ValueError(f'テキストUUIDが重複しています: {path.name}')
            if text_nodes:
                if value(text_nodes[0][1]) != annotation.last_written_number:
                    raise ValueError(f'線番テキストが手動変更されています。削除しません: {annotation.sheet} / {annotation.text_uuid}')
                edits.append(TextEdit(path, annotation.net_key, None, annotation.text_uuid, annotation.last_written_number))
            # A missing text is already deleted; just forget its managed UUID.
            continue
        if annotation.net_key not in numbers:
            updated_annotations.append(annotation)
            continue
        text_nodes = [n for n in children(imported.sheets[path].node, 'text') if uid(n) == annotation.text_uuid]
        if len(text_nodes) > 1:
            raise ValueError(f'テキストUUIDが重複しています: {path.name}')
        number = numbers[annotation.net_key]
        if not text_nodes:
            missing.append(f'{annotation.sheet}: {annotation.text_uuid}')
            if not recreate_missing:
                continue
            if key not in positions:
                raise ValueError(f'再作成する配置候補がありません: {annotation.sheet}')
            identifier = str(uuid4())
            edits.append(TextEdit(path, annotation.net_key, number, identifier, None, positions[key]))
        else:
            if value(text_nodes[0][1]) != annotation.last_written_number:
                raise ValueError(f'線番テキストが手動変更されています。上書きしません: {annotation.sheet} / {annotation.text_uuid}')
            identifier = annotation.text_uuid
            edits.append(TextEdit(path, annotation.net_key, number, identifier, annotation.last_written_number))
        updated_annotations.append(TextAnnotation(path.relative_to(imported.folder).as_posix(), identifier, annotation.net_key, number))
    if missing and not recreate_missing:
        raise MissingAnnotations(missing)
    occupied = {}
    for (path, net_key), position in positions.items():
        if net_key not in numbers:
            continue
        location = (path, position)
        if location in occupied and occupied[location] != numbers[net_key]:
            raise ValueError(f'共用シートの同じ配置位置に異なる線番が必要です: {path.name}')
        occupied[location] = numbers[net_key]
        if (path, net_key) in managed:
            continue
        identifier = str(uuid4())
        edits.append(TextEdit(path, net_key, numbers[net_key], identifier, None, position))
        updated_annotations.append(TextAnnotation(path.relative_to(imported.folder).as_posix(), identifier, net_key, numbers[net_key]))
    represented = {edit.net_key for edit in edits if edit.number is not None}
    for net in numbers.keys() - represented:
        warnings.append(f'配置対象の配線がない、または座標を確定できないネット: {net}')
    grouped = defaultdict(list)
    for edit in edits:
        grouped[edit.sheet].append(edit)
    updates = {}
    for path, operations in grouped.items():
        content = edit_texts(originals[path], operations)
        if content != originals[path]:
            updates[path] = content
    validate_annotations(updated_annotations)
    payload = {'version': 3, 'wires': [asdict(w) for w in wires], 'numbering': asdict(settings),
               'annotations': [asdict(a) for a in updated_annotations]}
    project_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    # Do not rewrite a project solely due to whitespace differences on no-op runs.
    if json.loads(originals[project_path].decode('utf-8-sig')) != payload:
        updates[project_path] = project_bytes
    return WritePlan(imported, project_path, originals, updates, updated_annotations, edits, list(dict.fromkeys(warnings)))


def net_signature(imported):
    return sorted((net.root, net.name, tuple(sorted((t.device, t.pin) for t in net.terminals))) for net in imported.nets)


def validate_with_kicad(plan):
    """Run KiCad on staged copies, never on original files to be overwritten."""
    with tempfile.TemporaryDirectory(prefix='kiwire-validate-') as temporary:
        base = Path(temporary)
        for path, sheet in plan.imported.sheets.items():
            content = plan.updates.get(path, plan.originals[path])
            node = parse_schematic(content.decode('utf-8-sig'))
            for ref_node, ref in zip(children(node, 'sheet'), sheet.refs):
                for prop in children(ref_node, 'property'):
                    if len(prop) >= 3 and value(prop[1]) in ('Sheetfile', 'Sheet file'):
                        prop[2] = json.dumps(os.path.relpath(ref.target, path.parent).replace('\\', '/'), ensure_ascii=False)
            staged = base / path.relative_to(plan.imported.folder)
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(serialize(node), encoding='utf-8')
        verified = import_folder(base)
        if verified.diagnostics or net_signature(verified) != net_signature(plan.imported):
            raise ValueError('書込後のネット接続が元図面と一致しません。元図面は変更していません。')


def save_journal(path, record):
    atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2).encode('utf-8'))


def recover_transaction(journal_path, folder, project_path):
    """Explicit recovery, with destinations restricted to the current project."""
    journal_path, folder, project_path = Path(journal_path).resolve(), Path(folder).resolve(), Path(project_path).resolve()
    backup = journal_path.parent
    if not backup.is_relative_to(folder / 'backup') or journal_path.name != 'writeback.json':
        raise ValueError('復元記録の保存先が不正です。')
    record = json.loads(journal_path.read_text(encoding='utf-8'))
    if record['folder'] != str(folder) or record['project'] != str(project_path):
        raise ValueError('復元記録と現在のプロジェクトが一致しません。')
    if record['state'] == 'committed':
        raise ValueError('完了済み処理は自動復元しません。')
    targets = []
    for entry in record['entries']:
        target = project_path if entry['kind'] == 'project' else (folder / entry['relative']).resolve()
        source = (backup / entry['backup']).resolve()
        if not source.is_relative_to(backup) or (entry['kind'] != 'project' and (not target.is_relative_to(folder) or target.suffix.lower() != '.kicad_sch' or target.is_relative_to(folder / 'backup'))):
            raise ValueError('復元先が範囲外です。')
        original = source.read_bytes()
        if digest(original) != entry['before']:
            raise ValueError('バックアップのハッシュが一致しません。')
        current_hash = digest(target.read_bytes()) if target.exists() else None
        if current_hash not in (entry['before'], entry['after'], None):
            raise ValueError(f'処理後に編集されたファイルがあるため復元を停止します: {target}')
        targets.append((target, original))
    try:
        for target, original in reversed(targets):
            atomic_write(target, original)
        record['state'] = 'rolled_back'
        save_journal(journal_path, record)
    except OSError:
        record['state'] = 'recovery_failed'
        save_journal(journal_path, record)
        raise


def execute_writeback(plan, validator=validate_with_kicad):
    pending = pending_transactions(plan.imported.folder)
    if pending:
        raise RecoveryRequired(pending[0])
    check_sources(plan.imported)
    for path, original in plan.originals.items():
        if path.read_bytes() != original:
            raise ValueError(f'プレビュー後にファイルが変更されました。再取込してください: {path.name}')
    if not plan.updates:
        return None
    validator(plan)
    base = plan.imported.folder / 'backup'
    if base.exists() and (base.is_symlink() or base.resolve() != plan.imported.folder / 'backup'):
        raise ValueError('バックアップ先がリンク先の別フォルダーです。')
    base.mkdir(exist_ok=True)
    backup = base / datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f')
    while True:
        try:
            backup.mkdir()
            break
        except FileExistsError:
            backup = base / (backup.name + '_' + uuid4().hex[:8])
    # Exclusive backup creation, originals are never replaced until all copies verify.
    for path, original in plan.originals.items():
        destination = backup / ('_project.json' if path == plan.project_path else path.relative_to(plan.imported.folder))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        if digest(destination.read_bytes()) != digest(original):
            raise ValueError('バックアップの検証に失敗しました。')
    entries = []
    for path, content in plan.updates.items():
        relative = '' if path == plan.project_path else path.relative_to(plan.imported.folder).as_posix()
        entries.append({'kind': 'project' if path == plan.project_path else 'schematic', 'relative': relative,
                        'backup': '_project.json' if path == plan.project_path else relative,
                        'before': digest(plan.originals[path]), 'after': digest(content)})
    record = {'state': 'prepared', 'folder': str(plan.imported.folder), 'project': str(plan.project_path), 'entries': entries}
    journal = backup / 'writeback.json'
    save_journal(journal, record)
    # Recheck after backup; concurrent edits are not overwritten or rolled back.
    for path, original in plan.originals.items():
        if path.read_bytes() != original:
            record['state'] = 'rolled_back'
            save_journal(journal, record)
            raise ValueError(f'バックアップ中にファイルが変更されました: {path.name}')
    record['state'] = 'committing'
    save_journal(journal, record)
    try:
        for path, content in plan.updates.items():
            if path.read_bytes() != plan.originals[path]:
                raise ValueError(f'書込中にファイルが変更されました: {path.name}')
            atomic_write(path, content)
        record['state'] = 'committed'
        save_journal(journal, record)
    except Exception as exc:
        try:
            recover_transaction(journal, plan.imported.folder, plan.project_path)
        except Exception as recovery_error:
            raise ValueError(f'書込失敗。復元にも失敗しました。次回書込前に復元が必要です。\n{journal}\n{recovery_error}') from exc
        raise ValueError(f'書込に失敗し、バックアップから復元しました。\n{backup}\n{exc}') from exc
    # Advance the baseline only after diagrams and JSON are committed together.
    for path, sheet in plan.imported.sheets.items():
        content = plan.updates.get(path, plan.originals[path])
        sheet.original_bytes = content
        sheet.node = parse_schematic(content.decode('utf-8-sig'))
        plan.imported.fingerprints[path] = digest(content)
    return backup
