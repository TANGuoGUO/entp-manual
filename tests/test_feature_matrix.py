from __future__ import annotations

import os
import sqlite3
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import markdown_store as markdown_module
from database import Database
from markdown_store import MarkdownStore, SYSTEM_END, SYSTEM_START


class TemporaryDatabaseTestCase(unittest.TestCase):
    """Every test owns a disposable database and Markdown tree."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.db_path = self.base / "test.db"
        self.db = Database(self.db_path)
        self.markdown = MarkdownStore(self.base / "markdown")

    def tearDown(self) -> None:
        try:
            self.db.close()
        except sqlite3.ProgrammingError:
            pass
        self.temp.cleanup()

    def active_mainlines(self) -> list[int]:
        return [
            int(row["id"])
            for row in self.db.list_mainlines()
            if row["name"] != "收集箱" and row["status"] != "已归档"
        ]


class StartupSchemaTests(TemporaryDatabaseTestCase):
    def test_ST_01_schema_and_current_mainline(self) -> None:
        tables = {
            row["name"]
            for row in self.db.rows(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertEqual(
            tables,
            {
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
            },
        )
        self.assertIn(self.db.current_mainline_id(), self.active_mainlines())

    def test_ST_02_reopen_is_idempotent(self) -> None:
        before = {
            table: int(self.db.row(f"SELECT COUNT(*) AS n FROM {table}")["n"])
            for table in ("mainlines", "tasks", "thoughts", "execution_logs")
        }
        self.db.close()
        self.db = Database(self.db_path)
        after = {
            table: int(self.db.row(f"SELECT COUNT(*) AS n FROM {table}")["n"])
            for table in before
        }
        self.assertEqual(before, after)

    def test_ST_03_foreign_keys_and_unique_daily_entry(self) -> None:
        self.assertEqual(int(self.db.row("PRAGMA foreign_keys")[0]), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute(
                "INSERT INTO tasks(mainline_id, title) VALUES (?, ?)", (999_999, "孤儿任务")
            )
        self.db.conn.rollback()

        mainline_id = self.db.current_mainline_id()
        task_id = self.db.create_task(mainline_id, "唯一账本项")
        day = self.db.today_iso()
        self.db.plan_task_for_day(task_id, day)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.conn.execute(
                """INSERT INTO daily_entries(
                       entry_date, task_id, task_title_snapshot, mainline_id,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (day, task_id, "重复", mainline_id, self.db.local_timestamp(), self.db.local_timestamp()),
            )
        self.db.conn.rollback()

    def test_ST_04_invalid_current_setting_repairs_itself(self) -> None:
        archived_id = self.db.create_mainline("将被归档")
        self.db.archive_mainline(archived_id)
        self.db.set_setting("current_mainline_id", str(archived_id))
        current = self.db.current_mainline_id()
        self.assertNotEqual(current, archived_id)
        self.assertIn(current, self.active_mainlines())

    def test_ST_05_fresh_workspace_is_a_functional_product_tour(self) -> None:
        current = self.db.row(
            "SELECT * FROM mainlines WHERE id = ?", (self.db.current_mainline_id(),)
        )
        self.assertEqual(current["name"], "欢迎：先认识这套工作流")
        self.assertEqual(self.db.get_setting("onboarding_seed_version"), "1")
        self.assertIsNotNone(
            self.db.row("SELECT id FROM mainlines WHERE name = '收集箱'")
        )

        task_titles = {str(row["title"]) for row in self.db.list_tasks()}
        for feature_hint in (
            "回车添加",
            "自由记录详情",
            "没动力",
            "Markdown",
            "完成日历",
            "保管箱",
            "归档和恢复",
            "收集箱",
        ):
            self.assertTrue(
                any(feature_hint in title for title in task_titles),
                f"初始化任务缺少功能介绍：{feature_hint}",
            )

        statuses = {str(row["status"]) for row in self.db.list_thoughts()}
        self.assertEqual(statuses, {"未审视", "待孵化", "正在尝试", "已归档"})
        self.assertTrue(self.db.completion_days(date.today().year, date.today().month))
        self.assertTrue(self.db.completed_entries_on(date.today().isoformat()))
        self.assertTrue(
            self.db.completed_entries_on((date.today() - timedelta(days=1)).isoformat())
        )
        self.assertFalse(
            task_titles
            & {
                "整理选题清单",
                "完成脚本初稿",
                "录制视频素材",
                "梳理阅读笔记标签",
            }
        )


class MainlineTests(TemporaryDatabaseTestCase):
    def test_ML_01_03_create_and_edit_freeform_mainline(self) -> None:
        mainline_id = self.db.create_mainline("新的主线", "")
        self.db.update_mainline(mainline_id, name="重命名主线", vision="自由正文\n第二行")
        row = self.db.row("SELECT * FROM mainlines WHERE id = ?", (mainline_id,))
        self.assertEqual(row["name"], "重命名主线")
        self.assertEqual(row["vision"], "自由正文\n第二行")

    def test_ML_02_empty_mainline_title_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.db.create_mainline("   ")
        existing = self.db.current_mainline_id()
        with self.assertRaises(ValueError):
            self.db.update_mainline(existing, name="   ")

    def test_ML_04_multiple_mainlines_one_current(self) -> None:
        first = self.db.create_mainline("主线甲")
        second = self.db.create_mainline("主线乙")
        self.db.set_current_mainline(first)
        self.assertEqual(self.db.current_mainline_id(), first)
        self.db.set_current_mainline(second)
        self.assertEqual(self.db.current_mainline_id(), second)
        self.assertIn(first, [int(row["id"]) for row in self.db.list_mainlines()])

    def test_ML_05_archive_restore_preserves_tasks(self) -> None:
        mainline_id = self.db.create_mainline("可归档主线")
        task_id = self.db.create_task(mainline_id, "保留的任务")
        self.db.archive_mainline(mainline_id)
        self.assertEqual(self.db.row("SELECT status FROM mainlines WHERE id = ?", (mainline_id,))["status"], "已归档")
        self.assertIsNotNone(self.db.get_task(task_id))
        self.db.restore_mainline(mainline_id)
        self.assertEqual(self.db.row("SELECT status FROM mainlines WHERE id = ?", (mainline_id,))["status"], "进行中")

    def test_ML_06_archive_current_switches_atomically_on_success(self) -> None:
        current = self.db.current_mainline_id()
        self.db.create_mainline("替代主线")
        self.db.set_current_mainline(current)
        returned = self.db.archive_mainline(current)
        self.assertNotEqual(returned, current)
        self.assertEqual(self.db.current_mainline_id(), returned)
        self.assertIn(returned, self.active_mainlines())

    def test_ML_07_08_last_active_and_inbox_are_protected(self) -> None:
        active = self.active_mainlines()
        for mainline_id in active[1:]:
            self.db.archive_mainline(mainline_id)
        with self.assertRaises(ValueError):
            self.db.archive_mainline(active[0])
        inbox = self.db.get_or_create_inbox()
        with self.assertRaises(ValueError):
            self.db.archive_mainline(inbox)

    def test_ML_09_archive_rolls_back_when_setting_write_fails(self) -> None:
        current = self.db.current_mainline_id()
        self.db.create_mainline("故障时替代主线")
        self.db.conn.execute(
            """CREATE TRIGGER fail_current_setting
               BEFORE UPDATE OF value ON app_settings
               WHEN NEW.key = 'current_mainline_id'
               BEGIN SELECT RAISE(ABORT, 'forced-setting-failure'); END"""
        )
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.archive_mainline(current)
        # A later, unrelated successful operation must not accidentally commit
        # the first half of the failed archive transaction.
        self.db.set_setting("post_failure_probe", "1")
        row = self.db.row("SELECT status FROM mainlines WHERE id = ?", (current,))
        self.assertEqual(row["status"], "进行中", "归档第一步必须随第二步失败而回滚")


class TaskTests(TemporaryDatabaseTestCase):
    def test_TK_01_multiple_tasks_and_list_membership(self) -> None:
        mainline_id = self.db.create_mainline("多任务主线")
        ids = [self.db.create_task(mainline_id, f"任务 {index}") for index in range(3)]
        listed = {int(row["id"]) for row in self.db.list_tasks(mainline_id)}
        self.assertTrue(set(ids).issubset(listed))

    def test_TK_02_empty_task_title_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.db.create_task(self.db.current_mainline_id(), "   ")
        task_id = self.db.create_task(self.db.current_mainline_id(), "保留标题")
        with self.assertRaises(ValueError):
            self.db.update_task(task_id, title="   ")
        self.assertEqual(self.db.get_task(task_id)["title"], "保留标题")

    def test_TK_03_optional_fields_and_next_action(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "可选字段", due_date="")
        self.db.update_task(task_id, title="新标题", description="说明", next_action="打开文件")
        row = self.db.get_task(task_id)
        self.assertEqual((row["title"], row["description"], row["next_action"]), ("新标题", "说明", "打开文件"))
        self.assertEqual(row["due_date"], "")

    def test_TK_04_05_focus_is_unique_per_mainline(self) -> None:
        first_mainline = self.db.create_mainline("焦点一")
        a = self.db.create_task(first_mainline, "A")
        b = self.db.create_task(first_mainline, "B")
        self.db.set_focus_task(a)
        self.db.set_focus_task(b)
        focused = self.db.rows(
            "SELECT id FROM tasks WHERE mainline_id = ? AND is_focus = 1 AND status <> '完成'",
            (first_mainline,),
        )
        self.assertEqual([int(row["id"]) for row in focused], [b])

        second_mainline = self.db.create_mainline("焦点二")
        c = self.db.create_task(second_mainline, "C")
        self.db.set_focus_task(c)
        self.assertEqual(int(self.db.get_focus_task(first_mainline)["id"]), b)
        self.assertEqual(int(self.db.get_focus_task(second_mainline)["id"]), c)

    def test_TK_06_07_completion_and_reopen_keep_history(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "完成再重开", is_today=True)
        entry_id = int(self.db.row("SELECT id FROM daily_entries WHERE task_id = ?", (task_id,))["id"])
        self.db.set_daily_entry_completed(entry_id, True)
        self.assertEqual(self.db.get_task(task_id)["status"], "完成")
        self.db.set_daily_entry_completed(entry_id, False)
        row = self.db.list_daily_entries(self.db.today_iso())
        tested = next(item for item in row if int(item["id"]) == entry_id)
        self.assertEqual(tested["state"], "planned")
        self.assertEqual(int(tested["had_completion"]), 1)

    def test_TK_08_09_execution_log_updates_evidence_and_can_complete(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "执行中的任务")
        log_id = self.db.add_task_execution_log(
            task_id,
            action="做一次实验",
            result="得到结果",
            next_action="记录结论",
            complete=True,
        )
        self.assertGreater(log_id, 0)
        self.assertEqual(self.db.get_task(task_id)["next_action"], "记录结论")
        entry = self.db.row("SELECT * FROM daily_entries WHERE task_id = ?", (task_id,))
        self.assertEqual(entry["proof"], "得到结果")
        self.assertEqual(entry["state"], "completed")

    def test_TK_10_missing_task_execution_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "任务不存在"):
            self.db.add_task_execution_log(999_999, action="不存在")


class DailyLedgerAndCalendarTests(TemporaryDatabaseTestCase):
    def test_DL_01_inbox_task_enters_today(self) -> None:
        inbox = self.db.get_or_create_inbox()
        task_id = self.db.create_task(inbox, "今日快速输入", is_today=True)
        entry = self.db.row(
            "SELECT * FROM daily_entries WHERE task_id = ? AND entry_date = ?",
            (task_id, self.db.today_iso()),
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["state"], "planned")

    def test_DL_02_snapshot_is_immutable_after_rename(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "原标题")
        day = (date.today() - timedelta(days=5)).isoformat()
        entry_id = self.db.plan_task_for_day(task_id, day)
        self.db.update_task(task_id, title="现标题")
        self.assertEqual(self.db.row("SELECT task_title_snapshot FROM daily_entries WHERE id = ?", (entry_id,))["task_title_snapshot"], "原标题")

    def test_DL_03_04_complete_reopen_summary_retains_fact(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "事实不抹除", is_today=True)
        entry_id = int(self.db.row("SELECT id FROM daily_entries WHERE task_id = ?", (task_id,))["id"])
        self.db.set_daily_entry_completed(entry_id, True)
        self.db.set_daily_entry_completed(entry_id, False)
        summary = self.db.daily_summary(self.db.today_iso())
        self.assertGreaterEqual(int(summary["completed"] or 0), 1)
        self.assertTrue(any(int(row["id"]) == entry_id for row in self.db.completed_entries_on(self.db.today_iso())))

    def test_DL_05_06_07_overdue_carry_is_idempotent(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "需要顺延")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        old_id = self.db.plan_task_for_day(task_id, yesterday)
        overdue = {int(row["id"]) for row in self.db.list_overdue_entries(self.db.today_iso())}
        self.assertIn(old_id, overdue)
        self.assertEqual(self.db.carry_daily_entries((old_id,), self.db.today_iso()), 1)
        self.assertEqual(self.db.carry_daily_entries((old_id,), self.db.today_iso()), 0)
        self.assertEqual(
            int(self.db.row("SELECT COUNT(*) AS n FROM daily_entries WHERE task_id = ? AND entry_date = ?", (task_id, self.db.today_iso()))["n"]),
            1,
        )

    def test_DL_08_batch_carry_skips_existing_target(self) -> None:
        mainline = self.db.current_mainline_id()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        first = self.db.create_task(mainline, "已有今天项")
        second = self.db.create_task(mainline, "没有今天项")
        old_first = self.db.plan_task_for_day(first, yesterday)
        old_second = self.db.plan_task_for_day(second, yesterday)
        self.db.plan_task_for_day(first, self.db.today_iso())
        self.assertEqual(self.db.carry_daily_entries((old_first, old_second), self.db.today_iso()), 2)
        for task_id in (first, second):
            count = self.db.row("SELECT COUNT(*) AS n FROM daily_entries WHERE task_id = ? AND entry_date = ?", (task_id, self.db.today_iso()))
            self.assertEqual(int(count["n"]), 1)

    def test_DL_10_cross_month_and_year_dates(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "跨年")
        for day in ("2025-12-31", "2026-01-01", "2026-02-28"):
            self.assertGreater(self.db.plan_task_for_day(task_id, day), 0)
        dates = self.db.daily_dates()
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertTrue({"2025-12-31", "2026-01-01", "2026-02-28"}.issubset(dates))

    def test_DL_11_refresh_today_flags_does_not_rewrite_history(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "跨日任务")
        old_day = "2030-01-01"
        self.db.today_iso = lambda: old_day  # type: ignore[method-assign]
        self.db.plan_task_for_day(task_id, old_day)
        self.assertEqual(int(self.db.get_task(task_id)["is_today"]), 1)
        self.db.today_iso = lambda: "2030-01-02"  # type: ignore[method-assign]
        self.db.refresh_today_flags()
        self.assertEqual(int(self.db.get_task(task_id)["is_today"]), 0)
        self.assertIsNotNone(self.db.row("SELECT id FROM daily_entries WHERE task_id = ? AND entry_date = ?", (task_id, old_day)))

    def test_DL_12_empty_day_is_safe(self) -> None:
        self.assertEqual(self.db.list_daily_entries("1999-01-01"), [])
        summary = self.db.daily_summary("1999-01-01")
        self.assertEqual(int(summary["total"]), 0)

    def test_DL_13_invalid_date_is_rejected(self) -> None:
        task_id = self.db.create_task(self.db.current_mainline_id(), "非法日期")
        for invalid in ("2026-02-30", "08/13/2026", "", "today"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.db.plan_task_for_day(task_id, invalid)

    def test_CA_01_all_mainlines_and_filter(self) -> None:
        day = "2031-03-05"
        first = self.db.create_mainline("日历甲")
        second = self.db.create_mainline("日历乙")
        for mainline in (first, second):
            task = self.db.create_task(mainline, f"完成于 {mainline}")
            entry = self.db.plan_task_for_day(task, day)
            self.db.set_daily_entry_completed(entry, True)
        self.assertEqual(self.db.completion_days(2031, 3)[day], 2)
        self.assertEqual(self.db.completion_days(2031, 3, first)[day], 1)

    def test_CA_02_03_reopen_and_recomplete_count_once(self) -> None:
        day = self.db.today_iso()
        task = self.db.create_task(self.db.current_mainline_id(), "重复完成", is_today=True)
        entry = int(self.db.row("SELECT id FROM daily_entries WHERE task_id = ? AND entry_date = ?", (task, day))["id"])
        self.db.set_daily_entry_completed(entry, True)
        self.db.set_daily_entry_completed(entry, False)
        self.db.set_daily_entry_completed(entry, True)
        self.assertEqual(sum(1 for row in self.db.completed_entries_on(day) if int(row["id"]) == entry), 1)
        completed_events = self.db.row("SELECT COUNT(*) AS n FROM task_events WHERE daily_entry_id = ? AND event_type = 'completed'", (entry,))
        self.assertEqual(int(completed_events["n"]), 2)


class IdeaTests(TemporaryDatabaseTestCase):
    def test_ID_01_02_unlinked_blank_idea(self) -> None:
        thought_id = self.db.create_thought("一句灵感")
        thought = self.db.get_thought(thought_id)
        self.assertEqual(thought["status"], "未审视")
        self.assertIsNone(thought["mainline_id"])
        self.assertEqual(thought["raw_content"], "")
        self.assertEqual(thought["tags"], "")
        with self.assertRaises(ValueError):
            self.db.create_thought("   ")

    def test_ID_03_stage_events_are_not_duplicated(self) -> None:
        thought = self.db.create_thought("阶段变化")
        self.db.set_thought_stage(thought, "待孵化")
        self.db.set_thought_stage(thought, "待孵化")
        self.assertEqual(len(self.db.thought_review_events(thought)), 1)

    def test_ID_04_invalid_stage_is_rejected(self) -> None:
        thought = self.db.create_thought("非法阶段")
        with self.assertRaises(ValueError):
            self.db.set_thought_stage(thought, "随便看看")
        self.assertEqual(self.db.get_thought(thought)["status"], "未审视")

    def test_ID_05_free_tags_and_progress_clamping(self) -> None:
        thought = self.db.create_thought("自由标签")
        self.db.update_thought(
            thought,
            title="自由标签",
            raw_content="",
            conclusion="",
            evidence="",
            next_step="",
            status="待孵化",
            progress=160,
            mainline_id=None,
            tags="奇怪标签, 🧪, 中文 空格",
        )
        row = self.db.get_thought(thought)
        self.assertEqual(row["tags"], "奇怪标签, 🧪, 中文 空格")
        self.assertEqual(int(row["progress"]), 100)

    def test_ID_06_task_link_is_idempotent(self) -> None:
        thought = self.db.create_thought("关联任务")
        task = self.db.create_task(self.db.current_mainline_id(), "被关联任务")
        self.db.link_task(thought, task)
        self.db.link_task(thought, task)
        self.assertEqual(len(self.db.linked_tasks(thought)), 1)

    def test_ID_07_08_thought_relations_are_safe(self) -> None:
        source = self.db.create_thought("来源")
        target = self.db.create_thought("目标")
        self.db.link_thought(source, target, "启发")
        self.db.link_thought(source, target, "启发")
        self.db.link_thought(source, source, "启发")
        self.db.link_thought(source, target, "无效")
        relations = self.db.thought_relations(source)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["relation"], "启发")

    def test_ID_09_10_convert_linked_and_unlinked_idea_to_task(self) -> None:
        mainline = self.db.create_mainline("灵感转任务主线")
        linked = self.db.create_thought("有关联", mainline_id=mainline)
        unlinked = self.db.create_thought("无关联")
        linked_task = self.db.create_task_from_thought(linked)
        unlinked_task = self.db.create_task_from_thought(unlinked)
        self.assertEqual(int(self.db.get_task(linked_task)["mainline_id"]), mainline)
        self.assertIsNotNone(self.db.get_task(unlinked_task))
        self.assertEqual(len(self.db.linked_tasks(linked)), 1)

    def test_ID_11_execution_progress_changes_stage(self) -> None:
        thought = self.db.create_thought("执行灵感")
        self.db.add_execution_log(thought, action="试一次", result="有结果", blocker="", next_step="再试", progress=-3)
        self.assertEqual(int(self.db.get_thought(thought)["progress"]), 0)
        self.assertEqual(self.db.get_thought(thought)["status"], "正在尝试")
        self.db.add_execution_log(thought, action="完成", result="", blocker="", next_step="", progress=999)
        self.assertEqual(int(self.db.get_thought(thought)["progress"]), 100)
        self.assertEqual(self.db.get_thought(thought)["status"], "已归档")


class MarkdownTests(TemporaryDatabaseTestCase):
    def test_MD_01_02_all_kinds_and_stable_names(self) -> None:
        mainline = self.db.create_mainline("文档主线")
        task = self.db.create_task(mainline, "文档任务", is_today=True)
        thought = self.db.create_thought("文档灵感", mainline_id=mainline)
        log = self.db.add_execution_log(thought, action="记录", result="结果", blocker="", next_step="", progress=20)
        self.markdown.sync_all(self.db)
        paths = [
            self.markdown.path_for("mainline", mainline),
            self.markdown.path_for("task", task),
            self.markdown.path_for("thought", thought),
            self.markdown.path_for("execution", log),
            self.markdown.daily_path(self.db.today_iso()),
        ]
        self.assertTrue(all(path.exists() for path in paths))
        old_task_path = self.markdown.path_for("task", task)
        self.db.update_task(task, title="任务改名")
        self.markdown.sync_all(self.db)
        self.assertEqual(old_task_path, self.markdown.path_for("task", task))
        self.assertIn("任务改名", old_task_path.read_text(encoding="utf-8"))

    def test_MD_03_04_user_content_survives_idempotent_sync(self) -> None:
        task = self.db.create_task(self.db.current_mainline_id(), "保留自由正文")
        self.markdown.sync_all(self.db)
        path = self.markdown.path_for("task", task)
        original = path.read_text(encoding="utf-8")
        user_text = "\n\n## 我的自由记录\n这段文字不能被覆盖。\n"
        path.write_text(original + user_text, encoding="utf-8", newline="\n")
        self.db.update_task(task, title="系统区改名")
        self.markdown.sync_all(self.db)
        once = path.read_text(encoding="utf-8")
        self.markdown.sync_all(self.db)
        twice = path.read_text(encoding="utf-8")
        self.assertEqual(once, twice)
        self.assertIn("这段文字不能被覆盖。", twice)
        self.assertEqual(twice.count(SYSTEM_START), 1)
        self.assertEqual(twice.count(SYSTEM_END), 1)

    def test_MD_05_daily_uses_snapshot(self) -> None:
        task = self.db.create_task(self.db.current_mainline_id(), "历史名字")
        day = "2032-04-03"
        self.db.plan_task_for_day(task, day)
        self.db.update_task(task, title="现在名字")
        self.markdown.sync_all(self.db)
        content = self.markdown.daily_path(day).read_text(encoding="utf-8")
        self.assertIn("历史名字", content)
        self.assertNotIn("现在名字", content)

    def test_MD_06_indexes_reference_existing_files(self) -> None:
        self.markdown.sync_all(self.db)
        index_files = list(self.markdown.root.glob("*.md"))
        self.assertGreater(len(index_files), 0)
        for index in index_files:
            content = index.read_text(encoding="utf-8")
            for relative in [part.split(")", 1)[0] for part in content.split("](")[1:]]:
                target = (index.parent / relative).resolve()
                self.assertTrue(target.exists(), f"{index.name} 引用了不存在的 {relative}")

    def test_MD_07_immediate_write_failure_is_reported(self) -> None:
        self.markdown.sync_all(self.db)
        task = self.db.create_task(self.db.current_mainline_id(), "写盘故障")
        with patch.object(markdown_module.os, "replace", side_effect=OSError("disk-full")):
            with self.assertRaisesRegex(OSError, "disk-full"):
                self.markdown.sync_all(self.db)
        self.assertIsNotNone(self.db.get_task(task), "数据库已保存的对象应保持可辨认")

    def test_MD_07_existing_document_survives_partial_write_failure(self) -> None:
        task = self.db.create_task(self.db.current_mainline_id(), "原子写入保护")
        self.markdown.sync_all(self.db)
        target = self.markdown.path_for("task", task)
        before = target.read_text(encoding="utf-8")
        original_replace = markdown_module.os.replace

        def fail_before_replace(source: Path, destination: Path):
            if Path(destination) == target:
                raise OSError("simulated-interrupted-write")
            return original_replace(source, destination)

        with patch.object(markdown_module.os, "replace", side_effect=fail_before_replace):
            with self.assertRaisesRegex(OSError, "simulated-interrupted-write"):
                self.markdown.sync_all(self.db)
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            before,
            "同步必须先写临时文件再原子替换，不能留下截断文档",
        )
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_MD_08_images_are_copied_and_resolved_inside_workspace(self) -> None:
        task = self.db.create_task(self.db.current_mainline_id(), "带图片的记录")
        self.markdown.sync_all(self.db)
        source = self.base / "截图 示例.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\nimage-payload")

        first, relative = self.markdown.add_image("task", task, source)
        second, second_relative = self.markdown.add_image("task", task, source)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())
        self.assertNotEqual(first, second, "重复插入不能覆盖已有图片")
        self.assertTrue(relative.startswith("../_assets/task/"))
        content = self.markdown.read("task", task) + f"\n![截图]({relative})\n![第二张]({second_relative})\n"
        self.markdown.write_user_edited("task", task, content)
        self.assertEqual(self.markdown.image_paths("task", task, content), [first, second])

        outside = self.base / "outside.png"
        outside.write_bytes(b"outside")
        escaped = content + "\n![越界](../../outside.png)\n"
        self.assertEqual(self.markdown.image_paths("task", task, escaped), [first, second])
        unsupported = self.base / "not-image.txt"
        unsupported.write_text("text", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.markdown.add_image("task", task, unsupported)

    def test_MD_09_clipboard_image_bytes_are_stored_as_attachment(self) -> None:
        task = self.db.create_task(self.db.current_mainline_id(), "粘贴图片")
        self.markdown.sync_all(self.db)
        payload = (Path(__file__).resolve().parents[1] / "assets" / "app-icon.png").read_bytes()

        image, relative = self.markdown.add_image_bytes("task", task, payload)
        self.assertEqual(image.read_bytes(), payload)
        self.assertTrue(relative.startswith("../_assets/task/"))

        content = self.markdown.read("task", task) + f"\n![截图]({relative})\n"
        self.markdown.write_user_edited("task", task, content)
        self.assertEqual(self.markdown.image_paths("task", task, content), [image])

        with self.assertRaisesRegex(ValueError, "没有可用的图片"):
            self.markdown.add_image_bytes("task", task, b"")
        with self.assertRaisesRegex(ValueError, "格式无法识别"):
            self.markdown.add_image_bytes("task", task, b"not-an-image")


class RecoveryTests(TemporaryDatabaseTestCase):
    def test_ER_01_database_lock_fails_in_bounded_time(self) -> None:
        locker = sqlite3.connect(self.db_path)
        try:
            locker.execute("BEGIN EXCLUSIVE")
            self.db.conn.execute("PRAGMA busy_timeout = 100")
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                self.db.create_mainline("锁定期间保存")
            self.assertLess(time.monotonic() - started, 1.5)
            self.db.conn.rollback()
        finally:
            locker.rollback()
            locker.close()

    def test_ER_03_ui_has_global_callback_error_handler(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "flet_app.py").read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"page\.on_error\s*=",
            "Flet 页面需要统一记录并提示运行期回调异常",
        )
        self.assertRegex(source, r"window\.on_event\s*=", "桌面窗口关闭时需要释放数据库")
        self.assertIn("database is locked", source)

    def test_ER_05_duplicate_completion_does_not_duplicate_calendar_item(self) -> None:
        task = self.db.create_task(self.db.current_mainline_id(), "重复点击完成", is_today=True)
        entry = int(self.db.row("SELECT id FROM daily_entries WHERE task_id = ?", (task,))["id"])
        self.db.set_daily_entry_completed(entry, True)
        self.db.set_daily_entry_completed(entry, True)
        matching = [row for row in self.db.completed_entries_on(self.db.today_iso()) if int(row["id"]) == entry]
        self.assertEqual(len(matching), 1)

    def test_ER_06_closed_connection_is_diagnostic(self) -> None:
        self.db.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            self.db.list_mainlines()

    def test_ER_07_close_releases_database_file(self) -> None:
        self.db.close()
        moved = self.base / "moved.db"
        os.replace(self.db_path, moved)
        self.assertTrue(moved.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
