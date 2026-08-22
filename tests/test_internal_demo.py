from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database
from demo_data import populate_internal_demo, validate_internal_demo


class InternalDemoTests(unittest.TestCase):
    def test_demo_data_is_varied_and_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "demo.db"
            db = Database(path, seed_on_empty=False)
            try:
                populate_internal_demo(db)
                self.assertEqual(validate_internal_demo(db), [])
                self.assertGreaterEqual(len(db.list_mainlines()), 5)
                self.assertGreaterEqual(len(db.list_tasks()), 25)
                self.assertGreaterEqual(
                    len(db.rows("SELECT id FROM tasks WHERE parent_task_id IS NOT NULL")),
                    6,
                )
                self.assertGreaterEqual(len(db.list_thoughts()), 10)
                self.assertTrue(db.list_daily_entries(db.today_iso()))
                self.assertTrue(
                    db.row("SELECT 1 FROM mainlines WHERE status = '已归档'")
                )
                demo_mainlines = db.rows(
                    "SELECT name, vision FROM mainlines WHERE name <> '收集箱'"
                )
                self.assertEqual(
                    {str(row["name"]) for row in demo_mainlines},
                    {
                        "摄影行业创业",
                        "把表达练成长期能力",
                        "建立能稳定养活自己的个人业务",
                        "成为能带团队把复杂项目推进到底的人",
                        "用照片把身边的人留下来",
                    },
                )
                self.assertTrue(all(str(row["vision"]).strip() for row in demo_mainlines))
                product_tasks = {
                    str(row["title"])
                    for row in db.rows(
                        """SELECT task.title FROM tasks task
                           JOIN mainlines mainline ON mainline.id = task.mainline_id
                           WHERE mainline.name = '摄影行业创业'"""
                    )
                }
                self.assertTrue(
                    {"调研客户", "影棚竞品调研", "摄影师合作"}
                    <= product_tasks
                )
                self.assertTrue(
                    {"布景师合作", "cos mcn", "coser账号", "自媒体获客", "宠物摄影"}
                    <= product_tasks
                )
                self.assertEqual(
                    int(
                        db.row(
                            """SELECT COUNT(*) FROM tasks task
                               JOIN mainlines mainline ON mainline.id = task.mainline_id
                               WHERE mainline.status = '已归档' AND task.is_focus = 1"""
                        )[0]
                    ),
                    0,
                )
            finally:
                db.close()

            # A real demo is opened by a fresh process; initialization must not
            # silently remove today flags or reshape any hierarchy.
            reopened = Database(path, seed_on_empty=False)
            try:
                self.assertEqual(validate_internal_demo(reopened), [])
                today_entries = reopened.list_daily_entries(reopened.today_iso())
                today_tasks = reopened.list_tasks(today_only=True)
                self.assertEqual(len(today_entries), len(today_tasks))
                self.assertEqual(len(today_entries), 8)
            finally:
                reopened.close()

    def test_demo_seed_refuses_to_mix_with_existing_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db = Database(Path(temporary) / "normal.db")
            try:
                with self.assertRaisesRegex(ValueError, "只能写入空数据库"):
                    populate_internal_demo(db)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
