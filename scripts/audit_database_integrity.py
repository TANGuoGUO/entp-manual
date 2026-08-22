from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import SCHEMA_VERSION, THOUGHT_STATUSES, TASK_STATUSES, Database  # noqa: E402


def _consistent_backup(source: Path, target: Path) -> None:
    """Use SQLite's online backup API so a running app cannot produce a torn copy."""

    source_uri = source.resolve().as_uri() + "?mode=ro"
    source_conn = sqlite3.connect(source_uri, uri=True, timeout=2.0)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        str(row[0])
        for row in conn.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
               ORDER BY name"""
        )
    ]
    return {
        table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }


def _existing_value_snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Capture existing business values to detect silent edits during migration."""

    snapshots: dict[str, list[tuple]] = {}
    for table in _row_counts(conn):
        columns = [
            str(row[1])
            for row in conn.execute(f'PRAGMA table_info("{table}")')
            # sort_order is the only migration-managed value for an existing row.
            if not (table == "tasks" and str(row[1]) == "sort_order")
        ]
        quoted = ", ".join(f'"{column}"' for column in columns)
        snapshots[table] = [
            tuple(row)
            for row in conn.execute(f'SELECT {quoted} FROM "{table}" ORDER BY rowid')
        ]
    return snapshots


def _count(db: Database, sql: str, params=()) -> int:
    row = db.row(sql, params)
    return int(row[0]) if row else 0


def audit(source: Path, snapshot: Path) -> dict:
    _consistent_backup(source, snapshot)
    raw = sqlite3.connect(snapshot)
    try:
        before_counts = _row_counts(raw)
        before_values = _existing_value_snapshot(raw)
    finally:
        raw.close()

    db = Database(snapshot)
    try:
        after_counts = _row_counts(db.conn)
        after_values = _existing_value_snapshot(db.conn)
        existing_values_preserved = before_values == after_values
        trigger_count = _count(
            db,
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type = 'trigger' AND name LIKE 'trg_tasks_parent_%'""",
        )
        parent_fk = any(
            str(row["from"]) == "parent_task_id"
            for row in db.rows("PRAGMA foreign_key_list(tasks)")
        )
        checks = {
            "foreign_key_violations": len(db.rows("PRAGMA foreign_key_check")),
            "orphan_subtasks": _count(
                db,
                """SELECT COUNT(*) FROM tasks child
                   LEFT JOIN tasks parent ON parent.id = child.parent_task_id
                   WHERE child.parent_task_id IS NOT NULL AND parent.id IS NULL""",
            ),
            "self_parent_tasks": _count(
                db, "SELECT COUNT(*) FROM tasks WHERE parent_task_id = id"
            ),
            "cross_mainline_subtasks": _count(
                db,
                """SELECT COUNT(*) FROM tasks child
                   JOIN tasks parent ON parent.id = child.parent_task_id
                   WHERE child.mainline_id <> parent.mainline_id""",
            ),
            "nested_subtasks": _count(
                db,
                """SELECT COUNT(*) FROM tasks child
                   JOIN tasks parent ON parent.id = child.parent_task_id
                   WHERE parent.parent_task_id IS NOT NULL""",
            ),
            "subtasks_marked_today_or_focus": _count(
                db,
                """SELECT COUNT(*) FROM tasks
                   WHERE parent_task_id IS NOT NULL AND (is_today <> 0 OR is_focus <> 0)""",
            ),
            "subtasks_with_daily_entries": _count(
                db,
                """SELECT COUNT(*) FROM daily_entries de
                   JOIN tasks t ON t.id = de.task_id
                   WHERE t.parent_task_id IS NOT NULL""",
            ),
            "unfinished_children_of_completed_parents": _count(
                db,
                """SELECT COUNT(*) FROM tasks child
                   JOIN tasks parent ON parent.id = child.parent_task_id
                   WHERE parent.status = '完成' AND child.status <> '完成'""",
            ),
            "duplicate_active_focus_mainlines": _count(
                db,
                """SELECT COUNT(*) FROM (
                       SELECT mainline_id FROM tasks
                       WHERE is_focus = 1 AND status <> '完成'
                       GROUP BY mainline_id HAVING COUNT(*) > 1
                   )""",
            ),
            "blank_mainline_names": _count(
                db, "SELECT COUNT(*) FROM mainlines WHERE TRIM(name) = ''"
            ),
            "blank_task_titles": _count(
                db, "SELECT COUNT(*) FROM tasks WHERE TRIM(title) = ''"
            ),
            "blank_thought_titles": _count(
                db, "SELECT COUNT(*) FROM thoughts WHERE TRIM(title) = ''"
            ),
            "invalid_task_statuses": _count(
                db,
                f"SELECT COUNT(*) FROM tasks WHERE status NOT IN ({','.join('?' for _ in TASK_STATUSES)})",
                TASK_STATUSES,
            ),
            "invalid_thought_statuses": _count(
                db,
                f"SELECT COUNT(*) FROM thoughts WHERE status NOT IN ({','.join('?' for _ in THOUGHT_STATUSES)})",
                THOUGHT_STATUSES,
            ),
            "invalid_daily_dates": _count(
                db,
                """SELECT COUNT(*) FROM daily_entries
                   WHERE entry_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'""",
            ),
        }
        current_setting = db.get_setting("current_mainline_id")
        invalid_current_mainline = bool(
            current_setting
            and (
                not current_setting.isdigit()
                or not db.row("SELECT 1 FROM mainlines WHERE id = ?", (int(current_setting),))
            )
        )
        row_count_changes = {
            table: {"before": before_counts.get(table, 0), "after": count}
            for table, count in after_counts.items()
            if before_counts.get(table, 0) != count
        }
        integrity_check = str(db.row("PRAGMA integrity_check")[0])
        quick_check = str(db.row("PRAGMA quick_check")[0])
        schema_version = int(db.row("PRAGMA user_version")[0])
        critical_failures = {
            name: count for name, count in checks.items() if count != 0
        }
        passed = bool(
            integrity_check == "ok"
            and quick_check == "ok"
            and schema_version == SCHEMA_VERSION
            and not critical_failures
            and not invalid_current_mainline
            and not row_count_changes
            and existing_values_preserved
            and (parent_fk or trigger_count >= 4)
        )
        return {
            "passed": passed,
            "source_database": str(source.resolve()),
            "snapshot_database": str(snapshot.resolve()),
            "schema_version": schema_version,
            "integrity_check": integrity_check,
            "quick_check": quick_check,
            "parent_foreign_key": parent_fk,
            "hierarchy_guard_triggers": trigger_count,
            "row_counts": after_counts,
            "row_count_changes_during_open": row_count_changes,
            "existing_values_preserved": existing_values_preserved,
            "invalid_current_mainline": invalid_current_mainline,
            "checks": checks,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="在一致性副本上审计 ENTP 数据库")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="entp-integrity-audit-") as temporary:
            snapshot = Path(temporary) / "audit-copy.db"
            result = audit(args.db, snapshot)
            # 临时副本会被删除，报告不暴露一个已经失效的路径。
            result["snapshot_database"] = "temporary SQLite online-backup copy"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    except Exception as error:
        print(f"数据库完整性审计失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
