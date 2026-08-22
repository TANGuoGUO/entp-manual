from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from database import Database


class DailyLedgerMigrationTests(unittest.TestCase):
    def test_legacy_today_migration_runs_once_and_never_uses_future_due_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy-today.db"
            db = Database(path, seed_on_empty=False)
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            today = date.today().isoformat()
            try:
                db.conn.execute(
                    "INSERT INTO mainlines(name, vision) VALUES ('测试主线', '')"
                )
                mainline_id = int(db.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                db.conn.execute(
                    """INSERT INTO tasks(mainline_id, title, status, due_date, is_today)
                       VALUES (?, '已有今日账本', '今日', ?, 1)""",
                    (mainline_id, tomorrow),
                )
                existing_task = int(db.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                db.conn.execute(
                    """INSERT INTO daily_entries(
                           entry_date, task_id, task_title_snapshot, mainline_id,
                           mainline_name_snapshot, state, source, created_at, updated_at
                       ) VALUES (?, ?, '已有今日账本', ?, '测试主线', 'planned',
                                 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (today, existing_task, mainline_id),
                )
                db.conn.execute(
                    """INSERT INTO tasks(mainline_id, title, status, due_date, is_today)
                       VALUES (?, '只有旧标记', '今日', ?, 1)""",
                    (mainline_id, tomorrow),
                )
                db.conn.execute(
                    "DELETE FROM app_settings WHERE key = 'daily_ledger_migration_version'"
                )
                db.conn.commit()
            finally:
                db.close()

            reopened = Database(path, seed_on_empty=False)
            try:
                rows = reopened.rows(
                    """SELECT entry_date, source FROM daily_entries
                       ORDER BY id"""
                )
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row["entry_date"] == today for row in rows))
                self.assertEqual(
                    reopened.get_setting("daily_ledger_migration_version"), "1"
                )
            finally:
                reopened.close()

            second_open = Database(path, seed_on_empty=False)
            try:
                self.assertEqual(
                    int(second_open.row("SELECT COUNT(*) FROM daily_entries")[0]),
                    2,
                )
            finally:
                second_open.close()


if __name__ == "__main__":
    unittest.main()
