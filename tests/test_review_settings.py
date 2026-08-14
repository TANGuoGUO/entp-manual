from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import flet as ft

from database import Database
from flet_app import EntpFletApp, pill


class ReviewSettingsTests(unittest.TestCase):
    def test_RS_01_pill_exposes_click_handler(self) -> None:
        calls: list[str] = []
        control = pill(
            "按需复盘",
            icon=ft.Icons.TUNE_ROUNDED,
            on_click=lambda _: calls.append("opened"),
        )

        self.assertIsNotNone(control.on_click)
        self.assertTrue(control.ink)
        control.on_click(None)
        self.assertEqual(calls, ["opened"])

    def test_RS_02_dialog_saves_optional_review_settings(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "review-settings.db")
            app = EntpFletApp.__new__(EntpFletApp)
            app.db = database
            dialogs: list[ft.AlertDialog] = []
            updates: list[bool] = []
            app.page = SimpleNamespace(
                show_dialog=dialogs.append,
                update=lambda: updates.append(True),
            )
            app._sync_markdown = lambda *args, **kwargs: True
            app._close_dialog = lambda: updates.append(True)
            app.refresh_current_sections = lambda *args, **kwargs: updates.append(True)
            app._notify_error = self.fail

            mainline_id = database.current_mainline_id()
            app.open_review_settings_dialog(mainline_id)

            self.assertEqual(len(dialogs), 1)
            dialog = dialogs[0]
            focus_until = dialog.content.controls[2]
            review_mode = dialog.content.controls[4]
            next_review_date = dialog.content.controls[6]
            focus_until.value = "2026-08-31"
            review_mode.value = "每周提醒"
            next_review_date.value = "2026-09-07"
            dialog.actions[1].on_click(None)

            saved = next(
                row for row in database.list_mainlines() if int(row["id"]) == mainline_id
            )
            self.assertEqual(saved["focus_until"], "2026-08-31")
            self.assertEqual(saved["review_mode"], "每周提醒")
            self.assertEqual(saved["next_review_date"], "2026-09-07")
            self.assertGreaterEqual(len(updates), 2)
            database.close()

    def test_RS_03_invalid_date_is_reported_without_writing(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "review-invalid.db")
            app = EntpFletApp.__new__(EntpFletApp)
            app.db = database
            dialogs: list[ft.AlertDialog] = []
            updates: list[bool] = []
            app.page = SimpleNamespace(
                show_dialog=dialogs.append,
                update=lambda: updates.append(True),
            )
            app._sync_markdown = lambda *args, **kwargs: True
            app._close_dialog = lambda: self.fail("invalid input must keep the dialog open")
            app.refresh_current_sections = lambda *args, **kwargs: self.fail(
                "invalid input must not refresh the workspace"
            )
            app._notify_error = self.fail

            mainline_id = database.current_mainline_id()
            before = next(
                row for row in database.list_mainlines() if int(row["id"]) == mainline_id
            )
            app.open_review_settings_dialog(mainline_id)
            dialog = dialogs[0]
            focus_until = dialog.content.controls[2]
            focus_until.value = "2026-02-30"
            dialog.actions[1].on_click(None)

            after = next(
                row for row in database.list_mainlines() if int(row["id"]) == mainline_id
            )
            self.assertIsNotNone(focus_until.error)
            self.assertEqual(after["focus_until"], before["focus_until"])
            self.assertEqual(updates, [True])
            database.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
