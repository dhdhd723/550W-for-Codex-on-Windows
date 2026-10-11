import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from launcher.edition import Edition, read_edition
from launcher.config import data_dir


class EditionTests(unittest.TestCase):
    def test_brief_cannot_accidentally_ship_full_audio_policy(self):
        for raw in ({'name': '550W简洁版', 'mode': 'full', 'sound': False},
                    {'name': '550W简洁版', 'mode': 'brief', 'sound': True}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                Edition.parse(raw)

    def test_profile_from_portable_file_not_existing_user_preferences(self):
        raw = {'name': '550W简洁版', 'mode': 'brief', 'sound': False,
               'data_folder': '550WBrief', 'fixed_mode': True}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'edition.json'
            path.write_text(json.dumps(raw), encoding='utf-8')
            self.assertEqual(read_edition(path), Edition(**raw))

    def test_missing_manifest_keeps_source_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(read_edition(Path(folder) / 'absent.json'), Edition())

    def test_untrusted_profile_cannot_escape_local_appdata(self):
        for data_folder in ('../private', 'C:/private', '550W/../../private', '550W\\private'):
            with self.subTest(data_folder=data_folder), self.assertRaises(ValueError):
                Edition.parse({'data_folder': data_folder})

    def test_version_data_directories_are_separate(self):
        brief = Edition.parse({'name': '550W简洁版', 'mode': 'brief', 'sound': False, 'data_folder': '550WBrief'})
        full = Edition.parse({'name': '550W完整版', 'data_folder': '550WFull'})
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'LOCALAPPDATA': folder}):
            with patch('launcher.config.CURRENT', brief):
                brief_path = data_dir()
            with patch('launcher.config.CURRENT', full):
                full_path = data_dir()
            self.assertNotEqual(brief_path, full_path)
            self.assertEqual(brief_path.parent, full_path.parent)
            self.assertTrue(brief_path.is_dir() and full_path.is_dir())


if __name__ == '__main__':
    unittest.main()
