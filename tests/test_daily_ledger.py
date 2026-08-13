from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from database import Database
from markdown_store import MarkdownStore


def main() -> None:
    with TemporaryDirectory() as root:
        base = Path(root)
        db = Database(base / "daily-ledger.db")
        markdown = MarkdownStore(base / "markdown")
        current = db.current_mainline_id()
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        task_id = db.create_task(current, "原始任务标题", is_today=True)
        entry = db.row(
            "SELECT * FROM daily_entries WHERE task_id = ? AND entry_date = ?",
            (task_id, today),
        )
        assert entry is not None
        entry_id = int(entry["id"])

        db.update_task(task_id, title="后来修改的标题")
        snapshot = db.row("SELECT * FROM daily_entries WHERE id = ?", (entry_id,))
        assert snapshot["task_title_snapshot"] == "原始任务标题"

        db.set_daily_entry_completed(entry_id, True)
        assert db.completion_days(date.today().year, date.today().month)[today] == 1
        assert len(db.completed_entries_on(today)) == 1

        db.set_daily_entry_completed(entry_id, False)
        reopened = db.list_daily_entries(today)[-1]
        assert reopened["state"] == "planned"
        assert int(reopened["had_completion"]) == 1
        assert db.completion_days(date.today().year, date.today().month)[today] == 1
        assert len(db.completed_entries_on(today)) == 1
        assert int(db.daily_summary(today)["completed"] or 0) == 1

        overdue_id = db.create_task(current, "昨天没有完成的任务")
        old_entry_id = db.plan_task_for_day(overdue_id, yesterday, source="test")
        assert any(int(row["id"]) == old_entry_id for row in db.list_overdue_entries(today))
        assert db.carry_daily_entries((old_entry_id,), today) == 1
        assert db.carry_daily_entries((old_entry_id,), today) == 0
        old = db.row("SELECT state FROM daily_entries WHERE id = ?", (old_entry_id,))
        new = db.row(
            "SELECT state FROM daily_entries WHERE task_id = ? AND entry_date = ?",
            (overdue_id, today),
        )
        assert old["state"] == "carried"
        assert new["state"] == "planned"

        markdown.sync_all(db)
        daily_document = markdown.daily_path(today).read_text(encoding="utf-8")
        assert "原始任务标题" in daily_document
        assert "后来修改的标题" not in daily_document
        assert "已完成过 · 后续重新打开" in daily_document

        db.close()

    print("daily-ledger-snapshot-completion-reopen-carry-ok")


if __name__ == "__main__":
    main()
