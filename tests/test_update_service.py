from __future__ import annotations

import hashlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from update_service import (
    ReleaseInfo,
    UpdateError,
    download_release,
    fetch_latest_release,
    is_newer_version,
    launch_silent_update,
    parse_version,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _release_payload(content: bytes, *, version: str = "2.2.0", digest: str | None = None):
    actual_digest = digest or hashlib.sha256(content).hexdigest()
    name = f"ENTP-Manual-{version}-Setup.exe"
    return {
        "version": version,
        "tag_name": f"v{version}",
        "notes": "更新说明",
        "html_url": f"https://github.com/TANGuoGUO/entp-manual/releases/tag/v{version}",
        "asset_name": name,
        "download_url": (
            "https://github.com/TANGuoGUO/entp-manual/releases/"
            f"download/v{version}/{name}"
        ),
        "size": len(content),
        "sha256": actual_digest,
    }


class UpdateServiceTests(unittest.TestCase):
    def test_UP_01_versions_are_compared_numerically(self) -> None:
        self.assertEqual(parse_version("v2.10.3"), (2, 10, 3))
        self.assertTrue(is_newer_version("2.10.0", "2.9.9"))
        self.assertFalse(is_newer_version("2.1.0", "2.1.0"))
        with self.assertRaises(UpdateError):
            parse_version("latest")

    def test_UP_02_latest_release_uses_exact_project_asset_and_digest(self) -> None:
        content = b"signed installer payload"
        payload = _release_payload(content)

        def opener(_request, timeout):
            self.assertGreater(timeout, 0)
            return _Response(json.dumps(payload).encode("utf-8"))

        release = fetch_latest_release(opener=opener)

        self.assertEqual(release.version, "2.2.0")
        self.assertEqual(release.asset_name, "ENTP-Manual-2.2.0-Setup.exe")
        self.assertEqual(release.sha256, hashlib.sha256(content).hexdigest())

    def test_UP_03_release_without_sha256_is_rejected(self) -> None:
        payload = _release_payload(b"payload", digest="")
        payload["sha256"] = ""

        with self.assertRaisesRegex(UpdateError, "SHA-256"):
            fetch_latest_release(
                opener=lambda *_args, **_kwargs: _Response(
                    json.dumps(payload).encode("utf-8")
                )
            )

    def test_UP_04_download_is_atomic_and_hash_verified(self) -> None:
        content = b"installer" * 4096
        payload = _release_payload(content)
        release = fetch_latest_release(
            opener=lambda *_args, **_kwargs: _Response(json.dumps(payload).encode())
        )
        progress: list[tuple[int, int]] = []
        with TemporaryDirectory() as temporary:
            target = download_release(
                release,
                Path(temporary),
                progress=lambda done, total: progress.append((done, total)),
                opener=lambda *_args, **_kwargs: _Response(content),
            )

            self.assertEqual(target.read_bytes(), content)
            self.assertFalse(target.with_suffix(".exe.part").exists())
            self.assertEqual(progress[-1], (len(content), len(content)))

    def test_UP_05_hash_mismatch_removes_partial_file(self) -> None:
        content = b"tampered"
        release = ReleaseInfo(
            version="2.2.0",
            tag_name="v2.2.0",
            notes="",
            html_url="",
            asset_name="ENTP-Manual-2.2.0-Setup.exe",
            download_url=(
                "https://github.com/TANGuoGUO/entp-manual/releases/"
                "download/v2.2.0/ENTP-Manual-2.2.0-Setup.exe"
            ),
            size=len(content),
            sha256="0" * 64,
        )
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with self.assertRaisesRegex(UpdateError, "校验失败"):
                download_release(
                    release,
                    folder,
                    opener=lambda *_args, **_kwargs: _Response(content),
                )
            self.assertEqual(list(folder.iterdir()), [])

    def test_UP_06_installer_uses_quiet_in_place_update_flags(self) -> None:
        with TemporaryDirectory() as temporary:
            installer = Path(temporary) / "setup.exe"
            installer.write_bytes(b"exe")
            popen = Mock(return_value=object())

            launch_silent_update(installer, popen=popen)

            arguments = popen.call_args.args[0]
            self.assertEqual(arguments[0], str(installer))
            for flag in (
                "/SP-",
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
            ):
                self.assertIn(flag, arguments)


if __name__ == "__main__":
    unittest.main(verbosity=2)
