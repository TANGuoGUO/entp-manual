from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.verify_windows_bundle import PYTHON_MAGIC, verify_bundle


class WindowsBundleVerifierTests(unittest.TestCase):
    def _bundle(self, root: Path, *, runtime: str = "python313.dll", magic: bytes | None = None) -> Path:
        (root / runtime).write_bytes(b"runtime")
        package = root / "site-packages" / "certifi"
        package.mkdir(parents=True)
        (package / "__init__.pyc").write_bytes((magic or PYTHON_MAGIC["3.13"]) + b"payload")
        return root

    def test_accepts_one_matching_runtime_and_matching_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bytecode, extensions = verify_bundle(
                self._bundle(Path(directory)), "3.13"
            )
        self.assertEqual(bytecode, 1)
        self.assertEqual(extensions, 0)

    def test_rejects_two_python_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self._bundle(Path(directory))
            (bundle / "python314.dll").write_bytes(b"runtime")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                verify_bundle(bundle, "3.13")

    def test_rejects_mismatched_bytecode_magic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = self._bundle(Path(directory), magic=b"BAD!")
            with self.assertRaisesRegex(ValueError, "bytecode does not match"):
                verify_bundle(bundle, "3.13")


if __name__ == "__main__":
    unittest.main()
