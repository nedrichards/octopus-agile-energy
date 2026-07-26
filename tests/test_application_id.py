import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.application_id import DEFAULT_APPLICATION_ID, get_application_id, is_development_build


class ApplicationIdTests(unittest.TestCase):
    def test_uses_flatpak_application_id(self):
        self.assertEqual(
            get_application_id({"FLATPAK_ID": "com.nedrichards.octopusagile.Devel"}),
            "com.nedrichards.octopusagile.Devel",
        )

    def test_uses_production_id_outside_flatpak(self):
        self.assertEqual(get_application_id({}), DEFAULT_APPLICATION_ID)

    def test_ignores_empty_flatpak_application_id(self):
        self.assertEqual(get_application_id({"FLATPAK_ID": ""}), DEFAULT_APPLICATION_ID)

    def test_development_build_uses_devel_application_id(self):
        self.assertTrue(is_development_build({"FLATPAK_ID": "com.nedrichards.octopusagile.Devel"}))

    def test_production_build_is_not_development(self):
        self.assertFalse(is_development_build({"FLATPAK_ID": DEFAULT_APPLICATION_ID}))


if __name__ == "__main__":
    unittest.main()
