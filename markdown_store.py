from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from database import Database


SYSTEM_START = "<!-- ENTP-SYSTEM:START -->"
SYSTEM_END = "<!-- ENTP-SYSTEM:END -->"

KIND_INFO = {
    "mainline": ("主线", "M"),
    "task": ("任务", "T"),
    "thought": ("思路", "I"),
    "execution": ("执行记录", "L"),
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MARKDOWN_IMAGE_PATTERN = re.compile(
    r"!\[[^\]]*\]\((?:<(?P<angled>[^>]+)>|(?P<plain>[^)\s]+))\)"
)


def yaml_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


class MarkdownStore:
    """Maps every database object to one durable Markdown document.

    Only the block between SYSTEM_START and SYSTEM_END is refreshed. Everything
    outside it belongs to the user and is never overwritten by synchronization.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.last_sync_errors: list[tuple[Path, OSError]] = []
        self.root.mkdir(parents=True, exist_ok=True)
        for directory, _prefix in KIND_INFO.values():
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "每日").mkdir(parents=True, exist_ok=True)

    def path_for(self, kind: str, object_id: int) -> Path:
        directory, prefix = KIND_INFO[kind]
        return self.root / directory / f"{prefix}{int(object_id):04d}.md"

    def relative_path_for(self, kind: str, object_id: int) -> str:
        return self.path_for(kind, object_id).relative_to(self.root).as_posix()

    def editor_image_context(self, kind: str, object_id: int) -> tuple[Path, str]:
        """Return the durable image directory and its Markdown link prefix."""
        document = self.path_for(kind, object_id)
        _directory, prefix = KIND_INFO[kind]
        attachment_dir = self.root / "_assets" / kind / f"{prefix}{int(object_id):04d}"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        relative = os.path.relpath(attachment_dir, document.parent).replace(os.sep, "/")
        return attachment_dir, relative

    def editor_body_with_legacy_images(
        self, kind: str, object_id: int, body: str
    ) -> str:
        """Bring images added by the former bottom gallery into the editor body.

        The old UI appended image links below the system block without storing
        them in the task description. Their original cursor position was never
        recorded, so the only lossless migration is to append each missing link
        once. New Quill pastes are stored at their actual cursor position.
        """
        content = self.read(kind, object_id)
        missing = [
            match.group(0)
            for match in MARKDOWN_IMAGE_PATTERN.finditer(content)
            if match.group(0) not in body
        ]
        if not missing:
            return body
        parts = [body.rstrip(), *missing]
        return "\n\n".join(part for part in parts if part).strip()

    def read(self, kind: str, object_id: int) -> str:
        path = self.path_for(kind, object_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def add_image(self, kind: str, object_id: int, source: str | Path) -> tuple[Path, str]:
        """Copy an image into the managed Markdown tree and return its relative link."""
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"找不到所选图片：{source_path}")
        suffix = source_path.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            raise ValueError("只支持 PNG、JPG、GIF、WebP 和 BMP 图片")

        document = self.path_for(kind, object_id)
        _directory, prefix = KIND_INFO[kind]
        attachment_dir = self.root / "_assets" / kind / f"{prefix}{int(object_id):04d}"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", source_path.stem).strip("-")
        safe_stem = safe_stem or "image"
        destination = attachment_dir / f"{safe_stem}{suffix}"
        if destination.exists():
            destination = attachment_dir / f"{safe_stem}-{uuid.uuid4().hex[:8]}{suffix}"

        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(source_path, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

        relative = os.path.relpath(destination, document.parent).replace(os.sep, "/")
        return destination, relative

    def add_image_bytes(
        self,
        kind: str,
        object_id: int,
        image_bytes: bytes,
        *,
        stem: str = "pasted-image",
    ) -> tuple[Path, str]:
        """Store an encoded clipboard image beside the managed Markdown tree."""
        if not image_bytes:
            raise ValueError("剪贴板中没有可用的图片")

        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            suffix = ".png"
        elif image_bytes.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
        elif image_bytes.startswith((b"GIF87a", b"GIF89a")):
            suffix = ".gif"
        elif image_bytes.startswith(b"BM"):
            suffix = ".bmp"
        elif (
            len(image_bytes) >= 12
            and image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        ):
            suffix = ".webp"
        else:
            raise ValueError("剪贴板图片格式无法识别，请改用“插入图片”")

        document = self.path_for(kind, object_id)
        _directory, prefix = KIND_INFO[kind]
        attachment_dir = self.root / "_assets" / kind / f"{prefix}{int(object_id):04d}"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", stem).strip("-")
        safe_stem = safe_stem or "pasted-image"
        destination = attachment_dir / f"{safe_stem}{suffix}"
        if destination.exists():
            destination = attachment_dir / f"{safe_stem}-{uuid.uuid4().hex[:8]}{suffix}"

        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(image_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

        relative = os.path.relpath(destination, document.parent).replace(os.sep, "/")
        return destination, relative

    def image_paths(self, kind: str, object_id: int, content: str) -> list[Path]:
        """Resolve local image references without allowing paths outside this workspace."""
        document = self.path_for(kind, object_id)
        root = self.root.resolve()
        images: list[Path] = []
        for match in MARKDOWN_IMAGE_PATTERN.finditer(content):
            reference = match.group("angled") or match.group("plain") or ""
            if "://" in reference or reference.startswith("data:"):
                continue
            # Keep the path spelling rooted in the configured workspace. Windows
            # can expose the same temporary directory once as RUNNER~1 and once
            # as runneradmin; returning the canonical spelling made an image look
            # different from the path returned when it was inserted.
            candidate = Path(os.path.abspath(document.parent / reference))
            canonical_candidate = candidate.resolve()
            try:
                canonical_candidate.relative_to(root)
            except ValueError:
                continue
            if (
                canonical_candidate.is_file()
                and canonical_candidate.suffix.lower() in IMAGE_EXTENSIONS
            ):
                images.append(candidate)
        return images

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        """Write beside the destination and replace it only after a full flush.

        A crash, full disk, sync-tool conflict, or permission error can leave a
        temporary file behind briefly, but can no longer truncate the user's
        last valid Markdown document.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def write_user_edited(self, kind: str, object_id: int, content: str) -> Path:
        path = self.path_for(kind, object_id)
        self._atomic_write_text(path, content)
        return path

    def append_user_markdown(self, kind: str, object_id: int, addition: str) -> Path:
        """Append user-owned Markdown without exposing or changing the system block."""
        path = self.path_for(kind, object_id)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        addition = addition.strip()
        if not addition:
            return path
        user_content = existing.split(SYSTEM_END, 1)[-1] if SYSTEM_END in existing else existing
        if addition in user_content:
            return path
        merged = existing.rstrip() + "\n\n" + addition + "\n"
        self._atomic_write_text(path, merged)
        return path

    def daily_path(self, day: str) -> Path:
        return self.root / "每日" / f"{day}.md"

    def _merge_synced_path(self, path: Path, system: str, user_template: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        system_block = f"{SYSTEM_START}\n{system.strip()}\n{SYSTEM_END}"

        if SYSTEM_START in existing and SYSTEM_END in existing:
            start = existing.index(SYSTEM_START)
            end = existing.index(SYSTEM_END, start) + len(SYSTEM_END)
            merged = existing[:start] + system_block + existing[end:]
        elif existing.strip():
            merged = system_block + "\n\n" + existing.lstrip()
        else:
            merged = system_block + "\n\n" + user_template.strip() + "\n"

        self._atomic_write_text(path, merged)
        return path

    def _write_synced(self, kind: str, object_id: int, system: str, user_template: str) -> Path:
        path = self.path_for(kind, object_id)
        return self._merge_synced_path(path, system, user_template)

    def sync_all(
        self,
        db: "Database",
        *,
        continue_on_error: bool = False,
    ) -> dict[str, int]:
        """同步全部文档；应用运行时可隔离单个被占用文件的写入失败。"""
        counts = {key: 0 for key in KIND_INFO}
        counts["daily"] = 0
        self.last_sync_errors = []
        mainlines = db.list_mainlines()
        tasks = db.list_tasks()
        thoughts = db.list_thoughts()
        logs = db.rows(
            """SELECT l.*, th.title AS thought_title, th.mainline_id,
                      m.name AS mainline_name
               FROM execution_logs l
               JOIN thoughts th ON th.id = l.thought_id
               LEFT JOIN mainlines m ON m.id = th.mainline_id
               ORDER BY l.id"""
        )

        def sync_one(path: Path, kind: str, operation) -> None:
            try:
                operation()
            except OSError as error:
                if not continue_on_error:
                    raise
                # 只隔离文件系统错误；代码错误和数据错误仍向上抛出，避免静默损坏。
                self.last_sync_errors.append((path, error))
            else:
                counts[kind] += 1

        for row in mainlines:
            sync_one(
                self.path_for("mainline", int(row["id"])),
                "mainline",
                lambda current=row: self._sync_mainline(current),
            )
        for row in tasks:
            sync_one(
                self.path_for("task", int(row["id"])),
                "task",
                lambda current=row: self._sync_task(db, current),
            )
        for row in thoughts:
            sync_one(
                self.path_for("thought", int(row["id"])),
                "thought",
                lambda current=row: self._sync_thought(db, current),
            )
        for row in logs:
            sync_one(
                self.path_for("execution", int(row["id"])),
                "execution",
                lambda current=row: self._sync_execution(current),
            )

        daily_dates = db.daily_dates()
        for day in daily_dates:
            sync_one(
                self.daily_path(day),
                "daily",
                lambda current=day: self._sync_daily(db, current),
            )

        try:
            self._write_indexes(mainlines, tasks, thoughts, logs, daily_dates)
        except OSError as error:
            if not continue_on_error:
                raise
            self.last_sync_errors.append((self.root / "索引文件", error))
        return counts

    def _frontmatter(self, pairs: Iterable[tuple[str, object]]) -> str:
        lines = ["---"]
        lines.extend(f"{key}: {yaml_value(value)}" for key, value in pairs)
        lines.append("---")
        return "\n".join(lines)

    def _sync_mainline(self, row) -> Path:
        object_code = f"M{row['id']:04d}"
        frontmatter = self._frontmatter(
            (
                ("entp_id", object_code),
                ("type", "mainline"),
                ("title", row["name"]),
                ("status", row["status"]),
                ("created_at", row["created_at"]),
            )
        )
        system = f"""{frontmatter}

# {row['name']}

状态：**{row['status']}**

## 记录

{row['vision'] or ''}

_以上为程序同步区，请在下方自由记录。_"""
        path = self._write_synced("mainline", row["id"], system, "")
        legacy_template = """## 主线记录

### 当前判断


### 本阶段目标

- [ ]

### 复盘"""
        content = path.read_text(encoding="utf-8")
        if SYSTEM_END in content:
            head, tail = content.split(SYSTEM_END, 1)
            if tail.strip() == legacy_template.strip():
                self._atomic_write_text(path, head + SYSTEM_END + "\n")
        return path

    def _sync_task(self, db: "Database", row) -> Path:
        object_code = f"T{row['id']:04d}"
        execution_logs = db.task_execution_logs(row["id"])
        execution_lines = "\n".join(
            f"- {log['event_date']} · {log['action'] or '执行'} → "
            f"{log['result'] or '尚未填写结果'}"
            f"{' · 下一步：' + log['next_action'] if log['next_action'] else ''}"
            for log in execution_logs
        ) or "- 暂无执行记录"
        frontmatter = self._frontmatter(
            (
                ("entp_id", object_code),
                ("type", "task"),
                ("title", row["title"]),
                ("mainline", row["mainline_name"]),
                ("parent_task", row["parent_task_title"] or ""),
                ("status", row["status"]),
                ("priority", row["priority"]),
                ("due_date", row["due_date"]),
                ("today", bool(row["is_today"])),
                ("focus", bool(row["is_focus"])),
                ("next_action", row["next_action"]),
                ("progress", row["progress"]),
                ("created_at", row["created_at"]),
                ("completed_at", row["completed_at"]),
            )
        )
        system = f"""{frontmatter}

# {row['title']}

**所属主线：** {row['mainline_name']}  
**父任务：** {row['parent_task_title'] or '无（独立任务）'}<br>
**状态：** {row['status']} · **优先级：** {row['priority']} · **进度：** {row['progress']}%
**当前焦点：** {'是' if row['is_focus'] else '否'}  
**最小下一步：** {row['next_action'] or '尚未填写'}

## 任务说明

{row['description'] or '暂无说明。'}

## 执行记录

{execution_lines}

_以上为程序同步区，请在下方自由记录。_"""
        user = """## 执行笔记

### 开始前

- 预期结果：
- 最小下一步：

### 过程记录


### 完成复盘

- 实际结果：
- 下次改进：
"""
        return self._write_synced("task", row["id"], system, user)

    def _sync_thought(self, db: "Database", row) -> Path:
        object_code = f"I{row['id']:04d}"
        frontmatter = self._frontmatter(
            (
                ("entp_id", object_code),
                ("type", "thought"),
                ("title", row["title"]),
                ("status", row["status"]),
                ("tags", row["tags"] or ""),
                ("created_at", row["created_at"]),
                ("updated_at", row["updated_at"]),
            )
        )
        system = f"""{frontmatter}

# {row['title']}

**状态：** {row['status']} · **标签：** {row['tags'] or ''}

## 记录

{row['raw_content'] or ''}

_以上为程序同步区，请在下方自由记录。_"""
        path = self._write_synced("thought", row["id"], system, "")
        # Remove only the untouched legacy prompt template. Anything the user
        # actually wrote outside the system block remains unchanged.
        legacy_template = """## 自由补充

### 新证据


### 反例与疑问


### 可复用的方法"""
        content = path.read_text(encoding="utf-8")
        if SYSTEM_END in content:
            head, tail = content.split(SYSTEM_END, 1)
            if tail.strip() == legacy_template.strip():
                self._atomic_write_text(path, head + SYSTEM_END + "\n")
        return path

    def _sync_execution(self, row) -> Path:
        object_code = f"L{row['id']:04d}"
        frontmatter = self._frontmatter(
            (
                ("entp_id", object_code),
                ("type", "execution_log"),
                ("thought_id", f"I{row['thought_id']:04d}"),
                ("thought", row["thought_title"]),
                ("mainline", row["mainline_name"] or ""),
                ("progress", row["progress"]),
                ("created_at", row["created_at"]),
            )
        )
        system = f"""{frontmatter}

# 执行记录：{row['thought_title']}

**时间：** {row['created_at']} · **进度：** {row['progress']}%

## 本次行动

{row['action'] or '暂无。'}

## 执行结果

{row['result'] or '暂无。'}

## 遇到的阻碍

{row['blocker'] or '暂无。'}

## 下一步

{row['next_step'] or '暂无。'}

_以上为程序同步区，请在下方自由记录。_"""
        user = """## 补充记录

- 当时的判断：
- 后来发生了什么：
- 是否需要修正原思路：
"""
        return self._write_synced("execution", row["id"], system, user)

    def _sync_daily(self, db: "Database", day: str) -> Path:
        rows = db.list_daily_entries(day)
        summary = db.daily_summary(day)
        completed = int(summary["completed"] or 0) if summary else 0
        total = int(summary["total"] or 0) if summary else 0
        unfinished = int(summary["unfinished"] or 0) if summary else 0
        carried = int(summary["carried"] or 0) if summary else 0

        lines: list[str] = []
        for row in rows:
            state = row["state"]
            had_completion = bool(row["had_completion"])
            mark = "x" if had_completion else " "
            suffix = {
                "completed": "已完成",
                "planned": "未完成",
                "carried": "已结转",
                "skipped": "已放弃",
            }.get(state, state)
            if had_completion and state != "completed":
                suffix = "已完成过 · 后续重新打开" if state == "planned" else f"已完成过 · {suffix}"
            lines.append(
                f"- [{mark}] {row['task_title_snapshot']} · {row['mainline_name_snapshot']} · {suffix}"
            )
            if row["last_completed_at"]:
                lines.append(f"  - 完成时间：{row['last_completed_at']}")
            if row["proof"]:
                lines.append(f"  - 成果证据：{row['proof']}")
            if row["carried_from_entry_id"]:
                lines.append("  - 来源：由更早日期结转")

        frontmatter = self._frontmatter(
            (
                ("type", "daily_ledger"),
                ("date", day),
                ("total", total),
                ("completed", completed),
                ("unfinished", unfinished),
                ("carried", carried),
            )
        )
        system = f"""{frontmatter}

# {day} · 每日账本

**完成：** {completed}/{total} · **未完成：** {unfinished} · **已结转：** {carried}

## 当天行动

{chr(10).join(lines) or '- 当天没有行动记录'}

_以上为程序同步区。任务后续改名或转移主线，不会改写这里的当天快照。_"""
        user = """## 当日意图


## 成果证据


## 当日复盘

- 什么推动了主线？
- 什么只是忙碌？
- 明天是否仍愿意选择这条主线？
"""
        return self._merge_synced_path(self.daily_path(day), system, user)

    def _write_indexes(self, mainlines, tasks, thoughts, logs, daily_dates) -> None:
        groups = (
            ("主线", "mainline", mainlines, lambda row: row["name"]),
            ("任务", "task", tasks, lambda row: f"{row['title']} · {row['status']}"),
            ("思路", "thought", thoughts, lambda row: f"{row['title']} · {row['status']}"),
            (
                "执行记录",
                "execution",
                logs,
                lambda row: f"{row['thought_title']} · {row['created_at'][:16]}",
            ),
        )
        root_lines = ["# ENTP 自强手册 · Markdown 文档", ""]
        root_lines.append("每个主线、任务、思路、单次执行记录和日期账本都有独立文档。")
        root_lines.append("")
        for directory, kind, rows, labeler in groups:
            index_lines = [f"# {directory}", "", "_此索引由程序自动生成。_", ""]
            for row in rows:
                filename = self.path_for(kind, row["id"]).name
                index_lines.append(f"- [{labeler(row)}](./{filename})")
            self._atomic_write_text(
                self.root / directory / "INDEX.md", "\n".join(index_lines) + "\n"
            )
            root_lines.append(f"- [{directory}](./{directory}/INDEX.md) · {len(rows)} 个文档")
        daily_index = ["# 每日账本", "", "_此索引由程序自动生成。_", ""]
        for day in daily_dates:
            summary = self.daily_path(day).name
            daily_index.append(f"- [{day}](./{summary})")
        self._atomic_write_text(
            self.root / "每日" / "INDEX.md", "\n".join(daily_index) + "\n"
        )
        root_lines.append(f"- [每日账本](./每日/INDEX.md) · {len(daily_dates)} 个文档")
        self._atomic_write_text(self.root / "README.md", "\n".join(root_lines) + "\n")
