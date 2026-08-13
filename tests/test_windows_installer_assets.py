from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class WindowsInstallerAssetTests(unittest.TestCase):
    def test_app_icon_assets_are_valid(self) -> None:
        png_path = ROOT / "assets" / "app-icon.png"
        ico_path = ROOT / "assets" / "app-icon.ico"
        self.assertTrue(png_path.is_file())
        self.assertTrue(ico_path.is_file())
        with Image.open(png_path) as image:
            self.assertEqual(image.width, image.height)
            self.assertGreaterEqual(image.width, 512)
        with Image.open(ico_path) as image:
            self.assertEqual(image.format, "ICO")
            self.assertIn((256, 256), image.info.get("sizes", set()))

    def test_installer_exposes_uninstall_and_uses_icon(self) -> None:
        script = (ROOT / "installer" / "entp_installer.iss").read_text(encoding="utf-8")
        build = (ROOT / "installer" / "build_installer.ps1").read_text(encoding="utf-8")
        self.assertIn("SetupIconFile=..\\assets\\app-icon.ico", script)
        self.assertIn('Name: "{group}\\卸载 {#MyAppName}"', script)
        self.assertIn('Filename: "{uninstallexe}"', script)
        self.assertIn('--icon "assets\\app-icon.ico"', build)


if __name__ == "__main__":
    unittest.main()
