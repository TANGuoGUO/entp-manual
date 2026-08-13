from pathlib import Path
from tempfile import TemporaryDirectory

from database import Database


def main() -> None:
    with TemporaryDirectory() as root:
        path = Path(root) / "qa-archive.db"
        db = Database(path)
        ids = [int(row["id"]) for row in db.list_mainlines() if row["name"] != "收集箱"]
        inbox = next(
            (int(row["id"]) for row in db.list_mainlines() if row["name"] == "收集箱"),
            None,
        )
        current = db.current_mainline_id()
        other = next(mainline_id for mainline_id in ids if mainline_id != current)

        db.archive_mainline(other)
        assert db.row("SELECT status FROM mainlines WHERE id = ?", (other,))["status"] == "已归档"
        db.restore_mainline(other)
        assert db.row("SELECT status FROM mainlines WHERE id = ?", (other,))["status"] == "进行中"

        replacement = db.archive_mainline(current)
        assert replacement == other
        assert db.current_mainline_id() == other

        try:
            db.archive_mainline(other)
        except ValueError:
            pass
        else:
            raise AssertionError("the only active mainline must not be archived")

        if inbox is not None:
            try:
                db.archive_mainline(inbox)
            except ValueError:
                pass
            else:
                raise AssertionError("the system inbox must not be archived as a mainline")

        db.close()
        print("archive-restore-switch-guard-ok", current, other)


if __name__ == "__main__":
    main()
