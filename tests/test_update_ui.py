from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from app_version import APP_VERSION
from flet_app import EntpFletApp
from update_service import ReleaseInfo


def _release(version: str) -> ReleaseInfo:
    return ReleaseInfo(
        version=version,
        tag_name=f"v{version}",
        notes="说明",
        html_url=f"https://github.com/TANGuoGUO/entp-manual/releases/tag/v{version}",
        asset_name=f"ENTP-Manual-{version}-Setup.exe",
        download_url=(
            "https://github.com/TANGuoGUO/entp-manual/releases/"
            f"download/v{version}/ENTP-Manual-{version}-Setup.exe"
        ),
        size=1024,
        sha256="0" * 64,
    )


class UpdateUiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = EntpFletApp.__new__(EntpFletApp)
        self.app.available_release = None
        self.app._update_checking = False
        self.app._update_downloading = False
        self.app.update_button = ft.TextButton(f"检查更新 · {APP_VERSION}")
        self.app.page = SimpleNamespace(update=Mock())
        self.app._notify_success = Mock()
        self.app._notify_error = Mock()
        self.app._write_runtime_error = Mock()

    async def test_UP_07_automatic_check_marks_available_update_without_modal(self) -> None:
        latest = _release("9.0.0")
        self.app.show_update_dialog = Mock()
        with patch("flet_app.fetch_latest_release", return_value=latest):
            await self.app._check_for_updates(manual=False)

        self.assertIs(self.app.available_release, latest)
        self.assertEqual(self.app.update_button.content, "更新到 9.0.0")
        self.app.show_update_dialog.assert_not_called()
        self.app._notify_success.assert_called_once()

    async def test_UP_08_manual_check_reports_latest_version(self) -> None:
        with patch("flet_app.fetch_latest_release", return_value=_release(APP_VERSION)):
            await self.app._check_for_updates(manual=True)

        self.assertIsNone(self.app.available_release)
        self.app._notify_success.assert_called_once_with(
            f"当前版本 {APP_VERSION} 已是最新版"
        )
        self.app._notify_error.assert_not_called()

    async def test_UP_09_daily_check_runs_only_once(self) -> None:
        settings: dict[str, str] = {}
        self.app.db = SimpleNamespace(
            get_setting=lambda key: settings.get(key, ""),
            set_setting=lambda key, value: settings.__setitem__(key, value),
        )
        self.app._check_for_updates = AsyncMock()

        await self.app._auto_check_for_updates()
        await self.app._auto_check_for_updates()

        self.app._check_for_updates.assert_awaited_once_with(manual=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)

