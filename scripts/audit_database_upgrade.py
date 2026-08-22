from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import SCHEMA_VERSION, Database  # noqa: E402


DEFAULT_REFS = (
    "v2.0.0",
    "v2.0.1",
    "v2.0.2",
    "v2.1.0",
    "v2.1.1",
    "v2.1.2",
    "v2.1.3",
    "v2.1.5",
)


def _legacy_database_class(ref: str):
    """Load the exact historical Database class without modifying the worktree."""

    source = subprocess.check_output(
        ["git", "show", f"{ref}:database.py"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    namespace: dict[str, Any] = {"__name__": f"legacy_database_{ref.replace('.', '_')}"}
    exec(compile(source, f"{ref}:database.py", "exec"), namespace)
    return namespace["Database"]


def _snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    tables = [
        str(row["name"])
        for row in conn.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
               ORDER BY name"""
        )
    ]
    result: dict[str, Any] = {}
    for table in tables:
        columns = [
            str(row["name"])
            for row in conn.execute(f'PRAGMA table_info("{table}")')
        ]
        rows = [
            {column: row[column] for column in columns}
            for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
        ]
        result[table] = {"columns": columns, "rows": rows}
    return result


def _shared_data_equal(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Require every legacy row while allowing migration-generated rows/columns."""

    for table, old_table in before.items():
        if table not in after:
            return False
        columns = old_table["columns"]
        unmatched_new_rows = [
            {column: row[column] for column in columns}
            for row in after[table]["rows"]
        ]
        # Migrations may legitimately add ledger entries or version markers to
        # an existing table.  They still must preserve every pre-upgrade row,
        # including duplicate rows, so consume matches one by one.
        for old_row in old_table["rows"]:
            try:
                index = unmatched_new_rows.index(old_row)
            except ValueError:
                return False
            unmatched_new_rows.pop(index)
    return True


def _populate_legacy_workspace(db) -> None:
    mainline_id = db.create_mainline("升级兼容主线", "中文、Markdown 与换行\n都应保留")
    task_id = db.create_task(
        mainline_id,
        "升级前任务",
        description="正文 **不会丢失**",
        priority="重要",
        is_today=True,
        next_action="继续检查",
    )
    db.add_task_execution_log(
        task_id,
        action="执行兼容测试",
        result="旧版记录",
        next_action="升级",
    )
    thought_id = db.create_thought(
        "升级前灵感",
        raw_content="灵感正文",
        mainline_id=mainline_id,
    )
    second_thought = db.create_thought("关联灵感", mainline_id=mainline_id)
    db.link_task(thought_id, task_id)
    db.link_thought(thought_id, second_thought, "启发")
    db.add_execution_log(
        thought_id,
        action="验证旧灵感",
        result="可读取",
        blocker="",
        next_step="继续",
        progress=30,
    )
    db.set_setting("upgrade_audit_marker", "保留设置")


def audit_ref(ref: str, root: Path) -> dict[str, Any]:
    path = root / f"{ref.replace('.', '_')}.db"
    legacy_class = _legacy_database_class(ref)
    legacy = legacy_class(path)
    try:
        _populate_legacy_workspace(legacy)
    finally:
        legacy.close()

    before_conn = sqlite3.connect(path)
    try:
        before = _snapshot(before_conn)
    finally:
        before_conn.close()

    upgraded = Database(path)
    try:
        after = _snapshot(upgraded.conn)
        shared_data_preserved = _shared_data_equal(before, after)
        integrity = str(upgraded.row("PRAGMA integrity_check")[0])
        foreign_key_violations = len(upgraded.rows("PRAGMA foreign_key_check"))
        schema_version = int(upgraded.row("PRAGMA user_version")[0])
        columns = {str(row["name"]) for row in upgraded.rows("PRAGMA table_info(tasks)")}
        parent_fk = any(
            str(row["from"]) == "parent_task_id"
            for row in upgraded.rows("PRAGMA foreign_key_list(tasks)")
        )

        parent_id = upgraded.create_task(upgraded.current_mainline_id(), "升级后父任务")
        child_id = upgraded.create_task(
            upgraded.current_mainline_id(),
            "升级后子任务",
            parent_task_id=parent_id,
        )
        hierarchy_roundtrip = bool(
            int(upgraded.get_task(child_id)["parent_task_id"]) == parent_id
            and upgraded.promote_subtask(child_id)
            and upgraded.get_task(child_id)["parent_task_id"] is None
            and upgraded.move_task_under(child_id, parent_id)
            and int(upgraded.get_task(child_id)["parent_task_id"]) == parent_id
        )
    finally:
        upgraded.close()

    reopened = Database(path)
    try:
        repeated_open_ok = bool(
            str(reopened.row("PRAGMA integrity_check")[0]) == "ok"
            and not reopened.rows("PRAGMA foreign_key_check")
            and int(reopened.row("PRAGMA user_version")[0]) == SCHEMA_VERSION
        )
    finally:
        reopened.close()

    passed = all(
        (
            shared_data_preserved,
            integrity == "ok",
            foreign_key_violations == 0,
            schema_version == SCHEMA_VERSION,
            {"parent_task_id", "sort_order"}.issubset(columns),
            parent_fk,
            hierarchy_roundtrip,
            repeated_open_ok,
        )
    )
    return {
        "legacy_ref": ref,
        "passed": passed,
        "legacy_tables": len(before),
        "legacy_rows": sum(len(value["rows"]) for value in before.values()),
        "shared_data_preserved": shared_data_preserved,
        "integrity_check": integrity,
        "foreign_key_violations": foreign_key_violations,
        "schema_version": schema_version,
        "parent_foreign_key": parent_fk,
        "hierarchy_roundtrip": hierarchy_roundtrip,
        "repeated_open_ok": repeated_open_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="审计历史版本数据库升级到当前结构")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--refs", nargs="*", default=list(DEFAULT_REFS))
    args = parser.parse_args()

    try:
        with tempfile.TemporaryDirectory(prefix="entp-upgrade-audit-") as temporary:
            root = Path(temporary)
            results = [audit_ref(ref, root) for ref in args.refs]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "refs_tested": len(results),
            "passed": all(item["passed"] for item in results),
            "results": results,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["passed"] else 1
    except Exception as error:
        # CI 和人工运行都需要明确失败，而不是留下半份“看似成功”的报告。
        print(f"数据库升级审计失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
