from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from database import Database


class SubtaskDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.db = Database(Path(self.temporary.name) / "subtasks.db")
        self.mainline_id = self.db.current_mainline_id()

    def tearDown(self) -> None:
        self.db.close()
        self.temporary.cleanup()

    def test_create_subtask_keeps_daily_ledger_at_parent_level(self) -> None:
        parent_id = self.db.create_task(self.mainline_id, "父任务", is_today=True)
        before_stats = self.db.mainline_stats(self.mainline_id)

        child_id = self.db.create_task(
            self.mainline_id,
            "子任务",
            is_today=True,
            parent_task_id=parent_id,
        )

        child = self.db.get_task(child_id)
        self.assertEqual(int(child["parent_task_id"]), parent_id)
        self.assertFalse(bool(child["is_today"]))
        self.assertEqual([int(row["id"]) for row in self.db.list_subtasks(parent_id)], [child_id])
        after_stats = self.db.mainline_stats(self.mainline_id)
        self.assertEqual(int(after_stats["total"]), int(before_stats["total"]))
        daily_task_ids = {
            int(row["task_id"])
            for row in self.db.list_daily_entries(self.db.today_iso())
            if row["task_id"] is not None
        }
        self.assertIn(parent_id, daily_task_ids)
        self.assertNotIn(child_id, daily_task_ids)

    def test_only_one_level_and_same_mainline_are_allowed(self) -> None:
        parent_id = self.db.create_task(self.mainline_id, "父任务")
        child_id = self.db.create_task(
            self.mainline_id,
            "第一层",
            parent_task_id=parent_id,
        )
        with self.assertRaisesRegex(ValueError, "一层"):
            self.db.create_task(
                self.mainline_id,
                "第二层",
                parent_task_id=child_id,
            )

        other_mainline = self.db.create_mainline("另一条主线")
        with self.assertRaisesRegex(ValueError, "同一条主线"):
            self.db.create_task(
                other_mainline,
                "跨主线子任务",
                parent_task_id=parent_id,
            )

    def test_subtask_completion_does_not_auto_complete_parent(self) -> None:
        parent_id = self.db.create_task(self.mainline_id, "父任务", is_today=True)
        child_id = self.db.create_task(
            self.mainline_id,
            "子任务",
            parent_task_id=parent_id,
        )

        self.db.set_subtask_completed(child_id, True)

        self.assertEqual(str(self.db.get_task(child_id)["status"]), "完成")
        self.assertNotEqual(str(self.db.get_task(parent_id)["status"]), "完成")
        daily_task_ids = {
            int(row["task_id"])
            for row in self.db.list_daily_entries(self.db.today_iso())
            if row["task_id"] is not None
        }
        self.assertIn(parent_id, daily_task_ids)
        self.assertNotIn(child_id, daily_task_ids)

    def test_completing_parent_closes_children_and_reopening_child_reopens_parent(self) -> None:
        parent_id = self.db.create_task(self.mainline_id, "父任务", is_today=True)
        child_id = self.db.create_task(
            self.mainline_id,
            "子任务",
            parent_task_id=parent_id,
        )

        self.db.complete_task_with_subtasks(parent_id)
        self.assertEqual(str(self.db.get_task(parent_id)["status"]), "完成")
        self.assertEqual(str(self.db.get_task(child_id)["status"]), "完成")

        self.db.set_subtask_completed(child_id, False)
        self.assertNotEqual(str(self.db.get_task(parent_id)["status"]), "完成")
        self.assertEqual(str(self.db.get_task(child_id)["status"]), "待执行")

    def test_dragging_between_parent_and_child_preserves_today_visibility(self) -> None:
        target_parent = self.db.create_task(self.mainline_id, "目标父任务", is_today=True)
        movable = self.db.create_task(self.mainline_id, "可拖动任务", is_today=True)

        self.db.move_task_under(movable, target_parent)
        self.assertEqual(int(self.db.get_task(movable)["parent_task_id"]), target_parent)
        planned_after_indent = {
            int(row["task_id"])
            for row in self.db.list_daily_entries(self.db.today_iso())
            if str(row["state"]) == "planned" and row["task_id"] is not None
        }
        self.assertNotIn(movable, planned_after_indent)

        self.db.promote_subtask(movable)
        promoted = self.db.get_task(movable)
        self.assertIsNone(promoted["parent_task_id"])
        self.assertTrue(bool(promoted["is_today"]))
        planned_after_promote = {
            int(row["task_id"])
            for row in self.db.list_daily_entries(self.db.today_iso())
            if str(row["state"]) == "planned" and row["task_id"] is not None
        }
        self.assertIn(movable, planned_after_promote)

    def test_invalid_hierarchy_drops_never_change_existing_data(self) -> None:
        parent = self.db.create_task(self.mainline_id, "父任务")
        child = self.db.create_task(
            self.mainline_id, "子任务", parent_task_id=parent
        )
        other_mainline = self.db.create_mainline("另一条主线")
        other_parent = self.db.create_task(other_mainline, "另一父任务")

        before = {
            task_id: dict(self.db.get_task(task_id))
            for task_id in (parent, child, other_parent)
        }
        with self.assertRaisesRegex(ValueError, "自己"):
            self.db.move_task_under(parent, parent)
        with self.assertRaisesRegex(ValueError, "跨主线"):
            self.db.move_task_under(child, other_parent)
        with self.assertRaisesRegex(ValueError, "一层"):
            self.db.move_task_under(parent, child)

        after = {
            task_id: dict(self.db.get_task(task_id))
            for task_id in (parent, child, other_parent)
        }
        self.assertEqual(after, before)

    def test_repeated_drop_is_a_noop(self) -> None:
        parent = self.db.create_task(self.mainline_id, "父任务")
        child = self.db.create_task(
            self.mainline_id, "子任务", parent_task_id=parent
        )

        self.assertFalse(self.db.move_task_under(child, parent))
        self.assertFalse(self.db.promote_subtask(parent))
        self.assertEqual(int(self.db.get_task(child)["parent_task_id"]), parent)
        self.assertIsNone(self.db.get_task(parent)["parent_task_id"])

    def test_move_transaction_rolls_back_every_related_change_on_failure(self) -> None:
        parent = self.db.create_task(self.mainline_id, "父任务", is_today=True)
        movable = self.db.create_task(self.mainline_id, "可拖动任务", is_today=True)
        original_focus_update = self.db._ensure_focus_for_mainline

        def fail_focus_update(*_args, **_kwargs):
            raise RuntimeError("模拟事务中断")

        self.db._ensure_focus_for_mainline = fail_focus_update
        try:
            with self.assertRaisesRegex(RuntimeError, "模拟事务中断"):
                self.db.move_task_under(movable, parent)
        finally:
            self.db._ensure_focus_for_mainline = original_focus_update

        self.assertIsNone(self.db.get_task(movable)["parent_task_id"])
        planned = {
            int(row["task_id"])
            for row in self.db.list_daily_entries(self.db.today_iso())
            if row["task_id"] is not None and str(row["state"]) == "planned"
        }
        self.assertIn(movable, planned)


if __name__ == "__main__":
    unittest.main()
