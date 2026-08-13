from __future__ import annotations

import asyncio
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import flet as ft

from database import Database
from flet_app import EntpFletApp


class UiExceptionBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = EntpFletApp.__new__(EntpFletApp)
        self.errors: list[tuple[str, str]] = []
        self.messages: list[str] = []
        self.app._write_runtime_error = (
            lambda context, details: self.errors.append((context, details))
        )
        self.app._notify_error = self.messages.append

    def test_ER_10_nested_sync_handlers_are_automatically_isolated(self) -> None:
        def fail(_event) -> None:
            raise ValueError("任务标题不能为空")

        field = ft.TextField(label="任务标题", on_submit=fail)
        button = ft.FilledButton("保存任务", on_click=fail)
        root = ft.Column([ft.Container(field), button])

        self.app._protect_control_tree(root)
        field.on_submit(None)
        button.on_click(None)

        self.assertEqual(len(self.errors), 2)
        self.assertEqual(self.messages, ["任务标题不能为空", "任务标题不能为空"])

    def test_ER_11_async_handlers_are_awaited_and_isolated(self) -> None:
        async def fail(_event) -> None:
            await asyncio.sleep(0)
            raise OSError("disk unavailable")

        button = ft.FilledButton("导出全部", on_click=fail)
        self.app._protect_control_tree(button)

        asyncio.run(button.on_click(None))

        self.assertEqual(len(self.errors), 1)
        self.assertIn("文件操作没有完成", self.messages[0])

    def test_ER_12_repeated_updates_do_not_stack_boundaries(self) -> None:
        button = ft.FilledButton("切换主线", on_click=lambda _: None)
        self.app._protect_control_tree(button)
        first = button.on_click
        self.app._protect_control_tree(button)

        self.assertIs(button.on_click, first)
        self.assertTrue(getattr(button.on_click, "_entp_exception_boundary", False))

    def test_ER_13_page_update_protects_new_dynamic_controls(self) -> None:
        button = ft.FilledButton(
            "动态按钮",
            on_click=lambda _: (_ for _ in ()).throw(RuntimeError("dynamic failure")),
        )
        updates: list[tuple] = []
        self.app.page = SimpleNamespace(controls=[ft.Column([button])], overlay=[])
        self.app._original_page_update = lambda *controls: updates.append(controls)

        self.app._protected_page_update()
        button.on_click(None)

        self.assertEqual(updates, [()])
        self.assertEqual(len(self.errors), 1)
        total, unprotected = self.app.interaction_boundary_audit()
        self.assertEqual(total, 1)
        self.assertEqual(unprotected, [])

    def test_ER_14_error_messages_distinguish_common_boundaries(self) -> None:
        self.assertIn(
            "暂时被占用",
            self.app._interaction_error_message(sqlite3.OperationalError("database is locked")),
        )
        self.assertIn(
            "访问权限",
            self.app._interaction_error_message(PermissionError("denied")),
        )
        self.assertIn(
            "继续使用",
            self.app._interaction_error_message(RuntimeError("unexpected")),
        )

    def test_ER_15_failed_callback_rolls_back_uncommitted_database_changes(self) -> None:
        with TemporaryDirectory() as temporary:
            self.app.db = Database(Path(temporary) / "rollback.db")
            before = len(self.app.db.list_mainlines())

            def partial_write_then_fail(_event) -> None:
                self.app.db.conn.execute(
                    "INSERT INTO mainlines(name, vision) VALUES (?, ?)",
                    ("不应泄漏的半成品", ""),
                )
                raise RuntimeError("forced failure after first SQL")

            guarded = self.app._wrap_event_handler(
                partial_write_then_fail,
                "事务回滚测试",
            )
            guarded(None)

            self.assertEqual(len(self.app.db.list_mainlines()), before)
            self.assertFalse(self.app.db.conn.in_transaction)
            self.app.db.close()

    def test_ER_16_failed_callback_restores_navigation_state(self) -> None:
        self.app.active_index = self.app.NAV_CURRENT
        self.app.selected_task_id = 7
        self.app.today_priority_sort = False
        self.app.today_collapsed = {"已完成": False}
        self.app.rail = SimpleNamespace(selected_index=self.app.NAV_CURRENT)

        def mutate_state_then_fail(_event) -> None:
            self.app.active_index = self.app.NAV_CALENDAR
            self.app.selected_task_id = 99
            self.app.today_priority_sort = True
            self.app.today_collapsed["已完成"] = True
            self.app.rail.selected_index = self.app.NAV_CALENDAR
            raise RuntimeError("failed after state mutation")

        guarded = self.app._wrap_event_handler(mutate_state_then_fail, "状态恢复测试")
        guarded(None)

        self.assertEqual(self.app.active_index, self.app.NAV_CURRENT)
        self.assertEqual(self.app.selected_task_id, 7)
        self.assertFalse(self.app.today_priority_sort)
        self.assertEqual(self.app.today_collapsed, {"已完成": False})
        self.assertEqual(self.app.rail.selected_index, self.app.NAV_CURRENT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
