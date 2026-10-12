"""Today header must offer a real date picker, and deletion must ask first."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import flet as ft

from database import Database
from flet_app import EntpFletApp
from markdown_store import MarkdownStore


class StubPage:
    def __init__(self) -> None:
        self.dialogs: list = []
        self.updates = 0

    def show_dialog(self, dialog) -> None:
        self.dialogs.append(dialog)

    def pop_dialog(self) -> None:
        if self.dialogs:
            self.dialogs.pop()

    def update(self) -> None:
        self.updates += 1


class DayPickerAndDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "delete-ui.db")
        self.app = EntpFletApp.__new__(EntpFletApp)
        self.app.db = self.db
        self.app.current_mid = self.db.current_mainline_id()
        self.app.page = StubPage()
        self.app.selected_day = date.today()
        self.app.active_index = EntpFletApp.NAV_TODAY
        self.app.selected_task_id = None
        self.app.selected_thought_id = None
        self.app.selected_mainline_id = None
        self.app._active_editor_dialog = None
        self.app._closed = False
        self.app._exiting = False
        self.app._write_runtime_error = lambda *_: None
        self.errors: list[str] = []
        self.messages: list[str] = []
        self.app._notify_error = self.errors.append
        self.app._notify_success = self.messages.append
        self.app._sync_markdown = lambda **_: True
        self.views: list[int] = []
        self.app.show_view = self.views.append
        self.app.markdown = MarkdownStore(Path(self.temp.name) / "markdown")
        self.app.today_priority_sort = False

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    # ------------------------------------------------------------- day picker

    def test_TP_01_today_header_exposes_a_date_picker_button(self) -> None:
        header = self.app._today_header()
        tooltips = [
            getattr(control, "tooltip", None) for control in header.controls[1].controls
        ]
        self.assertIn("选择日期", tooltips)

    def test_TP_02_picking_a_past_day_moves_the_ledger(self) -> None:
        target = date.today() - timedelta(days=9)
        self.app.open_day_picker()
        picker = self.app.page.dialogs[-1]
        self.assertIsInstance(picker, ft.DatePicker)
        self.assertEqual(picker.last_date, date.today())

        class _Event:
            control = picker

        picker.value = target
        picker.on_change(_Event())

        self.assertEqual(self.app.selected_day, target)
        self.assertEqual(self.views, [EntpFletApp.NAV_TODAY])

    def test_TP_03_future_days_stay_clamped_to_today(self) -> None:
        self.app.open_day_picker()
        picker = self.app.page.dialogs[-1]

        class _Event:
            control = picker

        picker.value = date.today() + timedelta(days=3)
        picker.on_change(_Event())

        self.assertEqual(self.app.selected_day, date.today())

    # ---------------------------------------------------------------- deletion

    def test_DL_01_delete_confirmation_runs_only_after_confirming(self) -> None:
        runs: list[str] = []
        self.app._confirm_delete("删除任务", "确定吗？", "删除", lambda: runs.append("done"))
        dialog = self.app.page.dialogs[-1]
        self.assertIsInstance(dialog, ft.AlertDialog)
        self.assertEqual(len(dialog.actions), 2)
        self.assertEqual(runs, [])

        dialog.actions[1].on_click(None)
        self.assertEqual(runs, ["done"])

    def test_DL_02_delete_task_removes_it_and_reports(self) -> None:
        task_id = self.db.create_task(self.current_mid(), "可以删掉的任务")
        self.app.request_delete_task(task_id)
        dialog = self.app.page.dialogs[-1]
        # 第一次取消不应该删除任何东西。
        dialog.actions[0].on_click(None)
        self.assertIsNotNone(self.db.get_task(task_id))

        self.app.request_delete_task(task_id)
        self.app.page.dialogs[-1].actions[1].on_click(None)
        self.assertIsNone(self.db.get_task(task_id))
        self.assertTrue(self.messages)
        self.assertEqual(self.errors, [])

    def current_mid(self) -> int:
        return self.db.current_mainline_id()


if __name__ == "__main__":
    unittest.main(verbosity=2)
