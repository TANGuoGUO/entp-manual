from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

from scripts.generate_windows_icon import WINDOWS_ICON_SIZES


ROOT = Path(__file__).resolve().parents[1]


class WindowsIconAssetTests(unittest.TestCase):
    def test_both_windows_icons_contain_every_dpi_size(self) -> None:
        expected = {(size, size) for size in WINDOWS_ICON_SIZES}
        for relative in ("assets/app-icon.ico", "assets/icon_windows.ico"):
            with self.subTest(icon=relative), Image.open(ROOT / relative) as icon:
                self.assertEqual(set(icon.info.get("sizes", set())), expected)

    def test_installer_shortcuts_use_the_multires_icon_file(self) -> None:
        installer = (ROOT / "installer" / "entp_installer.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn('DestName: "ENTPManual.ico"', installer)
        self.assertEqual(installer.count('IconFilename: "{app}\\ENTPManual.ico"'), 2)


if __name__ == "__main__":
    unittest.main()
