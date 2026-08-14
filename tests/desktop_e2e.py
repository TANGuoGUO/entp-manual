from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import flet as ft

from backup_service import export_workspace, inspect_backup


@dataclass
class E2ECase:
    case_id: str
    feature: str
    status: str
    evidence: str
    level: str = "E2E"


def _walk(root: ft.Control | None):
    if root is None:
        return
    pending = [root]
    visited: set[int] = set()
    while pending:
        control = pending.pop()
        if id(control) in visited:
            continue
        visited.add(id(control))
        yield control
        values = list(getattr(control, "_values", {}).values())
        for name, value in getattr(control, "__dict__", {}).items():
            if name not in {"_values", "_dirty", "_internals", "data"}:
                values.append(value)
        for value in values:
            if isinstance(value, ft.Control):
                pending.append(value)
            elif isinstance(value, (list, tuple)):
                pending.extend(item for item in value if isinstance(item, ft.Control))


def _find(root: ft.Control, control_type, **properties):
    for control in _walk(root):
        if not isinstance(control, control_type):
            continue
        if all(getattr(control, name, None) == value for name, value in properties.items()):
            return control
    raise AssertionError(
        f"找不到控件 {control_type.__name__}，属性={properties}"
    )


class DesktopE2ERunner:
    """Drive the real Flet control callbacks against an isolated workspace."""

    def __init__(self, ui, report_path: Path) -> None:
        self.ui = ui
        self.page = ui.page
        self.report_path = report_path
        self.cases: list[E2ECase] = []
        self.context: dict[str, int | Path] = {}

    async def case(self, case_id: str, feature: str, action, *, level: str = "E2E") -> None:
        try:
            evidence = action()
            if hasattr(evidence, "__await__"):
                evidence = await evidence
            self.cases.append(E2ECase(case_id, feature, "PASS", str(evidence or "通过"), level))
        except Exception as error:
            self.cases.append(
                E2ECase(
                    case_id,
                    feature,
                    "FAIL",
                    f"{error}\n{traceback.format_exc()}",
                    level,
                )
            )

    def _startup(self) -> str:
        assert self.ui.current_mid == self.ui.db.current_mainline_id()
        assert self.ui.content_switcher.content is not None
        total, missing = self.ui.interaction_boundary_audit()
        assert total > 0 and not missing
        return f"当前主线={self.ui.current_mid}，受保护回调={total}"

    def _create_and_switch_mainline(self) -> str:
        self.ui.open_blank_mainline()
        root = self.ui.content_switcher.content
        title = _find(root, ft.TextField, hint_text="主线标题")
        body = next(
            control
            for control in _walk(root)
            if isinstance(control, ft.TextField) and control is not title
        )
        title.value = "E2E 好奇心回流主线"
        body.value = "通过真实编辑页创建，而不是直接写测试 SQL。"
        title.on_blur(SimpleNamespace(control=title))
        row = next(
            item
            for item in self.ui.db.list_mainlines()
            if str(item["name"]) == "E2E 好奇心回流主线"
        )
        mainline_id = int(row["id"])
        self.ui.activate_mainline(mainline_id)
        assert self.ui.db.current_mainline_id() == mainline_id
        assert "通过真实编辑页" in self.ui.markdown.read("mainline", mainline_id)
        self.context["mainline_id"] = mainline_id
        return f"主线 M{mainline_id:04d} 已创建、同步并切换"

    def _quick_add_task(self) -> str:
        title = "E2E 一次点击新增任务"
        self.ui.quick_task_input.value = title
        self.ui.quick_task_input.on_submit(SimpleNamespace(control=self.ui.quick_task_input))
        task = next(item for item in self.ui.db.list_tasks(self.ui.current_mid) if item["title"] == title)
        task_id = int(task["id"])
        assert int(task["is_today"]) == 1
        assert self.ui.markdown.path_for("task", task_id).exists()
        self.context["task_id"] = task_id
        return f"任务 T{task_id:04d} 已进入当前主线和今日账本"

    def _edit_task_detail(self) -> str:
        task_id = int(self.context["task_id"])
        self.ui.select_task(task_id)
        panel = self.ui.detail_holder.content
        title = _find(panel, ft.TextField, value="E2E 一次点击新增任务")
        description = _find(panel, ft.TextField, hint_text="输入内容，记录背景、思路或判断……")
        next_action = _find(panel, ft.TextField, label="下一步最小行动")
        title.value = "E2E 已整理任务"
        description.value = "从界面任务详情保存的背景。"
        next_action.value = "先完成 15 分钟最小实验"
        next_action.on_blur(SimpleNamespace(control=next_action))
        task = self.ui.db.get_task(task_id)
        assert task["title"] == "E2E 已整理任务"
        assert task["next_action"] == "先完成 15 分钟最小实验"
        assert "从界面任务详情" in self.ui.markdown.read("task", task_id)
        return "任务详情标题、正文、最小行动已落库并同步 Markdown"

    def _focus_and_execute_task(self) -> str:
        task_id = int(self.context["task_id"])
        self.ui.select_task(task_id)
        panel = self.ui.detail_holder.content
        focus_button = next(
            control
            for control in _walk(panel)
            if isinstance(control, ft.IconButton) and control.tooltip == "设为当前任务"
        )
        focus_button.on_click(SimpleNamespace(control=focus_button))
        assert int(self.ui.db.get_focus_task(self.ui.current_mid)["id"]) == task_id
        before = len(self.ui.db.task_execution_logs(task_id))
        captured: list[ft.AlertDialog] = []
        original_show_dialog = self.page.show_dialog

        def capture_dialog(dialog) -> None:
            captured.append(dialog)
            original_show_dialog(dialog)

        self.page.show_dialog = capture_dialog
        try:
            self.ui.open_execution_dialog(task_id)
        finally:
            self.page.show_dialog = original_show_dialog
        assert captured, "记录执行按钮没有打开弹窗"
        dialog = captured[-1]
        self.ui._protect_control_tree(dialog)
        action = _find(dialog, ft.TextField, label="我实际做了什么")
        result = _find(dialog, ft.TextField, label="产生了什么结果 / 发现")
        next_action = _find(dialog, ft.TextField, label="接下来最小的一步（可选）")
        action.value = "完成 15 分钟最小实验"
        result.value = "得到可验证结果"
        next_action.value = "整理实验结论"
        save = _find(dialog, ft.FilledButton, content="保存记录")
        save.on_click(SimpleNamespace(control=save))
        assert len(self.ui.db.task_execution_logs(task_id)) == before + 1
        assert "完成 15 分钟最小实验" in self.ui.markdown.read("task", task_id)
        return "通过详情按钮和执行弹窗完成焦点、行动、成果及下一步闭环"

    def _complete_reopen_calendar(self) -> str:
        task_id = int(self.context["task_id"])
        self.ui.select_task(task_id)
        checkbox = next(
            control for control in _walk(self.ui.detail_holder.content) if isinstance(control, ft.Checkbox)
        )
        checkbox.value = True
        checkbox.on_change(SimpleNamespace(control=checkbox))
        today = date.today().isoformat()
        assert any(int(row["task_id"]) == task_id for row in self.ui.db.completed_entries_on(today))
        self.ui.select_task(task_id)
        checkbox = next(
            control for control in _walk(self.ui.detail_holder.content) if isinstance(control, ft.Checkbox)
        )
        checkbox.value = False
        checkbox.on_change(SimpleNamespace(control=checkbox))
        entry = next(
            row for row in self.ui.db.list_daily_entries(today) if int(row["task_id"]) == task_id
        )
        assert entry["state"] == "planned" and int(entry["had_completion"]) == 1
        return "完成进入日历；重新打开后历史完成事实仍保留"

    def _today_inbox_and_carry(self) -> str:
        self.ui.show_view(self.ui.NAV_TODAY)
        self.ui.quick_today_input.value = "E2E 今日收集箱任务"
        self.ui.quick_today_input.on_submit(SimpleNamespace(control=self.ui.quick_today_input))
        inbox = self.ui.db.get_or_create_inbox()
        added = next(row for row in self.ui.db.list_tasks(inbox) if row["title"] == "E2E 今日收集箱任务")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        old_task = self.ui.db.create_task(inbox, "E2E 昨日未完成")
        old_entry = self.ui.db.plan_task_for_day(old_task, yesterday, source="e2e")
        self.ui.show_view(self.ui.NAV_TODAY)
        carry = _find(self.ui.content_switcher.content, ft.TextButton, content="顺延到今天")
        carry.on_click(SimpleNamespace(control=carry))
        carried = self.ui.db.row("SELECT state FROM daily_entries WHERE id = ?", (old_entry,))
        assert carried["state"] == "carried"
        assert any(int(row["task_id"]) == int(added["id"]) for row in self.ui.db.list_daily_entries(date.today().isoformat()))
        return "今日快速新增和昨日顺延均写入不可变每日账本"

    def _calendar_empty_and_month_navigation(self) -> str:
        self.ui.calendar_month = date(2026, 2, 1)
        self.ui.calendar_selected_day = date(2026, 2, 28)
        self.ui.show_view(self.ui.NAV_CALENDAR)
        day = next(
            control
            for control in _walk(self.ui.content_switcher.content)
            if isinstance(control, ft.Container) and control.tooltip == "2026-02-28"
        )
        day.on_click(SimpleNamespace(control=day))
        assert self.ui.calendar_selected_day == date(2026, 2, 28)
        assert self.ui.db.completed_entries_on("2026-02-28") == []
        previous = next(
            control
            for control in _walk(self.ui.content_switcher.content)
            if isinstance(control, ft.IconButton) and control.tooltip == "上个月"
        )
        previous.on_click(SimpleNamespace(control=previous))
        assert self.ui.calendar_month == date(2026, 1, 1)
        return "无记录日期显示空态，月底与跨月计算正常"

    def _capture_and_review_idea(self) -> str:
        self.ui.show_view(self.ui.NAV_CURRENT)
        thought_id = self.ui.save_quick_inspiration(
            "E2E 当前页暂存灵感",
            "默认不属于主线",
        )
        thought = self.ui.db.get_thought(thought_id)
        assert thought["mainline_id"] is None and thought["status"] == "未审视"
        self.ui.show_view(self.ui.NAV_IDEAS)
        self.ui.open_thought_review(thought_id)
        root = self.ui.content_switcher.content
        title = _find(root, ft.TextField, value="E2E 当前页暂存灵感")
        raw = next(
            control
            for control in _walk(root)
            if isinstance(control, ft.TextField) and bool(control.multiline)
        )
        tag = _find(root, ft.TextField, hint_text="＋ 添加标签")
        title.value = "E2E 已审视灵感"
        raw.value = "自由正文，没有预设问题。"
        tag.value = "产品,好奇心"
        tag.on_submit(SimpleNamespace(control=tag))
        hatch = _find(root, ft.IconButton, tooltip="孵化")
        hatch.on_click(SimpleNamespace(control=hatch))
        saved = self.ui.db.get_thought(thought_id)
        assert saved["title"] == "E2E 已审视灵感"
        assert saved["status"] == "待孵化"
        assert "产品" in saved["tags"]
        assert "自由正文" in self.ui.markdown.read("thought", thought_id)
        self.context["thought_id"] = thought_id
        return f"灵感 I{thought_id:04d} 从未审视进入待孵化，标签与自由正文已保存"

    def _idea_relations_and_execution(self) -> str:
        thought_id = int(self.context["thought_id"])
        second = self.ui.db.create_thought("E2E 关联灵感")
        self.ui.db.link_thought(thought_id, second, "启发")
        self.ui.db.link_task(thought_id, int(self.context["task_id"]))
        self.ui.db.add_execution_log(
            thought_id,
            action="验证灵感",
            result="值得继续",
            blocker="",
            next_step="生成任务",
            progress=60,
        )
        generated = self.ui.db.create_task_from_thought(thought_id)
        self.ui._sync_markdown()
        assert self.ui.db.thought_relations(thought_id)
        assert self.ui.db.linked_tasks(thought_id)
        assert self.ui.db.get_task(generated)
        assert self.ui.markdown.path_for("execution", self.ui.db.execution_logs(thought_id)[0]["id"]).exists()
        return "灵感关系、任务关联、执行日志与转任务均完整"

    def _archive_restore_mainline(self) -> str:
        mainline_id = int(self.context["mainline_id"])
        replacement = self.ui.db.create_mainline("E2E 临时切换主线")
        self.ui.activate_mainline(replacement)
        row = next(item for item in self.ui.db.list_mainlines() if int(item["id"]) == mainline_id)
        card = self.ui._vault_mainline_card(row)
        self.ui._protect_control_tree(card)
        archive = _find(card, ft.TextButton, content="归档")
        archive.on_click(SimpleNamespace(control=archive))
        archived = next(row for row in self.ui.db.list_mainlines() if int(row["id"]) == mainline_id)
        assert archived["status"] == "已归档"
        card = self.ui._vault_mainline_card(archived)
        self.ui._protect_control_tree(card)
        restore = _find(card, ft.OutlinedButton, content="恢复主线")
        restore.on_click(SimpleNamespace(control=restore))
        restored = next(row for row in self.ui.db.list_mainlines() if int(row["id"]) == mainline_id)
        assert restored["status"] == "进行中"
        assert self.ui.db.get_task(int(self.context["task_id"])) is not None
        return "主线归档/恢复不删除任务和 Markdown"

    def _markdown_roundtrip(self) -> str:
        task_id = int(self.context["task_id"])
        existing = self.ui.markdown.read("task", task_id)
        self.ui.markdown.write_user_edited(
            "task",
            task_id,
            existing + "\nE2E 用户自由 Markdown 正文。\n",
        )
        self.ui._sync_markdown()
        assert "E2E 用户自由 Markdown 正文" in self.ui.markdown.read("task", task_id)
        return "系统区刷新后用户自由 Markdown 原样保留"

    async def _backup_roundtrip(self) -> str:
        archive = self.report_path.parent / "desktop-e2e.entp.zip"
        before_tasks = len(self.ui.db.list_tasks())
        summary = export_workspace(self.ui.db, self.ui.markdown.root, archive)
        assert summary.tasks == before_tasks
        self.ui.db.create_task(self.ui.current_mid, "E2E 备份后临时任务")
        await self.ui.confirm_import_backup(archive)
        assert not any(row["title"] == "E2E 备份后临时任务" for row in self.ui.db.list_tasks())
        safety = list((self.report_path.parent / "backups").glob("导入前自动备份_*.entp.zip"))
        assert safety and inspect_backup(safety[-1]).tasks == before_tasks + 1
        return "完整导出、导入、导入前安全备份和重连通过"

    def _isolated_failure(self) -> str:
        messages: list[str] = []
        original_notify = self.ui._notify_error
        self.ui._notify_error = messages.append
        original_index = self.ui.active_index

        def fail(_event) -> None:
            self.ui.active_index = self.ui.NAV_CALENDAR
            self.ui.db.conn.execute(
                "INSERT INTO mainlines(name, vision) VALUES ('E2E 不应提交', '')"
            )
            raise RuntimeError("E2E forced isolated failure")

        try:
            self.ui._wrap_event_handler(fail, "E2E 故障注入")(None)
        finally:
            self.ui._notify_error = original_notify
        assert messages and self.ui.active_index == original_index
        assert not any(row["name"] == "E2E 不应提交" for row in self.ui.db.list_mainlines())
        assert not self.ui.db.conn.in_transaction
        return "异常只终止本次动作，事务和导航状态均恢复"

    def _today_sort_and_collapse(self) -> str:
        self.ui.show_view(self.ui.NAV_TODAY)
        root = self.ui.content_switcher.content
        sort_button = next(
            control
            for control in _walk(root)
            if isinstance(control, ft.IconButton)
            and control.tooltip in ("按优先级排序", "恢复默认排序")
        )
        before_sort = self.ui.today_priority_sort
        sort_button.on_click(SimpleNamespace(control=sort_button))
        assert self.ui.today_priority_sort is not before_sort
        root = self.ui.content_switcher.content
        collapse = next(
            control
            for control in _walk(root)
            if isinstance(control, ft.IconButton) and control.tooltip == "收起"
        )
        collapse.on_click(SimpleNamespace(control=collapse))
        assert any(self.ui.today_collapsed.values())
        return "今日分组折叠与优先级排序均通过真实按钮改变页面状态"

    def _empty_input_guards(self) -> str:
        before_tasks = len(self.ui.db.list_tasks())
        self.ui.show_view(self.ui.NAV_CURRENT)
        self.ui.quick_task_input.value = "   "
        self.ui.quick_task_input.on_submit(SimpleNamespace(control=self.ui.quick_task_input))
        assert len(self.ui.db.list_tasks()) == before_tasks
        before_thoughts = len(self.ui.db.list_thoughts())
        self.ui.show_view(self.ui.NAV_IDEAS)
        self.ui.quick_idea_input.value = ""
        self.ui.quick_idea_input.on_submit(SimpleNamespace(control=self.ui.quick_idea_input))
        assert len(self.ui.db.list_thoughts()) == before_thoughts
        assert self.ui.quick_idea_input.error_text == "先写下一句话灵感"
        return "空任务不创建；空灵感就地提示且不污染数据库"

    def _visible_entry_points(self) -> str:
        self.ui.show_view(self.ui.NAV_VAULT)
        vault = self.ui.content_switcher.content
        for label in ("导出全部", "导入备份", "新建主线"):
            assert any(
                isinstance(control, (ft.FilledButton, ft.OutlinedButton))
                and control.content == label
                for control in _walk(vault)
            )
        assert any(
            isinstance(control, ft.IconButton)
            and "Markdown" in str(control.tooltip or "")
            for control in _walk(vault)
        )
        self.ui.show_view(self.ui.NAV_CURRENT)
        assert self.ui.quick_task_input in set(_walk(self.ui.content_switcher.content))
        return "备份、新建主线和对象 Markdown 入口在实际页面可发现"

    def _idea_archive_recycle_bin(self) -> str:
        thought_id = self.ui.db.create_thought("E2E 回收站灵感")
        self.ui.show_view(self.ui.NAV_IDEAS)
        board = self.ui.content_switcher.content
        matching_cards = [
            control
            for control in _walk(board)
            if isinstance(control, ft.Container)
            and any(
                isinstance(child, ft.Text) and child.value == "E2E 回收站灵感"
                for child in _walk(control)
            )
            and any(
                isinstance(child, ft.IconButton) and child.tooltip == "归档"
                for child in _walk(control)
            )
        ]
        card = min(matching_cards, key=lambda control: sum(1 for _ in _walk(control)))
        archive = _find(card, ft.IconButton, tooltip="归档")
        archive.on_click(SimpleNamespace(control=archive))
        assert self.ui.db.get_thought(thought_id)["status"] == "已归档"
        assert not any(
            isinstance(control, ft.Text) and control.value == "E2E 回收站灵感"
            for control in _walk(self.ui.content_switcher.content)
        )

        archived_entry = next(
            control
            for control in _walk(self.ui.content_switcher.content)
            if isinstance(control, ft.TextButton)
            and str(control.content or "").startswith("已归档")
        )
        archived_entry.on_click(SimpleNamespace(control=archived_entry))
        archive_view = self.ui.content_switcher.content
        card = next(
            control
            for control in _walk(archive_view)
            if isinstance(control, ft.Row)
            and any(
                isinstance(child, ft.Text) and child.value == "E2E 回收站灵感"
                for child in _walk(control)
            )
            and any(
                isinstance(child, ft.OutlinedButton) and child.content == "恢复"
                for child in _walk(control)
            )
        )
        restore = _find(card, ft.OutlinedButton, content="恢复")
        restore.on_click(SimpleNamespace(control=restore))
        assert self.ui.db.get_thought(thought_id)["status"] == "未审视"
        return "灵感一键归档后离开候审看板，并可从独立回收站一键恢复"

    async def run(self) -> dict:
        await self.case("E2E-01", "启动与统一异常边界", self._startup)
        await self.case("E2E-02", "主线创建与切换", self._create_and_switch_mainline)
        await self.case("E2E-03", "任务快速新增", self._quick_add_task)
        await self.case("E2E-04", "任务详情自动保存", self._edit_task_detail)
        await self.case("E2E-05", "焦点与现实执行记录", self._focus_and_execute_task)
        await self.case("E2E-06", "完成/重开/完成日历", self._complete_reopen_calendar)
        await self.case("E2E-07", "今日收集箱与过期顺延", self._today_inbox_and_carry)
        await self.case("E2E-08", "日历空状态与跨月", self._calendar_empty_and_month_navigation)
        await self.case("E2E-09", "灵感暂存与审视", self._capture_and_review_idea)
        await self.case(
            "DC-01",
            "灵感关系、执行与转任务数据契约",
            self._idea_relations_and_execution,
            level="DATA_CONTRACT",
        )
        await self.case("E2E-11", "主线归档与恢复", self._archive_restore_mainline)
        await self.case(
            "DC-02",
            "Markdown 自由正文数据契约",
            self._markdown_roundtrip,
            level="DATA_CONTRACT",
        )
        await self.case("E2E-13", "完整导出与导入", self._backup_roundtrip)
        await self.case("E2E-14", "异常隔离与事务回滚", self._isolated_failure)
        await self.case("E2E-15", "今日排序与分组折叠", self._today_sort_and_collapse)
        await self.case("E2E-16", "空输入边界", self._empty_input_guards)
        await self.case("E2E-17", "可发现的核心入口", self._visible_entry_points)
        await self.case("E2E-18", "灵感归档回收站", self._idea_archive_recycle_bin)
        total, missing = self.ui.interaction_boundary_audit()
        coverage_gaps = [
            {
                "id": "GAP-01",
                "feature": "任务优先级编辑",
                "reason": "今日页可以按优先级排序，但当前 Flet 任务详情没有修改优先级的入口",
            },
            {
                "id": "GAP-02",
                "feature": "灵感关联、执行记录与一键转任务",
                "reason": "数据库方法和 Markdown 同步存在，但当前 Flet 灵感详情只暴露状态、标签和正文",
            },
            {
                "id": "GAP-03",
                "feature": "内置 Markdown 源码编辑与实时预览",
                "reason": "旧 Tkinter 入口仍有编辑器；当前 Flet 入口只调用系统外部 Markdown 应用",
            },
            {
                "id": "GAP-04",
                "feature": "系统保存/选择文件窗口",
                "reason": "Windows UI Automation 无法识别 Flutter 控件树；备份内容、确认、恢复与回滚已覆盖，原生文件选择需人工点击",
            },
        ]
        result = {
            "suite": "ENTP Desktop Native E2E",
            "date": date.today().isoformat(),
            "database": str(self.ui.db.path),
            "ui_driver": "Flet native control callbacks",
            "windows_uia": "Flutter window exposes no automatable element tree",
            "callbacks_audited": total,
            "callbacks_unprotected": missing,
            "passed_e2e": sum(
                case.status == "PASS" and case.level == "E2E" for case in self.cases
            ),
            "passed_data_contract": sum(
                case.status == "PASS" and case.level == "DATA_CONTRACT"
                for case in self.cases
            ),
            "failed": sum(case.status == "FAIL" for case in self.cases),
            "coverage_gaps": coverage_gaps,
            "cases": [asdict(case) for case in self.cases],
        }
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result
