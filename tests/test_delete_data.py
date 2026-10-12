"""Deletion removes data for good; archiving only changes a status."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from database import Database
from markdown_store import MarkdownStore


class DeleteDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = Database(self.root / "delete.db", seed_on_empty=False)
        self.markdown = MarkdownStore(self.root / "markdown")
        self.mainline_id = self.db.create_mainline("删除测试主线", "用于验证删除")
        self.other_id = self.db.create_mainline("另一条主线", "兜底主线")

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    # ---------------------------------------------------------------- tasks

    def test_delete_task_removes_subtasks_and_ledger_rows(self) -> None:
        task_id = self.db.create_task(self.mainline_id, "父任务")
        child_id = self.db.create_task(self.mainline_id, "子任务", parent_task_id=task_id)
        self.db.plan_task_for_day(task_id, self.db.today_iso())
        self.db.set_task_completed(task_id, True)
        self.markdown.write_user_edited("task", task_id, "# 文档\n")

        report = self.db.delete_task(task_id)

        self.assertEqual(report["tasks"], 2)
        self.assertEqual(report["subtasks"], 1)
        self.assertIsNone(self.db.get_task(task_id))
        self.assertIsNone(self.db.get_task(child_id))
        self.assertEqual(
            self.db.rows("SELECT id FROM daily_entries WHERE task_id IN (?, ?)", (task_id, child_id)),
            [],
        )
        self.assertEqual(
            self.db.rows("SELECT id FROM task_events WHERE task_id IN (?, ?)", (task_id, child_id)),
            [],
        )
        self.assertEqual(
            self.db.rows(
                "SELECT id FROM task_execution_logs WHERE task_id IN (?, ?)",
                (task_id, child_id),
            ),
            [],
        )

        self.assertTrue(self.markdown.remove_document("task", task_id))
        self.assertFalse(self.markdown.path_for("task", task_id).exists())

    def test_delete_missing_task_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.delete_task(999999)

    def test_delete_task_keeps_other_tasks(self) -> None:
        keep_id = self.db.create_task(self.mainline_id, "保留的任务")
        remove_id = self.db.create_task(self.mainline_id, "删除的任务")
        self.db.delete_task(remove_id)
        self.assertIsNotNone(self.db.get_task(keep_id))
        self.assertIsNone(self.db.get_task(remove_id))

    # -------------------------------------------------------------- thoughts

    def test_delete_thought_removes_related_rows(self) -> None:
        thought_id = self.db.create_thought("一个灵感", mainline_id=self.mainline_id)
        task_id = self.db.create_task(self.mainline_id, "灵感产生的任务")
        self.db.link_task(thought_id, task_id)
        self.db.add_execution_log(
            thought_id,
            action="做了一点",
            result="结论",
            blocker="",
            next_step="继续",
            progress=10,
        )

        self.db.delete_thought(thought_id)

        self.assertIsNone(self.db.get_thought(thought_id))
        self.assertEqual(
            self.db.rows("SELECT thought_id FROM thought_task_links WHERE thought_id = ?", (thought_id,)),
            [],
        )
        self.assertEqual(
            self.db.rows("SELECT id FROM execution_logs WHERE thought_id = ?", (thought_id,)),
            [],
        )
        # 灵感删除不应该顺手删掉已经生成的任务。
        self.assertIsNotNone(self.db.get_task(task_id))

    def test_delete_missing_thought_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.delete_thought(999999)

    # ------------------------------------------------------------- mainlines

    def test_delete_mainline_moves_thoughts_to_inbox_and_switches(self) -> None:
        self.db.set_current_mainline(self.mainline_id)
        task_id = self.db.create_task(self.mainline_id, "主线任务")
        self.db.plan_task_for_day(task_id, self.db.today_iso())
        thought_id = self.db.create_thought("主线灵感", mainline_id=self.mainline_id)
        inbox_id = self.db.get_or_create_inbox()

        next_id = self.db.delete_mainline(self.mainline_id)

        self.assertIsNone(self.db.row("SELECT id FROM mainlines WHERE id = ?", (self.mainline_id,)))
        self.assertEqual(next_id, self.other_id)
        self.assertEqual(self.db.current_mainline_id(), self.other_id)
        self.assertEqual(int(self.db.get_thought(thought_id)["mainline_id"]), inbox_id)
        self.assertIsNone(self.db.get_task(task_id))
        self.assertEqual(
            self.db.rows("SELECT id FROM daily_entries WHERE mainline_id = ?", (self.mainline_id,)),
            [],
        )

    def test_delete_mainline_guards_inbox(self) -> None:
        inbox_id = self.db.get_or_create_inbox()
        with self.assertRaises(ValueError):
            self.db.delete_mainline(inbox_id)

    def test_delete_mainline_keeps_one_mainline_alive(self) -> None:
        with TemporaryDirectory() as root:
            db = Database(Path(root) / "single.db", seed_on_empty=False)
            only_id = db.create_mainline("唯一的主线")
            try:
                with self.assertRaises(ValueError):
                    db.delete_mainline(only_id)
                with self.assertRaises(ValueError):
                    db.delete_mainline(999999)
            finally:
                db.close()


    # ---------------------------------------------------------- daily ledger

    def test_delete_daily_entry_removes_events(self) -> None:
        task_id = self.db.create_task(self.mainline_id, "账本任务")
        entry_id = self.db._plan_task_for_day(task_id, self.db.today_iso())
        self.db.set_task_completed(task_id, True)

        self.db.delete_daily_entry(entry_id)

        self.assertIsNone(
            self.db.row("SELECT id FROM daily_entries WHERE id = ?", (entry_id,))
        )
        self.assertEqual(
            self.db.rows("SELECT id FROM task_events WHERE daily_entry_id = ?", (entry_id,)),
            [],
        )

    def test_delete_missing_daily_entry_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.db.delete_daily_entry(999999)


if __name__ == "__main__":
    unittest.main()
