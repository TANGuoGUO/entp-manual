from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import flet as ft

from flet_app import EntpFletApp


class _Window:
    def __init__(self) -> None:
        self.visible = True
        self.skip_task_bar = False
        self.focused = False
        self.front_calls = 0
        self.destroy_calls = 0

    async def to_front(self) -> None:
        self.front_calls += 1

    async def destroy(self) -> None:
        self.destroy_calls += 1


class TrayBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.window = _Window()
        self.updates = 0
        self.app = EntpFletApp.__new__(EntpFletApp)
        self.app.page = SimpleNamespace(
            window=self.window,
            update=self._update,
        )
        self.app._tray_icon = None
        self.app._tray_hint_shown = False
        self.app._exiting = False
        self.app.tray_available = True
        self.app._write_runtime_error = Mock()

    def _update(self) -> None:
        self.updates += 1

    async def test_TR_01_hide_removes_window_and_taskbar_icon(self) -> None:
        await self.app._hide_window()

        self.assertFalse(self.window.visible)
        self.assertTrue(self.window.skip_task_bar)
        self.assertEqual(self.updates, 1)

    async def test_TR_02_show_restores_and_focuses_window(self) -> None:
        self.window.visible = False
        self.window.skip_task_bar = True

        await self.app._show_window()

        self.assertTrue(self.window.visible)
        self.assertFalse(self.window.skip_task_bar)
        self.assertTrue(self.window.focused)
        self.assertEqual(self.window.front_calls, 1)

    async def test_TR_03_close_hides_instead_of_exiting_when_tray_exists(self) -> None:
        self.app._hide_window = AsyncMock()
        self.app._exit_application = AsyncMock()

        await self.app._handle_window_event(
            SimpleNamespace(type=ft.WindowEventType.CLOSE)
        )

        self.app._hide_window.assert_awaited_once()
        self.app._exit_application.assert_not_awaited()

    async def test_TR_04_tray_exit_closes_database_and_window(self) -> None:
        self.app._stop_tray = Mock()
        self.app._close_database = Mock()

        await self.app._exit_application()

        self.assertTrue(self.app._exiting)
        self.app._stop_tray.assert_called_once()
        self.app._close_database.assert_called_once()
        self.assertEqual(self.window.destroy_calls, 1)


if __name__ == "__main__":
    unittest.main()
