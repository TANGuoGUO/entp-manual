from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import flet as ft

from database import Database
from flet_app import EntpFletApp


class CalendarUiSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "calendar-ui.db")
        self.app = EntpFletApp.__new__(EntpFletApp)
        self.app.db = self.db
        self.app.current_mid = self.db.current_mainline_id()
        self.app.today = date(2026, 2, 14)
        self.app._write_runtime_error = lambda *_: None
        self.errors: list[str] = []
        self.app._notify_error = self.errors.append

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_CA_04_every_clickable_mini_calendar_day_keeps_its_own_date(self) -> None:
        picked: list[date] = []
        self.app.open_completion_calendar = picked.append
        card = self.app._calendar_card(2026, 2)
        calendar_grid = card.content.content.controls[2]
        clickable = [cell for cell in calendar_grid.controls if cell.on_click is not None]

        for cell in clickable:
            cell.on_click(None)

        self.assertEqual(picked, [date(2026, 2, day) for day in range(1, 29)])
        self.assertEqual(self.errors, [])

    def test_ER_09_calendar_callback_error_is_reported_without_escaping(self) -> None:
        def fail(_event) -> None:
            raise ValueError("day is out of range for month")

        guarded = self.app._guard_ui_action(
            "日历测试异常",
            fail,
            "无法查看这个日期",
        )

        guarded(None)

        self.assertEqual(len(self.errors), 1)
        self.assertIn("可以继续使用", self.errors[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
