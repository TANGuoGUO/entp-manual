from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


TASK_STATUSES = ("待执行", "今日", "执行中", "完成")
THOUGHT_STATUSES = (
    "未审视",
    "待孵化",
    "正在尝试",
    "已归档",
    # Keep accepting legacy values while older entry points still exist.
    "待整理",
    "已成型",
    "验证中",
    "已落地",
    "已搁置",
)
INTEREST_LEVELS = ("一闪而过", "有点好奇", "很想继续", "持续着迷")
RELATION_TYPES = ("支撑", "拆解", "启发", "冲突", "延伸")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A bounded wait handles brief antivirus/sync-tool contention without
        # making the desktop UI appear frozen indefinitely.
        self.conn = sqlite3.connect(self.path, timeout=2.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 2000")
        self._create_schema()
        self._seed_if_empty()
        self._migrate_legacy_daily_entries()
        self._initialize_focus_state()
        self.refresh_today_flags()

    def close(self) -> None:
        self.conn.close()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mainlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vision TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#1976E9',
                status TEXT NOT NULL DEFAULT '进行中',
                focus_until TEXT NOT NULL DEFAULT '',
                review_mode TEXT NOT NULL DEFAULT '按需复盘',
                next_review_date TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mainline_id INTEGER NOT NULL REFERENCES mainlines(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待执行',
                priority TEXT NOT NULL DEFAULT '普通',
                due_date TEXT NOT NULL DEFAULT '',
                is_today INTEGER NOT NULL DEFAULT 0,
                is_focus INTEGER NOT NULL DEFAULT 0,
                next_action TEXT NOT NULL DEFAULT '',
                progress INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS thoughts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mainline_id INTEGER REFERENCES mainlines(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                raw_content TEXT NOT NULL DEFAULT '',
                conclusion TEXT NOT NULL DEFAULT '',
                evidence TEXT NOT NULL DEFAULT '',
                next_step TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待整理',
                progress INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS thought_task_links (
                thought_id INTEGER NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                PRIMARY KEY (thought_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS thought_links (
                source_thought_id INTEGER NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
                target_thought_id INTEGER NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
                relation TEXT NOT NULL,
                PRIMARY KEY (source_thought_id, target_thought_id, relation),
                CHECK (source_thought_id <> target_thought_id)
            );

            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thought_id INTEGER NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '',
                blocker TEXT NOT NULL DEFAULT '',
                next_step TEXT NOT NULL DEFAULT '',
                progress INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS thought_review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thought_id INTEGER NOT NULL REFERENCES thoughts(id) ON DELETE CASCADE,
                from_status TEXT NOT NULL DEFAULT '',
                to_status TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                event_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                mainline_id INTEGER REFERENCES mainlines(id) ON DELETE SET NULL,
                task_title_snapshot TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '',
                next_action TEXT NOT NULL DEFAULT '',
                event_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                task_title_snapshot TEXT NOT NULL,
                mainline_id INTEGER REFERENCES mainlines(id) ON DELETE SET NULL,
                mainline_name_snapshot TEXT NOT NULL DEFAULT '',
                mainline_color_snapshot TEXT NOT NULL DEFAULT '#8B9099',
                priority_snapshot TEXT NOT NULL DEFAULT '普通',
                due_date_snapshot TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'planned',
                is_primary INTEGER NOT NULL DEFAULT 0,
                carried_from_entry_id INTEGER REFERENCES daily_entries(id) ON DELETE SET NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                completed_at TEXT NOT NULL DEFAULT '',
                proof TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(entry_date, task_id)
            );

            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                daily_entry_id INTEGER REFERENCES daily_entries(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                task_title_snapshot TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS daily_notes (
                note_date TEXT PRIMARY KEY,
                intention TEXT NOT NULL DEFAULT '',
                reflection TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_mainline_status
                ON tasks(mainline_id, status);
            CREATE INDEX IF NOT EXISTS idx_thoughts_mainline_status
                ON thoughts(mainline_id, status);
            CREATE INDEX IF NOT EXISTS idx_logs_thought
                ON execution_logs(thought_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_thought_review_events
                ON thought_review_events(thought_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_task_execution_logs_task
                ON task_execution_logs(task_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_task_execution_logs_date
                ON task_execution_logs(event_date, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_daily_entries_date_state
                ON daily_entries(entry_date, state);
            CREATE INDEX IF NOT EXISTS idx_daily_entries_task
                ON daily_entries(task_id, entry_date DESC);
            CREATE INDEX IF NOT EXISTS idx_task_events_date
                ON task_events(event_date, occurred_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_primary_per_day
                ON daily_entries(entry_date) WHERE is_primary = 1;
            """
        )
        self._ensure_column("tasks", "completed_at", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("tasks", "is_focus", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("tasks", "next_action", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("mainlines", "focus_until", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(
            "mainlines", "review_mode", "TEXT NOT NULL DEFAULT '按需复盘'"
        )
        self._ensure_column("mainlines", "next_review_date", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("thoughts", "category", "TEXT NOT NULL DEFAULT '未分类'")
        self._ensure_column(
            "thoughts", "interest_level", "TEXT NOT NULL DEFAULT '有点好奇'"
        )
        self._ensure_column("thoughts", "tags", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("thoughts", "reviewed_at", "TEXT NOT NULL DEFAULT ''")
        self.conn.execute(
            """UPDATE thoughts SET status = CASE status
                   WHEN '待整理' THEN '未审视'
                   WHEN '已成型' THEN '待孵化'
                   WHEN '验证中' THEN '正在尝试'
                   WHEN '已落地' THEN '已归档'
                   WHEN '已搁置' THEN '已归档'
                   ELSE status END"""
        )
        self.conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_one_focus_task_per_mainline
               ON tasks(mainline_id) WHERE is_focus = 1 AND status <> '完成'"""
        )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def local_timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def today_iso() -> str:
        return date.today().isoformat()

    @staticmethod
    def _valid_day(value: str) -> bool:
        try:
            date.fromisoformat(value)
            return True
        except (TypeError, ValueError):
            return False

    def _migrate_legacy_daily_entries(self) -> None:
        """Snapshot the old permanent `is_today` flag into dated ledger rows once."""
        tasks = self.rows(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
               WHERE t.is_today = 1"""
        )
        now = self.local_timestamp()
        for task in tasks:
            entry_day = task["due_date"] if self._valid_day(task["due_date"]) else self.today_iso()
            state = "completed" if task["status"] == "完成" else "planned"
            self.conn.execute(
                """INSERT OR IGNORE INTO daily_entries(
                       entry_date, task_id, task_title_snapshot, mainline_id,
                       mainline_name_snapshot, mainline_color_snapshot,
                       priority_snapshot, due_date_snapshot, state, source,
                       completed_at, proof, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy', ?, ?, ?, ?)""",
                (
                    entry_day,
                    task["id"],
                    task["title"],
                    task["mainline_id"],
                    task["mainline_name"],
                    task["mainline_color"],
                    task["priority"],
                    task["due_date"],
                    state,
                    task["completed_at"] if "completed_at" in task.keys() else "",
                    "旧版数据迁移：原程序没有保存真实完成时间。" if state == "completed" else "",
                    now,
                    now,
                ),
            )
        self.conn.commit()

    def _initialize_focus_state(self) -> None:
        """Create pressure-free focus defaults without changing historical facts."""
        configured = self.get_setting("current_mainline_id")
        valid = None
        if configured and configured.isdigit():
            valid = self.row(
                """SELECT id FROM mainlines
                   WHERE id = ? AND name <> '收集箱' AND status <> '已归档'""",
                (int(configured),),
            )
        if not valid:
            valid = self.row(
                """SELECT id FROM mainlines
                   WHERE name <> '收集箱' AND status <> '已归档'
                   ORDER BY id LIMIT 1"""
            ) or self.row(
                "SELECT id FROM mainlines WHERE status <> '已归档' ORDER BY id LIMIT 1"
            )
            if valid:
                self.set_setting("current_mainline_id", str(valid["id"]))
        for row in self.rows("SELECT id FROM mainlines"):
            self._ensure_focus_for_mainline(int(row["id"]), commit=False)
        self.conn.commit()

    def refresh_today_flags(self) -> None:
        """Derive the legacy convenience flag from the dated ledger."""
        today = self.today_iso()
        self.conn.execute(
            """UPDATE tasks SET is_today = CASE WHEN EXISTS(
                       SELECT 1 FROM daily_entries de
                       WHERE de.task_id = tasks.id AND de.entry_date = ? AND de.state = 'planned'
                   ) THEN 1 ELSE 0 END""",
            (today,),
        )
        self.conn.execute(
            """UPDATE tasks SET status = CASE
                   WHEN is_today = 1 AND status = '待执行' THEN '今日'
                   WHEN is_today = 0 AND status = '今日' THEN '待执行'
                   ELSE status END"""
        )
        self.conn.commit()

    def _seed_if_empty(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) FROM mainlines").fetchone()[0]
        if count:
            return

        today = datetime.now().date()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO mainlines(name, vision, color) VALUES (?, ?, ?)",
            ("建立稳定的创作系统", "把灵感转化为每周稳定发布、可持续复盘的内容系统。", "#1976E9"),
        )
        creative_id = cur.lastrowid
        cur.execute(
            "INSERT INTO mainlines(name, vision, color) VALUES (?, ?, ?)",
            ("建立个人知识体系", "把输入、判断和输出连接成可复用的知识网络。", "#7B61FF"),
        )
        knowledge_id = cur.lastrowid

        task_rows = [
            (creative_id, "整理选题清单", "从用户问题中整理本周可执行选题。", "执行中", "重要", today.isoformat(), 1, 45),
            (creative_id, "完成脚本初稿", "完成一期播客脚本的结构和开场。", "今日", "重要", today.isoformat(), 1, 10),
            (creative_id, "录制视频素材", "完成三段核心素材录制。", "今日", "普通", today.isoformat(), 1, 0),
            (creative_id, "研究热门话题趋势", "采集近七天同类账号高互动内容。", "待执行", "普通", (today + timedelta(days=1)).isoformat(), 0, 0),
            (creative_id, "收集案例与素材", "为本周脚本建立证据和案例库。", "待执行", "普通", (today + timedelta(days=2)).isoformat(), 0, 0),
            (creative_id, "复盘发布数据", "记录点击、完播和评论中的问题。", "完成", "普通", (today - timedelta(days=1)).isoformat(), 0, 100),
            (knowledge_id, "梳理阅读笔记标签", "减少重复标签，建立主题入口。", "执行中", "普通", today.isoformat(), 1, 30),
            (knowledge_id, "建立每周回顾模板", "固定回顾本周输入、输出和判断。", "待执行", "普通", "", 0, 0),
        ]
        cur.executemany(
            """INSERT INTO tasks(
                mainline_id, title, description, status, priority, due_date, is_today, progress
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            task_rows,
        )

        thought_rows = [
            (
                creative_id,
                "用问题而不是主题做选题",
                "与其先想主题，不如先收集用户真正问过的问题。",
                "问题型选题更容易形成明确承诺，也更容易验证价值。",
                "真实问题天然包含痛点、语境和结果期待；标题也更具体。",
                "补充 5 个关于内容定位的问题，完善问题库。",
                "正在尝试",
                45,
            ),
            (creative_id, "播客内容可以拆成短视频", "一段完整播客可以按观点拆成多个短内容。", "", "", "", "未审视", 0),
            (creative_id, "每周做一次失败复盘", "失败不是废稿，可以成为下一周的输入。", "", "", "", "未审视", 0),
            (creative_id, "建立选题问题库并持续更新", "单独维护用户问题，选题时直接调用。", "", "", "", "未审视", 0),
            (creative_id, "搭建内容框架模板库", "把高表现内容的结构抽象成模板。", "", "", "", "待孵化", 10),
            (creative_id, "从用户痛点收集问题", "评论区和私信比凭空头脑风暴更接近真实需求。", "把问题按痛点阶段分类。", "已验证的用户表达可直接成为选题语言。", "每周整理一次新增问题。", "已归档", 100),
            (knowledge_id, "笔记应该指向下一次使用", "如果一条笔记没有使用场景，之后很难被找到。", "", "", "", "未审视", 0),
        ]
        cur.executemany(
            """INSERT INTO thoughts(
                mainline_id, title, raw_content, conclusion, evidence, next_step, status, progress
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            thought_rows,
        )

        selected_thought = cur.execute(
            "SELECT id FROM thoughts WHERE title = ?", ("用问题而不是主题做选题",)
        ).fetchone()[0]
        supporting_thought = cur.execute(
            "SELECT id FROM thoughts WHERE title = ?", ("从用户痛点收集问题",)
        ).fetchone()[0]
        selected_task = cur.execute(
            "SELECT id FROM tasks WHERE title = ?", ("整理选题清单",)
        ).fetchone()[0]
        cur.execute(
            "INSERT INTO thought_task_links(thought_id, task_id) VALUES (?, ?)",
            (selected_thought, selected_task),
        )
        cur.execute(
            "INSERT INTO thought_links(source_thought_id, target_thought_id, relation) VALUES (?, ?, ?)",
            (supporting_thought, selected_thought, "支撑"),
        )

        log_rows = [
            (
                selected_thought,
                "初步列出常见选题方式对比。",
                "问题选题优于主题选题。",
                "数据样本不足。",
                "收集更多案例数据验证。",
                20,
                (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
            ),
            (
                selected_thought,
                "梳理了问题收集渠道和方法。",
                "确定通过评论区、私信和问卷收集。",
                "问卷参与度较低。",
                "优化问卷话术并增加激励。",
                35,
                (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            ),
            (
                selected_thought,
                "收集了 15 个用户问题，并初步分类整理。",
                "问题多集中在起步困难和内容定位。",
                "部分问题不够具体，需要进一步追问。",
                "补充 5 个关于内容定位的问题。",
                45,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        ]
        cur.executemany(
            """INSERT INTO execution_logs(
                thought_id, action, result, blocker, next_step, progress, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            log_rows,
        )
        self.conn.commit()

    def rows(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, tuple(params)).fetchall())

    def row(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.row("SELECT value FROM app_settings WHERE key = ?", (key,))
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO app_settings(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, str(value)),
        )
        self.conn.commit()

    def current_mainline_id(self) -> int:
        configured = self.get_setting("current_mainline_id")
        if configured.isdigit():
            row = self.row(
                "SELECT id FROM mainlines WHERE id = ? AND status <> '已归档'",
                (int(configured),),
            )
            if row:
                return int(row["id"])
        row = self.row(
            """SELECT id FROM mainlines
               WHERE name <> '收集箱' AND status <> '已归档'
               ORDER BY id LIMIT 1"""
        ) or self.row(
            "SELECT id FROM mainlines WHERE status <> '已归档' ORDER BY id LIMIT 1"
        )
        if not row:
            raise RuntimeError("至少需要一条主线")
        self.set_setting("current_mainline_id", str(row["id"]))
        return int(row["id"])

    def set_current_mainline(self, mainline_id: int) -> None:
        if not self.row(
            "SELECT id FROM mainlines WHERE id = ? AND status <> '已归档'",
            (mainline_id,),
        ):
            raise ValueError("主线不存在或已经归档")
        self.set_setting("current_mainline_id", str(mainline_id))

    def archive_mainline(self, mainline_id: int) -> int:
        mainline = self.row("SELECT * FROM mainlines WHERE id = ?", (mainline_id,))
        if not mainline:
            raise ValueError("主线不存在")
        if str(mainline["name"]) == "收集箱":
            raise ValueError("收集箱是系统区域，不能作为主线归档")
        if str(mainline["status"]) == "已归档":
            return self.current_mainline_id()
        current_id = self.current_mainline_id()
        replacement = self.row(
            """SELECT id FROM mainlines
               WHERE id <> ? AND name <> '收集箱' AND status <> '已归档'
               ORDER BY id LIMIT 1""",
            (mainline_id,),
        )
        if mainline_id == current_id and not replacement:
            raise ValueError("至少需要保留一条未归档主线")
        # Both state changes form one business operation. The connection
        # context commits once on success and rolls every statement back when
        # any later statement fails.
        with self.conn:
            self.conn.execute(
                "UPDATE mainlines SET status = '已归档' WHERE id = ?",
                (mainline_id,),
            )
            if mainline_id == current_id and replacement:
                self.conn.execute(
                    """INSERT INTO app_settings(key, value) VALUES ('current_mainline_id', ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                    (str(replacement["id"]),),
                )
        if mainline_id == current_id and replacement:
            return int(replacement["id"])
        return current_id

    def restore_mainline(self, mainline_id: int) -> None:
        if not self.row("SELECT id FROM mainlines WHERE id = ?", (mainline_id,)):
            raise ValueError("主线不存在")
        self.conn.execute(
            "UPDATE mainlines SET status = '进行中' WHERE id = ?",
            (mainline_id,),
        )
        self.conn.commit()

    def update_mainline(
        self,
        mainline_id: int,
        *,
        name: str | None = None,
        vision: str | None = None,
        focus_until: str | None = None,
        review_mode: str | None = None,
        next_review_date: str | None = None,
    ) -> None:
        if name is not None and not name.strip():
            raise ValueError("主线标题不能为空")
        fields: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("name", name),
            ("vision", vision),
            ("focus_until", focus_until),
            ("review_mode", review_mode),
            ("next_review_date", next_review_date),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value.strip() if isinstance(value, str) else value)
        if not fields:
            return
        values.append(mainline_id)
        self.conn.execute(
            f"UPDATE mainlines SET {', '.join(fields)} WHERE id = ?", values
        )
        self.conn.commit()

    def list_mainlines(self) -> list[sqlite3.Row]:
        return self.rows("SELECT * FROM mainlines ORDER BY id")

    def create_mainline(self, name: str, vision: str = "") -> int:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("主线标题不能为空")
        cur = self.conn.execute(
            "INSERT INTO mainlines(name, vision) VALUES (?, ?)", (clean_name, vision.strip())
        )
        self.conn.commit()
        mainline_id = int(cur.lastrowid)
        if not self.get_setting("current_mainline_id"):
            self.set_current_mainline(mainline_id)
        return mainline_id

    def _ensure_focus_for_mainline(self, mainline_id: int, *, commit: bool = True) -> None:
        focused = self.row(
            """SELECT id FROM tasks
               WHERE mainline_id = ? AND is_focus = 1 AND status <> '完成'
               ORDER BY id LIMIT 1""",
            (mainline_id,),
        )
        if not focused:
            candidate = self.row(
                """SELECT id FROM tasks
                   WHERE mainline_id = ? AND status <> '完成'
                   ORDER BY is_today DESC,
                            CASE status WHEN '执行中' THEN 0 WHEN '今日' THEN 1 ELSE 2 END,
                            CASE priority WHEN '重要' THEN 0 ELSE 1 END,
                            id
                   LIMIT 1""",
                (mainline_id,),
            )
            if candidate:
                self.conn.execute(
                    "UPDATE tasks SET is_focus = 0 WHERE mainline_id = ?",
                    (mainline_id,),
                )
                self.conn.execute(
                    "UPDATE tasks SET is_focus = 1 WHERE id = ?",
                    (candidate["id"],),
                )
        if commit:
            self.conn.commit()

    def get_focus_task(self, mainline_id: int) -> sqlite3.Row | None:
        self._ensure_focus_for_mainline(mainline_id)
        return self.row(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
               WHERE t.mainline_id = ? AND t.is_focus = 1 AND t.status <> '完成'
               LIMIT 1""",
            (mainline_id,),
        )

    def set_focus_task(self, task_id: int) -> None:
        task = self.get_task(task_id)
        if not task or task["status"] == "完成":
            return
        self.conn.execute(
            "UPDATE tasks SET is_focus = 0 WHERE mainline_id = ?",
            (task["mainline_id"],),
        )
        self.conn.execute(
            "UPDATE tasks SET is_focus = 1 WHERE id = ?",
            (task_id,),
        )
        self.conn.commit()

    def mainline_stats(self, mainline_id: int) -> sqlite3.Row:
        return self.row(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status = '完成' THEN 1 ELSE 0 END) AS done
               FROM tasks WHERE mainline_id = ?""",
            (mainline_id,),
        )

    def list_tasks(
        self,
        mainline_id: int | None = None,
        status: str | None = None,
        today_only: bool = False,
    ) -> list[sqlite3.Row]:
        where: list[str] = []
        params: list[Any] = []
        if mainline_id is not None:
            where.append("t.mainline_id = ?")
            params.append(mainline_id)
        if status:
            where.append("t.status = ?")
            params.append(status)
        if today_only:
            where.append("t.is_today = 1")
        clause = " WHERE " + " AND ".join(where) if where else ""
        return self.rows(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id"""
            + clause
            + " ORDER BY t.is_today DESC, t.id DESC",
            params,
        )

    def get_task(self, task_id: int) -> sqlite3.Row | None:
        return self.row(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
               WHERE t.id = ?""",
            (task_id,),
        )

    def create_task(
        self,
        mainline_id: int,
        title: str,
        description: str = "",
        status: str = "待执行",
        priority: str = "普通",
        due_date: str = "",
        is_today: bool = False,
        next_action: str = "",
    ) -> int:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("任务标题不能为空")
        if status not in TASK_STATUSES:
            status = "待执行"
        if is_today and status == "待执行":
            status = "今日"
        cur = self.conn.execute(
            """INSERT INTO tasks(
                mainline_id, title, description, status, priority, due_date, is_today, next_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mainline_id,
                clean_title,
                description.strip(),
                status,
                priority,
                due_date,
                int(is_today),
                next_action.strip(),
            ),
        )
        task_id = int(cur.lastrowid)
        if is_today:
            self._plan_task_for_day(task_id, self.today_iso(), source="task_create")
        self._ensure_focus_for_mainline(mainline_id, commit=False)
        self.conn.commit()
        return task_id

    def update_task_status(self, task_id: int, status: str) -> None:
        if status not in TASK_STATUSES:
            return
        if status == "完成":
            task = self.get_task(task_id)
            entry = self.row(
                "SELECT id FROM daily_entries WHERE task_id = ? AND entry_date = ?",
                (task_id, self.today_iso()),
            )
            if not entry:
                entry_id = self._plan_task_for_day(task_id, self.today_iso(), source="status_change")
            else:
                entry_id = int(entry["id"])
            self._set_daily_entry_completed(entry_id, True)
            if task:
                self._ensure_focus_for_mainline(int(task["mainline_id"]), commit=False)
            self.conn.commit()
            return
        progress = 100 if status == "完成" else None
        if progress is None:
            self.conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        else:
            self.conn.execute(
                "UPDATE tasks SET status = ?, progress = ? WHERE id = ?",
                (status, progress, task_id),
            )
        self.conn.commit()

    def update_task(
        self,
        task_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        next_action: str | None = None,
    ) -> None:
        if title is not None and not title.strip():
            raise ValueError("任务标题不能为空")
        fields: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("title", title),
            ("description", description),
            ("next_action", next_action),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value.strip())
        if not fields:
            return
        values.append(task_id)
        self.conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)
        self.conn.commit()

    def set_task_today(self, task_id: int, is_today: bool) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        status = task["status"]
        if is_today and status == "待执行":
            status = "今日"
        elif not is_today and status == "今日":
            status = "待执行"
        self.conn.execute(
            "UPDATE tasks SET is_today = ?, status = ? WHERE id = ?",
            (int(is_today), status, task_id),
        )
        today = self.today_iso()
        if is_today:
            self._plan_task_for_day(task_id, today, source="today_toggle")
        else:
            entry_row = self.row(
                "SELECT id, state FROM daily_entries WHERE task_id = ? AND entry_date = ?",
                (task_id, today),
            )
            if entry_row and entry_row["state"] == "planned":
                self.conn.execute("DELETE FROM daily_entries WHERE id = ?", (entry_row["id"],))
        self.conn.commit()

    def set_task_completed(self, task_id: int, completed: bool) -> None:
        """Complete or restore a task from the daily checklist."""
        entry = self.row(
            "SELECT id FROM daily_entries WHERE task_id = ? AND entry_date = ?",
            (task_id, self.today_iso()),
        )
        if not entry:
            entry_id = self._plan_task_for_day(task_id, self.today_iso(), source="completion")
        else:
            entry_id = int(entry["id"])
        if entry_id:
            self._set_daily_entry_completed(entry_id, completed)
        self.conn.commit()

    def postpone_tasks_to_today(self, task_ids: Iterable[int]) -> int:
        ids = [int(task_id) for task_id in task_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        rows = self.rows(
            f"""SELECT id FROM daily_entries
                 WHERE task_id IN ({placeholders}) AND state = 'planned'
                 ORDER BY entry_date""",
            ids,
        )
        return self.carry_daily_entries((row["id"] for row in rows), self.today_iso())

    def _record_task_event(
        self,
        task_id: int | None,
        entry_id: int | None,
        event_type: str,
        event_date: str,
        title: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO task_events(
                   task_id, daily_entry_id, event_type, event_date, occurred_at,
                   task_title_snapshot, details_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                entry_id,
                event_type,
                event_date,
                self.local_timestamp(),
                title,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )

    def _plan_task_for_day(
        self,
        task_id: int,
        day: str,
        *,
        source: str = "manual",
        carried_from_entry_id: int | None = None,
    ) -> int:
        if not self._valid_day(day):
            raise ValueError("日期必须使用 YYYY-MM-DD 格式")
        existing = self.row(
            "SELECT id FROM daily_entries WHERE task_id = ? AND entry_date = ?",
            (task_id, day),
        )
        if existing:
            return int(existing["id"])
        task = self.get_task(task_id)
        if not task:
            return 0
        now = self.local_timestamp()
        cur = self.conn.execute(
            """INSERT INTO daily_entries(
                   entry_date, task_id, task_title_snapshot, mainline_id,
                   mainline_name_snapshot, mainline_color_snapshot,
                   priority_snapshot, due_date_snapshot, state,
                   carried_from_entry_id, source, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?)""",
            (
                day,
                task_id,
                task["title"],
                task["mainline_id"],
                task["mainline_name"],
                task["mainline_color"],
                task["priority"],
                task["due_date"],
                carried_from_entry_id,
                source,
                now,
                now,
            ),
        )
        entry_id = int(cur.lastrowid)
        self._record_task_event(task_id, entry_id, "planned", day, task["title"], {"source": source})
        return entry_id

    def plan_task_for_day(self, task_id: int, day: str, *, source: str = "manual") -> int:
        entry_id = self._plan_task_for_day(task_id, day, source=source)
        if day == self.today_iso() and entry_id:
            task = self.get_task(task_id)
            if task and task["status"] == "待执行":
                self.conn.execute(
                    "UPDATE tasks SET is_today = 1, status = '今日' WHERE id = ?", (task_id,)
                )
        self.conn.commit()
        return entry_id

    def list_daily_entries(self, day: str) -> list[sqlite3.Row]:
        return self.rows(
            """SELECT de.*, de.task_title_snapshot AS title,
                      de.mainline_name_snapshot AS mainline_name,
                      de.mainline_color_snapshot AS mainline_color,
                      de.priority_snapshot AS priority,
                      de.due_date_snapshot AS due_date,
                      EXISTS(
                          SELECT 1 FROM task_events te
                          WHERE te.daily_entry_id = de.id AND te.event_type = 'completed'
                      ) AS had_completion,
                      COALESCE((
                          SELECT MAX(te.occurred_at) FROM task_events te
                          WHERE te.daily_entry_id = de.id AND te.event_type = 'completed'
                      ), de.completed_at) AS last_completed_at,
                      COALESCE(t.status, CASE WHEN de.state = 'completed' THEN '完成' ELSE '待执行' END) AS task_status
               FROM daily_entries de
               LEFT JOIN tasks t ON t.id = de.task_id
               WHERE de.entry_date = ?
               ORDER BY de.is_primary DESC, de.id""",
            (day,),
        )

    def list_overdue_entries(self, before_day: str) -> list[sqlite3.Row]:
        return self.rows(
            """SELECT de.*, de.task_title_snapshot AS title,
                      de.mainline_name_snapshot AS mainline_name,
                      de.mainline_color_snapshot AS mainline_color,
                      de.priority_snapshot AS priority,
                      de.entry_date AS due_date,
                      COALESCE(t.status, '待执行') AS task_status
               FROM daily_entries de
               LEFT JOIN tasks t ON t.id = de.task_id
               WHERE de.entry_date < ? AND de.state = 'planned'
                 AND de.id = (
                     SELECT MAX(de2.id) FROM daily_entries de2
                     WHERE de2.task_id = de.task_id AND de2.state = 'planned'
                 )
               ORDER BY de.entry_date, de.id""",
            (before_day,),
        )

    def _set_daily_entry_completed(self, entry_id: int, completed: bool) -> None:
        entry = self.row("SELECT * FROM daily_entries WHERE id = ?", (entry_id,))
        if not entry:
            return
        task_id = entry["task_id"]
        now = self.local_timestamp()
        if completed:
            self.conn.execute(
                "UPDATE daily_entries SET state = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
                (now, now, entry_id),
            )
            if task_id:
                self.conn.execute(
                    "UPDATE tasks SET status = '完成', progress = 100, completed_at = ?, is_today = 0 WHERE id = ?",
                    (now, task_id),
                )
            event_type = "completed"
        else:
            self.conn.execute(
                "UPDATE daily_entries SET state = 'planned', completed_at = '', updated_at = ? WHERE id = ?",
                (now, entry_id),
            )
            if task_id:
                is_today = entry["entry_date"] == self.today_iso()
                self.conn.execute(
                    "UPDATE tasks SET status = ?, progress = 0, completed_at = '', is_today = ? WHERE id = ?",
                    ("今日" if is_today else "待执行", int(is_today), task_id),
                )
            event_type = "reopened"
        self._record_task_event(
            task_id, entry_id, event_type, entry["entry_date"], entry["task_title_snapshot"]
        )
        if entry["mainline_id"]:
            self._ensure_focus_for_mainline(int(entry["mainline_id"]), commit=False)

    def set_daily_entry_completed(self, entry_id: int, completed: bool) -> None:
        entry = self.row("SELECT * FROM daily_entries WHERE id = ?", (entry_id,))
        if (
            completed
            and entry
            and entry["state"] == "planned"
            and entry["entry_date"] < self.today_iso()
            and entry["task_id"]
        ):
            self.carry_daily_entries((entry_id,), self.today_iso())
            target = self.row(
                "SELECT id FROM daily_entries WHERE task_id = ? AND entry_date = ?",
                (entry["task_id"], self.today_iso()),
            )
            if target:
                entry_id = int(target["id"])
        self._set_daily_entry_completed(entry_id, completed)
        self.conn.commit()

    def carry_daily_entries(self, entry_ids: Iterable[int], target_day: str) -> int:
        if not self._valid_day(target_day):
            raise ValueError("日期必须使用 YYYY-MM-DD 格式")
        count = 0
        now = self.local_timestamp()
        for entry_id in {int(value) for value in entry_ids}:
            old = self.row("SELECT * FROM daily_entries WHERE id = ?", (entry_id,))
            if not old or old["state"] != "planned" or not old["task_id"]:
                continue
            new_id = self._plan_task_for_day(
                int(old["task_id"]),
                target_day,
                source="carry",
                carried_from_entry_id=entry_id,
            )
            if not new_id:
                continue
            self.conn.execute(
                "UPDATE daily_entries SET state = 'carried', updated_at = ? WHERE id = ?",
                (now, entry_id),
            )
            if target_day == self.today_iso():
                self.conn.execute(
                    """UPDATE tasks SET is_today = 1,
                           status = CASE WHEN status = '待执行' THEN '今日' ELSE status END
                       WHERE id = ?""",
                    (old["task_id"],),
                )
            self._record_task_event(
                old["task_id"],
                new_id,
                "carried",
                target_day,
                old["task_title_snapshot"],
                {"from_date": old["entry_date"], "from_entry_id": entry_id},
            )
            count += 1
        self.conn.commit()
        return count

    def daily_summary(self, day: str) -> sqlite3.Row:
        return self.row(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN EXISTS(
                          SELECT 1 FROM task_events te
                          WHERE te.daily_entry_id = daily_entries.id
                            AND te.event_type = 'completed'
                      ) THEN 1 ELSE 0 END) AS completed,
                      SUM(CASE WHEN state = 'planned' AND NOT EXISTS(
                          SELECT 1 FROM task_events te
                          WHERE te.daily_entry_id = daily_entries.id
                            AND te.event_type = 'completed'
                      ) THEN 1 ELSE 0 END) AS unfinished,
                      SUM(CASE WHEN state = 'carried' THEN 1 ELSE 0 END) AS carried
               FROM daily_entries WHERE entry_date = ?""",
            (day,),
        )

    def daily_dates(self) -> list[str]:
        return [row["entry_date"] for row in self.rows(
            "SELECT DISTINCT entry_date FROM daily_entries ORDER BY entry_date DESC"
        )]

    def completion_days(
        self, year: int, month: int, mainline_id: int | None = None
    ) -> dict[str, int]:
        prefix = f"{year:04d}-{month:02d}-"
        params: list[Any] = [prefix + "%"]
        mainline_clause = ""
        if mainline_id is not None:
            mainline_clause = " AND de.mainline_id = ?"
            params.append(mainline_id)
        rows = self.rows(
            """SELECT de.entry_date, COUNT(*) AS completed
               FROM daily_entries de
               WHERE de.entry_date LIKE ? AND EXISTS(
                   SELECT 1 FROM task_events te
                   WHERE te.daily_entry_id = de.id AND te.event_type = 'completed'
               )"""
            + mainline_clause
            + " GROUP BY de.entry_date ORDER BY de.entry_date",
            params,
        )
        return {str(row["entry_date"]): int(row["completed"]) for row in rows}

    def completed_entries_on(
        self, day: str, mainline_id: int | None = None
    ) -> list[sqlite3.Row]:
        params: list[Any] = [day]
        mainline_clause = ""
        if mainline_id is not None:
            mainline_clause = " AND de.mainline_id = ?"
            params.append(mainline_id)
        return self.rows(
            """SELECT de.id, de.entry_date, de.task_id,
                      de.task_title_snapshot, de.mainline_id,
                      de.mainline_name_snapshot, de.mainline_color_snapshot,
                      de.priority_snapshot, de.due_date_snapshot, de.state,
                      de.is_primary, de.carried_from_entry_id, de.source,
                      de.proof, de.created_at, de.updated_at,
                      de.task_title_snapshot AS title,
                      de.mainline_name_snapshot AS mainline_name,
                      COALESCE((
                          SELECT MAX(te.occurred_at) FROM task_events te
                          WHERE te.daily_entry_id = de.id AND te.event_type = 'completed'
                      ), de.completed_at) AS completed_at
               FROM daily_entries de
               WHERE de.entry_date = ? AND EXISTS(
                   SELECT 1 FROM task_events te
                   WHERE te.daily_entry_id = de.id AND te.event_type = 'completed'
               )"""
            + mainline_clause
            + " ORDER BY completed_at DESC, de.id DESC",
            params,
        )

    def add_task_execution_log(
        self,
        task_id: int,
        *,
        action: str,
        result: str = "",
        next_action: str = "",
        complete: bool = False,
    ) -> int:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        now = self.local_timestamp()
        today = self.today_iso()
        cur = self.conn.execute(
            """INSERT INTO task_execution_logs(
                   task_id, mainline_id, task_title_snapshot, action,
                   result, next_action, event_date, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                task["mainline_id"],
                task["title"],
                action.strip(),
                result.strip(),
                next_action.strip(),
                today,
                now,
            ),
        )
        if next_action.strip():
            self.conn.execute(
                "UPDATE tasks SET next_action = ? WHERE id = ?",
                (next_action.strip(), task_id),
            )
        entry_id = self._plan_task_for_day(task_id, today, source="execution_log")
        self.conn.execute(
            "UPDATE daily_entries SET proof = ?, updated_at = ? WHERE id = ?",
            (result.strip(), now, entry_id),
        )
        self._record_task_event(
            task_id,
            entry_id,
            "executed",
            today,
            task["title"],
            {"action": action.strip(), "result": result.strip()},
        )
        if complete:
            self._set_daily_entry_completed(entry_id, True)
        self.conn.commit()
        return int(cur.lastrowid)

    def task_execution_logs(self, task_id: int) -> list[sqlite3.Row]:
        return self.rows(
            """SELECT * FROM task_execution_logs
               WHERE task_id = ? ORDER BY created_at DESC, id DESC""",
            (task_id,),
        )

    def get_or_create_inbox(self) -> int:
        existing = self.row("SELECT id FROM mainlines WHERE name = ?", ("收集箱",))
        if existing:
            return int(existing["id"])
        cur = self.conn.execute(
            """INSERT INTO mainlines(name, vision, color)
               VALUES (?, ?, ?)""",
            ("收集箱", "临时收集尚未归入具体主线的任务。", "#8B9099"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_thoughts(
        self, mainline_id: int | None = None, statuses: tuple[str, ...] | None = None
    ) -> list[sqlite3.Row]:
        where: list[str] = []
        params: list[Any] = []
        if mainline_id is not None:
            where.append("th.mainline_id = ?")
            params.append(mainline_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"th.status IN ({placeholders})")
            params.extend(statuses)
        clause = " WHERE " + " AND ".join(where) if where else ""
        return self.rows(
            """SELECT th.*, m.name AS mainline_name
               FROM thoughts th LEFT JOIN mainlines m ON m.id = th.mainline_id"""
            + clause
            + " ORDER BY CASE th.status WHEN '未审视' THEN 0 WHEN '待孵化' THEN 1 WHEN '正在尝试' THEN 2 WHEN '已归档' THEN 3 ELSE 4 END, th.updated_at DESC, th.id DESC",
            params,
        )

    def get_thought(self, thought_id: int) -> sqlite3.Row | None:
        return self.row(
            """SELECT th.*, m.name AS mainline_name
               FROM thoughts th LEFT JOIN mainlines m ON m.id = th.mainline_id
               WHERE th.id = ?""",
            (thought_id,),
        )

    def create_thought(
        self,
        title: str,
        raw_content: str = "",
        mainline_id: int | None = None,
        *,
        category: str = "未分类",
        interest_level: str = "有点好奇",
    ) -> int:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("灵感标题不能为空")
        cur = self.conn.execute(
            """INSERT INTO thoughts(
                   mainline_id, title, raw_content, status, category, interest_level
               ) VALUES (?, ?, ?, '未审视', ?, ?)""",
            (
                mainline_id,
                clean_title,
                raw_content.strip(),
                category.strip() or "未分类",
                interest_level if interest_level in INTEREST_LEVELS else "有点好奇",
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_thought(
        self,
        thought_id: int,
        *,
        title: str,
        raw_content: str,
        conclusion: str,
        evidence: str,
        next_step: str,
        status: str,
        progress: int,
        mainline_id: int | None,
        category: str | None = None,
        interest_level: str | None = None,
        tags: str | None = None,
    ) -> None:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("灵感标题不能为空")
        if status not in THOUGHT_STATUSES:
            status = "未审视"
        current = self.get_thought(thought_id)
        old_status = str(current["status"]) if current else ""
        saved_category = (
            category.strip()
            if category is not None and category.strip()
            else str(current["category"] if current else "未分类")
        )
        saved_interest = (
            interest_level
            if interest_level in INTEREST_LEVELS
            else str(current["interest_level"] if current else "有点好奇")
        )
        saved_tags = tags.strip() if tags is not None else str(current["tags"] if current else "")
        reviewed_at = (
            self.local_timestamp()
            if status != "未审视"
            else str(current["reviewed_at"] if current else "")
        )
        self.conn.execute(
            """UPDATE thoughts SET
                mainline_id = ?, title = ?, raw_content = ?, conclusion = ?,
                evidence = ?, next_step = ?, status = ?, progress = ?, category = ?,
                interest_level = ?, tags = ?, reviewed_at = ?,
                updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                mainline_id,
                clean_title,
                raw_content.strip(),
                conclusion.strip(),
                evidence.strip(),
                next_step.strip(),
                status,
                max(0, min(100, int(progress))),
                saved_category,
                saved_interest,
                saved_tags,
                reviewed_at,
                thought_id,
            ),
        )
        if old_status and old_status != status:
            self._record_thought_review_event(
                thought_id,
                from_status=old_status,
                to_status=status,
                note="在候审区调整阶段",
            )
        self.conn.commit()

    def _record_thought_review_event(
        self,
        thought_id: int,
        *,
        from_status: str,
        to_status: str,
        note: str = "",
    ) -> None:
        now = self.local_timestamp()
        self.conn.execute(
            """INSERT INTO thought_review_events(
                   thought_id, from_status, to_status, note, event_date, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (thought_id, from_status, to_status, note.strip(), self.today_iso(), now),
        )

    def set_thought_stage(self, thought_id: int, status: str, note: str = "") -> None:
        if status not in ("未审视", "待孵化", "正在尝试", "已归档"):
            raise ValueError("无效的灵感阶段")
        thought = self.get_thought(thought_id)
        if not thought:
            raise ValueError("灵感不存在")
        old_status = str(thought["status"])
        reviewed_at = self.local_timestamp() if status != "未审视" else str(thought["reviewed_at"])
        self.conn.execute(
            """UPDATE thoughts SET status = ?, reviewed_at = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (status, reviewed_at, thought_id),
        )
        if old_status != status:
            self._record_thought_review_event(
                thought_id,
                from_status=old_status,
                to_status=status,
                note=note,
            )
        self.conn.commit()

    def thought_review_events(self, thought_id: int) -> list[sqlite3.Row]:
        return self.rows(
            """SELECT * FROM thought_review_events
               WHERE thought_id = ? ORDER BY created_at DESC, id DESC""",
            (thought_id,),
        )

    def linked_tasks(self, thought_id: int) -> list[sqlite3.Row]:
        return self.rows(
            """SELECT t.* FROM tasks t
               JOIN thought_task_links l ON l.task_id = t.id
               WHERE l.thought_id = ? ORDER BY t.id DESC""",
            (thought_id,),
        )

    def link_task(self, thought_id: int, task_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO thought_task_links(thought_id, task_id) VALUES (?, ?)",
            (thought_id, task_id),
        )
        self.conn.commit()

    def thought_relations(self, thought_id: int) -> list[sqlite3.Row]:
        return self.rows(
            """SELECT l.*, s.title AS source_title, t.title AS target_title
               FROM thought_links l
               JOIN thoughts s ON s.id = l.source_thought_id
               JOIN thoughts t ON t.id = l.target_thought_id
               WHERE l.source_thought_id = ? OR l.target_thought_id = ?
               ORDER BY l.rowid DESC""",
            (thought_id, thought_id),
        )

    def link_thought(self, source_id: int, target_id: int, relation: str) -> None:
        if source_id == target_id or relation not in RELATION_TYPES:
            return
        self.conn.execute(
            """INSERT OR IGNORE INTO thought_links(
                source_thought_id, target_thought_id, relation
            ) VALUES (?, ?, ?)""",
            (source_id, target_id, relation),
        )
        self.conn.commit()

    def create_task_from_thought(self, thought_id: int) -> int:
        thought = self.get_thought(thought_id)
        if not thought:
            raise ValueError("思路不存在")
        mainline_id = thought["mainline_id"]
        if mainline_id is None:
            mainline = self.list_mainlines()[0]
            mainline_id = mainline["id"]
        title = thought["next_step"].strip() or f"验证：{thought['title']}"
        task_id = self.create_task(
            mainline_id,
            title,
            description=f"由思路「{thought['title']}」生成。\n\n{thought['conclusion']}",
            status="待执行",
        )
        self.link_task(thought_id, task_id)
        return task_id

    def execution_logs(self, thought_id: int) -> list[sqlite3.Row]:
        return self.rows(
            "SELECT * FROM execution_logs WHERE thought_id = ? ORDER BY created_at DESC, id DESC",
            (thought_id,),
        )

    def add_execution_log(
        self,
        thought_id: int,
        *,
        action: str,
        result: str,
        blocker: str,
        next_step: str,
        progress: int,
    ) -> int:
        progress = max(0, min(100, int(progress)))
        cur = self.conn.execute(
            """INSERT INTO execution_logs(
                thought_id, action, result, blocker, next_step, progress
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (thought_id, action.strip(), result.strip(), blocker.strip(), next_step.strip(), progress),
        )
        thought = self.get_thought(thought_id)
        status = thought["status"] if thought else "正在尝试"
        if status in ("未审视", "待孵化", "待整理", "已成型"):
            status = "正在尝试"
        if progress >= 100:
            status = "已归档"
        self.conn.execute(
            """UPDATE thoughts SET progress = ?, status = ?, next_step = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (progress, status, next_step.strip(), thought_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)
