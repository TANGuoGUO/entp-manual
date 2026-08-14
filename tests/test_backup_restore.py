from __future__ import annotations

import asyncio
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import backup_service
import flet_app
from backup_service import BackupError, export_workspace, inspect_backup, restore_workspace
from database import Database
from markdown_store import MarkdownStore


class BackupRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.db_path = self.base / "entp.db"
        self.markdown_root = self.base / "markdown"
        self.archive = self.base / "workspace.entp.zip"
        self.db = Database(self.db_path)
        self.markdown = MarkdownStore(self.markdown_root)

    def tearDown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
        self.temp.cleanup()

    def _rewrite_archive(self, mutate) -> Path:
        target = self.base / f"mutated-{len(list(self.base.glob('mutated-*.zip')))}.zip"
        with zipfile.ZipFile(self.archive, "r") as source, zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            entries = {info.filename: source.read(info) for info in source.infolist()}
            mutate(entries)
            for name, content in entries.items():
                destination.writestr(name, content)
        return target

    def test_BU_01_02_export_contains_database_markdown_and_manifest(self) -> None:
        mainline = self.db.current_mainline_id()
        task = self.db.create_task(mainline, "必须被完整导出的任务", is_today=True)
        self.markdown.sync_all(self.db)
        task_path = self.markdown.path_for("task", task)
        task_path.write_text(
            task_path.read_text(encoding="utf-8") + "\n用户自由记录：导出我。\n",
            encoding="utf-8",
        )
        source_image = self.base / "backup-image.png"
        source_image.write_bytes(b"\x89PNG\r\n\x1a\nbackup-image")
        attached_image, relative_image = self.markdown.add_image("task", task, source_image)
        task_path.write_text(
            task_path.read_text(encoding="utf-8") + f"\n![备份图片]({relative_image})\n",
            encoding="utf-8",
        )

        summary = export_workspace(self.db, self.markdown_root, self.archive)
        self.assertGreater(summary.table_counts["tasks"], 0)
        self.assertGreater(summary.markdown_files, 0)
        with zipfile.ZipFile(self.archive, "r") as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("database/entp.db", names)
            self.assertIn(f"markdown/任务/T{task:04d}.md", names)
            self.assertIn(
                f"markdown/{attached_image.relative_to(self.markdown_root).as_posix()}",
                names,
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["format"], "entp-workspace-backup")
            self.assertEqual(manifest["table_counts"], summary.table_counts)

    def test_BU_03_round_trip_restores_everything_and_removes_later_state(self) -> None:
        mainline = self.db.current_mainline_id()
        task = self.db.create_task(mainline, "备份时存在", is_today=True)
        thought = self.db.create_thought("备份中的灵感")
        self.db.link_task(thought, task)
        self.markdown.sync_all(self.db)
        thought_path = self.markdown.path_for("thought", thought)
        thought_path.write_text(
            thought_path.read_text(encoding="utf-8") + "\n只属于备份的自由正文。\n",
            encoding="utf-8",
        )
        export_workspace(self.db, self.markdown_root, self.archive)

        later_task = self.db.create_task(mainline, "备份之后才创建")
        self.markdown.sync_all(self.db)
        self.db.close()
        restore_workspace(self.archive, self.db_path, self.markdown_root)
        self.db = Database(self.db_path)

        titles = {str(row["title"]) for row in self.db.list_tasks()}
        self.assertIn("备份时存在", titles)
        self.assertNotIn("备份之后才创建", titles)
        self.assertIsNone(self.db.get_task(later_task))
        self.assertIn("只属于备份的自由正文。", thought_path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.db.linked_tasks(thought)), 1)

    def test_BU_04_corrupted_payload_is_rejected_without_touching_current_data(self) -> None:
        self.markdown.sync_all(self.db)
        export_workspace(self.db, self.markdown_root, self.archive)

        def corrupt(entries: dict[str, bytes]) -> None:
            entries["database/entp.db"] = entries["database/entp.db"][:-32] + b"broken-backup-payload"

        broken = self._rewrite_archive(corrupt)
        before = self.db_path.read_bytes()
        with self.assertRaisesRegex(BackupError, "校验失败"):
            inspect_backup(broken)
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_BU_05_future_version_and_missing_manifest_are_rejected(self) -> None:
        self.markdown.sync_all(self.db)
        export_workspace(self.db, self.markdown_root, self.archive)

        def future(entries: dict[str, bytes]) -> None:
            manifest = json.loads(entries["manifest.json"])
            manifest["format_version"] = 999
            entries["manifest.json"] = json.dumps(manifest).encode("utf-8")

        future_archive = self._rewrite_archive(future)
        with self.assertRaisesRegex(BackupError, "更高版本"):
            inspect_backup(future_archive)

        missing = self._rewrite_archive(lambda entries: entries.pop("manifest.json"))
        with self.assertRaisesRegex(BackupError, "缺少 manifest"):
            inspect_backup(missing)

    def test_BU_06_unsafe_member_path_is_rejected(self) -> None:
        self.markdown.sync_all(self.db)
        export_workspace(self.db, self.markdown_root, self.archive)

        def unsafe(entries: dict[str, bytes]) -> None:
            entries["../outside.txt"] = b"must-not-escape"

        malicious = self._rewrite_archive(unsafe)
        with self.assertRaisesRegex(BackupError, "不安全"):
            inspect_backup(malicious)
        self.assertFalse((self.base.parent / "outside.txt").exists())

    def test_BU_07_restore_failure_rolls_current_database_and_markdown_back(self) -> None:
        mainline = self.db.current_mainline_id()
        self.db.create_task(mainline, "备份版本")
        self.markdown.sync_all(self.db)
        export_workspace(self.db, self.markdown_root, self.archive)

        self.db.create_task(mainline, "导入前的当前版本")
        self.markdown.sync_all(self.db)
        marker = self.markdown_root / "current-marker.md"
        marker.write_text("当前版本必须回滚回来", encoding="utf-8")
        self.db.close()
        original_replace = backup_service.os.replace

        def fail_installing_markdown(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.name.startswith(".markdown.import-")
                and destination_path.name == self.markdown_root.name
            ):
                raise OSError("forced-markdown-install-failure")
            return original_replace(source, destination)

        with patch.object(backup_service.os, "replace", side_effect=fail_installing_markdown):
            with self.assertRaisesRegex(BackupError, "原数据已经恢复"):
                restore_workspace(self.archive, self.db_path, self.markdown_root)

        self.db = Database(self.db_path)
        titles = {str(row["title"]) for row in self.db.list_tasks()}
        self.assertIn("导入前的当前版本", titles)
        self.assertEqual(marker.read_text(encoding="utf-8"), "当前版本必须回滚回来")

    def test_BU_08_export_cannot_overwrite_live_data(self) -> None:
        self.markdown.sync_all(self.db)
        with self.assertRaisesRegex(BackupError, "不能覆盖数据库"):
            export_workspace(self.db, self.markdown_root, self.db_path)
        with self.assertRaisesRegex(BackupError, "不能保存在"):
            export_workspace(self.db, self.markdown_root, self.markdown_root / "backup.zip")

    def test_BU_09_11_ui_import_creates_safety_backup_and_reconnects(self) -> None:
        mainline = self.db.current_mainline_id()
        self.db.create_task(mainline, "备份中的工作空间")
        self.markdown.sync_all(self.db)
        export_workspace(self.db, self.markdown_root, self.archive)
        self.db.create_task(mainline, "导入前当前工作空间")
        self.markdown.sync_all(self.db)

        app = flet_app.EntpFletApp.__new__(flet_app.EntpFletApp)
        app.db = self.db
        app.markdown = self.markdown
        app._closed = False
        app._close_dialog = lambda: None
        app._sync_markdown = lambda **_: True
        shown_views: list[int] = []
        notices: list[str] = []
        app.show_view = shown_views.append
        app._notify_success = notices.append
        app._notify_error = lambda message: self.fail(message)

        with patch.object(flet_app, "ROOT", self.base):
            asyncio.run(app.confirm_import_backup(self.archive))

        self.db = app.db
        titles = {str(row["title"]) for row in self.db.list_tasks()}
        self.assertIn("备份中的工作空间", titles)
        self.assertNotIn("导入前当前工作空间", titles)
        self.assertEqual(shown_views, [app.NAV_CURRENT])
        self.assertTrue(notices)
        safety_backups = list((self.base / "backups").glob("导入前自动备份_*.entp.zip"))
        self.assertEqual(len(safety_backups), 1)
        safety_summary = inspect_backup(safety_backups[0])
        imported_summary = inspect_backup(self.archive)
        self.assertEqual(safety_summary.tasks, imported_summary.tasks + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
