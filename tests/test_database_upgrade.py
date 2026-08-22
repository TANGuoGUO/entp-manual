from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from database import SCHEMA_VERSION, Database


LEGACY_SCHEMA = """
CREATE TABLE mainlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    vision TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#1976E9',
    status TEXT NOT NULL DEFAULT '进行中',
    focus_until TEXT NOT NULL DEFAULT '',
    review_mode TEXT NOT NULL DEFAULT '按需复盘',
    next_review_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mainline_id INTEGER NOT NULL REFERENCES mainlines(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '待执行',
    priority TEXT NOT NULL DEFAULT '普通',
    due_date TEXT NOT NULL DEFAULT '',
    is_today INTEGER NOT NULL DEFAULT 0,
    is_focus INTEGER NOT NULL DEFAULT 0,
    next_action TEXT NOT NULL DEFAULT '',
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class DatabaseUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _legacy_path(self, *, beta_hierarchy_columns: bool = False) -> Path:
        path = Path(self.temporary.name) / (
            "beta.db" if beta_hierarchy_columns else "legacy.db"
        )
        schema = LEGACY_SCHEMA
        if beta_hierarchy_columns:
            # 2.1.8 的早期测试构建曾把父任务列作为普通整数列加入。
            schema = schema.replace(
                "    title TEXT NOT NULL,",
                "    parent_task_id INTEGER DEFAULT NULL,\n"
                "    title TEXT NOT NULL,",
            ).replace(
                "    progress INTEGER NOT NULL DEFAULT 0,",
                "    progress INTEGER NOT NULL DEFAULT 0,\n"
                "    sort_order INTEGER NOT NULL DEFAULT 0,",
            )
        conn = sqlite3.connect(path)
        conn.executescript(schema)
        conn.execute(
            "INSERT INTO mainlines(id, name, vision, color) VALUES (1, ?, ?, ?)",
            ("旧版主线", "保留中文、引号'和换行\n正文", "#123456"),
        )
        conn.execute(
            """INSERT INTO tasks(
                   id, mainline_id, title, description, status, priority,
                   due_date, is_today, is_focus, next_action, progress
               ) VALUES (10, 1, ?, ?, '执行中', '重要', '2026-08-31', 0, 1, ?, 35)""",
            ("旧任务甲", "Markdown **正文**", "继续验证"),
        )
        conn.execute(
            """INSERT INTO tasks(
                   id, mainline_id, title, description, status, priority,
                   due_date, is_today, is_focus, next_action, progress
               ) VALUES (20, 1, ?, '', '待执行', '普通', '', 0, 0, '', 0)""",
            ("旧任务乙",),
        )
        conn.commit()
        conn.close()
        return path

    def test_official_legacy_schema_upgrades_without_losing_fields(self) -> None:
        path = self._legacy_path()
        db = Database(path)
        try:
            task = db.get_task(10)
            self.assertEqual(str(task["title"]), "旧任务甲")
            self.assertEqual(str(task["description"]), "Markdown **正文**")
            self.assertEqual(str(task["status"]), "执行中")
            self.assertEqual(str(task["priority"]), "重要")
            self.assertEqual(str(task["due_date"]), "2026-08-31")
            self.assertEqual(str(task["next_action"]), "继续验证")
            self.assertEqual(int(task["progress"]), 35)
            self.assertIsNone(task["parent_task_id"])
            self.assertEqual(int(task["sort_order"]), -10)

            columns = {
                str(row["name"]): row
                for row in db.rows("PRAGMA table_info(tasks)")
            }
            self.assertIn("parent_task_id", columns)
            self.assertIn("sort_order", columns)
            foreign_keys = db.rows("PRAGMA foreign_key_list(tasks)")
            self.assertTrue(
                any(str(row["from"]) == "parent_task_id" for row in foreign_keys)
            )
            self.assertEqual(int(db.row("PRAGMA user_version")[0]), SCHEMA_VERSION)
            self.assertEqual(str(db.row("PRAGMA integrity_check")[0]), "ok")
            self.assertEqual(db.rows("PRAGMA foreign_key_check"), [])
        finally:
            db.close()

        # 重复启动不能再次改写旧任务顺序或业务字段。
        reopened = Database(path)
        try:
            self.assertEqual(int(reopened.get_task(10)["sort_order"]), -10)
            self.assertEqual(int(reopened.get_task(20)["sort_order"]), -20)
            self.assertEqual(str(reopened.get_task(10)["title"]), "旧任务甲")
        finally:
            reopened.close()

    def test_early_beta_plain_parent_column_gets_trigger_guards(self) -> None:
        path = self._legacy_path(beta_hierarchy_columns=True)
        db = Database(path)
        try:
            child_id = db.create_task(1, "测试子任务", parent_task_id=10)
            other_mainline = db.create_mainline("另一条主线")
            other_parent = db.create_task(other_mainline, "另一父任务")

            with self.assertRaisesRegex(sqlite3.IntegrityError, "invalid task parent"):
                db.conn.execute(
                    "UPDATE tasks SET parent_task_id = ? WHERE id = ?",
                    (other_parent, child_id),
                )
            db.conn.rollback()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "today or focus"):
                db.conn.execute("UPDATE tasks SET is_today = 1 WHERE id = ?", (child_id,))
            db.conn.rollback()

            # 没有原生自引用外键的早期测试库也能得到 SET NULL 删除语义。
            db.conn.execute("DELETE FROM tasks WHERE id = 10")
            db.conn.commit()
            self.assertIsNone(db.get_task(child_id)["parent_task_id"])
            self.assertEqual(str(db.row("PRAGMA integrity_check")[0]), "ok")
            self.assertEqual(db.rows("PRAGMA foreign_key_check"), [])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
