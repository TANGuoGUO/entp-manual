from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from database import Database  # noqa: E402
from demo_data import INTERNAL_DEMO_VERSION, populate_internal_demo  # noqa: E402


def build_demo_database(output: Path) -> dict[str, object]:
    """Build beside the target and replace it only after every check passes."""

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=".entp-internal-demo-",
        suffix=".db",
        dir=output.parent,
    )
    os.close(descriptor)
    candidate = Path(candidate_name)
    try:
        db = Database(candidate, seed_on_empty=False)
        try:
            populate_internal_demo(db)
            summary = {
                "demo_version": INTERNAL_DEMO_VERSION,
                "mainlines": int(db.row("SELECT COUNT(*) FROM mainlines")[0]),
                "tasks": int(db.row("SELECT COUNT(*) FROM tasks")[0]),
                "subtasks": int(db.row("SELECT COUNT(*) FROM tasks WHERE parent_task_id IS NOT NULL")[0]),
                "thoughts": int(db.row("SELECT COUNT(*) FROM thoughts")[0]),
                "today_entries": int(
                    db.row(
                        "SELECT COUNT(*) FROM daily_entries WHERE entry_date = ?",
                        (db.today_iso(),),
                    )[0]
                ),
                "integrity": str(db.row("PRAGMA integrity_check")[0]),
                "foreign_key_violations": len(db.rows("PRAGMA foreign_key_check")),
            }
        finally:
            db.close()
        if os.name == "nt":
            # Windows keeps the replacement file's ACL during os.replace().
            # Reset it while the candidate is beside the target, so the final
            # database inherits the workspace permissions and the desktop app
            # can open the database under the signed-in user account.
            subprocess.run(
                ["icacls", str(candidate), "/reset"],
                check=True,
                capture_output=True,
                text=True,
            )
        # os.replace is atomic on the same volume, so a failed build cannot
        # leave a half-written demo database at the requested path.
        os.replace(candidate, output)
    finally:
        # A validation or permission failure must not leave a candidate file.
        candidate.unlink(missing_ok=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="创建 ENTP 内部演示数据库")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = build_demo_database(args.output)
    except Exception as error:
        print(f"创建内部演示数据库失败：{error}", file=os.sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
