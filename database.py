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
SCHEMA_VERSION = 218


class Database:
    def __init__(
        self,
        path: str | Path,
        *,
        seed_on_empty: bool = True,
        internal_demo: bool = False,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A bounded wait handles brief antivirus/sync-tool contention without
        # making the desktop UI appear frozen indefinitely.
        self.conn = sqlite3.connect(self.path, timeout=2.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 2000")
        self._create_schema()
        if internal_demo and not self.row("SELECT 1 FROM mainlines LIMIT 1"):
            # Import locally to keep the database module usable without demo
            # content and to avoid a module-level dependency cycle.
            from demo_data import populate_internal_demo

            populate_internal_demo(self)
        # QA databases can request the real schema without any initial rows.
        elif seed_on_empty:
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
                parent_task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待执行',
                priority TEXT NOT NULL DEFAULT '普通',
                due_date TEXT NOT NULL DEFAULT '',
                is_today INTEGER NOT NULL DEFAULT 0,
                is_focus INTEGER NOT NULL DEFAULT 0,
                next_action TEXT NOT NULL DEFAULT '',
                progress INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
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
        # SQLite 允许以 NULL 默认值增加自引用外键。这样从 2.1.5 及更早
        # 版本直接升级的数据库，与全新 2.1.9 数据库具有相同的删除语义。
        self._ensure_column(
            "tasks",
            "parent_task_id",
            "INTEGER REFERENCES tasks(id) ON DELETE SET NULL DEFAULT NULL",
        )
        self._ensure_column("tasks", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        # 旧数据没有顺序字段。只迁移一次，避免后来合法写入的 0 顺序在
        # 每次启动时又被误判成旧数据。
        sort_migration = self.conn.execute(
            "SELECT value FROM app_settings WHERE key = 'task_sort_order_migration_version'"
        ).fetchone()
        if not sort_migration or str(sort_migration[0]) != "1":
            self.conn.execute(
                "UPDATE tasks SET sort_order = -id WHERE sort_order = 0"
            )
            self.conn.execute(
                """INSERT INTO app_settings(key, value)
                   VALUES ('task_sort_order_migration_version', '1')
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value"""
            )
        self.conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_tasks_parent_sort
               ON tasks(parent_task_id, sort_order)"""
        )
        self._create_task_hierarchy_guards()
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
        # user_version 只在全部结构迁移成功后写入，便于后续版本准确识别基线。
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _create_task_hierarchy_guards(self) -> None:
        """给已升级旧库补齐与新库外键等价且更严格的层级保护。"""

        self.conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tasks_parent_guard_insert
            BEFORE INSERT ON tasks
            WHEN NEW.parent_task_id IS NOT NULL
            BEGIN
                SELECT CASE WHEN NEW.parent_task_id = NEW.id
                    THEN RAISE(ABORT, 'task cannot parent itself') END;
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM tasks parent
                    WHERE parent.id = NEW.parent_task_id
                      AND parent.mainline_id = NEW.mainline_id
                      AND parent.parent_task_id IS NULL
                ) THEN RAISE(ABORT, 'invalid task parent') END;
                SELECT CASE WHEN NEW.is_today <> 0 OR NEW.is_focus <> 0
                    THEN RAISE(ABORT, 'subtask cannot be today or focus') END;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_tasks_parent_guard_update
            BEFORE UPDATE OF parent_task_id, mainline_id, is_today, is_focus ON tasks
            WHEN NEW.parent_task_id IS NOT NULL
            BEGIN
                SELECT CASE WHEN NEW.parent_task_id = NEW.id
                    THEN RAISE(ABORT, 'task cannot parent itself') END;
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM tasks parent
                    WHERE parent.id = NEW.parent_task_id
                      AND parent.mainline_id = NEW.mainline_id
                      AND parent.parent_task_id IS NULL
                ) THEN RAISE(ABORT, 'invalid task parent') END;
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM tasks child WHERE child.parent_task_id = NEW.id
                ) THEN RAISE(ABORT, 'task with children cannot become subtask') END;
                SELECT CASE WHEN NEW.is_today <> 0 OR NEW.is_focus <> 0
                    THEN RAISE(ABORT, 'subtask cannot be today or focus') END;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_tasks_parent_mainline_guard
            BEFORE UPDATE OF mainline_id ON tasks
            WHEN NEW.parent_task_id IS NULL AND EXISTS (
                SELECT 1 FROM tasks child
                WHERE child.parent_task_id = NEW.id
                  AND child.mainline_id <> NEW.mainline_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'parent and children must share mainline');
            END;

            -- 早期测试版已经增加过普通 parent_task_id 列。该触发器为这些
            -- 数据库补上 ON DELETE SET NULL，避免删除父记录后留下孤儿。
            CREATE TRIGGER IF NOT EXISTS trg_tasks_parent_delete_set_null
            AFTER DELETE ON tasks
            BEGIN
                UPDATE tasks SET parent_task_id = NULL
                WHERE parent_task_id = OLD.id;
            END;
            """
        )

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

        if self.get_setting("daily_ledger_migration_version") == "1":
            return
        today = self.today_iso()
        # 2.1.8 could incorrectly copy an already-planned today task to its
        # future due date. Remove only that exact system-generated duplicate.
        self.conn.execute(
            """DELETE FROM daily_entries AS legacy
               WHERE legacy.source = 'legacy' AND legacy.entry_date > ?
                 AND EXISTS (
                     SELECT 1 FROM daily_entries current
                     WHERE current.task_id = legacy.task_id
                       AND current.entry_date = ?
                       AND current.source <> 'legacy'
                 )""",
            (today, today),
        )
        tasks = self.rows(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
               WHERE t.is_today = 1"""
        )
        now = self.local_timestamp()
        for task in tasks:
            # A task that already has ledger history must not be inferred a
            # second time from the compatibility flag.
            if self.row("SELECT 1 FROM daily_entries WHERE task_id = ? LIMIT 1", (task["id"],)):
                continue
            state = "completed" if task["status"] == "完成" else "planned"
            self.conn.execute(
                """INSERT OR IGNORE INTO daily_entries(
                       entry_date, task_id, task_title_snapshot, mainline_id,
                       mainline_name_snapshot, mainline_color_snapshot,
                       priority_snapshot, due_date_snapshot, state, source,
                       completed_at, proof, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy', ?, ?, ?, ?)""",
                (
                    today,
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
        self.conn.execute(
            """INSERT INTO app_settings(key, value)
               VALUES ('daily_ledger_migration_version', '1')
               ON CONFLICT(key) DO UPDATE SET value = excluded.value"""
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
        for row in self.rows("SELECT id, status FROM mainlines"):
            if str(row["status"]) == "已归档":
                self.conn.execute(
                    "UPDATE tasks SET is_focus = 0 WHERE mainline_id = ?",
                    (row["id"],),
                )
            else:
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

        today = date.today()
        yesterday = today - timedelta(days=1)
        now = self.local_timestamp()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO mainlines(name, vision, color) VALUES (?, ?, ?)",
            (
                "欢迎：先认识这套工作流",
                "执行区一次只突出一条当前主线；先把下一步做小，在现实里留下变化。所有示例都可以直接改成你的内容。",
                "#316BEE",
            ),
        )
        welcome_id = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO mainlines(name, vision, color) VALUES (?, ?, ?)",
            (
                "示例：其他主线会进入保管箱",
                "你可以保存多条主线，但它们不会并排争夺注意力；需要时再从保管箱切换回来。",
                "#8B6FD6",
            ),
        )
        vault_demo_id = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO mainlines(name, vision, color) VALUES (?, ?, ?)",
            (
                "收集箱",
                "临时接住今天冒出的任务；之后再决定它是否属于某条主线。",
                "#8B9099",
            ),
        )
        inbox_id = int(cur.lastrowid)

        task_rows = [
            (
                welcome_id,
                "从这里开始：把下一步写小一点",
                "当前任务会单独突出。点击任务可以补充需要记住的内容。",
                "执行中",
                "重要",
                today.isoformat(),
                1,
                1,
                "",
                20,
                "",
            ),
            (
                welcome_id,
                "试试上方输入框：回车添加一个真实任务",
                "创建任务不弹表单。先写一句标题，之后再按需要补充正文和最小行动。",
                "今日",
                "普通",
                today.isoformat(),
                1,
                0,
                "在页面顶部输入一个任务并按回车",
                0,
                "",
            ),
            (
                welcome_id,
                "点击任一任务：右侧可以自由记录详情",
                "任务详情会自动保存；每个任务也有一个独立 Markdown 文档。",
                "今日",
                "普通",
                today.isoformat(),
                1,
                0,
                "点开本任务，改写标题或正文",
                0,
                "",
            ),
            (
                welcome_id,
                "没动力时点“没动力了”：去审视灵感",
                "它表示新鲜感下降，不是任务失败。候审区里的不同灵感可以重新激发兴趣。",
                "待执行",
                "普通",
                "",
                0,
                0,
                "打开候审区，挑一条真正让你好奇的灵感",
                0,
                "",
            ),
            (
                welcome_id,
                "每个小块都有独立 Markdown 文档",
                "主线、任务、灵感和每日账本都会同步为本地 Markdown，方便长期记录和迁移。",
                "待执行",
                "普通",
                "",
                0,
                0,
                "点击任一文档图标查看对应文件",
                0,
                "",
            ),
            (
                welcome_id,
                "示例完成：勾选任务后会写入完成日历",
                "这是初始化的完成示例。完成并不是把任务藏起来，而是在日期账本中留下事实。",
                "完成",
                "普通",
                today.isoformat(),
                0,
                0,
                "",
                100,
                now,
            ),
            (
                welcome_id,
                "示例历史：昨天完成的内容仍然可以回看",
                "切换日期或打开完成日历，可以看到过去真正完成过什么；重新打开任务也不会抹掉历史事实。",
                "完成",
                "普通",
                yesterday.isoformat(),
                0,
                0,
                "",
                100,
                f"{yesterday.isoformat()}T18:30:00+08:00",
            ),
            (
                vault_demo_id,
                "保管箱让其他可能性暂时退出视野",
                "它们仍然保留任务和 Markdown，只是不出现在当前执行区。",
                "待执行",
                "普通",
                "",
                0,
                1,
                "需要切换方向时，再主动进入主线保管箱",
                0,
                "",
            ),
            (
                vault_demo_id,
                "主线可以归档和恢复，不会删除内容",
                "归档用于降低干扰；最后一条活动主线不会被归档，避免工作区失去入口。",
                "待执行",
                "普通",
                "",
                0,
                0,
                "在保管箱中查看归档按钮",
                0,
                "",
            ),
            (
                inbox_id,
                "收集箱：临时接住今天冒出的任务",
                "今日清单顶部可以快速添加；没有归属的任务先放这里，不必当场分类。",
                "今日",
                "普通",
                today.isoformat(),
                1,
                1,
                "打开今日清单，体验快速收纳",
                0,
                "",
            ),
        ]
        cur.executemany(
            """INSERT INTO tasks(
                mainline_id, title, description, status, priority, due_date,
                is_today, is_focus, next_action, progress, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            task_rows,
        )

        thought_rows = [
            (
                None,
                "灵感默认不关联主线：先接住，不打断执行",
                "候审区是独立灵感池。执行时冒出的想法先快速收纳，不要求立刻分类，也不自动切换当前任务。",
                "未审视",
                "核心理念,快速收纳",
            ),
            (
                None,
                "点开卡片：正文是一张自由 Markdown 记录页",
                "系统不预设类别、问题模板或标准答案。标题、标签和正文都可以按你的思考方式自由填写，并在离开输入框时自动保存。",
                "未审视",
                "Markdown,自由记录",
            ),
            (
                None,
                "小图标可以一键孵化、尝试或归档",
                "卡片底部的三个图标直接改变去向，不需要打开下拉框。待孵化表示值得以后继续，但现在不抢占主线。",
                "待孵化",
                "一键操作,状态",
            ),
            (
                welcome_id,
                "正在尝试：把想法改成一次低成本实验",
                "尝试不是承诺把整件事做完，只需要验证一个关键假设。它可以选择关联主线，但关联不是灵感的必填归宿。",
                "正在尝试",
                "最小实验,执行",
            ),
            (
                None,
                "已归档是灵感回收站，可以恢复",
                "归档只让灵感退出日常候审，不会删除标题、标签或 Markdown。进入“已归档”即可查看并恢复到未审视。",
                "已归档",
                "归档,恢复",
            ),
        ]
        cur.executemany(
            """INSERT INTO thoughts(
                mainline_id, title, raw_content, status, tags
            ) VALUES (?, ?, ?, ?, ?)""",
            thought_rows,
        )

        selected_thought = cur.execute(
            "SELECT id FROM thoughts WHERE title = ?",
            ("正在尝试：把想法改成一次低成本实验",),
        ).fetchone()[0]
        supporting_thought = cur.execute(
            "SELECT id FROM thoughts WHERE title = ?",
            ("小图标可以一键孵化、尝试或归档",),
        ).fetchone()[0]
        selected_task = cur.execute(
            "SELECT id FROM tasks WHERE title = ?",
            ("从这里开始：把下一步写小一点",),
        ).fetchone()[0]
        cur.execute(
            "INSERT INTO thought_task_links(thought_id, task_id) VALUES (?, ?)",
            (selected_thought, selected_task),
        )
        cur.execute(
            "INSERT INTO thought_links(source_thought_id, target_thought_id, relation) VALUES (?, ?, ?)",
            (supporting_thought, selected_thought, "支撑"),
        )

        def seed_completion(task_title: str, day_value: date, completed_at: str) -> None:
            task = cur.execute(
                """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color
                     FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
                     WHERE t.title = ?""",
                (task_title,),
            ).fetchone()
            cur.execute(
                """INSERT INTO daily_entries(
                       entry_date, task_id, task_title_snapshot, mainline_id,
                       mainline_name_snapshot, mainline_color_snapshot,
                       priority_snapshot, due_date_snapshot, state, source,
                       completed_at, proof, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', 'onboarding', ?, ?, ?, ?)""",
                (
                    day_value.isoformat(),
                    task["id"],
                    task["title"],
                    task["mainline_id"],
                    task["mainline_name"],
                    task["mainline_color"],
                    task["priority"],
                    task["due_date"],
                    completed_at,
                    "这是初始化示例：完成任务后，现实结果会留在对应日期。",
                    completed_at,
                    completed_at,
                ),
            )
            entry_id = int(cur.lastrowid)
            cur.execute(
                """INSERT INTO task_events(
                       task_id, daily_entry_id, event_type, event_date, occurred_at,
                       task_title_snapshot, details_json
                   ) VALUES (?, ?, 'completed', ?, ?, ?, ?)""",
                (
                    task["id"],
                    entry_id,
                    day_value.isoformat(),
                    completed_at,
                    task["title"],
                    json.dumps({"source": "onboarding"}, ensure_ascii=False),
                ),
            )

        seed_completion(
            "示例完成：勾选任务后会写入完成日历",
            today,
            now,
        )
        seed_completion(
            "示例历史：昨天完成的内容仍然可以回看",
            yesterday,
            f"{yesterday.isoformat()}T18:30:00+08:00",
        )
        cur.execute(
            """INSERT INTO daily_notes(note_date, intention, reflection, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                today.isoformat(),
                "今日页汇总所有主线；先选择少量真正准备推进的任务。",
                "完成与未完成都会留在当天账本，不会因日期更迭而被改写。",
                now,
                now,
            ),
        )
        cur.executemany(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (
                ("current_mainline_id", str(welcome_id)),
                ("onboarding_seed_version", "1"),
            ),
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
               WHERE mainline_id = ? AND parent_task_id IS NULL
                 AND is_focus = 1 AND status <> '完成'
               ORDER BY id LIMIT 1""",
            (mainline_id,),
        )
        if not focused:
            candidate = self.row(
                """SELECT id FROM tasks
                   WHERE mainline_id = ? AND parent_task_id IS NULL
                     AND status <> '完成'
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
               WHERE t.mainline_id = ? AND t.parent_task_id IS NULL
                 AND t.is_focus = 1 AND t.status <> '完成'
               LIMIT 1""",
            (mainline_id,),
        )

    def set_focus_task(self, task_id: int) -> None:
        task = self.get_task(task_id)
        if not task or task["status"] == "完成" or task["parent_task_id"] is not None:
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
               FROM tasks WHERE mainline_id = ? AND parent_task_id IS NULL""",
            (mainline_id,),
        )

    def list_tasks(
        self,
        mainline_id: int | None = None,
        status: str | None = None,
        today_only: bool = False,
        top_level_only: bool = False,
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
        if top_level_only:
            where.append("t.parent_task_id IS NULL")
        clause = " WHERE " + " AND ".join(where) if where else ""
        return self.rows(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color,
                      parent.title AS parent_task_title
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
               LEFT JOIN tasks parent ON parent.id = t.parent_task_id"""
            + clause
            + """ ORDER BY
                    CASE WHEN t.parent_task_id IS NULL THEN t.sort_order
                         ELSE COALESCE(parent.sort_order, t.sort_order) END,
                    CASE WHEN t.parent_task_id IS NULL THEN 0 ELSE 1 END,
                    t.sort_order, t.id""",
            params,
        )

    def get_task(self, task_id: int) -> sqlite3.Row | None:
        return self.row(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color,
                      parent.title AS parent_task_title
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
               LEFT JOIN tasks parent ON parent.id = t.parent_task_id
               WHERE t.id = ?""",
            (task_id,),
        )

    def list_subtasks(self, parent_task_id: int) -> list[sqlite3.Row]:
        """返回父任务的直属子任务；产品只允许一层，不递归查询。"""
        return self.rows(
            """SELECT t.*, m.name AS mainline_name, m.color AS mainline_color,
                      parent.title AS parent_task_title
               FROM tasks t JOIN mainlines m ON m.id = t.mainline_id
               JOIN tasks parent ON parent.id = t.parent_task_id
               WHERE t.parent_task_id = ?
               ORDER BY t.sort_order, t.id""",
            (parent_task_id,),
        )

    def _next_task_sort_order(self, mainline_id: int, parent_task_id: int | None) -> int:
        if parent_task_id is None:
            row = self.row(
                "SELECT MIN(sort_order) AS position FROM tasks WHERE mainline_id = ? AND parent_task_id IS NULL",
                (mainline_id,),
            )
            return int(row["position"] or 0) - 1
        row = self.row(
            "SELECT MAX(sort_order) AS position FROM tasks WHERE parent_task_id = ?",
            (parent_task_id,),
        )
        return int(row["position"] or 0) + 1

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
        parent_task_id: int | None = None,
    ) -> int:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("任务标题不能为空")
        if status not in TASK_STATUSES:
            status = "待执行"
        if parent_task_id is not None:
            parent = self.get_task(parent_task_id)
            if not parent:
                raise ValueError("父任务不存在")
            if int(parent["mainline_id"]) != int(mainline_id):
                raise ValueError("子任务必须与父任务属于同一条主线")
            if parent["parent_task_id"] is not None:
                raise ValueError("目前只支持一层子任务")
            if str(parent["status"]) == "完成":
                raise ValueError("已完成任务不能继续添加子任务")
            # 子任务跟随父任务显示，不单独进入今日账本或成为焦点任务。
            is_today = False
            status = "待执行"
        if is_today and status == "待执行":
            status = "今日"
        sort_order = self._next_task_sort_order(mainline_id, parent_task_id)
        cur = self.conn.execute(
            """INSERT INTO tasks(
                mainline_id, parent_task_id, title, description, status, priority,
                due_date, is_today, next_action, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mainline_id,
                parent_task_id,
                clean_title,
                description.strip(),
                status,
                priority,
                due_date,
                int(is_today),
                next_action.strip(),
                sort_order,
            ),
        )
        task_id = int(cur.lastrowid)
        if is_today:
            self._plan_task_for_day(task_id, self.today_iso(), source="task_create")
        if parent_task_id is None:
            self._ensure_focus_for_mainline(mainline_id, commit=False)
        self.conn.commit()
        return task_id

    def move_task_under(self, task_id: int, parent_task_id: int) -> bool:
        """将独立任务缩进为子任务，并保持数据变更为单次事务。"""
        task = self.get_task(task_id)
        parent = self.get_task(parent_task_id)
        if not task or not parent:
            raise ValueError("拖动的任务已经不存在")
        if task_id == parent_task_id:
            raise ValueError("任务不能成为自己的子任务")
        if int(task["mainline_id"]) != int(parent["mainline_id"]):
            raise ValueError("不能跨主线拖动为子任务")
        if parent["parent_task_id"] is not None:
            raise ValueError("目前只支持一层子任务")
        if self.list_subtasks(task_id):
            raise ValueError("含有子任务的任务不能再缩进")
        if str(parent["status"]) == "完成":
            raise ValueError("不能拖入已完成任务")
        if task["parent_task_id"] == parent_task_id:
            return False

        # 删除今日计划、更新层级和重新选择焦点必须共同成功，否则整体回滚。
        with self.conn:
            today_entry = self.row(
                "SELECT id, state FROM daily_entries WHERE task_id = ? AND entry_date = ?",
                (task_id, self.today_iso()),
            )
            if today_entry and str(today_entry["state"]) == "planned":
                self.conn.execute(
                    "DELETE FROM daily_entries WHERE id = ?", (today_entry["id"],)
                )
            self.conn.execute(
                """UPDATE tasks
                   SET parent_task_id = ?, sort_order = ?, is_today = 0, is_focus = 0,
                       status = CASE WHEN status = '今日' THEN '待执行' ELSE status END
                   WHERE id = ?""",
                (
                    parent_task_id,
                    self._next_task_sort_order(
                        int(task["mainline_id"]), parent_task_id
                    ),
                    task_id,
                ),
            )
            self._ensure_focus_for_mainline(int(task["mainline_id"]), commit=False)
        return True

    def promote_subtask(self, task_id: int, *, keep_today: bool = False) -> bool:
        """将子任务拖出为父任务；若原父任务在今日，则保持它在今日可见。"""
        task = self.get_task(task_id)
        if not task:
            raise ValueError("拖动的子任务已经不存在")
        parent_id = task["parent_task_id"]
        if parent_id is None:
            return False
        parent = self.get_task(int(parent_id))
        inherit_today = bool(
            task["status"] != "完成"
            and (keep_today or (parent and parent["is_today"]))
        )
        status = "今日" if inherit_today and task["status"] == "待执行" else str(task["status"])
        # 层级、今日账本与焦点任务同属一次事务，避免只更新一半。
        with self.conn:
            self.conn.execute(
                """UPDATE tasks
                   SET parent_task_id = NULL, sort_order = ?, is_today = ?, status = ?
                   WHERE id = ?""",
                (
                    self._next_task_sort_order(int(task["mainline_id"]), None),
                    int(inherit_today),
                    status,
                    task_id,
                ),
            )
            if inherit_today:
                self._plan_task_for_day(
                    task_id, self.today_iso(), source="subtask_promoted"
                )
            self._ensure_focus_for_mainline(int(task["mainline_id"]), commit=False)
        return True

    def set_subtask_completed(self, task_id: int, completed: bool) -> None:
        """更新子任务状态，但不创建独立的今日记录或完成日历证据。"""
        task = self.get_task(task_id)
        if not task or task["parent_task_id"] is None:
            raise ValueError("目标不是子任务")
        now = self.local_timestamp()
        self.conn.execute(
            """UPDATE tasks
               SET status = ?, progress = ?, completed_at = ?, is_today = 0, is_focus = 0
               WHERE id = ?""",
            ("完成" if completed else "待执行", 100 if completed else 0, now if completed else "", task_id),
        )
        # 已完成父任务下面不能悬挂未完成子任务。用户重新打开子任务时，
        # 父任务也回到可推进状态，并进入今天等待重新确认成果。
        if not completed:
            parent = self.get_task(int(task["parent_task_id"]))
            if parent and str(parent["status"]) == "完成":
                self.set_task_completed(int(parent["id"]), False)
        self.conn.commit()

    def _mark_subtasks_completed(self, parent_task_id: int) -> None:
        """在当前事务中完成直属子任务；提交由外层用户动作统一负责。"""
        parent = self.get_task(parent_task_id)
        if not parent or parent["parent_task_id"] is not None:
            raise ValueError("目标不是父任务")
        now = self.local_timestamp()
        self.conn.execute(
            """UPDATE tasks SET status = '完成', progress = 100,
                      completed_at = ?, is_today = 0, is_focus = 0
               WHERE parent_task_id = ?""",
            (now, parent_task_id),
        )

    def complete_subtasks(self, parent_task_id: int) -> None:
        """完成直属子任务，但不改变父任务所在的每日账本记录。"""
        self._mark_subtasks_completed(parent_task_id)
        self.conn.commit()

    def complete_task_with_subtasks(self, task_id: int) -> None:
        """显式完成父任务时，一并收口仍未完成的直属子任务。"""
        task = self.get_task(task_id)
        if not task or task["parent_task_id"] is not None:
            raise ValueError("只能完成父任务及其子任务")
        self._mark_subtasks_completed(task_id)
        entry = self.row(
            "SELECT id FROM daily_entries WHERE task_id = ? AND entry_date = ?",
            (task_id, self.today_iso()),
        )
        entry_id = (
            int(entry["id"])
            if entry
            else self._plan_task_for_day(task_id, self.today_iso(), source="completion")
        )
        self._set_daily_entry_completed(entry_id, True)
        self.conn.commit()

    def complete_daily_entry_with_subtasks(self, task_id: int, entry_id: int) -> None:
        """从今日清单完成父任务和子任务，保持整个动作原子化。"""
        entry = self.row("SELECT task_id FROM daily_entries WHERE id = ?", (entry_id,))
        if not entry or int(entry["task_id"] or 0) != task_id:
            raise ValueError("每日记录与父任务不匹配")
        self._mark_subtasks_completed(task_id)
        self._set_daily_entry_completed(entry_id, True)
        self.conn.commit()

    def update_task_status(self, task_id: int, status: str) -> None:
        if status not in TASK_STATUSES:
            return
        task = self.get_task(task_id)
        if not task:
            return
        if task["parent_task_id"] is not None:
            if status == "完成":
                self.set_subtask_completed(task_id, True)
            else:
                self.conn.execute(
                    "UPDATE tasks SET status = ?, progress = 0, completed_at = '' WHERE id = ?",
                    (status, task_id),
                )
                self.conn.commit()
            return
        if status == "完成":
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
        if task["parent_task_id"] is not None:
            raise ValueError("子任务跟随父任务显示，不能单独加入今日")
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
        task = self.get_task(task_id)
        if not task:
            return
        if task["parent_task_id"] is not None:
            self.set_subtask_completed(task_id, completed)
            return
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
        if task["parent_task_id"] is not None:
            raise ValueError("子任务不能单独加入每日清单")
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
