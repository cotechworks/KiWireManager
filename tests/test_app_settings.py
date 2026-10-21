import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_settings


class SettingsTests(unittest.TestCase):
    def test_default_and_persist_false(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            self.assertTrue(app_settings.load_settings(path))
            self.assertFalse(path.exists())
            app_settings.save_settings(path, False)
            self.assertFalse(app_settings.load_settings(path))
            app_settings.save_settings(path, True)
            self.assertTrue(app_settings.load_settings(path))

    def test_invalid_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for data in ([], {'version': 2, 'include_single_terminal': False},
                         {'version': 1, 'include_single_terminal': 'false'}, {}):
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    app_settings.load_settings(path)

    def test_failed_save_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            app_settings.save_settings(path, True)
            original = path.read_bytes()
            with patch('app_settings.os.replace', side_effect=PermissionError('read only')):
                with self.assertRaises(OSError):
                    app_settings.save_settings(path, False)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_location_uses_script_or_frozen_executable(self):
        self.assertEqual(app_settings.default_settings_path().name, 'settings.json')
        self.assertEqual(app_settings.default_settings_path().parent, Path(app_settings.__file__).resolve().parent)
        with patch.object(app_settings.sys, 'frozen', True, create=True), \
                patch.object(app_settings.sys, 'executable', str(Path.cwd() / 'distribution' / 'app.exe')):
            self.assertEqual(app_settings.default_settings_path().parent, Path.cwd() / 'distribution')


if __name__ == '__main__':
    unittest.main()
