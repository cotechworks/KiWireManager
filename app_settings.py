"""Persistent application preferences beside the script or packaged executable."""
import json
import os
import sys
import tempfile
from pathlib import Path


def default_settings_path():
    directory = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    return directory / 'settings.json'


def load_settings(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return True
    if (not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1
            or type(data.get('include_single_terminal')) is not bool):
        raise ValueError('設定ファイルの形式が不正です。')
    return data['include_single_terminal']


def save_settings(path, include_single_terminal):
    if type(include_single_terminal) is not bool:
        raise ValueError('取込設定は真偽値で指定してください。')
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump({'version': 1, 'include_single_terminal': include_single_terminal}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
