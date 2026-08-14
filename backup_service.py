from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, BinaryIO

from app_version import APP_VERSION

if TYPE_CHECKING:
    from database import Database


BACKUP_FORMAT = "entp-workspace-backup"
BACKUP_VERSION = 1
DATABASE_MEMBER = "database/entp.db"
MANIFEST_MEMBER = "manifest.json"
MAX_MEMBER_SIZE = 1024 * 1024 * 1024
MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
REQUIRED_TABLES = {
    "mainlines",
    "tasks",
    "thoughts",
    "thought_task_links",
    "thought_links",
    "execution_logs",
    "thought_review_events",
    "task_execution_logs",
    "daily_entries",
    "task_events",
    "daily_notes",
    "app_settings",
}


class BackupError(RuntimeError):
    """The backup cannot be safely created or restored."""


@dataclass(frozen=True)
class BackupSummary:
    archive_path: Path
    created_at: str
    table_counts: dict[str, int]
    markdown_files: int
    total_bytes: int

    @property
    def mainlines(self) -> int:
        return self.table_counts.get("mainlines", 0)

    @property
    def tasks(self) -> int:
        return self.table_counts.get("tasks", 0)

    @property
    def thoughts(self) -> int:
        return self.table_counts.get("thoughts", 0)


def _sha256_stream(handle: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _sha256_path(path: Path) -> tuple[str, int]:
    with path.open("rb") as handle:
        return _sha256_stream(handle)


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing = REQUIRED_TABLES - tables
    if missing:
        raise BackupError(f"备份数据库缺少必要数据表：{', '.join(sorted(missing))}")
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in sorted(REQUIRED_TABLES)
    }


def _validate_database(path: Path) -> dict[str, int]:
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.lower() != "ok":
                raise BackupError(f"备份数据库完整性检查失败：{integrity}")
            return _table_counts(connection)
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise BackupError(f"备份中的 SQLite 数据库无效：{error}") from error


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        info = archive.getinfo(MANIFEST_MEMBER)
    except KeyError as error:
        raise BackupError("这不是有效的 ENTP 完整备份：缺少 manifest.json") from error
    if info.file_size > 1024 * 1024:
        raise BackupError("备份清单异常过大")
    try:
        manifest = json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackupError("备份清单无法读取") from error
    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError("备份格式不属于 ENTP 自强手册")
    version = manifest.get("format_version")
    if not isinstance(version, int) or version < 1:
        raise BackupError("备份版本信息无效")
    if version > BACKUP_VERSION:
        raise BackupError("这个备份由更高版本创建，请先升级程序再导入")
    if manifest.get("database") != DATABASE_MEMBER:
        raise BackupError("备份清单中的数据库路径无效")
    return manifest


def _validate_archive(archive_path: Path, *, stage_database: Path | None = None) -> BackupSummary:
    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise BackupError("找不到要导入的备份文件")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise BackupError("备份包含重复文件名")
            if any(not _safe_member_name(name) for name in names):
                raise BackupError("备份包含不安全的文件路径")
            if any(info.flag_bits & 0x1 for info in infos):
                raise BackupError("不支持加密的备份文件")
            if any(((info.external_attr >> 16) & 0o170000) == 0o120000 for info in infos):
                raise BackupError("备份中不能包含符号链接")
            total_bytes = sum(info.file_size for info in infos)
            if total_bytes > MAX_TOTAL_SIZE or any(info.file_size > MAX_MEMBER_SIZE for info in infos):
                raise BackupError("备份文件异常过大")
            if archive.testzip() is not None:
                raise BackupError("备份压缩包校验失败，文件可能已经损坏")

            manifest = _read_manifest(archive)
            payload = manifest.get("payload")
            if not isinstance(payload, list):
                raise BackupError("备份清单缺少文件校验信息")
            declared: dict[str, dict] = {}
            for entry in payload:
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                    raise BackupError("备份文件校验信息无效")
                declared[entry["path"]] = entry
            if len(declared) != len(payload):
                raise BackupError("备份清单包含重复文件")
            actual_payload = set(names) - {MANIFEST_MEMBER}
            if set(declared) != actual_payload or DATABASE_MEMBER not in actual_payload:
                raise BackupError("备份内容与清单不一致")

            temporary_context = None
            if stage_database is None:
                temporary_context = TemporaryDirectory()
                stage_database = Path(temporary_context.name) / "entp.db"
            try:
                for name, entry in declared.items():
                    info = archive.getinfo(name)
                    with archive.open(info, "r") as source:
                        if name == DATABASE_MEMBER:
                            stage_database.parent.mkdir(parents=True, exist_ok=True)
                            with stage_database.open("wb") as destination:
                                digest = hashlib.sha256()
                                size = 0
                                while chunk := source.read(1024 * 1024):
                                    destination.write(chunk)
                                    digest.update(chunk)
                                    size += len(chunk)
                            actual_hash = digest.hexdigest()
                        else:
                            actual_hash, size = _sha256_stream(source)
                    if size != entry.get("size") or actual_hash != entry.get("sha256"):
                        raise BackupError(f"备份文件校验失败：{name}")
                counts = _validate_database(stage_database)
            finally:
                if temporary_context is not None:
                    temporary_context.cleanup()

            declared_counts = manifest.get("table_counts")
            if declared_counts != counts:
                raise BackupError("备份数据库数量与清单不一致")
            markdown_files = sum(1 for name in actual_payload if name.startswith("markdown/"))
            return BackupSummary(
                archive_path=archive_path,
                created_at=str(manifest.get("created_at") or ""),
                table_counts=counts,
                markdown_files=markdown_files,
                total_bytes=total_bytes,
            )
    except zipfile.BadZipFile as error:
        raise BackupError("备份压缩包无法读取或已经损坏") from error


def inspect_backup(archive_path: str | Path) -> BackupSummary:
    return _validate_archive(Path(archive_path))


def export_workspace(
    db: "Database", markdown_root: str | Path, target_path: str | Path
) -> BackupSummary:
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    markdown_root = Path(markdown_root).resolve()
    if target == db.path.resolve() or target.is_relative_to(markdown_root):
        raise BackupError("备份文件不能覆盖数据库，也不能保存在受管理的 Markdown 目录中")
    temporary_zip = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with TemporaryDirectory(dir=target.parent) as temporary_root:
            snapshot = Path(temporary_root) / "entp.db"
            destination = sqlite3.connect(snapshot)
            try:
                db.conn.backup(destination)
            finally:
                destination.close()
            counts = _validate_database(snapshot)

            payload: list[dict[str, object]] = []
            database_hash, database_size = _sha256_path(snapshot)
            payload.append(
                {"path": DATABASE_MEMBER, "size": database_size, "sha256": database_hash}
            )
            markdown_files = sorted(
                path for path in markdown_root.rglob("*") if path.is_file()
            ) if markdown_root.exists() else []
            for path in markdown_files:
                relative = path.relative_to(markdown_root).as_posix()
                digest, size = _sha256_path(path)
                payload.append(
                    {"path": f"markdown/{relative}", "size": size, "sha256": digest}
                )

            manifest = {
                "format": BACKUP_FORMAT,
                "format_version": BACKUP_VERSION,
                "app_version": APP_VERSION,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "database": DATABASE_MEMBER,
                "markdown_root": "markdown/",
                "table_counts": counts,
                "payload": payload,
            }
            with zipfile.ZipFile(
                temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                archive.write(snapshot, DATABASE_MEMBER)
                for path in markdown_files:
                    relative = path.relative_to(markdown_root).as_posix()
                    archive.write(path, f"markdown/{relative}")
                archive.writestr(
                    MANIFEST_MEMBER,
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
            os.replace(temporary_zip, target)
    except (OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as error:
        raise BackupError(f"无法创建完整备份：{error}") from error
    finally:
        temporary_zip.unlink(missing_ok=True)
    return inspect_backup(target)


def restore_workspace(
    archive_path: str | Path,
    database_path: str | Path,
    markdown_root: str | Path,
) -> BackupSummary:
    """Restore a validated package. The caller must close the live DB first."""
    archive_path = Path(archive_path).resolve()
    database_path = Path(database_path).resolve()
    markdown_root = Path(markdown_root).resolve()
    if archive_path == database_path or archive_path.is_relative_to(markdown_root):
        raise BackupError("导入包不能是当前数据库或受管理 Markdown 目录内的文件")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_root.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    stage_database = database_path.with_name(f".{database_path.name}.import-{token}")
    incoming_markdown = markdown_root.with_name(f".{markdown_root.name}.import-{token}")
    rollback_database = database_path.with_name(f".{database_path.name}.before-import-{token}")
    rollback_markdown = markdown_root.with_name(f".{markdown_root.name}.before-import-{token}")
    database_was_present = database_path.exists()
    markdown_was_present = markdown_root.exists()
    moved_database = False
    moved_markdown = False
    installed_database = False
    installed_markdown = False
    rollback_failed = False
    try:
        summary = _validate_archive(archive_path, stage_database=stage_database)
        incoming_markdown.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(archive_path, "r") as archive:
            manifest = _read_manifest(archive)
            for entry in manifest["payload"]:
                name = str(entry["path"])
                if not name.startswith("markdown/"):
                    continue
                relative = PurePosixPath(name).relative_to("markdown")
                target = incoming_markdown.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)

        for suffix in ("-wal", "-shm"):
            database_path.with_name(database_path.name + suffix).unlink(missing_ok=True)
        if database_was_present:
            os.replace(database_path, rollback_database)
            moved_database = True
        if markdown_was_present:
            os.replace(markdown_root, rollback_markdown)
            moved_markdown = True
        os.replace(stage_database, database_path)
        installed_database = True
        os.replace(incoming_markdown, markdown_root)
        installed_markdown = True
        _validate_database(database_path)
    except Exception as error:
        try:
            if installed_database and database_path.exists():
                database_path.unlink()
            if moved_database and rollback_database.exists():
                os.replace(rollback_database, database_path)
            if installed_markdown and markdown_root.exists():
                shutil.rmtree(markdown_root)
            if moved_markdown and rollback_markdown.exists():
                os.replace(rollback_markdown, markdown_root)
        except Exception as rollback_error:
            rollback_failed = True
            raise BackupError(
                f"导入失败，且自动回滚也失败：{error}；回滚错误：{rollback_error}"
            ) from error
        if isinstance(error, BackupError):
            raise
        raise BackupError(f"导入失败，原数据已经恢复：{error}") from error
    finally:
        stage_database.unlink(missing_ok=True)
        if incoming_markdown.exists():
            shutil.rmtree(incoming_markdown, ignore_errors=True)
        if not rollback_failed:
            rollback_database.unlink(missing_ok=True)
            if rollback_markdown.exists():
                shutil.rmtree(rollback_markdown, ignore_errors=True)
    return summary


def default_backup_name() -> str:
    return f"ENTP完整备份_{datetime.now():%Y%m%d_%H%M%S}.entp.zip"
