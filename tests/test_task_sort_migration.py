from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database


class TaskSortMigrationTests(unittest.TestCase):
    def test_new_zero_sort_order_is_not_rewritten_on_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sort.db"
            db = Database(path, seed_on_empty=False)
            try:
                mainline_id = db.create_mainline("长期主线")
                db.conn.execute(
                    """INSERT INTO tasks(mainline_id, title, sort_order)
                       VALUES (?, '排在零位', 0)""",
                    (mainline_id,),
                )
                db.conn.commit()
                self.assertEqual(
                    db.get_setting("task_sort_order_migration_version"), "1"
                )
            finally:
                db.close()

            reopened = Database(path, seed_on_empty=False)
            try:
                self.assertEqual(
                    int(
                        reopened.row(
                            "SELECT sort_order FROM tasks WHERE title = '排在零位'"
                        )[0]
                    ),
                    0,
                )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
